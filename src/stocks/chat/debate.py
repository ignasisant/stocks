"""Bull and bear: two subagents argue a decision before the answer weighs it.

"Should I buy NVDA?" asked of one model gets one voice, and a single voice
drifts to whichever side the question leaned: the user who asks "isn't NVDA a
great buy?" hears that it is. So a question that asks for a decision is argued
first — one analyst builds the strongest honest case for, another the
strongest case against, each off the same evidence the answer will read — and
the answer is written with both in front of it, told to weigh them and say
which is stronger rather than to pick the one the question hoped for.

Each side is an AG-UI subagent: its run is announced, its words stream under
its own id, and it finishes or fails on its own without taking the answer
with it. A side that fails is simply absent; the answer goes on.

Gated tightly, because it is two more model calls on keys that are often the
operator's: an explicit ask for a decision or for both sides, about something
the message names.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING

from stocks import obs

if TYPE_CHECKING:
    from stocks.web.llm import Provider

_ASK_RE = re.compile(
    r"deber[ií]a\s+(?:comprar|vender|entrar|salir|mantener|a[ñn]adir)|"
    r"\bshould\s+i\s+(?:buy|sell|hold|add|trim|exit)\b|"
    r"\bbull(?:ish)?\b.*\bbear|\bbear(?:ish)?\b.*\bbull|"
    r"pros\s+y\s+contras|a\s+favor\s+y\s+en\s+contra|pros\s+and\s+cons|"
    r"\bfor\s+and\s+against\b|es\s+(?:una\s+)?buena\s+compra|\bgood\s+buy\b|"
    r"merece\s+la\s+pena\s+(?:comprar|entrar)|\bworth\s+buying\b|"
    r"tesis\s+(?:alcista|bajista)|\b(?:bull|bear)\s+case\b",
    re.IGNORECASE,
)

TIMEOUT = 25.0
MAX_WORDS = 110

_LANG_NAME = {"en": "English", "es": "Spanish"}

SIDES: dict[str, str] = {
    "bull": (
        "You are the bull analyst in a two-analyst debate. Build the strongest "
        "HONEST case FOR the position the user is weighing: the two or three "
        "best arguments, each tied to a figure or fact from the material you "
        "are given. No hedging, no counter-arguments — the bear analyst has "
        "those."
    ),
    "bear": (
        "You are the bear analyst in a two-analyst debate. Build the strongest "
        "HONEST case AGAINST the position the user is weighing: the two or "
        "three best arguments — valuation, fragility, what would break the "
        "thesis — each tied to a figure or fact from the material you are "
        "given. No hedging, no counter-arguments — the bull analyst has those."
    ),
}

# What both sides got wrong the first time they ran on a real book: the bull
# told the reader "yes, you should buy more" of a stock the book did not hold,
# and quoted a blog's five-year growth forecast as a fact. A side argues a
# thesis; the answer after it is the one that speaks to the reader.
_RULES = (
    "Rules for both analysts:\n"
    "- You argue a case about the security; you do not advise the reader. "
    'Never tell them what to do ("yes, you should buy") — the answer written '
    "after you weighs both cases and is the one that speaks to them.\n"
    "- The material lists the reader's holdings. Do not assume they own the "
    "security unless it is listed there: when it is not, the question is "
    "about opening a position, not adding to one.\n"
    "- Never invent a number that is not in the material. Give each figure "
    "its period when the material says (Q2 2026, trailing twelve months), "
    "and prefer the newest period it has.\n"
    "- Company filings and results, live quotes and the app's own figures "
    "are facts. A figure found only on an opinion or forecast site (Motley "
    "Fool, blogs, price-target aggregators) is that site's claim: name it as "
    "one, never state it as fact."
)


def wants(message: str) -> bool:
    """Whether the message asks for a decision, or for both sides of one."""
    return bool(_ASK_RE.search(message or ""))


def _system(side: str, lang: str) -> str:
    return (
        f"{SIDES[side]}\n\n{_RULES}\n\n"
        f"Write at most {MAX_WORDS} words: a one-line thesis, "
        "then two or three short bullets. Markdown bullets only, no headings. "
        f"Write in {_LANG_NAME.get(lang, 'English')}."
    )


def argue(provider: Provider, api_key: str, model: str, messages: list[dict],
          side: str, lang: str) -> str:
    """One side's case, off the same messages (evidence included) the answer gets."""
    text = provider.complete(api_key, model, _system(side, lang), messages)
    return (text or "").strip()


def run(provider: Provider, api_key: str, messages: list[dict], lang: str, *,
        on_event: Callable[[dict], None] | None = None,
        timeout: float = TIMEOUT) -> list[dict]:
    """Both sides at once. Returns `[{side, text}]` for the sides that spoke.

    `on_event` is told `{kind: "start"|"text"|"end"|"error", id, side, ...}` as
    each side starts and lands — the AG-UI subagent lifecycle, left to the
    caller to put on its own wire. Runs on the provider's cheap model, like
    the gather: arguing from given material is not what the big model is for.
    """
    from stocks.chat.engine import in_parallel

    tell = on_event or (lambda _event: None)
    model = provider.classifier_model or provider.default_model
    ids = {side: f"sub_{side}_{secrets.token_hex(4)}" for side in SIDES}

    def one(side: str) -> dict | None:
        tell({"kind": "start", "id": ids[side], "side": side})
        try:
            text = argue(provider, api_key, model, messages, side, lang)
        except Exception as exc:  # noqa: BLE001 — one side failing is not the answer failing
            obs.warn("chat.debate_side_failed", side=side, provider=provider.id,
                     error_type=type(exc).__name__, error=str(exc)[:300])
            tell({"kind": "error", "id": ids[side], "side": side,
                  "message": "chat.debate_failed"})
            return None
        if not text:
            tell({"kind": "error", "id": ids[side], "side": side,
                  "message": "chat.debate_failed"})
            return None
        tell({"kind": "text", "id": ids[side], "side": side, "text": text})
        tell({"kind": "end", "id": ids[side], "side": side})
        return {"side": side, "text": text}

    got = in_parallel(*(lambda s=side: one(s) for side in SIDES), timeout=timeout)
    spoken = [g for g in got if isinstance(g, dict)]
    obs.event("chat.debated", provider=provider.id, sides=[g["side"] for g in spoken])
    return spoken


def brief(sides: list[dict]) -> str:
    """The paragraph the answer is written against: both cases, and the rule."""
    if not sides:
        return ""
    cases = "\n\n".join(f"{s['side'].upper()} ANALYST:\n{s['text']}" for s in sides)
    return (
        "\n\n---\nTwo analysts argued this before you, from the same material "
        "(the reader has seen both):\n\n"
        f"{cases}\n\n"
        "Weigh them: say which case you find stronger for THIS reader and why, "
        "what would change your mind, and do not simply repeat either one. "
        "An analyst may overstate: correct any figure of theirs the material "
        "does not support, and treat a forecast site's number as its claim. "
        "If the security is not among the reader's holdings, say so rather "
        "than treating the question as adding to a position."
    )
