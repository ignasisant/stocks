"""Per-account alert delivery state — dedupe so hourly checks don't spam.

An alert condition ("NVDA above 190") often stays true for days; the hourly
cron must message on the rising edge, then stay quiet until either the
condition clears (re-arming the edge) or a 24h cooldown passes (one daily
re-reminder while it holds). State lives in alerts_state.json next to the
account's prefs.json and is mirrored to the bucket like every user file.

Several writers share the file, each owning its own keys: the hourly alerts
run (`alerts`), the digest (`highlights`, `tax_reminded`), the weekly review
(`weekly`) and the dormancy nudge (`nudges`) — from the cron or from the app's
own schedule. Each loads the state, spends a while building its message, then
saves only the keys it owns (`save_state(..., only=...)`) over the file as it
is by then, so a digest that took a minute does not put back the alert edges
the hourly run moved meanwhile.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from stocks import userstore
from stocks.config import Alert

VERSION = 1
COOLDOWN_HOURS = 24
# Digest highlights kept for the repetition guard (notify/narrative.py). Long
# enough that "the same sentence again" is caught across a working week, short
# enough that the prompt it is pasted into stays small.
HIGHLIGHTS_KEPT = 5


def fingerprint(ticker: str, alert: Alert) -> str:
    """Stable identity of one alert rule: same rule → same key across runs."""
    threshold = next(
        (f"{name}={val:g}" for name, val in (
            ("price", alert.price), ("pct", alert.pct), ("level", alert.level),
        ) if val is not None),
        "",
    )
    return f"{ticker.upper()}|{alert.type}|{threshold}|w={alert.window or ''}"


def load_state(path: Path) -> dict:
    """State from disk; a fresh structure when missing or corrupt."""
    raw = userstore.read(path)
    if isinstance(raw.get("alerts"), dict):
        raw.setdefault("version", VERSION)
        return raw
    return {"version": VERSION, "alerts": {}}


def save_state(
    state: dict, path: Path, active_fingerprints: set[str] | None = None, *,
    only: Iterable[str] | None = None,
) -> None:
    """Write state (pruning rules no longer on the watchlist) and mirror it.

    `only` names the keys this writer owns: those come from `state`, every
    other key from the file as it is now. Without it `state` replaces the file.
    """
    if active_fingerprints is not None:
        state["alerts"] = {
            fp: rec for fp, rec in state["alerts"].items() if fp in active_fingerprints
        }
    with userstore.lock(path):
        if only is None:
            current = state
        else:
            current = load_state(path)
            for key in only:
                if key in state:
                    current[key] = state[key]
                else:
                    current.pop(key, None)
        userstore.write(path, current)


def should_send(
    state: dict,
    fp: str,
    fired: bool,
    now: datetime,
    cooldown_h: int = COOLDOWN_HOURS,
) -> bool:
    """Decide whether this run messages for `fp`, updating the state in place.

    fired, was clear            -> send (rising edge)
    fired, active, cooldown up  -> send again (daily re-reminder)
    fired, active, in cooldown  -> suppress
    not fired                   -> clear `active` so the next fire is an edge
    """
    rec = state["alerts"].get(fp, {"active": False, "last_sent": None})
    if not fired:
        if rec["active"]:
            state["alerts"][fp] = {**rec, "active": False}
        return False
    if rec["active"] and rec.get("last_sent"):
        last = datetime.fromisoformat(rec["last_sent"])
        if now - last < timedelta(hours=cooldown_h):
            state["alerts"][fp] = rec
            return False
    state["alerts"][fp] = {"active": True, "last_sent": now.isoformat()}
    return True


def recent_highlights(state: dict) -> list[str]:
    """The last few digest highlight lines, oldest first."""
    got = state.get("highlights")
    if not isinstance(got, list):
        return []
    return [str(x) for x in got if str(x).strip()][-HIGHLIGHTS_KEPT:]


def remember_highlight(state: dict, line: str, keep: int = HIGHLIGHTS_KEPT) -> None:
    """Record a sent highlight so tomorrow's prompt can avoid repeating it."""
    if not line.strip():
        return
    state["highlights"] = [*recent_highlights(state), line][-keep:]


TAX_REMINDERS_KEPT = 40


def tax_reminders_due(state: dict, code: str | None, today) -> list:
    """Deadlines inside the 30-day window this account was not yet told about.

    One reminder per deadline, the first weekday digest after it enters the
    window — the digest skips weekends, so "exactly 30 days out" would miss
    whichever deadlines land on a Saturday's T-30.
    """
    from stocks.portfolio.tax import deadlines

    told = set(state.get("tax_reminded") or [])
    return [d for d in deadlines.due_soon(code, today) if d.id not in told]


def remember_tax_reminders(
    state: dict, sent, keep: int = TAX_REMINDERS_KEPT
) -> None:
    """Record delivered reminders; a bounded list, oldest dropped first."""
    told = [str(x) for x in state.get("tax_reminded") or []]
    told += [d.id for d in sent if d.id not in told]
    state["tax_reminded"] = told[-keep:]


def nudges_sent(state: dict) -> list[str]:
    """When this dormancy spell's reminders went out (ISO stamps, oldest first)."""
    got = state.get("nudges")
    if not isinstance(got, list):
        return []
    return [str(x) for x in got if str(x).strip()]


def remember_nudge(state: dict, now: datetime) -> None:
    state["nudges"] = [*nudges_sent(state), now.isoformat()]


def forget_nudges(state: dict) -> None:
    """The account came back: the next spell starts from zero."""
    state.pop("nudges", None)


def previous_top_weight(state: dict) -> float | None:
    """Last week's top-5 concentration, or None the first time round.

    The weekly review's concentration line is only worth reading as a *drift* —
    "top 5 is 68% of the book" is a fact that barely changes and quickly stops
    being read, while "68%, up 3 points in a week" is news. One number is all
    that is kept: the review needs the delta, not a history.
    """
    got = state.get("weekly", {}).get("top_weight")
    try:
        return float(got)
    except (TypeError, ValueError):
        return None


def remember_top_weight(state: dict, weight: float, now: datetime) -> None:
    """Record this week's concentration for next week's comparison."""
    state["weekly"] = {"top_weight": float(weight), "at": now.isoformat()}
