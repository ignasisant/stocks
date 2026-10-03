"""Profile's list of connected apps, and its "Revoke".

A session's only, both of them: the list says which assistants can read a
book, and a bearer token can name any account. What a grant *is* — hashes,
rotation, reuse — is `test_connector_store.py`'s; here is the binding.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.connector import store

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    return paths


def grant(email: str = EMAIL, kind: str = "cimd", name: str = "Claude") -> str:
    return store.ledger().issue(
        email=email, client_id="c", client_name=name, client_kind=kind,
        redirect_host="claude.ai",
    ).grant


def test_a_session_sees_its_own_connections(client, sign_in):
    mine = grant()
    grant(kind="dcr", name="Someone's script")
    grant("other@example.com")
    sign_in(client, EMAIL)
    body = client.get("/v1/connections").json()
    rows = {r["client_name"]: r for r in body["connections"]}
    assert set(rows) == {"Claude", "Someone's script"}
    assert rows["Claude"]["id"] == mine
    assert rows["Claude"]["verified"] is True
    assert rows["Someone's script"]["verified"] is False
    assert "token" not in json.dumps(body).lower()


def test_the_address_to_paste_is_null_while_the_connector_is_closed(client, sign_in):
    sign_in(client, EMAIL)
    assert client.get("/v1/connections").json()["url"] is None


def test_revoking_ends_the_connection(client, sign_in):
    gid = grant()
    sign_in(client, EMAIL)
    assert client.delete(f"/v1/connections/{gid}").status_code == 204
    assert client.get("/v1/connections").json()["connections"] == []


def test_somebody_elses_connection_is_not_found(client, sign_in):
    theirs = grant("other@example.com")
    sign_in(client, EMAIL)
    assert client.delete(f"/v1/connections/{theirs}").status_code == 404
    assert len(store.ledger().grants_for("other@example.com")) == 1


def test_a_malformed_id_never_reaches_the_ledger(client, sign_in):
    sign_in(client, EMAIL)
    assert client.delete("/v1/connections/..%2F..%2Fgrants").status_code in (404, 422)


@pytest.mark.parametrize("method, path", [
    ("GET", "/v1/connections"), ("DELETE", "/v1/connections/g_00"),
])
def test_a_token_can_neither_list_nor_revoke(client, method, path):
    r = client.request(method, path, params={"account": EMAIL}, headers=AUTH)
    assert r.status_code == 403


@pytest.mark.parametrize("method, path", [
    ("GET", "/v1/connections"), ("DELETE", "/v1/connections/g_00"),
])
def test_an_anonymous_caller_is_turned_away(client, method, path):
    assert client.request(method, path).status_code == 401
