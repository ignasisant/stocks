"""The assistant over HTTP: its threads, its settings, and one streaming turn.

The Streamlit side panel (`web/chat_core.py`) is 3,600 lines of drawer built on
`st.session_state`, and none of that is the assistant — it is the drawer. What
the assistant *is* lives in `stocks.chat.engine`: the provider chain, the free
quota, skill routing, the web grounding, and a turn that ends with a completed
user+assistant pair on disk. This router is the second binding of that engine
(the Telegram bot is the first), so a React drawer and a chat window in Telegram
give the same answer to the same question, and a change to how a turn works is
made once.

Sending is a stream, not a request/response. A chat turn takes ten to forty
seconds against a busy provider, and a client with nothing to show for thirty
of them looks broken — so `POST /chat/runs` answers `text/event-stream` and
the words arrive as the model writes them. The stream is AG-UI
(docs.ag-ui.com): the body is its `RunAgentInput`, the events are its own, an
app action waits on the reader as an interrupt, and a page link is a frontend
tool call. It is a POST rather than an
`EventSource` GET on purpose: the message is a body, bodies are what this API's
CSRF defence is built on (a cross-site form cannot send `application/json`), and
a question typed by a user does not belong in a URL that lands in logs.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

from ag_ui.core import (
    ActivitySnapshotEvent,
    BaseEvent,
    CustomEvent,
    Interrupt,
    ResumeEntry,
    RunAgentInput,
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
    TextPart,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    UserMessage,
)
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from stocks import accounts, navigation
from stocks.accounts import UserPaths
from stocks.api.deps import Account, ChatTurn, SurfaceAction, Writer
from stocks.api.routes import chat_attach
from stocks.chat import a2ui, engine, guide_ai, navigate, tools, whatif
from stocks.portfolio import autodetect
from stocks.web import chat_skills, llm, stt

router = APIRouter(prefix="/chat", tags=["chat"])

# Long enough for a pasted earnings paragraph, short enough that a runaway
# client cannot push a novel through the free chain on someone else's keys.
MAX_MESSAGE = 4000
# A run's `messages` and `tools`, bounded. Only the last message is read (the
# thread on disk is the history), so a client sending more is sending noise.
MAX_RUN_MESSAGES = 50
MAX_RUN_TOOLS = 8

# The tool call a proposal arrives as, and the reason its interrupt names.
CONFIRM_TOOL = "confirm_action"
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

_SKILL_MODES = ("auto", "manual", "off")

# The two headers a session-only key travels in (see `session_keys`). Headers
# rather than body fields because the key has to reach the read that says who
# answers (`GET /chat/state`) as well as the turn, and a GET has no body.
KEY_HEADER = "X-Chat-Key"
PROVIDER_HEADER = "X-Chat-Provider"

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


# ------------------------------------------------------------------ schemas


class Source(BaseModel):
    """One web hit that grounded an answer."""

    title: str = ""
    url: str = ""


class Step(BaseModel):
    """One tool line behind an answer: what ran, on what, and what came back."""

    tool: str
    arg: str = ""
    out: str = ""


class ToolCallOut(BaseModel):
    """One frontend tool call on a stored turn.

    `navigate` with `{step}` is a walkthrough step the model offered
    (`guide_goto` on disk), with `{page, tab?, ticker?}` a page link (`nav`).
    `confirm_action` is a proposal (`proposal`), and `state` says whether it is
    still waiting ("pending") or was answered ("done", "cancelled").
    """

    id: str
    name: str
    args: dict
    state: str | None = None


class DebateSide(BaseModel):
    """One analyst's case: `side` is "bull" or "bear"."""

    side: str
    text: str


class ActivityOut(BaseModel):
    """One AG-UI activity on a stored turn: `type` "a2ui" is a surface, and
    `content.messages` its A2UI v0.9 messages."""

    id: str
    type: str
    content: dict


class Message(BaseModel):
    """One stored turn. `skills`, `web` and `steps` are what the answer was
    built from — the lens, the pages, and the tool trace."""

    role: str
    content: str
    skills: list[str] = []
    web: list[Source] = []
    steps: list[Step] = []
    # Set on a turn the engine answered by *doing* something (an import it
    # refused, a favorite it set) rather than by asking a model.
    action: str | None = None
    # Set on a turn the walkthrough wrote: `step` is the registry id the card
    # presents, `state` is "done" for a receipt and "end" for the last line.
    guide: dict[str, str] | None = None
    # The frontend tool calls the answer carried, as the stream handed them
    # over — so a reloaded turn draws the same buttons as the one watched.
    tool_calls: list[ToolCallOut] = []
    # A2UI surfaces drawn under the answer (`chat/a2ui.py`), as the AG-UI
    # activities the stream carried them in: a pending proposal's edit form.
    activities: list[ActivityOut] = []
    # The bull and bear cases argued before the answer (`chat/debate.py`).
    debate: list[DebateSide] = []


class Conversation(BaseModel):
    """A thread's metadata — no bodies; the list view never needs them."""

    id: str
    title: str
    title_auto: bool
    created: str
    updated: str
    messages: int
    active: bool


class Conversations(BaseModel):
    conversations: list[Conversation]


class Thread(BaseModel):
    id: str
    title: str
    messages: list[Message]


class SkillInfo(BaseModel):
    id: str
    name: str
    description: str


class ProviderInfo(BaseModel):
    """One offered backend. `has_key` is about *this* account, the rest is not."""

    id: str
    label: str
    models: list[str]
    needs_key: bool
    has_key: bool
    model: str = Field(
        description=(
            "The model this account would use on this provider — its saved "
            "choice, or the provider's default when it has none."
        )
    )
    console_url: str = Field(
        description="Where this provider hands out keys. Empty for a keyless one."
    )
    key_placeholder: str = ""
    key_tail: str | None = Field(
        default=None,
        description=(
            "The last four characters of the key this account would use here, "
            "stored or held for the session — enough to tell two keys apart, "
            "not enough to use one. The whole key is `POST "
            "/chat/keys/{provider}/reveal`, for the signed-in owner only."
        ),
    )
    key_session: bool = Field(
        default=False,
        description=(
            "The key in use arrived with this request (`X-Chat-Key`) and is "
            "not stored on the account."
        ),
    )
    key_days_left: int | None = Field(
        default=None,
        description=(
            "Days before the stored key lapses, or null when none is stored. "
            "A key is kept for 90 days from its last use, and never more than "
            "180 from the day it was entered."
        ),
    )
    domain: str | None = None
    connect_url: str | None = Field(
        default=None,
        description=(
            "An OAuth PKCE authorize page that mints this account a key of its "
            "own in one click, instead of a pasted one. The client runs the "
            "flow and hands the key to `PUT /chat/keys/{provider}` (or holds "
            "it for the session) like a typed one. Null: paste a key."
        ),
    )
    connect_token_url: str | None = Field(
        default=None,
        description=(
            "Where the client trades the code `connect_url` sends back, with "
            "its PKCE verifier, for the key. Set exactly when `connect_url` is."
        ),
    )


class State(BaseModel):
    """Everything a drawer has to know before the user types anything.

    `free_left` is null — not 0 — for an account the free chain does not serve
    at all. Zero left is a wall that lifts tomorrow; null is a different fact,
    and a client that renders "0 of 30" at a reader who was never given 30 is
    telling them they spent messages they never sent.
    """

    providers: list[ProviderInfo]
    answering: str | None  # provider id that would serve the next turn
    # The provider the account chose. Usually `answering` too — but a BYOK
    # provider picked and not yet given a key is preferred and does not answer,
    # and a settings screen that showed only `answering` would keep insisting
    # the reader never made the choice they just made.
    preferred: str | None
    free_left: int | None
    free_cap: int | None
    cap_reason: str | None  # locale key, set only when there is a wall
    skills: list[SkillInfo]
    skills_mode: str
    skills_selected: list[str]
    max_manual: int
    # What the composer's paperclip may offer. The extensions are every parser's
    # own plus the three the column mapper reads, so a client that hard-coded a
    # list would silently stop offering the next broker's format
    # (`portfolio.autodetect.supported_types`).
    upload_types: list[str]
    upload_max_mb: int
    # Whether this deployment can turn a recording into text at all. A
    # microphone that apologises on press is worse than no microphone.
    voice: bool
    # Whether a key can be kept on the account at all (`[chat] enc_key`).
    # False leaves "this session only" as the one way to use a key of your
    # own, and the settings screen offers exactly that instead of a form that
    # would be refused on submit.
    key_storage: bool = False


class Settings(BaseModel):
    """The drawer's own preferences. Only the fields sent are changed."""

    model_config = {"extra": "forbid"}

    skills_mode: str | None = None
    skills: list[str] | None = None
    provider: str | None = None
    # Applied to the provider named in the same patch, or to the preferred one.
    # A model belongs to a backend, so the pair travels together or not at all.
    model: str | None = None

    @field_validator("provider")
    @classmethod
    def _offered(cls, value: str | None) -> str | None:
        if value is None:
            return value
        pid = value.strip()
        if pid not in {p.id for p in llm.available_providers()}:
            raise ValueError(f"no provider {pid!r} is offered by this deployment")
        return pid

    @field_validator("skills_mode")
    @classmethod
    def _known_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        mode = value.strip().lower()
        if mode not in _SKILL_MODES:
            raise ValueError(f"skills_mode must be one of {', '.join(_SKILL_MODES)}")
        return mode

    @field_validator("skills")
    @classmethod
    def _known_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        valid = chat_skills.valid_ids()
        unknown = [i for i in value if i not in valid]
        if unknown:
            raise ValueError(f"no such skill: {', '.join(sorted(unknown))}")
        return value[: chat_skills.MAX_MANUAL]


class NewThread(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(default="", max_length=80)


class EditThread(BaseModel):
    """Rename a thread, make it the active one, or both."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=80)
    active: bool | None = None


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

    The page slug and the ticker on screen. The Streamlit panel has always told
    the model both (`chat_core._view_context`) — "is this a good entry?" means
    nothing without the page it was asked on — and the focused symbol also
    feeds the quote lookup and the gather, so a price for "it" is fetched even
    when the message never names a ticker. Unknown slugs and anything that is
    not a symbol are dropped, not echoed.
    """

    model_config = {"extra": "forbid"}

    view: str = Field(default="", max_length=40)
    focus: str = Field(default="", max_length=40)


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


# -------------------------------------------------------------------- reads


def _prefs(paths: UserPaths) -> dict:
    return accounts.load_prefs(paths.prefs)


def session_keys(provider: str | None, key: str | None) -> dict[str, str]:
    """The key this one request brought with it, as `engine.attempts` takes it.

    The React drawer's "this session only" key: held in the tab's
    sessionStorage and sent on each request that needs it, used for that
    request, and never written anywhere — not to prefs, not to a log line
    (nothing in this API logs headers), not to the response. It is what the
    Streamlit panel does with `st.session_state`, and it is the one way to use
    a key of your own on a deployment with no encryption secret.

    Only for a provider this deployment offers and that takes a key; anything
    else is ignored rather than refused, because a stale tab holding a key for
    a provider that has since been switched off should simply fall back to the
    chain it would have had without it.
    """
    pid = (provider or "").strip()
    held = (key or "").strip()
    if not pid or not held or len(held) > 512:
        return {}
    known = llm.PROVIDERS.get(pid)
    if known is None or not known.needs_key:
        return {}
    return {pid: held}


def _view(view: str, focus: str, lang: str) -> tuple[str, str]:
    """(the prompt's "Current view" sentence, the clean focused symbol)."""
    from stocks.web.i18n import translate

    slug = (view or "").strip().lower()
    label = _VIEW_LABELS.get(slug)
    page = translate(label, lang) if label else ""
    sym = engine.clean_focus(focus)
    return engine.view_context(page, sym), sym


def _turn(raw: dict, lang: str = "en") -> Message:
    return Message(
        role=str(raw.get("role", "")),
        content=str(raw.get("content", "")),
        skills=list(raw.get("skills") or []),
        web=[Source(**s) for s in (raw.get("web") or []) if isinstance(s, dict)],
        steps=[
            Step(
                tool=str(s.get("tool", "")),
                arg=str(s.get("arg", "")),
                out=str(s.get("out", "")),
            )
            for s in (raw.get("steps") or [])
            if isinstance(s, dict)
        ],
        action=raw.get("action"),
        guide=(
            {k: str(v) for k, v in raw["guide"].items()}
            if isinstance(raw.get("guide"), dict)
            else None
        ),
        tool_calls=_calls(raw),
        activities=[ActivityOut(**a) for a in _activities(raw, lang)],
        debate=[
            DebateSide(side=str(d.get("side", "")), text=str(d.get("text", "")))
            for d in (raw.get("debate") or [])
            if isinstance(d, dict) and d.get("text")
        ],
    )


def _activities(raw: dict, lang: str) -> list[dict]:
    """The surfaces a stored turn draws. Built from what the turn holds rather
    than stored beside it: a pending proposal's form is a pure function of the
    proposal, and a second copy on disk would be one more thing to go stale."""
    from stocks.web.i18n import translate

    stored = [
        a for a in (raw.get("activities") or [])
        if isinstance(a, dict) and a.get("id") and a.get("type") == a2ui.ACTIVITY_TYPE
        and isinstance(a.get("content"), dict)
    ]
    offer = raw.get("proposal")
    if not (isinstance(offer, dict) and offer.get("state") == "pending"
            and offer.get("id") and offer.get("kind") in tools.TOOLS):
        return stored
    form = a2ui.proposal_form(offer, lambda key: translate(key, lang))
    return [*stored, a2ui.activity(f"form_{offer['id']}", form)]


def _calls(raw: dict) -> list[ToolCallOut]:
    """A stored turn's buttons, as the `tool_calls` the stream sent for it."""
    out: list[ToolCallOut] = []
    if raw.get("guide_goto"):
        out.append(ToolCallOut(id="goto", name=navigate.TOOL_NAME,
                               args={"step": str(raw["guide_goto"])}))
    nav = raw.get("nav")
    if isinstance(nav, dict) and navigate.target(
        "/".join(str(nav.get(k, "")) for k in ("page", "tab", "ticker") if nav.get(k))
    ):
        out.append(ToolCallOut(id="nav", name=navigate.TOOL_NAME,
                               args={k: str(v) for k, v in nav.items()}))
    offer = raw.get("proposal")
    if isinstance(offer, dict) and offer.get("id") and offer.get("kind"):
        out.append(ToolCallOut(id=str(offer["id"]), name=CONFIRM_TOOL,
                               args=_call_args(offer),
                               state=str(offer.get("state") or "pending")))
    return out


def _tail(key: str) -> str | None:
    """The last four characters of a key long enough to spare them."""
    return key[-4:] if len(key) > 12 else None


@router.get("/state", response_model=State, summary="What the assistant can do")
def state(
    paths: Account,
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> State:
    """The drawer's opening read: who answers, on what allowance, with which lens.

    One call rather than four because all of it is decided together — an
    account with its own key has no free allowance to show, and a reader whose
    allowance is gone needs the reason, not the number. A session-only key
    (`X-Chat-Provider` + `X-Chat-Key`) counts here exactly as it does on the
    turn, so the header names the provider that will actually answer.
    """
    return _state(paths, session_keys(x_chat_provider, x_chat_key))


def _state(paths: UserPaths, held: dict[str, str] | None = None) -> State:
    held = held or {}
    prefs = _prefs(paths)
    eligible = engine.free_eligible(prefs)
    left = engine.free_left(prefs) if eligible else None
    chain = engine.chain(prefs, held)
    in_use = {provider.id: key for provider, key, _model in chain}
    return State(
        providers=[
            ProviderInfo(
                id=provider.id,
                label=provider.label,
                models=list(provider.models),
                needs_key=provider.needs_key,
                has_key=provider.id in held
                or engine.byok_alive(prefs, provider.id),
                key_tail=(
                    _tail(in_use[provider.id])
                    if provider.needs_key and in_use.get(provider.id)
                    else None
                ),
                key_session=provider.id in held,
                model=(
                    saved
                    if (saved := prefs.get(f"{provider.id}_model"))
                    in provider.models
                    else provider.default_model
                ),
                console_url=provider.console_url,
                key_placeholder=provider.key_placeholder,
                key_days_left=engine.byok_days_left(prefs, provider.id),
                domain=provider.domain,
                connect_url=provider.connect_url or None,
                connect_token_url=provider.connect_token_url or None,
            )
            for provider in llm.available_providers()
        ],
        answering=chain[0][0].id if chain else None,
        preferred=prefs.get("llm_provider") or llm.default_provider_id(),
        free_left=left,
        free_cap=engine.free_daily_cap(prefs) if eligible else None,
        # Only when there is actually a wall: a reader with allowance left does
        # not need to be told which one they have not hit.
        cap_reason=(
            engine.FREE_CAP_ERRORS[engine.free_cap_reason(prefs)]
            if not left
            else None
        ),
        skills=[
            SkillInfo(id=s.id, name=s.name, description=s.description)
            for s in chat_skills.catalog()
        ],
        skills_mode=prefs.get("chat_skills_mode", "auto"),
        skills_selected=[
            i for i in prefs.get("chat_skills", []) if i in chat_skills.valid_ids()
        ],
        max_manual=chat_skills.MAX_MANUAL,
        upload_types=list(autodetect.supported_types()),
        upload_max_mb=chat_attach.MAX_UPLOAD_MB,
        voice=stt.available(),
        key_storage=engine.can_store_keys(),
    )


@router.get(
    "/conversations", response_model=Conversations, summary="The account's threads"
)
def conversations(paths: Account) -> Conversations:
    """Thread metadata, most recently used first. No bodies.

    Empty for an account that has never chatted. The store synthesizes a blank
    thread for the panel to type into, but it synthesizes a *new id every time*
    until something is saved — so handing that id out would give a client a
    thread it cannot then rename or delete. A read says what exists; the first
    turn (or `POST /chat/conversations`) is what makes one exist.
    """
    from stocks.web import auth

    if not paths.chat.exists():
        return Conversations(conversations=[])
    return Conversations(
        conversations=[
            Conversation(**c) for c in auth.list_conversations(paths.chat)
        ]
    )


@router.get(
    "/conversations/{cid}",
    response_model=Thread,
    summary="One thread, with its turns",
)
def thread(cid: str, paths: Account) -> Thread:
    from stocks.web import auth

    lang = str(_prefs(paths).get("language") or "en")
    book = auth.load_book(paths.chat)
    for conv in book["conversations"]:
        if conv["id"] == cid:
            return Thread(
                id=conv["id"],
                title=conv["title"],
                messages=[_turn(m, lang) for m in conv["messages"]],
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"no conversation {cid}"
    )


# ------------------------------------------------------------------- writes


@router.post(
    "/conversations",
    response_model=Conversation,
    status_code=status.HTTP_201_CREATED,
    summary="Start a thread",
)
def start(body: NewThread, paths: Writer) -> Conversation:
    """New thread, activated. An active thread that is still empty is reused,
    so pressing New twice cannot stack blank threads (`auth.new_conversation`).
    """
    from stocks.web import auth

    cid = auth.new_conversation(paths.chat, body.title)
    return next(
        Conversation(**c)
        for c in auth.list_conversations(paths.chat)
        if c["id"] == cid
    )


@router.patch(
    "/conversations/{cid}",
    response_model=Conversation,
    summary="Rename a thread or make it active",
)
def edit(cid: str, body: EditThread, paths: Writer) -> Conversation:
    from stocks.web import auth

    metas = {c["id"]: c for c in auth.list_conversations(paths.chat)}
    if cid not in metas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no conversation {cid}"
        )
    if body.title is not None:
        # Pins the title: auto-titling never overwrites a name a user chose.
        auth.rename_conversation(cid, body.title, paths.chat)
    if body.active:
        auth.set_active_conversation(cid, paths.chat)
    return next(
        Conversation(**c)
        for c in auth.list_conversations(paths.chat)
        if c["id"] == cid
    )


@router.delete(
    "/conversations/{cid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a thread",
)
def drop(cid: str, paths: Writer) -> None:
    """Drop a thread and forget it from the long-term index.

    404 on an unknown id rather than a silent 204: a client that deleted the
    wrong thing and a client that deleted nothing look identical otherwise.
    """
    from stocks.web import auth

    if not any(c["id"] == cid for c in auth.list_conversations(paths.chat)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no conversation {cid}"
        )
    auth.delete_conversation(cid, paths.chat)


@router.patch("/settings", response_model=State, summary="Change the drawer's settings")
def settings(
    body: Settings,
    paths: Writer,
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> State:
    """Who answers, on which model, with which lens. Returns the whole state,
    so one round-trip both applies the change and re-reads what it implies —
    picking a provider that needs a key changes the allowance, the wall and
    which key the screen should be asking for."""
    changes: dict = {}
    if body.skills_mode is not None:
        changes["chat_skills_mode"] = body.skills_mode
    if body.skills is not None:
        changes["chat_skills"] = body.skills
    if body.provider is not None:
        changes["llm_provider"] = body.provider
    if body.model is not None:
        # A model is a property of one backend, so it is stored under that
        # backend's key — and validated against it here rather than in the
        # schema, which cannot see the provider this patch also sets.
        prefs = _prefs(paths)
        pid = body.provider or prefs.get("llm_provider") or llm.default_provider_id()
        provider = llm.PROVIDERS.get(pid)
        if provider is None or body.model not in provider.models:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{pid} does not serve a model called {body.model!r}",
            )
        changes[f"{pid}_model"] = body.model
    if changes:
        accounts.update_prefs(paths.prefs, changes)
    return _state(paths, session_keys(x_chat_provider, x_chat_key))


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
    held: dict[str, str] | None = None,
) -> Iterator[str]:
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
            else:
                reply = payload
                assert isinstance(reply, engine.Reply)
                yield from close_step()
                yield from words(tail())
                if reply.error and not reply.text:
                    if opened:
                        yield _frame(TextMessageEndEvent(message_id=mid))
                    yield _frame(RunErrorEvent(message=reply.error, code=reply.error))
                    return
                # An answer the engine settled without streaming it (an import
                # note, a proposal) arrives whole, as one text message.
                if not opened:
                    yield from words(reply.text)
                if opened:
                    yield _frame(TextMessageEndEvent(message_id=mid))
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
    except Exception:  # pragma: no cover - the engine already swallows its own
        yield _frame(RunErrorEvent(message="chat.api_error", code="chat.api_error"))


def _call_args(offer: dict) -> dict:
    """A proposal as `confirm_action`'s arguments — what would run."""
    return {"kind": offer["kind"], "ticker": offer["ticker"],
            "args": dict(offer.get("args") or {})}


def _result(reply: engine.Reply) -> dict:
    """`RUN_FINISHED.result`: the finished Reply, as the client stores a turn."""
    return {
        "text": reply.text,
        "skills": list(reply.skills),
        "sources": list(reply.sources),
        "provider": reply.provider_id or None,
        "steps": list(reply.steps),
        # Only on a turn that asked or settled one: every other result keeps
        # the shape it has always had.
        **({"proposal": dict(reply.proposal)} if reply.proposal else {}),
        **({"debate": [dict(d) for d in reply.debate]} if reply.debate else {}),
    }


def _settled(*, thread: str, run: str, reply: engine.Reply) -> Iterator[str]:
    """The stream for a proposal the reader just answered: one line, done."""
    mid = f"msg_{uuid.uuid4().hex[:16]}"
    yield _frame(RunStartedEvent(thread_id=thread, run_id=run))
    if reply.error:
        yield _frame(RunErrorEvent(message=reply.error, code=reply.error))
        return
    yield _frame(TextMessageStartEvent(message_id=mid, role="assistant"))
    yield _frame(TextMessageContentEvent(message_id=mid, delta=reply.text))
    yield _frame(TextMessageEndEvent(message_id=mid))
    yield _frame(RunFinishedEvent(thread_id=thread, run_id=run,
                                  result=_result(reply)))


def _rewind(paths: UserPaths) -> str:
    """Take the last answer and its question off the thread; return the question.

    Both, not just the answer: the engine appends the question it is given, so
    leaving the old one in place would file it twice with two answers under it.
    Asking the same question again is what regenerating *is* — the thread ends
    up holding one pair, the new one.
    """
    from stocks.web import auth

    history = auth.load_chat(paths.chat)
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
    auth.save_chat(history[:-2], paths.chat)
    return str(asked["content"]).strip()


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
    """
    from stocks.web import auth

    if body.thread_id:
        if not any(
            c["id"] == body.thread_id for c in auth.list_conversations(paths.chat)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no conversation {body.thread_id}",
            )
        # The engine writes the *active* thread, which is what the panel and
        # the bot have always meant by "the conversation". Two windows of the
        # same account therefore share one cursor; last one to send wins, and
        # the thread each answer landed in is what the client re-reads.
        auth.set_active_conversation(body.thread_id, paths.chat)

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
    thread = body.thread_id or auth.active_conversation(paths.chat)["id"]

    if body.resume:
        entry = body.resume[0]
        said = _answer(entry)
        try:
            reply = engine.settle_proposal(
                chat_path=paths.chat, watchlist=paths.watchlist,
                proposal_id=entry.interrupt_id, approve=said.approved, lang=lang,
                ticker=said.ticker, args=said.args, form=said.form,
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
            _settled(thread=thread, run=body.run_id, reply=reply),
            media_type="text/event-stream",
            headers=_STREAM_HEADERS,
        )

    if props.regenerate:
        message = _rewind(paths)

    where = body.where
    view, focus = _view(where.view, where.focus, lang)
    # The engine writes the active thread, so that is the one to test: a turn
    # lands on the walkthrough's thread exactly when it is the active one.
    guided = guide_ai.owns(auth.active_conversation(paths.chat)["id"], prefs)
    return StreamingResponse(
        _events(
            thread=thread,
            run=body.run_id,
            prefs=prefs,
            paths=paths,
            message=message,
            lang=lang,
            staged_import=props.staged_import.strip(),
            view=view,
            focus=focus,
            guided=guided,
            linked=not guided and body.declares(navigate.TOOL_NAME),
            held=session_keys(x_chat_provider, x_chat_key),
        ),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


# ---------------------------------------------------------- surface actions


class SurfacePress(BaseModel):
    """A2UI's client-to-server action, as its spec words it."""

    model_config = {"extra": "forbid"}

    name: str = Field(max_length=40)
    surfaceId: str = Field(max_length=80)  # noqa: N815 — A2UI's own field names
    sourceComponentId: str = Field(default="", max_length=80)  # noqa: N815
    timestamp: str = Field(default="", max_length=40)
    context: dict = {}

    @field_validator("context")
    @classmethod
    def _small(cls, value: dict) -> dict:
        if len(json.dumps(value, default=str)) > 2000:
            raise ValueError("an action's context is at most 2000 characters")
        return value


class ActionBody(BaseModel):
    model_config = {"extra": "forbid"}

    action: SurfacePress
    lang: str | None = Field(default=None, max_length=8)


class SurfaceUpdate(BaseModel):
    """What the surface should apply: A2UI v0.9 server messages."""

    messages: list[dict]


@router.post("/actions", response_model=SurfaceUpdate,
             summary="Press something on a surface the assistant drew")
def press(body: ActionBody, paths: SurfaceAction) -> SurfaceUpdate:
    """An A2UI action from a surface in the drawer, answered with the messages
    that update it. No model is asked and nothing is stored: a slider moving
    is the reader exploring, and the answer above it still says what it said.

    One surface answers here today — the what-if sale's slider
    (`chat/whatif.py`), re-run through the tax engine for the shares it now
    names. An action this server has no handler for is a 404, not a guess.
    """
    press_ = body.action
    lang = (body.lang or _prefs(paths).get("language") or "en").strip().lower()
    if press_.surfaceId != whatif.SURFACE_ID or press_.name != whatif.ACTION:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no action {press_.name} on {press_.surfaceId}",
        )
    symbol = engine.clean_focus(str(press_.context.get("ticker") or ""))
    try:
        shares = float(press_.context.get("shares", ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="shares must be a number",
        ) from exc
    from stocks.web.i18n import translate

    sale = whatif.simulate(db=paths.db, prefs_path=paths.prefs, ticker=symbol,
                           shares=shares) if symbol else None
    if sale is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"nothing of {symbol or 'that'} to sell, or no price for it",
        )
    return SurfaceUpdate(messages=whatif.moved(
        sale, lambda key, **kw: translate(key, lang, **kw)
    ))


# ------------------------------------------------------------ provider keys


class ProviderKey(BaseModel):
    """One provider's own API key, on the way in. Never on the way out."""

    model_config = {"extra": "forbid"}

    key: str = Field(min_length=8, max_length=512)


@router.put(
    "/keys/{provider}", response_model=State, summary="Store your own key"
)
def set_key(provider: str, body: ProviderKey, paths: Writer) -> State:
    """Encrypt and keep one provider's key on this account.

    What it buys is the daily cap: the keyless chain runs on the operator's
    shared keys and is rationed, and a key of your own is not. It is stored
    encrypted with the deployment's `[chat] enc_key` and kept for 90 days from
    its last use — a deployment without that secret refuses rather than writing
    a provider key in the clear beside somebody's portfolio.

    Not the only way to use a key: "this session only" is the client keeping
    it (the React drawer holds it in the tab's sessionStorage) and sending it
    per request in `X-Chat-Key` — see `session_keys`. That path writes
    nothing, and it is the one a deployment without the secret still offers.
    """
    if provider not in llm.PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no provider {provider}"
        )
    if not llm.PROVIDERS[provider].needs_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{provider} is keyless and takes no key",
        )
    stored = accounts.stored_prefs(paths.prefs)
    if not engine.save_byok(stored, provider, body.key):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="this deployment cannot store a key: no encryption secret",
        )
    accounts.save_prefs(paths.prefs, stored)
    return _state(paths)


class RevealedKey(BaseModel):
    """One stored key, in full — for the owner's own eyes only."""

    provider: str
    key: str


@router.post(
    "/keys/{provider}/reveal",
    response_model=RevealedKey,
    summary="Show your stored key",
)
def reveal_key(provider: str, paths: Writer) -> JSONResponse:
    """The stored key, decrypted, for the reader who stored it.

    The Streamlit panel's "Show key" toggle, and the one route in this API that
    hands a secret *out*. Three things fence it:

    * `Writer`, so a signed-in session and nothing else. A bearer token reads
      an account but names nobody, and a key is not something any holder of a
      shared token should be able to lift from every account it can name.
    * POST with no body worth sending, rather than a GET: the CSRF defence
      here is built on requests a cross-site page cannot make, a GET is the
      one request any page can trigger, and a secret has no business in a
      response a prefetch or an extension might cache. `no-store` says the
      same to anything between here and the browser.
    * 404 for a keyless provider, a provider with nothing stored, and a key
      that no longer decrypts — the same answer for all three, because the
      reader's next step is the same: type it again.
    """
    known = llm.PROVIDERS.get(provider)
    if known is None or not known.needs_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no provider {provider}"
        )
    key = engine.decrypt_byok(accounts.stored_prefs(paths.prefs), provider)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no key stored for {provider}",
        )
    return JSONResponse(
        RevealedKey(provider=provider, key=key).model_dump(),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.delete(
    "/keys/{provider}", response_model=State, summary="Forget your key"
)
def forget_key(provider: str, paths: Writer) -> State:
    """Delete the stored key, ciphertext included.

    404 on a provider with nothing stored: a client that forgot the wrong one
    and a client that forgot nothing should not look identical.
    """
    if provider not in llm.PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no provider {provider}"
        )
    stored = accounts.stored_prefs(paths.prefs)
    if not engine.forget_byok(stored, provider):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no key stored for {provider}",
        )
    accounts.save_prefs(paths.prefs, stored)
    return _state(paths)
