"""A chat answer or a list of tickers shared by link: the frozen copy, the
routes, the link card.

The copy is cut once and stored outside the account (`web/shares.py`), so a
pruned thread cannot break a link already sent; a guest reads it, only its
owner takes it down, and deleting the account takes every link with it.
"""

# The API fixtures are borrowed from test_api_chat, and a test naming one as
# a parameter reads to ruff as redefining the import.
# ruff: noqa: F811

from __future__ import annotations

import json
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


def _book(path, *, answer_id: str = "a1", earlier: list | None = None,
          later: list | None = None) -> None:
    auth.save_book({"conversations": [{
        "id": "c1", "title": "t", "updated": STAMP,
        "messages": [
            *(earlier or []),
            {"role": "user", "content": QUESTION},
            {"role": "assistant", "content": ANSWER, "id": answer_id,
             "skills": ["tax"], "web": [{"title": "SEC", "url": "https://sec.gov"}],
             "debate": [{"side": "bull", "text": "Tus 30 acciones valen 4.200 €."},
                        {"side": "bear", "text": "Capex enorme."}],
             "steps": [{"tool": "positions", "arg": "", "out": "NVDA 30 @ 120"}],
             "learned": [{"op": "added", "id": "m1", "text": "secret"}],
             "provider": "gemini",
             "activities": [_surface("chart"), _surface("whatif")]},
            *(later or []),
        ],
    }], "active": "c1"}, path)


EARLIER = [
    {"role": "user", "content": "¿Cómo va NVDA en mi cartera?"},
    {"role": "assistant", "content": "Llevas 30 acciones que valen 4.200 €.", "id": "a0",
     "skills": ["growth"], "steps": [{"tool": "positions", "out": "NVDA 30"}],
     "activities": [_surface("chart"), _surface("whatif")]},
    {"role": "user", "content": "¿Y AMD?"},
    {"role": "assistant", "content": "", "id": "a00", "error": "timeout"},
    {"role": "user", "content": "¿Y el resultado de ayer?"},
]


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
    assert set(share) == {"id", "owner", "answer_id", "question", "content", "debate",
                          "turns", "web", "skills", "activities", "masked", "by",
                          "lang", "created"}
    assert share["turns"] == []
    assert "4.200" not in share["content"] and "30 acciones" not in share["question"]
    assert [d["side"] for d in share["debate"]] == ["bull", "bear"]
    assert "4.200" not in share["debate"][0]["text"], "the cases are masked too"
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


def test_a_link_made_before_the_cases_were_kept_gets_them_on_the_next_share(account):
    _book(account.chat)
    old = shares.create(account, "a1", masked=True, lang="es")
    path = shares.SHARES_DIR / f"{old['id']}.json"
    path.write_text(json.dumps({k: v for k, v in old.items() if k != "debate"}))
    again = shares.create(account, "a1", masked=True, lang="es")
    assert again["id"] == old["id"]
    assert [d["side"] for d in shares.load(old["id"])["debate"]] == ["bull", "bear"]


def test_the_thread_before_the_answer_goes_along_cut_the_same_way(account):
    later = [{"role": "user", "content": "¿Y TSM?"},
             {"role": "assistant", "content": "TSM sube.", "id": "a2"}]
    _book(account.chat, earlier=EARLIER, later=later)
    share = shares.create(account, "a1", masked=True, lang="es")
    turns = share["turns"]
    # The failed answer drops with its question, and so does the unanswered one.
    assert [t["question"] for t in turns] == ["¿Cómo va NVDA en mi cartera?"]
    assert "4.200" not in turns[0]["content"] and "acciones" in turns[0]["content"]
    assert [a["id"] for a in turns[0]["activities"]] == ["chart"]
    assert turns[0]["skills"] == ["growth"] and "steps" not in turns[0]
    assert "TSM" not in json.dumps(share), "what came after the answer stays home"
    unmasked = shares.preview(account, "a1", False)
    assert "4.200" in unmasked["turns"][0]["content"]
    assert [a["id"] for a in unmasked["turns"][0]["activities"]] == ["chart", "whatif"]


def test_a_long_thread_goes_as_its_last_exchanges(account):
    earlier = [m for n in range(shares._TURNS_MAX + 5)
               for m in ({"role": "user", "content": f"q{n}"},
                         {"role": "assistant", "content": f"r{n}", "id": f"x{n}"})]
    _book(account.chat, earlier=earlier)
    turns = shares.preview(account, "a1", True)["turns"]
    assert len(turns) == shares._TURNS_MAX
    assert turns[0]["question"] == "q5"
    assert turns[-1]["content"] == f"r{shares._TURNS_MAX + 4}"


def test_a_link_made_before_the_thread_was_kept_gets_it_on_the_next_share(account):
    _book(account.chat, earlier=EARLIER)
    old = shares.create(account, "a1", masked=True, lang="es")
    path = shares.SHARES_DIR / f"{old['id']}.json"
    path.write_text(json.dumps({k: v for k, v in old.items() if k != "turns"}))
    again = shares.create(account, "a1", masked=True, lang="es")
    assert again["id"] == old["id"]
    assert len(shares.load(old["id"])["turns"]) == 1


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
    (store / "someoneElse1.json").write_text(json.dumps(other))
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
    assert answer["debate"] == made["debate"] and len(made["debate"]) == 2
    assert answer["shared_from"] == made["id"] and answer["id"] not in ("", "a1")
    gone = signed_in.post("/v1/chat/conversations", json={"from_share": "missing123"})
    assert gone.status_code == 404


def test_carrying_on_from_a_link_takes_the_thread_above_it_too(account, signed_in):
    _book(account.chat, earlier=EARLIER)
    made = signed_in.post("/v1/chat/turns/a1/share", json={}).json()
    assert [t["question"] for t in made["turns"]] == ["¿Cómo va NVDA en mi cartera?"]
    cid = signed_in.post("/v1/chat/conversations",
                         json={"from_share": made["id"]}).json()["id"]
    thread = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert [m["role"] for m in thread["messages"]] == [
        "user", "assistant", "user", "assistant"]
    assert thread["messages"][1]["content"] == made["turns"][0]["content"]
    assert thread["messages"][1]["id"] not in ("", "a0")
    assert not thread["messages"][1].get("shared_from")
    assert thread["messages"][-1]["shared_from"] == made["id"]
    assert thread["title"] == "¿Cómo va NVDA en mi cartera?"


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


# -------------------------------------------------------------- the list


def test_the_account_lists_its_links_newest_first_and_revoke_drops_them(account):
    _book(account.chat)
    one = shares.create(account, "a1", masked=True, lang="es")
    one_open = shares.create(account, "a1", masked=False, lang="es")
    rows = shares.listed(account)
    assert [r["id"] for r in rows] == [one_open["id"], one["id"]]
    assert rows[1]["masked"] is True and rows[1]["question"] == one["question"]
    assert "30 acciones" not in rows[1]["question"], "a masked link is listed masked"
    shares.revoke(account, one["id"])
    assert shares.listed(account) == []


def test_the_list_survives_its_thread_being_pruned(account):
    _book(account.chat)
    share = shares.create(account, "a1", masked=True, lang="es")
    account.chat.unlink()
    assert [r["id"] for r in shares.listed(account)] == [share["id"]]
    assert shares.revoke(account, share["id"])
    assert shares.listed(account) == []


def test_an_account_that_shared_before_the_list_gets_it_from_its_stamps(account):
    _book(account.chat)
    share = shares.create(account, "a1", masked=True, lang="es")
    account.shares.unlink()
    assert [r["id"] for r in shares.listed(account)] == [share["id"]]
    assert account.shares.exists(), "built once, then read"


def test_the_list_endpoint_is_the_sharers_alone(account, signed_in):
    _book(account.chat)
    made = signed_in.post("/v1/chat/turns/a1/share", json={"masked": True}).json()
    r = signed_in.get("/v1/chat/shares")
    assert r.status_code == 200
    assert [(s["id"], s["masked"]) for s in r.json()] == [(made["id"], True)]
    assert set(r.json()[0]) == {"id", "kind", "answer_id", "question", "masked",
                                "created"}
    assert TestClient(fastapi_app).get("/v1/chat/shares").status_code in (401, 403)


# ------------------------------------------------------------ shared lists


def test_a_list_keeps_the_symbols_once_each_and_nothing_else(account):
    share = shares.create_list(
        account, ["nvda", " NVDA", "msft", "not a symbol!", "BTC-EUR"],
        "  Semis\n y  cripto ", "es", by="Ana")
    assert share["kind"] == "watchlist"
    assert share["tickers"] == ["NVDA", "MSFT", "BTC-EUR"]
    assert share["title"] == "Semis y cripto" and share["by"] == "Ana"
    assert share["masked"] is False and share["answer_id"] == ""
    assert shares.load(share["id"]) == share


def test_a_list_is_cut_at_its_cap_and_one_with_no_symbol_is_none(account):
    many = [f"T{i}" for i in range(shares.LIST_MAX + 10)]
    assert len(shares.create_list(account, many, "", "es")["tickers"]) == shares.LIST_MAX
    assert shares.create_list(account, ["!!", ""], "x", "es") is None


def test_the_same_list_under_the_same_name_is_the_same_link(account):
    def link(tickers: list[str], title: str) -> str:
        return shares.create_list(account, tickers, title, "es")["id"]

    first = link(["NVDA", "MSFT"], "Semis")
    assert link(["nvda", "msft"], "Semis") == first
    assert link(["NVDA", "MSFT"], "Otra") != first
    assert link(["MSFT", "NVDA"], "Semis") != first, "the order is the sharer's"


def test_taking_down_a_list_leaves_the_other_links_up(account):
    _book(account.chat)
    answer = shares.create(account, "a1", masked=True, lang="es")
    one = shares.create_list(account, ["NVDA"], "Uno", "es")
    two = shares.create_list(account, ["MSFT"], "", "es")
    assert shares.revoke(account, one["id"])
    assert shares.load(one["id"]) is None
    assert shares.load(two["id"]) is not None and shares.load(answer["id"]) is not None
    rows = shares.listed(account)
    assert [(r["id"], r["kind"], r["question"]) for r in rows] == [
        (two["id"], "watchlist", "MSFT"), (answer["id"], "answer", answer["question"])]
    assert shares.revoke(account, answer["id"])
    assert [r["id"] for r in shares.listed(account)] == [two["id"]]


def test_following_a_list_adds_whats_new_under_its_name(account):
    from stocks import watchlist as wl
    from stocks.config import load_watchlist

    wl.add_entry(account.watchlist, "NVDA")
    share = shares.create_list(account, ["NVDA", "MSFT"], "Semis", "es")
    assert shares.follow(account, share) == ["MSFT"]
    held = {h.ticker: h.tags for h in load_watchlist(account.watchlist)}
    assert (held["NVDA"], held["MSFT"]) == (["Semis"], ["Semis"])
    assert shares.follow(account, share) == [], "following twice adds nothing"


def test_a_list_is_made_previewed_and_followed_over_the_api(account, signed_in, store):
    preview = signed_in.post("/v1/shares", json={
        "tickers": ["nvda", "msft"], "title": "Semis", "preview": True})
    assert preview.status_code == 200
    assert preview.json()["id"] == "" and preview.json()["tickers"] == ["NVDA", "MSFT"]
    assert not store.exists() or not list(store.iterdir())
    bad = signed_in.post("/v1/shares", json={"tickers": ["!!"]})
    assert bad.status_code == 422
    made = signed_in.post("/v1/shares", json={"tickers": ["NVDA", "MSFT"],
                                               "title": "Semis"}).json()
    assert made["kind"] == "watchlist" and made["mine"] is True
    read = TestClient(fastapi_app).get(f"/v1/shares/{made['id']}").json()
    assert read["kind"] == "watchlist" and read["title"] == "Semis"
    assert read["question"] == "" and read["content"] == ""
    r = signed_in.post(f"/v1/shares/{made['id']}/follow")
    assert r.status_code == 200 and r.json() == {"added": ["NVDA", "MSFT"]}
    listed = signed_in.get("/v1/chat/shares").json()
    assert [(s["kind"], s["question"]) for s in listed] == [("watchlist", "Semis")]


def test_a_guest_cannot_make_or_follow_a_list(account, signed_in):
    made = signed_in.post("/v1/shares", json={"tickers": ["NVDA"]}).json()
    guest = TestClient(fastapi_app)
    assert guest.post("/v1/shares", json={"tickers": ["NVDA"]}).status_code in (401, 403)
    assert guest.post(f"/v1/shares/{made['id']}/follow").status_code in (401, 403)


def test_an_answer_cannot_be_followed_nor_a_list_carried_on(account, signed_in):
    _book(account.chat)
    answer = signed_in.post("/v1/chat/turns/a1/share", json={}).json()
    assert signed_in.post(f"/v1/shares/{answer['id']}/follow").status_code == 404
    assert signed_in.post("/v1/shares/missing123/follow").status_code == 404
    made = signed_in.post("/v1/shares", json={"tickers": ["NVDA"]}).json()
    r = signed_in.post("/v1/chat/conversations", json={"from_share": made["id"]})
    assert r.status_code == 404
