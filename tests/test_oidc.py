"""The app's own sign-in flow, and the ways it must refuse to sign anybody in.

Streamlit used to run this round trip. Now it is ours, which means the checks
Streamlit was quietly doing are ours to get right — and the one that matters
most is the one authlib does *not* do for you: `parse_id_token` pins the issuer
and never compares the audience to our client id, so a token minted for another
Google client would otherwise sail through a signature check and sign somebody in.

Every test below is a variation on one question: when something is wrong, does
the response leave without a session cookie? A flow that errors is an
inconvenience. A flow that mints a session for the wrong claims is not.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from stocks import session
from stocks.web import oidc
from tests.conftest import AUTH_COOKIE_SECRET

CLIENT_ID = "our-client-id.apps.googleusercontent.com"
EMAIL = "jane@example.com"
AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=st-1"


class FakeGoogle:
    """Authlib's client, with the network taken out and the shape kept."""

    def __init__(self, **over):
        self.over = over
        self.seen: dict = {}

    async def create_authorization_url(self, redirect_uri, **kw):
        if "authorize_raises" in self.over:
            raise self.over["authorize_raises"]
        self.seen["redirect_uri"] = redirect_uri
        self.seen["prompt"] = kw.get("prompt")
        return {
            "url": AUTHORIZE,
            "state": "st-1",
            "nonce": "no-1",
            "code_verifier": "verifier-1",
        }

    async def fetch_access_token(self, **kw):
        if "token_raises" in self.over:
            raise self.over["token_raises"]
        self.seen["token_kw"] = kw
        return self.over.get("token", {"id_token": "signed.jwt", "access_token": "at"})

    async def parse_id_token(self, token, **kw):
        if "claims_raises" in self.over:
            raise self.over["claims_raises"]
        self.seen["claims_kw"] = kw
        return self.over.get(
            "claims",
            {"email": EMAIL, "email_verified": True, "aud": CLIENT_ID,
             "sub": "1", "name": "Jane"},
        )


@pytest.fixture
def configured(monkeypatch):
    """A deployment with sign-in switched on, signing with a known secret."""
    monkeypatch.setenv("AUTH_COOKIE_SECRET", AUTH_COOKIE_SECRET)
    monkeypatch.setenv("AUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AUTH_CLIENT_SECRET", "our-client-secret")
    monkeypatch.setenv("AUTH_REDIRECT_URI", "https://app.example.com/oauth2callback")
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)


@pytest.fixture
def google(monkeypatch, configured):
    """Swap the OIDC client, and hand the fake back so a test can steer it."""
    fake = FakeGoogle()

    def _install(**over):
        fake.over.update(over)
        monkeypatch.setattr(oidc, "_client", lambda: fake)
        return fake

    _install()
    return type("G", (), {"install": staticmethod(_install), "fake": fake})


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=oidc.routes())
    return TestClient(app, follow_redirects=False)


def cookies_set(response) -> dict[str, str]:
    """Cookie name -> the whole Set-Cookie line, deletions included."""
    out = {}
    for line in response.headers.get_list("set-cookie"):
        out[line.split("=", 1)[0].strip()] = line
    return out


def start(client, google, **over):
    """Run the leaving half, and hand back the flow cookie it stashed."""
    google.install(**over)
    response = client.get(session.LOGIN_PATH)
    return response, cookies_set(response).get(session.FLOW_COOKIE, "")


# ------------------------------------------------------------------- leaving


def test_the_login_route_sends_the_browser_to_google(client, google):
    response = client.get(session.LOGIN_PATH)
    assert response.status_code == 302
    assert response.headers["location"] == AUTHORIZE


def test_the_round_trip_is_asked_for_with_pkce_and_a_nonce():
    """PKCE is opt-in in authlib — no `code_challenge_method`, no challenge,
    silently. This is the assertion that stops that from regressing."""
    oidc._client.cache_clear()
    import os

    os.environ["AUTH_CLIENT_ID"] = CLIENT_ID
    os.environ["AUTH_CLIENT_SECRET"] = "s"
    try:
        kwargs = oidc._client().client_kwargs
    finally:
        oidc._client.cache_clear()
    assert kwargs["code_challenge_method"] == "S256"
    assert "openid" in kwargs["scope"]


def test_the_flow_cookie_is_short_lived_and_not_reachable_from_script(client, google):
    _, flow = start(client, google)
    assert "HttpOnly" in flow
    assert "samesite=lax" in flow.lower()
    assert f"Max-Age={session.FLOW_MAX_AGE}" in flow


@pytest.mark.parametrize(
    "hostile", ["//evil.example.com", "https://evil.example.com", "/\\evil.example.com"]
)
def test_a_next_parameter_cannot_send_the_browser_off_site(client, google, hostile):
    """An open redirect on the way out of a sign-in is still an open redirect,
    and it has to be closed where the value is stored, not where it is used."""
    _, flow = start(client, google)  # prime the fake
    client.get(f"{session.LOGIN_PATH}?next={hostile}")
    stashed = session.open_flow(
        {session.FLOW_COOKIE: client.cookies[session.FLOW_COOKIE]}
    )
    assert stashed["next"] == "/"
    assert come_back(client, google, "").headers["location"] == "/"


def test_a_next_parameter_that_is_ours_is_honoured(client, google):
    google.install()
    client.get(f"{session.LOGIN_PATH}?next=/portfolio?tab=fees")
    response = client.get(f"{session.CALLBACK_PATH}?state=st-1&code=c")
    assert response.headers["location"] == "/portfolio?tab=fees"
    assert signed_in_as(response) == EMAIL


def test_discovery_being_down_is_not_a_500(client, google):
    response, flow = start(client, google, authorize_raises=RuntimeError("no dns"))
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert not flow


def test_sign_in_that_is_not_configured_just_comes_back(client, monkeypatch):
    monkeypatch.setattr(oidc, "configured", lambda: False)
    response = client.get(session.LOGIN_PATH)
    assert response.status_code == 302
    assert not cookies_set(response).get(session.FLOW_COOKIE)


# ------------------------------------------------------------------ coming back


def signed_in_as(response) -> str | None:
    """The address the response's session cookie names, if it set one."""
    line = cookies_set(response).get(session.COOKIE, "")
    value = line.split("=", 1)[1].split(";")[0] if "=" in line else ""
    return session.signed_in_email({session.COOKIE: value})


def come_back(client, google, flow: str, query="?state=st-1&code=c", **over):
    google.install(**over)
    client.cookies.clear()
    if flow:
        client.cookies.set(session.FLOW_COOKIE, flow.split("=", 1)[1].split(";")[0])
    return client.get(f"{session.CALLBACK_PATH}{query}")


def test_a_completed_round_trip_signs_the_browser_in(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow)
    assert signed_in_as(response) == EMAIL


def test_the_address_is_stored_lower_cased(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow, claims={
        "email": "Jane@Example.COM", "email_verified": True, "aud": CLIENT_ID})
    assert signed_in_as(response) == EMAIL


def test_the_flow_cookie_is_spent_whatever_happens(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow)
    assert "Max-Age=0" in cookies_set(response)[session.FLOW_COOKIE]


def test_a_callback_whose_state_does_not_match_signs_nobody_in(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow, query="?state=somebody-elses&code=c")
    assert signed_in_as(response) is None


def test_a_callback_with_no_flow_cookie_signs_nobody_in(client, google):
    response = come_back(client, google, "")
    assert signed_in_as(response) is None


def test_a_replayed_callback_cannot_mint_a_second_session(client, google):
    """The flow cookie is single-use: the browser was told to drop it the first
    time, so the replay arrives without one."""
    _, flow = start(client, google)
    assert signed_in_as(come_back(client, google, flow)) == EMAIL
    assert signed_in_as(come_back(client, google, "")) is None


def test_an_id_token_for_another_audience_is_refused(client, google):
    """The check authlib does not do. A token minted for a different Google
    client is a valid, correctly signed token — for somebody else's app."""
    _, flow = start(client, google)
    response = come_back(client, google, flow, claims={
        "email": EMAIL,
        "email_verified": True,
        "aud": "another-app.googleusercontent.com",
    })
    assert signed_in_as(response) is None


def test_an_audience_that_merely_contains_us_is_refused(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow, claims={
        "email": EMAIL, "email_verified": True, "aud": [CLIENT_ID, "someone-else"]})
    assert signed_in_as(response) is None


def test_a_token_response_with_no_id_token_is_refused(client, google):
    """Authlib skips ID-token validation entirely when there is none, so an
    unchecked response must not become a session."""
    _, flow = start(client, google)
    response = come_back(client, google, flow, token={"access_token": "at"})
    assert signed_in_as(response) is None


def test_an_id_token_that_does_not_verify_is_refused(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow,
                         claims_raises=ValueError("bad signature"))
    assert signed_in_as(response) is None


def test_a_failed_token_exchange_is_refused(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow, token_raises=ValueError("invalid_grant"))
    assert signed_in_as(response) is None


def test_an_identity_with_no_email_is_refused(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow,
                         claims={"email": "", "email_verified": True, "aud": CLIENT_ID})
    assert signed_in_as(response) is None


def test_an_unverified_address_never_reaches_a_data_directory(client, google):
    """A cookie is still minted — `require_login` names the state — but it does
    not resolve to an account, which is the invariant that matters."""
    _, flow = start(client, google)
    response = come_back(client, google, flow, claims={
        "email": EMAIL, "email_verified": False, "aud": CLIENT_ID})
    assert signed_in_as(response) is None


def test_a_cancelled_sign_in_comes_back_quietly_signed_out(client, google):
    _, flow = start(client, google)
    response = come_back(client, google, flow, query="?error=access_denied")
    assert response.status_code == 302
    assert signed_in_as(response) is None


def test_signing_in_clears_any_leftover_streamlit_cookie(client, google):
    """Two answers to "who is this" is the one thing the migration must not
    leave behind."""
    _, flow = start(client, google)
    response = come_back(client, google, flow)
    assert "Max-Age=0" in cookies_set(response)[session.LEGACY_COOKIE]


# ---------------------------------------------------------------- signing out


def test_signing_out_clears_the_session_and_the_streamlit_leftovers(client, google):
    response = client.get(session.LOGOUT_PATH)
    set_by = cookies_set(response)
    assert response.status_code == 302
    for name in (session.COOKIE, session.FLOW_COOKIE, session.LEGACY_COOKIE,
                 session.LEGACY_TOKENS_COOKIE):
        assert "Max-Age=0" in set_by[name], name


def test_signing_out_leaves_the_returning_visitor_cookie_alone(client, google):
    """`ts_app` is not a session and not a login: clearing it would send a
    signed-out reader to the marketing landing instead of the app."""
    response = client.get(session.LOGOUT_PATH)
    assert "ts_app" not in cookies_set(response)


def test_signing_out_does_not_send_the_reader_to_google(client, google):
    """We keep no token, so there is nothing to revoke — and Google's global
    sign-out would sign them out of Gmail."""
    response = client.get(session.LOGOUT_PATH)
    assert response.headers["location"] == "/"


# ------------------------------------------------------------------- the flags


def test_a_cookie_is_not_secure_on_plain_local_http(client, google):
    _, flow = start(client, google)
    assert "Secure" not in flow


def test_a_cookie_is_secure_behind_a_tls_proxy(client, google, monkeypatch):
    """Cloud Run terminates TLS and forwards the scheme; the cookie has to
    follow the real one, not the one the container sees."""
    monkeypatch.setenv("APP_PUBLIC_URL", "https://app.example.com")
    _, flow = start(client, google)
    assert "Secure" in flow
