"""The reader's conversations: list, open, start, rename, drop, rate a turn."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from stocks.api import runs
from stocks.api.deps import Account, Writer
from stocks.api.routes.chat.messages import Message, _turn
from stocks.api.routes.chat.preferences import _prefs
from stocks.api.routes.chat.turns import _resumed
from stocks.config import PROJECT_ROOT

router = APIRouter(prefix="/chat", tags=["chat"])


class Conversation(BaseModel):
    """A thread's metadata — no bodies; the list view never needs them."""

    id: str
    title: str
    title_auto: bool
    created: str
    updated: str
    messages: int
    active: bool
    # The day of a daily card's thread (`auth.save_card_thread`), "" otherwise.
    daily: str = ""
    # The job a scheduled run's thread came from (`notify/schedule.py`):
    # "briefing", "digest" or "weekly"; "" for any other thread.
    scheduled: str = ""
    # An answer is still being written on it (`runs.live_threads`). The panel
    # polls the list while one it is not showing is, to say when it lands.
    answering: bool = False


class Conversations(BaseModel):
    conversations: list[Conversation]


class Running(BaseModel):
    """A turn on this thread that is not in `messages`: still being answered
    — the reader left and came back — or refused while nobody was watching.
    `GET /chat/runs/{run_id}` replays it from the start."""

    run_id: str
    question: str
    live: bool


class Thread(BaseModel):
    id: str
    title: str
    messages: list[Message]
    running: Running | None = None


class NewThread(BaseModel):
    """`from_share` starts the thread from a shared answer (`/?share=<id>`):
    its question and answer, as the reader's own, to carry on from."""

    model_config = {"extra": "forbid"}

    title: str = Field(default="", max_length=80)
    from_share: str = Field(default="", max_length=24)


class EditThread(BaseModel):
    """Rename a thread, make it the active one, or both."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=80)
    active: bool | None = None


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

    A daily card's thread the reader never wrote in is left out, unless it is
    the active one: the list is their conversations, and a month of cards would
    bury them. The thread is still there — the card's "Ask" opens it by id,
    and once they write in it, it is listed like any other.

    `answering` marks a thread with an answer still being written — the reader
    moved to another one meanwhile, and the panel says when it lands.
    """
    from stocks.web import auth

    if not paths.chat.exists():
        return Conversations(conversations=[])
    live = runs.live_threads(str(paths.chat))
    return Conversations(
        conversations=[
            Conversation(**c, answering=c["id"] in live)
            for c in auth.list_conversations(paths.chat, cards=False)
        ]
    )


@router.get(
    "/conversations/{cid}",
    response_model=Thread,
    summary="One thread, with its turns",
)
def thread(cid: str, paths: Account, request: Request) -> Thread:
    """The thread, and the run still answering on it. One a restart cut short
    is started again here (`_resumed`), so it is still answering."""
    from stocks.web import auth

    lang = str(_prefs(paths).get("language") or "en")
    book = auth.load_book(paths.chat)
    for conv in book["conversations"]:
        if conv["id"] == cid:
            run = runs.on_thread(str(paths.chat), cid) or _resumed(
                paths, request, thread=cid)
            return Thread(
                id=conv["id"],
                title=conv["title"],
                messages=[_turn(m, lang) for m in conv["messages"]],
                running=(
                    Running(run_id=run.id, question=run.question, live=run.live)
                    if run is not None
                    else None
                ),
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
    One started `from_share` is always new; 404 when that link is gone.
    """
    from stocks.web import auth, shares

    if body.from_share:
        found = shares.load(body.from_share)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no share {body.from_share}",
            )
        cid = shares.continue_from(paths, found)
    else:
        cid = auth.new_conversation(paths.chat, body.title,
                                    busy=runs.live_threads(str(paths.chat)))
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


class Rating(BaseModel):
    """A thumbs on one answer. `vote` None takes it back; `reason` says what
    was wrong, kept only on a thumbs-down, and `note` is the reader's words
    either way."""

    model_config = {"extra": "forbid"}

    vote: Literal["up", "down"] | None
    reason: Literal["made_up", "wrong", "missed", "other"] | None = None
    note: str = Field(default="", max_length=1000)
    lang: str | None = None


class Rated(BaseModel):
    vote: Literal["up", "down"] | None


@router.put(
    "/turns/{tid}/rating", response_model=Rated, summary="Rate an answer"
)
def rate(tid: str, body: Rating, paths: Writer) -> Rated:
    """Thumbs up or down on one answer, named by its id. Each answer keeps
    its own; a second vote on the same one replaces the first.

    Two writes: the vote on the turn itself, so a reload draws the thumb the
    reader pressed, and a copy for the operator with the question, the answer
    and what it was built from (`web/feedback.rate`) — the part that says why
    an answer missed. Clearing a vote writes only the first.

    404 for an id no thread holds: an answer written before turns had ids, or
    a thread since deleted.
    """
    from stocks.web import auth, feedback

    found = auth.rate_turn(tid, body.vote, paths.chat)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no answer {tid}"
        )
    if body.vote is not None:
        feedback.rate(
            body.vote, found["answer"], found["question"],
            reason=body.reason or "", note=body.note,
            sender="owner" if paths.root == PROJECT_ROOT else paths.root.name,
            lang=body.lang or str(_prefs(paths).get("language") or ""),
            thread=found["thread"], history=found["history"],
        )
    return Rated(vote=body.vote)
