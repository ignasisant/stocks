"""One past print over HTTP: `GET /earnings/{symbol}/result`.

How a quarter is matched to a print, how a YoY guards a negative base and how
consensus is folded are `data.earnings` / `data.estimates`' business and tested
there. What this endpoint decides, and what is pinned here:

* the matched quarter's comparisons arrive computed (YoY, bps, TTM), so the
  React dialog prints the same numbers as the Streamlit one without re-deriving
  them;
* "not published yet" and "no statements at all" are told apart;
* a failed statement fetch keeps the headline and says `unavailable`, rather
  than failing the whole dialog;
* a date with no print answers the bare header and fetches nothing further.

Nothing here touches the network: every loader and fetch is replaced.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from yfinance.exceptions import YFRateLimitError

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes import earnings as route
from stocks.data.earnings import EarningsResult, Quarter
from stocks.data.estimates import RawEstimates

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PRINT = date(2026, 7, 30)


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_caches():
    caches = (route._reaction, route._statements)
    for fn in caches:
        fn.cache_clear()
    yield
    for fn in caches:
        fn.cache_clear()


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: MSFT\n")
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "company_name", lambda ticker, wl: "Microsoft")
    monkeypatch.setattr(loaders, "logo", lambda ticker: "/static/logos/msft.png")
    return paths


def _quarter(end: date, revenue: float, gross: float, net: float, shares: float):
    return Quarter(
        end=end,
        revenue=revenue,
        gross_profit=gross,
        operating_income=revenue * 0.4,
        net_income=net,
        pretax_income=net * 1.25,
        tax_provision=net * 0.25,
        rnd=revenue * 0.1,
        diluted_eps=2.0,
        diluted_shares=shares,
    )


# Newest first, as `fetch_quarters` returns them: the June quarter is the one a
# 30 July print reports on, and June a year back is its YoY base.
QUARTERS = [
    _quarter(date(2026, 6, 30), 120.0, 84.0, 30.0, 98.0),
    _quarter(date(2026, 3, 31), 110.0, 75.0, 26.0, 99.0),
    _quarter(date(2025, 12, 31), 105.0, 70.0, 25.0, 99.5),
    _quarter(date(2025, 9, 30), 102.0, 68.0, 24.0, 99.8),
    _quarter(date(2025, 6, 30), 100.0, 65.0, 20.0, 100.0),
]


def _estimates() -> RawEstimates:
    frame = pd.DataFrame(
        {
            "avg": [2.5, 2.6, 9.0, 10.0],
            "low": [2.2, 2.3, 8.5, 9.0],
            "high": [2.8, 2.9, 9.5, 11.0],
            "growth": [0.1, 0.12, 0.1, 0.11],
            "numberOfAnalysts": [30, 28, 40, 38],
            "currency": ["USD"] * 4,
        },
        index=["0q", "+1q", "0y", "+1y"],
    )
    return RawEstimates(
        ticker="MSFT", earnings_estimate=frame, revenue_estimate=frame * 1
    )


@pytest.fixture
def feeds(monkeypatch):
    history = [
        EarningsResult("MSFT", date(2026, 4, 28), 1.9, 2.0, 5.26),
        EarningsResult("MSFT", PRINT, 2.2, 2.4, 9.09),
    ]
    monkeypatch.setattr(loaders, "earnings", lambda ticker: ([], history))
    monkeypatch.setattr(route, "price_reaction", lambda ticker, day: 4.5)
    monkeypatch.setattr(route, "fetch_quarters", lambda ticker: QUARTERS)
    monkeypatch.setattr(route, "fetch_statement_currency", lambda ticker: "USD")
    monkeypatch.setattr(loaders, "estimates", lambda ticker: _estimates())


def _get(client, symbol="msft", day=PRINT):
    return client.get(
        f"/v1/earnings/{symbol}/result",
        params={"account": EMAIL, "date": day.isoformat()},
        headers=AUTH,
    )


def test_the_matched_quarter_arrives_with_its_comparisons(client, account, feeds):
    body = _get(client).json()
    assert body["ticker"] == "MSFT"
    assert body["name"] == "Microsoft"
    assert body["result"]["reported_eps"] == 2.4
    assert body["price_reaction"] == 4.5
    assert body["quarter_state"] == "matched"
    assert body["currency_prefix"] == "$"

    breakdown = body["breakdown"]
    assert breakdown["quarter"]["end"] == "2026-06-30"
    assert breakdown["quarter"]["revenue_yoy"] == pytest.approx(0.2)
    assert breakdown["quarter"]["revenue_qoq"] == pytest.approx(120 / 110 - 1)
    assert breakdown["revenue_ttm"] == pytest.approx(120 + 110 + 105 + 102)
    assert breakdown["net_income_yoy"] == pytest.approx(0.5)
    assert breakdown["shares_yoy"] == pytest.approx(-0.02)
    # 70% gross against 65% a year back.
    assert breakdown["gross_margin_bps"] == pytest.approx(500)
    assert body["eps_gaap_gap"] == pytest.approx(0.4)
    assert len(body["trend"]) == 5


def test_history_is_newest_first(client, account, feeds):
    body = _get(client).json()
    assert [r["date"] for r in body["history"]] == ["2026-07-30", "2026-04-28"]


def test_consensus_is_the_next_quarter_plus_every_known_period(
    client, account, feeds
):
    body = _get(client).json()
    assert body["outlook"]["period"] == "+1q"
    assert body["outlook"]["eps_analysts"] == 28
    assert [p["period"] for p in body["outlook_periods"]] == ["0q", "+1q", "0y", "+1y"]


def test_a_quarter_not_filed_yet_is_pending_not_missing(
    client, account, feeds, monkeypatch
):
    """Statements exist, just not this quarter's: the dialog says 'soon', not
    'this company files nothing'."""
    monkeypatch.setattr(route, "fetch_quarters", lambda ticker: QUARTERS[1:])
    body = _get(client).json()
    assert body["quarter_state"] == "pending"
    assert body["breakdown"] is None
    assert body["eps_gaap_gap"] is None


def test_no_statements_at_all_reads_none(client, account, feeds, monkeypatch):
    monkeypatch.setattr(route, "fetch_quarters", lambda ticker: [])
    body = _get(client).json()
    assert body["quarter_state"] == "none"
    assert body["currency"] is None


def test_a_rate_limit_keeps_the_headline(client, account, feeds, monkeypatch):
    """The Streamlit dialog toasts and keeps its tiles; so does this."""

    def throttled(ticker):
        raise YFRateLimitError()

    monkeypatch.setattr(route, "fetch_quarters", throttled)
    response = _get(client)
    assert response.status_code == 200
    body = response.json()
    assert body["unavailable"] is True
    assert body["result"]["reported_eps"] == 2.4
    assert body["breakdown"] is None


def test_a_rate_limit_is_not_cached_as_no_statements(
    client, account, feeds, monkeypatch
):
    def throttled(ticker):
        raise YFRateLimitError()

    monkeypatch.setattr(route, "fetch_quarters", throttled)
    _get(client)
    monkeypatch.setattr(route, "fetch_quarters", lambda ticker: QUARTERS)
    assert _get(client).json()["quarter_state"] == "matched"


def test_a_date_with_no_print_fetches_nothing_more(
    client, account, feeds, monkeypatch
):
    def boom(*args, **kwargs):
        raise AssertionError("fetched a breakdown for a print that does not exist")

    monkeypatch.setattr(route, "fetch_quarters", boom)
    monkeypatch.setattr(route, "price_reaction", boom)
    body = _get(client, day=date(2026, 1, 5)).json()
    assert body["result"] is None
    assert body["history"]  # the record still ships
    assert body["name"] == "Microsoft"


def test_a_malformed_date_is_refused(client, account, feeds):
    response = client.get(
        "/v1/earnings/MSFT/result",
        params={"account": EMAIL, "date": "last tuesday"},
        headers=AUTH,
    )
    assert response.status_code == 422
