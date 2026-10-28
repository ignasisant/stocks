"""Two accounts, one assistant: nothing one of them told it reaches the other.

The app is multi-user, and every way the assistant knows a reader is a file
under that reader's own directory: the investor profile in prefs, the saved
memories, the exit rules in the decision journal, the threads and the index of
past conversations that `earlier()` searches on every turn. A prompt built from
the wrong directory — a path resolved once and cached, a module-level memo
keyed by something other than the account, a background thread that outlived
its request — would hand one reader's notes to the other's model, and nothing
on screen would show it.

So these tests plant a unique word in each of Alice's stores, run Bob's turns
over HTTP with a backend that records every system prompt and message it is
sent (the answer, the guard, the memory extraction alike), and assert the word
never appears there. Each test first runs the same question as Alice and finds
the word in *her* prompt: a test that never got the secret into any prompt
would pass for the wrong reason.

The ids are checked too: Bob naming one of Alice's thread, turn or memory ids
gets the 404 an unknown id gets, and Alice's data is untouched afterwards.
"""

from __future__ import annotations

import json
import threading
from datetime import date

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.chat import engine, journal, learnings, memory

ALICE, BOB = "alice@example.com", "bob@example.com"
# One word per store, so a failure names the store that leaked.
SECRET = {
    "profile": "kestrelprofile7741",
    "memory": "kestrelmemory7741",
    "criteria": "kestrelcriteria7741",
    "thread": "kestrelthread7741",
}

# Both hold the same name, so a lookup by ticker (the exit rules, the recall of
# earlier conversations) has something to match in either account.
WATCHLIST = """\
watchlist:
  - ticker: NVDA
    name: NVIDIA
"""
PREFS = {"currency": "EUR", "chat_skills_mode": "off", "language": "es"}
QUESTION = "¿Qué te conté de NVDA y de mi plan con ella? Recuérdame mis reglas."


class Recorder:
    """A backend that writes down everything it is asked.

    `stream` and `complete` both record: the answer streams, and the guard,
    the router and the memory extraction complete — any of them could be the
    one handed the wrong account's text."""

    needs_key = False
    domain = None

    def __init__(self):
        self.id = "fake"
        self.label = "Fake"
        self.models = ("fake-1",)
        self.default_model = "fake-1"
        self.seen: list[str] = []
        self._lock = threading.Lock()
        self.reply = "Vale."

    def _note(self, system, messages) -> None:
        with self._lock:
            self.seen.append(f"{system}\n{json.dumps(messages, ensure_ascii=False)}")

    def stream(self, api_key, model, system, messages):
        self._note(system, messages)
        yield self.reply

    def complete(self, api_key, model, system, messages):
        self._note(system, messages)
        return self.reply

    def available(self):
        return True

    def take(self) -> str:
        with self._lock:
            out, self.seen = "\n".join(self.seen), []
        return out


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "s3cret-token")


@pytest.fixture
def books(monkeypatch, tmp_path):
    """Alice's and Bob's directories, resolved by the real `paths_for` — the
    function a mix-up would live in — under a scratch users dir."""
    users = tmp_path / "users"
    real = accounts.paths_for
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for",
        lambda email, owner=None, users_dir=users: real(email, owner, users_dir=users))
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    made = {}
    for email in (ALICE, BOB):
        paths = real(email, None, users_dir=users)
        paths.root.mkdir(parents=True)
        paths.watchlist.write_text(WATCHLIST)
        paths.prefs.write_text(json.dumps(PREFS))
        made[email] = paths
    assert made[ALICE].root != made[BOB].root
    return made


@pytest.fixture
def backend(monkeypatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(engine, "attempts", lambda prefs: [(recorder, "k", "fake-1")])
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    monkeypatch.setattr(engine, "web_enabled", lambda: False)
    return recorder


@pytest.fixture
def clients(books, sign_in):
    return {email: sign_in(TestClient(fastapi_app), email) for email in books}


def _turn(client: TestClient, message: str, thread: str = "", ok: bool = True):
    body = {
        "threadId": thread, "runId": "run-1",
        "messages": [{"id": "m1", "role": "user", "content": message}],
        "state": {}, "forwardedProps": {"lang": "es"}, "tools": [],
    }
    response = client.post("/v1/chat/runs", json=body)
    if ok:
        assert response.status_code == 200, response.text
    return response


def _plant(paths: accounts.UserPaths, client: TestClient) -> None:
    """One secret in each of Alice's stores, written the way the app writes
    them — the conversation by having it, then leaving it for a new thread,
    since `earlier()` recalls other threads and never the one in progress."""
    prefs = json.loads(paths.prefs.read_text())
    prefs["investor_profile"] = {
        "set": True, "risk": "aggressive",
        "notes": f"Compro NVDA con la herencia {SECRET['profile']}.",
    }
    paths.prefs.write_text(json.dumps(prefs))
    learnings.add(paths.learnings,
                  f"Mi asesor fiscal se llama {SECRET['memory']} y lleva mi NVDA.",
                  kind="fact", tickers=["NVDA"])
    journal.add_criteria(journal.path_for(paths.chat), "NVDA",
                         [{"rule": "below", "level": 90}], date.today(),
                         thesis=f"Vendo NVDA si pierde el contrato {SECRET['criteria']}.")
    _turn(client, f"NVDA: mi plan es venderla toda cuando llegue a 200, lo "
                  f"llamo plan {SECRET['thread']} y no lo pienso cambiar nunca.")
    assert client.post("/v1/chat/conversations", json={}).status_code == 201


def _leaks(prompt: str) -> list[str]:
    return [store for store, word in SECRET.items() if word in prompt]


# ------------------------------------------------------------------ prompts


def test_bob_s_prompts_carry_nothing_alice_told_the_assistant(books, backend, clients):
    _plant(books[ALICE], clients[ALICE])
    backend.take()

    _turn(clients[ALICE], QUESTION)
    hers = backend.take()
    # The control: each store Alice has is read into her own turn. Without
    # this, a test whose secrets never reached any prompt would pass.
    expected = {"profile", "memory", "criteria"} | (
        {"thread"} if memory.available() else set())
    assert set(_leaks(hers)) == expected

    _turn(clients[BOB], QUESTION)
    assert _leaks(backend.take()) == []


def test_alice_s_own_conversation_does_not_reach_bob(books, backend, clients):
    # Planted by talking, not by writing files: a thread, its turns in the
    # memory index, a memory the message asks to keep.
    word = SECRET["thread"]
    backend.reply = f"Apuntado: el plan {word} para NVDA."
    _turn(clients[ALICE],
          f"Recuerda que mi plan para NVDA se llama {word}: vender toda la "
          "posición cuando llegue a 200 dólares, sin excepciones.")
    backend.take()

    backend.reply = "Vale."
    _turn(clients[BOB], QUESTION)
    assert word not in backend.take()
    listed = clients[BOB].get("/v1/chat/conversations").json()["conversations"]
    assert word not in json.dumps(listed)
    remembered = clients[BOB].get("/v1/chat/memories").json()
    assert word not in json.dumps(remembered)


def test_turns_running_at_once_keep_to_their_own_account(books, backend, clients):
    """Both turns inside the backend at the same moment: a prompt built from
    state the other request left behind (a context variable, a memo, the
    current account on a shared thread) would show here and not in turns run
    one after another."""
    _plant(books[ALICE], clients[ALICE])
    both_in = threading.Barrier(2, timeout=20)
    overlapped = threading.Event()
    prompts: dict[str, list[str]] = {ALICE: [], BOB: []}
    lock = threading.Lock()

    def stream(api_key, model, system, messages):
        text = f"{system}\n{json.dumps(messages, ensure_ascii=False)}"
        who = ALICE if "alice-asks" in text else BOB
        with lock:
            prompts[who].append(text)
        try:
            both_in.wait()
            overlapped.set()
        except threading.BrokenBarrierError:
            pass
        yield "Vale."

    backend.stream = stream
    errors: list[BaseException] = []

    def ask(email: str, tag: str) -> None:
        try:
            _turn(clients[email], f"{QUESTION} ({tag})")
        except BaseException as exc:  # noqa: BLE001 — reported below
            errors.append(exc)

    runs = [threading.Thread(target=ask, args=(ALICE, "alice-asks")),
            threading.Thread(target=ask, args=(BOB, "bob-asks"))]
    for t in runs:
        t.start()
    for t in runs:
        t.join(60)
    assert not errors, errors
    assert overlapped.is_set(), "the two turns never ran at the same time"
    assert prompts[ALICE] and prompts[BOB]
    assert all("bob-asks" not in p for p in prompts[ALICE])
    assert all(_leaks(p) == [] for p in prompts[BOB])
    assert any(SECRET["profile"] in p for p in prompts[ALICE])


# ---------------------------------------------------------------------- ids


def test_bob_cannot_reach_alice_s_thread_by_its_id(books, backend, clients):
    _turn(clients[ALICE], f"Mi plan con NVDA se llama {SECRET['thread']}.")
    cid = clients[ALICE].get("/v1/chat/conversations").json()["conversations"][0]["id"]
    before = books[ALICE].chat.read_bytes()

    bob = clients[BOB]
    assert bob.get(f"/v1/chat/conversations/{cid}").status_code == 404
    assert bob.patch(f"/v1/chat/conversations/{cid}",
                     json={"title": "mío"}).status_code == 404
    assert bob.delete(f"/v1/chat/conversations/{cid}").status_code == 404
    # A turn aimed at her thread is a 404 too — not a new thread of his own
    # under her id, and not a reply appended to hers.
    assert _turn(bob, "hola", thread=cid, ok=False).status_code == 404
    assert books[ALICE].chat.read_bytes() == before


def test_bob_cannot_rate_one_of_alice_s_answers(books, backend, clients):
    _turn(clients[ALICE], "hola, ¿cómo va NVDA hoy?")
    cid = clients[ALICE].get("/v1/chat/conversations").json()["conversations"][0]["id"]
    turns = clients[ALICE].get(f"/v1/chat/conversations/{cid}").json()["messages"]
    tid = next(m["id"] for m in turns if m["role"] == "assistant")
    before = books[ALICE].chat.read_bytes()

    got = clients[BOB].put(f"/v1/chat/turns/{tid}/rating",
                           json={"vote": "down", "reason": "wrong", "note": "spam"})
    assert got.status_code == 404
    assert books[ALICE].chat.read_bytes() == before


def test_bob_cannot_edit_or_drop_one_of_alice_s_memories(books, backend, clients):
    said = f"Mi asesor fiscal se llama {SECRET['memory']} y lleva mi NVDA."
    item, _ = learnings.add(books[ALICE].learnings, said, kind="fact")
    before = books[ALICE].learnings.read_bytes()

    bob = clients[BOB]
    assert bob.patch(f"/v1/chat/memories/{item.id}",
                     json={"text": "Mi asesor fiscal ahora es otro distinto."}
                     ).status_code == 404
    assert bob.delete(f"/v1/chat/memories/{item.id}").status_code == 404
    assert books[ALICE].learnings.read_bytes() == before
