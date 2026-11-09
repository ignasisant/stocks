"""One streaming turn: the run a drawer starts, rejoins, stops or holds open."""

from __future__ import annotations

import json
import time
from typing import Literal

from ag_ui.core import ResumeEntry, RunAgentInput, RunErrorEvent, TextPart, UserMessage
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from stocks import navigation, obs
from stocks.accounts import UserPaths
from stocks.api import holds as cpu_hold
from stocks.api import runs
from stocks.api.deps import Account, ChatTurn, Writer
from stocks.api.routes.chat.events import _events, _frame, _settled
from stocks.api.routes.chat.preferences import _prefs, session_keys
from stocks.chat import brief, engine, guide_ai, navigate
from stocks.chat import checkpoint as checkpoints
from stocks.chat.checkpoint import Checkpoint
from stocks.notify import webpush

router = APIRouter(prefix="/chat", tags=["chat"])


# Long enough for a pasted earnings paragraph, short enough that a runaway
# client cannot push a novel through the free chain on someone else's keys.
MAX_MESSAGE = 4000
# A run's `messages` and `tools`, bounded. Only the last message is read (the
# thread on disk is the history), so a client sending more is sending noise.
MAX_RUN_MESSAGES = 50
MAX_RUN_TOOLS = 8


# The code a run cut by Stop ends on (`api/runs.py`): not a refusal, so the
# drawer draws it as the stopped turn it already shows the reader who pressed.
STOPPED = "chat.stopped"


# The page slugs a drawer may say it is on, and the catalog key that names
# each one. The shell's own names (`home`, `import`, `bank`) beside the menu's
# — `navigation.SHELL_PATHS` is what the server hands the document for. A slug
# outside this table is dropped rather than echoed into a system prompt.
_VIEW_LABELS = {
    **{d.path: d.label for d in navigation.DESTINATIONS if d.path},
    "home": "nav.home",
    "import": "nav.import",
    "bank": "bank.title",
}


class Verdict(BaseModel):
    """The reader's answer to a proposal: approve or not, and any edits.

    `ticker` and `args` are the card's edit fields — the same symbol and tool
    fields the classifier filled — and go back through the tool's own parser
    (`tools.revise`), so an edit is held to exactly what a detection was.
    """

    model_config = {"extra": "forbid"}

    approved: bool
    ticker: str | None = Field(default=None, max_length=20)
    args: dict | None = None
    # The proposal's A2UI form (`/form` of its surface), as an alternative to
    # `ticker` + `args`: the drawer sends what the reader typed, and the tool
    # registry turns it back into arguments (`tools.args_from_form`).
    form: dict[str, str] | None = None

    @field_validator("form")
    @classmethod
    def _short(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and (
            len(value) > 12 or any(len(str(v)) > 200 for v in value.values())
        ):
            raise ValueError("a form is at most 12 fields of 200 characters")
        return value

    @field_validator("args")
    @classmethod
    def _small(cls, value: dict | None) -> dict | None:
        if value is not None and len(json.dumps(value)) > 2000:
            raise ValueError("args are at most 2000 characters of JSON")
        return value


class Where(BaseModel):
    """The run's `state`: where the reader is when they ask.

    The page slug and the ticker on screen. The model is told both — "is this a
    good entry?" means nothing without the page it was asked on — and the
    focused symbol also feeds the quote lookup and the gather, so a price for
    "it" is fetched even when the message never names a ticker. Unknown slugs
    and anything that is not a symbol are dropped, not echoed.
    """

    model_config = {"extra": "forbid"}

    view: str = Field(default="", max_length=40)
    focus: str = Field(default="", max_length=40)
    # The page's open `?tab=`, when it has tabs: "what is this column?" on
    # the Fees tab is about fees. Kept only when the page lists it.
    tab: str = Field(default="", max_length=40)


class Forwarded(BaseModel):
    """The run's `forwardedProps`: what this app passes that AG-UI does not name."""

    model_config = {"extra": "forbid"}

    lang: str | None = Field(default=None, max_length=8)
    # Answer the last question again instead of asking a new one. The thread is
    # rewound first — the previous answer *and* the question go, and the
    # question is asked again — so a regenerated turn leaves one pair behind
    # rather than the same question twice with two answers under it.
    regenerate: bool = False
    # The statement a preview card is waiting on, when there is one. "Import
    # these" is then answered with "press the button below", not with "attach
    # the file" — the drawer knows the card is up, the engine cannot.
    staged_import: str = Field(default="", max_length=255)
    # How far the research goes (`agent.profile_for`): "deep" is the panel's
    # "in depth" switch, "" lets the question decide. Never "fast" from the
    # panel — a reader cannot ask for less than the question needs.
    depth: Literal["", "deep"] = ""
    # The angle the ticker page's "Analyse with AI" asked for on the focused
    # symbol (`chat/brief.py`): the server writes the brief the button's short
    # sentence stands for. "" is a typed question.
    # `brief.ANGLES`, spelled out: the field shadows the module here.
    brief: Literal["", "full", "bear", "earnings", "fit"] = ""


class Run(RunAgentInput):
    """One AG-UI run: a question, a regenerate, or the answer to a proposal.

    AG-UI's own `RunAgentInput`, closed and bounded. `threadId` names the
    thread the turn lands in ("" is the active one — a first turn on a fresh
    account has no thread to name yet). Of `messages`, only the last one is
    read, and only when it is the reader's: the thread on disk is the history,
    and a client-sent transcript would be a way to put words in the
    assistant's mouth. `tools` says which frontend tools the client runs —
    `navigate` is the one this server offers to (`chat/navigate.py`).
    """

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(max_length=64)
    run_id: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _bounded(self) -> Run:
        if len(self.messages) > MAX_RUN_MESSAGES:
            raise ValueError(f"at most {MAX_RUN_MESSAGES} messages")
        if len(self.tools or []) > MAX_RUN_TOOLS:
            raise ValueError(f"at most {MAX_RUN_TOOLS} tools")
        if len(self.resume or []) > 1:
            raise ValueError("one proposal is answered per run")
        Where.model_validate(self.state or {})
        Forwarded.model_validate(self.forwarded_props or {})
        return self

    @property
    def where(self) -> Where:
        return Where.model_validate(self.state or {})

    @property
    def props(self) -> Forwarded:
        return Forwarded.model_validate(self.forwarded_props or {})

    @property
    def question(self) -> str:
        """The reader's last message, as text. "" when the run carries none."""
        last = self.messages[-1] if self.messages else None
        if not isinstance(last, UserMessage):
            return ""
        if isinstance(last.content, str):
            text = last.content
        else:
            text = "".join(
                part.text for part in last.content if isinstance(part, TextPart)
            )
        if len(text) > MAX_MESSAGE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"a message is at most {MAX_MESSAGE} characters",
            )
        return text.strip()

    def declares(self, name: str) -> bool:
        return any(tool.name == name for tool in self.tools or [])


def _view(view: str, focus: str, lang: str, tab: str = "") -> tuple[str, str]:
    """(the prompt's "Current view" sentence, the clean focused symbol)."""
    from stocks.i18n import translate

    slug = (view or "").strip().lower()
    label = _VIEW_LABELS.get(slug)
    page = translate(label, lang) if label else ""
    tab_key = navigate.tab_label(slug, tab) if page else ""
    tab_name = translate(tab_key, lang) if tab_key else ""
    sym = engine.clean_focus(focus)
    return engine.view_context(page, sym, tab_name, brief.about(sym)), sym


def _rewind(paths: UserPaths) -> tuple[str, dict]:
    """Take the last answer and its question off the thread; return the
    question, and the ticker brief it was asked with ({} for a typed one —
    `engine.prepare` files it on the turn, so regenerating "Analyse with AI"
    asks the same analysis again, not its one-line label).

    Both, not just the answer: the engine appends the question it is given, so
    leaving the old one in place would file it twice with two answers under it.
    Asking the same question again is what regenerating *is* — the thread ends
    up holding one pair, the new one.
    """
    from stocks.chat import conversations

    history = conversations.load_chat(paths.chat)
    if len(history) < 2 or history[-1].get("role") != "assistant":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this thread does not end in an answer to regenerate",
        )
    asked = history[-2]
    if asked.get("role") != "user" or not str(asked.get("content", "")).strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the answer on this thread has no question above it",
        )
    conversations.save_chat(history[:-2], paths.chat)
    # The same prompt again, to get another answer: not the one kept for it.
    engine.forget_answers(paths.chat)
    briefed = asked.get("brief")
    return str(asked["content"]).strip(), briefed if isinstance(briefed, dict) else {}


def _answer(entry: ResumeEntry) -> Verdict:
    """The reader's verdict out of one resume entry."""
    if entry.status == "cancelled":
        return Verdict(approved=False)
    try:
        said = Verdict.model_validate(entry.payload or {})
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return said


_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    # Nginx and Cloud Run's front end both buffer a response body by default,
    # which would hold every chunk until the turn ended and make the stream
    # pointless.
    "X-Accel-Buffering": "no",
}


@router.post("/runs", summary="Run the assistant (AG-UI, streams the answer)")
def ask(
    body: Run,
    paths: ChatTurn,
    request: Request,
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> StreamingResponse:
    """One chat turn as an AG-UI run, streamed as it is written.

    The body is AG-UI's `RunAgentInput` and the answer its event stream
    (`RUN_STARTED` … `RUN_FINISHED` or `RUN_ERROR`; see `_events`), so any
    AG-UI client can drive the drawer's assistant and ours reads a published
    protocol rather than frame names only it knows. Three kinds of run:

    * a question — the last of `messages`, the reader's;
    * a regenerate — `forwardedProps.regenerate`, with no message;
    * the answer to a proposal — `resume`, one entry naming the interrupt the
      previous run finished on. Approved, the action runs (as edited, when the
      payload carries edits) and the asking turn becomes its confirmation.

    The turn is a write — it appends to chat.json and spends the account's free
    allowance — so it is guarded by `Writer`: a bearer token may read this
    account but may never spend on it.

    A question or a regenerate is answered by a run that outlives this
    response (`api/runs.py`): closing the connection stops the reading, not
    the answer, which is stored as if the reader had stayed. `runId` names it
    for a reader who comes back (`GET /chat/runs/{runId}`) and for Stop
    (`POST /chat/runs/{runId}/stop`). A thread already being answered is a
    409.
    """
    from stocks.chat import conversations

    if body.thread_id:
        if not any(
            c["id"] == body.thread_id
            for c in conversations.list_conversations(paths.chat)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no conversation {body.thread_id}",
            )
        # Asking on a thread makes it the active one, which is what the panel
        # and the bot have always meant by "the conversation". The answer is
        # pinned to it all the same (`thread=` into the engine), so a reader
        # who switches threads mid-answer does not move where it lands.
        conversations.set_active_conversation(body.thread_id, paths.chat)

    props = body.props
    prefs = _prefs(paths)
    lang = (props.lang or prefs.get("language") or "en").strip().lower()
    message = body.question
    asked = [bool(body.resume), props.regenerate, bool(message)]
    if sum(asked) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="a run carries one of: a user message, regenerate, or resume",
        )
    thread = body.thread_id or conversations.active_conversation(paths.chat)["id"]

    if body.resume:
        entry = body.resume[0]
        said = _answer(entry)
        try:
            reply = engine.settle_proposal(
                chat_path=paths.chat, watchlist=paths.watchlist,
                proposal_id=entry.interrupt_id, approve=said.approved, lang=lang,
                ticker=said.ticker, args=said.args, form=said.form,
                db=paths.db,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no proposal {entry.interrupt_id} on this thread",
            ) from exc
        except engine.ProposalError as exc:
            if exc.code == "chat.action_gone":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="this proposal was already answered",
                ) from exc
            reply = engine.Reply(error=exc.code)
        return StreamingResponse(
            _settled(thread=thread, run=body.run_id, reply=reply, lang=lang),
            media_type="text/event-stream",
            headers=_STREAM_HEADERS,
        )

    where = body.where
    view, focus = _view(where.view, where.focus, lang, where.tab)
    # The engine writes the active thread, so that is the one to test: a turn
    # lands on the walkthrough's thread exactly when it is the active one.
    guided = guide_ai.owns(conversations.active_conversation(paths.chat)["id"], prefs)
    answering = runs.on_thread(str(paths.chat), thread)
    if props.regenerate and answering is not None and answering.live:
        # Checked before the rewind, which would otherwise take the pair off
        # the thread for a run that is then refused.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="this thread is still being answered")
    angle = props.brief
    if props.regenerate:
        message, briefed = _rewind(paths)
        if briefed.get("ticker") == focus:
            angle = str(briefed.get("angle") or "")
    held = session_keys(x_chat_provider, x_chat_key)
    asked_how = {
        "lang": lang, "staged_import": props.staged_import.strip(), "view": view,
        "focus": focus, "guided": guided,
        "linked": not guided and body.declares(navigate.TOOL_NAME),
        "depth": props.depth,
        "brief": angle,
    }
    try:
        run = _launch(paths, request, rid=body.run_id, thread=thread,
                      question=message, prefs=prefs, how=asked_how, held=held)
    except runs.Busy as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="this thread is still being answered") from exc
    return StreamingResponse(
        runs.atail(run),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


def _launch(paths: UserPaths, request: Request, *, rid: str, thread: str,
            question: str, prefs: dict, how: dict,
            held: dict[str, str] | None = None,
            resumed: dict | None = None) -> runs.Run:
    """Start run `rid` answering `question` on `thread`, asked `how`
    (`checkpoint.PROPS`), and on Cloud Run hold the CPU for it.

    The run keeps a checkpoint (`chat/checkpoint.py`) — `resumed`, the one a
    process before this one left, or a new one — unless it is on a key held
    for the session only, which may never be written down."""
    point = None
    if resumed is not None:
        point = Checkpoint.resume(paths.chat, resumed)
    elif not held:
        point = Checkpoint.open(paths.chat, rid=rid, thread=thread,
                                question=question, props=how)
    try:
        run = runs.start(
            owner=str(paths.chat),
            rid=rid,
            thread=thread,
            question=question,
            events=lambda _run: _events(
                thread=thread,
                run=rid,
                prefs=prefs,
                paths=paths,
                message=question,
                lang=str(how.get("lang") or "en"),
                staged_import=str(how.get("staged_import") or ""),
                view=str(how.get("view") or ""),
                focus=str(how.get("focus") or ""),
                guided=bool(how.get("guided")),
                linked=bool(how.get("linked")),
                held=held,
                depth=str(how.get("depth") or ""),
                checkpoint=point,
                angle=str(how.get("brief") or ""),
            ),
            stopped=_frame(RunErrorEvent(message=STOPPED, code=STOPPED)),
            failed=lambda frame: '"type":"RUN_ERROR"' in frame,
            # The reader may have put the phone away: tell the devices that
            # asked to be told, unless the app is on screen somewhere.
            done=lambda _run: webpush.answer_ready(
                paths.push, str(paths.chat), thread=thread, question=question
            ),
        )
    except runs.Busy:
        # Refused before it ran: a new checkpoint goes, and a resumed one is
        # the thread's live run's business, not ours.
        if point is not None and resumed is None:
            point.close()
        raise
    if runs.on_cloud_run():
        url = str(request.url_for("hold", rid=run.id))
        runs.hold(run, cpu_hold.pinned(url))
    return run


def _resumed(paths: UserPaths, request: Request, *, thread: str = "",
             rid: str = "") -> runs.Run | None:
    """The run a process before this one was answering on `thread` (or as
    `rid`) and never finished — a deploy, a crash — started again from its
    checkpoint under the same id; None when there is none.

    Run from a read (opening the thread, following the run): the turn was
    asked, and paid for, by the write that started it."""
    record = checkpoints.orphan(paths.chat, thread=thread, rid=rid)
    if record is None:
        return None
    obs.event("chat.run_resumed", age=round(time.time() - float(record["started"])),
              calls=len(record.get("calls") or []),
              gathered=record.get("evidence") is not None,
              charged=bool(record.get("charged")))
    try:
        return _launch(paths, request, rid=str(record["rid"]),
                       thread=str(record["thread"]),
                       question=str(record["question"]), prefs=_prefs(paths),
                       how=dict(record.get("props") or {}), resumed=record)
    except runs.Busy:
        return runs.on_thread(str(paths.chat), str(record["thread"]))


def _run(rid: str, paths: UserPaths, request: Request) -> runs.Run:
    found = runs.find(str(paths.chat), rid) or _resumed(paths, request, rid=rid)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"no run {rid}")
    return found


@router.get("/runs/{rid}", summary="Follow a run again, from its first event")
def rejoin(rid: str, paths: Account, request: Request) -> StreamingResponse:
    """The run's events from `RUN_STARTED` on, then the rest as it is written.

    For a reader who left while it was answered and is back: the thread names
    the run (`Thread.running`), and this replays it. 404 once the run is
    forgotten — a few minutes after it ended — when the thread on disk is the
    whole answer. A run a restart cut is started again from its checkpoint
    (`_resumed`) and followed from there. A read, so `Account`: following an
    answer spends nothing more than its asking already did.
    """
    return StreamingResponse(
        runs.atail(_run(rid, paths, request)),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@router.post("/runs/{rid}/stop", status_code=status.HTTP_204_NO_CONTENT,
             summary="Stop the answer being written")
def stop(rid: str, paths: Writer, request: Request) -> Response:
    """Cut a run: nothing of it is stored, as when Stop was the reader's own
    abort. Closing the connection no longer does this — that only stops the
    reading — so Stop has to say it. Stopping a run that already ended is a
    no-op. A run a restart cut is not started again only to be stopped: its
    checkpoint just goes."""
    found = runs.find(str(paths.chat), rid)
    if found is None and checkpoints.discard(paths.chat, rid):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    run = _run(rid, paths, request)
    if run.live:
        runs.stop(run)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Outside the gate: the caller is this service, holding no session — only the
# run's own token, which never leaves the process (`runs.hold`).
holds = APIRouter(prefix="/chat", tags=["chat"], include_in_schema=False)


@holds.post("/runs/{rid}/hold", name="hold", status_code=status.HTTP_204_NO_CONTENT)
async def hold(rid: str, x_run_hold: str = Header(default="")) -> Response:
    """Stay open until run `rid` is over — Cloud Run's CPU for a reader who
    left (`api/runs.py`). 404 for anything but this process's own token.

    Async, like `api/holds.py`: a hold is open for minutes and must not keep
    one of the request threadpool's threads for them."""
    run = runs.holding(rid, x_run_hold)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await runs.wait_async(run)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
