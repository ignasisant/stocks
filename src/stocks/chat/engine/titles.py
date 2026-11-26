"""Thread titles, written by the model after the first exchange.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat.engine.instructions import (
    _LANG_NAME,
)

if TYPE_CHECKING:

    from stocks.llm import Provider


TITLE_MAX_CHARS = 60

_TITLE_SYSTEM = (
    "You name chat conversations. Reply with ONLY a title for the "
    "conversation that the message below opens: at most 6 words, no quotes, "
    "no trailing period, written in the same language as the message. Name "
    "the subject (ticker, company, topic), not the request."
)


def _title_system(lang: str | None) -> str:
    """The title prompt, in the account's language when the caller knows it.

    Same rule as `language_rule` for the answer: the language the reader
    picked in the app decides, whatever the message is written in. It also
    settles a greeting, which the small models the free chain runs on read
    as whichever Romance language they lean to ("hola" got a Portuguese
    thread name on a Spanish account)."""
    if not lang:
        return _TITLE_SYSTEM
    name = _LANG_NAME.get(lang, _LANG_NAME["en"])
    return _TITLE_SYSTEM.replace(
        "written in the same language as the message",
        f"written in {name}, whatever language the message is in")


def _trim(text: str) -> str:
    """Cap a title at TITLE_MAX_CHARS on a word boundary, not mid-word."""
    text = text.strip()
    if len(text) <= TITLE_MAX_CHARS:
        return text
    cut = text[:TITLE_MAX_CHARS]
    head, sep, _ = cut.rpartition(" ")
    return ((head if sep and len(head) >= TITLE_MAX_CHARS // 2 else cut).rstrip(
        " ,;:-") + "\u2026")


def title_for(provider: Provider, api_key: str, message: str,
              lang: str | None = None) -> str:
    """A short conversation title for `message`.

    One call on the provider's cheapest model — the same shape as the skill
    router. Any failure (network, empty reply) degrades to a trimmed copy of
    the message itself, so a thread is never left unnamed."""
    fallback = _trim(" ".join(message.split()))
    try:
        raw = provider.complete(
            api_key,
            provider.classifier_model or provider.default_model,
            _title_system(lang),
            [{"role": "user", "content": message[:500]}],
        )
    except Exception as exc:
        obs.warn("chat.engine.title_failed", provider=provider.id,
                 model=provider.classifier_model or provider.default_model,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return fallback
    title = " ".join((raw or "").split()).strip().strip("\"'\u201c\u201d").rstrip(".")
    return _trim(title) or fallback


def autotitle(chat_path: Path, provider: Provider, api_key: str,
              history: list[dict], lang: str | None = None,
              thread: str | None = None) -> None:
    """Name the active thread — or `thread`, the one the turn was asked in —
    from its opening question, once.

    Fires on the first answered turn of a still-unnamed, never-renamed
    conversation, so the extra classifier call happens once per thread and
    never for a title the user chose. Not only the opening pair: a first turn
    the app answered itself (an import nudge, a memory command, a refusal)
    names nothing, and the thread then stayed nameless for good. Failures
    are swallowed: a nameless thread must not cost the user an answer."""
    opening = next((m for m in history if m.get("role") == "user"), None)
    if opening is None or history[-1].get("role") != "assistant":
        return
    from stocks.chat import conversations

    try:
        conv = conversations.active_conversation(chat_path, thread)
        if conv.get("title") or not conv.get("title_auto", True):
            return
        conversations.autotitle_conversation(
            conv["id"], title_for(provider, api_key, str(opening.get("content") or ""), lang),
            chat_path,
        )
    except Exception as exc:
        obs.warn("chat.engine.autotitle_failed",
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return
