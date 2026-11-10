"""Optional LLM line for the price-alert notification.

Provider resolution, first success wins:
  1. The user's own BYOK key (Fernet-encrypted in prefs.json, same 90-day
     TTL from entry the chat honours) — their key, their billing, their
     provider choice.
  2. The operator's free chain ([free_llm] secrets / FREE_LLM_* env), spent
     against the process-wide daily pot (see _complete).
  3. None — the notification ships computed-only.

Everything here is sandboxed: any exception or a hard timeout falls through
to the next step. An alert must never fail, or even stall,
because of an LLM.
"""

from __future__ import annotations

import json

from stocks.chat import engine

_TTL = engine.BYOK_TTL  # the shared "remembered for 90 days" promise
_LANG_NAME = {"en": "English", "es": "Spanish", "it": "Italian"}
MAX_CHARS = 300
# How many alerts the narration call is shown. A watchlist that fires twenty
# rules at once is a market-wide day, not twenty stories — the first few carry
# the point and the rest only cost tokens.
ALERTS_SHOWN = 8

# BYOK decryption and provider resolution live in the shared chat engine now
# (stocks/chat/engine/); these names stay for the callers and tests.
_decrypt_byok = engine.decrypt_byok
_attempts = engine.attempts


# ------------------------------------------------------------------ prompts


def _persona(lang: str, task: str, prefs: dict | None = None) -> str:
    """The prompt's opening. With `prefs`, it also says who the user is — the
    investor profile the chat reads (`engine.persona`): a line in a notification is
    the same assistant as the chat, writing to the same person."""
    who = ""
    if prefs is not None:
        from stocks import userprefs

        who = engine.persona(userprefs.load_profile(prefs))
    return (
        "You are the portfolio assistant for TopStocks, a stock-tracking app. "
        f"{who}{task} in {_LANG_NAME.get(lang, 'English')}. Plain text only: no "
        "markdown, no emoji, no preamble."
    )


def _remembered(system: str, memories: str) -> str:
    """`system` with the user's saved memories (`engine.memory_block`) and how
    to read them. Last, so the line's own instructions come first and the
    shared reading clause (`engine.MEMORY_USE`) sits right after the list."""
    if not memories:
        return system
    return f"{system}\n\n{memories}{engine.MEMORY_USE}"


def _alerts_prompt(
    hits, lang: str, *, prefs: dict | None = None, memories: str = ""
) -> tuple[str, list[dict]]:
    system = _persona(
        lang,
        "The user's own price alerts just fired. Write exactly 1-2 sentences on "
        "what they have in common and what to watch next",
        prefs,
    ) + (
        " The numbers are already in the message above yours, so do not repeat"
        " them. Never recommend buying, selling or holding anything."
    )
    facts = {
        "alerts": [
            {
                "ticker": h.ticker,
                "rule": h.type,
                "detail": h.message,
                "value": None if h.value is None else round(float(h.value), 4),
            }
            for h in hits[:ALERTS_SHOWN]
        ],
        "total_fired": len(hits),
    }
    system = _remembered(system, memories)
    return system, [{"role": "user", "content": json.dumps(facts)}]


# ------------------------------------------------------------- post-checks


def _sanitize(text: str) -> str | None:
    line = " ".join(text.split()).strip()
    if not line:
        return None
    return line[:MAX_CHARS].rstrip() if len(line) > MAX_CHARS else line


# ----------------------------------------------------------------- the call


def _complete(
    prefs: dict, system: str, messages: list[dict], timeout_s: float
) -> str | None:
    """One sandboxed completion over the resolved providers, or None.

    Free-chain attempts are charged to the process-wide daily pot, never to the
    account's own counter: these jobs must not write prefs.json (the live app
    owns that file), and the per-account counter lives there. The global cap is
    the one that matters for a fan-out anyway — it grows with the roster, and
    the shared free-tier keys are the operator's, not the user's. A BYOK
    attempt is the user's own billing and is never charged.
    """
    return engine.complete_attempts(
        prefs, system, messages, timeout_s,
        spend_free=engine.spend_free_global,
        accept=_sanitize,
        patient=True,  # a fan-out over the roster, read once pushed
    )


def alerts_line(
    hits, prefs: dict, lang: str, timeout_s: float = 45.0, memories: str = ""
) -> str | None:
    """1-2 sentences of context for the alerts that just fired, or None.

    Called once per account per alerts run, only when something is actually
    being sent — the rising-edge/cooldown state in notify/state.py is what
    keeps that rare enough to put on a free tier.
    """
    if not hits:
        return None
    try:
        system, messages = _alerts_prompt(hits, lang, prefs=prefs, memories=memories)
    except Exception:
        return None
    return _complete(prefs, system, messages, timeout_s)
