"""The Learn page over HTTP.

The curriculum is the same shipped files for everyone, so it reads without an
account; only the progress is an account's own, and it is a write — a session
may make it, a token or a guest may not.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts, learn
from stocks.api.app import app as fastapi_app
from stocks.api.routes.learn import PREF_DONE

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


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
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    return sign_in(client, EMAIL)


@pytest.fixture
def guest(monkeypatch):
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    paths = accounts.guest_paths()
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    return paths


FIRST = learn.paths()[0].lessons[0]
SECOND = learn.paths()[0].lessons[1]


# ------------------------------------------------------------------- reading


def test_the_curriculum_lists_every_path_in_order(client, account, signed_in):
    body = signed_in.get("/v1/learn", params={"lang": "es"}).json()
    assert [p["id"] for p in body["paths"]] == [p.id for p in learn.paths()]
    assert [ref["id"] for ref in body["paths"][0]["lessons"]] == list(
        learn.paths()[0].lessons
    )
    assert body["done"] == []
    assert body["terms"] == len(learn.glossary("es"))


def test_a_lesson_comes_in_the_language_asked(client, account, signed_in):
    es = signed_in.get(f"/v1/learn/lessons/{FIRST}", params={"lang": "es"}).json()
    en = signed_in.get(f"/v1/learn/lessons/{FIRST}", params={"lang": "en"}).json()
    assert es["title"] == learn.lesson(FIRST, "es").title
    assert en["title"] == learn.lesson(FIRST, "en").title
    assert es["before"] is None
    assert es["after"]["id"] == SECOND
    assert {t["id"] for t in es["terms"]} <= set(learn.lesson(FIRST, "es").terms)


def test_an_unknown_lesson_is_a_404(client, account, signed_in):
    assert signed_in.get("/v1/learn/lessons/no-such-lesson").status_code == 404


def test_the_glossary_links_a_term_to_its_lesson(client, account, signed_in):
    terms = signed_in.get("/v1/learn/glossary", params={"lang": "es"}).json()["terms"]
    assert len(terms) == len(learn.glossary("es"))
    taught = [t for t in terms if t["lesson"]]
    assert taught and all(learn.lesson(t["lesson"]["id"], "es") for t in taught)


def test_a_guest_reads_the_curriculum_and_gets_no_ticks(client, guest):
    """The demo's prefs file is shared: one visitor's ticks are not another's."""
    guest_paths = accounts.guest_paths()
    guest_paths.prefs.write_text(json.dumps({PREF_DONE: [FIRST]}))
    body = client.get("/v1/learn").json()
    assert body["paths"] and body["done"] == []
    lesson = client.get(f"/v1/learn/lessons/{FIRST}").json()
    assert lesson["done"] is False
    assert client.get("/v1/learn/glossary").status_code == 200


# ------------------------------------------------------------------- writing


def test_marking_a_lesson_read_keeps_it(client, account, signed_in):
    answer = signed_in.post("/v1/learn/progress", json={"lesson": FIRST})
    assert answer.status_code == 200
    assert answer.json()["done"] == [FIRST]
    assert accounts.load_prefs(account.prefs)[PREF_DONE] == [FIRST]
    assert signed_in.get("/v1/learn").json()["done"] == [FIRST]
    assert signed_in.get(f"/v1/learn/lessons/{FIRST}").json()["done"] is True


def test_unmarking_takes_it_back_and_leaves_the_rest(client, account, signed_in):
    signed_in.post("/v1/learn/progress", json={"lesson": FIRST})
    signed_in.post("/v1/learn/progress", json={"lesson": SECOND})
    answer = signed_in.post("/v1/learn/progress", json={"lesson": FIRST, "done": False})
    assert answer.json()["done"] == [SECOND]


def test_marking_twice_counts_once(client, account, signed_in):
    signed_in.post("/v1/learn/progress", json={"lesson": FIRST})
    answer = signed_in.post("/v1/learn/progress", json={"lesson": FIRST})
    assert answer.json()["done"] == [FIRST]


def test_a_retired_lesson_is_kept_on_disk_but_not_reported(client, account, signed_in):
    account.prefs.write_text(json.dumps({PREF_DONE: ["retired-lesson", FIRST]}))
    assert signed_in.get("/v1/learn").json()["done"] == [FIRST]


def test_an_unknown_lesson_cannot_be_marked(client, account, signed_in):
    answer = signed_in.post("/v1/learn/progress", json={"lesson": "no-such-lesson"})
    assert answer.status_code == 404


def test_progress_takes_no_other_fields(client, account, signed_in):
    answer = signed_in.post(
        "/v1/learn/progress", json={"lesson": FIRST, "account": "x@example.com"}
    )
    assert answer.status_code == 422


def test_a_token_may_not_mark_progress(client, account):
    answer = client.post(
        "/v1/learn/progress", params={"account": EMAIL}, json={"lesson": FIRST},
        headers=AUTH,
    )
    assert answer.status_code == 403
    assert PREF_DONE not in accounts.load_prefs(account.prefs)


def test_a_guest_may_not_mark_progress(client, guest):
    answer = client.post("/v1/learn/progress", json={"lesson": FIRST})
    assert answer.status_code == 401
