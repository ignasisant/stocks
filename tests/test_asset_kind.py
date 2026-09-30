"""Asset kind: which of seven things a symbol is, so the ticker page can say so.

Offline. The fund payloads below mirror what Yahoo answered for the real
symbols on 2026-09-30 (UCITS lines carry no category at all, which is why the
fund's name is read first); the price series are synthetic, shaped like a
money-market line, a short-bond one and an equity index.
"""

import json
import math
from pathlib import Path

import pytest

from stocks.data import asset_kind, cef, funds
from stocks.data.asset_kind import (
    BOND_FUND,
    CLOSED_END,
    CRYPTO,
    EQUITY_FUND,
    FUND,
    INDEX,
    KINDS,
    MONEY_MARKET,
    STOCK,
    classify,
    needs_prices,
    price_signals,
)

LOCALES = Path(__file__).resolve().parents[1] / "src/stocks/web/locales"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_kind, "KIND_CACHE", tmp_path / "asset_kinds.json")
    monkeypatch.setattr(asset_kind, "_kinds", None)
    monkeypatch.setattr(funds, "TYPE_CACHE", tmp_path / "quote_types.json")
    monkeypatch.setattr(funds, "_types", None)
    monkeypatch.setattr(cef, "CEF_CACHE", tmp_path / "closed_end.json")
    monkeypatch.setattr(cef, "_verdicts", None)
    yield
    monkeypatch.setattr(asset_kind, "_kinds", None)
    monkeypatch.setattr(funds, "_types", None)


def drift(days: int, rate: float, start: float = 100.0) -> list[float]:
    """A price rising at `rate` a year, one bar a trading day, never falling."""
    step = (1 + rate) ** (1 / 252)
    return [start * step**i for i in range(days)]


def wave(days: int, amplitude: float, start: float = 100.0) -> list[float]:
    """A price that swings `amplitude` either side of `start`."""
    return [start * (1 + amplitude * math.sin(i / 3)) for i in range(days)]


CALM = price_signals(drift(260, 0.03))
SHORT_BOND = price_signals(wave(260, 0.004))
EQUITY = price_signals(wave(260, 0.03))


# ------------------------------------------------------------------ classify


@pytest.mark.parametrize(
    ("case", "kwargs", "expected"),
    [
        (
            "XEON: a swap-based €STR line, named for it",
            dict(
                symbol="XEON.DE",
                quote_type="ETF",
                name="Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C",
            ),
            MONEY_MARKET,
        ),
        (
            "IB01: a T-bill fund whose name also says 'Treasury Bond'",
            dict(
                symbol="IB01.L",
                quote_type="ETF",
                name="iShares $ Treasury Bond 0-1yr UCITS ETF USD (Acc)",
                asset_classes=(("Bonds", 0.99), ("Cash", 0.01)),
            ),
            MONEY_MARKET,
        ),
        (
            "SGOV: ultrashort category, and its price is cash-flat",
            dict(
                symbol="SGOV",
                quote_type="ETF",
                name="iShares 0-3 Month Treasury Bond ETF",
                category="Ultrashort Bond",
            ),
            MONEY_MARKET,
        ),
        (
            "BIL-like: ultrashort, generic name, calm price",
            dict(
                symbol="BILX",
                quote_type="ETF",
                name="SPDR Bloomberg Short Paper ETF",
                category="Ultrashort Bond",
                vol_1y=CALM[0],
                max_dd=CALM[1],
            ),
            MONEY_MARKET,
        ),
        (
            "JPST-like: ultrashort but it moves like short credit",
            dict(
                symbol="JPST",
                quote_type="ETF",
                name="JPMorgan Ultra-Short Income ETF",
                category="Ultrashort Bond",
                vol_1y=0.02,
                max_dd=0.01,
            ),
            BOND_FUND,
        ),
        (
            "cash-heavy and calm: a money-market fund Yahoo has no words for",
            dict(
                symbol="CASHX",
                quote_type="MUTUALFUND",
                name="Some Government Cash Reserves",
                asset_classes=(("Cash", 0.97), ("Bonds", 0.03)),
                vol_1y=CALM[0],
                max_dd=CALM[1],
            ),
            MONEY_MARKET,
        ),
        (
            "TBT-like: all cash collateral, violently priced",
            dict(
                symbol="TBT",
                quote_type="ETF",
                name="ProShares UltraShort 20+ Year",
                category="Trading--Inverse Debt",
                asset_classes=(("Cash", 0.9), ("Other", 0.1)),
                vol_1y=0.4,
                max_dd=0.3,
            ),
            EQUITY_FUND,
        ),
        (
            "a swap line with no words and a calm price",
            dict(
                symbol="SWAP.DE",
                quote_type="ETF",
                name="Mystery Synthetic UCITS ETF",
                vol_1y=CALM[0],
                max_dd=CALM[1],
            ),
            MONEY_MARKET,
        ),
        (
            "GLD-like: an 'Other' basket that moves like gold",
            dict(
                symbol="GLD",
                quote_type="ETF",
                name="SPDR Gold Shares",
                category="Commodities Focused",
                asset_classes=(("Other", 1.0),),
                vol_1y=0.15,
                max_dd=0.08,
            ),
            EQUITY_FUND,
        ),
        (
            "AGGH: bonds by name, no category",
            dict(
                symbol="AGGH.AS",
                quote_type="ETF",
                name="iShares Core Global Aggregate Bond UCITS ETF EUR Hedged",
            ),
            BOND_FUND,
        ),
        (
            "a bond fund known only by its asset mix",
            dict(
                symbol="BNDX",
                quote_type="ETF",
                name="Vanguard Total International",
                asset_classes=(("Bonds", 0.97), ("Cash", 0.03)),
            ),
            BOND_FUND,
        ),
        (
            "IWDA: an equity index fund",
            dict(
                symbol="IWDA.AS",
                quote_type="ETF",
                name="iShares Core MSCI World UCITS ETF USD (Acc)",
                asset_classes=(("Equity", 0.99), ("Cash", 0.01)),
            ),
            EQUITY_FUND,
        ),
        (
            "PDI: a closed-end fund Yahoo calls a share",
            dict(symbol="PDI", quote_type="EQUITY", closed_end=True),
            CLOSED_END,
        ),
        ("AAPL", dict(symbol="AAPL", quote_type="EQUITY"), STOCK),
        ("^GSPC by its caret", dict(symbol="^GSPC", quote_type=None), INDEX),
        ("an index by quoteType", dict(symbol="SPX", quote_type="INDEX"), INDEX),
        ("BTC-EUR by its pair", dict(symbol="BTC-EUR", quote_type=None), CRYPTO),
        ("a coin by quoteType", dict(symbol="XYZ", quote_type="CRYPTOCURRENCY"), CRYPTO),
        ("a future carries no label", dict(symbol="GC=F", quote_type="FUTURE"), None),
        (
            "a currency carries no label",
            dict(symbol="EURUSD=X", quote_type="CURRENCY"),
            None,
        ),
        (
            "an unknown quoteType stays a stock",
            dict(symbol="SAN.MC", quote_type=None),
            STOCK,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_classify(case, kwargs, expected):
    assert classify(**kwargs) == expected, case


def test_an_equity_fund_is_not_money_market_just_because_it_is_calm_for_a_year():
    """Calm alone never makes a fund cash: an equity basket stays equity."""
    assert (
        classify(
            symbol="LOWV",
            quote_type="ETF",
            name="Low Volatility Equity",
            asset_classes=(("Equity", 0.98), ("Cash", 0.02)),
            vol_1y=0.005,
            max_dd=0.001,
        )
        == EQUITY_FUND
    )


def test_a_swap_line_that_once_fell_is_not_money_market():
    """Calm but with a real drawdown: the swap net needs both."""
    assert (
        classify(
            symbol="SWAP.DE",
            quote_type="ETF",
            name="Mystery Synthetic UCITS ETF",
            vol_1y=0.008,
            max_dd=0.02,
        )
        == EQUITY_FUND
    )


# ---------------------------------------------------------------- the price


def test_price_signals_read_a_cash_line_as_calm_and_an_index_as_not():
    assert CALM is not None and EQUITY is not None and SHORT_BOND is not None
    vol, dd = CALM
    assert vol < asset_kind.CASH_VOL and dd == 0
    assert EQUITY[0] > 0.1 and EQUITY[1] > 0.03
    assert asset_kind.CASH_VOL < SHORT_BOND[0] < EQUITY[0]


def test_price_signals_want_enough_history():
    assert price_signals(drift(asset_kind.MIN_BARS - 1, 0.03)) is None
    assert price_signals([]) is None


def test_price_signals_skip_gaps_and_read_only_the_last_year():
    """NaN bars are dropped; a crash three years ago is not this year's risk."""
    old_crash = wave(500, 0.2)
    series = old_crash + [float("nan")] + drift(260, 0.03, start=old_crash[-1])
    vol, dd = price_signals(series)
    assert vol < asset_kind.CASH_VOL and dd < asset_kind.CASH_DRAWDOWN


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (dict(name="Xtrackers II EUR Overnight Rate Swap"), False),
        (dict(name="iShares Core Global Aggregate Bond"), False),
        (dict(name="JPMorgan Ultra-Short Income", category="Ultrashort Bond"), True),
        (dict(name="Cash Reserves", asset_classes=(("Cash", 0.97),)), True),
        (
            dict(
                name="ProShares",
                category="Trading--Inverse",
                asset_classes=(("Cash", 0.9),),
            ),
            False,
        ),
        (dict(name="Mystery Synthetic"), True),
        (dict(name="SPDR Gold", asset_classes=(("Other", 1.0),)), True),
        (dict(name="iShares Core MSCI World", asset_classes=(("Equity", 0.99),)), False),
    ],
)
def test_needs_prices_only_when_the_description_cannot_place_the_fund(kwargs, expected):
    assert needs_prices(**kwargs) is expected


def test_needs_prices_agrees_with_classify():
    """If the verdict can change with the price, the loader must say so."""
    descriptions = [
        dict(name="Mystery Synthetic"),
        dict(name="Cash Reserves", asset_classes=(("Cash", 0.97),)),
        dict(name="JPM Ultra-Short", category="Ultrashort Bond"),
        dict(name="iShares Core MSCI World", asset_classes=(("Equity", 0.99),)),
        dict(name="Aggregate Bond"),
        dict(name="Overnight Rate Swap"),
    ]
    for desc in descriptions:
        etf = dict(symbol="X", quote_type="ETF", **desc)
        calm = classify(vol_1y=CALM[0], max_dd=CALM[1], **etf)
        wild = classify(vol_1y=EQUITY[0], max_dd=EQUITY[1], **etf)
        assert (calm != wild) <= needs_prices(**desc), desc


# ------------------------------------------------------------------ storage


def test_remember_persists_and_survives_a_fresh_process(tmp_path):
    asset_kind.remember("xeon.de", MONEY_MARKET)
    stored = json.loads((tmp_path / "asset_kinds.json").read_text())
    assert stored == {"XEON.DE": MONEY_MARKET}
    asset_kind.clear()
    assert asset_kind.known("XEON.DE") == MONEY_MARKET


def test_remember_refuses_what_is_not_a_kind(tmp_path):
    asset_kind.remember("VWCE.DE", FUND)
    asset_kind.remember("GC=F", None)
    assert not (tmp_path / "asset_kinds.json").exists()
    assert asset_kind.known("VWCE.DE") is None


def test_remember_survives_a_read_only_disk(monkeypatch, tmp_path):
    missing = tmp_path / "missing" / "asset_kinds.json"
    monkeypatch.setattr(asset_kind, "KIND_CACHE", missing)
    asset_kind.remember("IWDA.AS", EQUITY_FUND)
    assert asset_kind.known("IWDA.AS") == EQUITY_FUND


# ------------------------------------------------------------------- cached


def test_cached_never_fetches(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("cached() must not reach the network")

    monkeypatch.setattr("stocks.data.fetch.info", boom)
    monkeypatch.setattr(cef, "_edgar_verdict", boom, raising=False)
    for symbol in ("NVDA", "XEON.DE", "PDI", "ZZZZ"):
        asset_kind.cached(symbol)


def test_cached_reads_the_stored_verdict_first():
    asset_kind.remember("IB01.L", MONEY_MARKET)
    assert asset_kind.cached("ib01.l") == MONEY_MARKET


def test_cached_places_a_fund_by_its_name_or_answers_fund():
    funds.remember("XEON.DE", "ETF")
    funds.remember("MYST.DE", "ETF")
    xeon = asset_kind.cached("XEON.DE", "Xtrackers II EUR Overnight Rate Swap")
    assert xeon == MONEY_MARKET
    assert asset_kind.cached("MYST.DE", "Mystery UCITS ETF") == FUND


def test_cached_names_the_symbol_only_it_can():
    funds.remember("AAPL", "EQUITY")
    assert asset_kind.cached("AAPL") == STOCK
    assert asset_kind.cached("^GSPC") == INDEX
    assert asset_kind.cached("BTC-EUR") == CRYPTO
    # Nothing known: no label beats a wrong one.
    assert asset_kind.cached("ZZZZ") is None


def test_cached_reads_a_closed_end_verdict_already_on_disk(tmp_path):
    funds.remember("PDI", "EQUITY")
    (tmp_path / "closed_end.json").write_text(json.dumps({"PDI": True}))
    assert asset_kind.cached("PDI") == CLOSED_END


# ---------------------------------------------------------------- the copy


@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_kind_has_a_label_and_a_line(lang):
    copy = json.loads((LOCALES / lang / "ticker.json").read_text())
    for kind in KINDS:
        assert copy.get(f"ticker.asset_{kind}"), (lang, kind)
        assert copy.get(f"ticker.asset_{kind}_line"), (lang, kind)
