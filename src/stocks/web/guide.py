"""The guided tour as a conversation — the assistant walks the account in.

Same registry as the modal tour (`onboarding.STEPS`), same copy keys, a
different stage: the steps are appended to a real thread in the assistant
drawer instead of being drawn in a modal. `api/routes/guide.py` runs the
walkthrough; this module is the part of it that is pure state — which step an
account is on, which comes next, and the prefs keys that remember it.

Three things follow from the conversational stage:

1. **A step is a stored turn.** `{"role": "assistant", …, "guide": {"step":
   "import"}}` — the same extra-key convention `action`, `files` and `sources`
   already ride on. So the walkthrough is scrollable, survives a reload, and
   the reader can go back and re-read what they were told. A modal forgets
   everything the moment it closes.
2. **The registry drives it, not a model.** Order, targets and copy come from
   `onboarding.STEPS` and `tour.<id>_*`. An account with no LLM (a brand-new
   one is not free-chain eligible for 24h, see `chat.engine.free_eligible`)
   gets the identical walkthrough, minus prose. Nothing here calls a provider.
3. **It advances on what the account actually did.** Each step's `done`
   predicate is re-evaluated whenever the guide is read, so importing a
   statement in another tab is enough — come back and the guide has already
   moved on and says so.
"""

from __future__ import annotations

from stocks.chat import guide_ai
from stocks.secrets_env import secret
from stocks.web import onboarding

# ------------------------------------------------------------- prefs / state
# prefs.json keys, deliberately distinct from the modal tour's (`tour_done`,
# `tour_seen_version`): the two surfaces can be switched between with the flag
# below, and an account that took one must not read as having taken the other.
PREF_STEP = guide_ai.PREF_STEP  # id of the step the account is on ("" = none)
PREF_DONE = guide_ai.PREF_DONE  # finished, skipped or walked out of
PREF_THREAD = guide_ai.PREF_THREAD  # conversation the guide's turns live in
PREF_OPENS = "guide_opens"  # sessions the drawer has been popped open on

# How many sessions may auto-open the drawer before it goes quiet. An
# onboarding that reopens itself forever is a nag; the guide stays resumable
# by hand (the Profile launcher, `?guide=1`) after this.
MAX_AUTO_OPENS = 3


def surface() -> str:
    """Which onboarding surface this deploy serves: "card", "chat" or "modal".

    "card" (the default since 2026-10-10) interrupts nobody: no drawer popping
    open, no modal. Home's start card is the whole onboarding — a few icons,
    each one a door straight into the section that does the thing — and the
    sections teach themselves (Import has its own stepper). Walkthrough copy
    read before the reader has done anything was the part they skipped.

    "chat" (this walkthrough in the drawer) and "modal" (the tour opening
    itself) are kept whole behind this flag as the rollback; both still answer
    when asked for by URL (`?guide=1`, `?tour=1`).
    """
    got = (secret("GUIDE_SURFACE", "guide", "surface") or "").strip().lower()
    return got if got in ("card", "chat", "modal") else "card"


def steps() -> tuple[onboarding.Step, ...]:
    return onboarding.visible_steps()


def _index(step: onboarding.Step | None) -> int:
    """0-based position of a step, or -1. Used for progress and telemetry."""
    if step is None:
        return -1
    return next((i for i, s in enumerate(steps()) if s.id == step.id), -1)


def _next(step: onboarding.Step | None) -> onboarding.Step | None:
    """The step after this one, or None when it is the last."""
    all_steps = steps()
    idx = _index(step)
    if idx < 0 or idx + 1 >= len(all_steps):
        return None
    return all_steps[idx + 1]


def current(prefs: dict) -> onboarding.Step | None:
    """The step the account is on, or None when the guide is not running."""
    if prefs.get(PREF_DONE):
        return None
    return onboarding.by_id(str(prefs.get(PREF_STEP) or ""))


def active(prefs: dict) -> bool:
    """Whether the guide is started and not finished."""
    return current(prefs) is not None


def owns(conv: dict, prefs: dict) -> bool:
    """Whether this conversation is the guide's own thread, still running.

    The guide writes into one thread and must never append a step card to a
    conversation the user started.
    """
    return active(prefs) and conv.get("id") == prefs.get(PREF_THREAD)


def _has_card(history: list[dict], step_id: str) -> bool:
    """Whether this thread already presents that step (its acknowledgement
    line doesn't count — that one is a receipt, not a card)."""
    return any(
        m.get("guide", {}).get("step") == step_id
        and not m.get("guide", {}).get("state")
        for m in history
    )
