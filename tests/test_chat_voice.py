"""Voice notes: the clip becomes text, the text becomes an ordinary question.

Two promises are pinned here. The transcription guards refuse a clip before it
costs the operator's Whisper quota — silence, a tap, a recording left running
— and every refusal names a copy key that actually exists in the catalogs.
And a transcript enters the conversation through the same seed a clicked
suggestion uses, so it is rate-limited, stored and answered like any typed
message, and carries a badge saying it was spoken.
"""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from stocks.web import auth, chat_core, llm, stt

CATALOG = (Path(__file__).resolve().parents[1] / "src" / "stocks" / "web"
           / "locales")


def _wav(seconds: float = 2.0, rate: int = 16_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


@pytest.fixture
def keyed(monkeypatch):
    """A deploy whose [free_llm] groq key is set."""
    monkeypatch.setattr(llm, "free_secret",
                        lambda name: "k" if name == "groq" else "")
    return None


class _Resp:
    text = "  cuánto    peso tengo en NVDA "


_HEARD = _Resp()


def _fake_openai(monkeypatch, *, resp=_HEARD, boom: Exception | None = None):
    """Stand in for the groq endpoint; returns what the call was made with."""
    seen: dict = {}

    class _Transcriptions:
        def create(self, **kw):
            seen.update(kw)
            if boom is not None:
                raise boom
            return resp

    class _Audio:
        transcriptions = _Transcriptions()

    class _Client:
        audio = _Audio()

        def __init__(self, **kw):
            seen["init"] = kw

    monkeypatch.setattr("openai.OpenAI", _Client)
    return seen


# ------------------------------------------------------------------ backend


def test_no_key_means_no_microphone(monkeypatch):
    monkeypatch.setattr(llm, "free_secret", lambda name: "")
    assert stt.available() is False


def test_a_configured_key_offers_transcription(keyed):
    assert stt.available() is True


def test_clip_seconds_reads_a_wav_and_shrugs_at_anything_else():
    assert stt.clip_seconds(_wav(1.5)) == pytest.approx(1.5, abs=0.01)
    assert stt.clip_seconds(b"not audio at all") is None


def test_the_spoken_text_is_what_comes_back(keyed, monkeypatch):
    seen = _fake_openai(monkeypatch)
    assert stt.transcribe(_wav(), language="es") == "cuánto peso tengo en NVDA"
    # The locale rides along as Whisper's language hint, and the clip goes to
    # groq's endpoint rather than to OpenAI's default base_url.
    assert seen["language"] == "es"
    assert seen["init"]["base_url"] == stt._BASE_URL
    assert seen["model"] == stt._DEFAULT_MODEL


def test_a_backend_that_answers_with_a_bare_string_is_accepted(keyed, monkeypatch):
    _fake_openai(monkeypatch, resp="plain text answer")
    assert stt.transcribe(_wav()) == "plain text answer"


def test_a_model_override_is_a_config_change(keyed, monkeypatch):
    monkeypatch.setattr(llm, "free_secret",
                        lambda name: {"groq": "k",
                                      "groq_stt_model": "whisper-large-v3"}
                        .get(name, ""))
    seen = _fake_openai(monkeypatch)
    stt.transcribe(_wav())
    assert seen["model"] == "whisper-large-v3"


# --------------------------------------------------------------- the guards


def test_nothing_recorded_never_reaches_the_endpoint(keyed, monkeypatch):
    seen = _fake_openai(monkeypatch)
    with pytest.raises(stt.TranscriptionFailed) as err:
        stt.transcribe(b"")
    assert err.value.key == "chat.voice_empty"
    assert not seen


def test_a_tap_on_the_button_is_not_a_question(keyed, monkeypatch):
    seen = _fake_openai(monkeypatch)
    with pytest.raises(stt.TranscriptionFailed) as err:
        stt.transcribe(_wav(0.1))
    assert err.value.key == "chat.voice_empty"
    assert not seen


def test_a_recording_left_running_is_refused_by_duration(keyed, monkeypatch):
    seen = _fake_openai(monkeypatch)
    with pytest.raises(stt.TranscriptionFailed) as err:
        stt.transcribe(_wav(stt.MAX_SECONDS + 1))
    assert err.value.key == "chat.voice_too_long"
    assert err.value.fields == {"seconds": int(stt.MAX_SECONDS)}
    assert not seen


def test_an_unreadable_blob_still_hits_the_byte_cap(keyed, monkeypatch):
    seen = _fake_openai(monkeypatch)
    with pytest.raises(stt.TranscriptionFailed) as err:
        stt.transcribe(b"\x00" * (stt.MAX_BYTES + 1))
    assert err.value.key == "chat.voice_too_long"
    assert not seen


def test_a_dead_endpoint_fails_the_note_and_not_the_panel(keyed, monkeypatch):
    _fake_openai(monkeypatch, boom=RuntimeError("403 Forbidden"))
    with pytest.raises(stt.TranscriptionFailed) as err:
        stt.transcribe(_wav())
    assert err.value.key == "chat.voice_failed"


def test_a_clip_whisper_heard_nothing_in_says_so(keyed, monkeypatch):
    class _Empty:
        text = "   "

    _fake_openai(monkeypatch, resp=_Empty())
    with pytest.raises(stt.TranscriptionFailed) as err:
        stt.transcribe(_wav())
    assert err.value.key == "chat.voice_silent"


def test_every_refusal_has_copy_in_every_locale():
    keys = {"chat.voice_empty", "chat.voice_silent", "chat.voice_too_long",
            "chat.voice_failed", "chat.voice_unavailable"}
    for lang in ("en", "es"):
        catalog = json.loads((CATALOG / lang / "chat.json")
                             .read_text(encoding="utf-8"))
        assert keys <= set(catalog), f"{lang} is missing {keys - set(catalog)}"


# ------------------------------------------------------- inside the drawer

SCRIPT = """
from stocks.web import chat_core
chat_core.render_conversation("panel", chat_core.active_provider(), "m", "k")
"""

WATCHLIST = """\
watchlist:
  - ticker: NVDA
    name: Nvidia
"""


class _Provider:
    id = "free"
    label = "Aguait AI"
    needs_key = False
    models = ("m",)
    default_model = "m"

    def stream(self, api_key, model, system, messages):
        yield "the answer"

    def error_key(self, exc):
        return "chat.provider_busy"


class _Clip:
    """What st.chat_input hands back in `audio`: an UploadedFile-shaped WAV."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


@pytest.fixture
def paths(tmp_path):
    p = auth.UserPaths(
        root=tmp_path,
        watchlist=tmp_path / "watchlist.yaml",
        db=tmp_path / "portfolio.db",
        last_import=tmp_path / "last_import.json",
        prefs=tmp_path / "prefs.json",
        chat=tmp_path / "chat.json",
        bank=tmp_path / "bank.json",
        action=tmp_path / "daily_action.json",
    )
    p.watchlist.write_text(WATCHLIST)
    return p


@pytest.fixture
def app(monkeypatch, paths):
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "watchlist_path", lambda: paths.watchlist)
    monkeypatch.setattr(chat_core, "active_provider", lambda: _Provider())
    monkeypatch.setattr(chat_core.engine, "attempts", lambda prefs: [])
    monkeypatch.setattr(chat_core.engine, "in_parallel",
                        lambda *fns, **kw: [None] * len(fns))
    monkeypatch.setattr(chat_core, "_try_action", lambda *a: None)
    monkeypatch.setattr(chat_core, "_maybe_autotitle", lambda *a: False)
    return AppTest.from_string(SCRIPT, default_timeout=30)


def _records(app) -> bool:
    """Whether the composer drew the microphone beside its paperclip."""
    return app.chat_input[0].proto.accept_audio


def _speaks(monkeypatch, said: str | Exception, *, typed: str = ""):
    """Submit a voice note through the composer's own return value.

    AppTest cannot press a browser microphone, so the recording is injected
    where st.chat_input would have handed it over — which is also the only
    seam that exercises the real transcribe-then-ask path in render order.
    """
    monkeypatch.setattr(chat_core.stt, "available", lambda: True)
    monkeypatch.setattr(chat_core, "_submitted",
                        lambda value: (typed, [], _Clip(_wav())))

    def _heard(audio, **kw):
        if isinstance(said, Exception):
            raise said
        return said

    monkeypatch.setattr(chat_core.stt, "transcribe", _heard)


def test_the_composer_hides_the_microphone_when_nothing_can_transcribe(
        app, monkeypatch):
    monkeypatch.setattr(chat_core.stt, "available", lambda: False)
    app.run()
    assert not app.exception
    assert _records(app) is False


def test_the_composer_offers_the_microphone_when_a_key_is_set(app, monkeypatch):
    monkeypatch.setattr(chat_core.stt, "available", lambda: True)
    app.run()
    assert not app.exception
    assert _records(app) is True
    # Recorded at Whisper's own rate, so nothing resamples on arrival.
    assert app.chat_input[0].proto.audio_sample_rate == stt.SAMPLE_RATE


def test_a_voice_note_is_asked_through_the_real_turn_pipeline(
        app, monkeypatch, paths):
    _speaks(monkeypatch, "how concentrated am I")
    app.run()
    assert not app.exception
    thread = auth.load_chat(paths.chat)
    asked = [m for m in thread if m["role"] == "user"]
    assert [m["content"] for m in asked] == ["how concentrated am I"]
    # Marked as spoken: a misheard ticker should be explainable on reload.
    assert asked[0]["voice"] is True
    # And answered, which is the point of joining the typed path at all.
    assert thread[-1]["role"] == "assistant"


def test_a_note_recorded_over_typed_text_arrives_as_one_question(
        app, monkeypatch, paths):
    _speaks(monkeypatch, "and how about ASML", typed="NVDA weight?")
    app.run()
    assert not app.exception
    asked = [m for m in auth.load_chat(paths.chat) if m["role"] == "user"]
    assert asked[0]["content"] == "NVDA weight? and how about ASML"


def test_a_failed_transcription_leaves_no_question_behind(
        app, monkeypatch, paths):
    _speaks(monkeypatch, stt.TranscriptionFailed("chat.voice_failed"))
    app.run()
    assert not app.exception
    assert not paths.chat.exists()
    assert any("could not be transcribed" in m.value for m in app.markdown)
