"""Cloud Run's CPU for work a request started and did not wait for.

Billed per request, an instance's CPU is throttled to almost nothing between
requests, and a thread a request left behind stalls with it — the refresh a
stale memo starts on its way out (`cache.coalesced`). The book's price
download is twenty seconds to a minute; a page's dozen requests are over in
two, and the refresh then sat frozen until its wall-clock budget ran out and
failed, so the next visit found the same stale prices and started it again.

So while one is running this service holds one request open to itself
(`POST /v1/hold`, outside the gate, authenticated by a token that never leaves
the process) — the trick a detached chat run uses (`api/runs.py`). One hold
covers every refresh in flight; off Cloud Run there is nothing to hold.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Header, HTTPException, Response, status

from stocks import obs
from stocks.api import runs

# Longest a hold stays open: past every download budget, under Cloud Run's
# request timeout. A refresh still running then gets a new hold, not this one.
HOLD_S = 280.0

# The API's base URL as the request that started the refresh reached it (the
# public front end, which is what Cloud Run counts), set per request by the
# API middleware. A refresh started with no request on the stack — a warm-up
# at boot — has no front end to call.
BASE: ContextVar[str | None] = ContextVar("hold_base", default=None)
PATH = "v1/hold"


def base_of(scope: Mapping[str, Any], base_url: str) -> str:
    """The API's own base URL for a request: `base_url` with the mount kept.

    Starlette builds `request.base_url` from the outermost app's root, so under
    the shell's `/api` mount it names the site root, and a hold aimed there is
    a 404. The mount is in the scope's `root_path`.
    """
    at = urlsplit(base_url)
    root = scope.get("root_path", "").rstrip("/") + "/"
    return urlunsplit((at.scheme, at.netloc, root, "", ""))


def pinned(url: str) -> str:
    """`url` on the deploy's declared origin (`APP_PUBLIC_URL`), when it has one.

    A hold carries a token to whatever host it is aimed at, and a URL built
    from the request takes its host from the caller's own Host header. The
    front end refuses hosts it does not serve today; this keeps that from
    being the only thing standing between a token and somebody else's server.
    """
    from stocks.notify.links import app_base

    origin = app_base()
    if not origin:
        return url
    to, at = urlsplit(origin), urlsplit(url)
    return urlunsplit((to.scheme, to.netloc, at.path, at.query, at.fragment))


_TOKEN = secrets.token_urlsafe(32)
_lock = threading.Lock()
_pending: set[threading.Event] = set()
_active = False


def keep(done: threading.Event) -> None:
    """Hold the instance's CPU until `done` is set (or `HOLD_S` passes)."""
    global _active
    base = BASE.get()
    if base is None or not runs.on_cloud_run():
        return
    url = base.rstrip("/") + "/" + PATH
    with _lock:
        _pending.add(done)
        if _active:
            return
        _active = True
    threading.Thread(target=_hold, args=(url,), name="cpu-hold", daemon=True).start()


def spawn(name: str, target: Callable[[], None]) -> threading.Thread:
    """Start `target` on a daemon thread, the CPU kept on it until it ends.

    From the request thread: `keep` reads the request's base URL from a
    contextvar, and the thread itself inherits none of it. Off Cloud Run this
    is a plain daemon thread.
    """
    done = threading.Event()

    def run() -> None:
        try:
            target()
        finally:
            done.set()

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    keep(done)
    return thread


def keep_until(futures: Iterable[Future]) -> None:
    """Hold the CPU until every future still running has finished.

    For the pulls a request stopped waiting on at its budget: between requests
    they crawl, and the next reader waits on them all over again.
    """
    pending = [future for future in futures if not future.done()]
    if not pending:
        return
    done = threading.Event()
    left = len(pending)
    lock = threading.Lock()

    def settle(_: Future) -> None:
        nonlocal left
        with lock:
            left -= 1
            if left == 0:
                done.set()

    for future in pending:
        future.add_done_callback(settle)
    keep(done)


def _hold(url: str) -> None:
    global _active
    import httpx

    while True:
        try:
            # Anything but the route's own 204 (a redirect, a 404 from another
            # instance) ends the hold rather than asking again at once.
            httpx.post(
                url,
                headers={"X-Hold": _TOKEN},
                timeout=httpx.Timeout(HOLD_S + 15, connect=10),
            ).raise_for_status()
        except Exception as exc:  # noqa: BLE001 — a lost hold is a slow refresh
            obs.warn(
                "cache.hold_failed", error_type=type(exc).__name__, error=str(exc)[:300]
            )
            with _lock:
                _pending.clear()
                _active = False
            return
        with _lock:
            # A refresh that started while the hold was letting go must not
            # find `_active` set and nobody holding.
            for done in [e for e in _pending if e.is_set()]:
                _pending.discard(done)
            if not _pending:
                _active = False
                return


def _waiting() -> bool:
    with _lock:
        return any(not e.is_set() for e in _pending)


def _wait(timeout: float = HOLD_S) -> None:
    """Block until nothing is pending, or `timeout` passes."""
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        with _lock:
            waiting = [e for e in _pending if not e.is_set()]
        if not waiting:
            return
        waiting[0].wait(min(left, 5.0))


async def _wait_async(timeout: float = HOLD_S) -> None:
    """`_wait` for the event loop: polled by the second, so the hold — open
    for minutes — keeps no thread of the pool every other request runs on."""
    deadline = time.monotonic() + timeout
    while _waiting() and (left := deadline - time.monotonic()) > 0:
        await asyncio.sleep(min(left, 1.0))


router = APIRouter(include_in_schema=False)


@router.post("/hold", name="cpu_hold", status_code=status.HTTP_204_NO_CONTENT)
async def hold(x_hold: str = Header(default="")) -> Response:
    """Stay open while a refresh runs — this process calling itself. 404 for
    anything but its own token."""
    if not secrets.compare_digest(x_hold, _TOKEN):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _wait_async()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _reset() -> None:
    """Forget every pending refresh. Tests only."""
    global _active
    with _lock:
        _pending.clear()
        _active = False
