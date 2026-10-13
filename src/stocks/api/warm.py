"""Price the books people are actually reading before anyone asks.

Every memo in `loaders` is process-local, so a restart — a deploy, an
out-of-memory kill, a scale-to-zero — starts cold, and the first reader after
it paid the whole download in their request: the 2026-09-27 request log had
that reader waiting forty to sixty seconds for Home. This runs once at boot,
on a thread of its own so the health check answers meanwhile, and prices the
book and the watchlist of every account seen in the last few days. Sequential,
one account at a time: the point is to *avoid* a burst against Yahoo, not to
move it to boot.

Opt-in by `STOCKS_BOOT_WARM=1`, which `scripts/deploy.sh` sets only for a
service that keeps an instance around (`--min-instances` ≥ 1). That is the
only shape it helps: such an instance restarts with nobody waiting, so the
warm is free time, whereas a scale-to-zero container boots *because* a
reader is waiting and would only make them wait longer. A dev checkout and a
test client never set it.

Cloud Run allocates CPU to a container only while it serves a request (the
free tier's shape), so a thread left running after startup stops the moment
the server is ready. Hence `WAIT_S`: the lifespan holds readiness for up to
that long while the warm runs with the startup CPU, then serves — the rest
finishes on the first request's CPU, joined by its loaders rather than
duplicated.

The service that does scale to zero — production — is warmed from outside
instead: a GitHub Actions cron (`.github/workflows/warm.yml`) calls
`POST /v1/warm` with the API token before the European open, after the US
open and after each close. The request is the CPU: the warm runs on its
thread, one account at a time, every stale memo refreshed in place
(`cache.SYNC`) rather than handed to a background thread. The first of the
day is also the one that pays each book's daily chart month
(`loaders._REBASE_S`), so no reader does.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from stocks import obs
from stocks.api import cache, loaders, security
from stocks.config import CURRENCIES, load_watchlist

ENV_FLAG = "STOCKS_BOOT_WARM"
WAIT_FLAG = "STOCKS_BOOT_WARM_WAIT_S"
WAIT_S = 30.0
RECENT_DAYS = 3
# The route's wall clock: under Cloud Run's 300s request timeout, with room
# for the account already started when it runs out.
WARM_BUDGET_S = 240.0


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip() in ("1", "true", "yes")


def wait_budget() -> float:
    """How long the lifespan may hold readiness for the warm (`WAIT_S` unless
    the environment says otherwise; anything unreadable is the default)."""
    try:
        return max(0.0, float(os.environ.get(WAIT_FLAG, WAIT_S)))
    except ValueError:
        return WAIT_S


def seen_recently(last_seen: object, today: date, days: int = RECENT_DAYS) -> bool:
    """Whether an account's `last_seen` date (ISO, stamped once a day by the
    login path) falls within the last `days`. Unparseable or absent is no."""
    try:
        when = date.fromisoformat(str(last_seen or "")[:10])
    except ValueError:
        return False
    return today - when <= timedelta(days=days)


def warm_account(db: str, watchlist: str | Path, base: str) -> None:
    """Fill the memos one Home and one Portfolio read: the book's close
    download and the three frames built from it, then the watchlist's year."""
    from stocks.api.home import closes_tuple, year_closes

    mtime = loaders.db_mtime(db)
    loaders.held_closes(db, mtime)
    loaders.positions_table(db, mtime, base)
    loaders.history(db, mtime, base)
    loaders.basket_values(db, mtime, base)
    entries = load_watchlist(Path(watchlist))
    owned = set(loaders.held(db, mtime))
    # Through `year_closes`, as Home asks: it downloads only the names the
    # book's own prices do not cover, and that smaller tuple is the key Home
    # reads. Warming the whole tuple filled an entry nobody ever asked for.
    year_closes(closes_tuple(entries, owned), db, mtime)


def warm_recent(today: date | None = None, *, budget_s: float | None = None) -> int:
    """Warm every account seen in the last `RECENT_DAYS`; returns how many.

    Most recently seen first, so a `budget_s` that runs out leaves the
    accounts least likely to be read. Never raises — a throttled Yahoo or an
    unreadable ledger is logged and skipped, and the next reader simply pays
    what they would have paid anyway.
    """
    from stocks.notify.fanout import iter_all_users

    today = today or date.today()
    started = time.monotonic()
    warmed = 0
    try:
        users = iter_all_users()
    except Exception as exc:  # noqa: BLE001 — boot work must not take the app down
        obs.warn(
            "api.warm_roster_failed",
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return 0
    recent = [u for u in users if seen_recently(u.prefs.get("last_seen"), today)]
    recent.sort(key=lambda u: str(u.prefs.get("last_seen") or ""), reverse=True)
    for i, user in enumerate(recent):
        if budget_s is not None and time.monotonic() - started > budget_s:
            obs.warn("api.warm_budget_spent", warmed=warmed, left=len(recent) - i)
            break
        base = str(user.prefs.get("currency") or "EUR").upper()
        with obs.timed("api.warm", account=user.label) as rec:
            try:
                warm_account(
                    str(user.db),
                    str(user.watchlist),
                    base if base in CURRENCIES else "EUR",
                )
                warmed += 1
            except Exception as exc:  # noqa: BLE001 — see above
                rec["skipped"] = type(exc).__name__
                obs.warn(
                    "api.warm_failed",
                    account=user.label,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
    obs.event(
        "api.warm_run",
        warmed=warmed,
        accounts=len(recent),
        seconds=round(time.monotonic() - started, 1),
    )
    return warmed


router = APIRouter(include_in_schema=False)
_running = threading.Lock()


@router.post("/warm", name="warm")
def warm_now(
    who: Annotated[security.Caller, Depends(security.caller)],
) -> dict[str, object]:
    """Warm the recent accounts now, on this request's CPU. The API token
    only — a signed-in account has no business pricing everybody's book — and
    one at a time: a second call while one runs answers `busy` at once."""
    if who.kind != "token":
        security.refuse()
    if not _running.acquire(blocking=False):
        return {"warmed": 0, "busy": True}
    started = time.monotonic()
    token = cache.SYNC.set(True)
    try:
        warmed = warm_recent(budget_s=WARM_BUDGET_S)
    finally:
        cache.SYNC.reset(token)
        _running.release()
    return {"warmed": warmed, "seconds": round(time.monotonic() - started, 1)}


def start(wait_s: float | None = None) -> threading.Thread | None:
    """Kick the warm off on a daemon thread when the flag says so, and give
    it up to `wait_s` (the environment's budget by default) before returning
    — the startup window is the CPU it gets. Never blocks longer than that:
    a slow Yahoo is the next request's problem, not readiness'."""
    if not enabled():
        return None
    thread = threading.Thread(target=warm_recent, name="boot-warm", daemon=True)
    thread.start()
    thread.join(wait_budget() if wait_s is None else wait_s)
    return thread
