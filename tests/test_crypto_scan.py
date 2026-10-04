"""The nightly crypto scan — what it keeps when a source does not answer.

The sector scan's rule, applied here: a part that failed tonight keeps last
night's figures, and the file is never published half-empty.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from stocks.analysis import crypto_scan
from stocks.data import crypto_market as source


def _row(gid: str, ath: float, **extra) -> dict:
    return {"id": gid, "ath": ath, "ath_date": "2025-10-06T12:00:00.000Z",
            "market_cap": 100.0, "fully_diluted_valuation": 120.0,
            "market_cap_rank": 3, "circulating_supply": 10.0,
            "total_supply": 11.0, "max_supply": None, **extra}


@pytest.fixture
def scan_file(monkeypatch, tmp_path):
    path = tmp_path / "crypto_scan.json"
    monkeypatch.setattr(crypto_scan, "SCAN_FILE", path)
    monkeypatch.setattr(crypto_scan, "PAUSE_S", 0)
    monkeypatch.setattr(crypto_scan.storage, "enabled", lambda: False)
    return path


def test_rows_fold_into_one_entry_per_coin_with_a_peak_per_currency():
    coins = crypto_scan.coins_from({
        "usd": [_row("bitcoin", 126_000.0), _row("not-curated", 1.0)],
        "eur": [_row("bitcoin", 107_000.0)],
    })
    assert set(coins) == {"BTC"}
    btc = coins["BTC"]
    assert btc["ath"] == {"usd": 126_000.0, "eur": 107_000.0}
    assert btc["ath_date"]["eur"] == "2025-10-06"
    assert btc["rank"] == 3 and btc["max_supply"] is None


def test_a_currency_that_failed_keeps_last_night_peak(scan_file, monkeypatch):
    scan_file.write_text(json.dumps({
        "coins": {"BTC": {"ath": {"gbp": 93_000.0, "usd": 1.0}}},
        "global": {"btc_dominance": 50.0},
        "fear_greed": [["2026-10-01", 40]],
    }))

    def markets(ids, quote):
        if quote == "gbp":
            raise HTTPError("u", 500, "down", None, None)
        return [_row("bitcoin", 126_000.0 if quote == "usd" else 107_000.0)]

    def refused():
        raise HTTPError("u", 503, "down", None, None)

    monkeypatch.setattr(source, "gecko_markets", markets)
    monkeypatch.setattr(source, "gecko_global", refused)
    monkeypatch.setattr(source, "fear_greed", lambda days: [("2026-10-04", 65)])

    status = crypto_scan.run_scan()
    saved = json.loads(scan_file.read_text())
    assert saved["coins"]["BTC"]["ath"] == {
        "usd": 126_000.0, "eur": 107_000.0, "gbp": 93_000.0}
    assert saved["global"] == {"btc_dominance": 50.0}
    assert saved["fear_greed"] == [["2026-10-04", 65]]
    assert status["markets_gbp"].startswith("kept")
    assert status["global"].startswith("kept")


def test_a_dry_run_writes_nothing(scan_file, monkeypatch):
    monkeypatch.setattr(source, "gecko_markets", lambda ids, q: [_row("bitcoin", 1.0)])
    monkeypatch.setattr(source, "gecko_global", lambda: {})
    monkeypatch.setattr(source, "fear_greed", lambda days: [])
    crypto_scan.run_scan(dry_run=True)
    assert not scan_file.exists()


def test_global_reads_each_quote_currency():
    out = crypto_scan.global_from({
        "total_market_cap": {"usd": 3.0, "eur": 2.5, "jpy": 400.0},
        "market_cap_percentage": {"btc": 59.1, "eth": 11.4},
    })
    assert out == {"total_mcap": {"usd": 3.0, "eur": 2.5},
                   "btc_dominance": 59.1, "eth_dominance": 11.4}


def test_every_venue_failing_is_an_error_not_an_unlisted_coin(monkeypatch):
    def down(coin):
        raise OSError("geo-blocked")

    monkeypatch.setattr(source, "VENUES", (("a", down), ("b", down)))
    with pytest.raises(RuntimeError):
        source.positioning("BTC")
    monkeypatch.setattr(source, "VENUES", (("a", down), ("b", lambda c: None)))
    assert source.positioning("BTC") is None
