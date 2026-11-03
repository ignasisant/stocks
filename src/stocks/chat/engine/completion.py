"""Completions outside a chat turn (digest, alerts, the daily card), each
attempt sandboxed so an LLM failure degrades to None.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat.engine.providers import (
    chain,
    free_eligible,
    note_free_fallback,
)
from stocks.chat.engine.quota import (
    _spend_global_free,
)

if TYPE_CHECKING:

    pass

# The free chain, one patient caller at a time. groq's 8k tokens a minute fit
# about one card: four 08:30 cards at once (2026-11-03) were four 429s, groq
# rested, and the free models behind it too slow to answer two of them. The
# wait for the turn comes out of the caller's own timeout.
_FREE_TURN = threading.Lock()


def _patiently(complete, *args):
    from stocks.web import llm

    with llm.patient():
        return complete(*args)


def complete_attempts(
    prefs: dict,
    system: str,
    messages: list[dict],
    timeout_s: float,
    *,
    spend_free: Callable[[dict], bool],
    accept: Callable[[str], object] | None = None,
    session_keys: dict[str, str] | None = None,
    patient: bool = False,
):
    """First resolved provider whose reply `accept` keeps, or None. Never raises.

    The completion path for everything that is *not* a chat turn — the digest
    and alert lines (notify/narrative.py), the dashboard's daily action
    (chat/daily/). Those must never fail, or even stall, because of an LLM,
    so every attempt is sandboxed: a bad key, a rate limit or a hung provider
    falls through to the next candidate, and the whole loop degrades to None.

    `accept` turns a raw completion into whatever the caller wants (a trimmed
    line, a parsed object) and returns None to reject it — a provider that
    answers with noise is a miss, so the next candidate still gets its turn.
    `spend_free` decides how a free-chain attempt is charged and is required,
    not defaulted: the per-account counter (spend_free_quota, for the live app,
    which owns prefs.json) and the process-wide pot (spend_free_global, for the
    crons, which must not write that file) are both correct for their own
    caller and silently wrong for the other one.

    `patient` is for a caller nobody is watching (a scheduled card, a digest
    line): its free-chain attempt waits for `_FREE_TURN` and sits out the
    chain's rate limits (`llm.patient`) rather than race other such callers
    into them.

    The executor is deliberately unwrapped: `with` would block on shutdown
    waiting for a hung worker and defeat the timeout the call exists for.
    """
    keep = accept or (lambda raw: (raw or "").strip() or None)
    try:
        # `session_keys`: a key the caller holds for this request only — the
        # walkthrough's narration for a reader whose key lives in their tab.
        candidates = chain(prefs, session_keys)
    except Exception as exc:
        obs.warn("chat.engine.answer_candidates_failed",
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None
    # Who asked, for `llm.byok_to_free`: "daily", "narrative", "exit_judge"…
    surface = sys._getframe(1).f_globals.get("__name__", "").rsplit(".", 1)[-1]
    missed: list[str] = []
    for provider, key, model in candidates:
        free = getattr(provider, "id", "") == "free"
        if free and not spend_free(prefs):
            continue  # today's free allowance is gone — caller degrades
        queued = patient and free
        began = time.monotonic()
        if queued and not _FREE_TURN.acquire(timeout=timeout_s):
            obs.warn("chat.engine.free_turn_timeout", seconds=timeout_s)
            missed.append("free:queued")
            continue
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            if queued:
                future = pool.submit(
                    _patiently, provider.complete, key, model, system, messages
                )
            else:
                future = pool.submit(provider.complete, key, model, system, messages)
            raw = future.result(timeout=max(0.0, timeout_s - (time.monotonic() - began)))
            # Bound for `accept`, so a reply it rejects is logged against the
            # provider that sent it (structured.parse's llm.off_contract).
            with obs.context(provider=getattr(provider, "id", ""),
                             model=model or getattr(provider, "default_model", "")):
                out = keep(raw)
            if out is not None:
                if getattr(provider, "id", "") == "free":
                    note_free_fallback(surface, prefs, candidates, missed)
                return out
            missed.append(f"{getattr(provider, 'id', '')}:rejected")
        except Exception as exc:
            obs.warn("chat.engine.provider_failed", provider=provider.id,
                     model=model or getattr(provider, "default_model", ""),
                     error_type=type(exc).__name__, error=str(exc)[:300])
            missed.append(f"{getattr(provider, 'id', '')}:{type(exc).__name__}")
            continue  # timeout, bad key, rate limit, unparseable — next one
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            if queued:
                _FREE_TURN.release()
    return None


def spend_free_global(prefs: dict) -> bool:
    """Consume one unit of the *global* free allowance only; False when spent.

    For the notification crons (notify/narrative.py). They deliberately never
    write an account's prefs.json — the live app owns that file — so they
    cannot carry the per-account "free_msgs::<date>" counter spend_free_quota()
    maintains. Skipping the account counter is safe here because the crons
    decide when they run, not the user: at most one digest and one alert
    narration per account per day, which no per-account cap would ever bind.
    What does bind is the shared pot, since a fan-out grows with the roster —
    so that is the one this spends, and eligibility is still checked.
    """
    if not free_eligible(prefs):
        return False
    return _spend_global_free()
