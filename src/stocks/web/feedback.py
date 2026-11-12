"""In-app feedback, stored durably — the sink behind `POST /api/v1/feedback`.

Two sinks, deliberately redundant:

* A JSON file per submission under data/feedback/, mirrored to the bucket
  (key data/feedback/<stamp>-<id>.json) — the full text, kept until deleted.
  `stocks feedback` reads them back, local or straight from the bucket. When
  the writer attached a picture of their screen it sits beside it under the
  same stem (<stamp>-<id>.jpg) and the JSON names it in "shot".
* An obs event ("feedback") — so submissions show up in the production log
  timeline next to whatever the user was doing when they hit the button, and
  `stocks logs tail --event feedback` works with no extra tooling.

Who sent it: the account's data-dir name (the same pseudonymous slug the logs
use), "guest" for anonymous visitors. The text itself is user input — treat it
as untrusted when reading it back anywhere.

The way back: `stocks feedback-reply <id> "…"` files the operator's answer to a
submission under data/feedback/replies/<slug>.json, and the writer's app shows
it once (`shell/FeedbackReply`). Kept here, beside the submissions, and not in
the account's own directory: the running server treats its copy of an account
as the current one after the first touch (`storage.restore_once`), so a reply
written into it from outside would not be seen until the next boot.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR
from stocks.i18n import DEFAULT_LANG

FEEDBACK_DIR = DATA_DIR / "feedback"
KINDS = ("bug", "idea", "other")
MAX_CHARS = 4000

def submit(
    text: str,
    kind: str,
    page: str = "",
    shot: bytes | None = None,
    *,
    sender: str = "guest",
    lang: str = "",
) -> Path:
    """Persist one submission (disk + bucket) and log the event.

    `shot` is the optional JPEG of the screen the writer was on, already
    decoded and size-checked by the route.

    `sender` and `lang` are the two facts only the caller knows: the account's
    pseudonymous slug ("guest" when anonymous) and the reader's language.
    """
    kind = kind if kind in KINDS else "other"
    text = text.strip()[:MAX_CHARS]
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    path = FEEDBACK_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # The picture goes first: the JSON must never name a file that isn't there,
    # and a submission whose image failed is still a submission.
    shot_name = _store_shot(path, shot) if shot else ""
    payload = {
        "ts": stamp,
        "kind": kind,
        "text": text,
        "page": page,
        "user": sender,
        "lang": lang or DEFAULT_LANG,
    }
    if shot_name:
        payload["shot"] = shot_name
    atomic.write_json(path, payload, ensure_ascii=False, indent=2)
    storage.persist(path)
    obs.event("feedback", kind=kind, page=page, chars=len(text),
              shot=len(shot) if shot and shot_name else 0)
    return path


# A thumbs on an answer. Filed beside the widget's submissions (kind
# "rating"), because what a thumbs-down is worth is the turn it was pressed on:
# the question, the answer, who wrote it, what it searched and read. That is
# the reader's own chat, already in the bucket under their account; this copy
# is the operator's, kept so `stocks feedback` can read why answers miss
# without opening anyone's account.
RATING_REASONS = ("made_up", "wrong", "missed", "other")
_ANSWER_CHARS = 4000
_QUESTION_CHARS = 1000
_HISTORY_TURNS = 12
_HISTORY_CHARS = 600


def rate(vote: str, turn: dict, question: str, *, reason: str = "",
         note: str = "", sender: str = "guest", lang: str = "",
         thread: str = "", history: list[dict] | None = None) -> Path:
    """Persist one answer's rating (disk + bucket) and log it.

    `turn` is the stored answer it was pressed on and `history` the turns
    above it (`auth.rate_turn`) — the last _HISTORY_TURNS of them, each cut,
    since a conversation that went wrong rarely went wrong on its last line.
    Only a thumbs-down asks what went wrong, so `reason` is kept only on one;
    `note` is what the reader wrote either way — a thumbs-up's says what was
    worth keeping."""
    down = vote == "down"
    reason = reason if down and reason in RATING_REASONS else ""
    note = note.strip()[:MAX_CHARS]
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    path = FEEDBACK_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    web = [str(w.get("url") or "") for w in turn.get("web") or []
           if isinstance(w, dict)]
    steps = [{"tool": str(st.get("tool") or ""), "arg": str(st.get("arg") or "")}
             for st in turn.get("steps") or [] if isinstance(st, dict)]
    payload = {
        "ts": stamp,
        "kind": "rating",
        "vote": vote,
        "reason": reason,
        "text": note,
        "page": "chat",
        "user": sender,
        "lang": lang or DEFAULT_LANG,
        "turn": str(turn.get("id") or ""),
        "provider": str(turn.get("provider") or ""),
        # An app action the classifier read out of the message (add_ticker…),
        # "" for a written answer.
        "action": str(turn.get("action") or ""),
        "skills": [str(x) for x in turn.get("skills") or []],
        "web": web,
        "steps": steps,
        "thread": thread,
        "history": [{"role": str(h.get("role") or ""),
                     "content": str(h.get("content") or "")[:_HISTORY_CHARS]}
                    for h in (history or [])[-_HISTORY_TURNS:]],
        "question": question[:_QUESTION_CHARS],
        "answer": str(turn.get("content") or "")[:_ANSWER_CHARS],
    }
    atomic.write_json(path, payload, ensure_ascii=False, indent=2)
    storage.persist(path)
    obs.event("chat.rated", vote=vote, reason=reason,
              provider=payload["provider"], web=len(web), steps=len(steps),
              note=len(note))
    return path


# The once-per-account "how is TopStocks for you" prompt (shell/RatePrompt).
# Its own kind rather than a widget submission: a score with no comment is a
# complete answer here, and the widget's route requires text.
APP_RATING = "app_rating"
STARS = range(1, 6)


def rate_app(stars: int, text: str = "", *, page: str = "",
             sender: str = "guest", lang: str = "") -> Path:
    """Persist one score of the app as a whole (disk + bucket) and log it."""
    if stars not in STARS:
        raise ValueError(f"stars must be 1–5, not {stars!r}")
    text = text.strip()[:MAX_CHARS]
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    path = FEEDBACK_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": stamp,
        "kind": APP_RATING,
        "stars": stars,
        "text": text,
        "page": page,
        "user": sender,
        "lang": lang or DEFAULT_LANG,
    }
    atomic.write_json(path, payload, ensure_ascii=False, indent=2)
    storage.persist(path)
    obs.event("app.rated", stars=stars, chars=len(text))
    return path


def _store_shot(path: Path, shot: bytes) -> str:
    """Write the screenshot beside its submission; "" if it could not be kept.

    The one swallowed failure in this module, and deliberate: the comment is
    the report and the picture is an extra, so a bucket that refuses the image
    must not cost us the text that came with it. The local copy goes too — an
    orphan nothing names would never be read, only found years later.
    """
    image = path.with_suffix(".jpg")
    try:
        image.write_bytes(shot)
        storage.persist(image)
    except Exception:
        obs.event("feedback.shot_store_failed")
        image.unlink(missing_ok=True)
        return ""
    return image.name


# ------------------------------------------------------------------ read side


def stored(prefix: str = "data/feedback/") -> list[dict]:
    """Every stored submission, oldest first — local files plus bucket-only
    ones (a headless checkout sees the bucket, a dev checkout sees both)."""
    items: dict[str, dict] = {}
    if FEEDBACK_DIR.is_dir():
        for f in sorted(FEEDBACK_DIR.glob("*.json")):
            try:
                items[f.name] = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
    for key in storage.list_keys(prefix):
        name = key.removeprefix(prefix)
        if name in items or not name.endswith(".json") or "/" in name:
            # The .jpg siblings are fetched on demand by shot_path; replies/
            # holds the answers, not submissions.
            continue
        raw = storage.read_key(key)
        if raw:
            try:
                items[name] = json.loads(raw)
            except ValueError:
                continue
    return [{**items[k], "id": k.removesuffix(".json")} for k in sorted(items)]


def latest_ratings(items: list[dict]) -> list[dict]:
    """The submissions with each answer's thumbs reduced to its last.

    A thumbs-down is sent on the press and again with its reason, and a reader
    may change their mind: an answer's last rating is its verdict. Per answer,
    not per conversation: a thread with three answers voted down showed one
    (prod triage 2026-11-02). Everything that is not a rating passes through."""

    def rated(it: dict) -> tuple:
        return (it.get("user"), it.get("turn"))

    last = {
        rated(it): i
        for i, it in enumerate(items)
        if it.get("kind") == "rating" and it.get("turn")
    }
    return [
        it
        for i, it in enumerate(items)
        if it.get("kind") != "rating" or not it.get("turn") or last[rated(it)] == i
    ]


def shot_path(name: str) -> Path | None:
    """The local file for a submission's screenshot, or None if there isn't one.

    Pulls it out of the bucket when this checkout has never seen it, so
    `stocks feedback` on a fresh clone can still open the picture. `name`
    comes out of a stored JSON file — treated as untrusted: one directory, one
    extension, no traversal.
    """
    if not name or name != Path(name).name or not name.endswith(".jpg"):
        return None
    path = FEEDBACK_DIR / name
    if path.exists() or storage.restore(path):
        return path
    return None


# ------------------------------------------------------------------ replies

REPLIES_DIR = FEEDBACK_DIR / "replies"
REPLY_CHARS = 600
# How long a server keeps an account's replies before asking the bucket again:
# every signed-in load asks, and almost every answer is "none".
REPLIES_TTL_S = 300.0

# A submission's id is its file stem: <stamp>-<6 hex>.
_ID = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z-[0-9a-f]{6}")
_memo: dict[str, tuple[float, list[dict]]] = {}
_memo_lock = threading.Lock()


class NoSuchFeedback(LookupError):
    """The id names no stored submission, or one nobody can be answered at."""


def _replies_path(slug: str) -> Path:
    return REPLIES_DIR / f"{slug}.json"


def _read_replies(slug: str) -> list[dict]:
    path = _replies_path(slug)
    raw = storage.read(path) if storage.enabled() else None
    if raw is None and path.exists():
        raw = path.read_bytes()
    try:
        rows = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def submission(feedback_id: str) -> dict:
    """The stored submission `feedback_id` names (`stored()`'s file stem)."""
    if not _ID.fullmatch(feedback_id):
        raise NoSuchFeedback(feedback_id)
    path = FEEDBACK_DIR / f"{feedback_id}.json"
    raw = path.read_bytes() if path.exists() else storage.read(path)
    if not raw:
        raise NoSuchFeedback(feedback_id)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise NoSuchFeedback(feedback_id) from exc


def reply(feedback_id: str, text: str) -> dict:
    """File the operator's answer to one submission; returns that submission.

    A second answer to the same submission replaces the first: the reader is
    shown one, and it should be the last thing the operator meant. A guest has
    no account to be shown anything in, so a guest's submission is refused.
    """
    item = submission(feedback_id)
    slug = str(item.get("user") or "")
    if not slug or slug == "guest":
        raise NoSuchFeedback(feedback_id)
    text = " ".join(text.split())[:REPLY_CHARS]
    if not text:
        raise ValueError("an empty reply")
    stamp = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    rows = [r for r in _read_replies(slug) if r.get("id") != feedback_id]
    rows.append({"id": feedback_id, "ts": stamp, "about": str(item.get("ts", "")),
                 "kind": str(item.get("kind", "")), "text": text})
    path = _replies_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, rows, ensure_ascii=False, indent=2)
    storage.persist(path)
    with _memo_lock:
        _memo.pop(slug, None)
    obs.event("feedback.replied", user=slug, kind=item.get("kind", ""), chars=len(text))
    return item


def replies_for(slug: str, *, now: float | None = None) -> list[dict]:
    """Every answer filed for this account, oldest first; [] for a guest.

    Read from the bucket, not from a restored copy, and held for
    `REPLIES_TTL_S`: an answer reaches the reader within minutes of being
    filed, and an account with none costs one read per few minutes.
    """
    if not slug or slug == "guest":
        return []
    now = time.monotonic() if now is None else now
    with _memo_lock:
        held = _memo.get(slug)
        if held and now - held[0] < REPLIES_TTL_S:
            return held[1]
    rows = _read_replies(slug)
    with _memo_lock:
        _memo[slug] = (now, rows)
    return rows
