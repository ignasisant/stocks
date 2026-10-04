"""The ASGI application, and where it hangs off the server.

Mounted at `/api` by `stocks.web.server`, so every path below is reachable as
`/api/v1/…` on the same hostname the app answers on. Versioned from the first
commit: a client pinned to `/api/v1` must keep working while a `/api/v2` is
being shaped beside it.

The token gate is declared on the router that carries the data, not per route,
so a new endpoint is authenticated by default. `/health` sits outside it on
purpose — a probe has no token, and the answer tells nobody anything.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.error import URLError

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from yfinance.exceptions import YFRateLimitError

from stocks import accounts, memstat, obs
from stocks.api import cache, guest, guestbook, security, warm
from stocks.api.routes import (
    account,
    bank,
    brief,
    chat,
    chat_attach,
    chat_memory,
    chat_voice,
    comparables,
    connections,
    crypto,
    design,
    earnings,
    feedback,
    glance,
    guide,
    health,
    home,
    i18n,
    import_statement,
    market,
    me,
    notify,
    onboarding,
    portfolio,
    prefs,
    pulse,
    reference,
    search,
    sector,
    ticker,
    watchlist,
    watchlist_edit,
)
from stocks.api.security import Caller, Who

MOUNT_PATH = "/api"
API_VERSION = "v1"

DESCRIPTION = """\
Read-only HTTP access to a TopStocks book: positions, totals, the ledger,
time- and money-weighted returns, the watchlist and live quotes.

Two ways in. A browser signed into the app carries the session cookie and is
read as that account — `?account=` may only repeat its own address. A headless
job sends `Authorization: Bearer <token>` (`[api] token`, or `API_TOKEN`); that
token names nobody, so it has to pass `?account=`, and any holder of it can read
every account on the deployment.

Writes take a session only. Imports, preferences, watchlist edits, the chat
and the guide all write through this API — it is the app's one way into an
account — but every route that changes state answers a bearer token 403: the
token names nobody, and a change in somebody's name has to come from their own
signed-in browser.
"""


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Boot work: logging, then the shared guest book.

    The guest book at boot rather than on the first anonymous request, so
    that no request path can write the guest directory — see `api.guestbook`.
    """
    # At boot: without it every event goes out through logging's last resort —
    # bare text, fields lost, yfinance's misses still at ERROR.
    obs.setup()
    guestbook.provision()
    # The price memos for the accounts seen lately, on a thread of its own,
    # given the startup window to run in — see `api.warm`. Off unless the
    # deploy says otherwise.
    warm.start()
    yield


app = FastAPI(
    title="TopStocks API",
    version=API_VERSION,
    description=DESCRIPTION,
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=_lifespan,
)


# ------------------------------------------------------ when the data is old
# A memo that answered with a salvaged entry — the source refused, the last
# good figure stood in — marks the request (`cache.STALE`), and the response
# says so in a header rather than in every schema: the shell reads it once
# and tells the reader how old the figures are, instead of passing them off
# as today's.
STALE_HEADER = "X-Data-Stale-Since"


@app.middleware("http")
async def _stale_since(request: Request, call_next):
    token = cache.STALE.set({})
    try:
        response = await call_next(request)
        since = (cache.STALE.get() or {}).get("since")
        if since is not None:
            response.headers[STALE_HEADER] = datetime.fromtimestamp(
                since, tz=UTC
            ).isoformat(timespec="seconds")
        return response
    finally:
        cache.STALE.reset(token)


# ------------------------------------------------------ whose request this is
# Every record a request writes carries its account. Without it every event —
# the import diagnostics among them — logged `user="-"`, and a "this user could
# not import" report could only be traced by IP. Here and not in a dependency: a
# sync dependency runs on a copy of the context, so what it binds is gone
# before the endpoint runs, while what is bound around `call_next` reaches the
# endpoint, its threadpool work and a streamed body alike.
LOG_USER = os.getenv("STOCKS_LOG_USER", "1") != "0"


def _log_user(request: Request) -> str:
    """The account's slug (`accounts.slug`), or what stands in for one."""
    if not LOG_USER:
        return "anon"
    try:
        who = security.visitor(request, request.headers.get("authorization", ""))
        return accounts.slug(who.email) if who.email else who.kind
    except Exception:  # noqa: BLE001 — a log field never fails a request
        return "?"


@app.middleware("http")
async def _bind_user(request: Request, call_next):
    with obs.context(user=_log_user(request)):
        return await call_next(request)


# ----------------------------------------------------- what filled the memory
# The instance has 1GiB and the platform's metric says how full it is, never
# which request filled it. A request that grows the process by more than
# `memstat.STEP_MB` says so, by path (no query, so no account), so a
# climb towards an OOM can be read back as the requests that made it. Requests
# overlap, so a step is a lead, not a verdict.
@app.middleware("http")
async def _mem_step(request: Request, call_next):
    before = memstat.rss_mb()
    if before is None:  # no /proc: not Linux, nothing to measure
        return await call_next(request)
    response = await call_next(request)

    def report() -> None:
        after = memstat.rss_mb()
        if after is None or after - before < memstat.STEP_MB:
            return
        used, limit = memstat.cgroup_mb()
        obs.warn(
            "mem.step",
            path=request.url.path,
            delta_mb=round(after - before, 1),
            rss_mb=after,
            cgroup_mb=used,
            limit_mb=limit,
        )

    # A streamed answer (the chat) does its work after the headers go out,
    # which is when `call_next` returns — so the reading waits for the body.
    body = getattr(response, "body_iterator", None)
    if body is None:
        report()
        return response

    async def measured():
        try:
            async for chunk in body:
                yield chunk
        finally:
            report()

    response.body_iterator = measured()
    return response


# ------------------------------------------------- when the upstream says no
# Yahoo throttles datacenter egress IPs routinely, and a plain urllib fetcher
# dies on a dropped network. Both are ordinary weather, not a fault in this
# service, and neither is something the caller can fix by changing its request
# — so they are 503 with a reason the client can branch on, never a 500.

_UPSTREAM = {
    "rate_limited": "the upstream data provider is rate limiting this deployment",
    "offline": "the upstream data provider could not be reached",
}


def _unavailable(request: Request, reason: str) -> JSONResponse:
    obs.warn("api.upstream_unavailable", reason=reason, path=request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": _UPSTREAM[reason], "reason": reason},
        # Advisory only, and deliberately short: `fetch.retry` has already
        # backed off by the time this is raised, so the next attempt is not
        # far away.
        headers={"Retry-After": "60"},
    )


@app.exception_handler(YFRateLimitError)
def _throttled(request: Request, exc: YFRateLimitError) -> JSONResponse:
    return _unavailable(request, "rate_limited")


@app.exception_handler(URLError)
def _unreachable(request: Request, exc: URLError) -> JSONResponse:
    return _unavailable(request, "offline")


# Open: a liveness probe carries no credentials, and the design tokens and
# translated strings are shipped files the landing already publishes in plain
# HTML — a sign-in screen needs them before anyone is signed in.
_public = APIRouter(prefix=f"/{API_VERSION}")
_public.include_router(health.router)
_public.include_router(design.router)
_public.include_router(i18n.router)


def gate(request: Request, who: Who) -> Caller:
    """The token gate, with a third answer.

    Still declared on the router that carries the data rather than per route, so
    a new endpoint is authenticated by default. A guest reaches a route only by
    being named in `guest.OPEN`, so a new endpoint is shut to a guest by default
    too — the same property, stated twice, and neither half depends on anyone
    remembering it.

    `guest.OPEN` is keyed on the OpenAPI paths, which carry the version prefix.
    This dependency is declared *on* the versioned router, so the route it is
    handed names itself relative to that router — "/market/status", not
    "/v1/market/status". Putting the prefix back is what makes the two strings
    the same string, and `test_a_guest_reads_every_route_the_list_opens` is what
    stops that reasoning from rotting.
    """
    if who.kind != "guest":
        return who
    path = getattr(request.scope.get("route"), "path", None)
    if path is not None and not path.startswith(f"/{API_VERSION}/"):
        path = f"/{API_VERSION}{path}"
    if (path, request.method) in guest.OPEN:
        return who
    security.refuse()


# Gated: everything that reads somebody's data. The dependency is on the router
# so that adding a route cannot accidentally add an open one.
_private = APIRouter(prefix=f"/{API_VERSION}", dependencies=[Depends(gate)])
_private.include_router(me.router)
_private.include_router(portfolio.router)
_private.include_router(watchlist.router)
_private.include_router(market.router)
_private.include_router(ticker.router)
_private.include_router(crypto.router)
_private.include_router(comparables.router)
_private.include_router(search.router)
_private.include_router(sector.router)
_private.include_router(earnings.router)
_private.include_router(pulse.router)
_private.include_router(prefs.router)
_private.include_router(watchlist_edit.router)
_private.include_router(import_statement.router)
_private.include_router(glance.router)
_private.include_router(home.router)
_private.include_router(guide.router)
_private.include_router(reference.router)
_private.include_router(chat.router)
_private.include_router(chat_attach.router)
_private.include_router(chat_voice.router)
_private.include_router(chat_memory.router)
_private.include_router(brief.router)
_private.include_router(onboarding.router)
_private.include_router(notify.router)
_private.include_router(feedback.router)
_private.include_router(account.router)
_private.include_router(connections.router)
_private.include_router(bank.router)

app.include_router(_public)
app.include_router(_private)


def _guest_surface_is_real() -> None:
    """Every route a guest may read exists, and every one of them is a read.

    At import rather than in a test alone: `guest.OPEN` is keyed on path
    strings, so a typo opens nothing and a *rename* silently closes a page the
    shell needs. Both should be a failed boot rather than a screen that will
    not paint.
    """
    declared = {
        (path, method.upper())
        for path, item in app.openapi()["paths"].items()
        for method in item
    }
    if missing := guest.OPEN - declared:
        raise RuntimeError(
            f"guest.OPEN names routes that do not exist: {sorted(missing)}"
        )
    if writes := {entry for entry in guest.OPEN if entry[1] != "GET"} - guest.OPEN_WRITES:
        raise RuntimeError(f"a guest may only read: {sorted(writes)}")


_guest_surface_is_real()
