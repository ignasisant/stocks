"""A coin page's cards: cycle, positioning, holding — and the stats' new lines.

The arithmetic is `test_crypto_market.py`'s; what is tested here is what the
HTTP layer promises on top: a share asking gets an empty answer rather than an
error, a stablecoin gets no stretch or perpetual, a coin the scan does not
cover still gets a peak (labelled the 52-week stand-in), and the harvest line
only ever appears for a coin the tax engine agrees is held at a loss.

Nothing here touches the network — every loader is replaced.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.data.crypto_market import Positioning

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

SCAN = {
    "saved": "2026-10-04",
    "global": {"btc_dominance": 59.1, "total_mcap": {"eur": 2.5e12, "usd": 2.9e12}},
    "fear_greed": [[f"2026-09-{d:02d}", 40 + d] for d in range(1, 31)],
    "coins": {
        "BTC": {
            "ath": {"eur": 107_000.0}, "ath_date": {"eur": "2025-10-06"},
            "fdv": {"eur": 1.6e12}, "market_cap": {"eur": 1.52e12},
            "circulating": 20_000_000.0, "max_supply": 21_000_000.0, "rank": 1,
        },
    },
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    monkeypatch.setattr(loaders, "crypto_scan", lambda: SCAN)
    monkeypatch.setattr(loaders, "crypto_info", lambda t: {
        "marketCap": 1.5e12, "circulatingSupply": 19_900_000,
        "fiftyTwoWeekHigh": 100_000.0, "fiftyTwoWeekLow": 50_000.0,
    })


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: BTC-EUR\n")
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    monkeypatch.setattr(loaders, "custody", lambda db, m: {})
    return paths


def _closes(n: int, start: float = 100.0, step: float = 1.0) -> pd.Series:
    index = pd.date_range(end="2026-10-04", periods=n, freq="D")
    return pd.Series(start + step * np.arange(n), index=index, dtype=float)


# ---------------------------------------------------------------------- stats


def test_stats_carry_the_scan_peak_in_the_pair_currency(client):
    body = client.get("/v1/ticker/BTC-EUR/crypto", headers=AUTH).json()
    assert (body["ath"], body["ath_source"], body["ath_date"]) == (
        107_000.0, "scan", "2025-10-06")
    assert body["issued_pct"] == pytest.approx(20 / 21)
    assert body["fdv_ratio"] == pytest.approx(1.6 / 1.52)
    assert body["category"] == "store_of_value" and body["rank"] == 1


def test_a_coin_off_the_scan_gets_the_52_week_high_labelled_as_such(client):
    body = client.get("/v1/ticker/KAS-USD/crypto", headers=AUTH).json()
    assert (body["ath"], body["ath_source"], body["ath_date"]) == (100_000.0, "52w", None)
    assert body["fdv"] is None and body["issued_pct"] is None


def test_a_peak_since_the_scan_is_not_lost(client, monkeypatch):
    monkeypatch.setattr(loaders, "crypto_info", lambda t: {"fiftyTwoWeekHigh": 120_000.0})
    body = client.get("/v1/ticker/BTC-EUR/crypto", headers=AUTH).json()
    assert body["ath"] == 120_000.0


def test_a_coin_chart_marks_its_cycle(client):
    body = client.get("/v1/ticker/BTC-EUR/events", headers=AUTH).json()
    kinds = {e["kind"] for e in body["cycle"]}
    assert kinds == {"halving", "etf"} and body["earnings"] == []
    assert client.get("/v1/ticker/DOGE-USD/events", headers=AUTH).json()["cycle"] == []


# ---------------------------------------------------------------------- cycle


def test_cycle_reads_sentiment_from_the_scan_and_stretch_from_the_closes(
    client, monkeypatch
):
    closes = {"SOL-EUR": _closes(1500, step=0.5), "BTC-EUR": _closes(1500, step=1.0)}
    monkeypatch.setattr(loaders, "daily_closes",
                        lambda t, period="max": closes.get(t, pd.Series(dtype=float)))
    body = client.get("/v1/ticker/SOL-EUR/crypto/cycle", headers=AUTH).json()
    assert body["fear_greed"]["value"] == 70 and body["fear_greed"]["band"] == "greed"
    assert body["fear_greed_week"] == 63
    assert body["total_mcap"] == 2.5e12 and body["btc_dominance"] == 59.1
    assert body["mayer"]["value"] > 1 and body["ratio_200w"]["band"] is not None
    assert body["vs_btc_90d"] is not None and body["vs_nasdaq_90d"] is None
    assert body["halving"]["last"] == "2024-04-20"


def test_bitcoin_is_measured_against_the_nasdaq_in_dollars(client, monkeypatch):
    asked = []

    def closes(t, period="max"):
        asked.append(t)
        return _closes(400)

    monkeypatch.setattr(loaders, "daily_closes", closes)
    body = client.get("/v1/ticker/BTC-EUR/crypto/cycle", headers=AUTH).json()
    assert "BTC-USD" in asked and "QQQ" in asked
    assert body["vs_btc_90d"] is None and body["vs_nasdaq_90d"] is not None


def test_a_stablecoin_gets_the_market_and_nothing_of_its_own(client, monkeypatch):
    monkeypatch.setattr(loaders, "daily_closes",
                        lambda *a, **k: pytest.fail("a peg has no cycle"))
    body = client.get("/v1/ticker/USDT-EUR/crypto/cycle", headers=AUTH).json()
    assert body["fear_greed"]["value"] == 70 and body["mayer"] is None


def test_a_share_asking_for_a_cycle_is_empty(client):
    body = client.get("/v1/ticker/AAPL/crypto/cycle", headers=AUTH).json()
    assert body["fear_greed"] is None and body["ticker"] == "AAPL"


# ---------------------------------------------------------------- positioning


def test_positioning_restates_funding_per_eight_hours(client, monkeypatch):
    monkeypatch.setattr(loaders, "crypto_positioning", lambda coin: Positioning(
        venue="bybit", symbol="KASUSDT", funding=0.00005, funding_7d=0.0002,
        interval_h=4.0, oi_usd=1e7, oi_change_7d=0.1))
    body = client.get("/v1/ticker/KAS-USD/crypto/positioning", headers=AUTH).json()
    assert body["funding_8h"]["value"] == pytest.approx(0.0001)
    assert body["funding_7d_8h"]["band"] == "hot"
    assert body["annualized"] == pytest.approx(0.0004 * 3 * 365)
    assert body["venue"] == "bybit"


def test_every_venue_down_hides_the_card(client, monkeypatch):
    def down(coin):
        raise RuntimeError("every derivatives venue failed")

    monkeypatch.setattr(loaders, "crypto_positioning", down)
    got = client.get("/v1/ticker/BTC-EUR/crypto/positioning", headers=AUTH)
    assert got.json() is None


def test_a_stablecoin_has_no_perpetual_worth_reading(client, monkeypatch):
    monkeypatch.setattr(loaders, "crypto_positioning",
                        lambda coin: pytest.fail("not asked"))
    got = client.get("/v1/ticker/USDC-USD/crypto/positioning", headers=AUTH)
    assert got.json() is None


# -------------------------------------------------------------------- holding


def _book(**pnl) -> pd.DataFrame:
    # (shares, cost, value): bitcoin at a gain, ether at a loss.
    rows = {"BTC-EUR": (0.1, 5000.0, 6000.0), "ETH-EUR": (2.0, 4000.0, 3000.0),
            "AAPL": (10.0, 1000.0, 41000.0)}
    return pd.DataFrame(
        {"shares": [r[0] for r in rows.values()],
         "cost": [r[1] for r in rows.values()],
         "value": [r[2] for r in rows.values()],
         "pnl": [r[2] - r[1] for r in rows.values()],
         "ccy": ["EUR"] * 3},
        index=pd.Index(list(rows), name="ticker"),
    )


@dataclass
class FakeSale:
    gain: float
    extra_tax: float
    blocked: float = 0.0


@dataclass
class FakeHeld:
    ticker: str
    quantity: float


class FakeBook:
    currency = "EUR"
    day = "2026-10-04"

    class jurisdiction:
        repurchase_window = "2m"

    def held(self, symbol):
        return FakeHeld(symbol, 2.0) if symbol == "ETH-EUR" else None

    def scenario(self, symbol, shares, price, currency):
        return FakeSale(gain=-1000.0, extra_tax=-190.0)


def test_holding_reads_the_coin_against_the_crypto_sleeve(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "positions_table", lambda db, m, base: _book())
    body = client.get("/v1/ticker/BTC-EUR/crypto/holding",
                      params={"account": EMAIL}, headers=AUTH).json()
    assert body["held"] is True
    assert body["crypto_share"] == pytest.approx(9000 / 50000)
    assert body["crypto_weight"] == pytest.approx(6000 / 9000)
    assert body["sizing"] == "over"
    assert body["harvest"] is None, "held at a gain"


def test_a_coin_at_a_loss_carries_the_engine_harvest(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "positions_table", lambda db, m, base: _book())
    monkeypatch.setattr(loaders, "crypto_replay", lambda *a: FakeBook())
    body = client.get("/v1/ticker/ETH-EUR/crypto/holding",
                      params={"account": EMAIL}, headers=AUTH).json()
    harvest = body["harvest"]
    assert (harvest["loss"], harvest["saving"]) == (-1000.0, 190.0)
    assert harvest["window"] == "2m" and harvest["clear_on"] == "2026-12-05"


def test_a_coin_not_in_the_book_is_not_held(client, account, monkeypatch):
    monkeypatch.setattr(loaders, "positions_table", lambda db, m, base: _book())
    body = client.get("/v1/ticker/SOL-EUR/crypto/holding",
                      params={"account": EMAIL}, headers=AUTH).json()
    assert body["held"] is False and body["crypto_share"] is None
