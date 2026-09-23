"""The conversational walkthrough, for a front end that is not Streamlit.

`web/guide.py` walks a new account through the app inside the assistant
drawer: one step per turn, a card under each with "take me there" and "next",
and steps the account has already switched on walked past with a one-line
receipt. It is the default onboarding (`GUIDE_SURFACE` = "chat"); the modal
tour is the rollback. This router is the same walkthrough for any client.

**The state is the account's, and it is one state.** The same prefs keys
(`guide_step`, `guide_done`, `guide_thread`, `guide_opens`), the same
conversation, and the same stored turns with the same `guide` marker — so a
reader who starts the walkthrough in one front end finds it where they left it
in the other, and neither can append a card the other already appended.

**What does not come across is Streamlit's per-session plumbing**: "evaluated
once this session", "the panel is parked on a phone". Those are facts about a
browser tab, and the client that owns the tab keeps them. What this router
answers is `auto_open` — whether the account is still owed an automatic open —
and the client decides whether *this* load is the one that spends it.

**Deterministic only.** The model half of the Streamlit guide (the one
generated opening line, the prompt fence that keeps a mid-tour question on the
tour) rides on the Streamlit panel's own turn loop; it degrades to silence by
design, and the walkthrough is complete without it.

Every route here writes except `GET`: moving the marker, stamping an open and
appending a card are all stored state, so they are `Writer` like every other
write — a bearer token must not walk an account through its own tutorial.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import accounts, obs
from stocks.accounts import UserPaths
from stocks.api.deps import Account, Writer
from stocks.web import guide, onboarding
from stocks.web.i18n import translate

router = APIRouter(prefix="/guide", tags=["onboarding"])


# ------------------------------------------------------------------ schemas


class GuideStep(BaseModel):
    """The step the account is on, with where its card sends the reader."""

    id: str
    icon: str
    path: str | None = None
    params: dict[str, str] = {}
    session: dict[str, str] = {}
    gated: bool = False
    # Whether the account has this step's capability switched on — null for a
    # step that is a place rather than something to switch on.
    done: bool | None = None
    title_key: str
    body_key: str
    cta_key: str | None = None


class GuideState(BaseModel):
    surface: str = Field(description='"chat" (this walkthrough) or "modal".')
    active: bool
    finished: bool
    step: GuideStep | None = None
    # Every step, so an older card on the thread can still send the reader to
    # its page: navigating changes nothing about where the guide is, and a
    # thread you cannot re-follow is worse than the modal it replaced.
    steps: list[GuideStep] = []
    index: int = Field(description="1-based position of the step; 0 when none.")
    of: int
    thread: str | None = Field(description="The conversation the guide writes in.")
    auto_open: bool = Field(
        description=(
            "The account is still owed an automatic open: the walkthrough is "
            "not finished and fewer than three have been spent. Whether this "
            "page load is the one that spends it is the client's call."
        )
    )
    changed: bool = Field(
        default=False,
        description="This call appended to the guide's thread; re-read it.",
    )


class Start(BaseModel):
    model_config = {"extra": "forbid"}

    step: str | None = Field(
        default=None,
        description="Where to start. Omitted: the step the account is on, "
        "or the first.",
    )
    auto: bool = Field(
        default=False,
        description="An automatic open, which spends one of the three. A "
        "reader who asked for the guide never spends one.",
    )
    lang: str | None = None


class Finish(BaseModel):
    model_config = {"extra": "forbid"}

    # The step someone walks out on is the only feedback the walkthrough gives
    # about itself, so the ways out are told apart in the log.
    reason: str = Field(default="skipped", pattern=r"^[a-z_]{1,32}$")


class Lang(BaseModel):
    model_config = {"extra": "forbid"}

    lang: str | None = None


# ------------------------------------------------------------------ helpers


def _lang(prefs: dict, asked: str | None) -> str:
    return (asked or prefs.get("language") or "en").strip().lower()


def _step(step: onboarding.Step, prefs: dict, paths: UserPaths) -> GuideStep:
    return GuideStep(
        id=step.id,
        icon=step.icon,
        path=onboarding._url_path(step.page) if step.page else None,
        params=dict(step.query or {}),
        session={k: str(v) for k, v in (step.session or {}).items()},
        gated=step.gated,
        done=None if step.done is None else bool(step.done(prefs, paths)),
        title_key=f"tour.{step.id}_title",
        body_key=f"tour.{step.id}_body",
        cta_key=(
            f"tour.{step.id}_cta"
            if onboarding.i18n.has(f"tour.{step.id}_cta")
            else None
        ),
    )


def _state(paths: UserPaths, prefs: dict, *, changed: bool = False) -> GuideState:
    step = guide.current(prefs)
    return GuideState(
        surface=guide.surface(),
        active=step is not None,
        finished=bool(prefs.get(guide.PREF_DONE)),
        step=_step(step, prefs, paths) if step else None,
        steps=[_step(s, prefs, paths) for s in guide.steps()],
        index=guide._index(step) + 1 if step else 0,
        of=len(guide.steps()),
        thread=str(prefs.get(guide.PREF_THREAD) or "") or None,
        auto_open=(
            guide.surface() == "chat"
            and not prefs.get(guide.PREF_DONE)
            and int(prefs.get(guide.PREF_OPENS) or 0) < guide.MAX_AUTO_OPENS
        ),
        changed=changed,
    )


def _card(step: onboarding.Step, lang: str) -> dict:
    """The stored turn that presents one step — `guide.turn_for`, in `lang`."""
    return {
        "role": "assistant",
        "content": (
            f":material/{step.icon}: **{translate(f'tour.{step.id}_title', lang)}**"
            "\n\n" + translate(f"tour.{step.id}_body", lang)
        ),
        "guide": {"step": step.id},
    }


def _receipt(step: onboarding.Step, lang: str) -> dict:
    """The line for a step the account had already switched on."""
    return {
        "role": "assistant",
        "content": translate(
            "guide.step_done", lang, title=translate(f"tour.{step.id}_title", lang)
        ),
        "guide": {"step": step.id, "state": "done"},
    }


def _ensure_thread(paths: UserPaths, prefs: dict, lang: str) -> None:
    """Point the account at the guide's thread, creating it the first time.

    `new_conversation` reuses an empty active conversation, so a brand-new
    account gets its one blank thread titled rather than a second one.
    """
    from stocks.web import auth

    cid = str(prefs.get(guide.PREF_THREAD) or "")
    known = {c["id"] for c in auth.list_conversations(paths.chat)}
    if cid and cid in known:
        auth.set_active_conversation(cid, paths.chat)
        return
    prefs[guide.PREF_THREAD] = auth.new_conversation(
        paths.chat, translate("guide.thread_title", lang)
    )


def _finish(paths: UserPaths, prefs: dict, reason: str) -> None:
    """End the walkthrough for good — and, like the Streamlit guide, stamp the
    tour done and the release seen: someone who just walked through everything
    has no "what's new" to catch up on."""
    step = guide.current(prefs)
    obs.event(
        "guide.exit", reason=reason, step=step.id if step else "",
        index=guide._index(step) + 1, of=len(guide.steps()), via="api",
    )
    prefs[guide.PREF_DONE] = True
    prefs[guide.PREF_STEP] = ""
    prefs[onboarding.PREF_DONE] = True
    prefs[onboarding.PREF_SEEN_VERSION] = onboarding.CURRENT_VERSION
    accounts.save_prefs(paths.prefs, prefs)


def _sync(paths: UserPaths, prefs: dict, lang: str) -> bool:
    """`guide.sync`, against the guide's own thread.

    Walks past every step whose capability the account now has — an import
    done in another tab shows up as progress, not as a step to re-read — and
    makes sure the current step's card is on the thread. Only ever the guide's
    thread: the walkthrough must never append a card to a conversation the
    reader started.
    """
    from stocks.web import auth

    step = guide.current(prefs)
    cid = str(prefs.get(guide.PREF_THREAD) or "")
    if step is None or not cid:
        return False
    book = auth.load_book(paths.chat)
    conv = next((c for c in book["conversations"] if c["id"] == cid), None)
    if conv is None:
        return False
    history = conv["messages"]

    changed = False
    for _ in range(len(guide.steps())):
        if step is None or step.done is None or not step.done(prefs, paths):
            break
        obs.event("guide.step", step=step.id, index=guide._index(step) + 1,
                  of=len(guide.steps()), auto=True, via="api")
        history.append(_receipt(step, lang))
        step = guide._next(step)
        changed = True

    if step is None:
        _finish(paths, prefs, "completed")
        history.append({"role": "assistant",
                        "content": translate("guide.finished", lang),
                        "guide": {"step": "", "state": "end"}})
        auth.save_book(book, paths.chat)
        return True

    if changed:
        prefs[guide.PREF_STEP] = step.id
    if not guide._has_card(history, step.id):
        history.append(_card(step, lang))
        changed = True
    if changed:
        auth.save_book(book, paths.chat)
        accounts.save_prefs(paths.prefs, prefs)
    return changed


def _known(step_id: str) -> onboarding.Step:
    step = onboarding.by_id(step_id)
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no step {step_id}"
        )
    return step


# ------------------------------------------------------------------- routes


@router.get("", response_model=GuideState, summary="Where the walkthrough is")
def state(paths: Account) -> GuideState:
    return _state(paths, accounts.load_prefs(paths.prefs))


@router.post("/start", response_model=GuideState, summary="Open the walkthrough")
def start(body: Start, paths: Writer) -> GuideState:
    """Put the guide on a step, activate its thread, and draw the step's card.

    An automatic open resumes where the account left off and spends one of the
    three; one the reader asked for (the Profile launcher, `?guide=`) starts
    where it is told — the top, by default — and spends nothing. An automatic
    open for an account that has finished, or has none left, is refused with
    409 rather than quietly reopening something the reader closed.
    """
    prefs = accounts.load_prefs(paths.prefs)
    lang = _lang(prefs, body.lang)
    if body.auto:
        if prefs.get(guide.PREF_DONE) or int(
            prefs.get(guide.PREF_OPENS) or 0
        ) >= guide.MAX_AUTO_OPENS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this account is owed no automatic open",
            )
        step_id = str(prefs.get(guide.PREF_STEP) or "") or guide.steps()[0].id
    else:
        step_id = body.step or guide.steps()[0].id
    step_id = _known(step_id).id

    started = not prefs.get(guide.PREF_STEP)
    prefs[guide.PREF_STEP] = step_id
    prefs[guide.PREF_DONE] = False
    if body.auto:
        prefs[guide.PREF_OPENS] = int(prefs.get(guide.PREF_OPENS) or 0) + 1
    _ensure_thread(paths, prefs, lang)
    accounts.save_prefs(paths.prefs, prefs)
    if started:
        obs.event("guide.start", step=step_id, via="api")
    changed = _sync(paths, prefs, lang)
    return _state(paths, prefs, changed=changed)


@router.post("/sync", response_model=GuideState, summary="Catch the thread up")
def sync(body: Lang, paths: Writer) -> GuideState:
    """Walk past what the account has done since, and draw the current card.

    Called when the drawer opens on the guide's thread and after the reader
    comes back from a step's page: that is when a capability may have been
    switched on somewhere the guide was not looking.
    """
    prefs = accounts.load_prefs(paths.prefs)
    changed = _sync(paths, prefs, _lang(prefs, body.lang))
    return _state(paths, prefs, changed=changed)


@router.post("/advance", response_model=GuideState, summary="Next step")
def advance(body: Lang, paths: Writer) -> GuideState:
    """Move the marker to the next step and draw its card — or, from the last
    one, finish. The client takes the reader to the new step's page itself: on
    a phone the drawer is the viewport, and jumping there on every Next would
    spend the walkthrough reopening it."""
    prefs = accounts.load_prefs(paths.prefs)
    lang = _lang(prefs, body.lang)
    step = guide.current(prefs)
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="the guide is not running"
        )
    obs.event("guide.step", step=step.id, index=guide._index(step) + 1,
              of=len(guide.steps()), via="api")
    nxt = guide._next(step)
    if nxt is None:
        _finish(paths, prefs, "finished")
        return _state(paths, prefs, changed=False)
    prefs[guide.PREF_STEP] = nxt.id
    accounts.save_prefs(paths.prefs, prefs)
    changed = _sync(paths, prefs, lang)
    return _state(paths, prefs, changed=changed)


@router.post("/finish", response_model=GuideState, summary="End the walkthrough")
def finish(body: Finish, paths: Writer) -> GuideState:
    prefs = accounts.load_prefs(paths.prefs)
    if guide.current(prefs) is not None:
        _finish(paths, prefs, body.reason)
    return _state(paths, prefs)
