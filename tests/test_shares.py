"""A chat answer shared by link: the frozen copy, the routes, the link card.

The copy is cut once and stored outside the account (`web/shares.py`), so a
pruned thread cannot break a link already sent; a guest reads it, only its
owner takes it down, and deleting the account takes every link with it.
"""

# The API fixtures are borrowed from test_api_chat, and a test naming one as
# a parameter reads to ruff as redefining the import.
# ruff: noqa: F811

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from stocks.api.app import app as fastapi_app
from stocks.chat import a2ui
from stocks.web import auth, shares

from .test_api_chat import (  # noqa: F401 — fixtures
    EMAIL,
    account,
    client,
    signed_in,
    token,
)

STAMP = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="seconds")
QUESTION = "¿Cuánto gano si vendo 30 acciones de NVDA?"
ANSWER = "Venderías 30 acciones por 4.200 € y ganarías un 12 % sobre coste."


def _surface(sid: str) -> dict:
    parts = [a2ui.component("root", "Column", children=["t"]),
             a2ui.component("t", "Text", text="x")]
    return a2ui.activity(sid, a2ui.surface(sid, parts, {}))


def _book(path, *, answer_id: str = "a1") -> None:
    auth.save_book({"conversations": [{
        "id": "c1", "title": "t", "updated": STAMP,
        "messages": [
            {"role": "user", "content": QUESTION},
            {"role": "assistant", "content": ANSWER, "id": answer_id,
             "skills": ["tax"], "web": [{"title": "SEC", "url": "https://sec.gov"}],
             "steps": [{"tool": "positions", "arg": "", "out": "NVDA 30 @ 120"}],
             "learned": [{"op": "added", "id": "m1", "text": "secret"}],
             "provider": "gemini",
             "activities": [_surface("chart"), _surface("whatif")]},
        ],
    }], "active": "c1"}, path)


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(shares, "SHARES_DIR", tmp_path / "shares")
    monkeypatch.setattr(shares.storage, "persist", lambda path: None)
    monkeypatch.setattr(shares.storage, "restore", lambda path: False)
    return tmp_path / "shares"


# ------------------------------------------------------------------- store


def test_the_copy_holds_the_answer_cut_and_nothing_private(account):
    _book(account.chat)
    share = shares.create(account, "a1", masked=True, lang="es")
    assert set(share) == {"id", "owner", "answer_id", "question", "content", "web",
                          "skills", "activities", "masked", "by", "lang", "created"}
    assert "4.200" not in share["content"] and "30 acciones" not in share["question"]
    assert "12 %" in share["content"]
    assert [a["id"] for a in share["activities"]] == ["chart"]
    assert shares.load(share["id"]) == share


def test_the_same_cut_is_the_same_link_and_the_other_cut_a_second_one(account):
    _book(account.chat)
    first = shares.create(account, "a1", masked=True, lang="es")
    assert shares.create(account, "a1", masked=True, lang="es")["id"] == first["id"]
    open_ = shares.create(account, "a1", masked=False, lang="es")
    assert open_["id"] != first["id"]
    assert "4.200" in open_["content"]
    stamped = auth.find_answer("a1", account.chat)["answer"]["shares"]
    assert {(k["id"], k["masked"]) for k in stamped} == {
        (first["id"], True), (open_["id"], False)}
    assert shares.load(first["id"]) is not None, "a link already sent keeps working"


def test_a_link_outlives_the_thread_it_came_from(account):
    _book(account.chat)
    share = shares.create(account, "a1", masked=True, lang="es")
    auth.delete_conversation("c1", account.chat)
    assert shares.load(share["id"])["content"] == share["content"]


def test_revoke_takes_down_every_link_and_only_for_its_owner(account, tmp_path):
    _book(account.chat)
    one = shares.create(account, "a1", masked=True, lang="es")
    two = shares.create(account, "a1", masked=False, lang="es")
    stranger = auth.accounts.paths_in(tmp_path / "users" / "someone")
    assert not shares.revoke(stranger, one["id"])
    assert shares.revoke(account, one["id"])
    assert shares.load(one["id"]) is None and shares.load(two["id"]) is None
    assert "shares" not in auth.find_answer("a1", account.chat)["answer"]


def test_purge_owner_deletes_only_that_accounts_links(account, store):
    _book(account.chat)
    mine = shares.create(account, "a1", masked=True, lang="es")
    other = dict(mine, id="someoneElse1", owner="other")
    shares.atomic.write_json(store / "someoneElse1.json", other)
    assert shares.purge_owner(shares.owner_of(account)) == 1
    assert shares.load(mine["id"]) is None
    assert shares.load("someoneElse1") is not None


def test_an_id_that_is_not_one_reads_as_nothing():
    assert shares.load("../../etc/passwd") is None
    assert shares.load("") is None


# ------------------------------------------------------------------- API


def test_preview_publishes_nothing(account, signed_in, store):
    _book(account.chat)
    r = signed_in.post("/v1/chat/turns/a1/share", json={"preview": True})
    assert r.status_code == 200
    assert r.json()["masked"] is True and r.json()["id"] == ""
    assert not store.exists() or not list(store.iterdir())


def test_a_guest_reads_a_link_and_cannot_make_one(account, signed_in):
    _book(account.chat)
    made = signed_in.post("/v1/chat/turns/a1/share", json={"masked": True}).json()
    assert made["mine"] is True
    guest = TestClient(fastapi_app)
    r = guest.get(f"/v1/shares/{made['id']}")
    assert r.status_code == 200
    assert r.json()["question"] == made["question"] and r.json()["mine"] is False
    assert guest.post("/v1/chat/turns/a1/share", json={}).status_code in (401, 403)
    assert guest.delete(f"/v1/chat/shares/{made['id']}").status_code in (401, 403)


def test_unknown_answer_and_taken_down_link_are_404(account, signed_in):
    _book(account.chat)
    assert signed_in.post("/v1/chat/turns/nope/share", json={}).status_code == 404
    made = signed_in.post("/v1/chat/turns/a1/share", json={}).json()
    assert signed_in.delete(f"/v1/chat/shares/{made['id']}").status_code == 204
    assert signed_in.get(f"/v1/shares/{made['id']}").status_code == 404
    assert signed_in.delete(f"/v1/chat/shares/{made['id']}").status_code == 404


def test_carrying_on_from_a_link_starts_a_thread_of_ones_own(account, signed_in):
    _book(account.chat, answer_id="a1")
    made = signed_in.post("/v1/chat/turns/a1/share", json={}).json()
    r = signed_in.post("/v1/chat/conversations", json={"from_share": made["id"]})
    assert r.status_code == 201
    thread = signed_in.get(f"/v1/chat/conversations/{r.json()['id']}").json()
    user, answer = thread["messages"]
    assert user["content"] == made["question"]
    assert answer["content"] == made["content"]
    assert answer["shared_from"] == made["id"] and answer["id"] not in ("", "a1")
    gone = signed_in.post("/v1/chat/conversations", json={"from_share": "missing123"})
    assert gone.status_code == 404


def test_a_link_is_signed_with_the_sharers_first_name_only(account):
    _book(account.chat)
    assert shares.sharer({"name": "Ana María López"}) == "Ana"
    assert shares.sharer({"name": "  "}) == "" and shares.sharer(None) == ""
    share = shares.create(account, "a1", masked=True, lang="es", by="Ana")
    assert share["by"] == "Ana"
    assert shares.preview(account, "a1", True, "Ana")["by"] == "Ana"


def test_a_link_comes_down_after_its_thread_was_pruned(account):
    _book(account.chat)
    share = shares.create(account, "a1", masked=True, lang="es")
    account.chat.unlink()
    assert shares.revoke(account, share["id"]) is True
    assert shares.load(share["id"]) is None
