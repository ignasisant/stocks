"""The session cookie: who a request is signed in as, and who signed it.

The other half of `stocks.accounts`. That module answers *where does this
email's data live*; this one answers *who is this request*, and like it, it
knows nothing about Streamlit — because more than one runtime asks:

* the Starlette flow that mints the cookie (`stocks.web.oidc`),
* the internal HTTP API (`stocks.api.security`), for a browser caller,
* the Streamlit pages (`stocks.web.auth`), which read it off `st.context`.

One codec, one cookie name, one place the claims are shaped. Before this, the
cookie was Streamlit's `_streamlit_user` and only `st.login()` could create
one, which meant the React shell could read a session and never start one.

Nothing here raises. Every way a request can fail to carry an identity — no
cookie, another secret, a tampered body, an expired stamp, a payload that is
not the object it should be — returns None, and they are deliberately not told
apart: a caller gets "nobody is signed in" and nothing it could probe.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from secrets import token_hex

from itsdangerous import BadSignature, URLSafeTimedSerializer

from stocks import obs
from stocks.secrets_env import secret

#: The session itself. Sibling of `web.server.APP_COOKIE` ("ts_app"), which is
#: explicitly not a login — this one is.
COOKIE = "ts_session"
MAX_AGE = 30 * 24 * 3600

#: The in-flight OIDC round trip: state, nonce and PKCE verifier, for the ten
#: minutes between leaving for Google and coming back.
FLOW_COOKIE = "ts_oidc"
FLOW_MAX_AGE = 600

LOGIN_PATH = "/auth/login"
LOGOUT_PATH = "/auth/logout"
CALLBACK_PATH = "/oauth2callback"

#: Cookies Streamlit's own `st.login()` wrote, read during the migration and
#: cleared on the way out. Both go when the grace read does.
LEGACY_COOKIE = "_streamlit_user"
LEGACY_TOKENS_COOKIE = "_streamlit_user_tokens"

#: The payload shape. A cookie stamped with a version this build does not know
#: names nobody rather than being parsed as best it can.
VERSION = 1

#: Browsers drop a cookie over ~4096 bytes, and a truncated one is worse than
#: none. We carry no tokens, so the real payload is ~500 bytes; this is the
#: guard that keeps it that way rather than a licence to grow.
_MAX_BYTES = 3500


def signing_secret() -> str:
    """The key both cookies are signed with, or "" when none is configured.

    Deliberately not memoized: it is read per request so a rotated secret takes
    effect on deploy rather than on restart, and so a test can set it through
    the environment without a cache to clear.
    """
    return secret("AUTH_COOKIE_SECRET", "auth", "cookie_secret")


def sign_in_configured() -> bool:
    """Whether this deployment can sign anybody in.

    Here rather than in `web.oidc`, which owns the flow, because the API has to
    answer the same question for `GET /me` — a front end needs to know whether
    to draw a sign-in button at all — and `stocks.api` must not import the web
    package to find out. Both read one place, so they cannot disagree.
    """
    return bool(signing_secret()) and all(
        secret(f"AUTH_{key.upper()}", "auth", key)
        for key in ("client_id", "client_secret", "redirect_uri")
    )


def _serializer(salt: str, *, legacy: bool = False) -> URLSafeTimedSerializer | None:
    """The signer for one cookie, or None when there is no secret to sign with.

    The salt is load-bearing: the session and the flow cookie share a secret,
    so without it a flow cookie could be presented as a session. SHA-256 is
    pinned for ours because itsdangerous still defaults to SHA-1.

    `legacy` drops that pin, because the cookie `st.login()` wrote was signed
    with itsdangerous' defaults and the grace read has to reproduce them
    exactly — the same secret and salt under a different digest verifies
    nothing at all.
    """
    key = signing_secret()
    if not key:
        return None
    if legacy:
        return URLSafeTimedSerializer(key, salt=salt)
    return URLSafeTimedSerializer(
        key, salt=salt, signer_kwargs={"digest_method": hashlib.sha256}
    )


def _seal(salt: str, payload: dict) -> str | None:
    """Sign `payload` as one cookie value, or None if it cannot be made safely."""
    signer = _serializer(salt)
    if signer is None:
        obs.warn("session.no_cookie_secret")
        return None
    value = signer.dumps(json.dumps(payload, separators=(",", ":")))
    if len(value) > _MAX_BYTES:
        obs.warn("session.cookie_too_large", size=len(value))
        return None
    return value


def _open(salt: str, raw: str, max_age: int, *, legacy: bool = False) -> dict | None:
    """Verify one cookie value and return its object, or None.

    Broad on purpose, and the breadth is the point. Reading the secret goes
    through Streamlit's secrets loader, which raises on a malformed
    secrets.toml — and a bad config file must degrade to "nobody is signed in",
    not 500 every request on the deployment.
    """
    signer = _serializer(salt, legacy=legacy)
    if signer is None or not raw:
        return None
    try:
        payload = json.loads(signer.loads(raw, max_age=max_age))
    except BadSignature:
        # Covers a wrong secret, a tampered body and an expired stamp
        # (SignatureExpired subclasses it). No grace period on the last one.
        return None
    except Exception:
        obs.warn("session.unreadable")
        return None
    return payload if isinstance(payload, dict) else None


def verified(value: object) -> bool:
    """Whether an `email_verified` claim is a yes — exactly, not merely truthy.

    Google sends a JSON boolean, so `bool(value)` is right today and wrong the
    first time any provider or intermediate hop renders the claim as a string:
    `"false"` is truthy in Python, and an address the provider did not verify
    must never resolve to a data directory.
    """
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() == "true"


def mint(claims: Mapping[str, object]) -> str | None:
    """A signed session cookie value for these identity claims, or None.

    The address is lower-cased here, once, so the two front ends cannot
    disagree about which account a cookie names. Everything downstream
    (`accounts.slug`, `paths_for`, the API's `?account=` check) already
    lower-cases defensively; this is what makes that agreement structural
    rather than coincidental.

    No Google token of any kind goes in. The scope is `openid email profile`
    and there is no Google API to call, so carrying one would turn a leaked
    cookie into a live credential for nothing in return.
    """
    email = str(claims.get("email") or "").strip().lower()
    if not email:
        return None
    payload = {
        "v": VERSION,
        "email": email,
        "email_verified": verified(claims.get("email_verified")),
        "sub": str(claims.get("sub") or "")[:128],
        "name": str(claims.get("name") or "")[:128],
        "picture": str(claims.get("picture") or "")[:512],
        "iat": int(time.time()),
        # Not used to look anything up. It gives a log correlation key that is
        # not the address, and a handle to revoke against if this ever grows a
        # server-side session list — free now, awkward to retrofit.
        "sid": token_hex(16),
    }
    value = _seal(COOKIE, payload)
    if value is None and payload["picture"]:
        payload["picture"] = ""  # the avatar is the one claim worth dropping
        value = _seal(COOKIE, payload)
    return value


def claims(cookies: Mapping[str, str]) -> dict | None:
    """The identity claims this request carries, or None.

    Falls back to the cookie `st.login()` used to write, signed with the same
    secret under its own salt, so the change of issuer cannot sign anybody out
    mid-session. That fallback — and the clearing of those cookies on sign-out
    that goes with it — is temporary and leaves together.
    """
    payload = _open(COOKIE, cookies.get(COOKIE, ""), MAX_AGE)
    if payload is not None:
        return payload if payload.get("v") == VERSION else None
    # A chunked legacy cookie carries its marker inside the signed value, so
    # json.loads fails and this reads as signed out rather than as somebody
    # else. Google's claims are ~400 bytes, so chunking never happened here.
    return _open(
        LEGACY_COOKIE, cookies.get(LEGACY_COOKIE, ""), MAX_AGE, legacy=True
    )


def signed_in_email(cookies: Mapping[str, str]) -> str | None:
    """The verified address this request is signed in as, or None.

    The one gate both front ends pass through. All personal data is keyed to
    the email claim, so an address the provider did not verify must never
    resolve to a data directory.
    """
    payload = claims(cookies)
    if not payload or not verified(payload.get("email_verified")):
        return None
    return str(payload.get("email") or "").strip().lower() or None


def seal_flow(payload: dict) -> str | None:
    """Sign the in-flight OIDC round trip (state, nonce, verifier, next)."""
    return _seal(FLOW_COOKIE, payload)


def open_flow(cookies: Mapping[str, str]) -> dict | None:
    """The round trip this callback belongs to, or None if it is not ours."""
    return _open(FLOW_COOKIE, cookies.get(FLOW_COOKIE, ""), FLOW_MAX_AGE)
