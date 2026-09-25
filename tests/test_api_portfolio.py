"""The book's cost, income, tax and risk over HTTP.

The arithmetic behind these four is already covered — test_fees.py,
test_ledger.py, the twelve test_tax_*.py files and test_portfolio.py. What is
tested here is what the API layer promises on top of it:

* a fetch that failed degrades the answer instead of replacing it, and says
  which half is missing rather than reporting a zero;
* an estimate never merges into a figure the ledger booked;
* the tax endpoint follows the account's own jurisdiction — its currency and
  its share-matching rule — and not the caller's `?base=`.

Nothing here touches the network: the ledgers are single-currency so no rate is
ever looked up, and every loader that would fetch is replaced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from yfinance.exceptions import YFRateLimitError

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
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
    """Process-wide TTL memos keyed on (db path, mtime, base) — the right key in
    production and the wrong one across tests, where two books land on the same
    tmp path inside one mtime tick.

    Swept off the module rather than listed by name: a hand-written list is one
    a new loader is forgotten from, and the failure that causes is a test that
    passes alone and reads the previous test's book in the suite — the most
    expensive kind to chase.
    """
    memos = [
        fn
        for fn in vars(loaders).values()
        if callable(fn) and hasattr(fn, "cache_clear")
    ]
    for fn in memos:
        fn.cache_clear()
    yield
    for fn in memos:
        fn.cache_clear()


@pytest.fixture(autouse=True)
def _offline_prices(monkeypatch):
    """The two price loads the tax and positions routes reach for on the side.

    The tax report prices the open book for its foreign-asset lines and the
    positions table asks the basket for today's move; both would go to Yahoo
    from here. An unpriced book and no quotes is the offline answer — tests
    that care about either replace them again.
    """
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "basket_values", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(loaders, "quotes", lambda tickers: {})


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
        ledger.add_many(transactions, path=paths.db)
        return paths

    return write


def trades(note: str = "revolut apple") -> list[Transaction]:
    """Two buys and a sale, all EUR, all with a commission on them."""
    return [
        Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 2.0, note=note),
        Transaction("2024-02-01", "AAPL", "buy", 5, 110.0, "EUR", 1.0, note=note),
        Transaction("2024-03-01", "AAPL", "sell", 4, 130.0, "EUR", 1.5, note=note),
    ]


def bars() -> dict[str, pd.DataFrame]:
    """A daily high/low for each of those trade dates, mid = the traded price.

    Mid equal to the execution makes the spread exactly zero, so any figure the
    endpoint reports other than 0.0 is the endpoint's own arithmetic and not
    the fixture's.
    """
    index = pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"])
    return {
        "AAPL": pd.DataFrame(
            {"High": [101.0, 111.0, 131.0], "Low": [99.0, 109.0, 129.0]}, index=index
        )
    }


# ------------------------------------------------------------------------ fees


def test_fees_report_commission_and_spread_apart(client, book, monkeypatch):
    """Two different kinds of cost, never added up into one figure."""
    book(trades())
    monkeypatch.setattr(loaders, "trade_bars", lambda db, mtime: bars())

    body = client.get("/v1/portfolio/fees", params={"account": EMAIL}, headers=AUTH)
    assert body.status_code == 200
    payload = body.json()
    assert payload["spread_measured"] is True
    assert payload["explicit"] == pytest.approx(4.5)  # 2.00 + 1.00 + 1.50
    assert payload["spread"] == pytest.approx(0.0)  # every fill at the mid
    broker = payload["brokers"][0]
    assert broker["broker"] == "revolut"
    assert broker["trades"] == 3
    assert broker["measured"] == 3 and broker["skipped"] == 0


def test_an_unreachable_yahoo_leaves_the_spread_null_not_zero(
    client, book, monkeypatch
):
    """A spread nobody could measure is not a spread of zero.

    Zero would read as "this book traded at the midpoint", which is a claim
    about execution quality that no data was gathered to support.
    """
    book(trades())

    def throttled(db, mtime):
        raise YFRateLimitError

    monkeypatch.setattr(loaders, "trade_bars", throttled)

    payload = client.get(
        "/v1/portfolio/fees", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["spread_measured"] is False
    assert payload["spread"] is None
    assert payload["brokers"][0]["spread"] is None
    assert payload["brokers"][0]["total"] is None
    # The half the ledger knows on its own survives the failed fetch.
    assert payload["explicit"] == pytest.approx(4.5)


def test_any_spread_failure_degrades_to_the_ledger_half(client, book, monkeypatch):
    """Not just a throttle: whatever breaks the estimate (a malformed frame, an
    FX gap) leaves the commissions standing, as the Streamlit tab does, rather
    than 500-ing the whole tab."""
    book(trades())

    def broken(db, mtime):
        raise KeyError("High")

    monkeypatch.setattr(loaders, "trade_bars", broken)
    body = client.get("/v1/portfolio/fees", params={"account": EMAIL}, headers=AUTH)
    assert body.status_code == 200
    payload = body.json()
    assert payload["spread_measured"] is False and payload["spread"] is None
    assert payload["explicit"] == pytest.approx(4.5)


def test_a_book_that_never_traded_reports_no_brokers(client, book, monkeypatch):
    book([Transaction("2024-01-02", "AAPL", "dividend", 0, 12.0, "EUR", 1.8)])
    monkeypatch.setattr(loaders, "trade_bars", lambda db, mtime: {})
    payload = client.get(
        "/v1/portfolio/fees", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["brokers"] == []
    assert payload["cost_pct"] is None


# ------------------------------------------------------------------- dividends


def test_an_estimate_never_adds_into_what_the_ledger_booked(
    client, book, monkeypatch
):
    """The receipt and the entitlement ride side by side, in separate fields."""
    from stocks.portfolio.dividends import EstimatedYear

    book(
        [
            Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0),
            Transaction("2024-06-01", "AAPL", "dividend", 0, 20.0, "EUR", 3.0),
        ]
    )
    monkeypatch.setattr(
        loaders,
        "dividend_estimates",
        lambda db, mtime, base: (
            {2024: EstimatedYear(year=2024, gross=26.0)},
            [],
            {},
            {2024: 6.0},
        ),
    )

    payload = client.get(
        "/v1/portfolio/dividends", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["booked_total"] == pytest.approx(20.0)
    assert payload["estimated_total"] == pytest.approx(26.0)
    year = payload["years"][0]
    assert year["gross"] == pytest.approx(20.0)
    assert year["withheld"] == pytest.approx(3.0)
    assert year["estimated_gross"] == pytest.approx(26.0)
    assert year["unrecorded"] == pytest.approx(6.0)


def test_a_year_the_ledger_missed_still_gets_a_row(client, book, monkeypatch):
    """An import that carried no dividend row must not read as a year with none.

    The shares were paid whether or not the statement said so; leaving the year
    out entirely is how a broker whose dividends never import stays invisible.
    """
    from stocks.portfolio.dividends import EstimatedYear

    book([Transaction("2023-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0)])
    monkeypatch.setattr(
        loaders,
        "dividend_estimates",
        lambda db, mtime, base: (
            {2023: EstimatedYear(year=2023, gross=9.0)},
            [],
            {},
            {2023: 9.0},
        ),
    )

    payload = client.get(
        "/v1/portfolio/dividends", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert [row["year"] for row in payload["years"]] == [2023]
    row = payload["years"][0]
    assert row["gross"] == 0.0  # nothing was booked…
    assert row["estimated_gross"] == pytest.approx(9.0)  # …and something was owed


def test_a_throttled_estimate_is_null_rather_than_nothing_owed(
    client, book, monkeypatch
):
    def throttled(db, mtime, base):
        raise YFRateLimitError

    book(
        [
            Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0),
            Transaction("2024-06-01", "AAPL", "dividend", 0, 20.0, "EUR", 0.0),
        ]
    )
    monkeypatch.setattr(loaders, "dividend_estimates", throttled)

    payload = client.get(
        "/v1/portfolio/dividends", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["estimates_available"] is False
    assert payload["estimated_total"] is None
    assert payload["forward_annual"] is None
    assert payload["years"][0]["estimated_gross"] is None
    assert payload["booked_total"] == pytest.approx(20.0)  # the receipt stands


# ------------------------------------------------------------------------- tax


def test_tax_follows_the_account_and_not_the_query_string(client, book):
    """`?base=` reports money; it does not move anyone's tax residence.

    The ledger is replayed *at* the jurisdiction's currency, so letting a query
    parameter change it would hand back a basis computed under the wrong rules.
    """
    book(
        [
            Transaction("2023-01-02", "AAPL", "buy", 10, 10.0, "GBP", 0.0),
            Transaction("2024-05-02", "AAPL", "sell", 10, 15.0, "GBP", 0.0),
        ],
        prefs={"currency": "EUR", "tax_residence": "UK"},
    )

    payload = client.get(
        "/v1/portfolio/tax",
        params={"account": EMAIL, "base": "USD"},
        headers=AUTH,
    ).json()
    assert payload["jurisdiction"] == "UK"
    assert payload["resolved"] == "chosen"
    assert payload["currency"] == "GBP"
    assert payload["matching"] == "s104"  # pooled, not the FIFO the rest reports
    # The UK tax year opens on 6 April: a 2 May 2024 disposal is 2024/25.
    assert [p["period"] for p in payload["years"]] == ["2024"]
    assert payload["years"][0]["realized_gain"] == pytest.approx(50.0)
    assert payload["sales"][0]["matched"] in {"s104", "pool", "average"}


def test_an_account_that_named_no_country_is_told_the_rules_are_borrowed(
    client, book
):
    """Spain is the fallback, and a caller has to be able to see that it is one."""
    book(
        [
            Transaction("2023-01-02", "AAPL", "buy", 10, 10.0, "EUR", 0.0),
            Transaction("2024-05-02", "AAPL", "sell", 10, 15.0, "EUR", 0.0),
        ],
        prefs={"currency": "EUR"},
    )
    payload = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["jurisdiction"] == "ES"
    assert payload["resolved"] == "unknown"
    assert payload["currency"] == "EUR"


def test_several_years_come_with_their_total_and_one_year_does_not(client, book):
    """The aggregate the page offers and the API could not serve.

    Summed year by year, never replayed as one long period: brackets restart
    and allowances reset, so a decade run up a single scale would invent a tax
    nobody owes. A book with one tax year gets no aggregate at all — it would
    repeat the view beside it.
    """
    book(
        [
            Transaction("2023-01-02", "AAPL", "buy", 20, 10.0, "EUR", 0.0),
            Transaction("2023-06-15", "AAPL", "sell", 5, 15.0, "EUR", 0.0),
            Transaction("2024-06-15", "AAPL", "sell", 5, 20.0, "EUR", 0.0),
        ],
        prefs={"currency": "EUR", "tax_residence": "ES"},
    )
    payload = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert [p["period"] for p in payload["years"]] == ["2023", "2024"]
    total = payload["all_years"]
    assert total["years"] == [2023, 2024]
    # 5 × (15 − 10) in 2023, 5 × (20 − 10) in 2024.
    assert total["realized_gain"] == pytest.approx(75.0)
    assert total["sales"] == 2
    assert [k["name"] for k in total["kpis"]] == [
        k["name"] for k in payload["years"][0]["kpis"]
    ]


def test_one_tax_year_is_already_all_of_them(client, book):
    book(
        [
            Transaction("2023-01-02", "AAPL", "buy", 20, 10.0, "EUR", 0.0),
            Transaction("2024-06-15", "AAPL", "sell", 5, 20.0, "EUR", 0.0),
        ],
        prefs={"currency": "EUR", "tax_residence": "ES"},
    )
    payload = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["all_years"] is None


def test_months_cover_the_quiet_ones_between_two_sales(client, book):
    """A client charting the monthly view should not have to invent the gaps."""
    book(
        [
            Transaction("2023-01-02", "AAPL", "buy", 20, 10.0, "EUR", 0.0),
            Transaction("2024-01-15", "AAPL", "sell", 5, 15.0, "EUR", 0.0),
            Transaction("2024-04-15", "AAPL", "sell", 5, 16.0, "EUR", 0.0),
        ],
        prefs={"currency": "EUR", "tax_residence": "ES"},
    )
    payload = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert [p["period"] for p in payload["months"]] == [
        "2024-01",
        "2024-02",
        "2024-03",
        "2024-04",
    ]


def test_a_book_with_no_sale_owes_nothing_and_says_so_without_periods(client, book):
    book([Transaction("2024-01-02", "AAPL", "buy", 10, 10.0, "EUR", 0.0)])
    payload = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["years"] == [] and payload["months"] == []
    assert payload["sales"] == []


# ------------------------------------------------------------------------ risk


@dataclass
class _Report:
    """Enough of a PortfolioReport for the route; the real one needs a fetch."""

    weights: dict[str, float]
    meta: dict[str, dict]
    returns: pd.DataFrame
    port_returns: pd.Series
    prices: dict[str, float] = field(default_factory=dict)
    bench_returns: dict[str, pd.Series] = field(default_factory=dict)
    volatility: float = 0.2
    max_drawdown: float = -0.1

    def beta_vs(self, benchmark: str) -> float:
        return 1.25

    def allocation(self, key: str) -> pd.Series:
        from stocks.analysis.portfolio import allocation

        return allocation(self.weights, self.meta, key)


def report() -> _Report:
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    returns = pd.DataFrame(
        {"AAPL": [0.01, -0.02, 0.03], "MSFT": [0.02, -0.01, 0.01]}, index=index
    )
    return _Report(
        weights={"AAPL": 0.75, "MSFT": 0.25},
        meta={
            "AAPL": {"sector": "Technology", "country": "United States",
                     "currency": "USD"},
            "MSFT": {"sector": "Technology", "country": "United States",
                     "currency": "USD"},
        },
        returns=returns,
        port_returns=returns.mean(axis=1),
        bench_returns={"^GSPC": returns["AAPL"]},
    )


def test_risk_draws_the_book_the_basket_and_the_benchmarks_on_one_axis(
    client, book, monkeypatch
):
    """The chart the page could not draw: what the account earned, what today's
    holdings would have earned, and what the index did — rebased to the same
    first day, because three lines from three different zeros compare nothing.
    """
    book(trades())
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    twr = pd.Series([0.01, 0.01, 0.01], index=index)
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: report()
    )
    monkeypatch.setattr(loaders, "custody", lambda db, mtime: {})
    monkeypatch.setattr(
        loaders, "history", lambda db, mtime, base="EUR": (pd.DataFrame(), twr, ["ORGN"])
    )

    curves = client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()["curves"]
    assert curves["dates"] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    # 1% compounded three times, off the window's first day.
    assert curves["portfolio"] == pytest.approx([0.01, 0.0201, 0.030301])
    # The basket is the weighted mean of the two names, compounded.
    assert curves["basket"][0] == pytest.approx(0.015)
    assert set(curves["benchmarks"]) == {"^GSPC"}
    assert curves["benchmarks"]["^GSPC"][0] == pytest.approx(0.01)
    # The names the book could not price ride with the line that hides them.
    assert client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()["missing"] == ["ORGN"]


def test_a_window_with_no_returns_has_no_curves(client, book, monkeypatch):
    """Null, not three empty arrays: a chart with nothing to draw should not be
    drawn, and the client can only know that if the field says so."""
    book(trades())
    empty = report()
    empty.returns = pd.DataFrame()
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: empty
    )
    monkeypatch.setattr(loaders, "custody", lambda db, mtime: {})
    monkeypatch.setattr(
        loaders,
        "history",
        lambda db, mtime, base="EUR": (pd.DataFrame(), pd.Series(dtype=float), []),
    )
    payload = client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["curves"] is None


def test_risk_reports_the_shape_of_the_basket(client, book, monkeypatch):
    book(trades())
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: report()
    )
    monkeypatch.setattr(loaders, "custody", lambda db, mtime: {})

    payload = client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()
    # Since inception by default, as the page opens on it.
    assert payload["period"] == "inception"
    assert payload["top5_weight"] == pytest.approx(1.0)
    # 1 / (0.75^2 + 0.25^2) — a two-name book that behaves like 1.6 equal ones.
    assert payload["effective_names"] == pytest.approx(1.6)
    assert payload["betas"] == {"^GSPC": pytest.approx(1.25)}
    assert payload["allocation"]["sector"] == [
        {"label": "Technology", "weight": pytest.approx(1.0)}
    ]
    assert payload["correlation"]["AAPL"]["AAPL"] == pytest.approx(1.0)


def test_a_single_broker_book_gets_no_broker_split(client, book, monkeypatch):
    """One broker is a 100% slice, which says nothing and costs a whole donut."""
    from stocks.portfolio.custody import Custody

    book(trades())
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: report()
    )
    monkeypatch.setattr(
        loaders,
        "custody",
        lambda db, mtime: {
            "AAPL": {"revolut": Custody("AAPL", "revolut", quantity=10.0)},
            "MSFT": {"revolut": Custody("MSFT", "revolut", quantity=5.0)},
        },
    )
    payload = client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert "broker" not in payload["allocation"]


def test_a_multi_broker_book_gets_the_split_it_earns(client, book, monkeypatch):
    """Two custodians is the case the donut exists for: one name, two homes."""
    from stocks.portfolio.custody import Custody

    book(trades())
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: report()
    )
    monkeypatch.setattr(
        loaders,
        "custody",
        lambda db, mtime: {
            "AAPL": {
                "revolut": Custody("AAPL", "revolut", quantity=5.0),
                "clicktrade": Custody("AAPL", "clicktrade", quantity=5.0),
            },
            "MSFT": {"revolut": Custody("MSFT", "revolut", quantity=5.0)},
        },
    )
    payload = client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()
    split = {row["label"]: row["weight"] for row in payload["allocation"]["broker"]}
    # AAPL's 0.75 halves between the two; MSFT's 0.25 is Revolut's alone.
    assert split["revolut"] == pytest.approx(0.625)
    assert split["clicktrade"] == pytest.approx(0.375)


def test_a_window_nobody_defined_is_refused_rather_than_guessed_at(
    client, book, monkeypatch
):
    """yfinance takes any string and answers an unknown one with an empty frame,
    which would cross the wire as a book with no risk at all."""
    book(trades())
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: report()
    )
    response = client.get(
        "/v1/portfolio/risk",
        params={"account": EMAIL, "period": "3w"},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_an_empty_book_has_no_risk_figures_rather_than_zeroed_ones(
    client, book, monkeypatch
):
    book([Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0)])
    monkeypatch.setattr(
        loaders, "basket_report", lambda db, mtime, base, period: None
    )
    payload = client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["volatility"] is None
    assert payload["effective_names"] is None
    assert payload["weights"] == {}


# --------------------------------------------------- what the Streamlit tab had


def test_tax_years_carry_their_label_and_their_notes(client, book):
    """The UK writes a tax year as "2024/25", and a deferred loss is a sentence
    under the figures — both were the page's and the API had neither."""
    book(
        [
            Transaction("2023-01-02", "AAPL", "buy", 10, 10.0, "GBP", 0.0),
            Transaction("2024-05-02", "AAPL", "sell", 10, 15.0, "GBP", 0.0),
        ],
        prefs={"currency": "GBP", "tax_residence": "UK"},
    )
    year = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()["years"][0]
    assert year["year_label"] == "2024/25"
    assert all(set(n) == {"key", "kwargs"} for n in year["notes"])


def test_a_loss_bought_back_inside_two_months_comes_with_its_note(client, book):
    book(
        [
            Transaction("2024-01-02", "AAPL", "buy", 10, 20.0, "EUR", 0.0),
            Transaction("2024-03-01", "AAPL", "sell", 10, 10.0, "EUR", 0.0),
            Transaction("2024-03-15", "AAPL", "buy", 10, 11.0, "EUR", 0.0),
        ],
        prefs={"currency": "EUR", "tax_residence": "ES"},
    )
    payload = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()
    notes = payload["years"][0]["notes"]
    assert notes[0]["key"] == "deferred_note"
    assert notes[0]["kwargs"] == {"deferred": "100"}
    # A month is a breakdown, not a year: no notes of its own.
    assert all(m["notes"] == [] and m["year_label"] == "" for m in payload["months"])
    # Spain taxes both holding periods alike, so no term on a sale.
    assert payload["sales"][0]["term"] is None


def test_a_jurisdiction_that_splits_the_holding_period_marks_each_sale(client, book):
    book(
        [
            Transaction("2022-01-03", "AAPL", "buy", 10, 10.0, "USD", 0.0),
            Transaction("2024-01-02", "AAPL", "buy", 10, 10.0, "USD", 0.0),
            Transaction("2024-06-03", "AAPL", "sell", 20, 12.0, "USD", 0.0),
        ],
        prefs={"currency": "USD", "tax_residence": "US"},
    )
    sales = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()["sales"]
    assert sorted(s["term"] for s in sales) == ["long", "short"]


def test_foreign_asset_lines_price_the_open_book_cost_where_unpriced(
    client, book, monkeypatch
):
    """Modelo 720 against today's book: a name with no price counts at cost,
    because a threshold measured on half the holdings is the wrong answer."""
    book(trades(), prefs={"currency": "EUR", "tax_residence": "ES"})
    table = pd.DataFrame(
        {"cost": [30_000.0, 25_000.0], "value": [40_000.0, float("nan")]},
        index=pd.Index(["AAPL", "MSFT"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    flags = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()["flags"]
    assert flags == [
        {
            "name": "modelo_720",
            "reportable": True,
            "total_value": pytest.approx(65_000.0),
            "threshold": pytest.approx(50_000.0),
        }
    ]


def test_a_rate_that_failed_leaves_no_foreign_asset_line(client, book, monkeypatch):
    book(trades(), prefs={"currency": "USD", "tax_residence": "ES"})
    table = pd.DataFrame(
        {"cost": [1.0], "value": [2.0]}, index=pd.Index(["AAPL"], name="ticker")
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    monkeypatch.setattr(loaders, "spot_rates", lambda ccys, base="EUR": {})
    payload = client.get(
        "/v1/portfolio/tax", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["flags"] == []


def _history(start: str, days: int):
    index = pd.date_range(start, periods=days, freq="D")
    hist = pd.DataFrame(
        {"injected": 1000.0, "value": 1000.0, "pnl_pct": 0.0}, index=index
    )
    twr = pd.Series(0.001, index=index)
    return hist, twr


def test_performance_is_retaken_from_the_window_start(client, book, monkeypatch):
    """The "real performance" tiles follow the window selector, as the page's
    do — a one-year TWR compounds a year of days, not the book's whole life."""
    book(trades())
    today = pd.Timestamp.today().normalize()
    hist, twr = _history(str((today - pd.Timedelta(days=799)).date()), 800)
    monkeypatch.setattr(
        loaders, "history", lambda db, mtime, base="EUR": (hist, twr, [])
    )
    whole = client.get(
        "/v1/portfolio/performance", params={"account": EMAIL}, headers=AUTH
    ).json()
    year = client.get(
        "/v1/portfolio/performance",
        params={"account": EMAIL, "window": "1y"},
        headers=AUTH,
    ).json()
    assert whole["window"] == "inception" and year["window"] == "1y"
    assert whole["twr_cumulative"] == pytest.approx(1.001**800 - 1)
    assert year["twr_cumulative"] == pytest.approx(1.001**366 - 1, rel=1e-2)
    assert year["start"] > whole["start"]
    # Where the book stands is not a return over anything: same either way.
    assert year["value"] == whole["value"]


def test_a_performance_window_nobody_defined_is_refused(client, book):
    book(trades())
    response = client.get(
        "/v1/portfolio/performance",
        params={"account": EMAIL, "window": "3w"},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_risk_since_inception_starts_at_the_first_trade(client, book, monkeypatch):
    """Returns before the book existed are clipped off the basket, the
    benchmarks and the correlation input alike — and the cached report the
    other windows share is not the one that gets shortened."""
    book(
        [Transaction("2024-01-03", "AAPL", "buy", 10, 100.0, "EUR", 0.0)]
    )
    full = report()
    asked: list[str] = []

    def basket(db, mtime, base, period):
        asked.append(period)
        return full

    monkeypatch.setattr(loaders, "basket_report", basket)
    monkeypatch.setattr(loaders, "custody", lambda db, mtime: {})
    monkeypatch.setattr(
        loaders,
        "history",
        lambda db, mtime, base="EUR": (pd.DataFrame(), pd.Series(dtype=float), []),
    )
    payload = client.get(
        "/v1/portfolio/risk", params={"account": EMAIL}, headers=AUTH
    ).json()
    assert payload["curves"]["dates"] == ["2024-01-03", "2024-01-04"]
    # Fetched over the shortest named window that reaches back that far.
    assert asked and asked[0] in {"2y", "5y", "max"}
    assert len(full.returns) == 3  # the shared report is untouched


def test_positions_carry_todays_move_and_their_custody(client, book, monkeypatch):
    """The Hoy and Bróker columns: the basket's last two closes while the
    exchange is open, the session quote once it shuts — and which accounts
    hold the shares, off the ledger."""
    from stocks.api.routes import portfolio as route
    from stocks.portfolio.custody import Custody

    book(trades())
    table = pd.DataFrame(
        {
            "shares": [10.0, 5.0],
            "ccy": ["EUR", "EUR"],
            "cost": [1000.0, 500.0],
            "value": [1100.0, 600.0],
            "pnl": [100.0, 100.0],
            "pnl_pct": [0.1, 0.2],
        },
        index=pd.Index(["AAPL", "SAN.MC"], name="ticker"),
    )
    frame = pd.DataFrame(
        {"AAPL": [1000.0, 1100.0], "SAN.MC": [500.0, 600.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    monkeypatch.setattr(loaders, "spot_rates", lambda ccys, base="EUR": {"EUR": 1.0})
    monkeypatch.setattr(loaders, "basket_values", lambda *a, **k: frame)
    # AAPL's exchange is shut; SAN.MC's is trading.
    monkeypatch.setattr(route, "market_live", lambda t: t == "SAN.MC")
    monkeypatch.setattr(route, "market_active", lambda t: t == "SAN.MC")
    monkeypatch.setattr(
        loaders, "quotes", lambda tickers: {"AAPL": {"pct": 0.1, "as_of": "x"}}
    )
    monkeypatch.setattr(
        loaders,
        "custody",
        lambda db, mtime: {
            "AAPL": {
                "revolut": Custody("AAPL", "revolut", quantity=6.0),
                "clicktrade": Custody("AAPL", "clicktrade", quantity=4.0),
            },
            "SAN.MC": {"manual": Custody("SAN.MC", "manual", quantity=5.0)},
        },
    )
    rows = {
        r["ticker"]: r
        for r in client.get(
            "/v1/portfolio/positions", params={"account": EMAIL}, headers=AUTH
        ).json()["positions"]
    }
    # Shut: the quote's 10%, the money backed out of today's value.
    assert rows["AAPL"]["day_pct"] == pytest.approx(0.1)
    assert rows["AAPL"]["day"] == pytest.approx(100.0)
    assert rows["AAPL"]["market_active"] is False
    # Open: close to close on the basket.
    assert rows["SAN.MC"]["day"] == pytest.approx(100.0)
    assert rows["SAN.MC"]["day_pct"] == pytest.approx(0.2)
    assert rows["SAN.MC"]["market_active"] is True
    assert [(c["broker"], c["share"]) for c in rows["AAPL"]["custody"]] == [
        ("revolut", pytest.approx(0.6)),
        ("clicktrade", pytest.approx(0.4)),
    ]
    assert rows["AAPL"]["custody"][0]["name"] == "Revolut"
    # The generic bucket is the client's to word.
    assert rows["SAN.MC"]["custody"][0]["name"] == ""


def test_a_throttled_basket_leaves_todays_move_null_not_the_table(
    client, book, monkeypatch
):
    book(trades())
    table = pd.DataFrame(
        {
            "shares": [10.0],
            "ccy": ["EUR"],
            "cost": [1000.0],
            "value": [1100.0],
            "pnl": [100.0],
            "pnl_pct": [0.1],
        },
        index=pd.Index(["AAPL"], name="ticker"),
    )

    def throttled(*a, **k):
        raise YFRateLimitError()

    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    monkeypatch.setattr(loaders, "spot_rates", lambda ccys, base="EUR": {"EUR": 1.0})
    monkeypatch.setattr(loaders, "basket_values", throttled)
    response = client.get(
        "/v1/portfolio/positions", params={"account": EMAIL}, headers=AUTH
    )
    assert response.status_code == 200
    row = response.json()["positions"][0]
    assert row["day"] is None and row["day_pct"] is None
    assert row["value"] == pytest.approx(1100.0)
