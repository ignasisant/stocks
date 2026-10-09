"""Chat turns that outlive the request that asked for them (`api/runs.py`).

A turn used to be its response stream: the reader who left took the answer
with them. Now a worker writes it and the response only follows along, so what
is pinned here is what a reader who leaves, or comes back, is owed:

* the answer is stored though nobody read the stream to the end;
* the run replays from its first event to a reader who comes back, and the
  thread says it has one being answered — or one refused while nobody looked;
* Stop is its own call now (closing the stream no longer stops anything), and
  a stopped answer is stored nowhere, as before;
* one answer per thread at a time, and it lands on the thread it was asked on
  even when the reader moved to another one meanwhile;
* the Cloud Run hold opens only for this process's own token.
"""

# The API fixtures are borrowed from test_api_chat, and a test naming one as
# a parameter reads to ruff as redefining the import.
# ruff: noqa: F811

from __future__ import annotations

import threading
import time

import pytest

from stocks.api import runs
from stocks.chat import engine
from stocks.web import auth

from .test_api_chat import (  # noqa: F401 — fixtures
    EMAIL,
    FakeProvider,
    account,
    client,
    events,
    finished,
    painted,
    run,
    served,
    signed_in,
    token,
)


class GatedProvider(FakeProvider):
    """Says its first chunk, then waits for `gate` before the rest — a model
    still answering while the test looks at the run."""

    def __init__(self, gate: threading.Event, **kwargs):
        super().__init__(**kwargs)
        self.gate = gate

    def stream(self, api_key, model, system, messages):
        first, *rest = self._chunks
        yield first
        assert self.gate.wait(5), "gate never opened"
        yield from rest


@pytest.fixture(autouse=True)
def _registry():
    runs._reset()
    yield
    runs._reset()


@pytest.fixture
def gate():
    opened = threading.Event()
    yield opened
    opened.set()  # never leave a worker parked past its test


@pytest.fixture
def gated(served, gate):
    return lambda: served(GatedProvider(gate))


@pytest.fixture
def leaving(monkeypatch):
    """A reader who reads the run's first event and closes the tab."""
    real = runs.tail

    def first_only(run):
        stream = real(run)
        for frame in stream:
            yield frame
            if frame.startswith("data: "):
                break
        stream.close()

    monkeypatch.setattr(runs, "tail", first_only)
    return real


def ended(account, rid: str = "run-1") -> runs.Run:
    """Run `rid` once its worker is done."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = runs.find(str(account.chat), rid)
        if found is not None and not found.live:
            return found
        time.sleep(0.01)
    raise AssertionError(f"run {rid} never ended")


def started(account, rid: str = "run-1") -> runs.Run:
    """Run `rid` once its provider has said something — the gate is next."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = runs.find(str(account.chat), rid)
        if found is not None and any("TEXT_MESSAGE_CONTENT" in f for f in found.frames):
            return found
        time.sleep(0.01)
    raise AssertionError(f"run {rid} never started answering")


def turns(client, cid: str) -> list[dict]:
    return client.get(f"/v1/chat/conversations/{cid}").json()["messages"]


def fresh_thread(client) -> str:
    return client.post("/v1/chat/conversations", json={"title": "T"}).json()["id"]


# ------------------------------------------------------------------- leaving


def test_a_reader_who_leaves_still_gets_the_answer_stored(
    client, account, signed_in, gated, gate, leaving
):
    gated()
    cid = fresh_thread(signed_in)
    response = signed_in.post("/v1/chat/runs", json=run("hola", thread=cid))
    assert [e["type"] for e in events(response.text)] == ["RUN_STARTED"]
    gate.set()
    assert not ended(account).failed
    assert [(m["role"], m["content"]) for m in turns(signed_in, cid)] == [
        ("user", "hola"), ("assistant", "Hola mundo"),
    ]


def test_a_reader_who_comes_back_is_replayed_the_whole_run(
    client, account, signed_in, served
):
    served()
    first = events(signed_in.post("/v1/chat/runs", json=run("hola")).text)
    again = events(signed_in.get("/v1/chat/runs/run-1").text)
    assert again == first
    assert painted(again) == "Hola mundo"
    assert finished(again)["type"] == "RUN_FINISHED"


def test_a_run_another_account_started_is_not_found(
    client, account, signed_in, served, monkeypatch
):
    served()
    signed_in.post("/v1/chat/runs", json=run("hola"))
    # Same id, another account's chat file: the owner is part of the key.
    found = runs.find(str(account.chat), "run-1")
    monkeypatch.setattr(found, "owner", "someone/else/chat.json")
    with runs._lock:
        runs._runs[runs._key(found.owner, found.id)] = runs._runs.pop(
            runs._key(str(account.chat), found.id))
    assert signed_in.get("/v1/chat/runs/run-1").status_code == 404
    assert signed_in.post("/v1/chat/runs/run-1/stop").status_code == 404


def test_the_thread_names_the_run_it_is_being_answered_by(
    client, account, signed_in, gated, gate, leaving
):
    gated()
    cid = fresh_thread(signed_in)
    signed_in.post("/v1/chat/runs", json=run("hola", thread=cid))
    started(account)
    thread = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert thread["running"] == {"run_id": "run-1", "question": "hola", "live": True}
    gate.set()
    ended(account)
    assert signed_in.get(f"/v1/chat/conversations/{cid}").json()["running"] is None


def test_a_refusal_nobody_saw_is_shown_once(
    client, account, signed_in, monkeypatch, leaving
):
    """A refused turn stores nothing, so the thread alone would just have lost
    the question: the run stays on it until the reader has seen it end."""
    monkeypatch.setattr(engine, "attempts", lambda prefs: [])
    cid = fresh_thread(signed_in)
    signed_in.post("/v1/chat/runs", json=run("hola", thread=cid))
    assert ended(account).failed
    thread = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert thread["running"] == {"run_id": "run-1", "question": "hola", "live": False}
    monkeypatch.setattr(runs, "tail", leaving)  # back, and reading to the end
    replay = events(signed_in.get("/v1/chat/runs/run-1").text)
    assert finished(replay)["code"] == "chat.free_exhausted"
    assert signed_in.get(f"/v1/chat/conversations/{cid}").json()["running"] is None


# ---------------------------------------------------------------------- stop


def test_stop_cuts_the_answer_and_stores_none_of_it(
    client, account, signed_in, gated, gate, leaving, monkeypatch
):
    gated()
    cid = fresh_thread(signed_in)
    signed_in.post("/v1/chat/runs", json=run("hola", thread=cid))
    started(account)
    assert signed_in.post("/v1/chat/runs/run-1/stop").status_code == 204
    gate.set()
    done = ended(account)
    monkeypatch.setattr(runs, "tail", leaving)
    replay = events(signed_in.get("/v1/chat/runs/run-1").text)
    end = finished(replay)
    assert (end["type"], end["code"]) == ("RUN_ERROR", "chat.stopped")
    assert painted(replay) == "Hola"
    assert not [m for m in turns(signed_in, cid) if m["role"] == "assistant"]
    # A stop is the reader's own doing: nothing to show them on return.
    assert done.seen
    assert signed_in.get(f"/v1/chat/conversations/{cid}").json()["running"] is None


def test_stopping_a_run_that_ended_is_a_no_op(client, account, signed_in, served):
    served()
    signed_in.post("/v1/chat/runs", json=run("hola"))
    assert signed_in.post("/v1/chat/runs/run-1/stop").status_code == 204
    assert finished(events(signed_in.get("/v1/chat/runs/run-1").text))["type"] \
        == "RUN_FINISHED"


def test_stop_is_a_write(client, account, served, monkeypatch):
    served()
    assert client.post(
        "/v1/chat/runs/run-1/stop",
        headers={"Authorization": "Bearer s3cret-token"}, params={"account": EMAIL},
    ).status_code in (401, 403)


# ---------------------------------------------------------------------- busy


def test_a_thread_takes_one_answer_at_a_time(
    client, account, signed_in, gated, gate, leaving
):
    gated()
    cid = fresh_thread(signed_in)
    signed_in.post("/v1/chat/runs", json=run("hola", thread=cid))
    started(account)
    again = run("otra", thread=cid)
    again["runId"] = "run-2"
    assert signed_in.post("/v1/chat/runs", json=again).status_code == 409
    redo = run(thread=cid, regenerate=True)
    redo["runId"] = "run-3"
    assert signed_in.post("/v1/chat/runs", json=redo).status_code == 409
    gate.set()
    ended(account)
    # The refused regenerate took nothing off the thread.
    assert [m["content"] for m in turns(signed_in, cid)] == ["hola", "Hola mundo"]


def test_another_thread_is_answered_meanwhile(
    client, account, signed_in, gated, gate, leaving, monkeypatch
):
    gated()
    busy = fresh_thread(signed_in)
    signed_in.post("/v1/chat/runs", json=run("hola", thread=busy))
    started(account)
    other = fresh_thread(signed_in)
    body = run("otra", thread=other)
    body["runId"] = "run-2"
    monkeypatch.setattr(runs, "tail", leaving)  # read this one to the end
    gate.set()
    stream = events(signed_in.post("/v1/chat/runs", json=body).text)
    assert finished(stream)["type"] == "RUN_FINISHED"


# ------------------------------------------------------------------- pinning


def test_an_answer_lands_on_the_thread_it_was_asked_on(
    client, account, signed_in, gated, gate, leaving
):
    """The reader opens another thread while the first is answered: that
    moves the active pointer, never where the answer is written."""
    gated()
    asked = fresh_thread(signed_in)
    signed_in.post("/v1/chat/runs", json=run("hola", thread=asked))
    started(account)
    # New while the first question is answered: the asked thread is still
    # empty on disk, and New must not hand it back as the blank one.
    elsewhere = fresh_thread(signed_in)
    assert elsewhere != asked
    assert auth.active_conversation(account.chat)["id"] == elsewhere
    gate.set()
    ended(account)
    assert [m["content"] for m in turns(signed_in, asked)] == ["hola", "Hola mundo"]
    assert turns(signed_in, elsewhere) == []


def test_an_answer_whose_thread_was_deleted_is_dropped_not_misfiled(
    account, monkeypatch
):
    warned = []
    monkeypatch.setattr(auth.obs, "warn", lambda name, **kw: warned.append(name))
    auth.save_chat([{"role": "user", "content": "otra"}], account.chat)
    kept = auth.load_chat(account.chat)
    auth.save_chat(
        [{"role": "user", "content": "hola"},
         {"role": "assistant", "content": "Hola mundo"}],
        account.chat, "c_gone",
    )
    assert auth.load_chat(account.chat) == kept
    assert warned == ["chat.thread_gone"]


# ---------------------------------------------------------------------- hold


def test_on_cloud_run_a_run_holds_the_instance(
    client, account, signed_in, served, monkeypatch
):
    served()
    held = []
    monkeypatch.setattr(runs, "on_cloud_run", lambda: True)
    monkeypatch.setattr(runs, "hold", lambda r, url: held.append((r.id, url)))
    signed_in.post("/v1/chat/runs", json=run("hola"))
    assert held == [("run-1", "http://testserver/v1/chat/runs/run-1/hold")]


def test_off_cloud_run_nothing_is_held(
    client, account, signed_in, served, monkeypatch
):
    served()
    monkeypatch.delenv("K_SERVICE", raising=False)
    held = []
    monkeypatch.setattr(runs, "hold", lambda r, url: held.append(url))
    signed_in.post("/v1/chat/runs", json=run("hola"))
    assert held == []


def test_a_hold_opens_only_for_the_runs_own_token(
    client, account, signed_in, served
):
    served()
    signed_in.post("/v1/chat/runs", json=run("hola"))
    own = runs.find(str(account.chat), "run-1").token
    hold = "/v1/chat/runs/run-1/hold"
    assert client.post(hold).status_code == 404
    assert client.post(hold, headers={"X-Run-Hold": "nope"}).status_code == 404
    assert client.post("/v1/chat/runs/run-9/hold",
                       headers={"X-Run-Hold": own}).status_code == 404
    # No session needed: the caller is the service itself.
    client.cookies.clear()
    assert client.post(hold, headers={"X-Run-Hold": own}).status_code == 204


def test_a_hold_stays_open_until_the_run_is_over(
    client, account, signed_in, gated, gate, leaving
):
    gated()
    signed_in.post("/v1/chat/runs", json=run("hola"))
    live = started(account)
    released = threading.Event()

    def holding():
        runs.wait(live)
        released.set()

    threading.Thread(target=holding, daemon=True).start()
    assert not released.wait(0.2)
    gate.set()
    assert released.wait(5)


# ---------------------------------------------------------------- registry


def test_a_quiet_run_pings_its_reader(monkeypatch):
    monkeypatch.setattr(runs, "PING_S", 0.01)
    quiet = threading.Event()

    def events(_run):
        yield "data: one\n\n"
        quiet.wait(5)
        yield "data: two\n\n"

    run_ = runs.start(owner="o", rid="r", thread="t", question="q", events=events,
                      stopped="data: stopped\n\n", failed=lambda f: False)
    reader = runs.tail(run_)
    assert next(reader) == "data: one\n\n"
    assert next(reader) == runs.PING
    quiet.set()
    assert [f for f in reader if f != runs.PING] == ["data: two\n\n"]
    assert run_.seen


def one_frame(_run):
    yield "data: x\n\n"


def test_an_account_keeps_a_bounded_number_of_runs():
    for n in range(runs.PER_OWNER + 3):
        r = runs.start(owner="o", rid=f"r{n}", thread=f"t{n}", question="q",
                       events=one_frame,
                       stopped="", failed=lambda f: False)
        deadline = time.monotonic() + 5
        while r.live and time.monotonic() < deadline:
            time.sleep(0.005)
    kept = [k for k in runs._runs if k.startswith("o\0")]
    assert len(kept) == runs.PER_OWNER
    assert runs.find("o", "r0") is None
    assert runs.find("o", f"r{runs.PER_OWNER + 2}") is not None


def test_a_finished_run_is_forgotten_after_a_while(monkeypatch):
    r = runs.start(owner="o", rid="r", thread="t", question="q",
                   events=one_frame,
                   stopped="", failed=lambda f: True)
    deadline = time.monotonic() + 5
    while r.live and time.monotonic() < deadline:
        time.sleep(0.005)
    assert runs.on_thread("o", "t") is r
    r.ended -= runs.KEEP_S + 1
    assert runs.on_thread("o", "t") is None
    assert runs.find("o", "r") is None
