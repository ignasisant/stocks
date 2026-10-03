"""Which apps may ask for a grant, and how each one proves who it is.

Two doors, both open to anyone, because an MCP client is whatever the user
pastes our URL into and none of them is known in advance:

- **Dynamic registration** (RFC 7591, `/register`): the client posts its
  metadata and gets an id. Its `client_name` is self-asserted — anybody can
  register as "Claude" — so the consent screen labels these unverified and
  shows the host the code will be sent to, which is the part that cannot lie.
- **Client ID metadata documents** (CIMD): the client id *is* an https URL and
  the metadata lives there. The domain vouches for it, so these need no
  storage at all; the price is that this server fetches a URL a stranger chose,
  which is why `_fetch_document` is as narrow as it is.

Either way a redirect URI is https, or http on the loopback interface for a
desktop client (RFC 8252 §7.3, port ignored because native apps pick a free
one per run). Custom schemes are refused: on the web any app can claim one.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import ipaddress
import json
import socket
import time
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from mcp.server.auth.middleware.client_auth import (
    AuthenticationError,
    ClientAuthenticator,
)
from mcp.server.auth.provider import RegistrationError
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl, ValidationError
from starlette.requests import Request

from stocks import obs
from stocks.connector import store

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "[::1]", "::1", "localhost"})
_AUTH_METHODS = frozenset({"none", "client_secret_post", "client_secret_basic"})
_GRANTS = ("authorization_code", "refresh_token")

DOC_MAX_BYTES = 16 * 1024
DOC_TIMEOUT_S = 5.0
DOC_TTL_S = 3600
DOC_FAIL_TTL_S = 300
_DOC_CACHE_MAX = 256


def _is_loopback(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS


def redirect_allowed(url: str) -> bool:
    """https anywhere, or http on loopback; no fragment, no credentials."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not parts.hostname:
        return False
    return parts.scheme == "https" or _is_loopback(url)


def redirect_host(url: str) -> str:
    """The host a code is sent to: what the consent screen shows."""
    return (urlsplit(url).hostname or "").lower()


class Client(OAuthClientInformationFull):
    """The SDK's client record with this server's scope and redirect rules.

    `client_secret` holds the secret's sha256 for a confidential client; the
    `Authenticator` below is the only thing that compares it.
    """

    kind: str = "dcr"  # "dcr" | "cimd"

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        # One scope exists. Asking for others is not an error worth failing a
        # connection over — clients send "openid" or nothing — so the answer
        # is always the one there is.
        del requested_scope
        return [store.SCOPE]

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        registered = [str(u) for u in self.redirect_uris or []]
        if redirect_uri is None:
            if len(registered) == 1:
                return AnyUrl(registered[0])
            raise InvalidRedirectUriError("redirect_uri is required")
        asked = str(redirect_uri)
        if not redirect_allowed(asked):
            raise InvalidRedirectUriError("redirect_uri must be https or loopback")
        if asked in registered:
            return redirect_uri
        if _is_loopback(asked) and any(_same_but_port(asked, r) for r in registered):
            return redirect_uri
        raise InvalidRedirectUriError("redirect_uri is not registered for this client")


def _same_but_port(a: str, b: str) -> bool:
    pa, pb = urlsplit(a), urlsplit(b)
    return (
        _is_loopback(b)
        and pa.hostname == pb.hostname
        and pa.path == pb.path
        and pa.query == pb.query
    )


def label(client: OAuthClientInformationFull) -> str:
    """The client's name as the consent screen and Profile print it."""
    name = (client.client_name or "").strip()
    if isinstance(client, Client) and client.kind == "cimd":
        return name[:80] or redirect_host(client.client_id)
    return name[:80] or "MCP client"


# ------------------------------------------------------------- registration


def register(info: OAuthClientInformationFull) -> None:
    """Admit one dynamic registration, or raise `RegistrationError`.

    The SDK has already checked grant and response types; this is the policy
    on top. `info` is the very object the SDK answers with, so the scope set
    here is what the client is told it got.
    """
    uris = [str(u) for u in info.redirect_uris or []]
    if not uris or not all(redirect_allowed(u) for u in uris):
        raise RegistrationError(
            "invalid_redirect_uri", "redirect_uris must be https or loopback http"
        )
    if len(uris) > 10:
        raise RegistrationError("invalid_redirect_uri", "too many redirect_uris")
    method = info.token_endpoint_auth_method or "client_secret_post"
    if method not in _AUTH_METHODS:
        raise RegistrationError(
            "invalid_client_metadata",
            f"token_endpoint_auth_method {method!r} is not supported",
        )
    info.scope = store.SCOPE
    info.grant_types = [g for g in info.grant_types if g in _GRANTS]
    if info.client_name:
        info.client_name = info.client_name.strip()[:80]
    record = info.model_dump(mode="json", exclude_none=True)
    record.pop("client_secret", None)
    if info.client_secret:
        record["secret_hash"] = store.digest(info.client_secret)
    if not store.ledger().register(info.client_id, record):
        raise RegistrationError(
            "invalid_client_metadata", "registration is closed for now"
        )
    obs.event("mcp.register", auth_method=method)


def _registered(client_id: str) -> Client | None:
    record = store.ledger().client(client_id)
    if record is None:
        return None
    secret = record.pop("secret_hash", None)
    record.pop("created", None)
    try:
        return Client.model_validate({**record, "client_secret": secret, "kind": "dcr"})
    except ValidationError:
        return None


# ----------------------------------------------------- metadata documents


class DocumentRefused(Exception):
    """A client id URL that does not lead to a usable metadata document."""


def document_url_allowed(url: str) -> bool:
    """CIMD client ids: https, default port, a real path, nothing else."""
    if len(url) > 512:
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and port in (None, 443)
        and parts.path not in ("", "/")
        and "/./" not in parts.path + "/"
        and "/../" not in parts.path + "/"
        and not parts.fragment
        and not parts.username
        and not parts.password
    )


async def _public_address(host: str) -> str:
    """One address for `host`, refusing if any of them is not public.

    All of them, not just the one used: a name that resolves to a public and a
    private address is a rebinding setup, not a misconfiguration.
    """
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, 443, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise DocumentRefused("unresolvable") from exc
    addresses = []
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise DocumentRefused("not a public address")
        addresses.append(str(ip))
    if not addresses:
        raise DocumentRefused("unresolvable")
    return addresses[0]


async def _fetch_document(url: str) -> bytes:
    """GET a client metadata document from the public internet, narrowly.

    Connects to the address `_public_address` vetted — not to whatever the
    name resolves to a moment later — while still checking the certificate
    against the name (SNI). No redirects, no cookies, 5 s, 16 KB.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    ip = await _public_address(host)
    netloc = f"[{ip}]" if ":" in ip else ip
    target = parts._replace(netloc=netloc).geturl()
    async with httpx.AsyncClient(
        timeout=DOC_TIMEOUT_S, follow_redirects=False, trust_env=False
    ) as http:
        req = http.build_request(
            "GET",
            target,
            headers={"Host": host, "Accept": "application/json"},
            extensions={"sni_hostname": host},
        )
        resp = await http.send(req, stream=True)
        try:
            if resp.status_code != 200:
                raise DocumentRefused(f"status {resp.status_code}")
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > DOC_MAX_BYTES:
                    raise DocumentRefused("too large")
            return bytes(body)
        finally:
            await resp.aclose()


def _from_document(url: str, raw: bytes) -> Client:
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise DocumentRefused("not JSON") from exc
    if not isinstance(doc, dict) or doc.get("client_id") != url:
        raise DocumentRefused("client_id does not match its URL")
    if "client_secret" in doc or "client_secret_expires_at" in doc:
        raise DocumentRefused("a metadata document cannot carry a secret")
    if doc.get("token_endpoint_auth_method", "none") != "none":
        raise DocumentRefused("only public clients are supported")
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > 10:
        raise DocumentRefused("redirect_uris missing")
    if not all(isinstance(u, str) and redirect_allowed(u) for u in uris):
        raise DocumentRefused("redirect_uris must be https or loopback http")
    grants = doc.get("grant_types") or list(_GRANTS)
    try:
        return Client.model_validate({
            "client_id": url,
            "client_name": str(doc.get("client_name") or "")[:80] or None,
            "redirect_uris": uris,
            "token_endpoint_auth_method": "none",
            "grant_types": [g for g in grants if g in _GRANTS],
            "scope": store.SCOPE,
            "kind": "cimd",
        })
    except ValidationError as exc:
        raise DocumentRefused("invalid metadata") from exc


_docs: dict[str, tuple[float, Client | None]] = {}


async def _documented(url: str) -> Client | None:
    """The client a metadata document URL describes, cached either way.

    Failures are cached too (for less long), so a client id that does not
    resolve costs one fetch per few minutes rather than one per request. No
    lock: two first requests racing fetch twice, which is harmless, and an
    asyncio lock would be bound to whichever event loop touched it first.
    """
    if not document_url_allowed(url):
        return None
    now = time.monotonic()
    hit = _docs.get(url)
    if hit is not None and hit[0] > now:
        return hit[1]
    try:
        client: Client | None = _from_document(url, await _fetch_document(url))
        ttl = DOC_TTL_S
    except (DocumentRefused, httpx.HTTPError) as exc:
        reason = str(exc)[:80] if isinstance(exc, DocumentRefused) else type(exc).__name__
        obs.warn("mcp.cimd_refused", host=redirect_host(url), reason=reason)
        client, ttl = None, DOC_FAIL_TTL_S
    if len(_docs) >= _DOC_CACHE_MAX:
        _docs.clear()
    _docs[url] = (now + ttl, client)
    return client


def forget_documents() -> None:
    """Drop every cached metadata document (tests)."""
    _docs.clear()


async def get(client_id: str) -> Client | None:
    """A client by id: a metadata document URL, or a registration."""
    if client_id.startswith("https://"):
        return await _documented(client_id)
    if len(client_id) > 64:
        return None
    return _registered(client_id)


# ------------------------------------------------------------ authentication


class Authenticator(ClientAuthenticator):
    """The SDK's client authentication, against a stored secret *hash*.

    Same rules — the registered method decides where the secret travels, a
    secret-method client without a stored secret is refused — but the
    presented secret is hashed before the constant-time compare, because the
    plain one is never stored (see `store`).
    """

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        form = await request.form()
        client_id = form.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise AuthenticationError("Missing client_id")
        client = await self.provider.get_client(client_id)
        if client is None:
            raise AuthenticationError("Invalid client_id")
        method = client.token_endpoint_auth_method or "client_secret_post"
        presented: str | None = None
        if method == "client_secret_basic":
            header = request.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                raise AuthenticationError("Missing Basic authentication")
            try:
                pair = base64.b64decode(header[6:]).decode()
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise AuthenticationError("Invalid Basic authentication") from exc
            basic_id, sep, secret = pair.partition(":")
            if not sep or unquote(basic_id) != client_id:
                raise AuthenticationError("Invalid Basic authentication")
            presented = unquote(secret)
        elif method == "client_secret_post":
            secret = form.get("client_secret")
            presented = secret if isinstance(secret, str) else None
        elif method != "none":
            raise AuthenticationError("Unsupported authentication method")
        if method == "none":
            if client.client_secret:
                raise AuthenticationError("Client secret is required")
            return client
        if not client.client_secret or not presented:
            raise AuthenticationError("Client secret is required")
        if not hmac.compare_digest(client.client_secret, store.digest(presented)):
            raise AuthenticationError("Invalid client_secret")
        return client


def describe(client: Any) -> dict[str, str]:
    """Client facts a grant keeps for Profile, without any secret."""
    kind = client.kind if isinstance(client, Client) else "dcr"
    return {"client_name": label(client), "client_kind": kind}
