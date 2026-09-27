"""Broker-code alias tests — watchlist.yaml `aliases` -> Yahoo symbols."""

import pandas as pd
import pytest

import stocks.data.fetch as fetch
from stocks.config import ticker_aliases

ALIASES = {"RCF": "TEP.PA", "HMI": "RMS.PA"}


def _patch_aliases(monkeypatch, aliases=ALIASES):
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: dict(aliases))


# ------------------------------------------------------------------ config
def test_ticker_aliases_parses_yaml(tmp_path):
    f = tmp_path / "watchlist.yaml"
    f.write_text("aliases:\n  rcf: TEP.PA\n  HMI: RMS.PA\nwatchlist: []\n")
    assert ticker_aliases(f) == {"RCF": "TEP.PA", "HMI": "RMS.PA"}


def test_reference_maps_fall_back_to_example(monkeypatch, tmp_path):
    # watchlist.yaml is git-ignored: on a checkout without it, the global
    # aliases/tv maps must come from the tracked example file instead.
    from stocks import config

    missing = tmp_path / "watchlist.yaml"
    example = tmp_path / "watchlist.example.yaml"
    example.write_text("aliases:\n  RCF: TEP.PA\ntv:\n  RCF: EURONEXT:TEP@france\n")
    monkeypatch.setattr(config, "WATCHLIST_FILE", missing)
    monkeypatch.setattr(config, "EXAMPLE_WATCHLIST_FILE", example)
    assert config.ticker_aliases(missing) == {"RCF": "TEP.PA"}
    assert config.tv_symbols(missing) == {"RCF": "EURONEXT:TEP@france"}
    # An explicit non-default path never falls back.
    assert config.ticker_aliases(tmp_path / "other.yaml") == {}


def test_ticker_aliases_missing_file_or_section(tmp_path):
    assert ticker_aliases(tmp_path / "nope.yaml") == {}
    f = tmp_path / "watchlist.yaml"
    f.write_text("watchlist: []\n")
    assert ticker_aliases(f) == {}


# ------------------------------------------------------------------ resolve
def test_resolve_maps_broker_code_and_passes_through(monkeypatch):
    _patch_aliases(monkeypatch)
    assert fetch.resolve("RCF") == "TEP.PA"
    assert fetch.resolve("rcf") == "TEP.PA"  # ledger codes are upper, be safe
    assert fetch.resolve("NVDA") == "NVDA"


# ------------------------------------------------------------------ fetch layer
def test_fetch_many_downloads_resolved_but_keys_by_broker_code(monkeypatch):
    _patch_aliases(monkeypatch)
    requested = {}

    def fake_download(symbols, **kwargs):
        requested["symbols"] = list(symbols)
        idx = pd.date_range("2026-01-05", periods=2, name="Date")
        cols = pd.MultiIndex.from_product([symbols, ["Close"]])
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(fetch.yf, "download", fake_download)
    out = fetch.fetch_many(["RCF", "NVDA"])
    assert requested["symbols"] == ["TEP.PA", "NVDA"]
    assert set(out) == {"RCF", "NVDA"}  # caller-facing keys stay broker codes


def test_fetch_many_strips_the_ticker_level_for_a_lone_symbol(monkeypatch):
    """yfinance 1.5 groups by ticker even for one symbol.

    The frame handed back must be flat-columned whatever the symbol count, or
    every `df["Close"]` downstream finds nothing and a one-name watchlist —
    or a single-position book — reads as unpriced.
    """
    _patch_aliases(monkeypatch)

    def fake_download(symbols, **kwargs):
        idx = pd.date_range("2026-01-05", periods=2, name="Date")
        cols = pd.MultiIndex.from_product([list(symbols), ["Close"]])
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(fetch.yf, "download", fake_download)
    out = fetch.fetch_many(["NVDA"])
    assert list(out) == ["NVDA"]
    assert list(out["NVDA"].columns) == ["Close"]
    assert out["NVDA"]["Close"].iloc[-1] == 1.0


def test_fetch_many_still_reads_a_flat_single_symbol_frame(monkeypatch):
    """And the older shape — flat columns, no ticker level — still works."""
    _patch_aliases(monkeypatch)

    def fake_download(symbols, **kwargs):
        idx = pd.date_range("2026-01-05", periods=2, name="Date")
        return pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)

    monkeypatch.setattr(fetch.yf, "download", fake_download)
    out = fetch.fetch_many(["NVDA"])
    assert out["NVDA"]["Close"].iloc[-1] == 2.0


def test_fetch_many_falls_back_a_missing_eur_crypto_pair_to_usd(monkeypatch):
    """CHILLGUY-EUR 404s on Yahoo; CHILLGUY-USD prices fine there.

    The fallback must retry the coin on its USD pair and convert the series
    back through the ECB rate, so the caller still gets it keyed by the
    original EUR pair it is actually held in.
    """
    _patch_aliases(monkeypatch, {})

    def fake_download(symbols, **kwargs):
        idx = pd.date_range("2026-01-05", periods=2, name="Date")
        priced = [s for s in symbols if s != "CHILLGUY-EUR"]
        if not priced:
            return pd.DataFrame()
        cols = pd.MultiIndex.from_product([priced, ["Open", "High", "Low", "Close"]])
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(fetch.yf, "download", fake_download)
    monkeypatch.setattr(
        fetch,
        "rates_range",
        lambda start, end, base, quote: {"2026-01-05": 0.9, "2026-01-06": 0.9},
    )
    out = fetch.fetch_many(["CHILLGUY-EUR"])
    assert list(out) == ["CHILLGUY-EUR"]
    assert out["CHILLGUY-EUR"]["Close"].iloc[-1] == pytest.approx(0.9)


def test_fetch_many_falls_back_a_yahoo_less_coin_to_coingecko(monkeypatch):
    """MOODENG has no Yahoo pair at all — not even -USD, so the Yahoo
    fallback above has nothing to retry. Only the hand-curated CoinGecko id
    (`crypto.COINGECKO_IDS`) prices it.
    """
    _patch_aliases(monkeypatch, {})
    monkeypatch.setattr(fetch.yf, "download", lambda symbols, **kwargs: pd.DataFrame())

    def fake_get_json(url, **kwargs):
        assert "moo-deng" in url
        assert "vs_currency=usd" in url
        return {"prices": [[1767571200000, 0.03], [1767657600000, 0.032]]}

    monkeypatch.setattr(fetch, "get_json", fake_get_json)
    out = fetch.fetch_many(["MOODENG-USD"])
    assert list(out) == ["MOODENG-USD"]
    assert out["MOODENG-USD"]["Close"].iloc[-1] == pytest.approx(0.032)


def test_fetch_many_never_asks_yahoo_for_a_coin_it_quotes_as_another(monkeypatch):
    """Yahoo's CAT-EUR is a different coin ~10,000x Simon's Cat, the CAT
    Revolut sells. It answers, so a miss-only fallback never fired and a ~500
    EUR position read 940k. A hand-mapped coin goes to CoinGecko, not Yahoo.
    """
    _patch_aliases(monkeypatch, {})
    asked: list[list[str]] = []

    def fake_download(symbols, **kwargs):
        asked.append(list(symbols))
        idx = pd.date_range("2026-01-05", periods=2, name="Date")
        cols = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close"]])
        return pd.DataFrame(0.02, index=idx, columns=cols)

    monkeypatch.setattr(fetch.yf, "download", fake_download)
    monkeypatch.setattr(
        fetch, "get_json",
        lambda url, **k: {"prices": [[1767571200000, 1.3e-6], [1767657600000, 1.2e-6]]}
        if "simon-s-cat" in url and "vs_currency=eur" in url else {},
    )
    out = fetch.fetch_many(["CAT-EUR", "AAPL"])
    assert all("CAT-EUR" not in batch for batch in asked)
    assert out["CAT-EUR"]["Close"].iloc[-1] == pytest.approx(1.2e-6)
    assert out["AAPL"]["Close"].iloc[-1] == pytest.approx(0.02)


def test_fetch_many_leaves_a_delisted_ticker_missing(monkeypatch):
    """A non-crypto miss (or a USD-quoted crypto miss) gets no fallback."""
    _patch_aliases(monkeypatch, {})
    monkeypatch.setattr(fetch.yf, "download", lambda symbols, **kwargs: pd.DataFrame())
    assert fetch.fetch_many(["ORGN"]) == {}


def test_latest_price_resolves_alias(monkeypatch):
    _patch_aliases(monkeypatch)
    seen = {}

    class FakeTicker:
        def __init__(self, symbol):
            seen["symbol"] = symbol
            self.fast_info = {"lastPrice": 123.0}

    monkeypatch.setattr(fetch.yf, "Ticker", FakeTicker)
    assert fetch.latest_price("HMI") == 123.0
    assert seen["symbol"] == "RMS.PA"
