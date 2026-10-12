"""Session cookies that stopped meaning anybody before they expired.

`stocks.session` signs a cookie and trusts it for `MAX_AGE`; without this a
signed-out or erased account kept answering to any copy of its cookie for the
rest of the month. Two ways a cookie ends early:

* **one session** — sign-out names the `sid` the cookie carries, so the
  browser that asked is signed out and the user's other devices are not;
* **every session of an address** — account deletion stamps a `not_before`
  for the email, so no cookie minted before the erasure resolves to the
  re-provisioned (empty) account again.

One JSON file, global because a cookie arrives before anybody knows whose
data dir it opens, mirrored to the bucket like `connector/store.py`. Emails
are kept as their sha256, so a copy of the file names nobody. Entries age out
once every cookie they could match has expired on its own (`MAX_AGE`).

Nothing here raises into a request: an unreadable file starts empty, and a
failed mirror is a warning — the revocation still holds on this instance.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR

DIR = DATA_DIR / "sessions"
NAME = "revoked.json"

_lock = threading.Lock()
_state: dict[str, dict[str, float]] | None = None


def _digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _load() -> dict[str, dict[str, float]]:
    global _state
    if _state is not None:
        return _state
    try:
        storage.restore_once(DIR, (DIR / NAME,))
    except Exception as exc:  # noqa: BLE001 — start from disk, say so
        obs.warn("session.revoked_restore_failed", error_type=type(exc).__name__)
    data: object = {}
    try:
        data = json.loads((DIR / NAME).read_text())
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        obs.error("session.revoked_unreadable", error_type=type(exc).__name__)
    data = data if isinstance(data, dict) else {}
    _state = {
        k: {str(i): float(v) for i, v in (data.get(k) or {}).items()}
        for k in ("sid", "before")
    }
    return _state


def _save(state: dict[str, dict[str, float]], max_age: int) -> None:
    now = time.time()
    # A sid entry holds the cookie's own expiry; a `before` stamp matters only
    # while a cookie minted before it could still be inside its max age.
    state["sid"] = {k: v for k, v in state["sid"].items() if v > now}
    state["before"] = {
        k: v for k, v in state["before"].items() if v + max_age > now
    }
    DIR.mkdir(parents=True, exist_ok=True)
    atomic.write_json(DIR / NAME, state, indent=1, sort_keys=True)
    try:
        storage.persist(DIR / NAME)
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        obs.warn("session.revoked_persist_failed", error_type=type(exc).__name__)


def revoke_session(sid: str, expires: float, max_age: int) -> None:
    """End the one session `sid` names; `expires` is when it would have."""
    if not sid:
        return
    with _lock:
        state = _load()
        state["sid"][sid] = float(expires)
        _save(state, max_age)


def revoke_email(email: str, max_age: int) -> None:
    """End every session of `email` minted up to now."""
    if not email.strip():
        return
    with _lock:
        state = _load()
        state["before"][_digest(email)] = time.time()
        _save(state, max_age)


def revoked(payload: dict) -> bool:
    """Whether a verified session payload has been ended early."""
    try:
        with _lock:
            state = _load()
            sid = str(payload.get("sid") or "")
            if sid and sid in state["sid"]:
                return True
            before = state["before"].get(_digest(str(payload.get("email") or "")))
        return before is not None and float(payload.get("iat") or 0) <= before
    except Exception as exc:  # noqa: BLE001 — a store fault never 500s a page
        obs.warn("session.revoked_check_failed", error_type=type(exc).__name__)
        return False


def reset_for_tests() -> None:
    """Forget the in-memory index (tests point `DIR` elsewhere first)."""
    global _state
    with _lock:
        _state = None
