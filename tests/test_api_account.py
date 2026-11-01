"""Erasing an account, exporting it, and filing feedback.

Small routers with one thing in common: each is a call that a bearer token
must never reach. A token names nobody and any holder can name any account,
so a token that could call these could erase every book on the deployment,
download a stranger's or file text against one.

What each *does* belongs to the modules underneath — `auth.delete_account`,
`web/exports.py`, `web/feedback.py` — and is tested with them. What is tested
here is the binding: the confirmation an irreversible action demands, and that
nothing happens on the way to a refusal.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app

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
def no_bucket(monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    monkeypatch.setattr("stocks.storage.enabled", lambda: False)


@pytest.fixture
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


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


def prefs_of(account) -> dict:
    return json.loads(account.prefs.read_text())


# ------------------------------------------------------------------ erasure


def test_erasing_needs_the_address_typed_back(client, account, signed_in):
    """A mistyped confirmation is a 422 and nothing is removed — the point of
    the confirmation is that this cannot happen by accident."""
    response = signed_in.request(
        "DELETE", "/v1/account", json={"confirm": "someone@else.com"}
    )
    assert response.status_code == 422
    assert account.watchlist.exists()


def test_erasing_removes_the_account(client, account, signed_in, monkeypatch):
    gone: list = []
    monkeypatch.setattr(
        "stocks.web.auth.delete_account", lambda paths: gone.append(paths.root)
    )
    response = signed_in.request("DELETE", "/v1/account", json={"confirm": EMAIL})
    assert response.status_code == 200
    assert gone == [account.root]
    # The browser still holds the session cookie, so the client is told where
    # to go next rather than left signed in to an account that is not there.
    assert response.json()["sign_out"] == "/auth/logout"


def test_the_address_is_matched_case_insensitively(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr("stocks.web.auth.delete_account", lambda paths: None)
    assert (
        signed_in.request(
            "DELETE", "/v1/account", json={"confirm": EMAIL.upper()}
        ).status_code
        == 200
    )


def test_a_refused_deletion_says_so_and_removes_nothing(
    client, account, signed_in, monkeypatch
):
    """`delete_account` refuses the owner and guest directories by raising.
    That is a 403 about what was asked, not a 500 about a crash."""

    def refuse(paths):
        raise ValueError("refusing to delete the owner or guest data")

    monkeypatch.setattr("stocks.web.auth.delete_account", refuse)
    response = signed_in.request("DELETE", "/v1/account", json={"confirm": EMAIL})
    assert response.status_code == 403
    assert account.watchlist.exists()


def test_a_token_cannot_erase_an_account(client, account):
    response = client.request(
        "DELETE",
        "/v1/account",
        params={"account": EMAIL},
        headers=AUTH,
        json={"confirm": EMAIL},
    )
    assert response.status_code == 403
    assert account.watchlist.exists()


# ------------------------------------------------------------------- export


def _bundle(response) -> zipfile.ZipFile:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="aguait-account-'
    )
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_the_export_bundles_what_the_account_holds_without_its_keys(
    client, account, signed_in
):
    """Every file the account has, as it is — except the settings, which go
    without the provider key typed in (and the dates around it): an export is
    a file people forward."""
    account.prefs.write_text(json.dumps({
        "currency": "EUR",
        "anthropic_key_enc": "gAAAAABn-not-for-export",
        "anthropic_key_saved_at": 1.0,
        "anthropic_key_first_at": 1.0,
        "notify_digest": False,
    }))
    account.chat.write_text(json.dumps({"conversations": []}))
    account.learnings.write_text("[]")
    bundle = _bundle(signed_in.get("/v1/account/export"))
    assert bundle.namelist() == [
        "README.txt", "watchlist.yaml", "prefs.json", "chat.json", "chat_learnings.json",
    ]
    assert json.loads(bundle.read("prefs.json")) == {
        "currency": "EUR", "notify_digest": False,
    }
    assert bundle.read("watchlist.yaml") == account.watchlist.read_bytes()
    assert bundle.read("chat.json") == account.chat.read_bytes()
    readme = bundle.read("README.txt").decode()
    assert "chat_learnings.json" in readme and "ledger.csv" not in readme


def test_the_export_carries_the_ledger_as_csv_not_as_a_database(
    client, account, signed_in
):
    from stocks.portfolio import ledger
    from stocks.portfolio.ledger import Transaction

    ledger.add(Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 2.0),
               path=account.db)
    bundle = _bundle(signed_in.get("/v1/account/export"))
    assert "ledger.csv" in bundle.namelist()
    assert "portfolio.db" not in bundle.namelist()
    [row] = csv.DictReader(io.StringIO(bundle.read("ledger.csv").decode()))
    assert (row["ticker"], row["action"], row["quantity"]) == ("AAPL", "buy", "10.0")
    assert "amount_eur" in row


def test_a_token_cannot_export_an_account(client, account):
    response = client.get("/v1/account/export", params={"account": EMAIL}, headers=AUTH)
    assert response.status_code == 403


def test_every_user_file_is_bundled_or_deliberately_left_out(account):
    """A file the app starts keeping for an account has to be in the export
    or named in `NOT_BUNDLED` with its reason — never silently missing."""
    from stocks.chat import memory
    from stocks.web import exports

    assert set(exports.bundled(account)) | exports.NOT_BUNDLED == set(accounts.USER_FILES)
    assert "devices.json" in exports.bundled(account)
    assert exports.NOT_BUNDLED == {"portfolio.db", memory.FILE, "push.json"}


# ----------------------------------------------------------------- feedback


def test_feedback_is_stored_against_this_account(
    client, account, signed_in, monkeypatch
):
    filed: list = []
    monkeypatch.setattr(
        "stocks.web.feedback.submit",
        lambda text, kind, page="", shot=None, sender=None, lang="": filed.append(
            (text, kind, page, sender, lang)
        ),
    )
    response = signed_in.post(
        "/v1/feedback",
        json={"text": "the chart is wrong", "kind": "bug", "page": "portfolio",
              "lang": "es"},
    )
    assert response.status_code == 201
    text, kind, page, sender, lang = filed[0]
    assert (text, kind, page, lang) == ("the chart is wrong", "bug", "portfolio", "es")
    # The account, not "guest": the sender is whoever the request signed in as.
    assert sender == account.root.name


def test_an_unreadable_screenshot_is_refused_not_stored(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(
        "stocks.web.feedback.submit",
        lambda *a, **k: pytest.fail("nothing should be stored"),
    )
    assert (
        signed_in.post(
            "/v1/feedback", json={"text": "hi", "shot": "not base64!!"}
        ).status_code
        == 422
    )


def test_a_screenshot_that_is_not_a_jpeg_is_refused(
    client, account, signed_in, monkeypatch
):
    import base64

    monkeypatch.setattr(
        "stocks.web.feedback.submit",
        lambda *a, **k: pytest.fail("nothing should be stored"),
    )
    html = base64.b64encode(b"<html><script>alert(1)</script>").decode()
    response = signed_in.post("/v1/feedback", json={"text": "hi", "shot": html})
    assert response.status_code == 422


def test_empty_feedback_is_not_a_submission(client, account, signed_in):
    assert signed_in.post("/v1/feedback", json={"text": ""}).status_code == 422


def test_a_token_cannot_file_feedback_for_somebody_else(client, account):
    response = client.post(
        "/v1/feedback", params={"account": EMAIL}, headers=AUTH,
        json={"text": "hello"},
    )
    assert response.status_code == 403
