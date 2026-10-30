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

from stocks import obs
from stocks.config import load_watchlist
from stocks.data.dividends import DividendEvent, upcoming_ex_dividends
from stocks.data.earnings import EarningsEvent, calendar_events
from stocks.notify import links, render
from stocks.notify.digest import (
    BENCHMARK,
    BENCHMARK_LABEL,
    money_changes,
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
    # {days: index % change} over the same windows, in the index's currency.
    benchmark: dict[int, float | None] = field(default_factory=dict)
    # (ticker, money, pct) over the week, best first / worst first.
    best: list[tuple[str, float, float | None]] = field(default_factory=list)
    worst: list[tuple[str, float, float | None]] = field(default_factory=list)
    dividends_received: tuple[float, int] | None = None
    ex_dividends: list[DividendEvent] = field(default_factory=list)
    dividend_cash: dict[str, float] = field(default_factory=dict)
    earnings: list[EarningsEvent] = field(default_factory=list)
    top_weight: float | None = None  # top TOP_N names as a share of the book
    effective_names: float | None = None  # 1/HHI — equal-sized-name equivalent
    drift: float | None = None  # top_weight minus last Sunday's
    highlight: str | None = None
    currency: str = "EUR"

    @property
    def ytd_days(self) -> int:
        """Calendar days back to 1 January — the YTD window for money_change."""
        return (self.date - date(self.date.year, 1, 1)).days


def compute_weekly_data(
    watchlist: Path, db: Path, base: str = "EUR", today: date | None = None
) -> WeeklyData:
    """Gather one account's weekly review, in `base`. Sections fail alone."""
    from stocks.analysis.portfolio import (
        effective_positions,
        load_closes,
        position_value_frames,
        ticker_changes,
        ticker_money_changes,
        top_n_weight,
    )

    data = WeeklyData(date=today or date.today(), currency=base)
    holdings = load_watchlist(watchlist)

    positions = []
    txs: list[Transaction] = []
    try:
        txs = all_transactions(db)
        if txs:
            positions, _ = build(txs, base=base)
    except Exception:
        positions = []
    if not positions:
        # A watchlist has no book to review — the daily digest is the right
        # message for that account, and this one has nothing to say.
        return data

    with obs.swallow("weekly.position_values", positions=len(positions)):
        # The week's movers and today's weights: a month of closes covers both.
        values, _ = position_value_frames(positions, period="1mo", base=base)
        if not values.empty:
            last = values.iloc[-1].dropna()
            data.total = float(last.sum()) if not last.empty else None
            data.best, data.worst = _week_movers(
                ticker_money_changes(values, WEEK), ticker_changes(values, WEEK)
            )
            if data.total:
                weights = {str(t): float(v) / data.total for t, v in last.items()}
                data.top_weight = top_n_weight(weights, TOP_N)
                data.effective_names = effective_positions(weights)

    index = None
    with obs.swallow("weekly.benchmark", ticker=BENCHMARK):
        index = load_closes([BENCHMARK], period="1y").get(BENCHMARK)

    with obs.swallow("weekly.returns", positions=len(positions)):
        # On the book's own money, the index bought with the same deposits on
        # the same days: a deposit in March is not a year-to-date gain, and a
        # good spring on 5,000 € is not one on 100,000 € (`money_changes`).
        windows = [WEEK, MONTH, data.ytd_days]
        changes, same = money_changes(txs, base, windows, index)
        data.week, data.month = changes[WEEK], changes[MONTH]
        data.ytd = changes[data.ytd_days]
        if data.week is not None:
            data.benchmark = same

    tickers = [p.ticker for p in positions]
    with obs.swallow("weekly.earnings"):
        events, _ = calendar_events(holdings, ref=data.date)
        data.earnings = [
            e for e in events if e.days_until is not None and e.days_until <= WEEK
        ]

    with obs.swallow("weekly.ex_dividends", tickers=len(tickers)):
        data.ex_dividends = upcoming_ex_dividends(
            tickers, within_days=WEEK, ref=data.date
        )
        data.dividend_cash = _dividend_cash(data.ex_dividends, positions, base)

    with obs.swallow("weekly.dividends_received"):
        data.dividends_received = recent_dividends(
            txs, base, within_days=WEEK, today=data.date
        )

    return data


def _week_movers(
    contributions, percents
) -> tuple[list[tuple[str, float, float | None]], list[tuple[str, float, float | None]]]:
    """(best, worst) names of the week, ranked by money and carrying the percent."""
    pcts = {str(t): float(v) for t, v in percents.items()}
    rows = [
        (str(t), float(v), pcts.get(str(t)))
        for t, v in contributions.items()
    ]
    ranked = sorted(rows, key=lambda r: r[1], reverse=True)
    best = [r for r in ranked if r[1] > 0][:NAMES_SHOWN]
    worst = [r for r in reversed(ranked) if r[1] < 0][:NAMES_SHOWN]
    return best, worst


def _dividend_cash(
    events: list[DividendEvent], positions, base: str
) -> dict[str, float]:
    """Estimated gross cash per upcoming ex-date, in `base`, keyed by ticker."""
    from stocks.notify.digest import _dividend_cash as shared

    return shared(events, positions, base)


# ---------------------------------------------------------------- rendering


def _window_line(data: WeeklyData, tr) -> str | None:
    """'Month +3,100 € (+3.02%) · YTD …' — the horizons the title leaves out."""
    parts = [
        f"{tr(key)} {delta(*value, data.currency)}"
        for key, value in (("month", data.month), ("ytd", data.ytd))
        if value is not None
    ]
    return " · ".join(parts) if parts else None


def _benchmark_line(data: WeeklyData, tr) -> str | None:
    """'vs S&P 500 · week +1.10% · YTD +9.80%' — the same windows, the index."""
    labels = {WEEK: "week", MONTH: "month", data.ytd_days: "ytd"}
    parts = [
        f"{tr(labels[days])} {pct * 100:+.2f}%"
        for days, pct in data.benchmark.items()
        if pct is not None and days in labels
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


def weekly_message(data: WeeklyData, lang: str) -> dict:
    """The review as a push (`render.message`): the week and the book in the
    title, then the longer horizons, the names behind the week and the
    narrated line. The tap opens the portfolio."""
    from stocks.web.i18n import translate

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
    lines = [
        _window_line(data, tr),
        _names_line(data),
        data.highlight,
        _concentration_line(data, tr),
        _dividends_line(data, tr),
        _ahead_line(data, lang, tr),
        _benchmark_line(data, tr),
    ]
    return render.message(title, lines, links.path(links.PORTFOLIO), "weekly")


# ------------------------------------------------------------------ fan-out


def run_weekly_fanout(dry_run: bool = False) -> dict[str, str]:
    """Compute and push every subscriber's weekly review. {label: status}."""
    from stocks.notify import narrative, webpush
    from stocks.notify.fanout import iter_notify_users
    from stocks.notify.state import (
        load_state,
        previous_top_weight,
        remember_top_weight,
        save_state,
    )

    now = datetime.now(UTC)
    status: dict[str, str] = {}
    for user in iter_notify_users("weekly"):
        try:
            state = load_state(user.state_path)
            base = str(user.prefs.get("currency") or "EUR").upper()
            data = compute_weekly_data(user.watchlist, user.db, base)
            if data.total is None:
                status[user.label] = "skipped: no book"
                continue
            if data.top_weight is not None:
                previous = previous_top_weight(state)
                data.drift = (
                    data.top_weight - previous if previous is not None else None
                )
            data.highlight = narrative.weekly_line(data, user.prefs, user.lang,
                                                   memories=user.memories())
            message = weekly_message(data, user.lang)
            if dry_run:
                print(f"── {user.label} ──\n{message['title']}\n{message['body']}\n")
                status[user.label] = "dry-run"
                continue
            took = webpush.send_all(user.push_path, message, topic="weekly")
            status[user.label] = f"sent {took}" if took else "not delivered"
            # Only a delivered review moves the concentration baseline: a push
            # that reached no device must not make next Sunday's drift measure
            # from a week the reader never saw.
            if took and data.top_weight is not None:
                remember_top_weight(state, data.top_weight, now)
                save_state(state, user.state_path)
        except Exception as exc:  # noqa: BLE001 — cron isolation per account
            status[user.label] = f"error: {exc}"
    return status
