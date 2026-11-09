"""Weekly review — the Sunday counterpart to the daily digest.

The digest answers "what happened today"; five of them in a row still never
answer "how is this going". This job takes the longer view once a week, off
the same analytics and the same one-fetch-per-account discipline:

* week, month and year-to-date in money and percent, each against the index;
* the names that actually moved the book over the week, by contribution;
* the cash that landed and the calendar for the week ahead;
* how concentrated the book has become, and — the part a single figure can't
  say — which way that drifted since last Sunday.

`compute_weekly_data` does the network work, `weekly_message` is pure text and
tests offline, and every section fails alone: a throttled earnings lookup
drops the week-ahead line and the review still sends. It goes out as a Web
Push notification, so it is a headline: the week in the title, the longer
horizons and the names behind the week underneath, and the tap opens the
portfolio for the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from stocks import obs
from stocks.config import Holding
from stocks.data.dividends import DividendEvent, upcoming_ex_dividends
from stocks.data.earnings import EarningsEvent, calendar_events
from stocks.notify import links, render
from stocks.notify.digest import (
    BENCHMARK,
    BENCHMARK_LABEL,
    dividend_cash,
    recent_dividends,
)
from stocks.notify.render import date_line, delta, money, signed
from stocks.portfolio.ledger import Transaction, all_transactions
from stocks.portfolio.positions import build

WEEK = 7
MONTH = 30
NAMES_SHOWN = 3
TOP_N = 5
# A concentration move smaller than this is the market re-pricing the book, not
# the reader changing it — reporting it weekly would be reporting noise.
DRIFT_FLOOR = 0.01


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
    drift: float | None = None  # top_weight minus last Sunday's
    highlight: str | None = None
    currency: str = "EUR"
    # Held names with no usable price, carried at cost in `total`: a total
    # that quietly drops part of the book is a lie in smaller print.
    missing: list[str] = field(default_factory=list)
    # The index's last session: the close every figure here is as of.
    as_of: date | None = None
    # What the email reads beyond the push, kept off the dataclass's face.
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
        # A watchlist has no book to review — the daily digest is the right
        # message for that account, and this one has nothing to say.
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
        # The book's own names: a print on a name merely followed is the
        # digest's news, not this book's week ahead.
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


# ---------------------------------------------------------------- rendering


def _window_line(data: WeeklyData, tr) -> str | None:
    """'Since start +9,800 € (+12.40%) · Month … · YTD …' — the horizons the
    title leaves out, the book's whole span first."""
    parts = [
        f"{tr(key)} {delta(*value, data.currency)}"
        for key, value in (
            ("since_start", data.since), ("month", data.month), ("ytd", data.ytd)
        )
        if value is not None
    ]
    return " · ".join(parts) if parts else None


def _benchmark_line(data: WeeklyData, tr) -> str | None:
    """'vs S&P 500 · since start +31.20% · week +1.10% · …' — the same
    windows, the index; the span from the book's first day leads."""
    labels = {WEEK: "week", MONTH: "month", data.ytd_days: "ytd"}
    if data.since_days:
        labels = {data.since_days: "since_start", **labels}
    parts = [
        f"{tr(label)} {pct * 100:+.2f}%"
        for days, label in labels.items()
        if (pct := data.benchmark.get(days)) is not None
    ]
    if not parts:
        return None
    return f"{tr('vs')} {BENCHMARK_LABEL} · " + " · ".join(parts)


def _names_line(data: WeeklyData) -> str | None:
    """'▲ NVDA +300 € (+4.1%) · ▼ TSLA -120 € (-3.0%)': who made the week."""
    sides = []
    for rows, marker in ((data.best, "▲"), (data.worst, "▼")):
        if not rows:
            continue
        ticker, amount, pct = rows[0]
        side = f"{marker} {ticker} {signed(amount, data.currency)}"
        if pct is not None:
            side += f" ({pct * 100:+.1f}%)"
        sides.append(side)
    return " · ".join(sides) or None


def _ahead_line(data: WeeklyData, lang: str, tr) -> str | None:
    """Prints and ex-dates in one line, soonest first — it is one week ahead."""
    entries: list[tuple[int, str]] = []
    for event in data.earnings:
        # An undated event cannot be placed in a week-ahead list; the calendar
        # only derives `days_until` from a date, so this drops nothing real.
        if event.date is None:
            continue
        entries.append((
            event.days_until or 0,
            f"{event.ticker} {tr('earnings_word')} {date_line(event.date, lang)}",
        ))
    for div in data.ex_dividends:
        line = f"{div.ticker} {tr('ex_date')} {date_line(div.ex_date, lang)}"
        if cash := data.dividend_cash.get(div.ticker):
            line += f" ~{money(cash, data.currency)}"
        entries.append((div.days_until, line))
    if not entries:
        return None
    ordered = [line for _, line in sorted(entries, key=lambda e: e[0])]
    return f"{tr('week_ahead')}: " + ", ".join(ordered)


def _dividends_line(data: WeeklyData, tr) -> str | None:
    if not data.dividends_received:
        return None
    amount, count = data.dividends_received
    if count == 1:
        return tr("div_week_one", amount=money(amount, data.currency))
    return tr("div_week", amount=money(amount, data.currency), count=count)


def _concentration_line(data: WeeklyData, tr) -> str | None:
    """'Top 5 = 68% of the book (+3 pt this week) · like 6.2 equal names'."""
    if data.top_weight is None:
        return None
    line = tr("concentration", n=TOP_N, pct=f"{data.top_weight * 100:.0f}")
    if data.drift is not None and abs(data.drift) >= DRIFT_FLOOR:
        line += " " + tr("drift", pts=f"{data.drift * 100:+.0f}")
    if data.effective_names is not None and data.effective_names == data.effective_names:
        line += " · " + tr("effective", n=f"{data.effective_names:.1f}")
    return line


def _weekly_parts(data: WeeklyData, lang: str) -> tuple[str, list[str | None]]:
    """The review's title and its lines in reading order: the push shows the
    first few, the scheduled thread every one."""
    from stocks.i18n import translate

    def tr(key: str, **kw) -> str:
        return translate(f"notify.{key}", lang, **kw)

    if data.total is not None and data.week is not None:
        title = tr(
            "weekly_title_book",
            change=delta(*data.week, data.currency),
            value=money(data.total, data.currency),
        )
    else:
        title = f"{tr('weekly_title')} · {date_line(data.date, lang)}"
    return title, [
        _window_line(data, tr),
        _names_line(data),
        data.highlight,
        _concentration_line(data, tr),
        _dividends_line(data, tr),
        _ahead_line(data, lang, tr),
        _benchmark_line(data, tr),
    ]


def weekly_message(data: WeeklyData, lang: str, url: str | None = None) -> dict:
    """The review as a push (`render.message`): the week and the book in the
    title, then the longer horizons, the names behind the week and the
    narrated line. The tap opens `url` — the run's thread when it was filed
    (`notify/schedule.py`) — else the portfolio."""
    title, lines = _weekly_parts(data, lang)
    return render.message(title, lines, url or links.path(links.PORTFOLIO), "weekly")


def weekly_markdown(data: WeeklyData, lang: str) -> str:
    """The whole review as the chat turn it is filed as."""
    title, lines = _weekly_parts(data, lang)
    return render.markdown(title, lines)


# ------------------------------------------------------------------ fan-out


def build_weekly(user, state: dict) -> WeeklyData | str:
    """One account's review, narrated, or why there is none ("no book")."""
    from stocks.notify import narrative
    from stocks.notify.state import previous_top_weight

    base = str(user.prefs.get("currency") or "EUR").upper()
    data = compute_weekly_data(user.watchlist, user.db, base)
    if data.total is None:
        return "no book"
    if data.top_weight is not None:
        previous = previous_top_weight(state)
        data.drift = data.top_weight - previous if previous is not None else None
    data.highlight = narrative.weekly_line(data, user.prefs, user.lang,
                                           memories=user.memories())
    return data


def weekly_delivered(user, state: dict, data: WeeklyData) -> None:
    """Only a delivered review moves the concentration baseline: a push that
    reached no device must not make next week's drift measure from a week the
    reader never saw."""
    from stocks.notify.state import remember_top_weight, save_state

    if data.top_weight is not None:
        remember_top_weight(state, data.top_weight, datetime.now(UTC))
        save_state(state, user.state_path, only=("weekly",))


def run_weekly_fanout(dry_run: bool = False) -> dict[str, str]:
    """Compute and push every subscriber's weekly review. {label: status}.

    By hand (`stocks weekly`): the scheduled run is the app's own
    (`notify/schedule.py`), which files it in the chat as well."""
    from stocks.notify import webpush
    from stocks.notify.fanout import iter_notify_users
    from stocks.notify.state import load_state

    status: dict[str, str] = {}
    for user in iter_notify_users("weekly"):
        try:
            state = load_state(user.state_path)
            data = build_weekly(user, state)
            if isinstance(data, str):
                status[user.label] = f"skipped: {data}"
                continue
            message = weekly_message(data, user.lang)
            if dry_run:
                print(f"── {user.label} ──\n{message['title']}\n{message['body']}\n")
                status[user.label] = "dry-run"
                continue
            took = webpush.send_all(user.push_path, message, topic="weekly")
            status[user.label] = f"sent {took}" if took else "not delivered"
            if took:
                weekly_delivered(user, state, data)
        except Exception as exc:  # noqa: BLE001 — cron isolation per account
            status[user.label] = f"error: {exc}"
    return status
