"""Deribit DVOL and DefiLlama in the nightly scan: parsing, mapping, failure.

Payloads are trimmed recordings of the live endpoints (2026-10-27). Nothing
here touches the network.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.error import HTTPError

import pytest

from stocks.analysis import crypto_market as cm
from stocks.analysis import crypto_scan
from stocks.data import crypto_market as source

DVOL = {"jsonrpc": "2.0", "result": {"continuation": None, "data": [
    [1761436800000, 42.9, 44.17, 42.41, 43.91],
    [1761523200000, 43.91, 43.91, 42.04, 42.82],
    [1793059200000, 38.56, 38.58, 37.24, 37.26],
]}}

PROTOCOLS = [
    {"name": "Binance CEX", "symbol": "BNB", "category": "CEX", "gecko_id": None,
     "slug": "binance-cex", "tvl": 1.7e11},
    {"name": "Uniswap V3", "symbol": "UNI", "category": "Dexs", "gecko_id": None,
     "slug": "uniswap-v3", "parentProtocol": "parent#uniswap", "tvl": 1.6e9},
    {"name": "Uniswap V4", "symbol": "UNI", "category": "Dexs", "gecko_id": None,
     "slug": "uniswap-v4", "parentProtocol": "parent#uniswap", "tvl": 1.2e9},
    {"name": "Aave V3", "symbol": "AAVE", "category": "Lending", "gecko_id": None,
     "slug": "aave-v3", "parentProtocol": "parent#aave", "tvl": 1.65e10},
    {"name": "Aave V2", "symbol": "AAVE", "category": "Lending", "gecko_id": "aave",
     "slug": "aave-v2", "parentProtocol": "parent#aave", "tvl": 1.0e8},
    {"name": "Arbitrum Bridge", "symbol": "ARB", "category": "Canonical Bridge",
     "gecko_id": None, "slug": "arbitrum-bridge", "tvl": 3.3e9},
    {"name": "Chainlink Requests", "symbol": "LINK", "category": "Oracle",
     "gecko_id": None, "slug": "chainlink-requests",
     "parentProtocol": "parent#chainlink", "tvl": 0},
    {"name": "Sky Lending", "symbol": "SKY", "category": "CDP", "gecko_id": None,
     "slug": "sky-lending", "parentProtocol": "parent#maker", "tvl": 5.2e9},
]
CHAINS = [
    {"gecko_id": "ethereum", "tvl": 7.0e10, "name": "Ethereum", "tokenSymbol": "ETH"},
    {"gecko_id": "solana", "tvl": 5.67e9, "name": "Solana", "tokenSymbol": "SOL"},
    {"gecko_id": "bitcoin", "tvl": 6.0e9, "name": "Bitcoin", "tokenSymbol": "BTC"},
    {"gecko_id": "arbitrum", "tvl": 3.0e9, "name": "Arbitrum", "tokenSymbol": "ARB"},
    {"gecko_id": "moonbeam", "tvl": 0, "name": "Moonbeam", "tokenSymbol": "GLMR"},
]


def _days(n: int, start: float = 100.0, step: float = 1.0):
    first = date(2026, 10, 27) - timedelta(days=n - 1)
    return [((first + timedelta(days=i)).isoformat(), start + step * i)
            for i in range(n)]


# ------------------------------------------------------------------- source


def test_dvol_reads_the_close_of_each_daily_candle(monkeypatch):
    seen = []
    monkeypatch.setattr(source, "get_json", lambda url, **k: seen.append(url) or DVOL)
    series = source.dvol("btc")
    assert series[0] == ("2025-10-26", 43.91) and series[-1] == ("2026-10-27", 37.26)
    assert "currency=BTC" in seen[0] and "resolution=86400" in seen[0]


def test_stablecoin_supply_sums_the_usd_column(monkeypatch):
    rows = [{"date": "1793059200", "totalCirculating": {"peggedUSD": 1.0},
             "totalCirculatingUSD": {"peggedUSD": 3.1e11}}, {"date": "bad"}]
    monkeypatch.setattr(source, "get_json", lambda url, **k: rows)
    assert source.stablecoin_supply() == [("2026-10-27", 3.1e11)]


def test_tvl_series_reads_protocols_and_chains(monkeypatch):
    raw = {"tvl": [{"date": 1793059200, "totalLiquidityUSD": 5.0e9}]}
    monkeypatch.setattr(source, "get_json", lambda url, **k: raw)
    assert source.llama_tvl_series("protocol", "uniswap") == [("2026-10-27", 5.0e9)]
    monkeypatch.setattr(source, "get_json",
                        lambda url, **k: [{"date": 1793059200, "tvl": 7.0}])
    assert source.llama_tvl_series("chain", "OP Mainnet") == [("2026-10-27", 7.0)]


# ----------------------------------------------------------------- analysis


def test_percentile_rank_is_the_share_of_the_year_at_or_under():
    year = [float(v) for v in range(1, 101)]
    assert cm.percentile_rank(year, 25) == 25.0
    assert cm.percentile_rank(year[:10], 5) is None
    assert cm.percentile_rank(year, None) is None


@pytest.mark.parametrize("pct,key,tone", [
    (10, "low", "green"), (50, "normal", "gray"),
    (80, "high", "orange"), (97, "extreme", "red"),
])
def test_dvol_bands(pct, key, tone):
    band = cm.dvol_band(pct)
    assert (band.key, band.tone) == (key, tone)
    assert cm.dvol_band(None) is None


def test_change_over_looks_back_calendar_days():
    series = _days(40, start=100.0, step=1.0)  # 100 .. 139
    assert cm.change_over(series, 30) == pytest.approx(139 / 109 - 1)
    assert cm.change_over(series, 90) is None  # does not reach back
    assert cm.change_over(series[:1], 30) is None
    assert cm.change_over(_days(40, start=0.0, step=0.0), 30) is None


# --------------------------------------------------------------------- scan


def test_coins_map_to_a_chain_first_then_a_summed_parent_protocol():
    mapping = crypto_scan.map_coins(PROTOCOLS, CHAINS)
    assert mapping["ETH"] == {"kind": "chain", "slug": "Ethereum", "name": "Ethereum"}
    assert mapping["SOL"]["kind"] == "chain"
    assert mapping["UNI"] == {"kind": "protocol", "slug": "uniswap", "name": "Uniswap"}
    assert mapping["AAVE"]["slug"] == "aave"
    assert mapping["MKR"]["slug"] == "sky"
    assert "DOT" not in mapping  # a same-ticker stranger is not Polkadot
    # A bridge is not the token's protocol; wrapped bitcoin is not the network;
    # a zero-TVL oracle has nothing to show.
    assert "BTC" not in mapping and "LINK" not in mapping
    assert "USDT" not in mapping
    assert mapping["ARB"]["kind"] == "chain"


def test_dvol_summary_carries_percentile_and_range():
    out = crypto_scan.dvol_from(_days(100, start=40.0, step=0.5))
    assert out["value"] == pytest.approx(89.5) and out["percentile"] == 100.0
    assert out["low"] == 40.0 and out["week_ago"] == pytest.approx(86.0)
    assert crypto_scan.dvol_from(_days(10)) is None


@pytest.fixture
def scan_file(monkeypatch, tmp_path):
    path = tmp_path / "crypto_scan.json"
    monkeypatch.setattr(crypto_scan, "SCAN_FILE", path)
    monkeypatch.setattr(crypto_scan, "PAUSE_S", 0)
    monkeypatch.setattr(crypto_scan, "LLAMA_PAUSE_S", 0)
    monkeypatch.setattr(crypto_scan.storage, "enabled", lambda: False)
    monkeypatch.setattr(source, "gecko_markets", lambda ids, q: [])
    monkeypatch.setattr(source, "gecko_global", lambda: {})
    monkeypatch.setattr(source, "fear_greed", lambda days: [("2026-10-27", 50)])
    return path


def test_the_scan_stores_vol_stablecoins_and_onchain(scan_file, monkeypatch):
    monkeypatch.setattr(source, "dvol", lambda c: _days(60, 40.0, 0.5))
    monkeypatch.setattr(source, "stablecoin_supply",
                        lambda days=400: _days(100, 3.0e11, 1e8))
    monkeypatch.setattr(source, "llama_protocols", lambda: PROTOCOLS)
    monkeypatch.setattr(source, "llama_chains", lambda: CHAINS)
    monkeypatch.setattr(source, "llama_tvl_series",
                        lambda kind, name: _days(60, 1e9, 1e7))

    def fees(slug, kind="dailyFees"):
        if slug == "solana":
            return {"total30d": 3_010_067.0 if kind == "dailyFees" else None}
        raise HTTPError("u", 404, "none", None, None)

    monkeypatch.setattr(source, "llama_fees", fees)
    status = crypto_scan.run_scan()
    saved = json.loads(scan_file.read_text())
    assert saved["dvol"]["BTC"]["value"] == pytest.approx(69.5)
    assert saved["stablecoins"]["change_30d"] > 0
    sol = saved["onchain"]["coins"]["SOL"]
    assert sol["fees_30d"] == 3_010_067.0 and sol["revenue_30d"] is None
    assert sol["tvl_change_30d"] == pytest.approx(1.59e9 / 1.29e9 - 1)
    assert saved["onchain"]["coins"]["UNI"]["fees_30d"] is None
    assert saved["onchain"]["map"]["UNI"]["slug"] == "uniswap"
    assert status["dvol_btc"].startswith("ok") and status["onchain"].startswith("ok")


def test_a_part_that_fails_keeps_last_nights_figures(scan_file, monkeypatch):
    stored = {
        "dvol": {"BTC": {"value": 50.0}},
        "stablecoins": {"usd": 1.0},
        "onchain": {"map": {"ETH": {"kind": "chain", "slug": "Ethereum",
                                    "name": "Ethereum"}},
                    "coins": {"ETH": {"tvl": 9.0}}},
        "fear_greed": [["2026-10-01", 40]],
    }
    scan_file.write_text(json.dumps(stored))

    def down(*a, **k):
        raise HTTPError("u", 500, "down", None, None)

    for name in ("dvol", "stablecoin_supply", "llama_protocols", "llama_chains",
                 "llama_tvl_series"):
        monkeypatch.setattr(source, name, down)
    status = crypto_scan.run_scan()
    saved = json.loads(scan_file.read_text())
    assert saved["dvol"] == stored["dvol"]
    assert saved["stablecoins"] == stored["stablecoins"]
    assert saved["onchain"]["coins"]["ETH"] == {"tvl": 9.0}
    assert status["dvol_btc"].startswith("kept")
    assert status["stablecoins"].startswith("kept")
