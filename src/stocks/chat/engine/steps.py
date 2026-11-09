"""The lines the panel draws behind its "N steps" counter, built here so every
binding of the engine can show them: what ran for this answer, in the order
it happened, with a one-line result, as {tool, arg, out}: the history turn
stores it and the drawer reads it back.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from stocks.chat import (
    toolbox,
)
from stocks.chat.engine.actions import (
    _tr,
)

if TYPE_CHECKING:

    from stocks.llm import ToolCall


_STEP_ARG_CHARS = 56  # of a tool's argument kept on its line
_STEP_ARG_KEYS = ("query", "url", "tickers", "ticker", "symbol")
_STEP_WHY_CHARS = 60  # of the model's own words for a call (`_step_why`)


def _step_why(args: dict) -> str:
    """What the model said a call was for (`toolbox.REASON`), as one short
    line of plain text: it is the model's words on the reader's screen."""
    text = " ".join(str(args.get(toolbox.REASON) or "").split())
    text = re.sub(r"<[^>]*>|[<>*_`#\[\]]", "", text)
    return text[:_STEP_WHY_CHARS].strip()


def _step_arg(args: dict) -> str:
    """The argument that identifies a call — the query, the URL, the tickers."""
    args = {k: v for k, v in args.items() if k != toolbox.REASON}
    value = next((args[k] for k in _STEP_ARG_KEYS if args.get(k)), None)
    if value is None:
        value = next((v for _, v in sorted(args.items()) if v), "")
    text = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
    return " ".join(text.split())[:_STEP_ARG_CHARS]


def _step_out(call, lang: str) -> str:
    """A search counted in hits; anything else in the characters that reached
    the prompt — a page read that hit a paywall says so by being tiny."""
    from stocks.i18n import translate

    result = call.result or ""
    if call.name == "search_web":
        hits = sum(1 for ln in result.splitlines() if ln.strip().startswith("http"))
        if hits:
            return translate("chat.step_results", lang, n=hits)
    return translate("chat.step_chars", lang, n=len(result))


_LIVE_ARGS_CHARS = 600  # of a call's JSON arguments put on the wire


def live_step(cid: str, call: ToolCall, lang: str, done: bool) -> dict:
    """One tool call as it is happening: the line `trace` will file for it,
    plus its id and its arguments — `out` only once it has returned."""
    args = call.args if len(json.dumps(call.args, default=str)) <= _LIVE_ARGS_CHARS \
        else {}
    step = {"id": cid, "tool": call.name, "arg": _step_arg(call.args),
            "args": args}
    if why := _step_why(call.args):
        step["why"] = why
    if done:
        step["out"] = _step_out(call, lang)
    return step


def trace(evidence, hits: list, live: list, lang: str = "en") -> list[dict]:
    """What ran for this answer, as tool lines.

    Two code paths produce the same shape: the model-directed gather's own
    calls (chat/agent.py), and the fixed pre-flight's search and quote lookup.
    Which one ran is plumbing — what a reader wants is the list of things the
    answer was built on.
    """
    from stocks.i18n import translate

    steps = [
        {"tool": call.name, "arg": _step_arg(call.args), "out": _step_out(call, lang),
         **({"why": why} if (why := _step_why(call.args)) else {})}
        for call in getattr(evidence, "calls", [])
    ]
    if hits:
        # The searches behind the hits, so a rated answer shows what was
        # asked as well as what came back; pasted links carry none.
        asked = list(dict.fromkeys(h.query for h in hits if h.query))
        steps.append({"tool": "search_web", "arg": _step_arg({"query": asked}),
                      "out": translate("chat.step_results", lang, n=len(hits))})
    if live:
        steps.append({
            "tool": "get_quotes",
            "arg": ", ".join(q.ticker for q in live)[:_STEP_ARG_CHARS],
            "out": translate("chat.step_quotes", lang, n=len(live)),
        })
    return steps


def _merged_sources(web: list[dict], gathered: list[dict]) -> list[dict]:
    """The web pages searched beside the gather, then what the gather read —
    the app's own documents among it — each once. Either alone used to win,
    and a fixed-path answer built on a help page cited only the web."""
    out = list(web)
    out += [s for s in gathered if s not in out]
    return out


def _unlisted_step(nowhere: dict, lang: str) -> dict:
    """The one lookup a made-up symbol gets, as a tool line."""
    return {"tool": "get_quotes", "arg": ", ".join(nowhere)[:_STEP_ARG_CHARS],
            "out": _tr("chat.step_quotes", lang, n=0)}
