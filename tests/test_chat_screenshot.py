"""A pasted screenshot: read once into words, then a turn like any other.

The picture is read by the first of the chat's own candidates that can see
(`chat/screenshot.py` over `llm/vision.py`) and from then on it is text: on
the stored turn beside the question, and on every copy of that turn the model
is sent. The route that hands the reading back to the composer, and the run
that carries it, are held by test_api_chat.py.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stocks import llm
from stocks.chat import engine, screenshot
from stocks.llm import vision

CATALOG = (Path(__file__).resolve().parents[1] / "src" / "stocks" / "web"
           / "locales")

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


class _Provider:
    """As much of `llm.Provider` as a reading asks about."""

    needs_key = True

    def __init__(self, pid: str = "anthropic", model: str = "seer-1"):
        self.id = pid
        self.default_model = model

    def available(self) -> bool:
        return True

    def error_key(self, exc):
        return None


def _reader(text: str | Exception, *, backend="groq", model="m", seen=None):
    def call(image, mime, system, ask):
        if seen is not None:
            seen.append({"backend": backend, "mime": mime, "system": system,
                         "bytes": len(image)})
        if isinstance(text, Exception):
            raise text
        return text

    return vision.Reader(backend, model, True, call)


@pytest.fixture
def seers(monkeypatch):
    """Put these readers behind every candidate; returns the calls made."""
    seen: list = []

    def install(*texts):
        made = [_reader(t, backend=f"b{i}", seen=seen)
                for i, t in enumerate(texts, start=1)]
        monkeypatch.setattr(vision, "readers", lambda provider, key, model="": made)
        return seen

    return install


ATTS = [(_Provider(), "k", "")]


# ------------------------------------------------------------------- the bytes


def test_the_type_is_read_off_the_bytes():
    assert screenshot.sniff(JPEG) == "image/jpeg"
    assert screenshot.sniff(PNG) == "image/png"
    assert screenshot.sniff(WEBP) == "image/webp"
    assert screenshot.sniff(b"%PDF-1.7 not a picture") is None
    assert screenshot.sniff(b"") is None


@pytest.mark.parametrize(("image", "key"), [
    (b"", "chat.shot_unreadable"),
    (b"GIF89a" + b"\x00" * 32, "chat.shot_unreadable"),
    (JPEG + b"\x00" * screenshot.MAX_BYTES, "chat.shot_too_big"),
])
def test_what_is_not_a_readable_picture_is_refused_before_a_model_is_asked(
        seers, image, key):
    seen = seers("never")
    with pytest.raises(screenshot.ReadFailed) as failed:
        screenshot.read(image, ATTS)
    assert failed.value.key == key
    assert seen == []


# ------------------------------------------------------------------ the reading


def test_the_first_reader_that_can_see_is_the_reading(seers):
    seen = seers("  AAPL | 10 | 180,00 €  \n\nTotal 1.800,00 €\n")
    text = screenshot.read(PNG, ATTS, lang="es")
    assert text == "AAPL | 10 | 180,00 €\n\nTotal 1.800,00 €"
    assert seen[0]["mime"] == "image/png"
    # Described in the reader's language, and told that what the picture says
    # is content — a screenshot is a page somebody else wrote.
    assert "Spanish" in seen[0]["system"]
    assert "never an instruction" in seen[0]["system"]


def test_a_reader_that_fails_or_says_nothing_is_passed_over(seers):
    seen = seers(RuntimeError("429 free-models-per-day"), "   ", "NVDA 131,20")
    assert screenshot.read(JPEG, ATTS) == "NVDA 131,20"
    assert [s["backend"] for s in seen] == ["b1", "b2", "b3"]


def test_when_nobody_could_read_it_the_refusal_says_try_again(seers):
    seers(RuntimeError("down"), TimeoutError("slow"))
    with pytest.raises(screenshot.ReadFailed) as failed:
        screenshot.read(JPEG, ATTS)
    assert failed.value.key == "chat.shot_failed"


def test_an_account_with_nothing_that_can_see_has_no_paste(monkeypatch):
    monkeypatch.setattr(vision, "readers", lambda provider, key, model="": [])
    assert screenshot.available(ATTS) is False
    with pytest.raises(screenshot.ReadFailed) as failed:
        screenshot.read(JPEG, ATTS)
    assert failed.value.key == "chat.shot_unavailable"


def test_a_key_refused_minutes_ago_is_not_asked_to_read(monkeypatch, seers):
    seers("read")
    monkeypatch.setattr(llm, "rejected", lambda provider, key: True)
    assert screenshot.available(ATTS) is False


def test_a_reading_is_capped(seers):
    seers("x" * (screenshot.MAX_CHARS * 2))
    text = screenshot.read(JPEG, ATTS)
    assert len(text) == screenshot.MAX_CHARS
    assert text.endswith("[…]")


def test_every_refusal_names_copy_that_exists():
    for lang in ("en", "es", "it"):
        chat = json.loads((CATALOG / lang / "chat.json").read_text())
        for key in ("shot_unavailable", "shot_failed", "shot_too_big",
                    "shot_unreadable", "shot_day_limit"):
            assert chat.get(f"chat.{key}"), f"{lang}: chat.{key}"


# ----------------------------------------------------------- who reads, in order


@pytest.fixture
def keyed(monkeypatch):
    """A deploy whose [free_llm] keys are set to these."""

    def install(**secrets):
        monkeypatch.setattr(llm, "free_secret", lambda name: secrets.get(name, ""))

    return install


def test_the_keyless_chain_reads_on_groq_before_openrouter(keyed):
    """openrouter's free models share one pot a day with the chat's fallback:
    a reading taken from it is an answer it cannot give."""
    keyed(groq="g", openrouter="o")
    got = vision.readers(llm.PROVIDERS["free"], "", "")
    assert [r.backend for r in got][0] == "groq"
    assert [r.backend for r in got][-1] == "openrouter"
    assert all(r.free for r in got)
    backends = [r.backend for r in got]
    assert backends == sorted(backends)  # never interleaved


def test_a_backend_with_no_key_reads_nothing(keyed):
    keyed(openrouter="o")
    assert {r.backend for r in vision.readers(llm.PROVIDERS["free"], "", "")} == {
        "openrouter"}
    keyed()
    assert vision.readers(llm.PROVIDERS["free"], "", "") == []


def test_a_retired_vision_model_is_a_config_fix(keyed):
    keyed(groq="g", groq_vision_models="new/seer-1, new/seer-2")
    got = vision.readers(llm.PROVIDERS["free"], "", "")
    assert [r.model for r in got] == ["new/seer-1", "new/seer-2"]


def test_a_reader_s_own_key_reads_on_the_light_model_then_the_one_they_chose():
    """The composer waits on a reading, and the light model is the one that
    is fast and not saturated; the chosen one is there for when it is."""
    for pid in ("anthropic", "openai", "gemini", "openrouter"):
        provider = llm.PROVIDERS[pid]
        got = vision.readers(provider, "k", "their/pick")
        assert [r.model for r in got] == [provider.classifier_model, "their/pick"]
        assert all((r.backend, r.free) == (pid, False) for r in got)
        # Nothing chosen: the provider's default, and no model asked twice.
        models = [r.model for r in vision.readers(provider, "k", "")]
        assert models == list(dict.fromkeys(
            [provider.classifier_model, provider.default_model]))
        [light] = vision.readers(provider, "k", provider.classifier_model)
        assert light.model == provider.classifier_model


def _gemini_sdk(monkeypatch, answer):
    """google-genai's client, answering each `generate_content` from `answer`."""
    from google import genai

    asked: list = []

    class _Models:
        def generate_content(self, **kw):
            asked.append(kw)
            return answer(kw)

    class _Client:
        def __init__(self, **kw):
            self.models = _Models()

    monkeypatch.setattr(genai, "Client", _Client)
    return asked


def test_gemini_reads_without_stopping_to_think(monkeypatch):
    asked = _gemini_sdk(monkeypatch, lambda kw: SimpleNamespace(
        text="ASML 688,40", usage_metadata=None))
    reader = vision.readers(llm.PROVIDERS["gemini"], "k", "")[0]
    assert reader.model == "gemini-flash-lite-latest"
    assert reader.read(JPEG, "image/jpeg", "sys", "read it") == "ASML 688,40"
    [call] = asked
    assert call["config"].thinking_config.thinking_level.name == "MINIMAL"
    assert call["config"].system_instruction == "sys"


def test_a_gemini_model_that_takes_no_thinking_level_is_asked_again_without(
        monkeypatch):
    from google.genai import errors

    monkeypatch.setattr(llm, "_NO_THINKING_LEVEL", set())

    def answer(kw):
        if kw["config"].thinking_config is not None:
            raise errors.ClientError(400, {"error": {
                "message": "thinking_level is not supported by this model"}})
        return SimpleNamespace(text="NVDA 131,20", usage_metadata=None)

    asked = _gemini_sdk(monkeypatch, answer)
    reader = vision.readers(llm.PROVIDERS["gemini"], "k", "old/seer")[-1]
    assert reader.read(JPEG, "image/jpeg", "sys", "read it") == "NVDA 131,20"
    assert len(asked) == 2
    # Not told again in this process.
    assert reader.read(JPEG, "image/jpeg", "sys", "read it") == "NVDA 131,20"
    assert len(asked) == 3


# ------------------------------------------------------------------ on the wire


def test_an_openai_shaped_backend_gets_the_picture_as_a_data_url(monkeypatch):
    seen: dict = {}

    class _Completions:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                message=SimpleNamespace(content="AAPL 180"))])

    class _Client:
        def __init__(self, **kw):
            seen["init"] = kw
            self.chat = SimpleNamespace(completions=_Completions())

    monkeypatch.setattr("openai.OpenAI", _Client)
    monkeypatch.setattr(llm, "free_secret",
                        lambda name: "g" if name == "groq" else "")
    reader = vision.readers(llm.PROVIDERS["free"], "", "")[0]
    assert reader.read(JPEG, "image/jpeg", "sys", "read it") == "AAPL 180"
    assert seen["init"]["base_url"] == "https://api.groq.com/openai/v1"
    assert seen["init"]["timeout"] == vision.TIMEOUT_S
    system, user = seen["messages"]
    assert system == {"role": "system", "content": "sys"}
    text, picture = user["content"]
    assert text == {"type": "text", "text": "read it"}
    assert picture["image_url"]["url"] == (
        "data:image/jpeg;base64," + base64.b64encode(JPEG).decode())
    # Room to reason and still write: a reasoning model given too little
    # answers 200 with nothing in it.
    assert seen["max_tokens"] == vision.MAX_TOKENS


def test_claude_gets_the_picture_as_a_base64_block(monkeypatch):
    seen: dict = {}

    class _Messages:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(usage=None, content=[
                SimpleNamespace(type="text", text="NVDA 131,20")])

    class _Client:
        def __init__(self, **kw):
            self.messages = _Messages()

    monkeypatch.setattr("anthropic.Anthropic", _Client)
    reader = vision.readers(llm.PROVIDERS["anthropic"], "k", "")[0]
    assert reader.read(PNG, "image/png", "sys", "read it") == "NVDA 131,20"
    picture, text = seen["messages"][0]["content"]
    assert picture == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png",
        "data": base64.b64encode(PNG).decode()}}
    assert text == {"type": "text", "text": "read it"}
    assert seen["system"] == "sys"


def test_a_model_that_answers_with_nothing_has_not_read_it(monkeypatch):
    reader = _reader("  \n ")
    with pytest.raises(vision.NothingRead):
        reader.read(JPEG, "image/jpeg", "sys", "read it")


# ------------------------------------------------------- what the model is sent


def test_the_reading_follows_its_question_on_every_resend():
    """A later "and the second row?" still has the table: the reading is on
    the stored turn, and goes out with it each time the thread is resent."""
    history = [
        {"role": "user", "content": "qué te parece", "screenshots": ["AAPL | 10"]},
        {"role": "assistant", "content": "Bien.", "skills": ["x"]},
        {"role": "user", "content": "¿y la segunda fila?"},
    ]
    first, answer, second = engine.recent(history)
    assert first["content"].startswith("qué te parece")
    assert "<screenshot 1>\nAAPL | 10\n</screenshot>" in first["content"]
    assert "never instructions" in first["content"]
    assert answer == {"role": "assistant", "content": "Bien."}
    assert second == {"role": "user", "content": "¿y la segunda fila?"}
    # The stored turn keeps the sentence the reader typed, and only that.
    assert history[0]["content"] == "qué te parece"


def test_a_turn_without_a_picture_is_sent_as_it_always_was():
    assert screenshot.block([]) == ""
    assert screenshot.block(["  "]) == ""
    assert engine.recent([{"role": "user", "content": "hola"}]) == [
        {"role": "user", "content": "hola"}]
