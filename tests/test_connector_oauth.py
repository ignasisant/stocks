"""The MCP connector's authorization server, end to end over HTTP.

What a client like claude.ai does, in order: read the protected resource's
metadata, then the authorization server's, register (or present a metadata
document URL), send the person to `/authorize`, wait for the redirect back
with a code, and trade the code — with the PKCE verifier — for tokens.

What is guarded here is everything a stranger would try on that road:

* the consent page is the only way to a code, and it only mints one for the
  person signed in, from a form this site drew for this session and request;
* a code is single use, and a second try revokes everything the first issued;
* a refresh token is single use too, and replaying an old one ends the grant;
* the site's own `API_TOKEN`, valid everywhere in `/api`, is nothing at `/mcp`;
* without a public origin the whole connector is a 404.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.connector import oauth, store
from stocks.connector.server import Door

ORIGIN = "https://testserver"
RESOURCE = f"{ORIGIN}/mcp"
EMAIL = "holder@example.com"
REDIRECT = "http://127.0.0.1:33418/callback"
PROTOCOL = "2025-11-25"


@pytest.fixture
def door() -> Door:
    return Door()


@pytest.fixture
def site(door, monkeypatch, cookie_secret):
    """The connector's routes alone, opened by their own lifespan."""
    monkeypatch.setenv("APP_PUBLIC_URL", ORIGIN)
    app = Starlette(
        routes=[Route(p, door) for p in oauth.PATHS],
        lifespan=lambda app: door.lifespan(),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client


@pytest.fixture
def book(monkeypatch, tmp_path):
    """The account the signed-in person owns: a watchlist and one buy."""
    from stocks.portfolio import ledger
    from stocks.portfolio.ledger import Transaction

    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    ledger.add_many(
        [Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0, note="t")],
        path=paths.db,
    )
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    for fn in vars(loaders).values():
        if callable(fn) and hasattr(fn, "cache_clear"):
            fn.cache_clear()
    return paths


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def register(client: TestClient, **extra) -> dict:
    body = {
        "redirect_uris": [REDIRECT],
        "client_name": "Test client",
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        **extra,
    }
    r = client.post("/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def authorize(client: TestClient, client_id: str, challenge: str, **extra) -> str:
    """`/authorize` for a client; the consent URL it sends the browser to."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st-1",
        "resource": RESOURCE,
        "scope": store.SCOPE,
        **extra,
    }
    r = client.get("/authorize", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    return r.headers["location"]


def form_fields(html: str) -> dict[str, str]:
    return dict(re.findall(r'name="(req|csrf)" value="([^"]*)"', html))


def decide(client: TestClient, consent_url: str, decision: str = "allow",
           **ticked: str) -> str:
    """Draw the consent page and press a button; where the browser goes next."""
    page = client.get(consent_url, follow_redirects=False)
    assert page.status_code == 200, page.text
    fields = form_fields(page.text)
    r = client.post(
        oauth.CONSENT_PATH,
        data={**fields, **ticked, "decision": decision},
        headers={"Origin": ORIGIN},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return r.headers["location"]


def code_from(location: str) -> str:
    query = parse_qs(urlsplit(location).query)
    assert query["state"] == ["st-1"]
    assert query["iss"] == [ORIGIN]
    return query["code"][0]


def exchange(client: TestClient, client_id: str, code: str, verifier: str):
    return client.post("/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": RESOURCE,
    })


def connect(client: TestClient, sign_in, *, scope: str = store.SCOPE,
            **ticked: str) -> tuple[str, dict]:
    """The whole dance; the client id and the token response."""
    sign_in(client, EMAIL)
    client_id = register(client)["client_id"]
    verifier, challenge = pkce()
    consent = authorize(client, client_id, challenge, scope=scope)
    code = code_from(decide(client, consent, **ticked))
    r = exchange(client, client_id, code, verifier)
    assert r.status_code == 200, r.text
    return client_id, r.json()


def rpc(client: TestClient, token: str, method: str, params: dict | None = None,
        **headers):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
            **headers,
        },
    )


def initialize(client: TestClient, token: str):
    return rpc(client, token, "initialize", {
        "protocolVersion": PROTOCOL,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    })


# ------------------------------------------------------------------ metadata


def test_the_resource_names_this_site_as_its_authorization_server(site):
    r = site.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == RESOURCE
    assert body["authorization_servers"] == [ORIGIN]
    # What every call needs; edits are granted on the consent page, not asked.
    assert body["scopes_supported"] == [store.SCOPE]


def test_the_authorization_server_metadata_is_exact(site):
    body = site.get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == ORIGIN  # no trailing slash: compared as a string
    assert body["authorization_endpoint"] == f"{ORIGIN}/authorize"
    assert body["token_endpoint"] == f"{ORIGIN}/token"
    assert body["registration_endpoint"] == f"{ORIGIN}/register"
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "none" in body["token_endpoint_auth_methods_supported"]
    assert body["client_id_metadata_document_supported"] is True


def test_an_unauthenticated_call_points_at_the_resource_metadata(site):
    r = site.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
    assert "oauth-protected-resource/mcp" in r.headers["www-authenticate"]


# ------------------------------------------------------------------ the dance


def test_the_whole_flow_ends_in_a_working_token(site, sign_in, book):
    _, tokens = connect(site, sign_in)
    assert tokens["access_token"].startswith(store.ACCESS_PREFIX)
    assert tokens["refresh_token"].startswith(store.REFRESH_PREFIX)
    assert tokens["token_type"].lower() == "bearer"
    r = initialize(site, tokens["access_token"])
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "TopStocks"


def _tool_names(client: TestClient, token: str) -> set[str]:
    listed = rpc(client, token, "tools/list").json()["result"]["tools"]
    return {t["name"] for t in listed}


def test_a_client_asking_to_write_still_only_reads_unless_the_box_is_ticked(
    site, sign_in, book
):
    """Edits are the person's to grant, on the consent page; a client's own
    scope request decides nothing."""
    _, tokens = connect(site, sign_in, scope=" ".join(store.SCOPES))
    assert tokens["scope"].split() == [store.SCOPE]
    assert "delete_transactions" not in _tool_names(site, tokens["access_token"])
    (row,) = store.ledger().grants_for(EMAIL)
    assert row["write"] is False


def test_ticking_allow_edits_grants_the_write_scope(site, sign_in, book):
    sign_in(site, EMAIL)
    page = site.get(authorize(site, register(site)["client_id"], pkce()[1]))
    assert 'name="write"' in page.text and "checked" not in page.text
    _, tokens = connect(site, sign_in, write="1")
    assert set(tokens["scope"].split()) == set(store.SCOPES)
    assert "delete_transactions" in _tool_names(site, tokens["access_token"])
    assert any(row["write"] for row in store.ledger().grants_for(EMAIL))


def test_nothing_is_kept_in_the_clear(site, sign_in, book):
    _, tokens = connect(site, sign_in)
    on_disk = "".join(p.read_text() for p in store.DIR.rglob("*") if p.is_file())
    assert tokens["access_token"] not in on_disk
    assert tokens["refresh_token"] not in on_disk


def test_a_signed_out_browser_is_sent_to_sign_in_first(site):
    client_id = register(site)["client_id"]
    consent = authorize(site, client_id, pkce()[1])
    r = site.get(consent, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("/auth/login?next=")


def test_saying_no_sends_the_client_an_access_denied(site, sign_in):
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    location = decide(site, authorize(site, client_id, pkce()[1]), "deny")
    query = parse_qs(urlsplit(location).query)
    assert query["error"] == ["access_denied"]
    assert "code" not in query


def test_the_consent_page_names_the_client_and_where_it_returns(site, sign_in):
    sign_in(site, EMAIL)
    client_id = register(site, client_name="Evil <b>Corp</b>")["client_id"]
    page = site.get(authorize(site, client_id, pkce()[1]))
    assert "Evil &lt;b&gt;Corp&lt;/b&gt;" in page.text
    assert "127.0.0.1" in page.text
    assert EMAIL in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"


def test_the_consent_page_lets_its_own_post_carry_an_origin(site, sign_in):
    # `no-referrer` makes a browser send `Origin: null` on any POST, so the
    # decision would always fail the origin check.
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    page = site.get(authorize(site, client_id, pkce()[1]))
    assert page.headers["referrer-policy"] == "same-origin"


def test_the_consent_page_shows_copy_never_catalog_keys(site, sign_in):
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    page = site.get(authorize(site, client_id, pkce()[1]))
    assert "Your tax report" in page.text
    assert "connector." not in page.text


def test_a_decision_from_another_origin_is_refused(site, sign_in):
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    page = site.get(authorize(site, client_id, pkce()[1]))
    r = site.post(
        oauth.CONSENT_PATH,
        data={**form_fields(page.text), "decision": "allow"},
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_a_form_drawn_for_someone_else_is_refused(site, sign_in):
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    page = site.get(authorize(site, client_id, pkce()[1]))
    sign_in(site, "someone-else@example.com")
    r = site.post(
        oauth.CONSENT_PATH,
        data={**form_fields(page.text), "decision": "allow"},
        headers={"Origin": ORIGIN},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_the_wrong_verifier_gets_no_token(site, sign_in):
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    _, challenge = pkce()
    code = code_from(decide(site, authorize(site, client_id, challenge)))
    r = exchange(site, client_id, code, pkce()[0])
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_a_token_for_another_resource_is_never_asked_for(site, sign_in):
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    r = site.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": pkce()[1], "code_challenge_method": "S256",
        "state": "st-1", "resource": "https://elsewhere.example/mcp",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "error=invalid_target" in r.headers["location"]


def test_an_unregistered_redirect_is_never_followed(site):
    client_id = register(site)["client_id"]
    r = site.get("/authorize", params={
        "response_type": "code", "client_id": client_id,
        "redirect_uri": "https://evil.example/cb",
        "code_challenge": pkce()[1], "code_challenge_method": "S256",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert "evil.example" not in r.headers.get("location", "")


# ---------------------------------------------------------------- reuse


def test_a_code_works_once_and_a_replay_ends_the_grant(site, sign_in, book):
    sign_in(site, EMAIL)
    client_id = register(site)["client_id"]
    verifier, challenge = pkce()
    code = code_from(decide(site, authorize(site, client_id, challenge)))
    first = exchange(site, client_id, code, verifier)
    assert first.status_code == 200
    again = exchange(site, client_id, code, verifier)
    assert again.status_code == 400
    # The tokens the first exchange handed out die with the replay.
    assert initialize(site, first.json()["access_token"]).status_code == 401


def test_a_refresh_rotates_and_a_replayed_refresh_ends_the_grant(site, sign_in, book):
    client_id, tokens = connect(site, sign_in)
    refreshed = site.post("/token", data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": client_id,
    })
    assert refreshed.status_code == 200, refreshed.text
    new = refreshed.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    assert initialize(site, new["access_token"]).status_code == 200

    replay = site.post("/token", data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": client_id,
    })
    assert replay.status_code == 400
    assert initialize(site, new["access_token"]).status_code == 401


def test_a_revoked_token_stops_working(site, sign_in, book):
    client_id, tokens = connect(site, sign_in)
    r = site.post("/revoke", data={
        "token": tokens["refresh_token"], "client_id": client_id,
    })
    assert r.status_code == 200
    assert initialize(site, tokens["access_token"]).status_code == 401


# ------------------------------------------------------------- other doors


def test_the_site_api_token_is_nothing_here(site, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "s3cret-token")
    assert initialize(site, "s3cret-token").status_code == 401


def test_a_stray_host_is_refused_at_the_transport(site, sign_in, book):
    _, tokens = connect(site, sign_in)
    r = rpc(site, tokens["access_token"], "ping", Host="evil.example")
    assert r.status_code == 421


def test_registration_is_throttled_per_address(site):
    for _ in range(oauth.REGISTER_MAX):
        register(site)
    r = site.post("/register", json={"redirect_uris": [REDIRECT]})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1


def test_without_a_public_origin_the_connector_is_not_there(door, monkeypatch):
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    monkeypatch.setattr("stocks.web.server.secret", lambda *a, **k: "")
    app = Starlette(
        routes=[Route(p, door) for p in oauth.PATHS],
        lifespan=lambda app: door.lifespan(),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/.well-known/oauth-authorization-server").status_code == 404
        assert client.post("/mcp", json={}).status_code == 404


def test_the_lifespan_can_be_entered_twice(site, door):
    """The site's lifespan runs once per TestClient; the SDK's session manager
    runs once per instance — so each entry has to build its own."""
    app = Starlette(
        routes=[Route(p, door) for p in oauth.PATHS],
        lifespan=lambda app: door.lifespan(),
    )
    with TestClient(app, base_url=ORIGIN) as again:
        assert again.get("/.well-known/oauth-authorization-server").status_code == 200


# ---------------------------------------------------- client metadata documents

DOC_URL = "https://client.example/oauth/metadata.json"


def _document(**over) -> bytes:
    return json.dumps({
        "client_id": DOC_URL,
        "client_name": "Doc client",
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
        **over,
    }).encode()


def test_a_metadata_document_client_connects_without_registering(
    site, sign_in, book, monkeypatch
):
    from stocks.connector import clients

    fetched: list[str] = []

    async def fetch(url: str) -> bytes:
        fetched.append(url)
        return _document()

    monkeypatch.setattr(clients, "_fetch_document", fetch)
    sign_in(site, EMAIL)
    verifier, challenge = pkce()
    consent = authorize(site, DOC_URL, challenge)
    page = site.get(consent)
    assert "Doc client" in page.text
    code = code_from(decide(site, consent))
    r = exchange(site, DOC_URL, code, verifier)
    assert r.status_code == 200, r.text
    assert fetched == [DOC_URL]  # cached: one fetch for the whole dance


@pytest.mark.parametrize("doc", [
    _document(client_id="https://client.example/other.json"),
    _document(client_secret="s3cret"),
    _document(token_endpoint_auth_method="client_secret_post"),
    _document(redirect_uris=["myapp://callback"]),
    _document(redirect_uris=[]),
    b"not json",
])
def test_a_bad_metadata_document_is_no_client(site, monkeypatch, doc):
    from stocks.connector import clients

    async def fetch(url: str) -> bytes:
        return doc

    monkeypatch.setattr(clients, "_fetch_document", fetch)
    r = site.get("/authorize", params={
        "response_type": "code", "client_id": DOC_URL, "redirect_uri": REDIRECT,
        "code_challenge": pkce()[1], "code_challenge_method": "S256",
    }, follow_redirects=False)
    assert r.status_code == 400


@pytest.mark.parametrize("url", [
    "http://client.example/meta.json",
    "https://client.example:8443/meta.json",
    "https://client.example/",
    "https://user:pw@client.example/meta.json",
    "https://client.example/a/../meta.json",
    "https://client.example/meta.json#frag",
])
def test_only_plain_https_document_urls_are_fetched(url):
    from stocks.connector import clients

    assert not clients.document_url_allowed(url)


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1"])
def test_a_document_on_a_private_address_is_never_fetched(host):
    import asyncio

    from stocks.connector import clients

    with pytest.raises(clients.DocumentRefused):
        asyncio.run(clients._public_address(host))
