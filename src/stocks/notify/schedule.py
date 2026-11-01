"""Scheduled runs: the AI briefing, the day's numbers and the weekly review,
each at the account's own time and filed in its chat.

Three fixed jobs, each switched by its `notify_<job>` key and timed by
`schedules[job]` ({"time": "HH:MM", "days": [0-6, Monday = 0]}) in the
account's `timezone`. Each run is filed as a chat thread of its own
(`auth.save_scheduled_thread`; the briefing is the daily card's thread,
marked) and pushed to the account's devices with that thread as the tap's
target, so the notification opens what it said and the rest it folded away.

**Inside the app, not a cron.** A run writes chat.json, and the app's live
instance owns that file (`storage`: single container, the local copy is the
current one); a GitHub runner writing it would be overwritten by the next
save, or overwrite one. So Cloud Scheduler calls `POST /v1/schedule/tick`
with the API token every quarter of an hour (infra/cron.tf), and the tick
runs whatever came due since — the request is the CPU, as for the warm.

**Due** is a local wall-clock time on a listed weekday, not yet run that
local day, and at most `CATCH_UP` late: a tick missed by an outage still
delivers this morning's briefing at nine, not at midnight.

**Who**: accounts with a device to push to, or seen in the last
`ACTIVE_DAYS` — a run spends a model call, and an account nobody opens has
nobody to read it.
"""

from __future__ import annotations

import contextvars
import time as clock
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stocks import obs

JOBS = ("briefing", "digest", "weekly")
DEFAULTS: dict[str, dict] = {
    "briefing": {"time": "08:30", "days": [0, 1, 2, 3, 4]},
    "digest": {"time": "22:30", "days": [0, 1, 2, 3, 4]},
    "weekly": {"time": "18:00", "days": [6]},
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
    return ZoneInfo(name.strip() if valid_zone(name) else DEFAULT_ZONE)


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
    """One job as the app applies it: {"on", "time", "days"}. A stored time or
    day list that does not parse is the default's — a settings read must not
    stop a run over one bad key."""
    stored = prefs.get(PREFS_KEY)
    mine = stored.get(job) if isinstance(stored, dict) else None
    mine = mine if isinstance(mine, dict) else {}
    default = DEFAULTS[job]
    at = mine.get("time") if parse_time(mine.get("time")) else default["time"]
    days = clean_days(mine.get("days")) if "days" in mine else default["days"]
    return {"on": bool(prefs.get(f"notify_{job}", True)), "time": at, "days": days}


def slots(prefs: dict) -> dict[str, dict]:
    return {job: slot(prefs, job) for job in JOBS}


def cutoff_hour(prefs: dict, default: int) -> int:
    """Where the account's card day turns over: `default`, or earlier when its
    briefing is scheduled earlier — a briefing sent at 08:30 is today's, and
    under a nine o'clock turnover it would be yesterday's card again."""
    mine = slot(prefs, "briefing")
    at = parse_time(mine["time"])
    if not mine["on"] or at is None:
        return default
    return min(default, at.hour)


# ------------------------------------------------------------------ due


def due(job_slot: dict, tz: ZoneInfo, now: datetime, last: object) -> date | None:
    """The local day a run comes due for at `now`, or None.

    Today's run, or yesterday's for a late slot whose catch-up crosses
    midnight; never one already run (`last`, the local day it last went out).
    """
    at = parse_time(job_slot.get("time"))
    if not job_slot.get("on") or at is None:
        return None
    local = now.astimezone(tz)
    for day in (local.date(), local.date() - timedelta(days=1)):
        if day.weekday() not in job_slot.get("days", []):
            continue
        when = datetime.combine(day, at, tzinfo=tz)
        if when <= local <= when + CATCH_UP and str(last or "") < day.isoformat():
            return day
    return None


def eligible(prefs: dict, devices: int, today: date) -> bool:
    """Whether runs are worth spending on this account (see the module note)."""
    if devices > 0:
        return True
    try:
        seen = date.fromisoformat(str(prefs.get("last_seen") or "")[:10])
    except ValueError:
        return False
    return today - seen <= timedelta(days=ACTIVE_DAYS)


# ------------------------------------------------------------------ the tick


@dataclass
class Account:
    label: str
    paths: object  # accounts.UserPaths
    prefs: dict
    runs: list[tuple[str, date]] = field(default_factory=list)

    @property
    def lang(self) -> str:
        from stocks.notify import webpush

        return self.prefs.get("language") or webpush.lang_of(self.paths.push) or "en"


def _roster() -> list[tuple[str, object]]:
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
        if not eligible(prefs, webpush.devices(paths.push), now.astimezone(tz).date()):
            continue
        last = prefs.get(LAST_KEY) if isinstance(prefs.get(LAST_KEY), dict) else {}
        runs = [
            (job, day)
            for job in JOBS
            if (day := due(slot(prefs, job), tz, now, last.get(job))) is not None
        ]
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


def thread_url(cid: str) -> str:
    """Where a run's notification lands: its thread, opened in the drawer."""
    return f"/?thread={quote(cid, safe='')}"


def _push(account: Account, message: dict, job: str) -> int:
    from stocks.notify import webpush

    return webpush.send_all(account.paths.push, message, topic=job)


def _status(filed: str, took: int) -> str:
    if not filed:
        return "not filed"
    return f"filed, pushed {took}" if took else "filed"


def _notify_user(account: Account):
    """The crons' account record, for the digest's and the review's builders,
    over this process's own files."""
    from stocks import storage
    from stocks.notify.fanout import NotifyUser

    state = account.paths.prefs.with_name("alerts_state.json")
    # The one file a cron still writes beside the app (the hourly alerts):
    # pulled fresh so its edges are not written back stale.
    storage.restore(state)
    return NotifyUser(
        label=account.label,
        prefs=account.prefs,
        watchlist=account.paths.watchlist,
        db=account.paths.db,
        prefs_path=account.paths.prefs,
        state_path=state,
        served=True,
    )


def _title(job: str, day: date, lang: str) -> str:
    from stocks.web.i18n import translate

    return translate(
        f"chat.scheduled_{job}_title", lang,
        day=day.day, month=translate(f"home.month_{day.month}", lang),
    )


def _digest(account: Account, day: date) -> str:
    from stocks.notify import digest
    from stocks.notify.state import load_state
    from stocks.web import auth

    user = _notify_user(account)
    state = load_state(user.state_path)
    data = digest.build_digest(user, state)
    if isinstance(data, str):
        return f"skipped: {data}"
    lang = account.lang
    cid = auth.save_scheduled_thread(
        "digest", day.isoformat(), _title("digest", day, lang),
        digest.digest_markdown(data, lang), account.paths.chat,
    )
    took = _push(account, digest.digest_message(data, lang, thread_url(cid)), "digest")
    # Filed is seen: the thread holds what the push would have said.
    digest.digest_delivered(user, state, data)
    return _status(cid, took)


def _weekly(account: Account, day: date) -> str:
    from stocks.notify import weekly
    from stocks.notify.state import load_state
    from stocks.web import auth

    user = _notify_user(account)
    state = load_state(user.state_path)
    data = weekly.build_weekly(user, state)
    if isinstance(data, str):
        return f"skipped: {data}"
    lang = account.lang
    cid = auth.save_scheduled_thread(
        "weekly", day.isoformat(), _title("weekly", day, lang),
        weekly.weekly_markdown(data, lang), account.paths.chat,
    )
    took = _push(account, weekly.weekly_message(data, lang, thread_url(cid)), "weekly")
    weekly.weekly_delivered(user, state, data)
    return _status(cid, took)


def _briefing(account: Account, day: date) -> str:
    """Home's daily card, asked for as Home asks for it (`daily_card.request`:
    a card that already stands costs nothing), waited on, and its thread
    marked as this run's."""
    from stocks.api import briefing, daily_card
    from stocks.chat import daily
    from stocks.notify import render
    from stocks.web import auth

    lang = account.lang
    daily_card.request(account.paths, lang, force=False)
    deadline = clock.monotonic() + BRIEFING_WAIT_S
    while (job := briefing.running(account.paths)) is not None and not job.done:
        if clock.monotonic() > deadline:
            break
        clock.sleep(1.0)
    card = daily_card.stored(account.paths)
    if card is None or card.day != day.isoformat():
        return "skipped: no card"
    cid = card.thread or daily.record(account.paths.chat, card)
    if not cid or not auth.mark_scheduled(cid, "briefing", card.day, account.paths.chat):
        return "not filed"
    lines = [i.get("line") for i in card.items] or [e.get("line") for e in card.entries]
    message = render.message(
        daily.thread_title(card.day, card.lang),
        [card.headline, *lines], thread_url(cid), "briefing",
    )
    return _status(cid, _push(account, message, "briefing"))


RUNNERS = {"briefing": _briefing, "digest": _digest, "weekly": _weekly}
