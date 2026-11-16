"""An ISIN nothing has placed is no symbol, and the ticker page still answers.

A row stored under its ISIN (a MyInvestor or DEGIRO fund) charts once a search
places it on a line. Until then `resolve` hands the ISIN back, and yfinance
runs its own ISIN search in `yf.Ticker(...)`'s constructor and raises
"Invalid ISIN number" when it finds nothing. Prod 2026-11-13: one such fund
answered ten of the ticker page's routes with a 500 each.

Nothing here touches the network: every `yf.Ticker` is the fake below.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stocks import loaders
from stocks.api.app import app as fastapi_app
from stocks.data import fetch, funds
from stocks.data.symbols import is_isin
from tests.patching import patch_loaders

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ISIN = "IE0000000000"


class _IsinRefusingYahoo:
    """`yf.Ticker` as yfinance builds one: an ISIN it cannot map raises."""

    asked: list[str] = []

    def __init__(self, symbol, session=None):
        if is_isin(symbol):
            _IsinRefusingYahoo.asked.append(symbol)
            raise ValueError(f"Invalid ISIN number: {symbol}")
        self.ticker = symbol

    def __getattr__(self, name):
        raise ConnectionError("network is off in tests: yfinance")


@pytest.fixture
def no_isin_search(monkeypatch):
    import yfinance

    _IsinRefusingYahoo.asked = []
    monkeypatch.setattr(yfinance, "Ticker", _IsinRefusingYahoo)
    monkeypatch.setattr(fetch.yf, "Ticker", _IsinRefusingYahoo)
    # Offline answers for what the page asks besides Yahoo: no fund kind
    # learned, no closed-end verdict from EDGAR.
    monkeypatch.setattr(funds, "quote_type", lambda t, fetch=True: None)
    patch_loaders(monkeypatch, "is_closed_end", lambda t, fetch=True: False)
    loaders._fund_kind.cache_clear()
    yield _IsinRefusingYahoo.asked
    loaders._fund_kind.cache_clear()


def test_an_unplaced_isin_is_not_handed_to_yahoo_one_symbol_at_a_time(no_isin_search):
    from stocks.data.estimates import fetch_estimates
    from stocks.data.fundamentals import fetch_fundamentals

    assert fetch.info(ISIN) == {}
    assert fetch.fetch_history(ISIN).empty
    assert fetch.close_on(ISIN, "2026-10-01") is None
    with pytest.raises(ValueError, match="no data"):
        fetch.latest_price(ISIN)
    assert fetch_fundamentals(ISIN).income.empty
    assert fetch_estimates(ISIN).price_targets == {}
    assert no_isin_search == []


ROUTES = [
    "quote?base=EUR",
    "bars?range=1d",
    "trend",
    "metrics?base=EUR",
    "dcf",
    "financials",
    "analysts",
    "moat",
    "insiders",
    "compare?range=1y&base=EUR",
]


@pytest.mark.parametrize("route", ROUTES)
def test_the_ticker_page_answers_for_an_unplaced_isin(no_isin_search, monkeypatch, route):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    reply = client.get(f"/v1/ticker/{ISIN}/{route}", headers=AUTH)
    assert reply.status_code < 500, reply.text[:300]
    assert reply.status_code != 404, "the route moved: this test asks nothing"
    assert no_isin_search == []
