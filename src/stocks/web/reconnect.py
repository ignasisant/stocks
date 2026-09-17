"""Turns cut by a lost connection, told apart from turns the reader stopped.

Streamlit stops a running script the moment its websocket goes: the session
manager's disconnect path calls ``request_script_stop`` before it files the
session away for ``server.disconnectedSessionTTL`` seconds (120 by default).
From inside the script that stop is indistinguishable from the one the
composer's Stop button asks for — same request, same unwind — and the
assistant has to tell them apart. A reader who pressed Stop wants the
half-written answer kept exactly as it was cut; a reader whose phone locked
the screen, or who switched apps on iOS (where the page is frozen and the
socket dropped within seconds), wants the answer they never got.

Only the runtime knows which of the two happened, so the disconnect is
recorded where it happens: the session manager is wrapped once per process and
every session id it disconnects is remembered with the time. The next script
run on that session — Streamlit's own frontend asks for one as soon as it
reconnects to a session whose script was still running — reads the mark and
knows the connection went, not the reader.

Best-effort by design: the wrap reaches into Streamlit's runtime internals, so
a version that moves them leaves `dropped` answering False and every stop
falls back to being read as the reader's. That is the behaviour this module
replaces, never a crash.
"""

from __future__ import annotations

import threading
import time

from stocks import obs

# Marks are read by the run that follows the disconnect, which arrives seconds
# later. A session the reader never comes back to is forgotten by Streamlit
# itself after server.disconnectedSessionTTL, so anything older than a few
# minutes here is dead weight held on a long-lived server.
_KEEP_SECONDS = 900.0

_LOCK = threading.Lock()
_DROPPED: dict[str, float] = {}
# None = not attempted, True = wrapped, False = the runtime did not look the
# way this module expects (attempted once, never retried).
_WATCHING: bool | None = None


def _mark(session_id: str) -> None:
    """Remember that this session lost its websocket, just now."""
    now = time.time()
    with _LOCK:
        _DROPPED[session_id] = now
        for sid, when in list(_DROPPED.items()):
            if now - when > _KEEP_SECONDS:
                del _DROPPED[sid]


def watch() -> bool:
    """Wrap the runtime's session manager once. True when marks are live.

    Called from the script thread (the first run that cares), which is after
    the runtime exists and before any disconnect this process has to explain.
    """
    global _WATCHING
    with _LOCK:
        if _WATCHING is not None:
            return _WATCHING
        try:
            from streamlit.runtime import get_instance

            manager = get_instance()._session_mgr
            original = manager.disconnect_session

            def disconnect_session(session_id: str, _inner=original) -> None:
                _mark(session_id)
                return _inner(session_id)

            # ty: ignore[invalid-assignment]  (wrapping the bound method)
            manager.disconnect_session = disconnect_session
        except Exception as exc:
            obs.warn("chat.reconnect.unavailable",
                     error_type=type(exc).__name__, error=str(exc)[:300])
            _WATCHING = False
        else:
            _WATCHING = True
        return _WATCHING


def _session_id() -> str | None:
    """This run's session id, or None off a script thread (tests, scripts)."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx(suppress_warning=True)
    except Exception:
        return None
    return ctx.session_id if ctx is not None else None


def dropped(since: float | None = None) -> bool:
    """Whether this session lost its websocket since `since` (a time.time()).

    Reading consumes the mark: it explains one cut turn, and a second turn
    stopped later is the reader's until the connection goes again.

    `since` is what keeps an idle disconnect — one with no turn under it, and
    so with no run to consume its mark — from being read much later as the
    explanation for a turn the reader really did stop. Pass the moment the
    turn started; a disconnect older than that cut something else.
    """
    if not watch():
        return False
    sid = _session_id()
    if sid is None:
        return False
    with _LOCK:
        when = _DROPPED.pop(sid, None)
    if when is None:
        return False
    return since is None or when >= since
