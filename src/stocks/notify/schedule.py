"""Scheduled runs: the AI briefing, once a day at the account's own time and
filed in its chat.

One summary a day and no more: the evening numbers and the Sunday review that
used to ride beside it were retired (2026-11-10) — they told the same session
again in less detail, and a reader pushed three summaries learns to swipe all
of them away. The job is switched by `notify_briefing` and timed by
`schedules["briefing"]` ({"time": "HH:MM", "days": [0-6, Monday = 0],
"close": bool}) in the account's `timezone`. Its run is the daily card's
thread, marked, pushed to the account's devices with that thread as the tap's
target, so the notification opens what it said and the rest it folded away.

**Two ways to read it.** By default the card is written after the US
after-hours session (`daily.BRIEF_AT`) and pushed at the reader's morning
time. With `close` the reader takes it the same evening: the account's card
turns over at `daily.CLOSE_AT` instead (`turnover`), and the run is pushed as
soon as that card is written — at whatever local hour the US close falls, so
no time to keep.

**Inside the app, not a cron.** A run writes chat.json, and the app's live
instance owns that file (`storage`: single container, the local copy is the
current one); a GitHub runner writing it would be overwritten by the next
save, or overwrite one. So Cloud Scheduler calls `POST /v1/schedule/tick`
with the API token every quarter of an hour (infra/cron.tf), and the tick
runs whatever came due since — the request is the CPU, as for the warm.

One more is the market's, not the reader's: the next day's card (`CARD`) is
written after the US close, when the account's `daily.action_day` turns over,
so the morning's briefing files and pushes a card already written instead of
waiting on a model at 08:30. It pushes nothing by itself and is not a setting.

**Due** is a local wall-clock time on a listed weekday, not yet run that
local day, and at most `CATCH_UP` late: a tick missed by an outage still
delivers this morning's briefing at nine, not at midnight.

**Who**: accounts with a device to push to, or seen in the last
`ACTIVE_DAYS` — a run spends a model call, and an account nobody opens has
nobody to read it. The Friday email is the exception (`email_due`): it
spends no model call and is how an account that has not come back hears
from its book, so it goes to every account with an address and an import.
"""

from __future__ import annotations

import contextvars
import time as clock
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stocks import obs
from stocks.notify import links

if TYPE_CHECKING:
    from stocks.accounts import UserPaths

JOBS = ("briefing",)
CARD = "card"
# The Friday email (`notify/weekly_email.py`): not one of the reader's chat
# runs, so not in JOBS, and read in one zone for everyone — 23:00 in Madrid is
# after the US close in every week of the year, DST gap weeks included, so it
# always reports a finished week.
EMAIL = "weekly_email"
EMAIL_ZONE = "Europe/Madrid"
DEFAULTS: dict[str, dict] = {
    "briefing": {"time": "08:30", "days": [0, 1, 2, 3, 4], "close": False},
    EMAIL: {"time": "23:00", "days": [4]},
}
PREFS_KEY = "schedules"
LAST_KEY = "schedule_last"
ZONE_KEY = "timezone"
DEFAULT_ZONE = "Europe/Madrid"
# How late a run may still go out after its time.
CATCH_UP = timedelta(hours=6)
ACTIVE_DAYS = 14
WORKERS = 4
# How long the tick keeps starting runs. Under Cloud Run's 300 s request
# timeout with a briefing's wait (`BRIEFING_WAIT_S`) to spare: a run not
# started by then waits for the next tick, a quarter of an hour later.
TICK_BUDGET_S = 120.0
# How long the briefing's generation is waited on before its stand-in is
# what gets filed.
BRIEFING_WAIT_S = 150.0


# ------------------------------------------------------------------ settings


def valid_zone(name: object) -> bool:
    if not isinstance(name, str) or not name.strip():
        return False
    try:
        ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def zone(prefs: dict) -> ZoneInfo:
    """The account's zone, `DEFAULT_ZONE` until the browser has sent one."""
    name = prefs.get(ZONE_KEY)
    ok = isinstance(name, str) and valid_zone(name)
    return ZoneInfo(name.strip() if ok and name else DEFAULT_ZONE)


def parse_time(text: object) -> time | None:
    """"HH:MM" as a time, None for anything else."""
    try:
        hours, minutes = str(text).split(":")
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return None


def clean_days(days: object) -> list[int]:
    """Weekday numbers, Monday = 0, sorted and once each."""
    if not isinstance(days, list):
        return []
    return sorted({d for d in days if isinstance(d, int) and 0 <= d <= 6})


def slot(prefs: dict, job: str) -> dict:
    """One job as the app applies it: {"on", "time", "days", "close"}. A stored
    time or day list that does not parse is the default's — a settings read
    must not stop a run over one bad key."""
    stored = prefs.get(PREFS_KEY)
    mine = stored.get(job) if isinstance(stored, dict) else None
    mine = mine if isinstance(mine, dict) else {}
    default = DEFAULTS[job]
    at = mine.get("time") if parse_time(mine.get("time")) else default["time"]
    days = clean_days(mine.get("days")) if "days" in mine else default["days"]
    out = {"on": bool(prefs.get(f"notify_{job}", True)), "time": at, "days": days}
    if "close" in default:
        out["close"] = mine.get("close") is True
    return out


def slots(prefs: dict) -> dict[str, dict]:
    return {job: slot(prefs, job) for job in JOBS}


def turnover(prefs: dict) -> time:
    """When the account's card turns over, New York time: at the close for a
    reader who takes the briefing that evening, after the after-hours session
    otherwise. Read off the slot whether or not it is switched on: Home's card
    keeps the day its reader chose to read it on."""
    from stocks.chat import daily

    return daily.CLOSE_AT if slot(prefs, "briefing")["close"] else daily.BRIEF_AT


# ------------------------------------------------------------------ due


def due(job_slot: dict, tz: ZoneInfo, now: datetime, last: object) -> date | None:
    """The local day a run comes due for at `now`, or None.

    Today's run, or yesterday's for a late slot whose catch-up crosses
    midnight; never one already run (`last`, the local day it last went out).
    """
    at = parse_time(job_slot.get("time"))
    # A `close` slot keeps no clock of its own: it goes out with the card.
    if not job_slot.get("on") or job_slot.get("close") or at is None:
        return None
    local = now.astimezone(tz)
    for day in (local.date(), local.date() - timedelta(days=1)):
        if day.weekday() not in job_slot.get("days", []):
            continue
        when = datetime.combine(day, at, tzinfo=tz)
        if when <= local <= when + CATCH_UP and str(last or "") < day.isoformat():
            return day
    return None


def card_due(now: datetime, last: object, at: time | None = None) -> date | None:
    """The US session whose close the card build is due for at `now`, or None:
    the account's turnover (`at`, `daily.BRIEF_AT` by default) New York time
    on a weekday the market traded."""
    from stocks.chat import daily
    from stocks.data import market_holidays as mh

    clock_at = (at or daily.BRIEF_AT).strftime("%H:%M")
    day = due({"on": True, "time": clock_at, "days": [0, 1, 2, 3, 4]},
              daily.CLOSE_ZONE, now, last)
    if day is None or mh.DAYS.get(mh.US, {}).get(day) == mh.CLOSED:
        return None
    return day


def close_due(prefs: dict, session: date, last: object) -> date | None:
    """The session an evening briefing goes out for, right after its card:
    switched on, in `close` mode, on a listed weekday (the session's, New York
    date) and not already sent that day — a reader who moved from morning to
    evening after this morning's push is not pushed twice the same day."""
    job_slot = slot(prefs, "briefing")
    if not (job_slot["on"] and job_slot["close"]):
        return None
    if session.weekday() not in job_slot["days"]:
        return None
    return session if str(last or "") < session.isoformat() else None


def eligible(prefs: dict, devices: int, today: date) -> bool:
    """Whether runs are worth spending on this account (see the module note)."""
    if devices > 0:
        return True
    try:
        seen = date.fromisoformat(str(prefs.get("last_seen") or "")[:10])
    except ValueError:
        return False
    return today - seen <= timedelta(days=ACTIVE_DAYS)


def email_due(prefs: dict, paths, now: datetime, last: object) -> date | None:
    """The Friday the weekly email is due for at `now`, or None.

    Switched by `notify_weekly_email` (on by default), for an account with an
    address and a book it imported — the onboarding sample is not one. No
    device and no recent visit needed. The ledger is read only once the slot
    is due, not on every tick."""
    if not prefs.get("email"):
        return None
    day = due(slot(prefs, EMAIL), ZoneInfo(EMAIL_ZONE), now, last)
    if day is None:
        return None
    from stocks.portfolio import demo

    try:
        return day if demo.has_real(paths.db) else None
    except Exception:  # noqa: BLE001 — unreadable ledger: nothing to report
        return None


# ------------------------------------------------------------------ the tick


@dataclass
class Account:
    label: str
    paths: UserPaths
    prefs: dict
    runs: list[tuple[str, date]] = field(default_factory=list)

    @property
    def lang(self) -> str:
        from stocks.notify import webpush

        return self.prefs.get("language") or webpush.lang_of(self.paths.push) or "en"


def _roster() -> list[tuple[str, UserPaths]]:
    """(label, UserPaths) for every account, the owner labelled "owner" — the
    crons' discovery (`fanout._slugs`), as paths this process serves."""
    from stocks import accounts
    from stocks.notify.fanout import USERS_DIR, _slugs

    found = [(s, accounts.paths_in(USERS_DIR / s)) for s in sorted(_slugs())]
    if accounts.configured_owner():
        found.append(("owner", accounts.owner_paths()))
    return found


def plan(now: datetime) -> list[Account]:
    """Every eligible account with the runs due at `now`."""
    from stocks import accounts
    from stocks.notify import webpush

    out: list[Account] = []
    for label, paths in _roster():
        try:
            # Once per process, like a request's: from then on this
            # process's files are the current ones.
            accounts.restore_account(paths, seed=False)
            prefs = accounts.load_prefs(paths.prefs)
        except Exception as exc:  # noqa: BLE001 — one account, not the tick
            obs.warn("schedule.account_unreadable", account=label,
                     error_type=type(exc).__name__)
            continue
        tz = zone(prefs)
        stored = prefs.get(LAST_KEY)
        last: dict = stored if isinstance(stored, dict) else {}
        runs: list[tuple[str, date]] = []
        if eligible(prefs, webpush.devices(paths.push), now.astimezone(tz).date()):
            runs = [
                (job, day)
                for job in JOBS
                if (day := due(slot(prefs, job), tz, now, last.get(job))) is not None
            ]
            if (session := card_due(now, last.get(CARD), turnover(prefs))) is not None:
                runs.insert(0, (CARD, session))
                if (after := close_due(prefs, session, last.get("briefing"))) is not None:
                    runs.insert(1, ("briefing", after))
        if (friday := email_due(prefs, paths, now, last.get(EMAIL))) is not None:
            runs.append((EMAIL, friday))
        if runs:
            out.append(Account(label, paths, prefs, runs))
    return out


def tick(now: datetime | None = None, budget_s: float = TICK_BUDGET_S) -> dict:
    """Run every job due at `now`; what ran, what was left for the next tick.

    One account's runs one after the other (they share its prefs file), up to
    `WORKERS` accounts at a time. A run not started within `budget_s` is left
    due. Never raises: one broken account is logged and the rest go out.
    """
    now = now or datetime.now(UTC)
    started = clock.monotonic()
    try:
        work = plan(now)
    except Exception as exc:  # noqa: BLE001 — the roster is the bucket's
        obs.warn("schedule.roster_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return {"due": 0, "ran": 0, "deferred": 0}
    ran: list[str] = []
    deferred: list[str] = []

    def one(account: Account) -> None:
        for job, day in account.runs:
            if clock.monotonic() - started > budget_s:
                deferred.append(f"{account.label}:{job}")
                continue
            run(account, job, day)
            ran.append(f"{account.label}:{job}")

    with ThreadPoolExecutor(WORKERS, thread_name_prefix="schedule") as pool:
        # In the request's context: the warm's `cache.SYNC` and the CPU hold's
        # base URL ride along into the workers.
        for account in work:
            pool.submit(contextvars.copy_context().run, one, account)
    total = sum(len(a.runs) for a in work)
    obs.event("schedule.tick", due=total, ran=len(ran), deferred=len(deferred),
              seconds=round(clock.monotonic() - started, 1))
    return {"due": total, "ran": len(ran), "deferred": len(deferred)}


def run(account: Account, job: str, day: date) -> str:
    """One job for one account: write it, file it, push it, mark it run.

    Marked run whatever came of it, a failure included: the next tick would
    otherwise pay a model call every quarter of an hour until the catch-up
    window closed, for the same failure.
    """
    from stocks import accounts

    began = clock.monotonic()
    try:
        status = RUNNERS[job](account, day)
    except Exception as exc:  # noqa: BLE001 — per-run isolation
        status = f"error: {type(exc).__name__}"
        obs.warn("schedule.run_failed", account=account.label, job=job,
                 error_type=type(exc).__name__, error=str(exc)[:200])
    try:
        last = account.prefs.get(LAST_KEY)
        last = dict(last) if isinstance(last, dict) else {}
        last[job] = day.isoformat()
        account.prefs[LAST_KEY] = last
        accounts.update_prefs(account.paths.prefs, {LAST_KEY: last})
    except Exception as exc:  # noqa: BLE001
        obs.warn("schedule.mark_failed", account=account.label, job=job,
                 error_type=type(exc).__name__)
    obs.event("schedule.run", account=account.label, job=job, day=day.isoformat(),
              status=status, seconds=round(clock.monotonic() - began, 1))
    return status


# ------------------------------------------------------------------ the jobs


# Where the briefing's "change" button lands: the switch and its clock.
SETTINGS_URL = links.path(links.PROFILE, tab="notify", edit="briefing")


def thread_url(cid: str, page: str = links.HOME) -> str:
    """Where a run's notification lands: its thread, opened in the drawer over
    `page` (the shell reads `?thread=` on any of them)."""
    return f"/{page}?thread={quote(cid, safe='')}"


def _landing(account: Account) -> str:
    """The page under the briefing's thread. With a book it is "Sell or add":
    the briefing says what moved, that page says what to do about it, and it
    is the one the accounts that keep coming back open (prod 2026-11-11).
    Without one there is nothing to review, so Home and its start card."""
    from stocks.portfolio import ledger

    with obs.swallow("briefing.landing"):
        if ledger.has_transactions(account.paths.db):
            return links.REVIEW
    return links.HOME


def _push(account: Account, message: dict, job: str) -> int:
    from stocks.notify import webpush

    return webpush.send_all(account.paths.push, message, topic=job)


def _status(filed: str, took: int) -> str:
    if not filed:
        return "not filed"
    return f"filed, pushed {took}" if took else "filed"


def _current_card(account: Account):
    """Home's daily card for the action day now, asked for as Home asks for it
    (`daily_card.request`: a card that already stands costs nothing) and
    waited on; None when none was stored for that day."""
    from stocks.views import briefing, daily_card

    daily_card.request(account.paths, account.lang, force=False)
    deadline = clock.monotonic() + BRIEFING_WAIT_S
    while (job := briefing.running(account.paths)) is not None and not job.done:
        if clock.monotonic() > deadline:
            break
        clock.sleep(1.0)
    card = daily_card.stored(account.paths)
    _, day = briefing.now_day(account.paths)
    return card if card is not None and card.day == day.isoformat() else None


def _card(account: Account, session: date) -> str:
    """The next day's card, written once `session` has closed."""
    card = _current_card(account)
    return f"{card.source}: {card.day}" if card is not None else "skipped: no card"


def _briefing(account: Account, day: date) -> str:
    """The current card — written the evening before (`_card`), or now if
    that run missed it — with its thread marked as this run's and pushed."""
    from stocks.chat import conversations, daily
    from stocks.i18n import translate
    from stocks.notify import render

    card = _current_card(account)
    if card is None:
        return "skipped: no card"
    cid = card.thread or daily.record(account.paths.chat, card)
    if not cid or not conversations.mark_scheduled(
        cid, "briefing", card.day, account.paths.chat
    ):
        return "not filed"
    lines = [i.get("line") for i in card.items] or [e.get("line") for e in card.entries]
    # The way out is on the notification itself: one press to the switch and
    # the clock, never a hunt through the settings.
    change = {"action": "schedule", "url": SETTINGS_URL,
              "title": translate("notify.briefing_change", card.lang)}
    message = render.message(
        daily.thread_title(card.day, card.lang),
        [card.headline, *lines], thread_url(cid, _landing(account)), "briefing",
        [change],
    )
    return _status(cid, _push(account, message, "briefing"))


def _weekly_email(account: Account, day: date) -> str:
    """Send the Friday email."""
    from stocks.notify import weekly_email

    return weekly_email.send_for(account.label, account.paths, account.prefs, day)


RUNNERS = {CARD: _card, "briefing": _briefing, EMAIL: _weekly_email}
