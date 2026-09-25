"""A close converts at its own listing's rate, not at the ledger row's.

The case that broke: Revolut's ``ASML`` is the US ADR, bought in dollars, and
watchlist.yaml aliases it to ``ASML.AS`` — whose closes are euros. Every path
that turned a close into money multiplied that euro close by the *dollar's*
rate, so the holding read ~10-15% light (the EUR/USD gap), and the value
history, the TWR, the weights and the P/L all inherited it. London lines add
the second trap: Yahoo quotes them in pence (``GBp``), and a pence close read
as pounds is a hundredfold overstatement.

Everything here is offline: `listing._lookup` says what each listing is quoted
in, and the FX module's two network calls (`spot`, `rate_on`/`rates_range`)
are replaced with fixed rates.
"""

from __future__ import annotations

import pandas as pd
import pytest

from stocks.analysis import listing
from stocks.analysis import portfolio as ap
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import Position

# Captured at import, before conftest swaps it for "unknown" per test.
REAL_LOOKUP = listing._lookup

# How much one unit of each currency is worth in euros.
TO_EUR = {"EUR": 1.0, "USD": 0.9, "GBP": 1.2}
LISTED = {"ASML": "EUR", "AAPL": "USD", "AZN.L": "GBp"}


def _rate(ccy: str, base: str) -> float:
    return TO_EUR[ccy.upper()] / TO_EUR[base.upper()]


@pytest.fixture
def listings(monkeypatch):
    monkeypatch.setattr(listing, "_lookup", lambda ticker: LISTED.get(ticker))


@pytest.fixture
def fixed_fx(monkeypatch):
    """Every rate the valuation paths can ask for, constant over time."""
    monkeypatch.setattr(
        "stocks.data.fx.spot", lambda ccy, base: (_rate(ccy, base), "2024-01-05")
    )
    monkeypatch.setattr(
        "stocks.data.fx.rate_on", lambda day, ccy, base: _rate(ccy, base)
    )
    monkeypatch.setattr(
        "stocks.data.fx.rates_range",
        lambda start, end, ccy, base: {
            d: _rate(ccy, base)
            for d in ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04",
                      "2024-01-05")
        },
    )


def _positions() -> list[Position]:
    """ASML bought in dollars (2 @ $720), AAPL in dollars, AZN.L in pounds."""
    return [
        Position("ASML", 2.0, cost=2 * 720 * 0.9, cost_native=1440.0, currency="USD"),
        Position("AAPL", 10.0, cost=900.0, cost_native=1000.0, currency="USD"),
        Position("AZN.L", 10.0, cost=1080.0, cost_native=900.0, currency="GBP"),
    ]


CLOSES = {
    "ASML": pd.Series([700.0], index=pd.to_datetime(["2024-01-05"])),  # euros
    "AAPL": pd.Series([120.0], index=pd.to_datetime(["2024-01-05"])),  # dollars
    "AZN.L": pd.Series([10_000.0], index=pd.to_datetime(["2024-01-05"])),  # pence
}


# ------------------------------------------------------------------ the helper


def test_quote_unit_scales_minor_units_and_keeps_case_where_it_matters():
    assert listing.quote_unit("GBp") == ("GBP", 0.01)
    assert listing.quote_unit("GBP") == ("GBP", 1.0)
    assert listing.quote_unit("ZAc") == ("ZAR", 0.01)
    assert listing.quote_unit("eur") == ("EUR", 1.0)
    assert listing.quote_unit(None) == (None, 1.0)


def test_price_units_prefer_the_listing_and_fall_back_to_the_ledger(listings):
    units = listing.price_units(
        ["ASML", "AZN.L", "UNSEEN"], {"ASML": "USD", "AZN.L": "GBP", "UNSEEN": "USD"}
    )
    assert units == {
        "ASML": ("EUR", 1.0),
        "AZN.L": ("GBP", 0.01),
        "UNSEEN": ("USD", 1.0),
    }


def test_lookup_reads_the_memo_and_only_asks_yahoo_where_it_could_differ(monkeypatch):
    """The valuation paths run on every render: a bare, unaliased symbol the
    memo has never seen is taken at the ledger's word instead of costing a
    `.info` request; an aliased or venue-suffixed one is worth the one-off."""
    monkeypatch.setattr(listing, "_lookup", REAL_LOOKUP)
    aliases = {"ASML": "ASML.AS", "HMI": "RMS.PA"}
    memo = {"ASML.AS": {"currency": "EUR", "quoteType": "EQUITY"}}
    asked: list[str] = []

    def info(ticker):
        asked.append(ticker)
        return {"currency": "EUR"}

    monkeypatch.setattr("stocks.data.fetch.resolve", lambda t: aliases.get(t, t))
    monkeypatch.setattr("stocks.data.profiles.known", lambda s: memo.get(s))
    monkeypatch.setattr("stocks.data.fetch.info", info)

    assert listing.listing_currencies(["ASML", "HMI", "NVDA", "BTC-EUR"]) == {
        "ASML": "EUR",  # memo
        "HMI": "EUR",  # aliased, unseen: asked once
        "NVDA": None,  # bare and unseen: the ledger's word
        "BTC-EUR": "EUR",  # a pair names its own quote
    }
    assert asked == ["HMI"]


# ------------------------------------------------------------- live valuation


def test_market_values_convert_each_close_at_its_listings_rate(
    listings, fixed_fx, monkeypatch
):
    monkeypatch.setattr(ap, "load_closes", lambda tickers, period="5d": CLOSES)
    eur = ap.market_values(_positions(), base="EUR")
    # 2 x €700 — not 2 x 700 x 0.9, which read the euro close as dollars.
    assert eur["ASML"] == pytest.approx(1400.0)
    assert eur["AAPL"] == pytest.approx(10 * 120 * 0.9)
    # 10 x 10,000p = £1,000, at 1.2.
    assert eur["AZN.L"] == pytest.approx(1200.0)

    usd = ap.market_values(_positions(), base="USD")
    assert usd["ASML"] == pytest.approx(1400.0 / 0.9)
    assert usd["AAPL"] == pytest.approx(1200.0)
    assert usd["AZN.L"] == pytest.approx(1000.0 * 1.2 / 0.9)


def test_the_straggler_path_converts_at_the_listings_rate_too(
    listings, fixed_fx, monkeypatch
):
    """A name the bulk download drops is priced one by one — same rule."""
    monkeypatch.setattr(ap, "load_closes", lambda tickers, period="5d": {})
    monkeypatch.setattr(
        "stocks.data.fetch.latest_price",
        lambda t: {"ASML": 700.0, "AZN.L": 10_000.0}[t],
    )
    pos = [p for p in _positions() if p.ticker != "AAPL"]
    out = ap.market_values(pos, base="EUR")
    assert out == pytest.approx({"ASML": 1400.0, "AZN.L": 1200.0})


def test_the_positions_table_is_priced_in_the_listing_and_pl_has_no_fx_jump(
    listings, fixed_fx, monkeypatch
):
    """Cost stays what was paid (at each trade date's rate), value is the
    listing's close at its own rate, and `ccy` labels the price the table backs
    out of `value` — so that price is the listing's real quote."""
    from stocks.api.routes.portfolio import _native_price

    monkeypatch.setattr(ap, "load_closes", lambda tickers, period="5d": CLOSES)
    tbl = ap.positions_frame(_positions(), base="EUR")

    assert tbl.loc["ASML", "ccy"] == "EUR"
    assert tbl.loc["AZN.L", "ccy"] == "GBP", "the major unit, not pence"
    assert tbl.loc["ASML", "value"] == pytest.approx(1400.0)
    assert tbl.loc["ASML", "pnl"] == pytest.approx(1400.0 - 1296.0)
    assert tbl.loc["ASML", "pnl_pct"] == pytest.approx(1400.0 / 1296.0 - 1)

    weights = ap.value_weights(tbl)
    total = 1400.0 + 1080.0 + 1200.0
    assert weights["ASML"] == pytest.approx(1400.0 / total)
    assert weights.sum() == pytest.approx(1.0)

    rates = {c: _rate(c, "EUR") for c in ("EUR", "USD", "GBP")}
    assert _native_price(tbl.loc["ASML"], rates) == pytest.approx(700.0)
    assert _native_price(tbl.loc["AZN.L"], rates) == pytest.approx(100.0)


def test_risk_weights_scale_pence_before_converting(fixed_fx):
    positions = [p for p in _positions() if p.ticker != "AAPL"]
    weights = ap.market_value_weights_base(
        positions,
        prices={"ASML": 700.0, "AZN.L": 10_000.0},
        meta={"ASML": {"currency": "EUR"}, "AZN.L": {"currency": "GBp"}},
        base="EUR",
    )
    assert weights["ASML"] == pytest.approx(1400.0 / 2600.0)
    assert weights["AZN.L"] == pytest.approx(1200.0 / 2600.0)


def test_basket_frames_use_the_listing_currency(listings, fixed_fx):
    idx = pd.to_datetime(["2024-01-04", "2024-01-05"])
    closes = {
        "ASML": pd.Series([650.0, 700.0], index=idx),
        "AZN.L": pd.Series([9_000.0, 10_000.0], index=idx),
    }
    pos = [p for p in _positions() if p.ticker != "AAPL"]
    values, frozen = ap.position_value_frames(pos, base="EUR", closes=closes)
    assert list(values["ASML"]) == pytest.approx([1300.0, 1400.0])
    assert list(values["AZN.L"]) == pytest.approx([1080.0, 1200.0])
    assert frozen.equals(values), "constant rates: no FX share"


# ------------------------------------------------------------ history replay


def _asml_book() -> list[Transaction]:
    return [Transaction("2024-01-02", "ASML", "buy", 2, 720.0, "USD", 0.0)]


@pytest.mark.parametrize("base", ["EUR", "USD"])
def test_the_history_values_a_dollar_buy_off_a_euro_listing_without_a_jump(
    listings, fixed_fx, base
):
    """Priced at exactly what was paid (€648 = $720 x 0.9), the book must read
    flat — the old replay booked a -10% loss on the day of the buy and a TWR
    that never recovered it."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    closes = {"ASML": pd.Series([648.0, 648.0, 648.0, 700.0], index=idx)}
    hist, twr, missing = ap.book_history(_asml_book(), base=base, closes=closes)

    assert missing == []
    paid = 1440.0 * _rate("USD", base)
    at = pd.Timestamp("2024-01-04")
    assert hist.loc[at, "injected"] == pytest.approx(paid)
    assert hist.loc[at, "value"] == pytest.approx(paid)
    assert hist.loc[at, "pnl_pct"] == pytest.approx(0.0, abs=1e-12)
    assert twr.loc[:at].abs().max() == pytest.approx(0.0, abs=1e-12)

    last = hist["value"].iloc[-1]
    assert last == pytest.approx(1400.0 * _rate("EUR", base))
    assert hist["pnl_pct"].iloc[-1] == pytest.approx(1400.0 / 1296.0 - 1)


def test_injected_vs_value_without_units_keeps_the_ledger_reading():
    """The pure replay's contract is unchanged for a caller that passes no
    listing answer: closes are read in the ledger row's currency."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    closes = {"ASML": pd.Series([700.0, 700.0], index=idx)}
    fx = {"USD": pd.Series({"2024-01-02": 0.9, "2024-01-03": 0.9})}
    to_eur = lambda amount, ccy, day: amount * TO_EUR[ccy]  # noqa: E731
    hist = ap.injected_vs_value(_asml_book(), closes, fx, to_base=to_eur)
    assert hist["value"].iloc[1] == pytest.approx(2 * 700 * 0.9)
    hist = ap.injected_vs_value(
        _asml_book(), closes, {**fx, "EUR": pd.Series(dtype=float)}, to_base=to_eur,
        units={"ASML": ("EUR", 1.0)},
    )
    assert hist["value"].iloc[1] == pytest.approx(1400.0)


def test_a_pence_listing_is_valued_in_pounds_in_the_history(fixed_fx):
    book = [Transaction("2024-01-02", "AZN.L", "buy", 10, 100.0, "GBP", 0.0)]
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    closes = {"AZN.L": pd.Series([10_000.0, 11_000.0], index=idx)}
    to_eur = lambda amount, ccy, day: amount * TO_EUR[ccy]  # noqa: E731
    fx = {"GBP": pd.Series({"2024-01-02": 1.2, "2024-01-03": 1.2})}
    hist = ap.injected_vs_value(
        book, closes, fx, to_base=to_eur, units={"AZN.L": ("GBP", 0.01)}
    )
    assert hist.loc[pd.Timestamp("2024-01-02"), "pnl_pct"] == pytest.approx(0.0)
    assert hist.loc[pd.Timestamp("2024-01-03"), "value"] == pytest.approx(1320.0)


# ----------------------------------------------------- the ticker page's view


REVOLUT_ASML = [
    Transaction("2024-10-24", "ASML", "buy", 2, 720.0, "USD", 1.5),
    Transaction("2025-11-13", "ASML", "buy", 1, 690.0, "USD", 1.5),
    Transaction("2025-01-02", "AAPL", "buy", 1, 200.0, "USD", 0.0),
]


def _dated_usd(monkeypatch):
    rates = {"2024-10-24": 0.9, "2025-11-13": 0.86}
    monkeypatch.setattr(
        "stocks.data.fx.rate_on",
        lambda day, ccy, base: rates[str(day)] if ccy == "USD" else _rate(ccy, base),
    )


def test_the_chart_view_restates_basis_and_fills_at_each_trade_dates_rate(
    monkeypatch,
):
    from stocks.portfolio.corporate import own_fills
    from stocks.portfolio.positions import build

    _dated_usd(monkeypatch)
    held = build(REVOLUT_ASML, to_base=lambda a, c, d: a)[0]
    asml = next(p for p in held if p.ticker == "ASML")
    assert asml.cost_native == pytest.approx(1441.5 + 691.5)

    restated = listing.restate_position(asml, REVOLUT_ASML, "EUR")
    assert restated.currency == "EUR"
    assert restated.quantity == 3.0
    assert restated.cost_native == pytest.approx(1441.5 * 0.9 + 691.5 * 0.86)
    assert restated.cost == asml.cost, "the reporting basis is not touched"

    fills = own_fills(listing.restate_trades(REVOLUT_ASML, "ASML", "EUR"), "ASML")
    assert [f.price for f in fills] == pytest.approx([720 * 0.9, 690 * 0.86])
    # Another name's rows pass through as they were.
    rows = listing.restate_trades(REVOLUT_ASML, "ASML", "EUR")
    assert rows[2].price == 200.0 and rows[2].currency == "USD"


def test_the_chart_view_is_untouched_when_the_listing_agrees_or_is_unknown():
    pos = Position("AAPL", 1.0, cost=180.0, cost_native=200.0, currency="USD")
    assert listing.restate_position(pos, REVOLUT_ASML, "USD") is pos
    assert listing.restate_position(pos, REVOLUT_ASML, None) is pos


def test_a_pence_chart_gets_a_pence_basis():
    book = [Transaction("2024-01-02", "VOD.L", "buy", 100, 0.70, "GBP", 0.0)]
    pos = Position("VOD.L", 100.0, cost=84.0, cost_native=70.0, currency="GBP")
    restated = listing.restate_position(pos, book, "GBp")
    assert restated.currency == "GBp"
    assert restated.avg_cost_native == pytest.approx(70.0)  # pence
    fills = listing.restate_trades(book, "VOD.L", "GBp")
    assert fills[0].price == pytest.approx(70.0)


def test_a_missing_rate_keeps_the_trade_currency(monkeypatch):
    def down(*a, **k):
        raise RuntimeError("ECB down")

    monkeypatch.setattr("stocks.data.fx.rate_on", down)
    pos = Position("ASML", 3.0, cost=0.0, cost_native=2133.0, currency="USD")
    assert listing.restate_position(pos, REVOLUT_ASML, "EUR") is pos
    rows = listing.restate_trades(REVOLUT_ASML, "ASML", "EUR")
    assert [r.currency for r in rows] == ["USD", "USD", "USD"]
