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

    from stocks.web.llm import Provider


TITLE_MAX_CHARS = 60

_TITLE_SYSTEM = (
    "You name chat conversations. Reply with ONLY a title for the "
    "conversation that the message below opens: at most 6 words, no quotes, "
    "no trailing period, written in the same language as the message. Name "
    "the subject (ticker, company, topic), not the request."
)


def _title_system(lang: str | None) -> str:
    """The title prompt, with the account's language as the tiebreak.

    A greeting is the most common opener and the least telling: the small
    models the free chain runs on read "hola" or "oi" as whichever Romance
    language they lean to, and a Spanish account got a Portuguese thread name.
    Same rule as `language_rule` for the answer — the message decides, the
    locale settles what the message cannot."""
    if not lang:
        return _TITLE_SYSTEM
    name = _LANG_NAME.get(lang, _LANG_NAME["en"])
    return (
        _TITLE_SYSTEM + " When the message is too short to tell its language — "
        "a greeting, a bare ticker, a number — or could be either of two close "
        f"languages (Spanish or Portuguese, say), write the title in {name}."
    )


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

    Only fires on the first completed pair of a still-unnamed, never-renamed
    conversation, so the extra classifier call happens once per thread and
    never for a title the user chose. Failures are swallowed: a nameless
    thread must not cost the user an answer."""
    if len(history) != 2 or history[0]["role"] != "user":
        return
    from stocks.web import auth

    try:
        conv = auth.active_conversation(chat_path, thread)
        if conv.get("title") or not conv.get("title_auto", True):
            return
        auth.autotitle_conversation(
            conv["id"], title_for(provider, api_key, history[0]["content"], lang),
            chat_path,
        )
    except Exception as exc:
        obs.warn("chat.engine.autotitle_failed",
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return
