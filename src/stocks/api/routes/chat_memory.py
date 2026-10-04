"""The assistant's saved memories, for the reader to see and correct.

What the chat keeps about an account (`chat/learnings.py`) rides in every
system prompt, so it is the one piece of the assistant's state a reader most
needs to be able to read — and the one they must be able to change without
asking the assistant nicely. This router is that screen's backend: the list,
an edit, a delete, a "forget everything", and an add for a reader who would
rather type a memory than say it.

A chat turn files the same changes itself ("recuerda que…", `engine.remember`)
and says so on the turn (`learned`); an undo on that line is a call here.

Reads are `Account` (a guest reads the empty list of the shared demo book),
writes `Writer`: a session, never a token — a bearer that could edit this list
could edit what every account's assistant believes about its user.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from stocks import accounts
from stocks.accounts import UserPaths
from stocks.api.deps import Account, Writer
from stocks.chat import engine, learnings, market

router = APIRouter(prefix="/chat/memories", tags=["chat"])


class Memory(BaseModel):
    """One saved memory.

    `source` says where it came from: "chat" when it was said in a
    conversation that still exists (`thread`, `thread_title`), "deleted" when
    that conversation has since been deleted — the memory outlives it — and
    "manual" when it was typed into the memory screen."""

    id: str
    text: str
    kind: str
    tickers: list[str]
    source: Literal["chat", "deleted", "manual"]
    thread: str | None
    thread_title: str | None
    created: str
    updated: str


class Memories(BaseModel):
    memories: list[Memory]
    # The account's switches (`PATCH /chat/settings`), so the screen can say
    # "memory is off" above a list that is no longer read.
    enabled: bool
    recall: bool
    max: int = learnings.MAX_ITEMS
    max_chars: int = learnings.MAX_CHARS
    kinds: list[str] = list(learnings.KINDS)


class _Kinded(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Guessed from the wording when absent (`learnings.guess_kind`).
    kind: str | None = None

    @field_validator("kind")
    @classmethod
    def _known(cls, value: str | None) -> str | None:
        if value is not None and value not in learnings.KINDS:
            raise ValueError(f"kind must be one of {', '.join(learnings.KINDS)}")
        return value


# The routine ceiling: a routine may be that long, and anything else is cut to
# MAX_CHARS by `learnings` itself rather than refused.
class NewMemory(_Kinded):
    text: str = Field(min_length=1, max_length=learnings.MAX_ROUTINE_CHARS)


class EditMemory(_Kinded):
    """Only the fields sent are changed."""

    text: str | None = Field(default=None, min_length=1,
                             max_length=learnings.MAX_ROUTINE_CHARS)


def _titles(paths: UserPaths) -> dict[str, str]:
    from stocks.web import auth

    if not paths.chat.exists():
        return {}
    return {c["id"]: c["title"] for c in auth.list_conversations(paths.chat)}


def _out(item: learnings.Learning, titles: dict[str, str]) -> Memory:
    if not item.thread:
        source = "manual"
    else:
        source = "chat" if item.thread in titles else "deleted"
    return Memory(
        id=item.id, text=item.text, kind=item.kind, tickers=list(item.tickers),
        source=source, thread=item.thread or None,
        thread_title=titles.get(item.thread) if item.thread else None,
        created=item.created, updated=item.updated,
    )


def _missing(lid: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                         detail=f"no memory {lid}")


def _unfit(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                         detail=str(exc))


@router.get("", response_model=Memories, summary="What the assistant remembers")
def memories(paths: Account) -> Memories:
    """Every saved memory, oldest first — the order they ride in the prompt."""
    prefs = accounts.load_prefs(paths.prefs)
    titles = _titles(paths)
    return Memories(
        memories=[_out(i, titles) for i in learnings.load(paths.learnings)],
        enabled=engine.memory_on(prefs),
        recall=engine.recall_on(prefs),
    )


@router.post("", response_model=Memory, status_code=status.HTTP_201_CREATED,
             summary="Add a memory")
def add(body: NewMemory, paths: Writer) -> Memory:
    """Save one statement, typed rather than said. The same statement twice is
    one memory, refreshed; a full list is a 409 the reader resolves by
    deleting one — nothing is evicted behind their back."""
    tickers = market.mentioned(body.text, market.watchlist_names(paths.watchlist),
                               lookup=lambda _name: "")
    try:
        item, _new = learnings.add(paths.learnings, body.text, kind=body.kind,
                                   tickers=tickers)
    except learnings.Full as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"memory is full ({learnings.MAX_ITEMS}); delete one first",
        ) from exc
    except ValueError as exc:
        raise _unfit(exc) from exc
    return _out(item, _titles(paths))


@router.patch("/{lid}", response_model=Memory, summary="Reword a memory")
def edit(lid: str, body: EditMemory, paths: Writer) -> Memory:
    try:
        item = learnings.edit(paths.learnings, lid, text=body.text,
                              kind=body.kind)
    except ValueError as exc:
        raise _unfit(exc) from exc
    if item is None:
        raise _missing(lid)
    return _out(item, _titles(paths))


@router.delete("/{lid}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Forget one memory")
def drop(lid: str, paths: Writer) -> None:
    """404 on an unknown id rather than a silent 204, like a thread's delete:
    an undo that removed nothing must not look like one that worked."""
    if learnings.drop(paths.learnings, lid) is None:
        raise _missing(lid)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT,
               summary="Forget every memory")
def clear(paths: Writer) -> None:
    """The whole list, gone. Conversations are not touched: they are the
    threads list, deleted one by one, and whether answers may search them is
    the `recall` switch."""
    learnings.clear(paths.learnings)
