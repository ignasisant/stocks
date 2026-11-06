"""A chat answer shared by link — the store behind `/?share=<id>`.

A shared answer is a frozen copy, not a pointer into the sharer's chat.json:
threads there are pruned (idle, capped, deleted by their owner) and a link
sent to a group chat is opened weeks later. So `create` cuts the answer once
(`chat/share_mask.py`) and writes it to data/shares/<id>.json, mirrored to the
bucket like feedback; `load` reads it from either.

What is copied: the question, the answer's words, the bull and bear cases
argued above it, the pages it cited, the lenses it used and the surfaces it
drew (inert). The exchanges of the thread before it go too (`turns`), each cut
the same way: an answer read alone loses the "and what about…" it replied
to. What comes after it in the thread does not. What never is: a tool trace,
the memories read or written, a proposal, the model. A trace quotes the book
line by line, and none of the rest is the answer.

The id is random (`token_urlsafe`), so a link is found only by being sent.
The sharer's answer is stamped with the links it went out under
(`auth.stamp_share`), one per cut — the masked link and the unmasked one are
different pages, and a link already sent must keep working when the other is
made. `revoke` takes every one of them down, and so does deleting the
account (`purge_owner`).

The account also keeps its own list of the links it made (`paths.shares`,
`listed`), because the stamps go with their thread: a thread pruned after
KEEP_DAYS leaves its links up and nowhere to find them from.

A link can also carry a list of tickers (`kind` "watchlist", `create_list`):
the symbols and a title the sharer chose, nothing else of their watchlist —
no names they typed, no positions, no groups but the one they named. It has
no answer behind it, so it is its own link and comes down alone. The reader
follows it whole (`follow`), under its title as a group of their own.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from stocks import atomic, obs, storage
from stocks import watchlist as wl
from stocks.accounts import UserPaths
from stocks.chat import share_mask
from stocks.config import DATA_DIR, PROJECT_ROOT
from stocks.web import auth

SHARES_DIR = DATA_DIR / "shares"
# What `secrets.token_urlsafe(8)` spells, give or take: the route and the
# server's card both check it before a path is built from it.
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,24}$")
_QUESTION_CHARS = 1000
# The thread above a shared answer: its last exchanges, not a long session.
_TURNS_MAX = 20
# How much of the question names a link in the account's list.
_LISTED_CHARS = 140
# A shared list: past this many it is a dump, not a pick; a title is a group
# name, and the reader's watchlist shows it as one.
LIST_MAX = 50
_TITLE_CHARS = 60


def owner_of(paths: UserPaths) -> str:
    """The account's pseudonymous slug, as feedback and the logs name it."""
    return "owner" if paths.root == PROJECT_ROOT else paths.root.name


def _path(share_id: str) -> Path | None:
    return SHARES_DIR / f"{share_id}.json" if ID_RE.match(share_id or "") else None


def snapshot(found: dict, masked: bool) -> dict:
    """What a link to the answer `found` (`auth.find_answer`) shows: the
    exchange, the thread's earlier ones above it, and the cut."""
    return {**_exchange(found["question"], found["answer"], masked),
            "turns": _turns(found.get("earlier") or [], masked),
            "masked": masked}


def _turns(earlier: list[dict], masked: bool) -> list[dict]:
    """The exchanges of `earlier` (a thread's messages, oldest first), the
    last _TURNS_MAX. A question with nothing to read under it (failed,
    stopped, never answered) drops, so every turn is a question and its
    answer."""
    turns: list[dict] = []
    question = ""
    for m in earlier:
        if m.get("role") == "user":
            question = str(m.get("content") or "")
        elif m.get("role") == "assistant":
            if m.get("content") or m.get("activities"):
                turns.append(_exchange(question, m, masked))
            question = ""
    return turns[-_TURNS_MAX:]


def _exchange(question: str, answer: dict, masked: bool) -> dict:
    question = question[:_QUESTION_CHARS]
    content = str(answer.get("content") or "")
    debate = [{"side": str(d.get("side") or ""), "text": str(d.get("text") or ""),
               **({"failed": True} if d.get("failed") is True else {})}
              for d in answer.get("debate") or []
              if isinstance(d, dict) and (d.get("text") or d.get("failed") is True)]
    if masked:
        question = share_mask.mask_text(question)
        content = share_mask.mask_text(content)
        debate = [{**d, "text": share_mask.mask_text(str(d["text"]))} for d in debate]
    return {
        "question": question,
        "content": content,
        "debate": debate,
        "web": [{"title": str(w.get("title") or ""), "url": str(w.get("url") or ""),
                 "step": str(w.get("step") or "")}
                for w in answer.get("web") or [] if isinstance(w, dict)],
        "skills": [str(s) for s in answer.get("skills") or []],
        "activities": share_mask.surfaces(answer.get("activities") or [], masked),
    }


def sharer(claims: dict | None) -> str:
    """The first name a link is signed with: the reader should know who sent
    it, and a first name says that without the surname or the address."""
    words = str((claims or {}).get("name") or "").split()
    return words[0][:40] if words else ""


def preview(paths: UserPaths, tid: str, masked: bool, by: str = "") -> dict | None:
    """The page `create` would publish, published nowhere. None for an id no
    thread holds."""
    found = auth.find_answer(tid, paths.chat)
    return {**snapshot(found, masked), "by": by} if found else None


def create(
    paths: UserPaths, tid: str, masked: bool, lang: str, by: str = ""
) -> dict | None:
    """Publish the answer `tid`, signed with `by` (`sharer`); returns the
    stored share, or None for an id no thread holds. The same answer cut the
    same way is the same link."""
    found = auth.find_answer(tid, paths.chat)
    if found is None:
        return None
    links = _links(found["answer"])
    for link in links:
        if link["masked"] == masked and (kept := load(link["id"])) is not None:
            return _backfilled(kept, snapshot(found, masked))
    share_id = secrets.token_urlsafe(8)
    share = {
        "id": share_id,
        "owner": owner_of(paths),
        "answer_id": tid,
        **snapshot(found, masked),
        "by": by,
        "lang": lang,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = SHARES_DIR / f"{share_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, share, ensure_ascii=False, indent=2)
    storage.persist(path)
    links = [k for k in links if k["masked"] != masked]
    auth.stamp_share(tid, [*links, {"id": share_id, "masked": masked}], paths.chat)
    # A first read builds the list from the stamps, this one's included.
    _write_list(paths, [_entry(share),
                        *(k for k in listed(paths) if k["id"] != share_id)])
    obs.event("share.created", share=share_id, masked=masked,
              surfaces=len(share["activities"]), chars=len(share["content"]),
              turns=len(share["turns"]))
    return share


def _backfilled(kept: dict, cut: dict) -> dict:
    """A link made before the cases or the earlier turns were copied gets
    them the next time its answer is shared — the preview showed them: the
    same link, now with what the sharer saw above the answer."""
    missing = {key: cut[key] for key in ("debate", "turns")
               if key not in kept and cut[key]}
    if not missing:
        return kept
    kept = {**kept, **missing}
    path = SHARES_DIR / f"{kept['id']}.json"
    atomic.write_json(path, kept, ensure_ascii=False, indent=2)
    storage.persist(path)
    return kept


def kind_of(share: dict) -> str:
    """"watchlist" for a shared list; "answer" otherwise, the links made
    before there was a kind included."""
    return "watchlist" if share.get("kind") == "watchlist" else "answer"


def list_snapshot(tickers: list[str], title: str) -> dict:
    """What a link to a list shows: the symbols, upper-cased, once each, in
    the sharer's order, at most LIST_MAX; the title on one line."""
    from stocks.web.seo import ticker_symbol

    seen: list[str] = []
    for raw in tickers:
        symbol = ticker_symbol(str(raw or ""))
        if symbol and symbol not in seen:
            seen.append(symbol)
    return {
        "kind": "watchlist",
        "title": " ".join(str(title or "").split())[:_TITLE_CHARS],
        "tickers": seen[:LIST_MAX],
        "masked": False,
    }


def create_list(
    paths: UserPaths, tickers: list[str], title: str, lang: str, by: str = ""
) -> dict | None:
    """Publish a list of tickers, signed with `by`; returns the stored share,
    or None when no symbol in it is one. The same list under the same title
    is the same link."""
    cut = list_snapshot(tickers, title)
    if not cut["tickers"]:
        return None
    for row in listed(paths):
        if row.get("kind") != "watchlist":
            continue
        kept = load(row["id"])
        if (kept is not None and kept.get("tickers") == cut["tickers"]
                and kept.get("title") == cut["title"]):
            return kept
    share_id = secrets.token_urlsafe(8)
    share = {
        "id": share_id,
        "owner": owner_of(paths),
        "answer_id": "",
        **cut,
        "by": by,
        "lang": lang,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = SHARES_DIR / f"{share_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, share, ensure_ascii=False, indent=2)
    storage.persist(path)
    _write_list(paths, [_entry(share), *listed(paths)])
    obs.event("share.created", share=share_id, kind="watchlist",
              tickers=len(cut["tickers"]))
    return share


def follow(paths: UserPaths, share: dict) -> list[str]:
    """Put a shared list on the reader's watchlist, under its title when it
    has one; returns the symbols that were new to it."""
    tickers = [str(t) for t in share.get("tickers") or []]
    added = wl.add_entries(paths.watchlist, tickers, str(share.get("title") or ""))
    obs.event("share.followed", share=str(share.get("id") or ""),
              tickers=len(tickers), added=len(added))
    return added


def _links(answer: dict) -> list[dict]:
    return [{"id": str(k["id"]), "masked": k.get("masked") is True}
            for k in answer.get("shares") or []
            if isinstance(k, dict) and k.get("id")]


def load(share_id: str) -> dict | None:
    """The share `share_id` names, from disk or the bucket; None when there
    is none (never made, revoked, or not an id at all)."""
    path = _path(share_id)
    if path is None or not (path.exists() or storage.restore(path)):
        return None
    try:
        share = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        obs.warn("share.unreadable", share=share_id)
        return None
    return share if isinstance(share, dict) else None


def _drop(share_id: str) -> None:
    path = _path(share_id)
    if path is None:
        return
    path.unlink(missing_ok=True)
    storage.persist(path)  # a file that is gone deletes its key


def revoke(paths: UserPaths, share_id: str) -> bool:
    """Take down `share_id` and every other link its answer went out under.
    False when there is no such share or it is not this account's."""
    share = load(share_id)
    if share is None or share.get("owner") != owner_of(paths):
        return False
    if kind_of(share) == "watchlist":
        _drop(share_id)
        _write_list(paths, [k for k in listed(paths) if k["id"] != share_id])
        obs.event("share.revoked", share=share_id, links=1)
        return True
    tid = str(share.get("answer_id") or "")
    found = auth.find_answer(tid, paths.chat)
    # The answer may be gone from the thread (pruned), the link still up.
    links = _links(found["answer"]) if found else []
    ids = {share_id, *(k["id"] for k in links)}
    for each in ids:
        _drop(each)
    if found:
        auth.stamp_share(tid, [], paths.chat)
    _write_list(paths, [k for k in listed(paths)
                        if k["id"] not in ids and k["answer_id"] != tid])
    obs.event("share.revoked", share=share_id, links=len(ids))
    return True


def _entry(share: dict) -> dict:
    if kind_of(share) == "watchlist":
        # Named by its title, or by its symbols when it has none.
        named = str(share.get("title") or "") or ", ".join(share.get("tickers") or [])
    else:
        named = str(share.get("question") or "")
    return {
        "id": str(share.get("id") or ""),
        "kind": kind_of(share),
        "answer_id": str(share.get("answer_id") or ""),
        "question": " ".join(named.split())[:_LISTED_CHARS],
        "masked": share.get("masked") is True,
        "created": str(share.get("created") or ""),
    }


def _write_list(paths: UserPaths, entries: list[dict]) -> None:
    path = paths.shares
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, {"shares": entries}, ensure_ascii=False, indent=2)
    storage.persist(path)


def listed(paths: UserPaths) -> list[dict]:
    """The links this account has up, newest first: {id, kind, answer_id,
    question, masked, created}. The question is the stored one, so a masked
    link is listed masked; a list's is its name (`_entry`).

    An account that shared before the list was kept gets it built once from
    the stamps its threads still carry; what a pruned thread took with it is
    beyond recovering here, and those links stay up until the account goes.
    """
    path = paths.shares
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        rows = data.get("shares") if isinstance(data, dict) else None
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)
                    and ID_RE.match(str(r.get("id") or ""))]
    entries = []
    for conv in auth.load_book(paths.chat)["conversations"]:
        for message in conv["messages"]:
            for link in _links(message):
                if (share := load(link["id"])) is not None:
                    entries.append(_entry(share))
    entries.sort(key=lambda e: e["created"], reverse=True)
    _write_list(paths, entries)
    return entries


def continue_from(paths: UserPaths, share: dict) -> str:
    """Start the reader's own thread from a shared answer; returns its id.

    The shared thread goes in as its first turns, the earlier exchanges then
    the shared one, so the next question is asked with all of them above it.
    Each answer gets an id of this account's (a rating names it by that), and
    the shared one says where it came from. Named by the thread's first
    question, as the sharer's was."""
    exchanges = [t for t in share.get("turns") or [] if isinstance(t, dict)]
    exchanges.append(share)
    messages: list[dict] = []
    for each in exchanges:
        question = str(each.get("question") or "")
        if question:
            messages.append({"role": "user", "content": question})
        messages.append({
            "role": "assistant",
            "content": str(each.get("content") or ""),
            "skills": list(each.get("skills") or []),
            "debate": list(each.get("debate") or []),
            "web": list(each.get("web") or []),
            "activities": list(each.get("activities") or []),
            "id": secrets.token_hex(6),
        })
    messages[-1]["shared_from"] = str(share.get("id") or "")
    title = next((str(t.get("question") or "") for t in exchanges
                  if t.get("question")), "")
    cid = auth.seed_conversation(title, messages, paths.chat)
    obs.event("share.continued", share=str(share.get("id") or ""))
    return cid


def purge_owner(slug: str) -> int:
    """Delete every share `slug` made, on disk and in the bucket; returns how
    many. Account deletion runs it: a link outliving the account it quoted
    would break the promise that erasing it erases everything."""
    gone: set[str] = set()
    if SHARES_DIR.exists():
        for path in SHARES_DIR.glob("*.json"):
            try:
                owner = json.loads(path.read_text(encoding="utf-8")).get("owner")
            except (OSError, ValueError, AttributeError):
                continue
            if owner == slug:
                gone.add(path.stem)
    if storage.enabled():
        prefix = SHARES_DIR.relative_to(PROJECT_ROOT).as_posix() + "/"
        for key in storage.list_keys(prefix):
            stem = key.rsplit("/", 1)[-1].removesuffix(".json")
            if stem in gone or not ID_RE.match(stem):
                continue
            raw = storage.read_key(key)
            try:
                owner = json.loads(raw or b"{}").get("owner")
            except (ValueError, AttributeError):
                continue
            if owner == slug:
                gone.add(stem)
    for share_id in gone:
        _drop(share_id)
    return len(gone)
