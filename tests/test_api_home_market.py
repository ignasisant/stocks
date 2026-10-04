"""The Home market strip over HTTP: the Pulse, compressed to one card.

What the strip decides on top of the Pulse is tested here: that it reads only
series the Pulse already downloads, that a price move is a fraction and a
yield's move is basis points, that the day is a horizon of its own, and that
each source fails on its own instead of taking the card down.

Nothing here touches the network: every loader is replaced.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks.analysis import sentiment as sm
from stocks.analysis.sentiment import Pulse as PulseData
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.api.routes import home

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def _cold_caches():
    memos = (loaders.market_pulse, loaders.pulse_closes, loaders.pulse_rate_rows)
    for fn in memos:
        fn.cache_clear()
    yield
    for fn in memos:
        fn.cache_clear()


def days(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-01", periods=n)


def rising(n: int = 260, start: float = 100.0, end: float = 130.0) -> pd.Series:
    return pd.Series(np.linspace(start, end, n), index=days(n))


def built() -> PulseData:
    index = days(200)
    return PulseData(
        score=68.0,
        history=pd.Series(np.linspace(45.0, 68.0, len(index)), index=index),
        components=(),
        missing=(),
        as_of=index[-1],
    )


@pytest.fixture
def market(monkeypatch):
    closes = {symbol: rising() for _, symbol, _, _ in home.MARKET_TILES}
    closes["^VIX"] = rising(start=30.0, end=15.0)
    yields = pd.Series(np.linspace(4.0, 4.5, 260), index=days(260))
    monkeypatch.setattr(loaders, "pulse_closes", lambda: closes)
    monkeypatch.setattr(loaders, "pulse_rate_rows", lambda: {"DGS10": yields})
    monkeypatch.setattr(loaders, "market_pulse", lambda: built())
    return closes


def tiles(payload: dict) -> dict[str, dict]:
    return {t["key"]: t for t in payload["tiles"]}


def test_the_strip_never_widens_the_pulse_download():
    """Every tile is a series the Pulse already pulls in its one bulk request,
    so the Home card costs Yahoo nothing the Pulse page had not spent."""
    pulled = set(sm.all_tickers())
    assert {symbol for _, symbol, _, _ in home.MARKET_TILES} <= pulled
    assert home.MARKET_RATE[1] in sm.RATE_ROWS


def test_every_tile_reads_the_day_the_week_and_the_month(client, market):
    payload = client.get("/v1/home/market", headers=AUTH).json()
    sp = tiles(payload)["sp500"]
    assert set(sp["changes"]) == {"day", "week", "month"}
    series = market["^GSPC"]
    assert sp["changes"]["day"] == pytest.approx(series.iloc[-1] / series.iloc[-2] - 1)
    assert sp["unit"] == "percent"
    assert sp["linkable"] is True


def test_the_tiles_keep_the_strips_reading_order(client, market):
    keys = [t["key"] for t in client.get("/v1/home/market", headers=AUTH).json()["tiles"]]
    assert keys[:5] == ["sp500", "nasdaq", "stoxx50", "ibex", "em"]
    # The yield sits beside the fear gauge, not at the end with the commodities.
    assert keys[5:7] == ["vix", "us10y"]


def test_a_yield_moves_in_basis_points_not_percent(client, market):
    """"The 10-year rose 7%" is how a reader misreads 30 basis points."""
    us10y = tiles(client.get("/v1/home/market", headers=AUTH).json())["us10y"]
    assert us10y["unit"] == "basis_points"
    assert us10y["welcome"] == -1
    assert us10y["linkable"] is False  # a FRED id has no ticker page
    step = 0.5 / 259
    assert us10y["changes"]["day"] == pytest.approx(step * 100)


def test_the_fear_gauge_carries_its_place_in_its_own_year(client, market):
    vix = tiles(client.get("/v1/home/market", headers=AUTH).json())["vix"]
    assert vix["welcome"] == -1
    assert vix["percentile"] is not None
    assert vix["percentile"] < 10  # a year-long fall leaves it at the bottom


def test_the_regime_is_the_pulses_own_composite(client, market):
    payload = client.get("/v1/home/market", headers=AUTH).json()
    assert payload["score"] == 68.0
    assert payload["regime"] == "appetite"
    assert len(payload["history"]) == home.MARKET_HISTORY
    assert payload["breadth"] is None or payload["breadth"]["window"] == 200


def test_a_dead_composite_costs_the_chip_not_the_tiles(client, market, monkeypatch):
    def _dead():
        raise RuntimeError("no inputs")

    monkeypatch.setattr(loaders, "market_pulse", _dead)
    payload = client.get("/v1/home/market", headers=AUTH).json()
    assert payload["score"] is None
    assert payload["regime"] == "unknown"
    assert tiles(payload)["sp500"]["value"] is not None


def test_a_dead_fred_costs_the_yield_tile_only(client, market, monkeypatch):
    def _dead():
        raise OSError("FRED tarpit")

    monkeypatch.setattr(loaders, "pulse_rate_rows", _dead)
    keys = tiles(client.get("/v1/home/market", headers=AUTH).json())
    assert "us10y" not in keys
    assert "vix" in keys


def test_a_missing_series_drops_its_tile_rather_than_drawing_zero(
    client, market, monkeypatch
):
    del market["BTC-USD"]
    assert "btc" not in tiles(client.get("/v1/home/market", headers=AUTH).json())


def test_a_throttled_price_burst_empties_the_card_and_says_why(client, monkeypatch):
    from yfinance.exceptions import YFRateLimitError

    def _throttled():
        raise YFRateLimitError

    monkeypatch.setattr(loaders, "pulse_closes", _throttled)
    response = client.get("/v1/home/market", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["unavailable"] == "rate_limited"
    assert response.json()["tiles"] == []


def test_a_guest_reads_the_strip(client, market, monkeypatch):
    """The same answer for everybody: no account goes into it."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")
    assert client.get("/v1/home/market").status_code == 200
