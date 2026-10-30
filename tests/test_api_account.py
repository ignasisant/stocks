"""Erasing an account, linking a chat, and filing feedback.

Three small routers with one thing in common: each is a write that a bearer
token must never reach. A token names nobody and any holder can name any
account, so a token that could call these could erase every book on the
deployment, aim the bot at a chat it chose, or file text against a stranger.

What each *does* belongs to the modules underneath — `auth.delete_account`,
`notify/telegram.py`, `web/feedback.py` — and is tested with them. What is
tested here is the binding: the confirmation an irreversible action demands,
the states the linking dance can be in, and that nothing happens on the way to
a refusal.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from stocks import accounts, revocation
from stocks.api.app import app as fastapi_app
from stocks.api.routes import notify as notify_routes
from stocks.notify import telegram

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
        "telegram_chat_id": "42",
    }))
    account.chat.write_text(json.dumps({"conversations": []}))
    account.learnings.write_text("[]")
    bundle = _bundle(signed_in.get("/v1/account/export"))
    assert bundle.namelist() == [
        "README.txt", "watchlist.yaml", "prefs.json", "chat.json", "chat_learnings.json",
    ]
    assert json.loads(bundle.read("prefs.json")) == {
        "currency": "EUR", "telegram_chat_id": "42",
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


# ----------------------------------------------------------------- telegram


@pytest.fixture(autouse=True)
def _no_bot_updates(monkeypatch):
    """A pending code makes the polling route read the bot's updates; never
    from the network here."""
    monkeypatch.setattr(telegram, "get_updates", lambda timeout=0: [])


def _start(code: str, chat_id: int = 777, username: str = "ada") -> dict:
    return {
        "update_id": 1,
        "message": {
            "text": f"/start {code}",
            "chat": {"id": chat_id, "username": username},
        },
    }


def test_a_poll_completes_the_link_from_the_bots_updates(
    client, account, signed_in, monkeypatch
):
    """No webhook Worker is deployed, so no job ever reads "/start <code>":
    the polling route has to find it itself or the spinner never stops."""
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "bot_username", lambda: "topstocksbot")
    monkeypatch.setattr(telegram, "deep_link", lambda code: f"https://t.me/b?start={code}")
    sent: list[tuple] = []
    monkeypatch.setattr(
        telegram, "send_message", lambda text, chat_id, **kw: sent.append((text, chat_id))
    )
    code = signed_in.post("/v1/notify/telegram").json()["code"]
    updates = [_start("someone-else", 1), _start(code)]
    monkeypatch.setattr(telegram, "get_updates", lambda timeout=0: updates)
    body = signed_in.get("/v1/notify/telegram").json()
    assert (body["linked"], body["pending"], body["username"]) == (True, False, "ada")
    stored = prefs_of(account)
    assert stored["telegram_chat_id"] == 777
    assert stored.get("tg_link_code") is None
    # The welcome promises what this road delivers — no chat without the Worker.
    assert len(sent) == 1 and sent[0][1] == 777
    assert "/help" not in sent[0][0]


def test_a_poll_without_its_start_stays_pending(client, account, signed_in, monkeypatch):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "bot_username", lambda: "topstocksbot")
    monkeypatch.setattr(telegram, "deep_link", lambda code: f"https://t.me/b?start={code}")
    signed_in.post("/v1/notify/telegram")
    monkeypatch.setattr(telegram, "get_updates", lambda timeout=0: [_start("other")])
    body = signed_in.get("/v1/notify/telegram").json()
    assert (body["linked"], body["pending"]) == (False, True)


def test_a_failing_update_read_leaves_the_poll_pending(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "bot_username", lambda: "topstocksbot")
    monkeypatch.setattr(telegram, "deep_link", lambda code: f"https://t.me/b?start={code}")
    signed_in.post("/v1/notify/telegram")

    def down(timeout=0):
        raise RuntimeError("telegram getUpdates failed")

    monkeypatch.setattr(telegram, "get_updates", down)
    response = signed_in.get("/v1/notify/telegram")
    assert response.status_code == 200
    assert response.json()["pending"] is True


def test_the_test_message_goes_to_the_linked_chat(
    client, account, signed_in, monkeypatch
):
    """send_message takes the text first: the chat id went in as the text
    and the text as the chat id, so every test send failed "chat not found"."""
    monkeypatch.setattr(telegram, "configured", lambda: True)
    accounts.update_prefs(account.prefs, {"telegram_chat_id": 42})
    sent: list[tuple] = []
    monkeypatch.setattr(
        telegram, "send_message", lambda text, chat_id, **kw: sent.append((text, chat_id))
    )
    assert signed_in.post("/v1/notify/telegram/test").status_code == 200
    assert sent == [("✅ TopStocks", "42")]


def test_an_unconfigured_deployment_says_so_rather_than_failing(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(telegram, "configured", lambda: False)
    body = signed_in.get("/v1/notify/telegram").json()
    assert body["configured"] is False
    assert (body["linked"], body["pending"]) == (False, False)
    # And refuses to issue a code for a bot that is not there.
    assert signed_in.post("/v1/notify/telegram").status_code == 503


def test_linking_issues_a_code_and_remembers_it(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "bot_username", lambda: "topstocksbot")
    monkeypatch.setattr(telegram, "deep_link", lambda code: f"https://t.me/b?start={code}")
    body = signed_in.post("/v1/notify/telegram").json()
    assert body["deep_link"].endswith(body["code"])
    assert body["bot"] == "@topstocksbot"
    # The code lands in prefs because the process that matches it is the chat
    # job, not this one.
    assert prefs_of(account)["tg_link_code"] == body["code"]
    assert signed_in.get("/v1/notify/telegram").json()["pending"] is True


def test_a_lapsed_code_is_no_longer_pending(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    accounts.update_prefs(
        account.prefs,
        {"tg_link_code": "old", "tg_link_ts": 0},  # issued at the epoch
    )
    assert signed_in.get("/v1/notify/telegram").json()["pending"] is False


def test_a_pending_link_can_be_resumed_after_a_tab_switch(
    client, account, signed_in, monkeypatch
):
    """The state carries the outstanding code and its link. Without them a
    reader who switched tabs mid-dance can only start over, and the server
    would hand them a second code for the same attempt."""
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "bot_username", lambda: "topstocksbot")
    monkeypatch.setattr(
        telegram, "deep_link", lambda code: f"https://t.me/b?start={code}"
    )
    issued = signed_in.post("/v1/notify/telegram").json()
    resumed = signed_in.get("/v1/notify/telegram").json()
    assert resumed["code"] == issued["code"]
    assert resumed["deep_link"] == issued["deep_link"]


def test_a_lapsed_code_is_not_offered_again(client, account, signed_in, monkeypatch):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    accounts.update_prefs(account.prefs, {"tg_link_code": "old", "tg_link_ts": 0})
    body = signed_in.get("/v1/notify/telegram").json()
    assert body["pending"] is False
    assert body["code"] is None and body["deep_link"] is None


def test_testing_a_link_that_does_not_exist_is_a_409(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    assert signed_in.post("/v1/notify/telegram/test").status_code == 409


def test_a_provider_that_refuses_the_message_is_not_a_500(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    accounts.update_prefs(account.prefs, {"telegram_chat_id": 42})

    def boom(text, chat_id, **kw):
        raise RuntimeError("chat not found")

    monkeypatch.setattr(telegram, "send_message", boom)
    response = signed_in.post("/v1/notify/telegram/test")
    assert response.status_code == 502
    # The provider's own words, unprefixed: the client frames it with
    # `profile.tg_test_failed`, and saying it twice read as a stutter.
    assert response.json()["detail"] == "chat not found"


def test_a_linked_chat_names_its_handle(client, account, signed_in, monkeypatch):
    """The @username the link job recorded, which the Profile page prints
    beside "connected" — and nothing once the chat is gone, so the next link
    does not come back wearing the previous chat's name."""
    monkeypatch.setattr(telegram, "configured", lambda: True)
    accounts.update_prefs(
        account.prefs, {"telegram_chat_id": "42", "telegram_username": "ada"}
    )
    assert signed_in.get("/v1/notify/telegram").json()["username"] == "ada"
    body = signed_in.request("DELETE", "/v1/notify/telegram").json()
    assert body["username"] is None
    assert prefs_of(account).get("telegram_username") is None


def test_a_chat_without_a_public_username_names_nobody(
    client, account, signed_in, monkeypatch
):
    monkeypatch.setattr(telegram, "configured", lambda: True)
    accounts.update_prefs(account.prefs, {"telegram_chat_id": "42"})
    body = signed_in.get("/v1/notify/telegram").json()
    assert body["linked"] is True and body["username"] is None


def test_unlinking_keeps_the_switches(client, account, signed_in, monkeypatch):
    """A reader who disconnects and comes back should find the three toggles
    the way they left them — clearing them here would turn notifications on
    for everybody who ever unlinked."""
    monkeypatch.setattr(telegram, "configured", lambda: True)
    accounts.update_prefs(
        account.prefs,
        {"telegram_chat_id": 42, "notify_digest": False, "notify_weekly": False},
    )
    body = signed_in.request("DELETE", "/v1/notify/telegram").json()
    assert body["linked"] is False
    stored = prefs_of(account)
    assert stored["telegram_chat_id"] is None
    assert stored["notify_digest"] is False
    assert stored["notify_weekly"] is False


def test_the_polling_read_looks_in_the_bucket_first(
    client, account, signed_in, monkeypatch
):
    """The chat id is written by another process entirely. A local-only read is
    a spinner that never stops."""
    seen: list = []
    monkeypatch.setattr("stocks.storage.enabled", lambda: True)
    monkeypatch.setattr(
        notify_routes.storage, "restore", lambda path: seen.append(path)
    )
    signed_in.get("/v1/notify/telegram")
    # The session check restores its own revocation list on first touch.
    assert [p for p in seen if p.parent != revocation.DIR] == [account.prefs]


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
