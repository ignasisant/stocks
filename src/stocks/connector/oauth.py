"""The authorization server: how an MCP client earns a token for one account.

The SDK ships the protocol — `/authorize`, `/token`, `/register`, `/revoke`
and their validation — and asks for a provider behind it. This is that
provider, plus the routes, assembled by hand rather than through
`create_auth_routes` for two reasons: client secrets are stored hashed, so the
token and revocation endpoints need our authenticator (`clients.Authenticator`)
instead of the SDK's plain compare, and registration sits behind a per-address
limit, because it is a write anybody on the internet can make.

The flow, end to end:

1. `/authorize` validates the client and redirect URI (SDK), then
   `Provider.authorize` seals the request and sends the browser to the consent
   page (`consent.py`), which signs in first if it has to.
2. "Allow" there mints a one-time code (`mint_code`) and returns to the client.
3. `/token` trades the code — PKCE checked by the SDK — for a grant in
   `store`; refresh tokens rotate, and reuse of a spent one ends the grant.

Codes live in memory only, for five minutes. Sealing them would put the
account's email in a URL (itsdangerous signs, it does not encrypt), and the
service runs as one container, so there is nowhere else a code could be
redeemed. A deploy in the middle of a sign-in loses it; the user clicks again.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import (
    MetadataHandler,
    ProtectedResourceMetadataHandler,
)
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.routes import (
    AUTHORIZATION_PATH,
    REGISTRATION_PATH,
    REVOCATION_PATH,
    TOKEN_PATH,
    build_metadata,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    RequestBodyLimitMiddleware,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from pydantic import AnyUrl
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, request_response
from starlette.types import ASGIApp

from stocks import obs, session
from stocks.connector import clients, store
from stocks.web import ratelimit

MCP_PATH = "/mcp"
CONSENT_PATH = "/oauth/consent"
METADATA_PATH = "/.well-known/oauth-authorization-server"
RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"

#: Every path the connector answers, for the server's route table and gates.
PATHS = (
    METADATA_PATH,
    RESOURCE_METADATA_PATH,
    RESOURCE_METADATA_PATH + MCP_PATH,
    AUTHORIZATION_PATH,
    TOKEN_PATH,
    REGISTRATION_PATH,
    REVOCATION_PATH,
    CONSENT_PATH,
    MCP_PATH,
)

#: The salt the sealed authorization request travels under (`session.seal`).
REQUEST_PURPOSE = "mcp.authorize"
REQUEST_MAX_AGE = 600

CODE_TTL = 300
#: Redeemed codes are remembered a while longer, so a second redemption — a
#: copied code, RFC 6749 §4.1.2 — can end the grant the first one made.
SPENT_CODE_TTL = 2 * CODE_TTL

#: Dynamic registrations per address per hour. Real clients register once per
#: install; anything faster is filling the ledger.
REGISTER_MAX = 10
REGISTER_WINDOW_S = 3600

MAX_STATE = 512

_AUTH_METHODS = ["none", "client_secret_post", "client_secret_basic"]


# ------------------------------------------------------------------- codes


@dataclass(frozen=True)
class _Spent:
    grant: str
    email: str
    expires: float


_codes_lock = threading.Lock()
_codes: dict[str, AuthorizationCode] = {}
_spent: dict[str, _Spent] = {}


def _sweep(now: float) -> None:
    for h in [h for h, c in _codes.items() if c.expires_at <= now]:
        del _codes[h]
    for h in [h for h, s in _spent.items() if s.expires <= now]:
        del _spent[h]


def forget_codes() -> None:
    """Drop every pending and redeemed code (tests)."""
    with _codes_lock:
        _codes.clear()
        _spent.clear()


def seal_request(client_id: str, params: AuthorizationParams) -> str | None:
    """The authorization request, signed for the trip through consent."""
    return session.seal(REQUEST_PURPOSE, {
        "client_id": client_id,
        "redirect_uri": str(params.redirect_uri),
        "explicit": params.redirect_uri_provided_explicitly,
        "state": params.state,
        "challenge": params.code_challenge,
    })


def open_request(raw: str) -> dict | None:
    """A request `seal_request` signed in the last ten minutes, or None."""
    req = session.unseal(REQUEST_PURPOSE, raw, REQUEST_MAX_AGE)
    keys = ("client_id", "redirect_uri", "challenge")
    if not req or not all(isinstance(req.get(k), str) and req[k] for k in keys):
        return None
    return req


def mint_code(email: str, req: dict, *, resource: str) -> str:
    """A one-time code for `req` on behalf of `email` — the "Allow"."""
    code = secrets.token_urlsafe(32)
    now = time.time()
    pending = AuthorizationCode(
        code=code,
        scopes=[store.SCOPE],
        expires_at=now + CODE_TTL,
        client_id=req["client_id"],
        code_challenge=req["challenge"],
        redirect_uri=AnyUrl(req["redirect_uri"]),
        redirect_uri_provided_explicitly=bool(req.get("explicit")),
        resource=resource,
        subject=email,
    )
    with _codes_lock:
        _sweep(now)
        _codes[store.digest(code)] = pending
    return code


# ---------------------------------------------------------------- provider


class Provider:
    """`OAuthAuthorizationServerProvider` over `clients` and `store`.

    One per connector lifespan, bound to the public origin: that origin is the
    issuer, and `origin + /mcp` is the only resource a token is ever for.
    """

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.resource = origin + MCP_PATH

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await run_in_threadpool(clients.register, client_info)

    async def authorize(self, client: OAuthClientInformationFull,
                        params: AuthorizationParams) -> str:
        # RFC 8707: a client asking for a token to some other server is asking
        # the wrong authorization server. Absent is fine — there is only one.
        if params.resource and params.resource.rstrip("/") != self.resource:
            raise AuthorizeError("invalid_target", "unknown resource")
        # The request rides a URL through sign-in and back (consent, then the
        # login's own sealed `next`), which a browser caps; real states are
        # tens of characters.
        if params.state and len(params.state) > MAX_STATE:
            raise AuthorizeError("invalid_request", "state is too long")
        sealed = seal_request(client.client_id or "", params)
        if sealed is None:
            raise AuthorizeError("server_error", "authorization is unavailable")
        return f"{self.origin}{CONSENT_PATH}?req={quote(sealed, safe='')}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        h = store.digest(authorization_code)
        with _codes_lock:
            _sweep(time.time())
            pending = _codes.pop(h, None)
            replay = _spent.pop(h, None) if pending is None else None
        if replay is not None:
            obs.warn("mcp.code_reuse", grant=replay.grant)
            await run_in_threadpool(
                store.ledger().revoke, replay.grant, email=replay.email, via="code_reuse"
            )
        return pending

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        email = authorization_code.subject
        if not email or not client.client_id:
            raise TokenError("invalid_grant", "authorization code does not exist")
        issued = await run_in_threadpool(
            store.ledger().issue,
            email=email,
            client_id=client.client_id,
            redirect_host=clients.redirect_host(str(authorization_code.redirect_uri)),
            **clients.describe(client),
        )
        with _codes_lock:
            _spent[store.digest(authorization_code.code)] = _Spent(
                issued.grant, email, time.time() + SPENT_CODE_TTL
            )
        return _token(issued)

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        holder = await run_in_threadpool(store.ledger().refresh_holder, refresh_token)
        if holder is None or holder.client_id != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=holder.client_id,
            scopes=list(holder.scopes),
            expires_at=holder.expires_at,
            resource=self.resource,
            subject=holder.email,
        )

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        issued = await run_in_threadpool(store.ledger().rotate, refresh_token.token)
        if issued is None:
            raise TokenError("invalid_grant", "refresh token is no longer valid")
        return _token(issued)

    async def load_access_token(self, token: str) -> AccessToken | None:
        holder = await run_in_threadpool(store.ledger().holder, token)
        if holder is None:
            return None
        return AccessToken(
            token=token,
            client_id=holder.client_id,
            scopes=list(holder.scopes),
            expires_at=holder.expires_at,
            resource=self.resource,
            subject=holder.email,
            claims={"grant": holder.grant},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await run_in_threadpool(store.ledger().revoke_token, token.token)

    async def exchange_identity_assertion(self, client, params) -> OAuthToken:
        # Never advertised, and refused at registration; here for the protocol.
        raise TokenError("unsupported_grant_type", "not supported")


def _token(issued: store.Issued) -> OAuthToken:
    return OAuthToken(
        access_token=issued.access,
        expires_in=issued.expires_in,
        scope=" ".join(issued.scopes),
        refresh_token=issued.refresh,
    )


class Verifier:
    """`TokenVerifier` for the resource server: the same store, read-only."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.provider.load_access_token(token)


# ------------------------------------------------------------------ routes


def metadata(origin: str) -> OAuthMetadata:
    """RFC 8414 metadata: the SDK's, plus what this server does beyond it.

    Rebuilt from a dict so the issuer keeps its exact spelling — a bare
    origin, no trailing slash — which is what clients compare the `iss` on
    the redirect against (RFC 9207).
    """
    base = build_metadata(
        AnyUrl(origin),  # ty: ignore[invalid-argument-type]
        None,
        ClientRegistrationOptions(enabled=True),
        RevocationOptions(enabled=True),
    )
    return OAuthMetadata.model_validate({
        **base.model_dump(mode="json", exclude_none=True),
        "issuer": origin,
        "scopes_supported": [store.SCOPE],
        "token_endpoint_auth_methods_supported": _AUTH_METHODS,
        "revocation_endpoint_auth_methods_supported": _AUTH_METHODS,
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
    })


def _cors(app: ASGIApp, methods: list[str]) -> ASGIApp:
    # Browser-based clients (the MCP Inspector) call these cross-origin. Same
    # wrapper the SDK uses; theirs is private.
    return CORSMiddleware(app=app, allow_origins="*", allow_methods=methods,
                          allow_headers=[MCP_PROTOCOL_VERSION_HEADER])


def _limited(app: ASGIApp) -> ASGIApp:
    return RequestBodyLimitMiddleware(app, DEFAULT_MAX_REQUEST_BODY_SIZE)


class _Revocation(RevocationHandler):
    """RFC 7009 revocation that a public client can actually call.

    The SDK's form model declares `client_secret: str | None` without a
    default, which pydantic reads as required: every client registered with
    `token_endpoint_auth_method: none` — all of ours — gets a 400 for leaving
    out a secret it does not have. Same steps otherwise: authenticate the
    client, find the token, revoke it only if it is that client's, answer 200
    whatever happened (the RFC's "no oracle").
    """

    async def handle(self, request: Request) -> Response:
        try:
            client = await self.client_authenticator.authenticate_request(request)
        except AuthenticationError as exc:
            return JSONResponse(
                {"error": "unauthorized_client", "error_description": exc.message},
                status_code=401,
            )
        token = (await request.form()).get("token")
        if not isinstance(token, str) or not token:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "token is required"},
                status_code=400,
            )
        found = await self.provider.load_access_token(token)
        if found is None:
            found = await self.provider.load_refresh_token(client, token)
        if found is not None and found.client_id == client.client_id:
            await self.provider.revoke_token(found)
        return Response(
            status_code=200, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
        )


def _register_endpoint(handler: RegistrationHandler):
    async def register(request: Request) -> Response:
        key = f"mcp-register::{ratelimit.client_ip(request)}"
        if not ratelimit.allow(key, max_events=REGISTER_MAX, window_s=REGISTER_WINDOW_S):
            obs.warn("mcp.register_throttled")
            return JSONResponse(
                {"error": "invalid_client_metadata",
                 "error_description": "too many registrations, try again later"},
                status_code=429,
                headers={"Retry-After": str(max(1, ratelimit.retry_after(
                    key, window_s=REGISTER_WINDOW_S)))},
            )
        return await handler.handle(request)
    return register


def routes(provider: Provider) -> list[Route]:
    """The authorization server's endpoints, plus the root resource metadata.

    The resource server's own `/.well-known/oauth-protected-resource/mcp` comes
    from the SDK with `/mcp`; the bare path is added for clients that look
    there before reading `WWW-Authenticate`.
    """
    origin = provider.origin
    authenticator = clients.Authenticator(provider)
    resource_metadata = ProtectedResourceMetadata.model_validate({
        "resource": provider.resource,
        "authorization_servers": [origin],
        "scopes_supported": [store.SCOPE],
        "resource_name": "TopStocks",
    })
    registration = RegistrationHandler(
        provider, options=ClientRegistrationOptions(
            enabled=True, default_scopes=[store.SCOPE]),
    )
    get = ["GET", "OPTIONS"]
    post = ["POST", "OPTIONS"]
    return [
        Route(METADATA_PATH, methods=get, endpoint=_cors(
            request_response(MetadataHandler(metadata(origin)).handle), get)),
        Route(RESOURCE_METADATA_PATH, methods=get, endpoint=_cors(
            request_response(ProtectedResourceMetadataHandler(resource_metadata).handle),
            get)),
        Route(AUTHORIZATION_PATH, methods=["GET", "POST"], endpoint=_limited(
            request_response(AuthorizationHandler(provider).handle))),
        Route(TOKEN_PATH, methods=post, endpoint=_cors(_limited(
            request_response(TokenHandler(provider, authenticator).handle)), post)),
        Route(REGISTRATION_PATH, methods=post, endpoint=_cors(_limited(
            request_response(_register_endpoint(registration))), post)),
        Route(REVOCATION_PATH, methods=post, endpoint=_cors(_limited(
            request_response(_Revocation(provider, authenticator).handle)), post)),
    ]
