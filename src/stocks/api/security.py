"""Who is asking — a signed-in person, or a job holding the shared token.

The API answers two very different callers and must not confuse them:

* **A browser.** Carries the session cookie the app's own sign-in minted
  (`stocks/session.py`), which names a verified address. The *server* decides
  whose book that is; the client cannot ask for another. This is what a front
  end that is not Streamlit needs, and it is the only form strong enough to put
  in front of a person.
* **A job.** Carries `Authorization: Bearer <token>` — one shared secret in
  `[api] token` or `API_TOKEN`, compared in constant time. It names nobody, so
  it has to say which account it wants, which means any holder can read every
  account. That is the right strength for the owner's own cron over TLS, and
  not enough for anyone else.

Fails closed by construction: serving data needs a session or a token to check
out, so a deployment configured with neither refuses every request rather than
opening up. Refusals are always 401 — "this server has no API token" is an
ordinary state (the token is only for headless jobs) and a browser that meets it
should be offered a sign-in, not a server error. The misconfiguration worth
knowing about is logged instead.

No CSRF token, deliberately, and the argument has three legs rather than one.
Every write is a POST/PUT/PATCH/DELETE carrying `Content-Type: application/json`
— which no HTML form can produce, so no form can forge one. A cross-origin fetch
that sets that type is preflighted, and no CORS headers are sent, so the
preflight fails and the real request is never made. And the session cookie is
`SameSite=Lax`, so a cross-site non-GET carries no credential at all. Each leg
is load-bearing: relax any one of them — a form-encoded route, a CORS header, a
cookie set `SameSite=None` — and a token stops being optional.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated, Literal, NoReturn

from fastapi import Depends, Header, HTTPException, Request, status

from stocks import obs
from stocks.api import session
from stocks.secrets_env import secret


@dataclass(frozen=True)
class Caller:
    """An authenticated caller, and how it proved itself.

    `email` is set only for a session: a token cannot name anybody, which is
    exactly why a token-authenticated request has to pass `?account=` and a
    browser one must not be allowed to. A guest names nobody either, and unlike
    a token it may not be *given* a name — see `deps.account`.
    """

    kind: Literal["session", "token", "guest"]
    email: str | None = None


def configured_token() -> str:
    """The shared secret, or "" when no token has been configured."""
    return secret("API_TOKEN", "api", "token")


def _token_matches(authorization: str) -> bool:
    """True when the header carries the configured bearer token.

    The scheme is matched case-insensitively because clients disagree about it;
    the token itself is compared byte for byte in constant time.
    """
    expected = configured_token()
    if not expected:
        return False
    scheme, _, presented = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        presented.strip(), expected
    )


def refuse() -> NoReturn:
    """401, with the header that turns a refusal into a sign-in button.

    One function because two callers raise it now — `caller()`, for a route
    that wants a named caller in its own signature, and `api.app.gate`, for a
    route no guest may read — and the two must not drift on the wording or the
    header.
    """
    if not configured_token():
        # Worth an operator's attention — a deployment with no API token can
        # only ever serve browsers — but not worth a different status code. A
        # token is optional now that a session is a first-class way in, so "no
        # token configured" is an ordinary deployment, and answering 503 here
        # would show an anonymous visitor a server error where the page means
        # to show them a sign-in button.
        obs.warn("api.no_token_configured")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="sign in, or present a bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def visitor(
    request: Request, authorization: Annotated[str, Header()] = ""
) -> Caller:
    """FastAPI dependency: who is asking, including nobody.

    Never refuses, on purpose. Whether an anonymous caller may proceed depends
    on *which route was matched*, and that is not knowable here — so refusing is
    `api.app.gate`'s job and this answers one question only.

    The cookie is checked first. A person signed into the app is the common
    case, and checking it first means a browser never needs a token at all.
    Everything downstream (`deps.account`, `deps.writer`, `/me`) reads this, so
    a request has exactly one answer to "who is this" and no two dependencies
    can disagree about it.
    """
    if email := session.signed_in_email(request.cookies):
        return Caller(kind="session", email=email)
    if _token_matches(authorization):
        return Caller(kind="token")
    return Caller(kind="guest")


def caller(who: Annotated[Caller, Depends(visitor)]) -> Caller:
    """FastAPI dependency: a *named* caller, or 401.

    Unchanged in meaning — a guest is not a named caller. Kept as its own
    dependency because the routes that confirm a destructive act against the
    signed-in address want that stated in their own signature rather than
    inferred from `Writer`.
    """
    if who.kind == "guest":
        refuse()
    return who


#: Who is asking, including nobody. For the gate and for `/me`.
Who = Annotated[Caller, Depends(visitor)]

#: A named caller, or 401. What every route that acts on an account uses.
Authed = Annotated[Caller, Depends(caller)]
