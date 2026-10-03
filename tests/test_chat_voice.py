"""Voice notes: the clip becomes text, the text becomes an ordinary question.

The transcription guards refuse a clip before it costs the operator's Whisper
quota — silence, a tap, a recording left running — and every refusal names a
copy key that actually exists in the catalogs. The route that hands the
transcript back to the composer is held by test_api_chat.py.
"""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest

from stocks.web import llm, stt

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
