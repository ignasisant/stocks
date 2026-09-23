"""The book's daily path over HTTP, and the file it can be taken away as.

The arithmetic is already covered — test_portfolio.py owns `book_history`,
`injected_vs_value` and `time_weighted_returns`, and test_exports.py owns the
CSV. What is tested here is what the API layer promises on top of them:

* the window is clipped *and the return rebased* on the server, because those
  two are not the same operation and a client that sliced locally would draw a
  one-month chart starting at last year's cumulative return;
* a day whose return could not be taken is null, never zero — including the
  book's very first day, which has no prior close to measure against;
* a name with no price series is carried at cost and *said so*, rather than
  quietly leaving the value low;
* the export is the same bytes the Profile page hands back, so the two cannot
  drift apart.

Nothing here touches the network: the ledgers are single-currency so no rate is
ever looked up, and the one loader that would download closes is replaced.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes.portfolio import _ledger_csv
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

# The book starts here and `shares_frame` runs its index to *today*, forward
# filling — so every fixture below prices from this date to now rather than
# stopping at the last trade, which is what a real close download does.
START = "2024-01-02"


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_caches():
    """Process-wide TTL memos keyed on (db path, mtime, base) — the right key in
    production and the wrong one across tests, where two books land on the same
    tmp path inside one mtime tick."""
    memos = (loaders.ledger_state, loaders.held_closes, loaders.history, _ledger_csv)
    for fn in memos:
        fn.cache_clear()
    yield
    for fn in memos:
        fn.cache_clear()


@pytest.fixture
def book(monkeypatch, tmp_path):
    """An account whose ledger can be written per test, in one currency."""
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)

    def write(transactions, prefs: dict | None = None):
        paths.prefs.write_text(json.dumps(prefs or {"currency": "EUR"}))
        if transactions:
            ledger.add_many(transactions, path=paths.db)
        else:
            paths.db.touch()
        return paths

    return write


def closes(prices: dict[str, float]) -> dict[str, pd.Series]:
    """A flat daily close per ticker, from the book's first day to today.

    The shape `analysis.portfolio.load_closes` returns: one named float Series
    per ticker on a DatetimeIndex, tickers with no data simply absent. Flat on
    purpose — a value that never moves makes every figure the endpoint reports
    the endpoint's own arithmetic rather than the fixture's drift.
    """
    days = pd.date_range(START, pd.Timestamp.today().normalize(), freq="D")
    return {
        ticker: pd.Series([price] * len(days), index=days, name=ticker)
        for ticker, price in prices.items()
    }


@pytest.fixture
def priced(monkeypatch):
    """Swap the one loader that would download a year of bars per ticker."""

    def use(prices: dict[str, float]) -> None:
        series = closes(prices)
        monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: series)

    return use


def trades() -> list[Transaction]:
    """One buy, then a second a week later — two flows, so the TWR has work."""
    return [
        Transaction(START, "AAPL", "buy", 10, 100.0, "EUR", 2.0, note="revolut"),
        Transaction("2024-01-09", "AAPL", "buy", 5, 100.0, "EUR", 1.0, note="revolut"),
    ]


def get(client, **params) -> dict:
    response = client.get(
        "/v1/portfolio/history", params={**WHO, **params}, headers=AUTH
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- the series


def test_the_series_is_one_point_a_day_from_the_first_trade_to_today(
    client, book, priced
):
    """A chart's x-axis, not a list of events: the quiet days between two trades
    are points too, or the line jumps over a fortnight nothing happened in."""
    book(trades())
    priced({"AAPL": 100.0})

    payload = get(client)
    assert payload["base"] == "EUR"
    assert payload["window"] == "all"
    assert payload["start"] == START
    assert payload["end"] == str(pd.Timestamp.today().date())

    dates = [p["date"] for p in payload["points"]]
    assert dates == sorted(dates)
    span = (pd.Timestamp.today().normalize() - pd.Timestamp(START)).days + 1
    assert len(dates) == span
    assert len(set(dates)) == span  # no day reported twice


def test_money_put_in_and_what_it_is_worth_are_both_reported(client, book, priced):
    """The pair the chart is: a flat reference line and the value read against
    it. Fees are part of what went in — they left the account too."""
    book(trades())
    priced({"AAPL": 100.0})

    points = {p["date"]: p for p in get(client)["points"]}
    assert points[START]["injected"] == pytest.approx(1002.0)  # 10 x 100 + 2 fee
    assert points[START]["value"] == pytest.approx(1000.0)
    # The second buy lands, and both lines step with it.
    assert points["2024-01-09"]["injected"] == pytest.approx(1503.0)
    assert points["2024-01-09"]["value"] == pytest.approx(1500.0)
    assert points[START]["pnl_pct"] == pytest.approx(1000.0 / 1002.0 - 1)


def test_the_first_day_of_the_book_has_no_return_to_report(client, book, priced):
    """Null, not zero. A daily return needs a prior close to measure against and
    the book's opening day has none — reporting 0% would claim a flat day
    nobody measured, and a chart would draw it."""
    book(trades())
    priced({"AAPL": 100.0})

    points = get(client)["points"]
    assert points[0]["date"] == START
    assert points[0]["twr"] is None
    assert points[1]["twr"] is not None


def test_a_window_clips_the_series_and_rebases_the_return(client, book, priced):
    """The reason this is clipped on the server at all.

    `injected` and `value` are levels: the same day reads the same in any
    window. The TWR is an index that restarts wherever the chart does, so the
    same day reads differently — and a client that fetched `all` and sliced it
    would draw a one-month chart opening at two years of accumulated return.
    """
    book(trades())
    priced({"AAPL": 100.0})

    whole = {p["date"]: p for p in get(client)["points"]}
    month = get(client, window="1m")
    assert month["window"] == "1m"
    assert len(month["points"]) < len(whole)
    # 30 days back from the series' own last day, inclusive of both ends.
    assert len(month["points"]) == 31

    first = month["points"][0]
    assert first["injected"] == pytest.approx(whole[first["date"]]["injected"])
    assert first["value"] == pytest.approx(whole[first["date"]]["value"])
    # Rebased: the window opens on its own first day's return (flat prices, so
    # zero), not on the cumulative one that day carried in the full series —
    # which by then has the second buy's flow-adjustment in it.
    carried = whole[first["date"]]["twr"]
    assert first["twr"] == pytest.approx(0.0)
    assert carried is not None and carried != pytest.approx(0.0)


def test_an_explicit_range_is_honoured_end_to_end(client, book, priced):
    book(trades())
    priced({"AAPL": 100.0})

    payload = get(client, **{"from": "2024-01-05", "to": "2024-01-11"})
    assert payload["window"] == "custom"
    assert payload["start"] == "2024-01-05"
    assert payload["end"] == "2024-01-11"
    assert [p["date"] for p in payload["points"]][0] == "2024-01-05"
    assert len(payload["points"]) == 7


@pytest.mark.parametrize(
    "params",
    [
        {"window": "decade"},  # nobody defined it
        {"window": "1m", "from": "2024-01-05"},  # two answers to one question
        {"from": "2024-06-01", "to": "2024-01-01"},  # backwards
    ],
)
def test_a_window_the_route_cannot_honour_is_refused(client, book, priced, params):
    """Refused rather than guessed at. Silently preferring one of two windows a
    caller named is how a client ships a chart it never asked for."""
    book(trades())
    priced({"AAPL": 100.0})
    response = client.get(
        "/v1/portfolio/history", params={**WHO, **params}, headers=AUTH
    )
    assert response.status_code == 422


def test_a_range_outside_the_book_is_an_empty_series_not_an_error(
    client, book, priced
):
    book(trades())
    priced({"AAPL": 100.0})
    payload = get(client, **{"from": "2000-01-01", "to": "2000-12-31"})
    assert payload["points"] == []
    assert payload["start"] is None and payload["end"] is None


def test_a_book_with_no_transactions_has_no_series(client, book, priced):
    book([])
    priced({})
    payload = get(client)
    assert payload["points"] == []
    assert payload["base"] == "EUR"


# --------------------------------------------------- what could not be priced


def test_a_name_with_no_price_series_is_carried_at_cost_and_disclosed(
    client, book, priced
):
    """Not dropped, and not marked to zero. A held name nobody could price sits
    in the value line at what was paid for it — which keeps `value` comparable
    to `injected` — and `missing` is the only thing that says so."""
    book(
        [
            Transaction(START, "AAPL", "buy", 10, 100.0, "EUR", 0.0, note="revolut"),
            Transaction(START, "ORGN", "buy", 10, 50.0, "EUR", 0.0, note="revolut"),
        ]
    )
    priced({"AAPL": 100.0})  # ORGN delisted: no series came back for it

    payload = get(client)
    assert payload["missing"] == ["ORGN"]
    first = payload["points"][0]
    assert first["injected"] == pytest.approx(1500.0)
    # 1000 marked to market + 500 carried at cost. Dropping ORGN would read as
    # a book down a third on the day it was bought.
    assert first["value"] == pytest.approx(1500.0)


def test_a_day_the_return_priced_below_minus_one_is_null_and_named(
    client, book, priced
):
    """A long-only book cannot lose more than everything, so r <= -100% means
    the day's flow never landed in the value path — an unrecorded split, a
    corporate action. One such sample drags the whole cumulative line negative,
    so the day is excluded from the TWR, reads null rather than zero, and is
    listed where a client can print the caveat."""
    book(
        [
            Transaction(START, "AAPL", "buy", 10, 100.0, "EUR", 0.0, note="revolut"),
            # A thousand euros of stock the price series values at one euro.
            Transaction(
                "2024-01-04", "AAPL", "buy", 1000, 100.0, "EUR", 0.0, note="revolut"
            ),
        ]
    )
    priced({"AAPL": 1.0})

    payload = get(client)
    assert payload["dropped_days"] == ["2024-01-04"]
    broken = next(p for p in payload["points"] if p["date"] == "2024-01-04")
    assert broken["twr"] is None
    # The level lines still report that day: they are facts about the ledger
    # and the price series, not a return anybody could take.
    assert broken["injected"] is not None and broken["value"] is not None


# -------------------------------------------------------------- the CSV file


def test_the_export_is_a_named_attachment_of_the_whole_ledger(client, book):
    book(trades())
    response = client.get(
        "/v1/portfolio/transactions.csv", params=WHO, headers=AUTH
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; ")
    assert "aguait-ledger-" in disposition and disposition.endswith('.csv"')

    lines = response.text.strip().splitlines()
    assert len(lines) == 1 + len(trades())  # a header and a row per transaction
    header = lines[0].split(",")
    assert header[:3] == ["date", "ticker", "action"]
    # Every row also in the reporting currency, at its own trade date's rate.
    assert "amount_eur" in header


def test_the_export_is_the_formatter_the_page_already_uses(client, book):
    """Byte for byte. A second CSV writer on this side would drift the moment
    either grew a column, and the drift would only show up in somebody's
    spreadsheet."""
    from stocks.web.exports import ledger_csv

    paths = book(trades())
    response = client.get(
        "/v1/portfolio/transactions.csv", params=WHO, headers=AUTH
    )
    assert response.content == ledger_csv(paths.db, "EUR")


def test_the_export_follows_the_accounts_own_currency(client, book):
    """The app reckons in the account's reference currency, and an export whose
    amounts are in five native ones is not the book the user sees."""
    book(trades(), prefs={"currency": "USD"})
    body = client.get("/v1/portfolio/transactions.csv", params=WHO, headers=AUTH).text
    assert "amount_usd" in body.splitlines()[0]


def test_a_book_with_nothing_in_it_has_no_file_to_hand_back(client, book):
    """404, not a zero-byte attachment. The page offers no button in this state,
    and handing somebody a file that turns out to be empty is worse than
    telling them there is nothing to take."""
    book([])
    response = client.get(
        "/v1/portfolio/transactions.csv", params=WHO, headers=AUTH
    )
    assert response.status_code == 404
