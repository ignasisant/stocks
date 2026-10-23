"""The browsers an account is signed in on, so the owner can end any of them.

`stocks.session` mints a signed cookie per sign-in and `stocks.revocation` can
end one early; this is the account-side list that makes that usable. One JSON
file per account (`UserPaths.devices`, in `accounts.USER_FILES`, so it syncs to
the bucket like the prefs) with one row per live session:

* the id is the sha256 of the session's own `sid` — never the cookie value, and
  not the raw `sid` either, so a copy of the file cannot be turned back into a
  working handle;
* `created` / `seen` as epoch seconds — `seen` is only rewritten after
  `SEEN_EVERY`, so reading the app is not a write per request;
* `device` is the user agent boiled down to "Chrome · macOS". No address, no
  location: the host gives us neither without a vendor, and the raw agent
  string is more fingerprint than the list needs.

Ending a row stamps the hash in `revocation`, which refuses the cookie on its
next request. Rows past the cookie's own lifetime, and rows whose session was
ended elsewhere (plain sign-out), drop out on the next write.

Nothing here raises into a request: bookkeeping failures are warnings.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from stocks import atomic, obs, revocation, storage

FILE = "devices.json"

# A cookie's `seen` is rewritten at most this often.
SEEN_EVERY = 5 * 60
MAX_ROWS = 20

_lock = threading.Lock()
# sid hash -> monotonic-free wall clock of the last write, so a request that
# does not need a write does not even read the file.
_touched: dict[str, float] = {}


sid_hash = revocation.sid_key


_BROWSERS = (
    ("Edge", re.compile(r"\bEdg(?:e|A|iOS)?/")),
    ("Opera", re.compile(r"\b(?:OPR|Opera)/")),
    ("Firefox", re.compile(r"\b(?:Firefox|FxiOS)/")),
    ("Chrome", re.compile(r"\b(?:Chrome|CriOS)/")),
    ("Safari", re.compile(r"\bSafari/")),
)
_SYSTEMS = (
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Android", re.compile(r"Android")),
    ("Windows", re.compile(r"Windows")),
    ("macOS", re.compile(r"Macintosh|Mac OS X")),
    ("ChromeOS", re.compile(r"CrOS")),
    ("Linux", re.compile(r"Linux|X11")),
)


def summarise(user_agent: str) -> str:
    """"Chrome · macOS" from a user-agent string; "" when it says nothing."""
    ua = (user_agent or "")[:512]
    browser = next((n for n, rx in _BROWSERS if rx.search(ua)), "")
    system = next((n for n, rx in _SYSTEMS if rx.search(ua)), "")
    return " · ".join(p for p in (browser, system) if p)


def _read(path: Path) -> dict[str, dict]:
    # No restore here: the account's bucket restore (`accounts.restore_account`,
    # `USER_FILES`) already brought this file down with the rest.
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        obs.error("session.devices_unreadable", error_type=type(exc).__name__)
        return {}
    rows = data.get("sessions") if isinstance(data, dict) else None
    return {k: v for k, v in (rows or {}).items() if isinstance(v, dict)}


def _write(path: Path, rows: dict[str, dict]) -> None:
    now = time.time()
    live = {
        k: v for k, v in rows.items()
        if float(v.get("expires") or 0) > now and not revocation.session_revoked(k)
    }
    newest = sorted(live, key=lambda k: float(live[k].get("seen") or 0))[-MAX_ROWS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(path, {"sessions": {k: live[k] for k in newest}}, indent=1)
    storage.persist(path)


def record(
    path: Path, sid: str, *, user_agent: str, created: float, expires: float,
    now: float | None = None,
) -> None:
    """Add (or refresh) the row of the session `sid`. Sign-in calls this; so
    does the first request of a cookie minted before this list existed."""
    if not sid:
        return
    now = time.time() if now is None else now
    key = sid_hash(sid)
    try:
        with _lock:
            rows = _read(path)
            row = rows.get(key) or {}
            rows[key] = {
                "created": float(row.get("created") or created),
                "seen": now,
                "expires": float(expires),
                "device": summarise(user_agent) or row.get("device", ""),
            }
            _write(path, rows)
            _touched[key] = now
    except Exception as exc:  # noqa: BLE001 — bookkeeping, not the request
        obs.warn("session.devices_record_failed", error_type=type(exc).__name__)


def touch(
    path: Path, sid: str, *, user_agent: str, created: float, expires: float,
    now: float | None = None,
) -> None:
    """Mark the session active; a write at most once per `SEEN_EVERY`."""
    if not sid:
        return
    now = time.time() if now is None else now
    last = _touched.get(sid_hash(sid))
    if last is not None and now - last < SEEN_EVERY:
        return
    record(path, sid, user_agent=user_agent, created=created, expires=expires, now=now)


def listing(path: Path, current_sid: str, now: float | None = None) -> list[dict]:
    """The live rows, newest activity first, the caller's own marked."""
    now = time.time() if now is None else now
    me = sid_hash(current_sid) if current_sid else ""
    with _lock:
        rows = _read(path)
    out = [
        {
            "id": k,
            "device": str(v.get("device") or ""),
            "created": float(v.get("created") or 0),
            "seen": float(v.get("seen") or 0),
            "current": k == me,
        }
        for k, v in rows.items()
        if float(v.get("expires") or 0) > now and not revocation.session_revoked(k)
    ]
    return sorted(out, key=lambda r: -r["seen"])


def end(path: Path, key: str) -> bool:
    """End the session whose row is `key`; False when this account has none."""
    with _lock:
        rows = _read(path)
        row = rows.get(key)
        if row is None:
            return False
        revocation.revoke_hash(key, float(row.get("expires") or 0), _max_age())
        rows.pop(key)
        _write(path, rows)
        _touched.pop(key, None)
    return True


def end_others(path: Path, current_sid: str) -> int:
    """End every session but the caller's; how many there were."""
    me = sid_hash(current_sid) if current_sid else ""
    with _lock:
        rows = _read(path)
        others = [k for k in rows if k != me]
        for k in others:
            revocation.revoke_hash(k, float(rows[k].get("expires") or 0), _max_age())
            rows.pop(k)
            _touched.pop(k, None)
        if others:
            _write(path, rows)
    return len(others)


def _max_age() -> int:
    from stocks import session

    return session.MAX_AGE


def reset_for_tests() -> None:
    _touched.clear()
