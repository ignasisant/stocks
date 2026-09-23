"""The app's own Google sign-in: three routes, one cookie, no Streamlit.

Sign-in used to be `st.login()`, which meant only the Streamlit process could
create a session — the React shell could read one and never start one. These
routes run the authorization-code flow themselves and mint the cookie
`stocks.session` defines, so both front ends are served by one sign-in.

They answer at the paths Streamlit used (`/auth/login`, `/auth/logout`,
`/oauth2callback`) and shadow its own handlers, because user routes are matched
first. Keeping the names is what makes this invisible from outside: the same
redirect URI is registered with Google, the same `[auth] redirect_uri` is
deployed, and the React shell's existing sign-out links still point at a route
that exists.

The one thing worth knowing before editing: **the session cookie is written
exactly once, at the end of the callback, after every check has passed.** Never
"set it now and clear it if validation fails" — every failure path here has to
converge on leaving no cookie behind, because the alternative to failing closed
is not an error page, it is somebody signed in as the wrong person.
"""

from __future__ import annotations

import hmac
from functools import lru_cache
from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from stocks import obs, session
from stocks.secrets_env import secret

#: Google signs with RS256 today. The metadata says which algorithms it offers,
#: and we intersect that list with this one rather than trusting it: a document
#: that offered HS256 would invite a JWKS public key to be used as an HMAC
#: secret, which is the classic way an ID token check is turned inside out.
_ALGS = ("RS256", "ES256")

_SCOPE = "openid email profile"


def _conf(key: str) -> str:
    return secret(f"AUTH_{key.upper()}", "auth", key)


def configured() -> bool:
    """Whether sign-in can work at all on this deployment.

    The question itself lives in `stocks.session`, because `GET /me` has to
    answer it too and the API may not import this package to do so.
    """
    return session.sign_in_configured()


@lru_cache(maxsize=1)
def _client() -> Any:
    """The OIDC client, built once.

    Authlib caches the discovery document on the client for the life of the
    process and re-fetches the JWKS by itself when Google rotates a key and an
    unknown `kid` shows up — which is the handling we want. The cost is that a
    change to the discovery document itself needs a restart; on Cloud Run, where
    instances recycle on their own, that is a price worth naming and paying.

    PKCE is opt-in in authlib: without `code_challenge_method` it is silently
    skipped, which is why it is stated here and asserted in a test.
    """
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=_conf("client_id"),
        client_secret=_conf("client_secret"),
        server_metadata_url=_conf("server_metadata_url")
        or "https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": _SCOPE, "code_challenge_method": "S256"},
    )
    return oauth.google


def _secure(request: Request) -> bool:
    """Whether this deployment's cookies may carry the Secure flag.

    Mirrors the rule `SecurityHeaders` uses for HSTS, and deliberately trusts
    `[app] public_url` over the forwarded header: that header is client-supplied,
    so a request that lied `http` to a TLS deployment would otherwise be handed
    a cookie without Secure.

    One helper, used by the mint *and* the clear. They must not drift: Chrome
    refuses to set a Secure deletion cookie over plain HTTP, so a mismatch shows
    up as sign-out silently failing on localhost while working in production.
    """
    if (secret("APP_PUBLIC_URL", "app", "public_url") or "").startswith("https://"):
        return True
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (proto or request.url.scheme) == "https"


def _set(response: Response, name: str, value: str, max_age: int, request: Request):
    response.set_cookie(
        name, value, max_age=max_age, path="/", httponly=True,
        samesite="lax", secure=_secure(request),
    )


def _clear(response: Response, name: str, request: Request) -> None:
    response.delete_cookie(
        name, path="/", httponly=True, samesite="lax", secure=_secure(request)
    )


def _safe_next(raw: str) -> str:
    """A site-relative path we are willing to send a browser back to.

    `?next=https://evil` must not survive a sign-in. Anything that is not a
    plain single-slash path becomes "/" — including `//host`, which a browser
    reads as an absolute URL, and a backslash, which some of them normalise
    into one.
    """
    if raw.startswith("/") and not raw.startswith("//") and "\\" not in raw:
        return raw
    return "/"


def _home(request: Request, target: str = "/") -> Response:
    """Back to the app, with nothing cached: the answer depends on a cookie."""
    response = RedirectResponse(target, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


async def login(request: Request) -> Response:
    """Start the round trip: stash state, nonce and verifier, leave for Google."""
    target = _safe_next(request.query_params.get("next", "/"))
    if not configured():
        obs.warn("auth.not_configured")
        return _home(request, target)
    try:
        started = await _client().create_authorization_url(
            _conf("redirect_uri"), prompt="select_account"
        )
    except Exception as exc:  # noqa: BLE001 — discovery down is not a 500
        obs.error("auth.discovery_failed", exc)
        return _home(request, target)

    flow = session.seal_flow({
        "state": started["state"],
        "nonce": started.get("nonce", ""),
        "code_verifier": started.get("code_verifier", ""),
        "next": target,
    })
    if flow is None:
        return _home(request, target)
    response = _home(request, started["url"])
    _set(response, session.FLOW_COOKIE, flow, session.FLOW_MAX_AGE, request)
    return response


async def callback(request: Request) -> Response:
    """Come back from Google, and mint a session only if everything checks out.

    Every `return` before the last one leaves without a session cookie. The flow
    cookie is cleared on all of them, successful or not: it is single-use by
    construction, and a dangling one is ten minutes of usable code verifier.
    """
    flow = session.open_flow(request.cookies) or {}
    target = _safe_next(str(flow.get("next") or "/"))
    response = _home(request, target)
    _clear(response, session.FLOW_COOKIE, request)

    # Pressing Cancel at Google is the normal way not to sign in, not an error.
    if request.query_params.get("error"):
        return response

    state = request.query_params.get("state", "")
    if not flow or not hmac.compare_digest(state, str(flow.get("state") or "")):
        # No flow cookie, a stale one, or a callback that did not start here.
        obs.warn("auth.state_mismatch")
        return response

    try:
        token = await _client().fetch_access_token(
            redirect_uri=_conf("redirect_uri"),
            code=request.query_params.get("code", ""),
            code_verifier=str(flow.get("code_verifier") or ""),
            grant_type="authorization_code",
        )
        # Authlib validates an ID token when there is one and quietly skips the
        # whole check when there is not, so its presence is ours to require.
        if "id_token" not in token:
            obs.warn("auth.no_id_token")
            return response
        claims = await _client().parse_id_token(
            token,
            nonce=str(flow.get("nonce") or ""),
            claims_options=_claims_options(),
            leeway=60,
        )
    except Exception as exc:  # noqa: BLE001 — the catch-all IS the guarantee
        obs.error("auth.callback_failed", exc)
        return response

    if not _audience_is_ours(claims.get("aud")):
        obs.warn("auth.wrong_audience")
        return response
    if not str(claims.get("email") or "").strip():
        obs.warn("auth.no_email")
        return response

    cookie = session.mint(claims)
    if cookie is None:
        return response
    _set(response, session.COOKIE, cookie, session.MAX_AGE, request)
    # A browser that signed in under the old build still carries Streamlit's
    # cookie. Ours wins, but leaving it would mean two answers to "who is this"
    # for thirty days.
    _clear_legacy(response, request)
    return response


async def logout(request: Request) -> Response:
    """Clear the session and come back to the app as a guest.

    No trip to Google. We asked for `openid email profile`, kept no token and
    have no Google API to call, so there is nothing at Google that outlives this
    cookie — and sending somebody to Google's global sign-out would sign them
    out of Gmail, which is a hostile surprise from a portfolio app.
    """
    response = _home(request)
    _clear(response, session.COOKIE, request)
    _clear(response, session.FLOW_COOKIE, request)
    # Security-critical while the grace read lives: without this, signing out
    # with a valid Streamlit cookie still in the jar leaves you signed in.
    _clear_legacy(response, request)
    # `ts_app` is deliberately untouched. It is not a session and not a login —
    # clearing it would send a returning visitor to the marketing landing.
    return response


def _clear_legacy(response: Response, request: Request) -> None:
    for name in (session.LEGACY_COOKIE, session.LEGACY_TOKENS_COOKIE):
        _clear(response, name, request)
    for name in request.cookies:
        legacy = (f"{session.LEGACY_COOKIE}_", f"{session.LEGACY_TOKENS_COOKIE}_")
        if name.startswith(legacy):
            _clear(response, name, request)


def _claims_options() -> dict:
    """What `parse_id_token` must check beyond the signature.

    Authlib pins the issuer for us and leaves the audience alone — `aud` is
    required to be *present* and is never compared to our client id. That is the
    one check we would miss by taking the defaults, so it is stated here (and
    again, for the list-valued form, in `_audience_is_ours`).
    """
    return {"aud": {"essential": True, "value": _conf("client_id")}}


def _audience_is_ours(aud: object) -> bool:
    """An ID token minted for another client is not a sign-in here."""
    ours = _conf("client_id")
    if isinstance(aud, str):
        return hmac.compare_digest(aud, ours)
    if isinstance(aud, (list, tuple)):
        return len(aud) == 1 and hmac.compare_digest(str(aud[0]), ours)
    return False


def routes() -> list[Route]:
    """The three routes, for `server.py`'s table."""
    return [
        Route(session.LOGIN_PATH, login, methods=["GET"]),
        Route(session.CALLBACK_PATH, callback, methods=["GET"]),
        Route(session.LOGOUT_PATH, logout, methods=["GET"]),
    ]
