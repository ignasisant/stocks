"""Daily portfolio digest — computed headless, rendered as Telegram HTML.

compute_digest_data does the network work (prices, FX, earnings, dividends);
render_digest is pure text so it tests offline. Every section is individually
fault-tolerant: a failed FX fetch or a throttled earnings lookup drops that
section, the digest still sends.

Two rules shape what the message says rather than what it can say:

* **Money, not percent.** A name's contribution to the book is its weight times
  its move. The movers block leads with the currency figure and keeps the
  percentage as the qualifier, so the line the reader scans first is the one
  that changed their net worth.
* **A quiet day is a short message.** A digest that arrives identical and
  eventless every evening trains the reader to swipe it away, so a flat session
  with nothing on the calendar renders as one line and skips the LLM call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from stocks import obs
from stocks.config import currency_symbol, load_watchlist
from stocks.data.dividends import DividendEvent, upcoming_ex_dividends
from stocks.data.earnings import EarningsEvent, EarningsResult, calendar_events
from stocks.notify import links
from stocks.notify.render import date_line as _date_line
from stocks.notify.render import delta as _delta
from stocks.notify.render import esc
from stocks.notify.render import money as _money
from stocks.notify.render import ticker_link as _ticker
from stocks.portfolio.ledger import Transaction, all_transactions
from stocks.portfolio.positions import build
from stocks.portfolio.tax.deadlines import Deadline

MOVERS_SHOWN = 3
DIVIDENDS_SHOWN = 4
# Calendar window shared by the earnings and ex-dividend sections, and the
# lookback for dividends the ledger has already booked.
WINDOW_DAYS = 7

# What the book is measured against. Read off daily closes like the portfolio
# figure, but in the benchmark's own currency: for a EUR book holding US names
# the gap therefore excludes the FX leg, which is the comparison a reader means
# when they ask whether they beat the index.
BENCHMARK = "SPY"
BENCHMARK_LABEL = "S&P 500"

# How far back a print still counts as news. Wider than a day because the
# digest only runs on weekdays: a Friday-evening report has to survive the
# weekend to be mentioned at all.
RESULTS_LOOKBACK = 4

# The currency leg is only worth a line when it explains a real part of the
# day — below this share of the move it is rounding, and naming it would push
# the reader toward a number that means nothing.
FX_SHARE_FLOOR = 0.15

# A statement import older than this is probably a book drifting out of date.
# The nudge rides the Monday digest only: a daily reminder is nagging, and the
# fix (uploading a statement) is a weekday-morning job either way.
STALE_IMPORT_DAYS = 45
NUDGE_WEEKDAY = 0  # Monday

# A session this flat, with an empty calendar, is not worth a full message.
QUIET_PCT = 0.003


@dataclass
class DigestData:
    date: date
    total: float | None = None
    day: tuple[float, float] | None = None  # (change, pct) over 1 day
    week: tuple[float, float] | None = None  # over ~7 days
    movers: list[tuple[str, float]] = field(default_factory=list)  # (ticker, pct) desc
    # Per-ticker day contribution in `currency` — what each name did to the
    # book, as opposed to what it did to its own price. Empty when there is no
    # ledger to weight the moves by.
    contrib: dict[str, float] = field(default_factory=dict)
    # (pct over 1 day, pct over ~7 days) for BENCHMARK; either leg may be None.
    benchmark: tuple[float | None, float | None] | None = None
    earnings: list[EarningsEvent] = field(default_factory=list)
    # Prints from the last RESULTS_LOOKBACK days, newest first, and the move
    # across each one (percent, from stocks.data.earnings.price_reaction).
    results: list[EarningsResult] = field(default_factory=list)
    result_moves: dict[str, float] = field(default_factory=dict)
    # Day money attributable to the exchange rate rather than to prices.
    fx_effect: float | None = None
    # Days since the last statement import, when that is worth saying.
    stale_import_days: int | None = None
    ex_dividends: list[DividendEvent] = field(default_factory=list)
    # Estimated gross cash per upcoming ex-date, in `currency`, keyed by ticker.
    dividend_cash: dict[str, float] = field(default_factory=dict)
    # Dividends the ledger booked in the last WINDOW_DAYS: (net amount, count).
    dividends_received: tuple[float, int] | None = None
    # Tax deadlines entering the 30-day window, not yet reminded of. Filled by
    # the fan-out, which holds the prefs (residence) and the state (memory).
    tax_deadlines: list[Deadline] = field(default_factory=list)
    highlight: str | None = None  # optional LLM line, filled by the caller
    watchlist_only: bool = False  # no ledger -> movers/earnings-only digest
    # The account's reporting currency; every figure above is in it.
    currency: str = "EUR"

    @property
    def quiet(self) -> bool:
        """Whether the day carries nothing worth a full message.

        A flat session is only quiet when the calendar is empty too — an
        ex-date, a print or cash landing in the account is news on a day the
        prices did nothing. A book whose day change couldn't be computed is
        never quiet: silence there is a missing number, not a calm market.
        """
        if self.day is None:
            return False
        if self.earnings or self.ex_dividends or self.dividends_received:
            return False
        if self.results or self.stale_import_days or self.tax_deadlines:
            return False
        return abs(self.day[1]) < QUIET_PCT


def _benchmark_changes(period: str = "1mo") -> tuple[float | None, float | None] | None:
    """(1-day, ~7-day) % change of BENCHMARK off daily closes, or None."""
    from stocks.analysis.portfolio import benchmark_changes

    changes = benchmark_changes([1, WINDOW_DAYS], BENCHMARK, period)
    if not changes or all(v is None for v in changes.values()):
        return None
    return changes.get(1), changes.get(WINDOW_DAYS)


def recent_dividends(
    transactions: list[Transaction],
    base: str = "EUR",
    within_days: int = WINDOW_DAYS,
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


def compute_digest_data(
    watchlist: Path, db: Path, base: str = "EUR", import_record: Path | None = None
) -> DigestData:
    """Gather one account's digest inputs, in `base`. Sections fail alone."""
    from stocks.analysis.portfolio import (
        basket_change,
        fx_share,
        position_value_frames,
        session_moves,
        ticker_money_changes,
    )

    data = DigestData(date=date.today(), currency=base)
    holdings = load_watchlist(watchlist)

    positions = []
    txs: list[Transaction] = []
    try:
        txs = all_transactions(db)
        if txs:
            positions, _ = build(txs, base=base)
    except Exception:
        positions = []
    data.watchlist_only = not positions

    if positions:
        with obs.swallow("digest.position_values", positions=len(positions)):
            values, frozen = position_value_frames(positions, period="1mo", base=base)
            if not values.empty:
                last = values.iloc[-1].dropna()
                data.total = float(last.sum()) if not last.empty else None
                data.day = basket_change(values, 1)
                data.week = basket_change(values, WINDOW_DAYS)
                # Same frame, same anchoring as `day` — so the contributions
                # sum to the day change the header just reported.
                data.contrib = {
                    str(t): float(v)
                    for t, v in ticker_money_changes(values, 1).items()
                }
                data.fx_effect = fx_share(values, frozen, 1)

    tickers = (
        [p.ticker for p in positions]
        if positions
        else [h.ticker for h in holdings]
    )
    with obs.swallow("digest.session_moves", tickers=len(tickers)):
        moves = session_moves(tickers)
        data.movers = sorted(moves.items(), key=lambda kv: kv[1], reverse=True)

    if data.day is not None:
        with obs.swallow("digest.benchmark", ticker=BENCHMARK):
            data.benchmark = _benchmark_changes()

    with obs.swallow("digest.earnings"):
        events, results = calendar_events(holdings)
        data.earnings = [
            e for e in events
            if e.days_until is not None and e.days_until <= WINDOW_DAYS
        ]
        # Free of extra network: calendar_events already pulled the reported
        # columns, so the rear-view costs nothing the heads-up wasn't spending.
        data.results = [
            r for r in results
            if (data.date - r.date).days <= RESULTS_LOOKBACK
        ]
    if data.results:
        with obs.swallow("digest.result_moves", results=len(data.results)):
            data.result_moves = _result_moves(data.results)

    with obs.swallow("digest.ex_dividends", tickers=len(tickers)):
        data.ex_dividends = upcoming_ex_dividends(tickers, within_days=WINDOW_DAYS)
        data.dividend_cash = _dividend_cash(data.ex_dividends, positions, base)

    if txs:
        with obs.swallow("digest.dividends_received"):
            data.dividends_received = recent_dividends(txs, base)

    if import_record is not None and positions:
        with obs.swallow("digest.stale_import"):
            data.stale_import_days = stale_import_days(import_record, data.date)

    return data


def _result_moves(results: list[EarningsResult]) -> dict[str, float]:
    """% move across each print, keyed by ticker. One history call per result.

    Affordable precisely because prints are rare: a book of twenty names has
    nothing here on most evenings and two entries in the middle of a season.
    """
    from stocks.data.earnings import price_reaction

    moves: dict[str, float] = {}
    for result in results:
        try:
            move = price_reaction(result.ticker, result.date)
        except Exception:
            move = None
        if move is not None:
            moves[result.ticker] = move
    return moves


def stale_import_days(
    record_path: Path, today: date | None = None
) -> int | None:
    """Days since the last statement import, when that is worth mentioning.

    None unless the account actually imports statements and has not done so in
    a long time — an account that types its ledger by hand has no record here,
    and nudging it about a workflow it doesn't use would be noise. The nudge is
    also Monday-only: the message reappearing every evening is how a useful
    reminder turns into something the reader learns to skip.
    """
    from stocks.portfolio.last_import import load as load_record

    today = today or date.today()
    if today.weekday() != NUDGE_WEEKDAY:
        return None
    record = load_record(record_path)
    if record is None:
        return None
    try:
        imported = datetime.fromisoformat(record.imported_at).date()
    except (TypeError, ValueError):
        return None
    days = (today - imported).days
    return days if days >= STALE_IMPORT_DAYS else None


def _dividend_cash(
    events: list[DividendEvent], positions, base: str
) -> dict[str, float]:
    """Estimated gross cash per upcoming ex-date, in `base`, keyed by ticker.

    Only for tickers actually held: a watchlist name goes ex too, but there is
    no quantity to multiply, so those events render as a date alone.
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


# ---------------------------------------------------------------- rendering


def ranked_movers(data: DigestData) -> list[tuple[str, float | None, float | None]]:
    """(ticker, day pct, day money) rows, best first.

    Ranked by money when the book is priced, by percentage otherwise — a
    watchlist has no weights to rank by. The two inputs are unioned rather than
    intersected: a quote that failed still has a value move, and a name absent
    from the value frame still has a quote.
    """
    pcts = dict(data.movers)
    order = [*data.contrib, *(t for t in pcts if t not in data.contrib)]
    rows = [(t, pcts.get(t), data.contrib.get(t)) for t in order]
    if data.contrib:
        return sorted(rows, key=lambda r: r[2] if r[2] is not None else 0.0,
                      reverse=True)
    return sorted(rows, key=lambda r: r[1] if r[1] is not None else 0.0, reverse=True)


def _rank_value(row: tuple[str, float | None, float | None], by_money: bool) -> float:
    """The figure a row is ranked and sided by.

    Money when the book is priced, but falling back to the percentage for a
    name the value frame never saw — otherwise a holding whose price series is
    missing reads as a flat 0 and drops out of both lists.
    """
    value = row[2] if by_money else row[1]
    if value is None:
        value = row[1] if by_money else row[2]
    return value if value is not None else 0.0


def _mover_line(
    row: tuple[str, float | None, float | None],
    marker: str,
    currency: str,
    base: str | None = None,
) -> str:
    ticker, pct, money = row
    parts = [f"{marker} {_ticker(ticker, base)}"]
    if money is not None:
        parts.append(f"{money:+,.0f} {currency_symbol(currency)}")
    if pct is not None:
        moved = f"{pct * 100:+.1f}%"
        parts.append(f"({moved})" if money is not None else moved)
    return " ".join(parts)


def _benchmark_line(data: DigestData, tr) -> str | None:
    """'vs S&P 500 +1.40% · behind by 0.54 pt', or None when incomparable."""
    if data.benchmark is None or data.day is None:
        return None
    bench_day = data.benchmark[0]
    if bench_day is None:
        return None
    label = esc(BENCHMARK_LABEL)
    line = f"{esc(tr('vs'))} {label} {bench_day * 100:+.2f}%"
    gap = (data.day[1] - bench_day) * 100
    verdict = tr("ahead" if gap >= 0 else "behind", gap=f"{abs(gap):.2f}")
    return f"{line} · {esc(verdict)}"


def _fx_chip(data: DigestData, tr) -> str | None:
    """'FX -180 €' — the currency leg of the day, when it explains part of it.

    Suppressed for a single-currency book (always zero) and whenever the
    exchange rate moved the book by less than FX_SHARE_FLOOR of the day: a
    reader who sees the line every evening stops reading it on the evening it
    is the whole story.
    """
    if data.fx_effect is None or data.day is None:
        return None
    move = abs(data.day[0])
    if not move or abs(data.fx_effect) < FX_SHARE_FLOOR * move:
        return None
    symbol = currency_symbol(data.currency)
    return f"{esc(tr('fx'))} {data.fx_effect:+,.0f} {symbol}"


def _result_rows(data: DigestData, tr, base: str | None = None) -> list[str]:
    """'• NVDA — beat, EPS 1.24 vs 1.18 · +6.4%' per recent print."""
    rows = []
    for result in data.results:
        parts = [f"• {_ticker(result.ticker, base)}"]
        verdict = result.beat
        if verdict is not None:
            parts.append(esc(tr("beat" if verdict else "miss")))
        if result.reported_eps is not None and result.eps_estimate is not None:
            parts.append(
                f"EPS {result.reported_eps:.2f} "
                f"{esc(tr('vs'))} {result.eps_estimate:.2f}"
            )
        line = parts[0] + (" — " + ", ".join(parts[1:]) if len(parts) > 1 else "")
        if (move := data.result_moves.get(result.ticker)) is not None:
            line += f" · {move:+.1f}%"
        rows.append(line)
    return rows


def _dividend_rows(
    data: DigestData, lang: str, tr, base: str | None = None
) -> list[str]:
    rows = []
    for event in data.ex_dividends[:DIVIDENDS_SHOWN]:
        line = (
            f"• {_ticker(event.ticker, base)} — {esc(tr('ex_date'))} "
            f"{_date_line(event.ex_date, lang)} (T-{event.days_until})"
        )
        cash = data.dividend_cash.get(event.ticker)
        if cash:
            line += f" · ~{_money(cash, data.currency)}"
        rows.append(line)
    if data.dividends_received:
        amount, count = data.dividends_received
        key = "div_received_one" if count == 1 else "div_received"
        line = (
            tr(key, amount=_money(amount, data.currency))
            if count == 1
            else tr(key, amount=_money(amount, data.currency), count=count)
        )
        rows.append("• " + esc(line))
    return rows


def digest_buttons(data: DigestData, lang: str, base: str | None = None) -> list:
    """Link buttons for the digest — what this particular evening asks for.

    Empty without a configured origin, and never decorative: a button appears
    because the message above it named something the reader may want to act on.
    """
    from stocks.web.i18n import translate

    base = base if base is not None else links.app_base()
    if not base:
        return []
    buttons = [
        (translate("notify.btn_portfolio", lang), links.page_url(links.PORTFOLIO, base))
    ]
    if data.earnings or data.results:
        buttons.append(
            (translate("notify.btn_earnings", lang), links.page_url(links.EARNINGS, base))
        )
    if data.stale_import_days:
        buttons.append(
            (translate("notify.btn_import", lang), links.page_url(links.IMPORT, base))
        )
    return [(label, url) for label, url in buttons if url]


def render_digest(data: DigestData, lang: str, base: str | None = None) -> str:
    """The digest as Telegram HTML (parse_mode='HTML'), all dynamic text escaped.

    `base` is the app's public origin: given one, every ticker becomes a link
    to its page. Omitted, the message renders exactly as it does on a deploy
    that has not declared where it lives.
    """
    from stocks.web.i18n import translate

    def tr(key: str, **kw) -> str:
        return translate(f"notify.{key}", lang, **kw)

    parts: list[str] = [
        f"<b>📊 {esc(tr('digest_title'))}</b> · {_date_line(data.date, lang)}"
    ]

    if data.total is not None:
        line = (
            f"<b>{esc(tr('portfolio'))}</b> "
            f"{_money(data.total, data.currency)}"
        )
        deltas = []
        if data.day:
            deltas.append(f"{esc(tr('day'))} {_delta(*data.day, data.currency)}")
        if data.week:
            deltas.append(
                f"{esc(tr('week'))} {_delta(*data.week, data.currency)}"
            )
        if (currency_leg := _fx_chip(data, tr)) is not None:
            deltas.append(currency_leg)
        if deltas:
            line += "\n" + " · ".join(deltas)
        if (bench := _benchmark_line(data, tr)) is not None:
            line += "\n" + bench
        parts.append(line)

    # A flat session with an empty calendar stops here: the numbers above are
    # the whole story, and padding them with a movers block of ±0.1% names
    # would only teach the reader to stop opening the message.
    if data.quiet:
        parts.append(esc(tr("quiet")))
        return "\n\n".join(parts)

    rows = ranked_movers(data)
    if rows:
        by_money = bool(data.contrib)
        gainers = [r for r in rows if _rank_value(r, by_money) > 0][:MOVERS_SHOWN]
        losers = [r for r in reversed(rows) if _rank_value(r, by_money) < 0][
            :MOVERS_SHOWN
        ]
        lines = []
        if gainers:
            lines.append(
                "  ".join(_mover_line(r, "▲", data.currency, base) for r in gainers)
            )
        if losers:
            lines.append(
                "  ".join(_mover_line(r, "▼", data.currency, base) for r in losers)
            )
        if lines:
            parts.append(f"<b>{esc(tr('movers'))}</b>\n" + "\n".join(lines))

    if dividend_rows := _dividend_rows(data, lang, tr, base):
        parts.append(
            f"<b>{esc(tr('dividends'))}</b>\n" + "\n".join(dividend_rows)
        )

    if result_rows := _result_rows(data, tr, base):
        parts.append(
            f"<b>{esc(tr('results'))}</b>\n" + "\n".join(result_rows)
        )

    if data.earnings:
        rows_e = [
            f"• {_ticker(e.ticker, base)} — {_date_line(e.date, lang)} (T-{e.days_until})"
            for e in data.earnings
            if e.date is not None
        ]
        if rows_e:
            parts.append(
                f"<b>{esc(tr('earnings_7d'))}</b>\n" + "\n".join(rows_e)
            )

    if data.tax_deadlines:
        rows_t = [
            "• "
            + esc(translate(f"earnings.tax_{d.key}", lang, year=d.year_label))
            + f" — {_date_line(d.date, lang)} (T-{d.days_until(data.date)})"
            for d in data.tax_deadlines
        ]
        parts.append(f"<b>🗓 {esc(tr('tax_deadlines'))}</b>\n" + "\n".join(rows_t))

    if data.stale_import_days:
        parts.append(
            "📎 " + esc(tr("stale_import", days=data.stale_import_days))
        )

    if data.highlight:
        parts.append(f"💡 {esc(data.highlight)}")

    return "\n\n".join(parts)


# ------------------------------------------------------------------ fan-out


def run_digest_fanout(dry_run: bool = False) -> dict[str, str]:
    """Compute and send every subscriber's digest. Returns {label: status}."""
    from stocks.notify import narrative, telegram
    from stocks.notify.fanout import iter_notify_users
    from stocks.notify.state import (
        is_blocked,
        load_state,
        mark_blocked,
        recent_highlights,
        remember_highlight,
        remember_tax_reminders,
        save_state,
        tax_reminders_due,
    )
    from stocks.portfolio.tax import prefs as tax_prefs

    now = datetime.now(UTC)
    status: dict[str, str] = {}
    for user in iter_notify_users("digest"):
        try:
            state = load_state(user.state_path)
            if is_blocked(state):
                status[user.label] = "skipped: blocked"
                continue
            base = str(user.prefs.get("currency") or "EUR").upper()
            data = compute_digest_data(
                user.watchlist, user.db, base, import_record=user.import_path
            )
            code, _ = tax_prefs.resolve(user.prefs)
            data.tax_deadlines = tax_reminders_due(state, code, data.date)
            if (
                data.total is None
                and not data.movers
                and not data.earnings
                and not data.ex_dividends
                and not data.tax_deadlines
            ):
                status[user.label] = "skipped: no data"
                continue
            # The quiet digest is two numbers and a line saying so — narrating
            # it would spend a unit of the free pot to say "not much happened".
            if not data.quiet:
                data.highlight = narrative.highlight(
                    data, user.prefs, user.lang, recent=recent_highlights(state)
                )
            origin = links.app_base()  # not `base`: that one is the currency
            text = render_digest(data, user.lang, origin)
            buttons = digest_buttons(data, user.lang, origin)
            if dry_run:
                print(f"── {user.label} ──\n{text}\n")
                status[user.label] = "dry-run"
                continue
            try:
                telegram.send_message(
                    text, user.chat_id, parse_mode="HTML", buttons=buttons
                )
                status[user.label] = "sent"
                # Only what was actually delivered joins the memory, so a send
                # that failed does not burn the line it never showed.
                if data.highlight:
                    remember_highlight(state, data.highlight)
                if data.tax_deadlines:
                    remember_tax_reminders(state, data.tax_deadlines)
                if data.highlight or data.tax_deadlines:
                    save_state(state, user.state_path)
            except telegram.TelegramBlocked:
                mark_blocked(state, now)
                save_state(state, user.state_path)
                status[user.label] = "blocked"
            time.sleep(0.2)  # stay far below Telegram's global send rate
        except Exception as exc:  # noqa: BLE001 — cron isolation per account
            status[user.label] = f"error: {exc}"
    return status
