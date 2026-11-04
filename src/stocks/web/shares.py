"""A chat answer shared by link — the store behind `/?share=<id>`.

A shared answer is a frozen copy, not a pointer into the sharer's chat.json:
threads there are pruned (idle, capped, deleted by their owner) and a link
sent to a group chat is opened weeks later. So `create` cuts the answer once
(`chat/share_mask.py`) and writes it to data/shares/<id>.json, mirrored to the
bucket like feedback; `load` reads it from either.

What is copied: the question, the answer's words, the pages it cited, the
lenses it used and the surfaces it drew (inert). What never is: its tool
trace, the memories it read or wrote, a proposal, the debate, the model. A
trace quotes the book line by line, and none of the rest is the answer.

The id is random (`token_urlsafe`), so a link is found only by being sent.
The sharer's answer is stamped with the links it went out under
(`auth.stamp_share`), one per cut — the masked link and the unmasked one are
different pages, and a link already sent must keep working when the other is
made. `revoke` takes every one of them down, and so does deleting the
account (`purge_owner`).
"""

from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from stocks import atomic, obs, storage
from stocks.accounts import UserPaths
from stocks.chat import share_mask
from stocks.config import DATA_DIR, PROJECT_ROOT
from stocks.web import auth

SHARES_DIR = DATA_DIR / "shares"
# What `secrets.token_urlsafe(8)` spells, give or take: the route and the
# server's card both check it before a path is built from it.
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,24}$")
_QUESTION_CHARS = 1000


def owner_of(paths: UserPaths) -> str:
    """The account's pseudonymous slug, as feedback and the logs name it."""
    return "owner" if paths.root == PROJECT_ROOT else paths.root.name


def _path(share_id: str) -> Path | None:
    return SHARES_DIR / f"{share_id}.json" if ID_RE.match(share_id or "") else None


def snapshot(found: dict, masked: bool) -> dict:
    """What a link to the answer `found` (`auth.find_answer`) shows."""
    answer = found["answer"]
    question = found["question"][:_QUESTION_CHARS]
    content = str(answer.get("content") or "")
    if masked:
        question = share_mask.mask_text(question)
        content = share_mask.mask_text(content)
    return {
        "question": question,
        "content": content,
        "web": [{"title": str(w.get("title") or ""), "url": str(w.get("url") or ""),
                 "step": str(w.get("step") or "")}
                for w in answer.get("web") or [] if isinstance(w, dict)],
        "skills": [str(s) for s in answer.get("skills") or []],
        "activities": share_mask.surfaces(answer.get("activities") or [], masked),
        "masked": masked,
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
            return kept
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
    obs.event("share.created", share=share_id, masked=masked,
              surfaces=len(share["activities"]), chars=len(share["content"]))
    return share


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
    tid = str(share.get("answer_id") or "")
    found = auth.find_answer(tid, paths.chat)
    # The answer may be gone from the thread (pruned), the link still up.
    links = _links(found["answer"]) if found else []
    ids = {share_id, *(k["id"] for k in links)}
    for each in ids:
        _drop(each)
    if found:
        auth.stamp_share(tid, [], paths.chat)
    obs.event("share.revoked", share=share_id, links=len(ids))
    return True


def continue_from(paths: UserPaths, share: dict) -> str:
    """Start the reader's own thread from a shared answer; returns its id.

    The question and the answer go in as its first turns, so the next
    question is asked with them above it, and the answer gets an id of this
    account's (a rating names it by that) and says where it came from."""
    question = str(share.get("question") or "")
    answer = {
        "role": "assistant",
        "content": str(share.get("content") or ""),
        "skills": list(share.get("skills") or []),
        "web": list(share.get("web") or []),
        "activities": list(share.get("activities") or []),
        "id": secrets.token_hex(6),
        "shared_from": str(share.get("id") or ""),
    }
    cid = auth.seed_conversation(
        question, [{"role": "user", "content": question}, answer], paths.chat)
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
