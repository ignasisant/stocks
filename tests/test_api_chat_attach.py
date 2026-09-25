"""A statement attached to a conversation, over HTTP.

What parsing, detection and validation do is tested where they live. What is
tested here is the pair of calls the drawer makes and the promises they carry:

* a preview writes nothing to the ledger, and says what committing it would;
* the rows the ledger already holds are held back rather than silently
  re-imported, and the preview is what offers them anyway;
* both calls leave the conversation saying what happened, so a client that
  reloads mid-import is not looking at a thread that never mentions the file;
* a commit refuses a batch with no broker, because the fees and custody views
  read the book by it, and refuses an action the ledger has no meaning for;
* the demo book goes on the first real import — an invented cost basis must
  never mix into a real one;
* every one of these is a write, and a bearer token never gets one.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.portfolio import demo
from stocks.portfolio.ledger import all_transactions

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

# A generic ledger export: one of the parsers owns it, so no model is asked.
CLEAN = """date,ticker,action,quantity,price,currency,fee,note
2024-01-02,AAPL,buy,10,100.00,EUR,1.00,revolut Apple
2024-02-01,MSFT,buy,5,200.00,EUR,1.00,revolut Microsoft
"""


def upload(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR", "language": "en"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No split lookup and no ISIN map: this file is about the HTTP surface."""
    monkeypatch.setattr("stocks.data.fetch.splits", lambda *a, **k: {})
    monkeypatch.setattr(
        "stocks.api.routes.chat_attach.symbol_for_isin", lambda *a, **k: None
    )


def attach(text: str = CLEAN, **extra) -> dict:
    return {"filename": "ledger.csv", "content": upload(text), **extra}


def committed(preview: dict, **extra) -> dict:
    """The commit body a client builds out of a preview it was just shown."""
    return {
        "filename": preview["filename"],
        "platform": preview["platform"],
        "broker": preview["broker"] or "revolut",
        "rows": [dict(row) for row in preview["fresh"]],
        **extra,
    }


# ------------------------------------------------------------------ preview


def test_a_preview_says_what_it_would_write_and_writes_nothing(
    client, account, signed_in
):
    payload = signed_in.post("/v1/chat/attachments", json=attach()).json()
    assert [r["ticker"] for r in payload["fresh"]] == ["AAPL", "MSFT"]
    assert payload["platform"], "a file a parser owns is named, not guessed at"
    assert not all_transactions(account.db), "a preview is not an import"


def test_the_preview_files_a_note_on_the_thread(client, account, signed_in):
    """A client that reloads between the preview and the button finds the
    conversation saying a file arrived — the card is not a turn, the note is."""
    payload = signed_in.post("/v1/chat/attachments", json=attach()).json()
    assert payload["message"]["action"] == "import"
    assert "ledger.csv" in payload["message"]["content"]

    cid = payload["conversation"]
    thread = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert thread["messages"][-1]["content"] == payload["message"]["content"]


def test_an_unknown_thread_is_refused_before_anything_is_read(
    client, account, signed_in
):
    response = signed_in.post(
        "/v1/chat/attachments", json=attach(conversation="nope")
    )
    assert response.status_code == 404


def test_rows_the_ledger_already_holds_are_held_back_not_re_imported(
    client, account, signed_in
):
    first = signed_in.post("/v1/chat/attachments", json=attach()).json()
    signed_in.post("/v1/chat/attachments/commit", json=committed(first))

    again = signed_in.post("/v1/chat/attachments", json=attach()).json()
    assert again["fresh"] == [], "the same export twice imports nothing by itself"
    assert [r["ticker"] for r in again["duplicates"]] == ["AAPL", "MSFT"]
    assert again["duplicates"][0]["why"], "a held-back row says why it was held"


def test_a_file_no_parser_owns_is_answered_rather_than_failed(
    client, account, signed_in, monkeypatch
):
    """An account with nothing to ask — no key, no free chain — still gets an
    answer: detection runs, the mapper is simply never reached."""
    monkeypatch.setattr(
        "stocks.api.routes.chat_attach.engine.attempts", lambda prefs: []
    )
    payload = signed_in.post(
        "/v1/chat/attachments", json=attach("nothing,useful\n1,2\n")
    ).json()
    assert payload["fresh"] == []
    assert payload["skipped"], "the file is accounted for, not silently dropped"
    assert payload["needs_broker"] is False, "nothing to file needs no origin"


def test_a_preview_is_a_write_so_a_bearer_token_never_gets_one(client, account):
    response = client.post(
        "/v1/chat/attachments", params=WHO, headers=AUTH, json=attach()
    )
    assert response.status_code == 403


# ------------------------------------------------------------------- commit


def test_the_rows_land_in_the_ledger_stamped_with_their_broker(
    client, account, signed_in
):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    payload = signed_in.post(
        "/v1/chat/attachments/commit", json=committed(preview, broker="revolut")
    ).json()

    rows = all_transactions(account.db)
    assert payload["imported"] == len(rows) == 2
    assert payload["total"] == 2
    assert all(tx.note.lower().startswith("revolut") for tx in rows)


def test_the_commit_files_its_receipt_and_the_undo_hint(client, account, signed_in):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    payload = signed_in.post(
        "/v1/chat/attachments/commit", json=committed(preview)
    ).json()
    cid = preview["conversation"]
    thread = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert thread["messages"][-1]["content"] == payload["message"]["content"]
    assert payload["message"]["action"] == "import"


def test_a_batch_with_no_broker_is_refused_rather_than_filed_anywhere(
    client, account, signed_in
):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    response = signed_in.post(
        "/v1/chat/attachments/commit", json=committed(preview, broker="  ")
    )
    assert response.status_code == 422
    assert not all_transactions(account.db)


def test_an_action_the_ledger_has_no_meaning_for_is_refused(
    client, account, signed_in
):
    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    body = committed(preview)
    body["rows"][0]["action"] = "teleport"
    response = signed_in.post("/v1/chat/attachments/commit", json=body)
    assert response.status_code == 422
    assert not all_transactions(account.db), "nothing lands from a refused batch"


def test_the_first_real_import_takes_the_demo_book_with_it(
    client, account, signed_in
):
    demo.seed(account.db)
    assert demo.active(account.db)

    preview = signed_in.post("/v1/chat/attachments", json=attach()).json()
    signed_in.post("/v1/chat/attachments/commit", json=committed(preview))

    rows = all_transactions(account.db)
    assert demo.without(rows) == rows, "an invented cost basis never mixes in"


def test_a_commit_is_a_write_so_a_bearer_token_never_gets_one(client, account):
    response = client.post(
        "/v1/chat/attachments/commit",
        params=WHO,
        headers=AUTH,
        json={
            "filename": "ledger.csv",
            "broker": "revolut",
            "rows": [
                {
                    "date": "2024-01-02",
                    "ticker": "AAPL",
                    "action": "buy",
                    "quantity": 1,
                    "price": 10,
                    "currency": "EUR",
                }
            ],
        },
    )
    assert response.status_code == 403
