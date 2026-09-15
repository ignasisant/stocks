"""Stop, and the answer stops with you.

The composer's send button becomes a stop button while the answer is being
written (st.chat_input submit_mode). Pressing it ends the script run, which
means none of the code that files an answer on the thread ever runs: the
question is left trailing with no reply — the same shape the panel treats as
"answer this", so the stopped turn used to start over on the very next run.
These tests drive the real render through AppTest and pin what a stop leaves
behind.
"""

from __future__ import annotations

import threading
import time

import pytest
from streamlit.proto.ChatInput_pb2 import ChatInput as ChatInputProto
from streamlit.runtime.scriptrunner import get_script_run_ctx
from streamlit.runtime.scriptrunner_utils.exceptions import StopException
from streamlit.testing.v1 import AppTest

from stocks.web import auth, chat_core

SCRIPT = """
from stocks.web import chat_core
chat_core.render_conversation("panel", chat_core.active_provider(), "m", "k")
"""


# The panel is a fragment (chat_core._panel_body), and a fragment run is where
# every stop in production has to land. Streamlit re-raises the control-flow
# exceptions out of a fragment, but that is its promise to keep, not ours to
# assume.
FRAGMENT_SCRIPT = """
import streamlit as st
from stocks.web import chat_core

@st.fragment
def panel():
    chat_core.render_conversation("panel", chat_core.active_provider(), "m", "k")

panel()
"""


class _Provider:
    """A provider whose stream is stopped after `before` chunks.

    Raising StopException out of the stream is what a press on the stop button
    does to a running script: Streamlit's execution-control check raises it at
    the next st. call, and write_stream calls one per chunk.
    """

    id = "gemini"
    label = "Gemini"
    needs_key = False
    models = ("m",)
    default_model = "m"

    def __init__(self) -> None:
        self.chunks = ["tu cartera ", "sube un "]
        self.stop_after: int | None = None
        self.calls = 0

    def stream(self, api_key, model, system, messages):
        self.calls += 1
        for i, chunk in enumerate(self.chunks):
            if self.stop_after is not None and i == self.stop_after:
                raise StopException("stop requested")
            yield chunk

    def error_key(self, exc):
        return "chat.provider_busy"


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
def provider():
    return _Provider()


@pytest.fixture
def app(monkeypatch, paths, provider):
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(chat_core, "active_provider", lambda: provider)
    monkeypatch.setattr(chat_core.engine, "attempts", lambda prefs: [])
    monkeypatch.setattr(chat_core.engine, "in_parallel",
                        lambda *fns, **kw: [None] * len(fns))
    monkeypatch.setattr(chat_core, "_try_action", lambda *a: None)
    monkeypatch.setattr(chat_core, "_maybe_autotitle", lambda *a: False)
    return AppTest.from_string(SCRIPT, default_timeout=30)


@pytest.fixture
def free_pot(monkeypatch, tmp_path):
    """The free chain's two counters, isolated from the real data dir."""
    monkeypatch.setattr(chat_core.engine, "GLOBAL_FREE_FILE",
                        tmp_path / "free_llm_global.json")
    monkeypatch.setattr(chat_core.engine, "_global_free_loaded", True)
    monkeypatch.setattr(chat_core.engine, "_global_free", {"day": "", "used": 0})
    return chat_core.engine


def _units_spent(paths):
    key = f"free_msgs::{time.strftime('%Y-%m-%d')}"
    return int(auth.load_prefs(paths.prefs).get(key, 0) or 0)


def _thread(paths):
    """The stored turns without their instrumentation (see test_chat_retry)."""
    noise = ("ts", "took", "steps")
    return [{k: v for k, v in turn.items() if k not in noise}
            for turn in auth.load_chat(paths.chat)]


def test_the_composer_offers_a_stop_while_it_answers(app):
    """The button is Streamlit's own; what this pins is that the panel asks
    for it — without submit_mode the field would keep taking questions while
    one is being answered."""
    app.run()

    assert (app.chat_input[0].proto.submit_mode
            == ChatInputProto.SubmitMode.SUBMIT_MODE_STOP)


def test_a_stopped_answer_keeps_what_had_been_written(app, paths, provider):
    provider.stop_after = 1  # one chunk out, then the reader presses stop
    app.run()

    app.chat_input[0].set_value("¿cómo va mi cartera?").run()

    assert not app.exception
    # The run died before anything could be filed: only the question is on
    # disk, exactly as a reload-during-generation leaves it.
    assert _thread(paths) == [
        {"role": "user", "content": "¿cómo va mi cartera?"}]

    app.run()  # the next run — here, typing again, a click, anything

    assert not app.exception
    assert _thread(paths) == [
        {"role": "user", "content": "¿cómo va mi cartera?"},
        {"role": "assistant", "content": "tu cartera", "stopped": True},
    ]


def test_a_stopped_turn_is_not_answered_again(app, paths, provider):
    """The point of filing it: a trailing question with no reply is what the
    panel regenerates, so a stopped turn would quietly restart."""
    provider.stop_after = 1
    app.run()
    app.chat_input[0].set_value("hola").run()

    app.run()
    app.run()

    assert not app.exception
    assert provider.calls == 1
    assert len(_thread(paths)) == 2


def test_the_reader_can_ask_again_after_stopping(app, paths, provider):
    provider.stop_after = 1
    app.run()
    app.chat_input[0].set_value("primera").run()
    provider.stop_after = None  # nothing stops the next one

    app.chat_input[0].set_value("segunda").run()

    assert not app.exception
    # Four turns in order: the stopped answer lands under the question it was
    # answering, not after the one that followed it.
    assert _thread(paths) == [
        {"role": "user", "content": "primera"},
        {"role": "assistant", "content": "tu cartera", "stopped": True},
        {"role": "user", "content": "segunda"},
        {"role": "assistant", "content": "tu cartera sube un "},
    ]


def test_stopping_before_the_first_token_gives_the_unit_back(
        app, paths, provider, free_pot):
    """Nothing was written, so nothing was owed — the same debt a dead
    provider settles."""
    provider.id = "free"
    provider.stop_after = 0
    app.run()
    app.chat_input[0].set_value("hola").run()

    app.run()

    assert not app.exception
    assert _units_spent(paths) == 0
    assert free_pot._global_free["used"] == 0
    assert _thread(paths)[-1]["stopped"] is True


def test_a_stopped_answer_that_had_started_keeps_its_unit(
        app, paths, provider, free_pot):
    provider.id = "free"
    provider.stop_after = 1
    app.run()
    app.chat_input[0].set_value("hola").run()

    app.run()

    assert not app.exception
    assert _units_spent(paths) == 1  # the reader did get part of an answer


def test_an_answered_turn_leaves_nothing_to_recover(app, paths, provider):
    """The marker is a live turn's, not a stored one's: a completed answer
    must not come back as a second, stopped copy of itself."""
    app.run()
    app.chat_input[0].set_value("hola").run()

    app.run()

    assert not app.exception
    assert _thread(paths) == [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "tu cartera sube un "},
    ]


# ------------------------------------------------- where a stop can land
# Streamlit acts on a stop only where the script touches the runtime. A turn
# spends most of its wall clock touching nothing: the action probe, the two
# gather passes and the wait on the first token are network calls on the
# script thread. Pressed in there, stop used to do nothing at all — the
# working line ran on to "searching the web, 40s" with the press ignored.


def _press_stop() -> None:
    """What the stop button does to the running script."""
    get_script_run_ctx().script_requests.request_stop()


def test_a_stop_lands_while_the_turn_is_still_gathering(app, paths, provider,
                                                        monkeypatch):
    landed: list[str] = []

    def gather(*fns, tick=None, **kw):
        assert tick is not None, "the gather pass hands the runtime no tick"
        _press_stop()
        tick()  # the checkpoint: raises StopException when it works
        landed.append("kept going")
        return [None] * len(fns)

    monkeypatch.setattr(chat_core.engine, "in_parallel", gather)
    app.run()

    app.chat_input[0].set_value("hola").run()

    assert not app.exception
    assert not landed  # the stop cut the turn where it was pressed
    assert provider.calls == 0  # and no answer was ever asked for


def test_a_stop_lands_while_waiting_on_the_first_token(app, paths, provider,
                                                       monkeypatch):
    """The provider takes its time; the reader gives up before it answers.

    write_stream draws nothing until the first token, so this is the wait the
    reader is staring at when they press stop — and the one stretch where
    nothing but the pump gives the runtime a chance to act on it.
    """
    slow = threading.Event()

    def stream(api_key, model, system, messages):
        provider.calls += 1
        slow.wait(3)  # the model, thinking, with nothing on screen yet
        yield "demasiado tarde"

    provider.stream = stream
    pump = chat_core._pump
    # The press itself: on the script thread, just as the stream is picked up.
    monkeypatch.setattr(chat_core, "_pump",
                        lambda chunks, **kw: (_press_stop(), pump(chunks, **kw))[1])
    app.run()

    app.chat_input[0].set_value("hola").run()
    slow.set()

    assert not app.exception
    app.run()
    answer = _thread(paths)[-1]
    assert answer["stopped"] is True
    assert "demasiado tarde" not in answer["content"]


def test_a_stop_lands_inside_the_panel_fragment(app, paths, provider,
                                                monkeypatch):
    kept_going: list[str] = []

    def gather(*fns, tick=None, **kw):
        _press_stop()
        tick()
        kept_going.append("gathered")
        return [None] * len(fns)

    monkeypatch.setattr(chat_core.engine, "in_parallel", gather)
    at = AppTest.from_string(FRAGMENT_SCRIPT, default_timeout=30)
    at.run()

    at.chat_input[0].set_value("hola").run()

    assert not at.exception
    assert not kept_going
    assert provider.calls == 0


def test_a_gather_that_never_answers_does_not_hold_the_turn(app, paths,
                                                            provider,
                                                            monkeypatch):
    """A provider that accepts the routing call and never replies used to keep
    the turn in "gathering" indefinitely. The pass has a deadline now."""
    seen: list[float | None] = []

    def gather(*fns, timeout=None, **kw):
        seen.append(timeout)
        return [None] * len(fns)

    monkeypatch.setattr(chat_core.engine, "in_parallel", gather)
    app.run()

    app.chat_input[0].set_value("hola").run()

    assert not app.exception
    assert seen and all(t == chat_core.GATHER_DEADLINE for t in seen)
