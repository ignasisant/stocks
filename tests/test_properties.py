"""Properties the return and lot engines hold on any book, not just the ones
in the example tests.

Each one is a sentence an engine's docstring already claims, checked over
generated ledgers and value paths: a deposit cannot move the time-weighted
return, the money-weighted return is the time-weighted one when nothing
flows, the open lots are the position under every matching rule, and every
euro that bought a share is either still in a lot or in a realized sale.
The inconsistency log's "TWR jump" kind is what these are meant to keep
from coming back: a flow that is counted once in the value path and twice
in the flows would fail the first of them on the first example.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stocks.analysis.portfolio import money_weighted_return, time_weighted_returns
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import build, open_lots

# A day's price move. Bounded so a twenty-day path (0.9^19 to 1.1^19) stays
# inside the (-99.99%, 1000%) bracket the IRR bisection searches.
MOVE = st.floats(min_value=0.9, max_value=1.1, allow_nan=False, allow_infinity=False)
PRICE = st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False)
FEE = st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)


def flat(amount: float, currency: str, day: str) -> float:
    """No FX: the ledger is already in the reporting currency."""
    return amount


@st.composite
def price_path(draw, min_days: int = 2, max_days: int = 20) -> pd.Series:
    """A positive daily price series starting at 100."""
    moves = draw(st.lists(MOVE, min_size=min_days - 1, max_size=max_days - 1))
    prices = [100.0]
    for m in moves:
        prices.append(prices[-1] * m)
    idx = pd.date_range("2024-01-02", periods=len(prices), freq="D")
    return pd.Series(prices, index=idx)


@st.composite
def book_on_a_path(draw) -> tuple[pd.Series, pd.Series, pd.Series]:
    """A holding of one share class traded at the close: value path, external
    flows (buys +, sells −, at that day's price) and the price path itself.

    Shares never drop below one, so the book is never empty and every day
    has a prior value: the path's own return is the only thing left to see.
    """
    prices = draw(price_path())
    shares = draw(st.integers(min_value=1, max_value=1000))
    held = [shares]
    deltas = [0]
    for _ in range(len(prices) - 1):
        delta = draw(st.integers(min_value=-(held[-1] - 1), max_value=200))
        deltas.append(delta)
        held.append(held[-1] + delta)
    value = pd.Series([h * p for h, p in zip(held, prices, strict=True)],
                      index=prices.index)
    flows = pd.Series(
        {ts: d * p for ts, d, p in zip(prices.index, deltas, prices, strict=True) if d},
        dtype=float,
    )
    return value, flows, prices


@st.composite
def ledger(draw) -> list[Transaction]:
    """Buys and sells over one or two tickers, one a day, never overselling."""
    tickers = draw(st.sampled_from([("A",), ("A", "B")]))
    n = draw(st.integers(min_value=1, max_value=25))
    held = dict.fromkeys(tickers, 0.0)
    txs: list[Transaction] = []
    for i in range(n):
        day = (pd.Timestamp("2024-01-02") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        ticker = draw(st.sampled_from(tickers))
        can_sell = held[ticker] >= 1
        action = draw(st.sampled_from(["buy", "sell"] if can_sell else ["buy"]))
        if action == "buy":
            qty = draw(st.integers(min_value=1, max_value=100))
            held[ticker] += qty
        else:
            qty = draw(st.integers(min_value=1, max_value=int(held[ticker])))
            held[ticker] -= qty
        txs.append(Transaction(
            day, ticker, action, float(qty), draw(PRICE), "EUR", draw(FEE),
        ))
    return txs


# ------------------------------------------------------------------ returns


@settings(max_examples=200, deadline=None)
@given(book_on_a_path())
def test_twr_is_the_price_path_whatever_was_deposited_or_withdrawn(book):
    """Buying and selling shares at the close moves the value and the flows
    by the same amount, so the daily return is the price's and the compounded
    return is the price path's: deposit timing never reaches the TWR."""
    value, flows, prices = book
    r = time_weighted_returns(value, flows)
    assert r.attrs["dropped_days"] == []
    assert prices.index[0] not in r.index  # no prior value on day one
    expected = prices.pct_change().dropna()
    assert len(r) == len(expected)
    for ts, want in expected.items():
        assert r[ts] == pytest.approx(want, rel=1e-9, abs=1e-12)
    cumulative = float((1 + r).prod()) - 1
    assert cumulative == pytest.approx(prices.iloc[-1] / prices.iloc[0] - 1, rel=1e-9)


@settings(max_examples=200, deadline=None)
@given(price_path())
def test_irr_over_the_window_is_the_twr_when_nothing_flows(prices):
    """With no flows the investor's money and the strategy's are the same
    money, so the two readings agree: `annual=False` returns what the window
    made, which is what the daily returns compound to."""
    value = prices * 10
    none = pd.Series(dtype=float)
    twr = float((1 + time_weighted_returns(value, none)).prod()) - 1
    irr = money_weighted_return(value, none, annual=False)
    assert not math.isnan(irr)
    assert irr == pytest.approx(twr, rel=1e-6, abs=1e-9)


@settings(max_examples=100, deadline=None)
@given(book_on_a_path())
def test_irr_never_errors_and_is_a_rate_on_a_book_that_trades(book):
    """A positive book that traded at market prices always has a window rate
    the solver's bracket holds. Annualised, a short window's move can leave
    that bracket (-6% in a day is -100% a year): NaN then, never a raise."""
    value, flows, _ = book
    whole = money_weighted_return(value, flows, annual=False)
    assert not math.isnan(whole)
    assert -0.9999 < whole < 10.0
    annual = money_weighted_return(value, flows, annual=True)
    assert math.isnan(annual) or -0.9999 < annual < 10.0


# --------------------------------------------------------------------- lots


def _net(txs: list[Transaction]) -> dict[str, float]:
    held: dict[str, float] = {}
    for t in txs:
        signed = t.quantity if t.action == "buy" else -t.quantity
        held[t.ticker] = held.get(t.ticker, 0.0) + signed
    return {k: v for k, v in held.items() if v > 1e-9}


def _bought(txs: list[Transaction]) -> float:
    return sum(t.quantity * t.price + t.fee for t in txs if t.action == "buy")


def _sold(txs: list[Transaction]) -> float:
    return sum(t.quantity for t in txs if t.action == "sell")


@settings(max_examples=200, deadline=None)
@given(ledger(), st.sampled_from(["fifo", "lifo", "average", "s104"]))
def test_the_position_is_what_was_bought_less_what_was_sold(txs, matching):
    positions, realized = build(txs, to_base=flat, base="EUR", matching=matching)
    assert {p.ticker: p.quantity for p in positions} == pytest.approx(_net(txs))
    assert sum(s.quantity for s in realized) == pytest.approx(_sold(txs))
    assert all(p.quantity > 0 and p.cost >= 0 for p in positions)


@settings(max_examples=200, deadline=None)
@given(ledger(), st.sampled_from(["fifo", "lifo"]))
def test_the_open_lots_are_the_position(txs, matching):
    """What the tax page lists as parcels and what the portfolio page shows
    as the holding are the same shares carrying the same cost."""
    positions, _ = build(txs, to_base=flat, base="EUR", matching=matching)
    lots = open_lots(txs, flat, matching)
    by_ticker: dict[str, list] = {}
    for lot in lots:
        by_ticker.setdefault(lot.ticker, []).append(lot)
    assert set(by_ticker) == {p.ticker for p in positions}
    for p in positions:
        mine = by_ticker[p.ticker]
        assert sum(lot.quantity for lot in mine) == pytest.approx(p.quantity)
        assert sum(lot.cost for lot in mine) == pytest.approx(p.cost)
        assert all(lot.quantity > 1e-9 for lot in mine)


@settings(max_examples=200, deadline=None)
@given(ledger(), st.sampled_from(["fifo", "lifo", "average", "s104"]))
def test_every_euro_of_cost_is_in_a_lot_or_in_a_sale(txs, matching):
    """Cost is conserved: the buys' money (price plus fee) ends up either in
    the open position or in the basis of a realized sale, never lost or
    counted twice, under every matching rule."""
    positions, realized = build(txs, to_base=flat, base="EUR", matching=matching)
    kept = sum(p.cost for p in positions)
    gone = sum(s.cost for s in realized)
    assert kept + gone == pytest.approx(_bought(txs), rel=1e-9, abs=1e-6)
