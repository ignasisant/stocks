"""Re-engagement nudge — one message to an account that stopped opening the app.

An account that linked Telegram and then went quiet for a week gets one short
message: how long it has been, what its book did this week, and a button back
in. A second one a week later if it still has not come back, and then nothing
— two unanswered reminders are the reader's answer, and a bot that keeps
asking is the one that gets blocked. The count restarts only when the account
shows up again after a nudge and later goes quiet once more (a new spell).

"Last seen" is the day `accounts.stamp_login` wrote into prefs.json, so the
cron reads it headless from the bucket like every other notification input.
Accounts that never signed in through the web (no `last_seen`) are left alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from stocks import obs
from stocks.notify import links, telegram
from stocks.notify import weekly as weekly_mod
from stocks.notify.render import delta, esc, heading, money, ticker_link
from stocks.notify.state import (
    forget_nudges,
    is_blocked,
    load_state,
    mark_blocked,
    nudges_sent,
    remember_nudge,
    save_state,
)

# Quiet for this long = dormant. One week is past the first look and the
# import that follows it, which is also the retention window `stocks logs
# funnel` measures.
AWAY_DAYS = 7
# Reminders per dormancy spell, and the gap between them.
MAX_NUDGES = 2
GAP_DAYS = 7


@dataclass
class NudgeData:
    days: int  # since the last visit
    number: int  # 1 or 2 — which reminder of the spell this is
    total: float | None = None
    week: tuple[float, float] | None = None  # (change, pct), in `currency`
    mover: tuple[str, float, float | None] | None = None  # (ticker, money, pct)
    currency: str = "EUR"

    @property
    def last(self) -> bool:
        return self.number >= MAX_NUDGES


def days_away(prefs: dict, today: date) -> int | None:
    """Days since the account was last seen; None when it never signed in."""
    raw = prefs.get("last_seen")
    if not raw:
        return None
    try:
        seen = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
    return (today - seen).days


def due(state: dict, prefs: dict, today: date) -> int | None:
    """Which reminder (1 or 2) is due today, or None.

    Updates `state` in place when a visit since the last reminder closes the
    previous spell, so the caller saves it either way.
    """
    away = days_away(prefs, today)
    if away is None or away < AWAY_DAYS:
        return None
    sent = nudges_sent(state)
    if sent:
        last_nudge = date.fromisoformat(sent[-1][:10])
        seen = date.fromisoformat(str(prefs["last_seen"])[:10])
        if seen > last_nudge:
            # Came back after a reminder, quiet again now: a new spell.
            forget_nudges(state)
            sent = []
        elif len(sent) >= MAX_NUDGES or (today - last_nudge).days < GAP_DAYS:
            return None
    return len(sent) + 1


def wants_messages(prefs: dict) -> bool:
    """Linked, and has not switched every notification off."""
    if not prefs.get("telegram_chat_id"):
        return False
    return any(
        prefs.get(f"notify_{kind}", True) for kind in ("digest", "weekly", "alerts")
    )


def gather(user, number: int, days: int, today: date) -> NudgeData:
    """The message's figures: the book's week, when there is a book."""
    base = str(user.prefs.get("currency") or "EUR").upper()
    data = NudgeData(days=days, number=number, currency=base)
    with obs.swallow("nudge.book", user=user.label):
        week = weekly_mod.compute_weekly_data(user.watchlist, user.db, base, today=today)
        data.total = week.total
        data.week = week.week
        if week.best:
            data.mover = week.best[0]
    return data


def render(data: NudgeData, lang: str, base: str | None = None) -> str:
    """The Telegram message (parse_mode=HTML)."""
    from stocks.web.i18n import translate

    def tr(key: str, **kw) -> str:
        return translate(f"notify.{key}", lang, **kw)

    lines = [
        heading("👋 " + tr("nudge_title")),
        esc(tr("nudge_away", days=str(data.days))),
    ]
    if data.total is not None:
        change = (
            delta(data.week[0], data.week[1], data.currency) if data.week else "–"
        )
        lines.append(esc(tr(
            "nudge_book", value=money(data.total, data.currency), change=change,
        )))
        if data.mover and data.mover[2] is not None:
            ticker, _, pct = data.mover[0], data.mover[1], float(data.mover[2])
            # The link is the one HTML the line carries; everything around it
            # is escaped first, then the placeholder gives way to the link.
            lines.append(
                esc(tr("nudge_mover", ticker="\0", pct=f"{pct * 100:+.1f}%"))
                .replace("\0", ticker_link(ticker, base))
            )
    else:
        lines.append(esc(tr("nudge_empty")))
    if data.last:
        lines.append(esc(tr("nudge_last")))
    return "\n".join(lines)


def buttons(data: NudgeData, lang: str, base: str | None = None) -> list:
    """One button: the book when there is one, the importer otherwise."""
    from stocks.web.i18n import translate

    base = base if base is not None else links.app_base()
    if not base:
        return []
    if data.total is not None:
        label, url = translate("notify.btn_portfolio", lang), links.page_url(
            links.PORTFOLIO, base
        )
    else:
        label, url = translate("notify.btn_import", lang), links.page_url(
            links.IMPORT, base
        )
    return [(label, url)] if url else []


def run_nudge_fanout(dry_run: bool = False, today: date | None = None) -> dict[str, str]:
    """Message every dormant Telegram-linked account its reminder. {label: status}."""
    from stocks.notify.fanout import iter_all_users

    now = datetime.now(UTC)
    today = today or now.date()
    status: dict[str, str] = {}
    for user in iter_all_users():
        if not wants_messages(user.prefs):
            continue
        try:
            state = load_state(user.state_path)
            if is_blocked(state):
                status[user.label] = "skipped: blocked"
                continue
            number = due(state, user.prefs, today)
            if number is None:
                away = days_away(user.prefs, today)
                status[user.label] = (
                    "skipped: active" if away is None or away < AWAY_DAYS
                    else "skipped: already nudged"
                )
                continue
            data = gather(user, number, days_away(user.prefs, today) or 0, today)
            origin = links.app_base()
            text = render(data, user.lang, origin)
            if dry_run:
                print(f"── {user.label} ──\n{text}\n")
                status[user.label] = "dry-run"
                continue
            try:
                telegram.send_message(
                    text, user.chat_id, parse_mode="HTML",
                    buttons=buttons(data, user.lang, origin),
                )
                remember_nudge(state, now)
                status[user.label] = f"sent #{number}"
                obs.event(
                    "nudge.sent", user=user.label, number=number, days=data.days,
                    book=data.total is not None,
                )
            except telegram.TelegramBlocked:
                mark_blocked(state, now)
                status[user.label] = "blocked"
            save_state(state, user.state_path)
            telegram.pace()
        except Exception as exc:  # noqa: BLE001 — cron isolation per account
            status[user.label] = f"error: {exc}"
    return status
