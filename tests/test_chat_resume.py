"""An answer the connection took away is written again; one the reader
stopped stays stopped.

Streamlit ends a running script the moment its websocket drops, and from
inside the script that is the very same unwind the composer's Stop button
asks for. On a phone the first one happens constantly — every screen lock,
every app switch — and the assistant used to file whatever half-sentence had
arrived as the finished answer, so coming back to the app meant coming back to
a reply cut mid-word with no way to ask for the rest. These pin the two apart:
the runtime records the disconnect (web/reconnect.py) and the cut turn is left
trailing, which is the shape the panel already answers.
"""

from __future__ import annotations

import json
import time

import pytest
from streamlit.testing.v1 import AppTest

from stocks.web import auth, chat_core, reconnect

# The panel's own body, with the wreckage of a cut turn already in session
# state: what the stream had written and the free unit it spent, parked
# exactly as the generate block parks them before the first token.
SCRIPT = """
import streamlit as st
from stocks.web import chat_core

if not st.session_state.get("seeded"):
    st.session_state["seeded"] = True
    st.session_state["panel_generating"] = {
        "parts": ["half an ans"], "spent": [1], "started": 100.0}
chat_core._panel_body()
"""


class _Provider:
    id = "free"
    label = "Aguait AI"
    needs_key = False
    models = ("m",)
    default_model = "m"
    domain = ""

    def stream(self, api_key, model, system, messages):
        yield "the whole answer"

    def error_key(self, exc):
        return "chat.api_error"


@pytest.fixture(autouse=True)
def fresh_marks():
    """The wrap and its marks are per process, so per test here."""
    reconnect._WATCHING = None
    reconnect._DROPPED.clear()
    yield
    reconnect._WATCHING = None
    reconnect._DROPPED.clear()


@pytest.fixture
def paths(tmp_path):
    return auth.UserPaths(
        root=tmp_path,
        watchlist=tmp_path / "watchlist.yaml",
        db=tmp_path / "portfolio.db",
        last_import=tmp_path / "last_import.json",
        prefs=tmp_path / "prefs.json",
        chat=tmp_path / "chat.json",
        bank=tmp_path / "bank.json",
        action=tmp_path / "daily_action.json",
    )


@pytest.fixture
def app(monkeypatch, tmp_path, paths):
    """The panel, with a question already asked and never answered."""
    provider = _Provider()
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(chat_core, "active_provider", lambda: provider)
    monkeypatch.setattr(chat_core, "_offered_providers", lambda: [provider])
    monkeypatch.setattr(chat_core.llm, "PROVIDERS", {provider.id: provider})
    monkeypatch.setattr(chat_core.llm, "default_provider_id", lambda: provider.id)
    # Neither free counter is shared with the machine running the tests, and
    # none of the per-turn lookups run: these are about which turn is written,
    # not about what an answer is made of.
    monkeypatch.setattr(chat_core.engine, "GLOBAL_FREE_FILE",
                        tmp_path / "free_llm_global.json")
    monkeypatch.setattr(chat_core.engine, "_global_free_loaded", True)
    monkeypatch.setattr(chat_core.engine, "_global_free", {"day": "", "used": 0})
    monkeypatch.setattr(chat_core.engine, "attempts", lambda prefs: [])
    monkeypatch.setattr(chat_core.engine, "in_parallel",
                        lambda *fns, **kw: [None] * len(fns))
    monkeypatch.setattr(chat_core, "_try_action", lambda *a: None)
    monkeypatch.setattr(chat_core, "_maybe_autotitle", lambda *a: False)
    paths.chat.write_text(json.dumps({
        "version": 2, "active": "c1",
        "conversations": [{
            "id": "c1", "title": "Semis", "title_auto": False,
            "created": "2026-09-17T08:00:00+00:00",
            "updated": "2026-09-17T08:54:00+00:00",
            "messages": [{"role": "user", "content": "why is it down?"}],
        }],
    }))
    return AppTest.from_string(SCRIPT, default_timeout=30)


def _thread(paths):
    stored = json.loads(paths.chat.read_text())
    return stored["conversations"][0]["messages"]


def test_a_turn_the_connection_cut_is_answered_again(app, paths, monkeypatch):
    refunded: list[int] = []
    give_back = chat_core._refund_free_quota

    def spy(units):
        refunded.append(units)
        give_back(units)

    monkeypatch.setattr(chat_core, "_refund_free_quota", spy)
    monkeypatch.setattr(chat_core.reconnect, "dropped", lambda since=None: True)

    app.run()

    assert not app.exception
    thread = _thread(paths)
    # The half sentence is gone and the question has its real answer, written
    # on the run that followed the reader back.
    assert [m["role"] for m in thread] == ["user", "assistant"]
    assert thread[-1]["content"] == "the whole answer"
    assert "stopped" not in thread[-1]
    # And the unit the dead attempt spent went back before the new one spent
    # its own: an answer nobody read must not be paid for twice.
    assert refunded == [1]


def test_a_turn_the_reader_stopped_stays_where_it_was_cut(app, paths,
                                                          monkeypatch):
    monkeypatch.setattr(chat_core.reconnect, "dropped", lambda since=None: False)

    app.run()

    assert not app.exception
    thread = _thread(paths)
    assert [m["role"] for m in thread] == ["user", "assistant"]
    assert thread[-1]["content"] == "half an ans"
    assert thread[-1]["stopped"] is True
    # Nothing was regenerated over the top of it.
    assert "the whole answer" not in json.dumps(thread)


# ------------------------------------------------- the mark itself


class _Manager:
    def __init__(self):
        self.gone: list[str] = []

    def disconnect_session(self, session_id):
        self.gone.append(session_id)


class _Runtime:
    def __init__(self, manager):
        self._session_mgr = manager


@pytest.fixture
def runtime(monkeypatch):
    manager = _Manager()
    monkeypatch.setattr("streamlit.runtime.get_instance",
                        lambda: _Runtime(manager))
    monkeypatch.setattr(reconnect, "_session_id", lambda: "s1")
    return manager


def test_a_dropped_websocket_is_recorded_against_its_session(runtime):
    assert reconnect.watch() is True

    runtime.disconnect_session("s1")

    assert runtime.gone == ["s1"]  # the runtime's own work still happened
    assert reconnect.dropped(since=0.0) is True
    # Read once: it explains the turn it cut, not every later stop.
    assert reconnect.dropped(since=0.0) is False


def test_a_disconnect_older_than_the_turn_explains_nothing(runtime):
    """An idle session can lose its socket with no turn under it, and no run
    to read the mark. The next turn the reader really does stop must not be
    handed that stale mark as its excuse."""
    reconnect.watch()
    runtime.disconnect_session("s1")

    assert reconnect.dropped(since=time.time() + 60) is False
    assert reconnect.dropped(since=0.0) is False  # consumed all the same


def test_a_runtime_that_moved_leaves_every_stop_the_readers(monkeypatch):
    """The wrap reaches into Streamlit internals, so it is allowed to fail."""
    def gone():
        raise RuntimeError("no runtime here")

    monkeypatch.setattr("streamlit.runtime.get_instance", gone)

    assert reconnect.watch() is False
    assert reconnect.dropped(since=0.0) is False
