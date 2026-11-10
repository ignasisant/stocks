"""The week's numbers behind the Friday email and the dormant nudge.

The daily briefing answers "what happened"; this takes the longer view off the
same analytics and the same one-fetch-per-account discipline:

* week, month, year-to-date and since the book's first day in money and
  percent, each against the index bought with the same money;
* the names that actually moved the book over the week, by contribution;
* the cash that landed and the calendar for the week ahead;
* how concentrated the book has become.

`compute_weekly_data` does the network work and every section fails alone: a
throttled earnings lookup drops the week-ahead section and the rest still
reads. There is no push of its own any more (the Sunday review was retired
with the evening digest, `notify/schedule.py`): `notify/weekly_email.py`
renders it and `notify/nudge.py` borrows the book's week for its reminder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stocks import obs
from stocks.config import Holding
from stocks.data.dividends import DividendEvent, upcoming_ex_dividends
from stocks.data.earnings import EarningsEvent, calendar_events
from stocks.portfolio.ledger import Transaction, all_transactions
from stocks.portfolio.positions import build

# What the book is measured against. Read off daily closes like the portfolio
# figure, but in the book's own currency (`index_closes`): the gap therefore
# excludes the exchange rate's leg, which is the comparison a reader means when
# they ask whether they beat the index.
BENCHMARK = "SPY"
BENCHMARK_LABEL = "S&P 500"

WEEK = 7
MONTH = 30
NAMES_SHOWN = 3
TOP_N = 5


@dataclass
class WeeklyData:
    date: date
    total: float | None = None
    week: tuple[float, float] | None = None  # (change, pct)
    month: tuple[float, float] | None = None
    ytd: tuple[float, float] | None = None
    # From the book's first day (`today_sections.book_start`): the span every
    # comparison against an index opens on, so a later window cannot forgive
    # what the picks lost before it.
    since: tuple[float, float] | None = None
    start: date | None = None
    # {days: index % change} over the same windows, on the book's own money
    # and in its currency; a window the index cannot cover in it is None.
    benchmark: dict[int, float | None] = field(default_factory=dict)
    # {days: gain} the same money made in the index, beside `benchmark`.
    benchmark_gain: dict[int, float] = field(default_factory=dict)
    # (ticker, money, pct) over the week, best first / worst first.
    best: list[tuple[str, float, float | None]] = field(default_factory=list)
    worst: list[tuple[str, float, float | None]] = field(default_factory=list)
    dividends_received: tuple[float, int] | None = None
    ex_dividends: list[DividendEvent] = field(default_factory=list)
    dividend_cash: dict[str, float] = field(default_factory=dict)
    earnings: list[EarningsEvent] = field(default_factory=list)
    top_weight: float | None = None  # top TOP_N names as a share of the book
    effective_names: float | None = None  # 1/HHI — equal-sized-name equivalent
    largest: tuple[str, float] | None = None  # (ticker, weight)
    currency: str = "EUR"
    # Held names with no usable price, carried at cost in `total`: a total
    # that quietly drops part of the book is a lie in smaller print.
    missing: list[str] = field(default_factory=list)
    # The index's last session: the close every figure here is as of.
    as_of: date | None = None
    # What the email reads beyond the headline figures, kept off the dataclass's face.
    hist: pd.DataFrame | None = field(default=None, repr=False, compare=False)
    transactions: list = field(default_factory=list, repr=False, compare=False)
    realized: list = field(default_factory=list, repr=False, compare=False)

    @property
    def ytd_days(self) -> int:
        """Calendar days back to 1 January — the YTD window for money_change."""
        return (self.date - date(self.date.year, 1, 1)).days

    @property
    def since_days(self) -> int | None:
        """Calendar days back to the book's first day — its since-start window."""
        return (self.date - self.start).days if self.start else None


def index_closes(base: str, first) -> pd.Series | None:
    """The S&P 500 (SPY) in `base` from the book's first day, or None.

    The cached card download (`api.briefing.closes_since`), converted the way
    Today converts it: euros through the downloaded pair, any other base at the
    daily rate the book is valued at. Never the dollar series beside a euro
    book: a gap that is the exchange rate's is not the picks'.
    """
    from stocks.chat import daily_book
    from stocks.views.briefing import closes_since

    return daily_book.index_in_currency(closes_since(first), base)


def compute_weekly_data(
    watchlist: Path, db: Path, base: str = "EUR", today: date | None = None
) -> WeeklyData:
    """Gather one account's weekly review, in `base`. Sections fail alone.

    Every book figure reads one `book_history`: the total, the windows, the
    names behind the week and the weights are the same valuation, so they add
    up — a name without a price is carried at cost in all of them and listed
    in `missing`."""
    from stocks.analysis.portfolio import book_history, effective_positions, top_n_weight

    data = WeeklyData(date=today or date.today(), currency=base)

    positions = []
    txs: list[Transaction] = []
    try:
        txs = all_transactions(db)
        if txs:
            positions, data.realized = build(txs, base=base)
    except Exception:
        positions = []
    if not positions:
        # A watchlist has no book to review: nothing to say for this account.
        return data
    data.transactions = txs

    hist = None
    with obs.swallow("weekly.book", positions=len(positions)):
        hist, _twr, missing = book_history(txs, base)
        if hist.empty:
            hist = None
        else:
            data.hist = hist
            data.missing = sorted(missing)
            data.total = float(hist["value"].iloc[-1])

    if hist is not None:
        with obs.swallow("weekly.movers"):
            data.best, data.worst = _week_movers(hist, txs, base)
        with obs.swallow("weekly.weights"):
            weights = _weights(hist)
            if weights:
                data.top_weight = top_n_weight(weights, TOP_N)
                data.effective_names = effective_positions(weights)
                data.largest = max(weights.items(), key=lambda kv: kv[1])
        with obs.swallow("weekly.returns"):
            _windows(data, hist, base)

    held = [p.ticker for p in positions if p.quantity > 0]
    with obs.swallow("weekly.earnings"):
        # The book's own names: a print on a name merely followed is not this
        # book's week ahead.
        events, _ = calendar_events([Holding(ticker=t) for t in held], ref=data.date)
        data.earnings = [
            e for e in events if e.days_until is not None and e.days_until <= WEEK
        ]

    with obs.swallow("weekly.ex_dividends", tickers=len(held)):
        data.ex_dividends = upcoming_ex_dividends(
            held, within_days=WEEK, ref=data.date
        )
        data.dividend_cash = dividend_cash(data.ex_dividends, positions, base)

    with obs.swallow("weekly.dividends_received"):
        data.dividends_received = recent_dividends(
            txs, base, within_days=WEEK, today=data.date
        )

    return data


def _windows(data: WeeklyData, hist: pd.DataFrame, base: str) -> None:
    """Week, month, YTD and since the book's first day, each beside the index
    bought with the same money on the same days (`index_change`)."""
    from stocks.analysis.portfolio import index_change, money_change
    from stocks.chat.today_sections import book_start, reaching

    start = book_start(hist)
    data.start = start.date() if start is not None else None
    windows = [WEEK, MONTH, data.ytd_days]
    if data.since_days:
        windows.append(data.since_days)
    own = {days: money_change(hist, days) for days in windows}
    data.week, data.month, data.ytd = own[WEEK], own[MONTH], own[data.ytd_days]
    data.since = own.get(data.since_days) if data.since_days else None
    if data.week is None:
        return
    index = None
    with obs.swallow("weekly.benchmark", ticker=BENCHMARK):
        index = index_closes(base, start)
    if index is None:
        return
    data.as_of = index.index[-1].date()
    # Read from the book's first day, or from its first close within a few
    # days after: a download opens a session or so late.
    reached = reaching(index, start)
    if reached is not None:
        index = reached
    for days in windows:
        change = index_change(hist, index, days)
        data.benchmark[days] = None if change is None else change[1]
        if change is not None:
            data.benchmark_gain[days] = change[0]


def _week_movers(
    hist: pd.DataFrame, txs, base: str
) -> tuple[list[tuple[str, float, float | None]], list[tuple[str, float, float | None]]]:
    """(best, worst) names of the week by what each added to the book.

    `return_attribution` over the week's window: a name's move net of the
    money put into it, so a name bought on Wednesday counts from Wednesday and
    its purchase is not its gain. The percent beside it is its price over the
    days it was held, in its own currency."""
    from stocks.analysis.portfolio import window_span
    from stocks.analysis.return_attribution import attribution

    span = window_span(pd.DatetimeIndex(hist.index), WEEK)
    if span is None:
        return [], []
    split = attribution(hist, txs, start=span[0], base=base)
    if split is None:
        return [], []
    legs = hist.attrs.get("legs") or {}
    rows = [
        (str(t), float(v), _held_move(legs.get(t), span))
        for t, v in split.movers.items()
    ]
    ranked = sorted(rows, key=lambda r: r[1], reverse=True)
    best = [r for r in ranked if r[1] > 0][:NAMES_SHOWN]
    worst = [r for r in reversed(ranked) if r[1] < 0][:NAMES_SHOWN]
    return best, worst


def _held_move(leg, span) -> float | None:
    """The price move of `leg` over `span`, from the later of its open and the
    first day shares were held in it; None without a price at both ends."""
    if leg is None or leg.px is None:
        return None
    start, end = span
    held = leg.shares[(leg.shares.index >= start) & (leg.shares.index <= end)]
    held = held[held > 0]
    if held.empty:
        return None
    opened = held.index[0]
    if opened > start:
        # Bought inside the week: its first held close is where it starts.
        start = opened
    marked = leg.marked
    if not (bool(marked.get(start, False)) and bool(marked.get(end, False))):
        return None
    first, last = float(leg.px.loc[start]), float(leg.px.loc[end])
    return last / first - 1 if first else None


def _weights(hist: pd.DataFrame) -> dict[str, float]:
    """{ticker: share of the book} on its last day, off the same legs as the
    total — an unpriced name at its cost, as it is counted there."""
    legs = hist.attrs.get("legs") or {}
    total = float(hist["value"].iloc[-1])
    if not total:
        return {}
    last = {str(t): float(leg.value.iloc[-1]) for t, leg in legs.items()}
    return {t: v / total for t, v in last.items() if v > 0}


def recent_dividends(
    transactions: list[Transaction],
    base: str = "EUR",
    within_days: int = WEEK,
    today: date | None = None,
    to_base=None,
) -> tuple[float, int] | None:
    """(net cash in `base`, payment count) booked in the last `within_days`.

    Net, not gross: what the reader saw arrive is the gross dividend less the
    tax withheld at source, which is the ledger's `price - fee` convention (see
    stocks.portfolio.dividends). None when nothing was booked in the window.
    """
    from stocks.data.fx import converter, prefetch

    today = today or date.today()
    floor = (today - timedelta(days=within_days)).isoformat()
    rows = [
        t for t in transactions
        if t.action == "dividend" and floor <= t.date[:10] <= today.isoformat()
    ]
    if not rows:
        return None
    if to_base is None:
        prefetch((t.date, t.currency) for t in rows)
        to_base = converter(base)
    total = sum(to_base(t.price - t.fee, t.currency, t.date) for t in rows)
    return float(total), len(rows)


def dividend_cash(
    events: list[DividendEvent], positions, base: str
) -> dict[str, float]:
    """Estimated gross cash per upcoming ex-date, in `base`, keyed by ticker.

    Only for tickers actually held: a watchlist name goes ex too, but there is
    no quantity to multiply, so those events have no figure.
    """
    from stocks.data.fx import to_base

    held = {p.ticker: p for p in positions}
    today = date.today().isoformat()
    cash: dict[str, float] = {}
    for event in events:
        position = held.get(event.ticker)
        if position is None:
            continue
        native = event.cash(position.quantity)
        if native is None:
            continue
        currency = event.currency or position.currency
        try:
            cash[event.ticker] = to_base(native, currency, today, base)
        except Exception:
            continue
    return cash
