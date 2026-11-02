"""The free chain's allowance: per account per day, a smaller one for new
accounts, and the process-wide pot the operator's keys share.
"""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING

from stocks import atomic, obs, storage
from stocks.chat.engine.providers import (
    free_eligible,
    in_free_trial,
)
from stocks.config import DATA_DIR
from stocks.secrets_env import secret

if TYPE_CHECKING:

    pass


# The free chain runs on the operator's shared keys, so each account gets a
# modest daily allowance — one runaway user must not drain the quota every
# other account depends on. Override: FREE_LLM_DAILY_CAP env (headless) or
# [free_llm] daily_cap (secrets.toml).
FREE_DAILY_CAP = 30

# What an account gets before it is established (see FREE_ELIGIBILITY).
# A user who just signed up gets to actually try the assistant — being told to
# come back tomorrow is how a new account leaves and never returns — but on a
# small allowance, so farming throwaway Google accounts buys a few messages
# each instead of the full pot. Override: FREE_LLM_TRIAL_CAP env or
# [free_llm] trial_cap.
FREE_TRIAL_CAP = 5


def _configured_daily_cap() -> int:
    try:
        return int(secret("FREE_LLM_DAILY_CAP", "free_llm", "daily_cap")
                   or FREE_DAILY_CAP)
    except (TypeError, ValueError):
        return FREE_DAILY_CAP


def free_trial_cap() -> int:
    try:
        return int(secret("FREE_LLM_TRIAL_CAP", "free_llm", "trial_cap")
                   or FREE_TRIAL_CAP)
    except (TypeError, ValueError):
        return FREE_TRIAL_CAP


def free_daily_cap(prefs: dict | None = None) -> int:
    """Today's allowance for this account, in messages.

    Pass the account's prefs wherever the figure is spent or shown to someone:
    an account still in its trial window gets the smaller cap, and a reader
    told the full one would watch the wall arrive early. Called without prefs
    it answers the configured cap — what a caller holding no account (a CLI
    banner) can honestly mean.
    """
    full = _configured_daily_cap()
    if prefs is not None and in_free_trial(prefs):
        # Never *above* the configured cap: an operator who dialled the daily
        # allowance below the trial one meant that number to be the ceiling.
        return min(free_trial_cap(), full)
    return full


# Cost backstop across ALL accounts: the per-account cap bounds one user, this
# bounds the process — N signed-up accounts times the account cap is otherwise
# the real daily ceiling on shared free-tier keys.
FREE_GLOBAL_DAILY_CAP = 400
_global_free: dict = {"day": "", "used": 0}
_global_free_loaded = False
_global_free_lock = threading.Lock()

# Where the counter survives a restart. Cloud Run recycles the container on
# every deploy and on idle scale-to-zero, and an in-memory counter hands out a
# fresh 400 each time — which is exactly the lever an abuser leans on, since
# the restart is free to provoke. Persisted through the same bucket as
# everything else, so the web app and the headless jobs share one budget.
GLOBAL_FREE_FILE = DATA_DIR / "free_llm_global.json"


def free_global_daily_cap() -> int:
    try:
        return int(secret("FREE_LLM_GLOBAL_DAILY_CAP", "free_llm", "global_daily_cap")
                   or FREE_GLOBAL_DAILY_CAP)
    except (TypeError, ValueError):
        return FREE_GLOBAL_DAILY_CAP


def _load_global_free() -> None:
    """Read today's spend off disk once per process, bucket first.

    Best-effort in both directions: a missing file, a corrupt one or a bucket
    that will not answer all mean "nothing spent yet", which errs generous.
    Erring the other way would deny the free tier to everyone after any read
    hiccup, and the counter is a cost guard, not a ledger.
    """
    global _global_free_loaded
    if _global_free_loaded:
        return
    _global_free_loaded = True
    with obs.swallow("chat.free_quota_restore"):
        if storage.enabled():
            storage.restore(GLOBAL_FREE_FILE)
        saved = json.loads(GLOBAL_FREE_FILE.read_text())
        if saved.get("day") == time.strftime("%Y-%m-%d"):
            _global_free["day"] = saved["day"]
            _global_free["used"] = int(saved.get("used", 0))


def _save_global_free() -> None:
    try:
        GLOBAL_FREE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(GLOBAL_FREE_FILE, _global_free)
        if storage.enabled():
            storage.persist(GLOBAL_FREE_FILE)
    except Exception as exc:  # a counter that cannot be saved still counts
        obs.warn("llm.free.global_save_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])


def _spend_global_free(units: int = 1) -> bool:
    _load_global_free()
    day = time.strftime("%Y-%m-%d")
    cap = free_global_daily_cap()
    # Check and take under one lock: parallel turns each reading `used` below
    # the cap would all pass it. The save stays outside, it reaches the bucket.
    with _global_free_lock:
        if _global_free["day"] != day:
            _global_free["day"], _global_free["used"] = day, 0
        spent = _global_free["used"] + units <= cap
        if spent:
            _global_free["used"] += units
    if not spent:
        obs.event("llm.free.global_cap")
        return False
    _save_global_free()
    return True


# What a deep research turn costs on the free chain, in daily units. Its
# gather runs up to `agent.DEEP.max_calls` lookups and several model rounds
# against the shared free pot, where a quick one runs a handful.
DEEP_UNITS = 2
# Words a question about a made-up symbol may run to and still skip the
# research: "¿qué opinas de ZXQW?", not a paragraph that also asks more.
UNLISTED_WORDS = 12


def spend_free_quota(prefs: dict, units: int = 1) -> bool:
    """Consume `units` of today's free allowance; False when they are not left.

    Mutates `prefs` in place — the caller saves, so every caller
    shares one counter ("free_msgs::<date>"). Keys from previous
    days are dropped on spend so prefs.json never accumulates. The account
    counter is checked first so a capped-out user can't drain the global pot.

    Eligibility is re-checked here rather than trusted from the caller: this
    is the one function every free turn passes through in both surfaces, and
    a gate that only lives in the provider list is a gate a saved preference
    walks around.
    """
    if not free_eligible(prefs):
        return False
    day = time.strftime("%Y-%m-%d")
    key = f"free_msgs::{day}"
    used = int(prefs.get(key, 0))
    if used + units > free_daily_cap(prefs):
        return False
    if not _spend_global_free(units):
        return False
    for stale in [k for k in prefs if k.startswith("free_msgs::") and k != key]:
        prefs.pop(stale)
    prefs[key] = used + units
    return True


def refund_free_quota(prefs: dict, units: int = 1) -> None:
    """Give `units` back to both counters after a turn that answered nothing.

    A unit is spent before the model is called, because that is the only
    moment a turn can still be refused — so a provider that dies takes the
    reader's message *and* their allowance, and the Retry under the failure
    charges them for the same question again. Mutates `prefs` in place (the
    caller saves) and rolls the shared pot back by the same amount, since the
    call that would have cost money never happened.

    Both counters are cost guards, not ledgers: a refund that lands after
    midnight is dropped rather than credited against tomorrow's allowance,
    which is the safe direction to be wrong in.
    """
    if units <= 0:
        return
    day = time.strftime("%Y-%m-%d")
    key = f"free_msgs::{day}"
    used = int(prefs.get(key, 0) or 0)
    if used:
        prefs[key] = max(0, used - units)
    _load_global_free()
    if _global_free["day"] == day and _global_free["used"]:
        _global_free["used"] = max(0, int(_global_free["used"]) - units)
        _save_global_free()


def free_account_left(prefs: dict) -> int:
    """Units left on this account's own counter today."""
    key = f"free_msgs::{time.strftime('%Y-%m-%d')}"
    return max(0, free_daily_cap(prefs) - int(prefs.get(key, 0) or 0))


def free_global_left() -> int:
    """Units left in the shared pot today."""
    _load_global_free()
    if _global_free["day"] != time.strftime("%Y-%m-%d"):
        return free_global_daily_cap()  # a day the counter has not met yet
    return max(0, free_global_daily_cap() - int(_global_free["used"]))


def free_left(prefs: dict) -> int:
    """What a reader actually has left: whichever wall binds first.

    An account holding 12 units in front of an empty shared pot has none, and
    a counter that says 12 walks them into a refusal contradicting it.
    """
    return min(free_account_left(prefs), free_global_left())


# The locale key each free_cap_reason() answer speaks with. Formatted with
# cap=free_daily_cap(prefs) and full=free_daily_cap() — the trial copy is the
# one that needs both, because its news is that the smaller number grows.
FREE_CAP_ERRORS = {
    "account": "chat.free_cap",
    "trial": "chat.free_cap_trial",
    "global": "chat.free_cap_global",
    "ineligible": "chat.free_ineligible",
}


def free_cap_reason(prefs: dict) -> str:
    """Which wall a refused free turn hit: trial, account, global or ineligible.

    Checked in the order spend_free_quota checks them, so the answer names the
    refusal the caller just got instead of making a second, independent guess.
    An account wall hit inside the trial window is its own answer: that reader
    is not out until tomorrow at the same number, they are out until tomorrow
    at a bigger one.
    """
    if not free_eligible(prefs):
        return "ineligible"
    if free_account_left(prefs) <= 0:
        return "trial" if in_free_trial(prefs) else "account"
    return "global"
