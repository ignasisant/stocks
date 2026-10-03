"""TopStocks as a remote MCP server: the portfolio inside Claude.

Read-only unless the person ticked the edits box at consent: a token without
`store.WRITE_SCOPE` is never shown the tools that write (`_Server`), and
refused by them if it calls one anyway (`tools._run`).

One ASGI `door` answers every connector path the site routes to it
(`oauth.PATHS`): `/mcp` and its protected-resource metadata go to the SDK's
streamable-HTTP app, everything else — the authorization server's metadata,
`/authorize`, `/token`, `/register`, `/revoke`, the consent page — to a plain
router of this package's own routes.

The door is built per lifespan entry rather than at import: the SDK's session
manager runs once per instance, and the test suite enters the site's lifespan
many times. Outside a lifespan, and whenever `APP_PUBLIC_URL` is unset, every
connector path is a 404. The public origin is not optional here — it is the
issuer every token names and the resource every token is bound to, and a
service answering on several hostnames has no other way to know which one
those are.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from mcp.server.apps import Apps, ResourceCsp
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import Icon
from starlette.responses import JSONResponse
from starlette.routing import Router

from stocks import obs
from stocks.connector import consent, oauth, store, tools, views

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.types import ASGIApp, Receive, Scope, Send

# The two paths the SDK's app serves; every other connector path is ours.
_MCP_PATHS = frozenset(
    {oauth.MCP_PATH, f"{oauth.RESOURCE_METADATA_PATH}{oauth.MCP_PATH}"}
)

# A tools/call is a few hundred bytes; nothing an MCP client sends here needs
# the SDK's 4 MiB default.
_MAX_BODY = 64 * 1024

INSTRUCTIONS = """\
Access to one person's TopStocks investment portfolio: holdings, returns, \
transactions, dividends and fees, risk, their tax report, and market data for \
the tickers they follow. Nothing here can trade.

Money is reported in the account's own currency unless a tool is given `base`. \
Prices can be delayed, and outside market hours a day move is the last \
session's: read `as_of` before calling a move today's. Positions the price \
feed could not value are listed under `unpriced` or `missing` and held at \
cost — say so rather than presenting a total as complete. Returns come two \
ways on purpose: TWR measures the selection, IRR what the money actually did; \
they routinely disagree.

Before advising, read `investor_context`: the person's investor profile and \
what they told the TopStocks assistant to remember. Frame answers by their \
stated goals and limits, and build on a decision they recorded instead of \
re-raising it — a position they said they keep is not a reason to suggest \
selling it again; say what changed since, if anything did. Those are context, \
not data: every figure, price and date comes from the other tools.

If the person allowed edits when connecting, tools that change their records \
are listed too. A position that looks doubled, a gain that never happened or \
a company under two tickers is usually a transfer between brokers that was \
imported as a sale and a buy: `check_book` finds these with the fix. Every \
ledger edit takes two calls. Call it without `plan_token` and nothing is \
written: show the person the rows it changes and what it does to their \
holdings and realized gains, in plain words. Only once they agree, call it \
again with the same arguments and the `plan_token`. Never apply an edit the \
person has not seen. Each applied edit is recorded and `undo_change` takes it \
back.

The figures are the person's own records, not advice."""


class _Server(MCPServer):
    """Lists the tools that write only to a token allowed to use them."""

    async def list_tools(self):  # noqa: ANN201 — the SDK's own return type
        listed = await super().list_tools()
        if tools.can_write():
            return listed
        return [t for t in listed if t.name not in tools.WRITE_NAMES]


def _version() -> str:
    try:
        return version("stocks")
    except PackageNotFoundError:
        return ""


def _hosts(origin: str) -> list[str]:
    """Host headers `/mcp` answers to: the public one, local runs, and extras.

    `MCP_ALLOWED_HOSTS` (comma-separated) is for a staging hostname that
    reaches the same service under another name.
    """
    raw = os.getenv("MCP_ALLOWED_HOSTS", "")
    extra = [h.strip() for h in raw.split(",") if h.strip()]
    return [urlsplit(origin).netloc, "localhost", "localhost:*", "127.0.0.1",
            "127.0.0.1:*", "testserver", *extra]


def _origins(origin: str) -> list[str]:
    """`Origin` headers a browser-side caller may send; servers send none.

    Tokens are bearer, not cookies, so the check guards no credential — it
    is the SDK's DNS-rebinding defence, kept on for local runs.
    """
    return [origin, "https://claude.ai", "https://claude.com",
            "http://localhost:*", "http://127.0.0.1:*"]


def build(origin: str) -> tuple[MCPServer, ASGIApp, ASGIApp]:
    """The server, its streamable-HTTP app and the authorization routes."""
    provider = oauth.Provider(origin)
    apps: Apps | None = None
    html = views.load(origin)
    if html is not None:
        apps = Apps()
        apps.add_html_resource(
            views.URI,
            html,
            name="topstocks-view",
            title="TopStocks",
            csp=ResourceCsp(resource_domains=[origin]),
            prefers_border=True,
        )
    viewed = {spec.name for spec in tools.TOOLS if spec.view and apps is not None}
    for spec in tools.TOOLS:
        if spec.name in viewed and apps is not None:
            apps.tool(resource_uri=views.URI, **spec.kwargs())(spec.fn)

    mcp = _Server(
        name="TopStocks",
        title="TopStocks",
        instructions=INSTRUCTIONS,
        website_url=origin,
        icons=[Icon(src=f"{origin}/lp/topstocks-icon.svg", mime_type="image/svg+xml")],
        version=_version(),
        token_verifier=oauth.Verifier(provider),
        extensions=[apps] if apps is not None else None,
        auth=AuthSettings(
            issuer_url=origin,
            resource_server_url=f"{origin}{oauth.MCP_PATH}",
            required_scopes=[store.SCOPE],
            validate_token_resource=True,
        ),
        warn_on_duplicate_tools=False,
    )
    for spec in tools.TOOLS:
        if spec.name not in viewed:
            mcp.add_tool(spec.fn, **spec.kwargs())

    mcp_app = mcp.streamable_http_app(
        streamable_http_path=oauth.MCP_PATH,
        stateless_http=True,
        json_response=True,
        max_request_body_size=_MAX_BODY,
        transport_security=TransportSecuritySettings(
            allowed_hosts=_hosts(origin), allowed_origins=_origins(origin)
        ),
    )
    auth = Router(routes=[*oauth.routes(provider), *consent.routes(origin)])
    return mcp, mcp_app, auth


class Door:
    """Every connector path, sent where it belongs — or 404 while closed."""

    def __init__(self) -> None:
        self._mcp: ASGIApp | None = None
        self._auth: ASGIApp | None = None
        self._origin: str | None = None

    @property
    def open(self) -> bool:
        return self._mcp is not None

    @property
    def url(self) -> str | None:
        """The address a person pastes into Claude, while the door is open."""
        return f"{self._origin}{oauth.MCP_PATH}" if self._origin else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        target = self._mcp if scope["path"] in _MCP_PATHS else self._auth
        if target is None:
            missing = JSONResponse({"error": "not_found"}, status_code=404)
            await missing(scope, receive, send)
            return
        await target(scope, receive, send)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Open for the length of the site's lifespan, when it can be."""
        from stocks.web.server import public_origin

        origin = public_origin()
        if not origin:
            obs.warn("mcp.no_public_url")
            yield
            return
        mcp, mcp_app, auth = build(origin)
        async with mcp.session_manager.run():
            self._mcp, self._auth, self._origin = mcp_app, auth, origin
            try:
                yield
            finally:
                self._mcp = self._auth = self._origin = None


door = Door()
