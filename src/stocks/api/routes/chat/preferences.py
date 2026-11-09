"""Who answers: the reader's assistant settings, providers, models and keys."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from stocks import accounts, llm, loaders, obs
from stocks.accounts import UserPaths
from stocks.api.deps import Account, Writer
from stocks.api.routes import chat_attach
from stocks.chat import engine
from stocks.chat import skills as chat_skills
from stocks.portfolio import autodetect
from stocks.web import stt

router = APIRouter(prefix="/chat", tags=["chat"])


_SKILL_MODES = ("auto", "manual", "off")

# The two headers a session-only key travels in (see `session_keys`). Headers
# rather than body fields because the key has to reach the read that says who
# answers (`GET /chat/state`) as well as the turn, and a GET has no body.
KEY_HEADER = "X-Chat-Key"
PROVIDER_HEADER = "X-Chat-Provider"


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
    logo: str | None = Field(
        default=None,
        description=(
            "The provider's mark, same-origin where this host could mirror it. "
            "Null for the keyless chain, which draws the app's own."
        ),
    )
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
    # What an "in depth" question takes from that allowance (`DEEP_UNITS`).
    deep_units: int
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
    # The memory switches (`Settings.memory`, `Settings.recall`). Both on for
    # an account that never touched them.
    memory: bool = True
    recall: bool = True
    # Whether this deployment serves the Claude connector (`connector/`),
    # which needs the site's public origin. Picking Claude in settings points
    # at it: a reader who already pays for Claude can ask from there, keyless.
    connector: bool = False


class Settings(BaseModel):
    """The drawer's own preferences. Only the fields sent are changed."""

    model_config = {"extra": "forbid"}

    skills_mode: str | None = None
    skills: list[str] | None = None
    provider: str | None = None
    # Applied to the provider named in the same patch, or to the preferred one.
    # A model belongs to a backend, so the pair travels together or not at all.
    model: str | None = None
    # Keep saved memories and read them into answers (`chat/learnings.py`).
    # Off leaves the list on disk, untouched — forgetting is its own button.
    memory: bool | None = None
    # Let an answer search the account's earlier conversations.
    recall: bool | None = None

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


# -------------------------------------------------------------------- reads


def _prefs(paths: UserPaths) -> dict:
    return accounts.load_prefs(paths.prefs)


def session_keys(provider: str | None, key: str | None) -> dict[str, str]:
    """The key this one request brought with it, as `engine.attempts` takes it.

    The React drawer's "this session only" key: held in the tab's
    sessionStorage and sent on each request that needs it, used for that
    request, and never written anywhere — not to prefs, not to a log line
    (nothing in this API logs headers), not to the response. It is the one way
    to use a key of your own on a deployment with no encryption secret.

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


def _tail(key: str) -> str | None:
    """The last four characters of a key long enough to spare them."""
    return key[-4:] if len(key) > 12 else None


def _chosen(prefs: dict, provider: llm.Provider) -> str:
    """This account's model on `provider`: its saved choice, or the default."""
    saved = prefs.get(f"{provider.id}_model") or ""
    return saved if provider.accepts_model(saved) else provider.default_model


def _listed(prefs: dict, provider: llm.Provider) -> list[str]:
    """The curated models, plus the account's own pick when it is not one of
    them — a select that cannot show its value shows the first option instead."""
    chosen = _chosen(prefs, provider)
    curated = list(provider.models)
    return curated if chosen in curated else [*curated, chosen]


def _key_for(paths: UserPaths, pid: str, held: dict[str, str]) -> str:
    """The key this request would answer `pid` with: the session's, else the
    stored one. Never sent back — it only asks the vendor for its model list."""
    return held.get(pid) or engine.decrypt_byok(accounts.stored_prefs(paths.prefs), pid)


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
                models=_listed(prefs, provider),
                needs_key=provider.needs_key,
                has_key=provider.id in held
                or engine.byok_alive(prefs, provider.id),
                key_tail=(
                    _tail(in_use[provider.id])
                    if provider.needs_key and in_use.get(provider.id)
                    else None
                ),
                key_session=provider.id in held,
                model=_chosen(prefs, provider),
                console_url=provider.console_url,
                key_placeholder=provider.key_placeholder,
                key_days_left=engine.byok_days_left(prefs, provider.id),
                domain=provider.domain,
                logo=loaders.provider_logo(provider.id, provider.domain),
                connect_url=provider.connect_url or None,
                connect_token_url=provider.connect_token_url or None,
            )
            for provider in llm.available_providers()
        ],
        answering=chain[0][0].id if chain else None,
        preferred=prefs.get("llm_provider") or llm.default_provider_id(),
        free_left=left,
        free_cap=engine.free_daily_cap(prefs) if eligible else None,
        deep_units=engine.DEEP_UNITS,
        # Only when there is actually a wall: a reader with allowance left does
        # not need to be told which one they have not hit.
        cap_reason=(
            engine.FREE_CAP_ERRORS[engine.free_cap_reason(prefs)]
            if not left
            else None
        ),
        skills=[
            SkillInfo(id=s.id, name=s.name, description=s.description)
            for s in chat_skills.pickable()
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
        memory=engine.memory_on(prefs),
        recall=engine.recall_on(prefs),
        connector=_connector_open(),
    )


def _connector_open() -> bool:
    from stocks.web.server import connector_open

    return connector_open()


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
        if (
            provider is None
            or not provider.accepts_model(body.model)
            or not _served(paths, provider, body.model,
                           session_keys(x_chat_provider, x_chat_key))
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{pid} does not serve a model called {body.model!r}",
            )
        changes[f"{pid}_model"] = body.model
    if body.memory is not None:
        changes["chat_memory"] = body.memory
    if body.recall is not None:
        changes["chat_recall"] = body.recall
    if changes:
        accounts.update_prefs(paths.prefs, changes)
    return _state(paths, session_keys(x_chat_provider, x_chat_key))


def _served(paths: UserPaths, provider: llm.Provider, model: str,
            held: dict[str, str]) -> bool:
    """False only when the vendor was asked and its list leaves `model` out.

    A curated model is taken as served. Anything else is checked against the
    key's own listing when there is a key (or a public catalogue) to ask
    with; a listing that fails, or no key yet, takes the reader's word — the
    turn is where a wrong slug finally shows, by falling to the next provider.
    """
    if model in provider.models:
        return True
    key = _key_for(paths, provider.id, held)
    if not key and not provider.public_models:
        return True
    try:
        return model in provider.list_models(key)
    except Exception as exc:
        obs.warn("chat.models.list_failed", provider=provider.id,
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return True


class Models(BaseModel):
    """What a provider serves, for the model picker's "other model" field."""

    provider: str
    models: list[str]
    live: bool = Field(
        description=(
            "True when the list came from the provider itself, for this key. "
            "False is the curated list: no key yet, or the provider would not say."
        )
    )


@router.get(
    "/models/{provider}", response_model=Models, summary="Every model a provider serves"
)
def models(
    provider: str,
    paths: Account,
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> Models:
    """The provider's own catalogue, asked with the key this account would use.

    The curated `models` in the state are where the picker starts; this is
    the rest of what the reader's key can reach, so a model the vendor shipped
    last week is a pick rather than a release away. Listed through the
    session's key when it brought one, else the stored one; never the
    operator's.
    """
    known = llm.PROVIDERS.get(provider)
    if known is None or not known.available():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no provider {provider}"
        )
    if not known.needs_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{provider} picks its own model",
        )
    key = _key_for(paths, provider, session_keys(x_chat_provider, x_chat_key))
    if key or known.public_models:
        try:
            return Models(provider=provider, models=known.list_models(key), live=True)
        except Exception as exc:
            llm.note_failure(known, key, exc)
            obs.warn("chat.models.list_failed", provider=provider,
                     error_type=type(exc).__name__, error=str(exc)[:200])
    return Models(provider=provider, models=list(known.models), live=False)


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

    The one route in this API that hands a secret *out*. Three things fence it:

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
