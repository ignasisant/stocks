"""The ASGI application, and where it hangs off the server.

Mounted at `/api` by `stocks.web.server`, so every path below is reachable as
`/api/v1/…` on the same hostname the app answers on. Versioned from the first
commit: this is meant to outlive the Streamlit front end, and a client pinned
to `/api/v1` must keep working while a `/api/v2` is being shaped beside it.

The token gate is declared on the router that carries the data, not per route,
so a new endpoint is authenticated by default. `/health` sits outside it on
purpose — a probe has no token, and the answer tells nobody anything.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.error import URLError

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from yfinance.exceptions import YFRateLimitError

from stocks import obs
from stocks.api import guest, guestbook, security
from stocks.api.routes import (
    account,
    bank,
    chat,
    chat_attach,
    chat_voice,
    comparables,
    design,
    earnings,
    feedback,
    glance,
    guide,
    health,
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

Read-only but for one route: `POST /v1/search/recent` appends to the account's
recent-search list, which is what keeps the search box's history alive for a
client that is not the Streamlit app. Nothing else writes — imports,
preferences and watchlist edits still go through the app, so this API cannot
leave a ledger in a state the UI did not produce.
"""

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Boot work. Today: make the shared guest book exist.

    At boot rather than on the first anonymous request, so that no request path
    can write the guest directory — see `api.guestbook`.
    """
    guestbook.provision()
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


# ------------------------------------------------- when the upstream says no
# Yahoo throttles datacenter egress IPs routinely, and a plain urllib fetcher
# dies on a dropped network. Both are ordinary weather, not a fault in this
# service, and neither is something the caller can fix by changing its request
# — so they are 503 with a reason the client can branch on, never a 500.
#
# This mirrors what the pages do: `web/notices.data_toast` classifies the same
# two exceptions and the section degrades in place. The classification lives
# in both because the shapes differ (a toast versus a status code), but the
# two kinds must not: a client that learns "rate_limited" from here reads the
# same word the app prints.

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
_private.include_router(comparables.router)
_private.include_router(search.router)
_private.include_router(sector.router)
_private.include_router(earnings.router)
_private.include_router(pulse.router)
_private.include_router(prefs.router)
_private.include_router(watchlist_edit.router)
_private.include_router(import_statement.router)
_private.include_router(glance.router)
_private.include_router(guide.router)
_private.include_router(reference.router)
_private.include_router(chat.router)
_private.include_router(chat_attach.router)
_private.include_router(chat_voice.router)
_private.include_router(onboarding.router)
_private.include_router(notify.router)
_private.include_router(feedback.router)
_private.include_router(account.router)
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
