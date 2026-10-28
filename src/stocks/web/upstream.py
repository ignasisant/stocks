"""A local dashboard that reads and writes the production account.

`data/users/` on a laptop is a copy that stopped the day it was made: the
production book, chat threads, memories and settings live in the bucket that
only the deployed container syncs (`stocks.storage`). Pointing a laptop at
that bucket would make it a second writer, and the container trusts its own
copy once it has restored it — each would overwrite the other's newer files.

So the local server does not hold the account at all. It forwards `/api` and
the logo mirror to production, cookie and all, and serves only the document
and the frontend's source. Sign-in stays local: both servers sign the session
cookie with the same `[auth] cookie_secret`, so the one minted here is the one
production reads, and the account answering is the account signed in.

Only while the backend matches what production runs: a local Python change
would be invisible behind production's API, so any difference under `src/`
from the commit production's `/status` reports keeps the API local. The check
runs when the worker starts, and `dashboard --reload` restarts the worker on
every Python edit — editing the backend switches to local, reverting it
switches back.

`STOCKS_API_UPSTREAM` selects it, and only `stocks dashboard` sets it: `auto`
(the check above), `prod`, `local`, or a base URL. Unset — every deploy, every
test — nothing here runs.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

import httpx

from stocks.config import PROJECT_ROOT

ENV = "STOCKS_API_UPSTREAM"
PROD_URL = os.environ.get(
    "STOCKS_PROD_URL", "https://topstocks-613330607457.europe-west1.run.app"
).rstrip("/")
# What production serves for the account; everything else stays local.
PREFIXES = ("/api/", "/app/static/")
# The bundle is frontend, committed under src/ only so a deploy needs no Node.
_BACKEND = ("src", ":(exclude)src/stocks/web/static/app")
# Per-connection headers, meaningful to one hop only (RFC 9110 §7.6.1).
_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
})
_BODILESS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Choice:
    base: str  # "" = the local API
    why: str


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(PROJECT_ROOT), *args],
                          capture_output=True, text=True, timeout=20)


def prod_commit(base: str = PROD_URL) -> str | None:
    """The commit production says it runs, None when it cannot be asked."""
    try:
        commit = httpx.get(f"{base}/status", timeout=5).json().get("commit")
    except (httpx.HTTPError, ValueError):
        return None
    return commit if isinstance(commit, str) and commit != "dev" else None


def backend_changes(commit: str) -> list[str] | None:
    """Files under the backend that differ from `commit`, untracked included;
    None when this checkout does not have that commit (`git fetch` first)."""
    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode:
        return None
    changed = _git("diff", "--name-only", commit, "--", *_BACKEND).stdout.split()
    added = _git("ls-files", "--others", "--exclude-standard", "--", *_BACKEND)
    return sorted({*changed, *added.stdout.split()})


def resolve(setting: str) -> Choice:
    setting = setting.strip()
    if setting in ("", "local"):
        return Choice("", "local API")
    if setting != "auto":
        base = PROD_URL if setting == "prod" else setting.rstrip("/")
        return Choice(base, f"API from {base} (forced)")
    commit = prod_commit()
    if commit is None:
        return Choice("", "local API: production's /status did not answer")
    changes = backend_changes(commit)
    if changes is None:
        return Choice("", f"local API: production runs {commit[:8]}, "
                          "not in this checkout (git fetch)")
    if changes:
        listed = ", ".join(changes[:3]) + (" …" if len(changes) > 3 else "")
        return Choice("", f"local API: backend differs from production's "
                          f"{commit[:8]} ({len(changes)} files: {listed})")
    return Choice(PROD_URL, f"API from production ({commit[:8]}): backend "
                            "unchanged, so this is your production account")


_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    """One pooled client; no read timeout, because the chat streams."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30, read=None))
    return _client


async def _body(receive) -> bytes:
    parts = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        parts.append(message.get("body", b""))
        if not message.get("more_body"):
            break
    return b"".join(parts)


async def forward(base: str, scope, receive, send) -> None:
    """Send this request to `base` and stream its answer back untouched —
    still compressed, the chat's events as they arrive."""
    method = scope["method"]
    query = scope.get("query_string", b"").decode("latin-1")
    url = f"{base}{scope['path']}" + (f"?{query}" if query else "")
    headers = [(k, v) for k, v in scope["headers"]
               if k.decode("latin-1").lower() not in _HOP]
    content = None if method in _BODILESS else await _body(receive)
    try:
        response = await client().send(
            client().build_request(method, url, headers=headers, content=content),
            stream=True,
        )
    except httpx.HTTPError as error:
        body = json.dumps({"error": {"code": "upstream_unreachable",
                                     "message": f"{base}: {type(error).__name__}"}})
        await send({"type": "http.response.start", "status": 502,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body.encode()})
        return
    try:
        await send({
            "type": "http.response.start",
            "status": response.status_code,
            "headers": [(k, v) for k, v in response.headers.raw
                        if k.decode("latin-1").lower() not in _HOP - {"content-length"}],
        })
        async for chunk in response.aiter_raw():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b""})
    finally:
        await response.aclose()


class Upstream:
    """ASGI middleware: the account's paths go to `base`, the rest stay here."""

    def __init__(self, app, base: str) -> None:
        self.app = app
        self.base = base

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(PREFIXES):
            await forward(self.base, scope, receive, send)
        else:
            await self.app(scope, receive, send)


CHOICE = resolve(os.environ.get(ENV, ""))
BASE = CHOICE.base
if os.environ.get(ENV):
    print(CHOICE.why, flush=True)
