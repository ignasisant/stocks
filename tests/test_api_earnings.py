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
from stocks.data.earnings import EarningsEvent, EarningsResult
from stocks.portfolio import ledger
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


@pytest.fixture(autouse=True)
def _cold_caches():
    for fn in (loaders.earnings_calendar, loaders.ledger_state, loaders.held):
        fn.cache_clear()
    yield
    for fn in (loaders.earnings_calendar, loaders.ledger_state, loaders.held):
        fn.cache_clear()


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
