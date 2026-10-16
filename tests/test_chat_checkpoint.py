"""A run's progress on disk (`chat/checkpoint.py`), and a restart that picks
it up: the question is not lost, nothing already looked up is looked up
again, and a unit already paid is not charged twice."""

# The API fixtures are borrowed from test_api_chat, and a test naming one as
# a parameter reads to ruff as redefining the import.
# ruff: noqa: F811

from __future__ import annotations

import json
import time

import pytest

from stocks.api import runs
from stocks.chat import agent, checkpoint, engine, toolbox
from stocks.chat.checkpoint import Checkpoint
from stocks.web import auth
from stocks.web.llm import ToolCall, ToolRun

from .test_api_chat import (  # noqa: F401 — fixtures
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
from .test_chat_agent import _MSGS, _Provider


@pytest.fixture(autouse=True)
def _fresh():
    runs._reset()
    checkpoint._reset()
    yield
    runs._reset()
    checkpoint._reset()


def _left(chat_path, *, rid="run-dead", thread="t1", question="¿Qué tal ASML?",
          beat_ago=100.0, started_ago=100.0, **extra) -> object:
    """The checkpoint a process that died mid-run leaves behind."""
    path = checkpoint._path(chat_path, thread)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"rid": rid, "thread": thread, "question": question,
              "props": {"lang": "es"}, "started": time.time() - started_ago,
              "calls": [], "plan": [], "evidence": None, "charged": "",
              "resumes": 0, **extra}
    path.write_text(json.dumps(record))
    checkpoint._beat_path(path).write_text(repr(time.time() - beat_ago))
    return path


# ------------------------------------------------------------------- the file


def test_the_question_is_on_disk_before_anything_is_spent(tmp_path):
    chat = tmp_path / "chat.json"
    point = Checkpoint.open(chat, rid="r1", thread="t1", question="hola",
                            props={"lang": "es", "depth": "deep", "key": "sk-x"})
    try:
        record = json.loads(checkpoint._path(chat, "t1").read_text())
        assert record["question"] == "hola" and record["rid"] == "r1"
        assert record["props"] == {"lang": "es", "depth": "deep"}
        assert "sk-x" not in checkpoint._path(chat, "t1").read_text()
    finally:
        point.close()
    assert list(checkpoint.folder(chat).iterdir()) == []


def test_a_lookup_is_known_whatever_reason_it_was_asked_with(tmp_path):
    point = Checkpoint.open(tmp_path / "chat.json", rid="r1", thread="t1",
                            question="q", props={})
    try:
        point.called("get_quotes", {"tickers": ["NVDA"], toolbox.REASON: "a"}, "1")
        assert point.known() == {
            agent._key("get_quotes", {"tickers": ["NVDA"]}): "1"}
    finally:
        point.close()


def test_a_run_still_beating_is_nobodys_to_pick_up(tmp_path):
    chat = tmp_path / "chat.json"
    _left(chat, beat_ago=1)
    assert checkpoint.orphan(chat, thread="t1") is None
    _left(chat, beat_ago=checkpoint.STALE_S + 1)
    assert checkpoint.orphan(chat, thread="t1")["rid"] == "run-dead"
    assert checkpoint.orphan(chat, rid="run-dead")["thread"] == "t1"
    assert checkpoint.orphan(chat, rid="other") is None


def test_too_old_or_too_often_resumed_is_dropped(tmp_path):
    chat = tmp_path / "chat.json"
    old = _left(chat, started_ago=checkpoint.MAX_AGE_S + 1)
    assert checkpoint.orphan(chat, thread="t1") is None and not old.exists()
    again = _left(chat, resumes=checkpoint.MAX_RESUMES)
    assert checkpoint.orphan(chat, thread="t1") is None and not again.exists()


# --------------------------------------------------------------- the research


def test_a_resumed_gather_does_not_fetch_twice(monkeypatch):
    fetched = []
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes", (
        toolbox.TOOLS["get_quotes"][0],
        lambda a, c: fetched.append(a["tickers"]) or f"{a['tickers'][0]} 1"))
    filed = []
    p = _Provider()

    def again(execute):
        return ToolRun("DONE", [
            ToolCall("get_quotes", {"tickers": ["NVDA"]},
                     execute("get_quotes", {"tickers": ["NVDA"]})),
            ToolCall("get_quotes", {"tickers": ["AMD"]},
                     execute("get_quotes", {"tickers": ["AMD"]})),
        ])

    p.run = again
    seen = []
    ev = agent.gather(
        p, "k", _MSGS, toolbox.Context(),
        known={agent._key("get_quotes", {"tickers": ["NVDA"]}): "NVDA 640"},
        on_call=lambda *said: filed.append(said),
        on_tool=lambda cid, call, done: seen.append((call.name, done)))
    assert fetched == [["AMD"]]
    assert [c.result for c in ev.calls] == ["NVDA 640", "AMD 1"]
    assert filed == [("get_quotes", {"tickers": ["AMD"]}, "AMD 1")]
    # Both still shown as research, the remembered one done at once.
    assert seen.count(("get_quotes", True)) == 2


def test_a_finished_gather_is_handed_back_without_running(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "web_enabled", lambda: True)
    monkeypatch.setattr(agent, "gather", lambda *a, **k: pytest.fail("ran again"))
    point = Checkpoint(tmp_path / "t1.json", {
        "rid": "r", "plan": [{"text": "Precio", "done": True}],
        "evidence": {"calls": [{"name": "get_quotes", "args": {"tickers": ["NVDA"]},
                                "result": "NVDA 640"}],
                     "ok": True, "missing": "guidance"}})
    plans, shown = [], []
    ev = engine.gather_evidence({}, _Provider(), "k", _MSGS, tmp_path / "w.yaml",
                                tmp_path / "p.db", on_plan=plans.append,
                                on_tool=lambda *said: shown.append(said),
                                checkpoint=point)
    assert ev.ok and ev.calls[0].result == "NVDA 640" and ev.missing == "guidance"
    assert plans == [[{"text": "Precio", "done": True}]] and len(shown) == 2


# ------------------------------------------------------------- a restart, end to end


def _spent(account) -> int:
    day = f"free_msgs::{time.strftime('%Y-%m-%d')}"
    return json.loads(account.prefs.read_text()).get(day, 0)


def _ended(account, rid: str) -> runs.Run:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = runs.find(str(account.chat), rid)
        if found is not None and not found.live:
            return found
        time.sleep(0.01)
    raise AssertionError(f"run {rid} never ended")


def _thread(client) -> str:
    return client.post("/v1/chat/conversations", json={"title": "T"}).json()["id"]


def test_a_run_keeps_a_checkpoint_only_while_it_runs(
    client, account, signed_in, served
):
    served()
    cid = _thread(signed_in)
    signed_in.post("/v1/chat/runs", json=run("hola", thread=cid))
    _ended(account, "run-1")
    assert not checkpoint._path(account.chat, cid).exists()


def test_opening_the_thread_picks_a_cut_run_back_up(
    client, account, signed_in, served
):
    served()
    cid = _thread(signed_in)
    _left(account.chat, thread=cid)
    said = signed_in.get(f"/v1/chat/conversations/{cid}").json()
    assert said["running"]["run_id"] == "run-dead"
    assert said["running"]["question"] == "¿Qué tal ASML?"
    assert not _ended(account, "run-dead").failed
    stored = auth.load_chat(account.chat, cid)
    assert [(m["role"], m["content"]) for m in stored] == [
        ("user", "¿Qué tal ASML?"), ("assistant", "Hola mundo")]
    assert not checkpoint._path(account.chat, cid).exists()


def test_following_a_cut_run_again_replays_it_from_the_checkpoint(
    client, account, signed_in, served
):
    served()
    cid = _thread(signed_in)
    _left(account.chat, thread=cid)
    stream = events(signed_in.get("/v1/chat/runs/run-dead").text)
    assert painted(stream) == "Hola mundo"
    assert finished(stream)["type"] == "RUN_FINISHED"


def test_a_unit_paid_before_the_restart_is_not_paid_again(
    client, account, signed_in, served, monkeypatch
):
    served(FakeProvider(pid="free"))
    cid = _thread(signed_in)
    _left(account.chat, thread=cid, charged="free")
    signed_in.get(f"/v1/chat/conversations/{cid}")
    _ended(account, "run-dead")
    assert _spent(account) == 0


def test_stopping_a_cut_run_just_drops_it(client, account, signed_in, served):
    served()
    cid = _thread(signed_in)
    path = _left(account.chat, thread=cid)
    assert signed_in.post("/v1/chat/runs/run-dead/stop").status_code == 204
    assert not path.exists()
    assert runs.find(str(account.chat), "run-dead") is None


def test_a_turn_on_a_key_held_for_the_session_is_never_written_down(
    client, account, signed_in, served, monkeypatch
):
    served()
    opened = []
    monkeypatch.setattr(Checkpoint, "open", classmethod(
        lambda cls, *a, **k: opened.append(k) or pytest.fail("written down")))
    monkeypatch.setattr("stocks.api.routes.chat.session_keys",
                        lambda provider, key: {"anthropic": "sk-held"})
    signed_in.post("/v1/chat/runs", json=run("hola"))
    _ended(account, "run-1")
    assert opened == []
