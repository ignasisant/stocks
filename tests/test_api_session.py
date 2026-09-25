"""The API reading the browser's session instead of a shared token.

Two things are being guarded here.

The first is the cookie itself. `stocks.session` mints it and both front ends
read it, so its codec is the one place where "who is this request" is decided.
A change that quietly stopped recognising a valid cookie would turn every
signed-in person anonymous and start asking them for a bearer token; a change
that recognised an invalid one would be very much worse.

There is one cookie this app did not sign and still honours: the
`_streamlit_user` that `st.login()` wrote before the app ran its own OIDC flow.
`test_a_cookie_streamlit_signed_is_still_one_we_can_read` is what makes the
change of issuer unable to sign anybody out mid-session. It goes when that
grace read does.

The second is the authorization rule that makes a session worth having. A token
names nobody, so its caller says which account it wants. A session names a
verified address, so the server decides — and a browser must not be able to read
somebody else's book by editing a query string.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from streamlit.web.server.starlette.starlette_app_utils import create_signed_value

from stocks import accounts, session
from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from tests.conftest import AUTH_COOKIE_SECRET as SECRET

MINE = "mine@example.com"
YOURS = "yours@example.com"
TOKEN = "s3cret-token"

#: What `/me` adds for a session's own identity card — absent, as nulls, for
#: anybody who is not a session.
NO_CARD = {
    "name": None,
    "picture": None,
    "data_dir": None,
    "data_dir_full": None,
    "owner": False,
}


def cookie_for(email: str, *, verified: bool = True) -> str:
    """A session cookie, signed the way the OIDC callback signs one."""
    return session.mint({"email": email, "email_verified": verified, "name": "T"})


def legacy_cookie_for(email: str, *, verified: bool = True, secret: str = SECRET) -> str:
    """The cookie `st.login()` used to write, signed with Streamlit's own writer."""
    claims = {"email": email, "email_verified": verified, "name": "T", "origin": "google"}
    return create_signed_value(secret, session.LEGACY_COOKIE, json.dumps(claims)).decode()


@pytest.fixture(autouse=True)
def _signing_secret(cookie_secret):
    """Every test in this file signs and verifies with the same known secret."""


@pytest.fixture(autouse=True)
def _no_identity_provider(monkeypatch):
    """No IdP configured, pinned rather than inherited.

    `secrets_env.secret` falls back to `st.secrets`, so on a developer's own
    checkout `sign_in_configured()` reads the real `[auth]` section out of
    `.streamlit/secrets.toml` and `/me` answers a different `sign_in` here than
    it does in CI. Pinning it is what stops this file asserting a fact about
    whoever is running it.
    """
    monkeypatch.setattr(session, "sign_in_configured", lambda: False)


@pytest.fixture(autouse=True)
def _cold_caches():
    for fn in (loaders.ledger_state, loaders.positions_table, loaders.history):
        fn.cache_clear()
    yield
    for fn in (loaders.ledger_state, loaders.positions_table, loaders.history):
        fn.cache_clear()


@pytest.fixture
def books(monkeypatch, tmp_path):
    """Two real account directories, so "another account" is a real one.

    Plus an empty guest dir, because an unverified or absent cookie is now read
    as a guest and answers from one — and it must answer from *this* one rather
    than from the repository's real `data/users/_guest`.
    """
    users = tmp_path / "users"
    guest_dir = users / "_guest"
    guest_dir.mkdir(parents=True)
    (guest_dir / "watchlist.yaml").write_text("watchlist:\n  - ticker: GAA\n")
    monkeypatch.setattr(accounts, "GUEST_DIR", guest_dir)
    made = {}
    for address in (MINE, YOURS):
        paths = accounts.paths_for(address, None, users_dir=users)
        paths.root.mkdir(parents=True)
        paths.watchlist.write_text(f"watchlist:\n  - ticker: {address[0].upper()}AA\n")
        made[address] = paths
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: made[email]
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    return made


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


def as_(client: TestClient, email: str, **kw) -> TestClient:
    client.cookies.set(session.COOKIE, cookie_for(email, **kw))
    return client


# ------------------------------------------------------------------ the codec


def test_a_cookie_we_signed_is_one_we_can_read():
    jar = {session.COOKIE: cookie_for(MINE)}
    assert session.signed_in_email(jar) == MINE


def test_a_cookie_streamlit_signed_is_still_one_we_can_read():
    """The grace read, and the reason the change of issuer signs nobody out.

    Delete this the day `stocks.session` stops honouring `_streamlit_user` —
    it is a migration guarantee, not a permanent one."""
    jar = {session.LEGACY_COOKIE: legacy_cookie_for(MINE)}
    assert session.signed_in_email(jar) == MINE


def test_the_claims_we_depend_on_are_the_ones_the_cookie_carries():
    """Pins the payload shape, not just the signature: the email and its
    verification flag are what every data directory is keyed to."""
    payload = session.claims({session.COOKIE: cookie_for(MINE)})
    assert payload["email"] == MINE
    assert payload["email_verified"] is True
    assert payload["v"] == session.VERSION


def test_no_google_token_is_ever_kept_in_the_cookie():
    """A cookie is not a token store. Carrying one would turn a leaked cookie
    into a live Google credential, and nothing here calls a Google API."""
    payload = session.claims({session.COOKIE: cookie_for(MINE)})
    assert not {"access_token", "refresh_token", "id_token"} & set(payload)


def test_the_address_is_stored_lower_cased_so_both_front_ends_agree():
    """Normalised once, at the mint. Every reader downstream lower-cases
    defensively; this is what makes their agreement structural."""
    jar = {session.COOKIE: cookie_for("Mine@Example.COM")}
    assert session.signed_in_email(jar) == MINE


def test_a_cookie_signed_with_another_secret_names_nobody():
    jar = {session.LEGACY_COOKIE: legacy_cookie_for(MINE, secret="somebody-elses")}
    assert session.signed_in_email(jar) is None


def test_a_cookie_signed_for_the_oidc_flow_is_not_a_session():
    """Both cookies share the secret and are told apart only by their salt, so
    a flow cookie presented as a session must verify as nothing."""
    jar = {session.COOKIE: session.seal_flow({"state": "x", "nonce": "y"})}
    assert session.signed_in_email(jar) is None


def test_an_unverified_address_is_not_signed_in():
    """All personal data is keyed to the email claim, so an address the
    provider did not verify must never resolve to a data directory."""
    jar = {session.COOKIE: cookie_for(MINE, verified=False)}
    assert session.signed_in_email(jar) is None


def test_an_email_verified_of_the_string_false_is_not_verified():
    """`"false"` is truthy in Python. A provider or a hop that renders the
    claim as a string must not hand somebody an unverified account."""
    assert session.verified("false") is False
    assert session.verified("true") is True
    assert session.verified(True) is True


def test_a_payload_from_a_future_version_names_nobody():
    """A shape this build does not know is refused, not parsed as best it can."""
    raw = session._seal(session.COOKIE, {"v": session.VERSION + 1, "email": MINE,
                                         "email_verified": True})
    assert session.claims({session.COOKIE: raw}) is None


def test_a_missing_cookie_names_nobody():
    assert session.signed_in_email({}) is None


def test_a_mangled_cookie_names_nobody():
    assert session.signed_in_email({session.COOKIE: "not-a-signed-value"}) is None


def test_the_cookie_stays_well_under_what_a_browser_will_keep():
    """Browsers drop a cookie over ~4096 bytes and a truncated one is worse
    than none, so the payload is guarded rather than trusted to stay small."""
    raw = session.mint({"email": MINE, "email_verified": True, "name": "N" * 200,
                        "picture": "https://example.com/" + "p" * 400, "sub": "1" * 40})
    assert len(raw) < 4000


def test_no_configured_secret_names_nobody(monkeypatch):
    """Fail closed: with nothing to verify against, nobody is signed in."""
    jar = {session.COOKIE: cookie_for(MINE)}
    monkeypatch.delenv("AUTH_COOKIE_SECRET", raising=False)
    monkeypatch.setattr(session, "signing_secret", lambda: "")
    assert session.signed_in_email(jar) is None


def test_an_unreadable_secret_degrades_instead_of_raising(monkeypatch):
    """A malformed secrets.toml must read as "nobody is signed in", not 500
    every request on the deployment."""
    import streamlit as st

    jar = {session.COOKIE: cookie_for(MINE)}
    monkeypatch.delenv("AUTH_COOKIE_SECRET", raising=False)

    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("secrets.toml is not valid TOML")

    monkeypatch.setattr(st, "secrets", Boom())
    assert session.signed_in_email(jar) is None


# ---------------------------------------------------------- what a session buys


def test_a_signed_in_browser_needs_no_token_and_no_account(client, books, monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")
    response = as_(client, MINE).get("/v1/watchlist")
    assert response.status_code == 200
    assert [e["ticker"] for e in response.json()["entries"]] == ["MAA"]


def test_a_session_may_repeat_its_own_address(client, books):
    response = as_(client, MINE).get("/v1/watchlist", params={"account": MINE})
    assert response.status_code == 200


def test_a_session_cannot_read_another_account(client, books):
    """The point of the whole exercise: a browser does not get to pick."""
    response = as_(client, MINE).get("/v1/watchlist", params={"account": YOURS})
    assert response.status_code == 403
    assert "MAA" not in response.text and "YAA" not in response.text


def test_the_refusal_does_not_leak_whether_that_account_exists(client, books):
    """403 for both a real other account and an invented one — a 404 for one of
    them would answer a question this caller may not ask."""
    signed = as_(client, MINE)
    real = signed.get("/v1/watchlist", params={"account": YOURS})
    invented = signed.get("/v1/watchlist", params={"account": "nobody@example.com"})
    assert real.status_code == invented.status_code == 403


def test_the_address_is_compared_case_insensitively(client, books):
    response = as_(client, MINE).get("/v1/watchlist", params={"account": MINE.upper()})
    assert response.status_code == 200


def test_an_unverified_session_is_read_as_a_guest(client, books, monkeypatch):
    """Google will hand over an address it has not verified, and an address
    nobody proved is not an identity. It used to buy a 401; now it buys what
    presenting no cookie at all buys — the shared demo book, never MINE's."""
    monkeypatch.setenv("API_TOKEN", TOKEN)
    response = as_(client, MINE, verified=False).get("/v1/watchlist")
    assert response.status_code == 200
    assert "MAA" not in response.text
    assert [e["ticker"] for e in response.json()["entries"]] == ["GAA"]


def test_an_unverified_session_may_not_name_the_account_it_claims_to_be(
    client, books, monkeypatch
):
    """The half that would hurt: being demoted to a guest must not leave the
    `?account=` door open, or an unverified cookie would be a *better*
    credential than a verified one."""
    monkeypatch.setenv("API_TOKEN", TOKEN)
    signed = as_(client, MINE, verified=False)
    assert signed.get("/v1/watchlist", params={"account": MINE}).status_code == 403


# ------------------------------------------------------------ the token caller


def test_a_token_still_names_the_account_itself(client, books, monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    response = client.get(
        "/v1/watchlist",
        params={"account": YOURS},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert [e["ticker"] for e in response.json()["entries"]] == ["YAA"]


def test_a_token_without_an_account_is_refused(client, books, monkeypatch):
    """It names nobody, so there is no account to fall back to."""
    monkeypatch.setenv("API_TOKEN", TOKEN)
    response = client.get("/v1/watchlist", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 422


# -------------------------------------------------------------------- identity


def test_me_reports_the_signed_in_address(client, books):
    body = as_(client, MINE).get("/v1/me").json()
    assert {k: body[k] for k in ("kind", "email", "sign_in")} == {
        "kind": "session",
        "email": MINE,
        "sign_in": None,
    }


def test_me_carries_the_identity_card_for_the_session_itself(client, books):
    """The Streamlit card's name, avatar and folder chip: the name from the
    claims, the folder as its tail with the full path beside it for the
    tooltip, and no owner flag for an ordinary account."""
    client.cookies.set(
        session.COOKIE,
        session.mint(
            {
                "email": MINE,
                "email_verified": True,
                "name": "Ada Lovelace",
                "picture": "https://lh3.example.com/a.png",
            }
        ),
    )
    body = client.get("/v1/me").json()
    root = books[MINE].root
    assert body["name"] == "Ada Lovelace"
    assert body["picture"] == "https://lh3.example.com/a.png"
    assert body["data_dir"] == f"users/{root.name}"
    assert body["data_dir_full"] == str(root)
    assert body["owner"] is False


def test_me_names_the_owner_so_deletion_is_not_offered(client, books, monkeypatch):
    """The owner's book is the repo-root files: `DELETE /account` refuses it,
    so the client hides the control, as the Streamlit page does."""
    from dataclasses import replace

    from stocks.config import PROJECT_ROOT

    # The account files stay the fixture's; only the root says "owner".
    owned = replace(books[MINE], root=PROJECT_ROOT)
    monkeypatch.setattr(accounts, "paths_for", lambda email, owner=None: owned)
    body = as_(client, MINE).get("/v1/me").json()
    assert body["owner"] is True


def test_me_reports_a_token_caller_as_nameless(client, monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    body = client.get("/v1/me", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert body == {"kind": "token", "email": None, "sign_in": None, **NO_CARD}


def test_me_calls_an_anonymous_caller_a_guest(client, monkeypatch):
    """It used to refuse, which was right while anonymous meant nothing at all.
    Now it is the first call the shell makes and the answer decides which shape
    of app to paint, so refusing would hide the one state it has to report."""
    monkeypatch.setenv("API_TOKEN", TOKEN)
    response = client.get("/v1/me")
    assert response.status_code == 200
    assert response.json() == {
        "kind": "guest",
        "email": None,
        "sign_in": None,
        **NO_CARD,
    }


def test_me_says_where_to_sign_in_when_a_provider_is_configured(client, monkeypatch):
    """`sign_in` is null above because the test deployment has no identity
    provider, and a shell that drew a sign-in button anyway would send people to
    a route that 404s. This is the other arm, so "null" stays a fact about the
    deployment rather than about the field."""
    monkeypatch.setattr(session, "sign_in_configured", lambda: True)
    assert client.get("/v1/me").json()["sign_in"] == session.LOGIN_PATH


# -------------------------------------------------------------- provisioning


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    """No account on disk and no bucket: what a brand-new address looks like."""
    from stocks import storage

    users = tmp_path / "users"
    monkeypatch.setattr(accounts, "USERS_DIR", users)
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    real = accounts.paths_for
    monkeypatch.setattr(
        accounts, "paths_for",
        lambda email, owner=None, users_dir=users: real(email, None, users_dir=users),
    )
    monkeypatch.setattr(storage, "enabled", lambda: False)
    return users


def test_a_session_for_an_account_with_no_data_provisions_it(client, fresh):
    """A valid session whose account is missing — a cookie from before the
    callback provisioned, a callback that hit a bucket outage — used to 404
    "unknown account" forever, which the shell can only render as offline."""
    response = as_(client, MINE).get("/v1/watchlist")
    assert response.status_code == 200
    assert response.json()["entries"]  # the starter watchlist
    paths = accounts.paths_for(MINE)
    prefs = accounts.load_prefs(paths.prefs)
    assert prefs["email"] == MINE
    assert prefs["first_seen_estimated"] is False  # seeded now: an exact signup


def test_a_token_still_never_calls_an_account_into_existence(
    client, fresh, monkeypatch
):
    """The self-healing is the session's alone: a token names nobody."""
    monkeypatch.setenv("API_TOKEN", TOKEN)
    response = client.get(
        "/v1/watchlist", params={"account": "nobody@example.com"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 404
    assert not fresh.exists() or not list(fresh.iterdir())


def test_a_storage_outage_is_a_503_the_shell_can_translate(client, fresh, monkeypatch):
    def down(*a, **k):
        raise accounts.StorageUnavailable("bucket down")

    monkeypatch.setattr(accounts, "restore_account", down)
    response = as_(client, MINE).get("/v1/watchlist")
    assert response.status_code == 503
    assert response.json()["detail"] == "common.storage_restore_failed"


def test_an_ordinary_read_by_an_existing_account_writes_nothing(client, fresh):
    """Only the provisioning request stamps. After that a read is a read — the
    promise `/import/preview` makes (test_api_persistence) holds for every one."""
    signed = as_(client, MINE)
    signed.get("/v1/watchlist")
    prefs = accounts.paths_for(MINE).prefs
    before = prefs.stat().st_mtime_ns
    signed.get("/v1/watchlist")
    assert prefs.stat().st_mtime_ns == before
