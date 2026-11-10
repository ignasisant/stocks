"""One account's assistant conversations: the chat book in chat.json.

Several threads per account, one of them active, the daily cards and the
scheduled runs filed as threads of their own. Every write is a locked
read-modify-write of the whole book, mirrored to the bucket.
"""

from __future__ import annotations

import functools
import inspect
import json
import uuid
from collections.abc import Container
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stocks import obs, userstore
from stocks.chat import memory

# The bucket mirror every write here goes through: a failure is logged, never
# raised into a request whose local write already landed. A name of its own
# so the tests that count mirrored files patch one place.
_persist = userstore.persist


# ------------------------------------------------------------- chat threads
# The assistant keeps several conversations per account — each with an id, a
# title and timestamps, one of them active — persisted like prefs so they
# survive a reload, a new session or an ephemeral redeploy, and mirrored to
# the bucket.
#
# All of them live in a single chat.json ({"version", "active",
# "conversations"}) rather than one file per thread: the whole per-account
# sync path (accounts.USER_FILES, storage.restore_once, _persist) is built on a fixed
# tuple of paths, so a directory of threads would need its own bucket keying
# and orphan cleanup for nothing the user can see.
#
# load_chat/save_chat keep their original list-of-turns signature and act on
# the active conversation, so the headless engine never
# had to learn about threads.

CHAT_VERSION = 2
MAX_CONVERSATIONS = 50  # oldest by last use pruned first; never the active one
# A thread nobody has written in for this long is dropped — on read, so every
# reader agrees (`load_book`), and from the file on the next write. Never the
# active one: it is the thread the next turn lands in, however old. "Written
# in" is `updated`: opening, rating or renaming a thread is not a use.
KEEP_DAYS = 30
# Home's daily cards are filed as threads of their own (save_card_thread), one
# a day. The ones nobody wrote in are kept on a budget of their own: a month of
# cards must not push the reader's conversations out of MAX_CONVERSATIONS. Nor
# out of sight: the panel's list leaves them out (`list_conversations`, cards=
# False) until the reader opens one or writes in it — the list is what they
# said, not what they were told. A card the briefing pushed (mark_scheduled),
# and the evening and weekly runs filed before they were retired on
# 2026-11-10, are the exception to "out of sight": they are listed in a section
# of their own, which is how a pushed one is found again.
MAX_CARD_THREADS = 60
_TITLE_MAX = 80

# Every write is a read-modify-write of the whole book, and since the daily
# card files its thread from a background job, two can now overlap inside one
# process: a card filed while a chat turn is being saved. Each writer holds
# its book's lock (`userstore.lock`, re-entrant so a writer may call another);
# two accounts' books no longer queue behind each other.
def _locked(fn):
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        path = signature.bind(*args, **kwargs).arguments["path"]
        with userstore.lock(path):
            return fn(*args, **kwargs)

    return wrapper


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _blank_conversation(title: str = "") -> dict:
    now = _now()
    return {
        "id": f"c_{uuid.uuid4().hex[:8]}",
        "title": title,
        # False once the user renames it, so auto-titling stops overwriting.
        "title_auto": True,
        "created": now,
        "updated": now,
        "messages": [],
    }


def _empty_book() -> dict:
    conv = _blank_conversation()
    return {"version": CHAT_VERSION, "active": conv["id"], "conversations": [conv]}


def load_book(path: Path) -> dict:
    """Every conversation for the account, in the current shape.

    Never writes — a turn that fails must leave chat.json untouched (and
    absent when it never existed). A v1 file (the bare list of turns the
    single-thread assistant wrote) migrates to one conversation; anything
    missing or corrupt yields a fresh empty book.

    Threads idle beyond KEEP_DAYS are left out here rather than on write, so
    the list a returning reader opens the drawer on and the book their first
    turn is saved into agree. The file loses them on that write (`save_book`),
    and the memory index with it.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        data = None

    if isinstance(data, list):  # v1: one unnamed thread
        conv = _blank_conversation()
        conv["messages"] = [m for m in data if isinstance(m, dict)]
        return {"version": CHAT_VERSION, "active": conv["id"],
                "conversations": [conv]}
    if not isinstance(data, dict):
        return _empty_book()

    convs = [
        c for c in (data.get("conversations") or [])
        if isinstance(c, dict) and c.get("id")
    ]
    for c in convs:  # tolerate records written by an older/partial writer
        c.setdefault("title", "")
        c.setdefault("title_auto", True)
        c.setdefault("created", _now())
        c.setdefault("updated", c["created"])
        c["messages"] = [m for m in (c.get("messages") or []) if isinstance(m, dict)]
        # A daily card or scheduled run filed before those turns had ids: one
        # derived from its place, the same on every read, so it can be rated.
        for i, m in enumerate(c["messages"]):
            if (m.get("role") == "assistant" and not m.get("id")
                    and (m.get("daily") or m.get("scheduled"))):
                m["id"] = f"{c['id']}-{i}"
    if not convs:
        return _empty_book()

    active = data.get("active")
    if active not in {c["id"] for c in convs}:
        active = convs[0]["id"]
    cutoff = datetime.now(UTC) - timedelta(days=KEEP_DAYS)
    convs = [c for c in convs if c["id"] == active or not _idle_since(c, cutoff)]
    return {"version": CHAT_VERSION, "active": active, "conversations": convs}


def _idle_since(conv: dict, cutoff: datetime) -> bool:
    """Whether nothing was written in `conv` since `cutoff`. A stamp that does
    not parse keeps its thread: an unreadable date is no reason to lose one."""
    try:
        when = datetime.fromisoformat(str(conv.get("updated") or ""))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when < cutoff


def _unread_card(conv: dict) -> bool:
    """A daily card's or a scheduled run's thread the reader never wrote in.
    Once they have, it is a conversation like any other, and is kept like one."""
    return bool(conv.get("daily") or conv.get("scheduled")) and not any(
        m.get("role") == "user" for m in conv["messages"]
    )


def _pruned(book: dict) -> dict:
    """The book capped at MAX_CONVERSATIONS, dropping least-recently-used
    threads first and never the active one — and the cards nobody answered
    capped apart, at MAX_CARD_THREADS."""
    convs = book["conversations"]

    def card(c: dict) -> bool:
        return _unread_card(c) and c["id"] != book["active"]

    cards = [c for c in convs if card(c)]
    talk = [c for c in convs if not card(c)]
    if len(cards) <= MAX_CARD_THREADS and len(talk) <= MAX_CONVERSATIONS:
        return book

    def newest(group: list[dict], n: int) -> list[dict]:
        return sorted(group, key=lambda c: c.get("updated") or "", reverse=True)[:n]

    active = [c for c in talk if c["id"] == book["active"]][:1]
    others = [c for c in talk if c["id"] != book["active"]]
    keep = {
        c["id"]
        for c in active
        + newest(others, MAX_CONVERSATIONS - len(active))
        + newest(cards, MAX_CARD_THREADS)
    }
    return {**book, "conversations": [c for c in convs if c["id"] in keep]}


def save_book(book: dict, path: Path) -> None:
    kept = _pruned(book)
    userstore.write(path, kept, mirror=_persist)
    # A thread that is gone must not keep answering questions through the
    # memory index — whether the reader deleted it, KEEP_DAYS ran out on it or
    # a cap let it go. Swept here, where every one of those lands.
    index = memory_path(path)
    if memory.forget_except(index, {c["id"] for c in kept["conversations"]}):
        _persist(index)


def _active(book: dict) -> dict:
    """The active conversation — load_book guarantees one exists."""
    for c in book["conversations"]:
        if c["id"] == book["active"]:
            return c
    return book["conversations"][0]


def _pinned(book: dict, cid: str | None) -> dict:
    """Conversation `cid`, or the active one when none is named or it is gone.

    A turn names the thread it was asked in because the active pointer can
    move while it is being answered: a chat run outlives its request
    (`api/runs.py`), and the reader may open another thread before it lands.
    `cid` missing from the book is a first thread that had no durable id yet
    (`load_book` synthesizes one per read) or one deleted mid-turn."""
    if cid:
        for c in book["conversations"]:
            if c["id"] == cid:
                return c
    return _active(book)


def load_chat(path: Path, cid: str | None = None) -> list[dict]:
    """The turns of conversation `cid`, or of the active one (the historical
    single-thread API)."""
    return _pinned(load_book(path), cid)["messages"]


def memory_path(path: Path) -> Path:
    """The account's long-term chat index, beside its chat history."""
    return path.parent / memory.FILE


@_locked
def save_chat(history: list[dict], path: Path, cid: str | None = None) -> None:
    """Replace a conversation's turns and stamp it as just used: `cid`'s when
    it is named, the active one's otherwise.

    A named thread that is not in the book falls back to the active one only
    while that one's turns are where `history` started from — a first thread
    that only now gets its id, never a thread the reader moved to while this
    turn was being answered. That one would lose its turns to this history,
    so the save is dropped instead (the thread it was for is gone anyway).

    Indexing rides along here rather than at the two call sites: every turn
    that reaches disk is a turn the assistant may need to recall later, and
    every surface already comes through this
    one function. It is idempotent and best-effort — a failed index costs a
    worse search, never a lost message."""
    book = load_book(path)
    conv = _pinned(book, cid)
    if cid and conv["id"] != cid and conv["messages"] != history[: len(conv["messages"])]:
        obs.warn("chat.thread_gone", thread=cid)
        return
    conv["messages"] = list(history)
    conv["updated"] = _now()
    save_book(book, path)
    index = memory_path(path)
    if memory.remember(index, history, conv["id"]):
        _persist(index)  # only when it actually grew — most saves add nothing


def list_conversations(path: Path, cards: bool = True) -> list[dict]:
    """Conversation metadata (no message bodies), most recently used first.
    `daily` is the card day of a daily card's thread, "" for any other;
    `scheduled` the job a scheduled run's thread came from (`notify/schedule.py`).

    `cards=False` is the panel's list: it leaves out the card threads nobody
    wrote in (`_unread_card`) unless one is the active thread — the card's
    "Ask" just opened it. A month of cards would otherwise bury the reader's
    own conversations, and nothing in them was theirs to find. A scheduled
    run's thread is listed all the same: it was pushed to the reader, and the
    panel files it under its own section. Every lookup
    by id keeps the default: the threads exist, they are only not listed."""
    book = load_book(path)
    metas = [
        {
            "id": c["id"], "title": c["title"], "title_auto": c["title_auto"],
            "created": c["created"], "updated": c["updated"],
            "messages": len(c["messages"]), "active": c["id"] == book["active"],
            "daily": str(c.get("daily") or ""),
            "scheduled": str(c.get("scheduled") or ""),
        }
        for c in book["conversations"]
        if cards or c["id"] == book["active"] or c.get("scheduled")
        or not _unread_card(c)
    ]
    return sorted(metas, key=lambda m: m["updated"], reverse=True)


def active_conversation(path: Path, cid: str | None = None) -> dict:
    """Metadata of the conversation the next turn will land in — or of `cid`,
    the one a turn already in flight was asked in (`_pinned`)."""
    c = _pinned(load_book(path), cid)
    return {k: v for k, v in c.items() if k != "messages"}


@_locked
def new_conversation(path: Path, title: str = "", busy: Container[str] = ()) -> str:
    """Start (and activate) an empty conversation; returns its id.

    An active conversation that is still empty is reused, so pressing New
    repeatedly can't stack blank threads — unless it is in `busy`: a first
    question still being answered has not been written yet, and reusing its
    thread would hand the reader the one they meant to leave."""
    book = load_book(path)
    conv = _active(book)
    if conv["messages"] or conv["id"] in busy:
        conv = _blank_conversation(title)
        book["conversations"].append(conv)
    elif title:
        conv["title"] = title[:_TITLE_MAX]
    book["active"] = conv["id"]
    save_book(book, path)
    return conv["id"]


@_locked
def set_active_conversation(cid: str, path: Path) -> None:
    book = load_book(path)
    if any(c["id"] == cid for c in book["conversations"]):
        book["active"] = cid
        save_book(book, path)


@_locked
def rename_conversation(cid: str, title: str, path: Path) -> None:
    """User-set title — pins it, so auto-titling never overwrites it again."""
    book = load_book(path)
    for c in book["conversations"]:
        if c["id"] == cid:
            c["title"] = title.strip()[:_TITLE_MAX]
            c["title_auto"] = False
            save_book(book, path)
            return


@_locked
def autotitle_conversation(cid: str, title: str, path: Path) -> None:
    """Title derived from the opening exchange; a no-op on a renamed thread."""
    book = load_book(path)
    for c in book["conversations"]:
        if c["id"] == cid and c.get("title_auto", True):
            c["title"] = title.strip()[:_TITLE_MAX]
            save_book(book, path)
            return


@_locked
def delete_conversation(cid: str, path: Path) -> None:
    """Drop a conversation. Deleting the active one falls back to the most
    recently used survivor — or a fresh empty thread when it was the last."""
    book = load_book(path)
    kept = [c for c in book["conversations"] if c["id"] != cid]
    if len(kept) == len(book["conversations"]):
        return
    if not kept:
        kept = [_blank_conversation()]
    if book["active"] == cid:
        book["active"] = max(kept, key=lambda c: c["updated"])["id"]
    book["conversations"] = kept
    save_book(book, path)  # forgets its memories too


@_locked
def rate_turn(tid: str, vote: str | None, path: Path) -> dict | None:
    """Set (or, with None, clear) the reader's thumbs on one answer.

    Found by the id `_record` gave it, in whichever thread holds it (the
    reader may have switched threads since). Every answer keeps its own: a
    follow-up is an answer too, and a good first one says nothing of it.

    Returns {"answer": entry, "question": text, "thread": id, "history":
    the turns above that question}, or None for an id no thread holds. `updated` is left
    alone: a thumbs is not a use, and it must not lift an old thread to the
    top of the list.
    """
    if not tid:
        return None
    book = load_book(path)
    for conv in book["conversations"]:
        msgs = conv["messages"]
        for i, m in enumerate(msgs):
            if m.get("role") != "assistant" or m.get("id") != tid:
                continue
            m.pop("rating", None)
            if vote is not None:
                m["rating"] = vote
            save_book(book, path)
            at = next((j for j in range(i - 1, -1, -1)
                       if msgs[j].get("role") == "user"), None)
            asked = str(msgs[at].get("content") or "") if at is not None else ""
            return {"answer": dict(m), "question": asked, "thread": conv["id"],
                    "history": [{"role": str(q.get("role") or ""),
                                 "content": str(q.get("content") or "")}
                                for q in msgs[:at or 0]]}
    return None


def find_answer(tid: str, path: Path) -> dict | None:
    """The answer `tid` names, the question above it and the thread before
    that, read only: {"answer": entry, "question": text, "thread": id,
    "earlier": [message, …]}, or None."""
    if not tid:
        return None
    for conv in load_book(path)["conversations"]:
        msgs = conv["messages"]
        for i, m in enumerate(msgs):
            if m.get("role") != "assistant" or m.get("id") != tid:
                continue
            at = next((j for j in range(i - 1, -1, -1)
                       if msgs[j].get("role") == "user"), None)
            asked = str(msgs[at].get("content") or "") if at is not None else ""
            return {"answer": dict(m), "question": asked, "thread": conv["id"],
                    "earlier": [dict(q) for q in msgs[:at if at is not None else i]]}
    return None


@_locked
def stamp_share(tid: str, links: list[dict], path: Path) -> None:
    """Note on the answer the links it was shared under (`web/shares.py`);
    an empty list takes them off. `updated` is left alone, as a rating leaves
    it: sharing an answer is not writing in its thread."""
    book = load_book(path)
    for conv in book["conversations"]:
        for m in conv["messages"]:
            if m.get("role") == "assistant" and m.get("id") == tid:
                m.pop("shares", None)
                if links:
                    m["shares"] = links
                save_book(book, path)
                return


@_locked
def seed_conversation(title: str, messages: list[dict], path: Path) -> str:
    """A new active thread that starts with `messages`; returns its id. How a
    shared answer becomes the reader's own to carry on (`web/shares.py`)."""
    book = load_book(path)
    conv = _blank_conversation(title[:_TITLE_MAX])
    conv["title_auto"] = False
    conv["messages"] = list(messages)
    book["conversations"].append(conv)
    book["active"] = conv["id"]
    save_book(book, path)
    index = memory_path(path)
    if memory.remember(index, conv["messages"], conv["id"]):
        _persist(index)
    return conv["id"]


def _filed() -> dict:
    """What a turn written in the background carries: the id a thumbs names
    it by, and when it was written — no session watched it arrive."""
    return {"id": uuid.uuid4().hex[:12], "at": _now()}


@_locked
def save_card_thread(day: str, title: str, text: str, path: Path) -> str:
    """File a daily card in the chat as a thread of its own; returns its id.

    One thread per card day, titled once ("Daily action · 3 Oct") and never
    made active: the card is written in the background, and a reader halfway
    through a conversation must not find it carrying on somewhere else.
    Opening it is the card's "Ask" button, and the reader then asks with the
    card in the thread above the question. Until then it is not in the
    panel's list either (`list_conversations`, cards=False).

    A card rewritten the same day (the computed stand-in, then the model's)
    replaces its turn while nobody has answered it, and lands after the
    reader's turns when somebody has — the thread is what the reader was
    told, in order. Indexed like any turn, which is how the chat can recall
    what a card said."""
    book = load_book(path)
    conv = next((c for c in book["conversations"] if c.get("daily") == day), None)
    if conv is None:
        conv = _blank_conversation(title[:_TITLE_MAX])
        conv["title_auto"] = False
        conv["daily"] = day
        book["conversations"].append(conv)
    turn = {"role": "assistant", "content": text, "daily": day, **_filed()}
    msgs = conv["messages"]
    if msgs and msgs[-1].get("daily") == day:
        if msgs[-1].get("content") == text:
            return conv["id"]  # the same card again: nothing to file
        msgs[-1] = turn
    else:
        msgs.append(turn)
    conv["updated"] = _now()
    save_book(book, path)
    index = memory_path(path)
    if memory.remember(index, msgs, conv["id"]):
        _persist(index)
    return conv["id"]


@_locked
def mark_scheduled(cid: str, job: str, run: str, path: Path) -> bool:
    """Mark an existing thread as a scheduled run's — the daily card's, which
    `save_card_thread` filed, when the briefing job delivered it. False when
    the thread is gone."""
    book = load_book(path)
    conv = next((c for c in book["conversations"] if c["id"] == cid), None)
    if conv is None:
        return False
    if conv.get("scheduled") == job and conv.get("run") == run:
        return True
    conv["scheduled"] = job
    conv["run"] = run
    save_book(book, path)
    return True
