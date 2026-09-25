"""Process-wide sliding-window rate limiter for expensive interactions.

The free LLM chain already has a per-account *daily* cap (engine.
spend_free_quota); this is the other half — burst protection. A script
posting a chat turn every 200ms would otherwise fan out into web searches,
routing calls and provider requests (spending real money on BYOK keys and
shared free-tier quota) as fast as the event loop allows.

In-memory on purpose: the app is a single Cloud Run container (the storage
consistency model already assumes that), so a process dict with a lock is
exact, free, and needs no schema. A restart forgets the counters, which for
burst control is fine.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Mapping
from typing import Protocol

_lock = threading.Lock()
_events: dict[str, deque[float]] = {}

# One chat turn every few seconds sustained, with room for a quick exchange.
CHAT_MAX_TURNS = 20
CHAT_WINDOW_S = 300


def allow(key: str, *, max_events: int = CHAT_MAX_TURNS,
          window_s: float = CHAT_WINDOW_S) -> bool:
    """Record one event for `key`; False when the window is already full.

    `key` scopes the limit — use something account-stable (the user's data
    dir), not the Streamlit session id, so reconnecting doesn't reset it.
    """
    now = time.monotonic()
    with _lock:
        q = _events.setdefault(key, deque())
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= max_events:
            return False
        q.append(now)
        return True


def retry_after(key: str, *, window_s: float = CHAT_WINDOW_S) -> int:
    """Seconds until the oldest event for `key` leaves the window (>= 0)."""
    now = time.monotonic()
    with _lock:
        q = _events.get(key)
        if not q:
            return 0
        return max(0, round(window_s - (now - q[0])))


# ------------------------------------------------------------ who is knocking
# Here rather than in `web/server.py`, which is where it grew, because the API
# needs the same answer for its one unauthenticated write (`POST /v1/feedback`
# from a guest) and cannot import the server that mounts it. `server.client_ip`
# re-exports this, so there is still one definition of the word.

# How many proxies sit in front of this process. Cloud Run's frontend appends
# its own hop to X-Forwarded-For, so the client is the entry before the last.
# Behind a second proxy (a CDN in front of Cloud Run) it is two before, and
# with no proxy at all the socket peer is the client.
TRUSTED_PROXY_HOPS = 1


class _Peer(Protocol):
    # A property, not an attribute: Starlette's peer is a NamedTuple, whose
    # fields are read-only, and a Protocol asking for a writable one excludes
    # exactly the type it was written to describe.
    @property
    def host(self) -> str: ...


class _Addressed(Protocol):
    """The part of a request this needs — headers and a peer.

    Structural rather than `starlette.requests.Request` so this module keeps
    importing nothing: both front ends hand it the real thing.

    Read-only members, and typed rather than `object`: a Protocol that declares
    a plain attribute demands one that can be *written*, which Starlette's own
    `Request.client` (a property) is not — so the real request stopped matching
    the shape describing it.
    """

    # `Mapping`, not a hand-written shape: Starlette's `Headers` *is* one, and
    # spelling its `get` out by hand only invents a signature to disagree with.
    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def client(self) -> _Peer | None: ...


def _trusted_hops() -> int:
    try:
        return max(0, int(os.environ.get("TRUSTED_PROXY_HOPS", TRUSTED_PROXY_HOPS)))
    except ValueError:
        return TRUSTED_PROXY_HOPS


def client_ip(request: _Addressed) -> str:
    """The caller's address as far as it can be trusted.

    X-Forwarded-For is client-supplied up to the first proxy that appends to
    it, so only the entries our own infrastructure wrote mean anything: with
    one trusted hop, the last entry is Cloud Run's frontend and the one before
    it is what that frontend saw. Everything to the left of that a client can
    write itself.

    A determined attacker still has as many "addresses" as it has real ones,
    which is why this is a speed bump in front of the account-level limits,
    not the thing keeping anyone honest.
    """
    parts = [
        p.strip()
        for p in request.headers.get("x-forwarded-for", "").split(",")
        if p.strip()
    ]
    hops = _trusted_hops()
    if parts and hops and len(parts) > hops:
        return parts[-(hops + 1)]
    if parts and not hops:
        return parts[0]
    return request.client.host if request.client else "unknown"
