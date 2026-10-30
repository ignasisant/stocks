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
instead: a Cloud Scheduler job (infra/cron.tf; `.github/workflows/warm.yml`
by hand) calls `POST /v1/warm` with the API token before the European open,
as its morning readers arrive, after the US open and after each close —
Saturday included, for the weekend's readers. The request is the CPU: the
warm runs on its thread, one account at a time, every stale memo refreshed
in place (`cache.SYNC`) rather than handed to a background thread. The first
of the day is also the one that pays each book's daily chart month
(`loaders._REBASE_S`), so no reader does. Two passes: Home's memos for
every account (`warm_account`), then the other pages' (`warm_more`).
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
    """Repair the book's missing splits, then fill the memos one Home, one
    Portfolio and one Today read: the book's close download and the three
    frames built from it, the watchlist's year, then what Today's sections
    fetch for the largest names."""
    from stocks.api.home import closes_tuple, year_closes

    repair_splits(db)
    mtime = loaders.db_mtime(db)
    loaders.held_closes(db, mtime)
    tbl = loaders.positions_table(db, mtime, base)
    loaders.history(db, mtime, base)
    loaders.basket_values(db, mtime, base)
    entries = load_watchlist(Path(watchlist))
    owned = set(loaders.held(db, mtime))
    # Through `year_closes`, as Home asks: it downloads only the names the
    # book's own prices do not cover, and that smaller tuple is the key Home
    # reads. Warming the whole tuple filled an entry nobody ever asked for.
    year_closes(closes_tuple(entries, owned), db, mtime)
    warm_today(tbl)


def repair_splits(db: str) -> None:
    """Write the splits the book is missing before pricing it, so the memos
    below are filled on the repaired ledger (`portfolio.split_sweep`). Best
    effort: a scan that fails costs the repair, never the warm."""
    from stocks.data import fetch
    from stocks.portfolio import split_sweep

    asked = fetch.unanswered()
    try:
        split_sweep.repair(
            db,
            splits=fetch.splits,
            close_on=fetch.close_on,
            throttled=lambda: (
                fetch.throttle_remaining() > 0 or fetch.unanswered() > asked
            ),
        )
    except Exception as exc:  # noqa: BLE001 — see above
        obs.warn("api.warm_splits_failed", error_type=type(exc).__name__)


# What Today's comparisons and insider section read first: the Review metrics
# of the largest names and the Form 4 feed of the largest US ones. The
# comparisons' own cap, and fewer insider feeds than the section reads (SEC's
# fair-access rule), so a warm is a handful of requests per account.
TODAY_METRICS = 8
TODAY_INSIDERS = 3


def warm_today(tbl) -> None:
    """Fill the memos the Today page's own sections gather from, largest
    positions first. Best effort: each name stands alone, and a feed that
    refuses costs that name, never the account's warm."""
    from stocks.analysis.portfolio import value_weights
    from stocks.chat.daily_routines import _companies

    if tbl is None or getattr(tbl, "empty", True):
        return
    ranked = value_weights(tbl).sort_values(ascending=False, na_position="last")
    names = _companies(str(t) for t in ranked.index)
    us = [t for t in names if "." not in t]
    for fill, tickers in (
        (loaders.review_metrics, names[:TODAY_METRICS]),
        (loaders.insiders, us[:TODAY_INSIDERS]),
    ):
        for ticker in tickers:
            try:
                fill(ticker)
            except Exception as exc:  # noqa: BLE001 — see above
                obs.warn(
                    "api.warm_today_failed",
                    ticker=ticker,
                    error_type=type(exc).__name__,
                )


# The backtest's window, as the risk tab and both Pulso cards ask for it
# (`routes/portfolio.risk`, `routes/pulse`): the one key those pages read.
BOOK_PERIOD = "2y"


def warm_more(db: str, watchlist: str | Path, base: str) -> None:
    """The second pass over an account: the memos behind the pages the
    request log showed waiting on a cold instance after Home — the risk
    tab and the Pulso book card (`basket_report`), the Posiciones spots, the
    calendar's earnings and dividends. Each on its own: a feed that refuses
    costs that memo, never the rest of the pass."""
    mtime = loaders.db_mtime(db)
    entries = load_watchlist(Path(watchlist))
    # The calendar's own key (`routes/earnings`). Anything else warms an
    # entry nobody reads.
    reporting = loaders.calendar_tickers(entries, loaders.held(db, mtime))
    tbl = loaders.positions_table(db, mtime, base)
    currencies = (
        tuple(sorted({str(c).upper() for c in tbl["ccy"] if c}))
        if tbl is not None and not getattr(tbl, "empty", True) and "ccy" in tbl
        else ()
    )
    for name, fill in (
        ("book", lambda: loaders.basket_report(db, mtime, base, BOOK_PERIOD)),
        ("spots", lambda: loaders.spot_rates(currencies, base) if currencies else None),
        ("earnings", lambda: loaders.earnings_calendar(reporting)),
        ("dividends", lambda: loaders.dividend_payments(db, mtime, base)),
    ):
        try:
            fill()
        except Exception as exc:  # noqa: BLE001 — see above
            obs.warn("api.warm_more_failed", memo=name, error_type=type(exc).__name__)


def warm_shared() -> None:
    """The memos every reader shares, once a run: Today's market read, the
    pulse's prices and rates behind Home's market card and Pulso, and the
    CFTC's weekly positioning (Friday's release lands here, not in a read)."""
    for name, fill in (
        ("today_market", loaders.today_market),
        ("pulse_closes", loaders.pulse_closes),
        ("pulse_rate_rows", loaders.pulse_rate_rows),
        ("market_pulse", loaders.market_pulse),
        ("positioning", loaders.positioning),
    ):
        try:
            fill()
        except Exception as exc:  # noqa: BLE001 — see above
            obs.warn(f"api.warm_{name}_failed", error_type=type(exc).__name__)


def warm_recent(today: date | None = None, *, budget_s: float | None = None) -> int:
    """Warm every account seen in the last `RECENT_DAYS`; returns how many.

    Most recently seen first, so a `budget_s` that runs out leaves the
    accounts least likely to be read. Two passes in that order: Home's memos
    for every account first (`warm_account`), then the rest of the pages'
    (`warm_more`), so the second pass on one account never costs another
    its Home. Never raises — a throttled Yahoo or an unreadable ledger is
    logged and skipped, and the next reader simply pays what they would
    have paid anyway.
    """
    from stocks.notify.fanout import iter_all_users

    today = today or date.today()
    started = time.monotonic()
    warmed = 0
    more = 0
    try:
        users = iter_all_users()
    except Exception as exc:  # noqa: BLE001 — boot work must not take the app down
        obs.warn(
            "api.warm_roster_failed",
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return 0
    # One file and two market-wide downloads for every account: once.
    warm_shared()
    recent = [u for u in users if seen_recently(u.prefs.get("last_seen"), today)]
    recent.sort(key=lambda u: str(u.prefs.get("last_seen") or ""), reverse=True)

    def spent(done: int, left: int, stage: str) -> bool:
        if budget_s is not None and time.monotonic() - started > budget_s:
            obs.warn("api.warm_budget_spent", warmed=done, left=left, stage=stage)
            return True
        return False

    def base_of(user) -> str:
        base = str(user.prefs.get("currency") or "EUR").upper()
        return base if base in CURRENCIES else "EUR"

    homed = []
    for i, user in enumerate(recent):
        if spent(warmed, len(recent) - i, "home"):
            break
        with obs.timed("api.warm", account=user.label) as rec:
            try:
                warm_account(str(user.db), str(user.watchlist), base_of(user))
                warmed += 1
                homed.append(user)
            except Exception as exc:  # noqa: BLE001 — see above
                rec["skipped"] = type(exc).__name__
                obs.warn(
                    "api.warm_failed",
                    account=user.label,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
    # Only the accounts whose Home is warm: a ledger that would not price
    # has nothing for the backtest or the calendar either.
    for i, user in enumerate(homed):
        if spent(more, len(homed) - i, "more"):
            break
        with obs.timed("api.warm_more", account=user.label) as rec:
            try:
                warm_more(str(user.db), str(user.watchlist), base_of(user))
                more += 1
            except Exception as exc:  # noqa: BLE001 — see above
                rec["skipped"] = type(exc).__name__
                obs.warn(
                    "api.warm_more_skipped",
                    account=user.label,
                    error_type=type(exc).__name__,
                )
    obs.event(
        "api.warm_run",
        warmed=warmed,
        more=more,
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
