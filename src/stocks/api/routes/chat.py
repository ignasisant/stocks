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
of them looks broken — so `POST /chat/messages` answers `text/event-stream` and
the words arrive as the model writes them. It is a POST rather than an
`EventSource` GET on purpose: the message is a body, bodies are what this API's
CSRF defence is built on (a cross-site form cannot send `application/json`), and
a question typed by a user does not belong in a URL that lands in logs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from stocks import accounts
from stocks.accounts import UserPaths
from stocks.api.deps import Account, ChatTurn, Writer
from stocks.api.routes import chat_attach
from stocks.chat import engine
from stocks.portfolio import autodetect
from stocks.web import chat_skills, chat_web, llm, stt

router = APIRouter(prefix="/chat", tags=["chat"])

# Long enough for a pasted earnings paragraph, short enough that a runaway
# client cannot push a novel through the free chain on someone else's keys.
MAX_MESSAGE = 4000

_SKILL_MODES = ("auto", "manual", "off")


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
    key_days_left: int | None = Field(
        default=None,
        description=(
            "Days before the stored key lapses, or null when none is stored. "
            "A key is kept for 90 days from its last use, and never more than "
            "180 from the day it was entered."
        ),
    )
    domain: str | None = None


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
    web: bool
    web_available: bool
    # What the composer's paperclip may offer. The extensions are every parser's
    # own plus the three the column mapper reads, so a client that hard-coded a
    # list would silently stop offering the next broker's format
    # (`portfolio.autodetect.supported_types`).
    upload_types: list[str]
    upload_max_mb: int
    # Whether this deployment can turn a recording into text at all. A
    # microphone that apologises on press is worse than no microphone.
    voice: bool


class Settings(BaseModel):
    """The drawer's own preferences. Only the fields sent are changed."""

    model_config = {"extra": "forbid"}

    skills_mode: str | None = None
    skills: list[str] | None = None
    web: bool | None = None
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


class Ask(BaseModel):
    model_config = {"extra": "forbid"}

    message: str = Field(default="", max_length=MAX_MESSAGE)
    # Answer the last question again instead of asking a new one. The thread is
    # rewound first — the previous answer *and* the question go, and the
    # question is asked again — so a regenerated turn leaves one pair behind
    # rather than the same question twice with two answers under it.
    regenerate: bool = False
    # The statement a preview card is waiting on, when there is one. "Import
    # these" is then answered with "press the button below", not with "attach
    # the file" — the drawer knows the card is up, the engine cannot.
    staged_import: str = Field(default="", max_length=255)

    @model_validator(mode="after")
    def _one_or_the_other(self) -> Ask:
        if self.regenerate:
            if self.message.strip():
                raise ValueError(
                    "regenerate answers the question already on the thread; "
                    "send it without a message"
                )
            return self
        if not self.message.strip():
            raise ValueError("message must not be empty")
        return self
    # Which thread the turn lands in. Omitted means the active one — which is
    # what a single-window client always wants and what the Telegram bot has.
    conversation: str | None = None
    lang: str | None = None


# -------------------------------------------------------------------- reads


def _prefs(paths: UserPaths) -> dict:
    return accounts.load_prefs(paths.prefs)


def _turn(raw: dict) -> Message:
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
    )


@router.get("/state", response_model=State, summary="What the assistant can do")
def state(paths: Account) -> State:
    """The drawer's opening read: who answers, on what allowance, with which lens.

    One call rather than four because all of it is decided together — an
    account with its own key has no free allowance to show, and a reader whose
    allowance is gone needs the reason, not the number.
    """
    prefs = _prefs(paths)
    eligible = engine.free_eligible(prefs)
    left = engine.free_left(prefs) if eligible else None
    chain = engine.attempts(prefs)
    return State(
        providers=[
            ProviderInfo(
                id=provider.id,
                label=provider.label,
                models=list(provider.models),
                needs_key=provider.needs_key,
                has_key=engine.byok_alive(prefs, provider.id),
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
        web=engine.web_enabled(prefs),
        web_available=chat_web.available(),
        upload_types=list(autodetect.supported_types()),
        upload_max_mb=chat_attach.MAX_UPLOAD_MB,
        voice=stt.available(),
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

    book = auth.load_book(paths.chat)
    for conv in book["conversations"]:
        if conv["id"] == cid:
            return Thread(
                id=conv["id"],
                title=conv["title"],
                messages=[_turn(m) for m in conv["messages"]],
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
def settings(body: Settings, paths: Writer) -> State:
    """Who answers, on which model, with which lens. Returns the whole state,
    so one round-trip both applies the change and re-reads what it implies —
    picking a provider that needs a key changes the allowance, the wall and
    which key the screen should be asking for."""
    changes: dict = {}
    if body.skills_mode is not None:
        changes["chat_skills_mode"] = body.skills_mode
    if body.skills is not None:
        changes["chat_skills"] = body.skills
    if body.web is not None:
        changes["chat_web"] = body.web
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
    return state(paths)


# --------------------------------------------------------------- one turn


def _frame(event: str, data: dict) -> str:
    """One Server-Sent Event. `data` is one line: JSON never contains a raw
    newline, so no multi-line framing is needed and none is parsed."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _events(
    *, prefs: dict, paths: UserPaths, message: str, lang: str,
    staged_import: str = "",
) -> Iterator[str]:
    """The turn, as SSE frames. Never raises: a stream that dies mid-answer
    cannot be turned back into a status code, so every failure becomes a
    `done` frame carrying the same locale key the Reply would have carried."""
    # Flushes headers (and any proxy buffer) before the model is even asked, so
    # the client's reader resolves immediately instead of at the first token.
    yield ": open\n\n"
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
        ):
            if kind == "phase":
                # What the turn is doing before it has words: the panel's
                # `chat.work_*` line, named by its key.
                yield _frame("phase", {"phase": payload})
            elif kind == "text":
                yield _frame("text", {"chunk": payload})
            elif kind == "meta":
                assert isinstance(payload, dict)
                yield _frame("meta", payload)
            else:
                reply = payload
                assert isinstance(reply, engine.Reply)
                yield _frame(
                    "done",
                    {
                        "text": reply.text,
                        "skills": list(reply.skills),
                        "sources": list(reply.sources),
                        "provider": reply.provider_id or None,
                        "error": reply.error,
                        "steps": list(reply.steps),
                    },
                )
    except Exception:  # pragma: no cover - the engine already swallows its own
        yield _frame(
            "done",
            {"text": "", "skills": [], "sources": [], "provider": None,
             "error": "chat.api_error"},
        )


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


@router.post("/messages", summary="Ask the assistant (streams the answer)")
def ask(body: Ask, paths: ChatTurn) -> StreamingResponse:
    """One chat turn, streamed as it is written.

    Frames are `phase` (what the turn is doing before it has words —
    `gathering`, `searching`, `writing`), `meta` (which provider answered,
    with which lens — held until the first real chunk, so a client never names
    a provider that then failed over), `text` (a piece of the answer) and
    exactly one `done` (the finished Reply, or its error key). A client that
    only wants the answer can ignore everything but `done`.

    The turn is a write — it appends to chat.json and spends the account's free
    allowance — so it is guarded by `Writer`: a bearer token may read this
    account but may never spend on it.
    """
    from stocks.web import auth

    if body.conversation is not None:
        if not any(
            c["id"] == body.conversation
            for c in auth.list_conversations(paths.chat)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no conversation {body.conversation}",
            )
        # The engine writes the *active* thread, which is what the panel and
        # the bot have always meant by "the conversation". Two windows of the
        # same account therefore share one cursor; last one to send wins, and
        # the thread each answer landed in is what the client re-reads.
        auth.set_active_conversation(body.conversation, paths.chat)

    message = body.message.strip()
    if body.regenerate:
        message = _rewind(paths)

    prefs = _prefs(paths)
    lang = (body.lang or prefs.get("language") or "en").strip().lower()
    return StreamingResponse(
        _events(
            prefs=prefs,
            paths=paths,
            message=message,
            lang=lang,
            staged_import=body.staged_import.strip(),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx and Cloud Run's front end both buffer a response body by
            # default, which would hold every chunk until the turn ended and
            # make the stream pointless.
            "X-Accel-Buffering": "no",
        },
    )


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

    Unlike the Streamlit panel there is no "this session only" option: an HTTP
    caller has no session for a key to live in, so the only honest choices are
    store it or do not send it.
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
    return state(paths)


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
    return state(paths)
