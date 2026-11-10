"""Splits end to end: a broker statement, Yahoo's split-adjusted closes, and
everything the book computes from them, checked against the market's truth.

Each piece had its own tests and the pieces still disagreed: the split rule
declined a name sold out before its split, the replay restated fills by the
ledger's split rows only, and a book whose AMZN, GOOGL and NVDA closed in
2022 had its 2021-22 history held at cost (prod 2026-11-10). No test ran
the whole path, so none saw it.

Here a synthetic market has a known as-traded price and known splits. The
statement prints the trades as the broker would (as traded, or restated for
the splits that had happened when it printed), the book repairs itself the
way the warm sweep does (`missing_splits`, rows appended), and then:

- the value path equals true shares x as-traded close on every day,
- no name is carried at cost,
- the open position is the true share count today, at its true cost,
- realized gains are the true money: a split moves no cash.

The scenarios name the corner cases one by one; the property at the end
draws books nobody thought to write.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from stocks.analysis.portfolio import injected_vs_value, plausible_closes
from stocks.portfolio.corporate import missing_splits
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import build

TICKER = "X"
START = date(2024, 1, 1)
DAYS = 60


def flat(amount: float, currency: str, day: str) -> float:
    return amount


def _day(i: int) -> str:
    return (START + timedelta(days=i)).isoformat()


@dataclass(frozen=True)
class Market:
    """A name trading every day, splitting at the open of `splits` days."""

    splits: tuple[tuple[int, float], ...]

    def raw(self, i: int) -> float:
        """The close as it printed that day: a slow drift, cut by each split."""
        before = 100.0 * (1 + 0.002 * i)
        return before / math.prod(r for d, r in self.splits if d <= i)

    def adjusted(self, i: int) -> float:
        """Yahoo's close: every later split folded back into it."""
        return self.raw(i) / math.prod(r for d, r in self.splits if d > i)

    def closes(self) -> pd.Series:
        idx = pd.date_range(START, periods=DAYS, freq="D")
        return pd.Series([self.adjusted(i) for i in range(DAYS)], index=idx)

    def lookups(self):
        events = [(_day(d), r) for d, r in self.splits]

        def close_on(ticker, day):
            i = (date.fromisoformat(day) - START).days
            return self.adjusted(i) if 0 <= i < DAYS else None

        return (lambda ticker: list(events)), close_on


# A trade in the shares that existed that day: (day, "buy" | "sell", qty).
Trade = tuple[int, str, float]


def _truth(market: Market, trades: list[Trade]):
    """Shares held each day, open lots and realized gain, as the market had them.

    A split lands at the open, so a trade on its day is in post-split shares.
    """
    by_day: dict[int, list[Trade]] = {}
    for t in trades:
        by_day.setdefault(t[0], []).append(t)
    split_on = dict(market.splits)
    lots: list[list[float]] = []  # [shares, cost]
    held, realized = [], 0.0
    for i in range(DAYS):
        if i in split_on:
            for lot in lots:
                lot[0] *= split_on[i]
        for _, side, qty in by_day.get(i, []):
            px = market.raw(i)
            if side == "buy":
                lots.append([qty, qty * px])
                continue
            left = qty
            while left > 1e-12:
                lot = lots[0]
                take = min(left, lot[0])
                cost = lot[1] * take / lot[0]
                realized += take * px - cost
                lot[0] -= take
                lot[1] -= cost
                left -= take
                if lot[0] <= 1e-12:
                    lots.pop(0)
        held.append(sum(lot[0] for lot in lots))
    return held, sum(lot[1] for lot in lots), realized


def _statement(market: Market, trades: list[Trade], printed: int | None):
    """The broker's rows. `printed` None is as traded; a day restates every
    trade for the splits that had happened by then."""
    rows = []
    for n, (i, side, qty) in enumerate(trades):
        k = 1.0
        if printed is not None:
            k = math.prod(r for d, r in market.splits if i < d <= printed)
        rows.append(
            Transaction(
                date=_day(i), ticker=TICKER, action=side, quantity=qty * k,
                price=market.raw(i) / k, currency="USD", id=n + 1,
            )
        )
    return rows


def _check(market: Market, trades: list[Trade], printed=None, ledger_splits=()):
    """Run the book's whole path and hold it to the market's truth."""
    rows = _statement(market, trades, printed)
    rows += [
        Transaction(date=_day(d), ticker=TICKER, action="split", quantity=r,
                    currency="USD", id=1000 + d)
        for d, r in ledger_splits
    ]
    splits, close_on = market.lookups()
    gaps = missing_splits(rows, splits=splits, close_on=close_on)
    book = rows + [g.tx for g in gaps]

    held, open_cost, realized = _truth(market, trades)
    closes = plausible_closes({TICKER: market.closes()}, book, units={})
    df = injected_vs_value(book, closes, to_base=flat, base="USD")
    assert df.attrs["carried_at_cost"] == [], "a split left the name at cost"
    first = min(i for i, _, _ in trades)
    for i in range(first, DAYS):
        want = held[i] * market.raw(i)
        got = float(df["value"].loc[pd.Timestamp(_day(i))])
        assert got == pytest.approx(want, rel=1e-6, abs=1e-6), _day(i)

    positions, sales = build(book, to_base=flat, base="USD")
    have = {p.ticker: p for p in positions}
    if held[-1] > 1e-9:
        assert have[TICKER].quantity == pytest.approx(held[-1], rel=1e-9)
        assert have[TICKER].cost == pytest.approx(open_cost, rel=1e-9)
    else:
        assert TICKER not in have or have[TICKER].quantity == pytest.approx(0.0)
    assert sum(s.proceeds - s.cost for s in sales) == pytest.approx(
        realized, rel=1e-9, abs=1e-6
    )
    return gaps


FORWARD = Market(splits=((20, 20.0),))
TWO = Market(splits=((20, 4.0), (40, 10.0)))
REVERSE = Market(splits=((20, 1 / 30),))
BOTH_WAYS = Market(splits=((20, 10.0), (40, 1 / 5)))

# name: (market, trades). Quantities are the shares that existed on the day.
SCENARIOS = {
    "held through the split": (FORWARD, [(5, "buy", 1.0)]),
    "sold out before the split": (FORWARD, [(5, "buy", 1.0), (10, "sell", 1.0)]),
    "sold part before the split": (FORWARD, [(5, "buy", 3.0), (10, "sell", 1.0)]),
    "sold on the split day": (FORWARD, [(5, "buy", 1.0), (20, "sell", 20.0)]),
    "sold part after the split": (FORWARD, [(5, "buy", 2.0), (30, "sell", 15.0)]),
    "sold out after the split": (FORWARD, [(5, "buy", 1.0), (30, "sell", 20.0)]),
    "bought on the split day": (FORWARD, [(20, "buy", 20.0)]),
    "bought only after the split": (FORWARD, [(30, "buy", 5.0)]),
    "bought the day before the split": (FORWARD, [(19, "buy", 1.0)]),
    "sold out before, bought back after": (
        FORWARD, [(5, "buy", 1.0), (10, "sell", 1.0), (30, "buy", 7.0)],
    ),
    "sold out before, bought back after, sold again": (
        FORWARD,
        [(5, "buy", 1.0), (10, "sell", 1.0), (30, "buy", 7.0), (50, "sell", 7.0)],
    ),
    "bought on both sides, sold across": (
        FORWARD,
        [(5, "buy", 2.0), (25, "buy", 10.0), (35, "sell", 45.0)],
    ),
    "round trip before, round trip after": (
        FORWARD,
        [(5, "buy", 1.0), (10, "sell", 1.0), (30, "buy", 4.0), (35, "sell", 4.0)],
    ),
    "two splits, held through both": (TWO, [(5, "buy", 1.0)]),
    "two splits, sold out before both": (TWO, [(5, "buy", 2.0), (10, "sell", 2.0)]),
    "two splits, sold out between them": (TWO, [(5, "buy", 1.0), (30, "sell", 4.0)]),
    "two splits, bought between, held": (TWO, [(30, "buy", 3.0)]),
    "two splits, bought between, sold out before the second": (
        TWO, [(30, "buy", 3.0), (35, "sell", 3.0)],
    ),
    "two splits, sold part at each": (
        TWO, [(5, "buy", 2.0), (25, "sell", 4.0), (45, "sell", 10.0)],
    ),
    "reverse split, held through": (REVERSE, [(5, "buy", 300.0)]),
    "reverse split, sold out before": (
        REVERSE, [(5, "buy", 300.0), (10, "sell", 300.0)],
    ),
    "reverse split, sold after": (REVERSE, [(5, "buy", 300.0), (30, "sell", 6.0)]),
    "forward then reverse, held through": (BOTH_WAYS, [(5, "buy", 1.0)]),
    "forward then reverse, sold out before both": (
        BOTH_WAYS, [(5, "buy", 1.0), (10, "sell", 1.0)],
    ),
    "forward then reverse, sold out between": (
        BOTH_WAYS, [(5, "buy", 1.0), (30, "sell", 10.0)],
    ),
}


@pytest.mark.parametrize("printed", [None, 59], ids=["as traded", "restated"])
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_book_shape_reads_the_market(name, printed):
    market, trades = SCENARIOS[name]
    _check(market, trades, printed=printed)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_a_statement_printed_between_two_splits(name):
    """Restated for the splits before day 30, as traded for the rest."""
    market, trades = SCENARIOS[name]
    _check(market, trades, printed=30)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_split_rows_the_ledger_already_has_are_not_added_twice(name):
    market, trades = SCENARIOS[name]
    gaps = _check(market, trades, ledger_splits=market.splits)
    assert gaps == []


def test_the_prod_book_sold_out_before_both_nvda_splits():
    """Pau's NVDA: bought and sold in 2021 before the 4:1, then the 10:1 —
    every fill read the close 1/40 off and the series was rejected."""
    gaps = _check(TWO, [(3, "buy", 5.0), (8, "buy", 2.0), (12, "sell", 7.0)])
    assert [(g.tx.date, g.ratio) for g in gaps] == [(_day(20), 4.0), (_day(40), 10.0)]


CANCELLING = Market(splits=((20, 2.0), (40, 1 / 2)))


@pytest.mark.parametrize(
    "trades",
    [
        [(5, "buy", 1.0), (30, "buy", 1.0)],
        [(5, "buy", 1.0), (30, "sell", 2.0)],
    ],
    ids=["bought between", "sold between"],
)
def test_splits_that_cancel_out(trades):
    """2:1 then 1:2. A buy before both reads the close at face value, which
    fits both splits or neither; read alone, a trade between them proved the
    second only and the book got half the pair. The fit over every trade at
    once tells them apart."""
    _check(CANCELLING, trades)


# --------------------------------------------------------------- any book
RATIO = st.sampled_from([2.0, 3.0, 4.0, 10.0, 20.0, 1 / 2, 1 / 10, 1 / 30])


@st.composite
def book(draw):
    days = sorted(draw(st.sets(st.integers(1, DAYS - 1), min_size=0, max_size=2)))
    market = Market(splits=tuple((d, draw(RATIO)) for d in days))
    n = draw(st.integers(1, 8))
    trade_days = sorted(draw(st.lists(st.integers(0, DAYS - 1), min_size=n, max_size=n)))
    split_on = dict(market.splits)
    trades: list[Trade] = []
    held, last = 0.0, -1
    for i in trade_days:
        for d in range(last + 1, i + 1):
            held *= split_on.get(d, 1.0)
        last = i
        if held > 1e-9 and draw(st.booleans()):
            part = draw(st.sampled_from([0.25, 0.5, 1.0]))
            qty = held * part
            trades.append((i, "sell", qty))
            held -= qty
        else:
            qty = float(draw(st.integers(1, 50)))
            trades.append((i, "buy", qty))
            held += qty
    printed = draw(st.one_of(st.none(), st.integers(0, DAYS - 1)))
    return market, trades, printed


@settings(max_examples=300, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(book())
def test_any_book_reads_the_market(drawn):
    market, trades, printed = drawn
    assume(any(side == "buy" for _, side, _ in trades))
    _check(market, trades, printed=printed)
