"""A finished engine turn as AG-UI events: text, steps, tool calls, interrupts."""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator, Iterator, Sequence

from ag_ui.core import (
    ActivitySnapshotEvent,
    BaseEvent,
    CustomEvent,
    Interrupt,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    SubagentErrorEvent,
    SubagentFinishedEvent,
    SubagentStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder

from stocks import obs
from stocks.accounts import UserPaths
from stocks.api.routes.chat.messages import CONFIRM_TOOL, _activities, _call_args
from stocks.chat import engine, guide_ai, navigate
from stocks.chat.checkpoint import Checkpoint

# What `resume[0].payload` may say about a proposal (`Verdict`), as the
# interrupt advertises it to a client that has never seen this server.
RESUME_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "ticker": {"type": "string"},
        "args": {"type": "object"},
        "form": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["approved"],
    "additionalProperties": False,
}


# --------------------------------------------------------------- one turn


_WIRE = EventEncoder()


def _frame(event: BaseEvent) -> str:
    """One AG-UI event as one Server-Sent Event: `data: {json}`, no `event:`
    line — the type rides inside the JSON, which is how AG-UI frames SSE."""
    return _WIRE.encode(event)


def _call(call_id: str, name: str, args: dict, parent: str) -> Iterator[str]:
    """A tool call, whole: start, its arguments in one piece, end.

    Arguments are sent in one delta rather than streamed: they are decided
    after the answer (a marker is only known once the text is), so there is
    nothing to stream them alongside.
    """
    yield _frame(ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name,
                                    parent_message_id=parent))
    yield _frame(ToolCallArgsEvent(
        tool_call_id=call_id, delta=json.dumps(args, ensure_ascii=False)
    ))
    yield _frame(ToolCallEndEvent(tool_call_id=call_id))


def _interrupt(offer: dict, question: str) -> Interrupt:
    """The pause a pending proposal puts on the run, and how to answer it."""
    return Interrupt(
        id=offer["id"],
        reason=CONFIRM_TOOL,
        message=question,
        tool_call_id=offer["id"],
        response_schema=RESUME_SCHEMA,
    )


def _events(
    *, thread: str, run: str, prefs: dict, paths: UserPaths, message: str,
    lang: str, staged_import: str = "", view: str = "", focus: str = "",
    guided: bool = False, linked: bool = False,
    held: dict[str, str] | None = None, depth: str = "",
    checkpoint: Checkpoint | None = None, angle: str = "",
    screenshots: Sequence[str] = (), documents: Sequence[dict] = (),
) -> Generator[str]:
    """The turn, as AG-UI events. Never raises: a stream that dies mid-answer
    cannot be turned back into a status code, so every failure becomes a
    `RUN_ERROR` carrying the locale key the Reply would have carried.

    The engine's phases become steps (`STEP_STARTED`/`STEP_FINISHED`, named by
    the panel's `chat.work_*` keys), who answered is a `CUSTOM` "chat.meta"
    event held until the first real chunk, the words are one text message, and
    `RUN_FINISHED.result` is the finished Reply — authoritative, since the
    chunks were only what made the wait bearable. The research behind it
    streams as it happens: each tool the gather runs is a backend tool call,
    `TOOL_CALL_START`/`ARGS` when it starts and `END`/`RESULT` when it returns,
    so the reader watches "search_web · nvidia guidance" come back as
    "5 results" instead of a spinner over all of it.

    `guided` is a turn on the walkthrough's own thread: the fence in its
    prompt, and its `[[goto:…]]` withheld from the stream and handed over as a
    `navigate` call with `{step}`. `linked` is a client that runs the
    `navigate` tool: the page list in the prompt and its `[[open:…]]` handed
    over the same way with `{page, tab?, ticker?}`. An app action the engine
    would have run comes back as a `confirm_action` call instead, and the run
    finishes *interrupted* on it — AG-UI's human-in-the-loop pause.

    `checkpoint` keeps the run's progress on disk while it runs
    (`chat/checkpoint.py`) and goes when the stream does, however it ends.
    """
    # Flushes headers (and any proxy buffer) before the model is even asked, so
    # the client's reader resolves immediately instead of at the first token.
    yield ": open\n\n"
    yield _frame(RunStartedEvent(thread_id=thread, run_id=run))
    gates = [
        *([guide_ai.MarkerFilter()] if guided else []),
        *([guide_ai.MarkerFilter(navigate.MARKER_RE)] if linked else []),
    ]
    claimed: dict = {}
    mid = f"msg_{uuid.uuid4().hex[:16]}"
    opened = False
    step: str | None = None
    # Research calls started and not yet returned. One the gather's timeout
    # abandoned is closed before the answer starts, so no call is left open.
    running: set[str] = set()
    # Subagents announced and not yet finished — the same rule for a side of
    # the debate the timeout cut short.
    arguing: set[str] = set()

    def polish(entry: dict) -> None:
        # Runs inside the engine before the answer is stored, so the thread on
        # disk holds the scrubbed words and the button, never the marker.
        if guided:
            sid = guide_ai.claim_goto(entry, gates[0].found)
            if sid:
                claimed["goto"] = sid
        if linked:
            nav = navigate.claim(entry, gates[-1].found)
            if nav:
                claimed["nav"] = nav

    def shown(chunk: str) -> str:
        for gate in gates:
            chunk = gate.feed(chunk) if chunk else chunk
        return chunk

    def tail() -> str:
        out = ""
        for gate in gates:
            out = (gate.feed(out) if out else "") + gate.close()
        return out

    def words(delta: str) -> Iterator[str]:
        nonlocal opened
        if not delta:
            return
        if not opened:
            opened = True
            yield _frame(TextMessageStartEvent(message_id=mid, role="assistant"))
        yield _frame(TextMessageContentEvent(message_id=mid, delta=delta))

    def close_step() -> Iterator[str]:
        nonlocal step
        for cid in sorted(running):
            yield _frame(ToolCallEndEvent(tool_call_id=cid))
        running.clear()
        for sid in sorted(arguing):
            yield _frame(SubagentErrorEvent(subagent_run_id=sid,
                                            message="chat.debate_failed",
                                            code="chat.debate_failed"))
        arguing.clear()
        if step is not None:
            yield _frame(StepFinishedEvent(step_name=step))
            step = None

    def argued(said: dict) -> Iterator[str]:
        # One side of the debate, as an AG-UI subagent: announced, its case as
        # a text message under its own run id, then finished — or failed,
        # which leaves the answer to go on without it.
        sid, kind = str(said["id"]), said["kind"]
        if kind == "start":
            arguing.add(sid)
            yield _frame(SubagentStartedEvent(
                subagent_run_id=sid, name=str(said["side"]),
                description=f"{said['side']} analyst", parent_message_id=mid,
            ))
        elif kind == "text":
            sub = f"msg_{sid}"
            yield _frame(TextMessageStartEvent(message_id=sub, role="assistant",
                                               subagent_run_id=sid))
            yield _frame(TextMessageContentEvent(message_id=sub,
                                                 delta=str(said["text"]),
                                                 subagent_run_id=sid))
            yield _frame(TextMessageEndEvent(message_id=sub, subagent_run_id=sid))
        elif kind == "end" and sid in arguing:
            arguing.discard(sid)
            yield _frame(SubagentFinishedEvent(subagent_run_id=sid,
                                               result={"side": said["side"]}))
        elif kind == "error" and sid in arguing:
            arguing.discard(sid)
            yield _frame(SubagentErrorEvent(subagent_run_id=sid,
                                            message=str(said["message"]),
                                            code=str(said["message"])))

    def research(line: dict) -> Iterator[str]:
        # A backend tool, run here: AG-UI's full call, result included. The
        # result is the line the trace files ("5 results"), not what the tool
        # read — that went to the model, and a page of someone else's site has
        # no business on the wire twice.
        cid = str(line["id"])
        if cid not in running:
            yield _frame(ToolCallStartEvent(tool_call_id=cid,
                                            tool_call_name=str(line["tool"])))
            yield _frame(ToolCallArgsEvent(
                tool_call_id=cid,
                delta=json.dumps(line.get("args") or {}, ensure_ascii=False,
                                 default=str),
            ))
            running.add(cid)
        if "out" in line:
            running.discard(cid)
            yield _frame(ToolCallEndEvent(tool_call_id=cid))
            yield _frame(ToolCallResultEvent(
                message_id=f"res_{cid}", tool_call_id=cid, role="tool",
                content=str(line["out"]) or "-",
            ))

    try:
        for kind, payload in engine.answer_stream(
            prefs=prefs,
            prefs_path=paths.prefs,
            chat_path=paths.chat,
            watchlist=paths.watchlist,
            db=paths.db,
            message=message,
            lang=lang,
            context=engine.MARKDOWN_CONTEXT,
            staged_import=staged_import,
            view=view,
            focus=focus,
            # The walkthrough's fence closes the prompt on its own thread; the
            # page list goes where it would have, on every other one.
            fence=(
                guide_ai.prompt_fence(prefs, prefs.get(guide_ai.PREF_THREAD), lang)
                if guided
                else navigate.prompt_block() if linked else ""
            ),
            session_keys=held,
            polish=polish if gates else None,
            confirm_actions=True,
            debating=True,
            draws=True,
            # Pinned: the reader may switch threads while this one is being
            # answered, and the answer still belongs where it was asked.
            thread=thread,
            depth=depth,
            checkpoint=checkpoint,
            brief=angle,
            screenshots=screenshots,
            documents=documents,
        ):
            if kind == "phase":
                yield from close_step()
                step = name = str(payload)
                yield _frame(StepStartedEvent(step_name=name))
            elif kind == "tool":
                assert isinstance(payload, dict)
                yield from research(payload)
            elif kind == "subagent":
                assert isinstance(payload, dict)
                yield from argued(payload)
            elif kind == "text":
                yield from words(shown(str(payload)))
            elif kind == "meta":
                assert isinstance(payload, dict)
                yield from close_step()
                yield _frame(CustomEvent(name="chat.meta", value=payload))
            elif kind == "plan":
                # The deep research's own plan, replaced whole each time the
                # model updates it; the drawer ticks it off while it waits.
                yield _frame(CustomEvent(name="chat.plan", value=payload))
            elif kind == "recalled":
                # The "based on N conversations" line, drawn while the answer
                # is still being written; `RUN_FINISHED.result` repeats it.
                yield _frame(CustomEvent(name="chat.recalled", value=payload))
            else:
                reply = payload
                assert isinstance(reply, engine.Reply)
                yield from close_step()
                yield from words(tail())
                if reply.error and not reply.text:
                    if opened:
                        yield _frame(TextMessageEndEvent(message_id=mid))
                    # `RUN_ERROR` has no result to carry it in, and a memory
                    # command before the question was carried out regardless:
                    # the refusal still has to say so, undo and all.
                    if reply.learned:
                        yield _frame(CustomEvent(
                            name="chat.learned",
                            value=[dict(c) for c in reply.learned],
                        ))
                    yield _frame(RunErrorEvent(message=reply.error, code=reply.error))
                    return
                # An answer the engine settled without streaming it (an import
                # note, a proposal) arrives whole, as one text message.
                if not opened:
                    yield from words(reply.text)
                if opened:
                    yield _frame(TextMessageEndEvent(message_id=mid))
                if linked and reply.nav and "nav" not in claimed:
                    claimed["nav"] = dict(reply.nav)
                if "goto" in claimed:
                    yield from _call(f"nav_{uuid.uuid4().hex[:12]}", navigate.TOOL_NAME,
                                     {"step": claimed["goto"]}, mid)
                if "nav" in claimed:
                    yield from _call(f"nav_{uuid.uuid4().hex[:12]}", navigate.TOOL_NAME,
                                     claimed["nav"], mid)
                offer = reply.proposal
                asking = offer is not None and offer.get("state") == "pending"
                for shown_ui in _activities(
                    {"activities": list(reply.activities),
                     **({"proposal": offer} if asking else {})},
                    lang,
                ):
                    yield _frame(ActivitySnapshotEvent(
                        message_id=shown_ui["id"],
                        activity_type=shown_ui["type"],
                        content=shown_ui["content"],
                    ))
                if asking:
                    assert offer is not None
                    yield from _call(offer["id"], CONFIRM_TOOL, _call_args(offer), mid)
                yield _frame(RunFinishedEvent(
                    thread_id=thread,
                    run_id=run,
                    result=_result(reply),
                    outcome=(
                        RunFinishedInterruptOutcome(
                            interrupts=[_interrupt(offer, reply.text)]
                        )
                        if asking
                        else None
                    ),
                ))
    except Exception as exc:
        # The engine swallows its own; what lands here is a bug, and the reader
        # only sees "chat.api_error", so the cause has to be in the log.
        obs.error("chat.stream_failed", exc)
        yield _frame(RunErrorEvent(message="chat.api_error", code="chat.api_error"))
    finally:
        # Not on a process that dies mid-run, which is the point: the file
        # stays for the next one (`_resumed`).
        if checkpoint is not None:
            checkpoint.close()


def _result(reply: engine.Reply) -> dict:
    """`RUN_FINISHED.result`: the finished Reply, as the client stores a turn."""
    return {
        "text": reply.text,
        "skills": list(reply.skills),
        "sources": list(reply.sources),
        "provider": reply.provider_id or None,
        "steps": list(reply.steps),
        # What a rating names the stored answer by; absent on a turn no model
        # wrote, which has nothing to rate.
        **({"id": reply.turn_id} if reply.turn_id else {}),
        # Only on a turn that asked or settled one: every other result keeps
        # the shape it has always had.
        **({"proposal": dict(reply.proposal)} if reply.proposal else {}),
        **({"debate": [dict(d) for d in reply.debate]} if reply.debate else {}),
        **({"learned": [dict(c) for c in reply.learned]} if reply.learned else {}),
        **({"recalled": [dict(r) for r in reply.recalled]}
           if reply.recalled else {}),
    }


def _settled(*, thread: str, run: str, reply: engine.Reply,
             lang: str) -> Iterator[str]:
    """The stream for a proposal the reader just answered: one line, done.

    Or one more question: a trade form sent back filled is the same card
    asking again, now the planned trade with its figures (`engine._fill`), so
    the run ends interrupted on it exactly as the run that first asked did.
    """
    mid = f"msg_{uuid.uuid4().hex[:16]}"
    yield _frame(RunStartedEvent(thread_id=thread, run_id=run))
    if reply.error:
        yield _frame(RunErrorEvent(message=reply.error, code=reply.error))
        return
    yield _frame(TextMessageStartEvent(message_id=mid, role="assistant"))
    yield _frame(TextMessageContentEvent(message_id=mid, delta=reply.text))
    yield _frame(TextMessageEndEvent(message_id=mid))
    offer = reply.proposal
    asking = offer is not None and offer.get("state") == "pending"
    if asking:
        assert offer is not None
        for shown_ui in _activities({"proposal": offer}, lang):
            yield _frame(ActivitySnapshotEvent(
                message_id=shown_ui["id"], activity_type=shown_ui["type"],
                content=shown_ui["content"]))
        yield from _call(offer["id"], CONFIRM_TOOL, _call_args(offer), mid)
    yield _frame(RunFinishedEvent(
        thread_id=thread, run_id=run, result=_result(reply),
        outcome=(RunFinishedInterruptOutcome(
            interrupts=[_interrupt(offer, reply.text)]) if asking and offer
            else None),
    ))
