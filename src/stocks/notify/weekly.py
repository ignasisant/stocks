"""Weekly review — the Sunday counterpart to the daily digest.

The digest answers "what happened today"; five of them in a row still never
answer "how is this going". This job takes the longer view once a week, off
the same analytics and the same one-fetch-per-account discipline:

* week, month and year-to-date in money and percent, each against the index;
* the names that actually moved the book over the week, by contribution;
* the cash that landed and the calendar for the week ahead;
* how concentrated the book has become, and — the part a single figure can't
  say — which way that drifted since last Sunday.

`compute_weekly_data` does the network work, `render_weekly` is pure text and
tests offline, and every section fails alone: a throttled earnings lookup
drops the week-ahead block and the review still sends.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from stocks import obs
from stocks.config import load_watchlist
from stocks.data.dividends import DividendEvent, upcoming_ex_dividends
from stocks.data.earnings import EarningsEvent, calendar_events
from stocks.notify import links
from stocks.notify.digest import BENCHMARK, BENCHMARK_LABEL, recent_dividends
from stocks.notify.render import (
    date_line,
    delta,
    esc,
    heading,
    money,
    signed,
    ticker_link,
)
from stocks.portfolio.ledger import Transaction, all_transactions
from stocks.portfolio.positions import build

WEEK = 7
MONTH = 30
NAMES_SHOWN = 3
AHEAD_SHOWN = 5
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
        """Calendar days back to 1 January — the YTD window for basket_change."""
        return (self.date - date(self.date.year, 1, 1)).days


def compute_weekly_data(
    watchlist: Path, db: Path, base: str = "EUR", today: date | None = None
) -> WeeklyData:
    """Gather one account's weekly review, in `base`. Sections fail alone."""
    from stocks.analysis.portfolio import (
        basket_change,
        benchmark_changes,
        effective_positions,
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
        # A year of history: YTD is the point of the message, and the month
        # and week windows read off the same frame for free.
        values, _ = position_value_frames(positions, period="1y", base=base)
        if not values.empty:
            last = values.iloc[-1].dropna()
            data.total = float(last.sum()) if not last.empty else None
            data.week = basket_change(values, WEEK)
            data.month = basket_change(values, MONTH)
            data.ytd = basket_change(values, data.ytd_days)
            data.best, data.worst = _week_movers(
                ticker_money_changes(values, WEEK), ticker_changes(values, WEEK)
            )
            if data.total:
                weights = {str(t): float(v) / data.total for t, v in last.items()}
                data.top_weight = top_n_weight(weights, TOP_N)
                data.effective_names = effective_positions(weights)

    if data.week is not None:
        with obs.swallow("weekly.benchmark", ticker=BENCHMARK):
            data.benchmark = benchmark_changes(
                [WEEK, MONTH, data.ytd_days], BENCHMARK
            )

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
    """'Week +1,940 € (+1.89%) · Month … · YTD …' — the three horizons."""
    parts = [
        f"{esc(tr(key))} {delta(*value, data.currency)}"
        for key, value in (
            ("week", data.week), ("month", data.month), ("ytd", data.ytd)
        )
        if value is not None
    ]
    return " · ".join(parts) if parts else None


def _benchmark_line(data: WeeklyData, tr) -> str | None:
    """'vs S&P 500 · week +1.10% · YTD +9.80%' — the same windows, the index."""
    labels = {WEEK: "week", MONTH: "month", data.ytd_days: "ytd"}
    parts = [
        f"{esc(tr(labels[days]))} {pct * 100:+.2f}%"
        for days, pct in data.benchmark.items()
        if pct is not None and days in labels
    ]
    if not parts:
        return None
    head = f"{esc(tr('vs'))} {esc(BENCHMARK_LABEL)}"
    return f"{head} · " + " · ".join(parts)


def _name_rows(
    rows: list[tuple[str, float, float | None]], marker: str, data: WeeklyData, base
) -> list[str]:
    out = []
    for ticker, amount, pct in rows:
        line = f"{marker} {ticker_link(ticker, base)} {signed(amount, data.currency)}"
        if pct is not None:
            line += f" ({pct * 100:+.1f}%)"
        out.append(line)
    return out


def _ahead_rows(data: WeeklyData, lang: str, tr, base) -> list[str]:
    """Prints and ex-dates in one list, soonest first — it is one week ahead."""
    entries: list[tuple[int, str]] = []
    for event in data.earnings:
        # An undated event cannot be placed in a week-ahead list; the calendar
        # only derives `days_until` from a date, so this drops nothing real.
        if event.date is None:
            continue
        entries.append((
            event.days_until or 0,
            f"• {ticker_link(event.ticker, base)} — {esc(tr('earnings_word'))} "
            f"{date_line(event.date, lang)} (T-{event.days_until})",
        ))
    for div in data.ex_dividends:
        line = (
            f"• {ticker_link(div.ticker, base)} — {esc(tr('ex_date'))} "
            f"{date_line(div.ex_date, lang)} (T-{div.days_until})"
        )
        if cash := data.dividend_cash.get(div.ticker):
            line += f" · ~{money(cash, data.currency)}"
        entries.append((div.days_until, line))
    return [line for _, line in sorted(entries, key=lambda e: e[0])][:AHEAD_SHOWN]


def _concentration_line(data: WeeklyData, tr) -> str | None:
    """'Top 5 = 68% of the book (+3 pt this week) · like 6.2 equal names'."""
    if data.top_weight is None:
        return None
    line = esc(
        tr("concentration", n=TOP_N, pct=f"{data.top_weight * 100:.0f}")
    )
    if data.drift is not None and abs(data.drift) >= DRIFT_FLOOR:
        line += " " + esc(
            tr("drift", pts=f"{data.drift * 100:+.0f}")
        )
    if data.effective_names is not None and data.effective_names == data.effective_names:
        line += " · " + esc(
            tr("effective", n=f"{data.effective_names:.1f}")
        )
    return line


def render_weekly(data: WeeklyData, lang: str, base: str | None = None) -> str:
    """The review as Telegram HTML (parse_mode='HTML'), all dynamic text escaped."""
    from stocks.web.i18n import translate

    def tr(key: str, **kw) -> str:
        return translate(f"notify.{key}", lang, **kw)

    parts: list[str] = [
        f"{heading('🗓 ' + tr('weekly_title'))} · {date_line(data.date, lang)}"
    ]

    if data.total is not None:
        block = f"{heading(tr('portfolio'))} {money(data.total, data.currency)}"
        if (windows := _window_line(data, tr)) is not None:
            block += "\n" + windows
        if (bench := _benchmark_line(data, tr)) is not None:
            block += "\n" + bench
        parts.append(block)

    if rows := _name_rows(data.best, "▲", data, base):
        parts.append(heading(tr("best_week")) + "\n" + "\n".join(rows))
    if rows := _name_rows(data.worst, "▼", data, base):
        parts.append(heading(tr("worst_week")) + "\n" + "\n".join(rows))

    if data.dividends_received:
        amount, count = data.dividends_received
        key = "div_week_one" if count == 1 else "div_week"
        line = (
            tr(key, amount=money(amount, data.currency))
            if count == 1
            else tr(key, amount=money(amount, data.currency), count=count)
        )
        parts.append(heading(tr("dividends")) + "\n• " + esc(line))

    if rows := _ahead_rows(data, lang, tr, base):
        parts.append(heading(tr("week_ahead")) + "\n" + "\n".join(rows))

    if (line := _concentration_line(data, tr)) is not None:
        parts.append(heading(tr("concentration_title")) + "\n" + line)

    if data.highlight:
        parts.append(f"💡 {esc(data.highlight)}")

    return "\n\n".join(parts)


def weekly_buttons(data: WeeklyData, lang: str, base: str | None = None) -> list:
    """Link buttons for the review — Portfolio, plus Earnings when due."""
    from stocks.web.i18n import translate

    base = base if base is not None else links.app_base()
    if not base:
        return []
    buttons = [
        (translate("notify.btn_portfolio", lang), links.page_url(links.PORTFOLIO, base))
    ]
    if data.earnings:
        buttons.append(
            (translate("notify.btn_earnings", lang), links.page_url(links.EARNINGS, base))
        )
    return [(label, url) for label, url in buttons if url]


# ------------------------------------------------------------------ fan-out


def run_weekly_fanout(dry_run: bool = False) -> dict[str, str]:
    """Compute and send every subscriber's weekly review. {label: status}."""
    from stocks.notify import narrative, telegram
    from stocks.notify.fanout import iter_notify_users
    from stocks.notify.state import (
        is_blocked,
        load_state,
        mark_blocked,
        previous_top_weight,
        remember_top_weight,
        save_state,
    )

    now = datetime.now(UTC)
    status: dict[str, str] = {}
    for user in iter_notify_users("weekly"):
        try:
            state = load_state(user.state_path)
            if is_blocked(state):
                status[user.label] = "skipped: blocked"
                continue
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
            data.highlight = narrative.weekly_line(data, user.prefs, user.lang)
            origin = links.app_base()  # not `base`: that one is the currency
            text = render_weekly(data, user.lang, origin)
            if dry_run:
                print(f"── {user.label} ──\n{text}\n")
                status[user.label] = "dry-run"
                continue
            try:
                telegram.send_message(
                    text, user.chat_id, parse_mode="HTML",
                    buttons=weekly_buttons(data, user.lang, origin),
                )
                status[user.label] = "sent"
                # Only a delivered review moves the concentration baseline: a
                # send that failed must not make next Sunday's drift measure
                # from a week the reader never saw.
                if data.top_weight is not None:
                    remember_top_weight(state, data.top_weight, now)
                    save_state(state, user.state_path)
            except telegram.TelegramBlocked:
                mark_blocked(state, now)
                save_state(state, user.state_path)
                status[user.label] = "blocked"
            time.sleep(0.2)  # stay far below Telegram's global send rate
        except Exception as exc:  # noqa: BLE001 — cron isolation per account
            status[user.label] = f"error: {exc}"
    return status
