"""Web grounding for a turn: whether it may search, what it searches for,
and the evidence gathered before the answer is written.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from stocks.chat import (
    agent,
    clock,
    journal,
    market,
    toolbox,
)
from stocks.chat.engine.book import (
    reporting_currency,
)
from stocks.chat.engine.recall import (
    recall_on,
)
from stocks.web import chat_web

if TYPE_CHECKING:

    from stocks.chat.checkpoint import Checkpoint
    from stocks.web.llm import Provider, ToolCall


def web_enabled() -> bool:
    """Whether this turn may touch the internet: whenever a working ddgs
    install says it can.

    There used to be a "chat_web" pref behind it, drawn as an "Internet" chip
    above the composer. Almost nobody moved it off its default, the few who
    did got answers that were quietly worse with nothing on screen saying why,
    and the phone had already dropped the chip for the room it took — so the
    toggle went, and a stored "chat_web" is now ignored."""
    return chat_web.available()


def plan_web(prefs: dict, provider: Provider, api_key: str,
             history: list[dict], context: str = "") -> list[str]:
    """Search queries for the pending answer ([] = none needed / web off).

    Same planner as the web panel (chat_web.plan on the provider's cheapest
    model), with the caller's context (the current view, for the panel) and
    prior user turns riding along for topic continuity."""
    if not web_enabled():
        return []
    return chat_web.plan(provider, api_key, history[-1]["content"],
                         web_context(history, context))


def web_context(history: list[dict], context: str = "") -> str:
    """What a search plan is written against: the date, where the reader is,
    the last user turns and the ticker the conversation is about."""
    prior = [m["content"][:200] for m in history[:-1] if m["role"] == "user"][-2:]
    ctx = f"{clock.line()}." + (
        "\n" + context.strip() if context.strip() else "")
    if prior:
        ctx += "\nEarlier user messages (topic continuity): " + " | ".join(prior)
    topic = topic_ticker(history[:-1])
    if topic and "ticker in focus is" not in ctx:
        ctx += f"\nThe conversation is about {topic}."
    return ctx


def topic_ticker(history: list[dict], window: int = 6) -> str:
    """The ticker the last few turns were about, or "".

    Read off the page link an answer offered (`nav`), which the server checked
    against a real ticker before storing it — not off capitals in the prose,
    where "GMV" and "ETF" look like symbols too. It is what a follow-up means:
    "¿por qué ha subido hoy?" two turns after "¿por qué ha subido Shopify?"
    searched the web for "por qué ha subido hoy" and read four pages about
    nothing.

    Newest first, and a reader's turn that names something is newer than any
    link above it: its symbol is the topic, and a name no symbol is typed
    for ends the search with "" rather than reach past it — "Mira premarket"
    after "Resultados ServiceNow de hoy." searched for the coin a link three
    turns up was about. No lookup: what was typed, or nothing.
    """
    for m in reversed(history[-window:]):
        if m.get("role") == "assistant":
            nav = m.get("nav")
            if isinstance(nav, dict) and nav.get("ticker"):
                return str(nav["ticker"]).upper()
        elif m.get("role") == "user":
            text = str(m.get("content") or "")
            said = market.mentioned(text, lookup=lambda _name: "")
            if said:
                return said[0]
            if market.named(text):
                return ""
    return ""


def ground_web(prefs: dict, provider: Provider, api_key: str,
               history: list[dict], context: str = "") -> list[chat_web.Result]:
    """The pages this turn reads: planned searches plus any pasted links.

    No working search install means no internet at all, pasted links
    included."""
    if not web_enabled():
        return []
    return chat_web.collect(plan_web(prefs, provider, api_key, history, context),
                            history[-1]["content"])


def gather_evidence(prefs: dict, provider: Provider, api_key: str,
                    msgs: list[dict], watchlist: Path, db: Path,
                    chat_path: Path | None = None,
                    timeout: float | None = None,
                    focus: str = "",
                    on_tool: Callable[[str, ToolCall, bool], None] | None = None,
                    profile: agent.Profile = agent.FAST,
                    model: str = "",
                    prefs_path: Path | None = None,
                    proposes: bool = False,
                    on_plan: Callable[[list[dict]], None] | None = None,
                    checkpoint: Checkpoint | None = None,
                    ) -> agent.Evidence:
    """The model-directed lookup for a turn (chat/agent.py), as far as
    `profile` lets it go; `model` is the one that will answer, which a DEEP
    gather researches on, and `prefs_path` the tax settings its engines
    replay the ledger under. `proposes` offers it `propose_action`: the
    caller shows a card the reader can press (`_proposed`). `on_plan` is
    told a deep gather's plan each time the model sets it (`agent.gather`).

    `checkpoint` is the run's progress on disk (`chat/checkpoint.py`): each
    lookup is filed there as it returns and the finished evidence once the
    loop is over, and a run picked up after a restart starts from what it
    holds — a finished gather is handed back as it was, shown again in the
    live research, and an unfinished one is answered from its lookups.

    Gated like the fixed pre-flight (`web_enabled`): the tools reach the
    internet. Unsupported or failed both mean Evidence with ok=False, which
    puts the turn back on the fixed path."""
    if not web_enabled():
        return agent.Evidence(ok=False)
    from stocks.web import auth
    from stocks.web.llm import ToolCall

    if checkpoint is not None and (done := checkpoint.evidence) is not None:
        calls = [ToolCall(c["name"], c["args"], c["result"]) for c in done["calls"]]
        if checkpoint.plan and on_plan is not None:
            on_plan(checkpoint.plan)
        for n, call in enumerate(calls):
            if on_tool is not None:
                on_tool(f"tool_kept{n}", call, False)
                on_tool(f"tool_kept{n}", call, True)
        return agent.Evidence(calls, ok=bool(done["ok"]), plan=checkpoint.plan,
                              missing=str(done["missing"] or ""))
    if checkpoint is not None:
        told = on_plan

        def on_plan(plan: list[dict]) -> None:
            checkpoint.planned(plan)
            if told is not None:
                told(plan)

    memory_db, thread, decisions = None, "", None
    if chat_path is not None:
        # Off by the account's own switch: the earlier conversations stay on
        # disk (they are the threads list), but no answer reads them.
        memory_db = auth.memory_path(chat_path) if recall_on(prefs) else None
        thread = auth.active_conversation(chat_path)["id"]
        decisions = journal.path_for(chat_path)
    # `focus` is what "this" and "it" mean: the ticker on the reader's screen.
    ctx = toolbox.Context(watchlist=watchlist, db=db, memory_db=memory_db,
                          journal=decisions, thread=thread, focus=focus,
                          currency=reporting_currency(prefs),
                          prefs_path=prefs_path, proposes=proposes,
                          asked=_asked(msgs))
    evidence = agent.gather(
        provider, api_key, msgs, ctx, model=model, profile=profile,
        timeout=timeout, on_tool=on_tool, on_plan=on_plan,
        known=checkpoint.known() if checkpoint is not None else None,
        on_call=checkpoint.called if checkpoint is not None else None)
    if checkpoint is not None:
        checkpoint.gathered(evidence.calls, evidence.ok, evidence.missing)
    return evidence


# The reader's turns a proposal may answer to (`toolbox.Context.asked`): a
# follow-up ("¿y AMD?") keeps the ask from two turns back, while an "avísame"
# from far up the thread does not license today's alert.
ASKED_TURNS = 3


def _asked(msgs: list[dict]) -> tuple[str, ...]:
    said = [str(m.get("content") or "") for m in msgs if m.get("role") == "user"]
    return tuple(said[-ASKED_TURNS:])
