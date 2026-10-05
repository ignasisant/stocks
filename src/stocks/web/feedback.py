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
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR
from stocks.web.i18n import DEFAULT_LANG

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
    """Persist one conversation's rating (disk + bucket) and log it.

    `turn` is the stored answer it was pressed on and `history` the turns
    above it (`auth.rate_turn`) — the last _HISTORY_TURNS of them, each cut,
    since a conversation that went wrong rarely went wrong on its last line.
    Only a thumbs-down asks why, so `reason` and `note` are kept only on one."""
    down = vote == "down"
    reason = reason if down and reason in RATING_REASONS else ""
    note = note.strip()[:MAX_CHARS] if down else ""
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
        if name in items or not name.endswith(".json"):
            continue  # the .jpg siblings are fetched on demand by shot_path
        raw = storage.read_key(key)
        if raw:
            try:
                items[name] = json.loads(raw)
            except ValueError:
                continue
    return [items[k] for k in sorted(items)]


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
