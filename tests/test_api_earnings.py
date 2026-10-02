"""The watchlist's reporting calendar over HTTP.

Which dates Yahoo has and how a surprise is computed belongs to
`data.earnings`. What is tested here is what this endpoint decides: that names
which never report are dropped before the fetch and named rather than silently
missing, that the filter sets are the ones the calendar can actually offer, and
that a quarter with nothing to compare reads as null and not as a miss.

Nothing here touches the network: the calendar loader is replaced.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.data.dividends import DividendEvent, DividendHistory
from stocks.data.earnings import EarningsEvent, EarningsResult
from stocks.portfolio import ledger
from stocks.portfolio.dividends import EstimatedPayment
from stocks.portfolio.ledger import Transaction

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


_CACHED = (
    loaders.earnings_calendar,
    loaders.ledger_state,
    loaders.held,
    loaders.dividend_payments,
    loaders.ex_dividends,
    loaders.dividend_histories,
)


@pytest.fixture(autouse=True)
def _cold_caches():
    for fn in _CACHED:
        fn.cache_clear()
    yield
    for fn in _CACHED:
        fn.cache_clear()


@pytest.fixture(autouse=True)
def _no_dividends(monkeypatch):
    """A book that pays nothing, unless a test says otherwise — offline."""
    monkeypatch.setattr(loaders, "dividend_payments", lambda db, mtime, base: [])
    monkeypatch.setattr(loaders, "ex_dividends", lambda tickers: [])
    monkeypatch.setattr(loaders, "dividend_histories", lambda tickers: {})


# A dollar is 0.90 euro on every past day and 0.80 today, so a test can tell
# which rate an amount was converted at.
USD_PAST, USD_TODAY = 0.90, 0.80


@pytest.fixture(autouse=True)
def _fixed_fx(monkeypatch):
    from stocks.data import fx

    def rate_on(day, base, quote):
        if base.upper() == quote.upper():
            return 1.0
        return USD_TODAY if str(day) == date.today().isoformat() else USD_PAST

    monkeypatch.setattr(fx, "prefetch", lambda pairs, quote="EUR": None)
    monkeypatch.setattr(fx, "rate_on", rate_on)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(
        "watchlist:\n"
        "  - ticker: AAPL\n"
        "    favorite: true\n"
        "    tags: [Tech]\n"
        "  - ticker: MSFT\n"
        "    tags: [Tech]\n"
        "  - ticker: BTC-EUR\n"  # a coin never reports
    )
    ledger.add_many(
        [Transaction("2024-01-02", "MSFT", "buy", 5, 200.0, "EUR", 1.0)],
        path=paths.db,
    )
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    return paths


@pytest.fixture
def calendar(monkeypatch):
    """One print due next week and one that already landed."""
    soon = date.today() + timedelta(days=6)
    past = date.today() - timedelta(days=40)
    events = [EarningsEvent(ticker="AAPL", date=soon, days_until=6)]
    results = [
        EarningsResult(
            ticker="MSFT",
            date=past,
            eps_estimate=2.0,
            reported_eps=2.4,
            surprise_pct=20.0,
        ),
        # Nothing to compare: a date, and no figures on either side of it.
        EarningsResult(ticker="AAPL", date=past),
    ]
    monkeypatch.setattr(
        loaders, "earnings_calendar", lambda tickers: (events, results)
    )
    return events, results


def test_a_coin_is_named_rather_than_quietly_missing(client, account, calendar):
    """A watchlist entry absent from the calendar with no explanation reads as
    a bug in the calendar."""
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["skipped"] == ["BTC-EUR"]


def test_names_that_never_report_are_dropped_before_the_fetch(
    client, account, monkeypatch
):
    """Asking Yahoo about a coin spends a request on the answer "no dates"."""
    asked: list[tuple[str, ...]] = []

    def record(tickers):
        asked.append(tickers)
        return [], []

    monkeypatch.setattr(loaders, "earnings_calendar", record)
    client.get("/v1/earnings", params={"account": EMAIL}, headers=AUTH)
    assert asked == [("AAPL", "MSFT")]


def test_the_filter_sets_are_the_ones_the_calendar_can_offer(
    client, account, calendar
):
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["groups"]["portfolio"] == ["MSFT"]  # the only open position
    assert payload["groups"]["favorites"] == ["AAPL"]
    assert payload["groups"]["Tech"] == ["AAPL", "MSFT"]


def test_an_empty_group_is_left_out_rather_than_offered(client, account, calendar):
    """A pill that filters to nothing is a pill nobody should be able to press."""
    account.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert "favorites" not in payload["groups"]
    assert "Tech" not in payload["groups"]


def test_a_quarter_with_nothing_to_compare_is_null_and_not_a_miss(
    client, account, calendar
):
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    by_ticker = {row["ticker"]: row for row in payload["results"]}
    assert by_ticker["MSFT"]["beat"] is True
    assert by_ticker["MSFT"]["surprise_pct"] == pytest.approx(20.0)
    assert by_ticker["AAPL"]["beat"] is None
    assert by_ticker["AAPL"]["eps_estimate"] is None


def test_an_upcoming_print_carries_the_days_left(client, account, calendar):
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["upcoming"][0]["ticker"] == "AAPL"
    assert payload["upcoming"][0]["days_until"] == 6


def test_a_watchlist_of_nothing_but_coins_asks_yahoo_nothing(
    client, account, monkeypatch
):
    account.watchlist.write_text("watchlist:\n  - ticker: BTC-EUR\n")
    loaders.earnings_calendar.cache_clear()
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["upcoming"] == [] and payload["results"] == []
    assert payload["skipped"] == ["BTC-EUR"]


# ------------------------------------------------------------ names and logos
# The house rule is that a ticker on screen is a logo and a link, never a bare
# symbol. Per-ticker profiles would make a calendar of twenty names twenty
# requests, which is how a page gets itself rate limited — hence the batch.


def test_a_list_of_tickers_gets_its_names_and_logos_in_one_call(
    client, account, monkeypatch
):
    monkeypatch.setattr(loaders, "company_name", lambda t, w: f"{t} Inc")
    monkeypatch.setattr(loaders, "logo", lambda t: f"/logo/{t}.png")
    monkeypatch.setattr(loaders, "display_symbol", lambda t: t)
    payload = client.get(
        "/v1/market/profiles",
        params={"account": EMAIL, "tickers": "aapl,msft,aapl"},
        headers=AUTH,
    ).json()
    # Asked order, deduplicated: a caller drawing a table wants its own order
    # back, not a sorted one it has to re-join against.
    assert [p["ticker"] for p in payload["profiles"]] == ["AAPL", "MSFT"]
    assert payload["profiles"][0]["name"] == "AAPL Inc"
    assert payload["profiles"][0]["logo"] == "/logo/AAPL.png"


def test_a_name_nobody_knows_is_empty_rather_than_invented(
    client, account, monkeypatch
):
    monkeypatch.setattr(loaders, "company_name", lambda t, w: None)
    monkeypatch.setattr(loaders, "logo", lambda t: None)
    monkeypatch.setattr(loaders, "display_symbol", lambda t: t)
    payload = client.get(
        "/v1/market/profiles",
        params={"account": EMAIL, "tickers": "ZZZZ"},
        headers=AUTH,
    ).json()
    assert payload["profiles"][0]["name"] == ""
    assert payload["profiles"][0]["logo"] is None


def test_an_unbounded_batch_of_names_is_refused(client, account):
    response = client.get(
        "/v1/market/profiles",
        params={"account": EMAIL, "tickers": ",".join(f"T{i}" for i in range(60))},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_tax_deadlines_follow_the_chosen_residence(client, account, calendar):
    """The calendar carries the filing dates of wherever the account is taxed."""
    accounts.update_prefs(account.prefs, {"tax_residence": "UK"})
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["jurisdiction"] == "UK"
    keys = {d["key"] for d in payload["tax_deadlines"]}
    assert keys <= {"uk_self_assessment", "uk_payment_on_account"}
    assert keys
    for deadline in payload["tax_deadlines"]:
        assert deadline["remind"] == (0 <= deadline["days_until"] <= 30)


def test_an_unset_residence_gets_the_spanish_calendar(client, account, calendar):
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["jurisdiction"] == "ES"
    assert any(d["key"] == "es_renta" for d in payload["tax_deadlines"])


# ------------------------------------------------------------------ dividends
# The book's ex-dates ride the same response: the past ones its shares were
# owed, and the next one Yahoo has declared for each open position.


def test_a_past_ex_date_carries_the_shares_it_paid_on(client, account, monkeypatch):
    went_ex = (date.today() - timedelta(days=20)).isoformat()
    monkeypatch.setattr(
        loaders,
        "dividend_payments",
        lambda db, mtime, base: [EstimatedPayment("MSFT", went_ex, 0.83, 5, "USD")],
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["dividends"] == [
        {
            "ticker": "MSFT",
            "date": went_ex,
            "days_until": -20,
            "per_share": pytest.approx(0.83),
            "shares": 5,
            "amount": pytest.approx(4.15),
            "currency": "USD",
            "projected": False,
            "base_currency": "EUR",
            "amount_base": pytest.approx(4.15 * USD_PAST),
            "withholding": None,
            "withholding_basis": None,
        }
    ]


def test_a_declared_ex_date_is_priced_on_todays_position(client, account, monkeypatch):
    """The amount is a guess at the last payment's rate, on the shares held now."""
    ahead = date.today() + timedelta(days=9)
    asked: list[tuple[str, ...]] = []

    def declared(tickers):
        asked.append(tickers)
        return [DividendEvent("MSFT", ahead, 9, 0.91, "USD")]

    monkeypatch.setattr(loaders, "ex_dividends", declared)
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert asked == [("MSFT",)]  # open positions only, not the watchlist
    (row,) = payload["dividends"]
    assert row["date"] == ahead.isoformat() and row["days_until"] == 9
    assert row["shares"] == 5
    assert row["amount"] == pytest.approx(4.55)
    # Not paid yet, so today's rate is the only one it has.
    assert row["amount_base"] == pytest.approx(4.55 * USD_TODAY)


def test_withholding_is_read_off_the_books_own_statements(client, account, monkeypatch):
    """The name's own booked withholding first, then its currency's; a fee of
    zero is a statement that printed none, not a 0% to promise."""
    ahead = date.today() + timedelta(days=9)
    ledger.add_many(
        [
            Transaction("2024-01-02", "AAPL", "buy", 3, 150.0, "USD", 1.0),
            # MSFT's own: 15% on the latest booked payment, zeros skipped.
            Transaction("2025-06-12", "MSFT", "dividend", 0, 4.0, "USD", 0.6),
            Transaction("2025-09-11", "MSFT", "dividend", 0, 4.0, "USD", 0.0),
            # Another dollar payer at 30%, for AAPL to borrow with MSFT's.
            Transaction("2025-05-15", "KO", "dividend", 0, 10.0, "USD", 3.0),
        ],
        path=account.db,
    )
    monkeypatch.setattr(
        loaders,
        "ex_dividends",
        lambda t: [
            DividendEvent("MSFT", ahead, 9, 0.91, "USD"),
            DividendEvent("AAPL", ahead, 9, 0.26, "USD"),
        ],
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    rows = {d["ticker"]: d for d in payload["dividends"]}
    assert rows["MSFT"]["withholding"] == pytest.approx(0.15)
    assert rows["MSFT"]["withholding_basis"] == "ticker"
    assert rows["AAPL"]["withholding"] == pytest.approx(3.6 / 14.0)
    assert rows["AAPL"]["withholding_basis"] == "currency"


def test_an_fx_outage_costs_the_conversion_not_the_dividend(client, account, monkeypatch):
    from stocks.data import fx

    def down(day, base, quote):
        raise ConnectionError("rate source down")

    monkeypatch.setattr(fx, "rate_on", down)
    ahead = date.today() + timedelta(days=9)
    monkeypatch.setattr(
        loaders, "ex_dividends", lambda t: [DividendEvent("MSFT", ahead, 9, 0.91, "USD")]
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    (row,) = payload["dividends"]
    assert row["amount"] == pytest.approx(4.55)
    assert row["amount_base"] is None and row["base_currency"] == "EUR"


def test_an_ex_date_of_today_is_drawn_once(client, account, monkeypatch):
    """History runs through today, and so does the declared date: one chip."""
    today = date.today()
    monkeypatch.setattr(
        loaders,
        "dividend_payments",
        lambda db, mtime, base: [
            EstimatedPayment("MSFT", today.isoformat(), 0.83, 5, "USD")
        ],
    )
    monkeypatch.setattr(
        loaders, "ex_dividends", lambda t: [DividendEvent("MSFT", today, 0, 0.83, "USD")]
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert len(payload["dividends"]) == 1


def test_ex_dates_older_than_two_years_are_left_out(client, account, monkeypatch):
    old = (date.today() - timedelta(days=800)).isoformat()
    monkeypatch.setattr(
        loaders,
        "dividend_payments",
        lambda db, mtime, base: [EstimatedPayment("MSFT", old, 0.5, 5, "USD")],
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["dividends"] == []


def test_a_throttled_yahoo_costs_the_chips_not_the_calendar(
    client, account, calendar, monkeypatch
):
    from yfinance.exceptions import YFRateLimitError

    def throttled(*args):
        raise YFRateLimitError()

    monkeypatch.setattr(loaders, "dividend_payments", throttled)
    monkeypatch.setattr(loaders, "ex_dividends", throttled)
    monkeypatch.setattr(loaders, "dividend_histories", throttled)
    response = client.get("/v1/earnings", params={"account": EMAIL}, headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert payload["dividends"] == []
    assert payload["upcoming"][0]["ticker"] == "AAPL"


def _quarterly(ticker: str = "MSFT") -> DividendHistory:
    """Four payments over the last year, the latest raised: a quarterly payer."""
    today = date.today()
    days = (300, 209, 118, 27)
    amounts = (0.83, 0.83, 0.83, 0.91)
    return DividendHistory(
        ticker,
        tuple(
            ((today - timedelta(days=d)).isoformat(), a)
            for d, a in zip(days, amounts, strict=True)
        ),
        "USD",
    )


def test_last_years_schedule_fills_the_year_ahead(client, account, monkeypatch):
    """Yahoo declares weeks out; the rest of the year is last year's dates."""
    monkeypatch.setattr(loaders, "dividend_histories", lambda t: {"MSFT": _quarterly()})
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    ahead = [d for d in payload["dividends"] if d["projected"]]
    assert [d["days_until"] for d in ahead] == [64, 155, 246, 337]
    # A quarterly payer is guessed at its latest rate, on today's shares.
    assert [d["per_share"] for d in ahead] == [pytest.approx(0.91)] * 4
    assert [d["amount"] for d in ahead] == [pytest.approx(4.55)] * 4


def test_a_declared_ex_date_replaces_its_guess(client, account, monkeypatch):
    declared = date.today() + timedelta(days=60)
    monkeypatch.setattr(loaders, "dividend_histories", lambda t: {"MSFT": _quarterly()})
    event = DividendEvent("MSFT", declared, 60, 0.91, "USD")
    monkeypatch.setattr(loaders, "ex_dividends", lambda t: [event])
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    ahead = [(d["days_until"], d["projected"]) for d in payload["dividends"]]
    assert ahead == [(60, False), (155, True), (246, True), (337, True)]


# ---------------------------------------------------------- repurchase windows
# A loss sale under a rule that blocks it on a quick buy-back: the calendar
# marks the day buying it again stops costing the deduction.


def test_a_loss_sale_marks_the_day_a_buy_back_stops_blocking_it(client, account):
    sold = date.today() - timedelta(days=10)
    ledger.add_many(
        [Transaction(sold.isoformat(), "MSFT", "sell", 2, 150.0, "EUR", 1.0)],
        path=account.db,
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    (window,) = payload["repurchase_windows"]
    assert window["ticker"] == "MSFT" and window["window"] == "2m"
    assert window["sell_date"] == sold.isoformat()
    assert window["date"] > date.today().isoformat()
    # 2 × 50 down, plus the sale's fee and the sold shares' part of the buy's.
    assert window["loss"] == pytest.approx(101.4) and window["currency"] == "EUR"


def test_a_loss_already_blocked_has_no_window_left_to_wait_on(client, account):
    sold = date.today() - timedelta(days=10)
    back = sold + timedelta(days=5)
    ledger.add_many(
        [
            Transaction(sold.isoformat(), "MSFT", "sell", 2, 150.0, "EUR", 1.0),
            Transaction(back.isoformat(), "MSFT", "buy", 2, 155.0, "EUR", 1.0),
        ],
        path=account.db,
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["repurchase_windows"] == []


def test_a_country_without_the_rule_marks_nothing(client, account):
    accounts.update_prefs(account.prefs, {"tax_residence": "DE"})
    sold = date.today() - timedelta(days=10)
    ledger.add_many(
        [Transaction(sold.isoformat(), "MSFT", "sell", 2, 150.0, "EUR", 1.0)],
        path=account.db,
    )
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["repurchase_windows"] == []


# -------------------------------------------------------------- central banks


def test_the_rate_decisions_ride_along_oldest_first(client, account):
    payload = client.get(
        "/v1/earnings", params={"account": EMAIL}, headers=AUTH
    ).json()
    banks = payload["central_banks"]
    assert {b["bank"] for b in banks} == {"fed", "ecb"}
    assert [b["date"] for b in banks] == sorted(b["date"] for b in banks)
    for row in banks:
        assert row["days_until"] == (date.fromisoformat(row["date"]) - date.today()).days

