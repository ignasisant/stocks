"""The conversational walkthrough, over HTTP.

What the walkthrough *is* — which steps, which copy, what counts as done — is
the registry's (`web/onboarding.py`) and is tested there, and the Streamlit
rendering of it in `test_guide.py`. What is tested here is that the HTTP
binding keeps the promises that make it the *same* walkthrough:

* one state: the same prefs keys and the same thread, so a reader who starts
  in one front end finds it where they left it in the other;
* a card is written once, however often a client syncs;
* a step the account has already switched on is walked past with a receipt;
* only an automatic open spends one of the three, and a fourth is refused;
* finishing stamps the tour done and the release seen, so no modal follows;
* every move is a write, and a bearer token never gets one.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.web import guide, onboarding

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def chat_surface(monkeypatch):
    monkeypatch.setattr(guide, "surface", lambda: "chat")


@pytest.fixture(autouse=True)
def narrator(monkeypatch):
    """No provider answers unless a test says what it answers.

    The first Next carries the walkthrough's one generated line, and a real
    free chain behind it would put the network into every test that advances.
    Returns the list of lines to hand out, in order; empty means silence.
    """

    class Lines(list):
        calls: list[dict]

    lines = Lines()
    lines.calls = []

    def complete(prefs, system, messages, timeout, **kwargs):
        lines.calls.append({"system": system, "messages": messages, **kwargs})
        return lines.pop(0) if lines else None

    monkeypatch.setattr("stocks.chat.engine.complete_attempts", complete)
    return lines


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
    return sign_in(client, EMAIL)


@pytest.fixture
def switched_on(monkeypatch):
    """No step is switched on unless a test says so.

    Patched on the registry: `Step.done` holds the function captured when
    STEPS was built, so replacing the detector would not reach it.
    """
    marks: dict[str, bool] = {}
    monkeypatch.setattr(onboarding, "STEPS", tuple(
        dataclasses.replace(
            s, done=(lambda _p, _paths=None, _id=s.id: marks.get(_id, False))
        ) if s.done is not None else s
        for s in onboarding.STEPS
    ))
    return marks


def prefs(account) -> dict:
    return json.loads(account.prefs.read_text())


def thread(signed_in, cid: str) -> list[dict]:
    return signed_in.get(f"/v1/chat/conversations/{cid}").json()["messages"]


def first() -> str:
    return guide.steps()[0].id


def test_a_new_account_is_owed_the_walkthrough(client, account, signed_in, switched_on):
    body = signed_in.get("/v1/guide").json()
    assert body["surface"] == "chat"
    assert body["active"] is False and body["auto_open"] is True


def test_starting_writes_the_first_card_into_its_own_thread(
    client, account, signed_in, switched_on
):
    body = signed_in.post("/v1/guide/start", json={"auto": True}).json()
    assert body["active"] and body["step"]["id"] == first()
    assert body["changed"] is True
    turns = thread(signed_in, body["thread"])
    assert [t["guide"] for t in turns] == [{"step": first()}]
    # The same keys the Streamlit guide reads: one walkthrough, two doors.
    stored = prefs(account)
    assert stored[guide.PREF_STEP] == first()
    assert stored[guide.PREF_THREAD] == body["thread"]
    assert stored[guide.PREF_OPENS] == 1


def test_syncing_twice_never_writes_the_same_card_twice(
    client, account, signed_in, switched_on
):
    cid = signed_in.post("/v1/guide/start", json={}).json()["thread"]
    again = signed_in.post("/v1/guide/sync", json={}).json()
    assert again["changed"] is False
    assert len(thread(signed_in, cid)) == 1


def test_a_step_already_switched_on_is_walked_past_with_a_receipt(
    client, account, signed_in, switched_on
):
    on = next(s for s in guide.steps() if s.done is not None)
    switched_on[on.id] = True
    body = signed_in.post("/v1/guide/start", json={"step": on.id}).json()
    turns = thread(signed_in, body["thread"])
    assert turns[0]["guide"] == {"step": on.id, "state": "done"}
    assert body["step"]["id"] != on.id


def test_next_moves_one_step_on_and_draws_its_card(
    client, account, signed_in, switched_on
):
    cid = signed_in.post("/v1/guide/start", json={}).json()["thread"]
    body = signed_in.post("/v1/guide/advance", json={}).json()
    assert body["index"] == 2
    assert [t["guide"]["step"] for t in thread(signed_in, cid)] == [
        first(), guide.steps()[1].id
    ]


def test_only_an_automatic_open_spends_one_and_a_fourth_is_refused(
    client, account, signed_in, switched_on
):
    signed_in.post("/v1/guide/start", json={"step": first()})
    assert prefs(account).get(guide.PREF_OPENS, 0) == 0, "asked for, not spent"
    for _ in range(guide.MAX_AUTO_OPENS):
        assert signed_in.post("/v1/guide/start", json={"auto": True}).status_code == 200
    assert signed_in.get("/v1/guide").json()["auto_open"] is False
    assert signed_in.post("/v1/guide/start", json={"auto": True}).status_code == 409


def test_finishing_stamps_the_tour_and_the_release_so_no_modal_follows(
    client, account, signed_in, switched_on
):
    signed_in.post("/v1/guide/start", json={})
    body = signed_in.post("/v1/guide/finish", json={"reason": "skipped"}).json()
    assert body["finished"] and not body["active"] and not body["auto_open"]
    stored = prefs(account)
    assert stored[onboarding.PREF_DONE] is True
    assert stored[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION


def test_next_from_the_last_step_finishes(client, account, signed_in, switched_on):
    last = guide.steps()[-1].id
    signed_in.post("/v1/guide/start", json={"step": last})
    body = signed_in.post("/v1/guide/advance", json={}).json()
    assert body["finished"] is True


def test_an_unknown_step_is_refused(client, account, signed_in, switched_on):
    assert signed_in.post(
        "/v1/guide/start", json={"step": "nope"}
    ).status_code == 404


def test_the_modal_surface_is_owed_nothing_here(
    client, account, signed_in, switched_on, monkeypatch
):
    monkeypatch.setattr(guide, "surface", lambda: "modal")
    assert signed_in.get("/v1/guide").json()["auto_open"] is False


def test_moving_the_guide_is_a_write_so_a_token_may_not(client, account):
    response = client.post(
        "/v1/guide/start", params=WHO, headers=AUTH, json={"auto": True}
    )
    assert response.status_code == 403


# ------------------------------------------------------------ the narration


def test_the_first_next_adds_one_line_about_the_account(
    client, account, signed_in, switched_on, narrator
):
    """`guide.narrate`, over HTTP: a note under the second step's card."""
    narrator.append("Start with your broker statement: no ledger, no book.")
    cid = signed_in.post("/v1/guide/start", json={}).json()["thread"]
    body = signed_in.post("/v1/guide/advance", json={}).json()
    assert body["changed"] is True
    turns = thread(signed_in, cid)
    assert turns[-1]["guide"] == {"step": guide.steps()[1].id, "state": "note"}
    assert turns[-1]["content"].startswith("Start with your broker statement")
    assert prefs(account)[guide.PREF_NARRATED] is True
    # Counts, not holdings: the facts are what the Streamlit guide sends.
    assert narrator.calls[0]["messages"][0]["content"].startswith(
        "watchlist_tickers=1;"
    )


def test_a_silent_chain_costs_the_walkthrough_nothing_and_is_not_retried(
    client, account, signed_in, switched_on, narrator
):
    cid = signed_in.post("/v1/guide/start", json={}).json()["thread"]
    signed_in.post("/v1/guide/advance", json={})
    assert [t["guide"].get("state") for t in thread(signed_in, cid)] == [None, None]
    assert prefs(account)[guide.PREF_NARRATED] is True
    signed_in.post("/v1/guide/advance", json={})
    assert len(narrator.calls) == 1  # attempted once per account, ever


def test_a_session_only_key_reaches_the_narration(
    client, account, signed_in, switched_on, narrator
):
    """A reader whose key lives in their tab gets the line on that key."""
    signed_in.post("/v1/guide/start", json={})
    signed_in.post(
        "/v1/guide/advance",
        json={},
        headers={"X-Chat-Provider": "anthropic", "X-Chat-Key": "sk-ant-sessiononly"},
    )
    assert narrator.calls[0]["session_keys"] == {"anthropic": "sk-ant-sessiononly"}
    assert "sk-ant-sessiononly" not in account.prefs.read_text()
