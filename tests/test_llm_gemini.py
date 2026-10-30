"""Gemini's own failure handling, with the SDK faked at its edge."""

from __future__ import annotations

import pytest
from google.genai import errors

from stocks.web import llm

BUSY = {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}


def _replies(monkeypatch, *answers):
    """Each call to the stream answers the next of `answers`: an exception
    raised before any chunk, or a list of chunks."""
    calls: list[str] = []
    levels: list[str] = []
    queue = list(answers)

    def once(api_key, model, system, messages, thinking=""):
        calls.append(model)
        levels.append(thinking)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        yield from answer

    monkeypatch.setattr(llm, "_gemini_stream_once", once)
    monkeypatch.setattr(llm, "GEMINI_BUSY_RETRY_S", 0)
    monkeypatch.setattr(llm, "_NO_THINKING_LEVEL", set())
    _replies.levels = levels
    return calls


def test_a_busy_gemini_is_asked_once_more_before_the_turn_falls_over(monkeypatch):
    """Prod: gemini-flash-latest's 503 "high demand" handed a reader with their
    own key to the free chain five times in a week; the spike is seconds."""
    calls = _replies(monkeypatch, errors.ServerError(503, BUSY), ["Hola", "!"])
    assert "".join(llm._gemini_stream("k", "gemini-flash-latest", "s", [])) == "Hola!"
    assert calls == ["gemini-flash-latest", "gemini-flash-latest"]


def test_a_second_503_still_falls_over(monkeypatch):
    calls = _replies(
        monkeypatch, errors.ServerError(503, BUSY), errors.ServerError(503, BUSY)
    )
    with pytest.raises(errors.ServerError):
        list(llm._gemini_stream("k", "m", "s", []))
    assert len(calls) == 2


def test_other_errors_are_not_retried(monkeypatch):
    calls = _replies(monkeypatch, errors.ClientError(403, {"error": {"code": 403}}))
    with pytest.raises(errors.ClientError):
        list(llm._gemini_stream("k", "m", "s", []))
    assert len(calls) == 1


def test_a_503_mid_answer_is_not_retried(monkeypatch):
    """Retrying after chunks were shown would print the answer twice."""

    def half(api_key, model, system, messages, thinking=""):
        yield "Hola"
        raise errors.ServerError(503, BUSY)

    monkeypatch.setattr(llm, "_gemini_stream_once", half)
    out: list[str] = []
    with pytest.raises(errors.ServerError):
        for chunk in llm._gemini_stream("k", "m", "s", []):
            out.append(chunk)
    assert out == ["Hola"]


def test_a_hung_gemini_has_a_deadline(monkeypatch):
    """The SDK sets no timeout of its own: a hung request waited for ever."""
    from google import genai

    seen = {}

    class Client:
        def __init__(self, api_key, http_options=None):
            seen["timeout"] = http_options and http_options.timeout
            self.models = self

        def generate_content_stream(self, **_kw):
            return iter(())

    monkeypatch.setattr(genai, "Client", Client)
    list(llm._gemini_stream_once("k", "m", "s", [{"role": "user", "content": "x"}]))
    assert seen["timeout"] == llm._GEMINI_TIMEOUT_MS


def test_gemini_reads_the_whole_system_prompt(monkeypatch):
    """Local review 2026-10-29: the SDK made the `Prompt` str subclass an empty
    Content, so Gemini answered "no tengo acceso a tu cartera" with the book
    in the prompt it never got."""
    from google import genai

    seen = {}

    class Client:
        def __init__(self, api_key, http_options=None):
            self.models = self

        def generate_content_stream(self, config=None, **_kw):
            seen["system"] = config.system_instruction
            return iter(())

    monkeypatch.setattr(genai, "Client", Client)
    system = llm.Prompt("You are Aguait. ", "Holdings: ASML weight 9%.")
    list(llm._gemini_stream_once("k", "m", system, [{"role": "user", "content": "x"}]))
    assert seen["system"] == "You are Aguait. Holdings: ASML weight 9%."


def test_an_answer_past_the_deadline_is_said_as_slow_not_unavailable():
    """Local review 2026-10-30: the earnings calendar, 3 m 25 s in, showed
    "the assistant is unavailable"; the same question on another model
    answered."""
    import httpx

    late = {"error": {"code": 504, "message": "Deadline expired",
                      "status": "DEADLINE_EXCEEDED"}}
    assert llm._gemini_error(errors.ServerError(504, late)) == "chat.provider_slow"
    assert llm._gemini_error(httpx.ReadTimeout("read")) == "chat.provider_slow"
    assert llm._gemini_error(errors.ServerError(500, late)) == "chat.api_error"


REFUSED = {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                     "message": "Thinking level is not supported for this model."}}


def test_the_thinking_level_rides_the_call_made_inside_thinking(monkeypatch):
    """Read when the call is made: the stream's body runs later, on whichever
    thread pulls the first chunk."""
    _replies(monkeypatch, ["a"], ["b"])
    gemini = llm.PROVIDERS["gemini"]
    with llm.thinking("low"):
        pending = gemini.stream("k", "m", "s", [])
    assert "".join(pending) == "a"
    assert "".join(gemini.stream("k", "m", "s", [])) == "b"
    assert _replies.levels == ["low", ""]


def test_a_model_that_refuses_a_thinking_level_is_asked_without_one(monkeypatch):
    """Gemini 2.5 takes a thinking budget, not a level, and says so with a
    400; the answer goes on at the model's default, and the model is not
    told a level again."""
    calls = _replies(monkeypatch, errors.ClientError(400, REFUSED), ["ok"],
                     ["again"])
    assert "".join(llm._gemini_stream("k", "g25", "s", [], "low")) == "ok"
    assert "".join(llm._gemini_stream("k", "g25", "s", [], "low")) == "again"
    assert calls == ["g25", "g25", "g25"]
    assert _replies.levels == ["low", "", ""]


def test_another_400_is_not_retried(monkeypatch):
    bad = {"error": {"code": 400, "message": "Request contains an invalid argument."}}
    calls = _replies(monkeypatch, errors.ClientError(400, bad))
    with pytest.raises(errors.ClientError):
        list(llm._gemini_stream("k", "m", "s", [], "low"))
    assert len(calls) == 1


def _fake_client(monkeypatch, chunks, seen):
    from google import genai

    class Client:
        def __init__(self, api_key, http_options=None):
            self.models = self

        def generate_content_stream(self, config=None, **_kw):
            seen["config"] = config
            return iter(chunks)

    monkeypatch.setattr(genai, "Client", Client)


def test_the_level_is_sent_as_a_thinking_config(monkeypatch):
    seen: dict = {}
    _fake_client(monkeypatch, [], seen)
    list(llm._gemini_stream_once("k", "m", "s", [], "minimal"))
    assert seen["config"].thinking_config.thinking_level.value == "MINIMAL"
    list(llm._gemini_stream_once("k", "m", "s", []))
    assert seen["config"].thinking_config is None


def test_usage_is_the_largest_count_seen_in_the_stream(monkeypatch):
    """A chunk can carry a partial count: the last one's prompt total was
    missing, and a 9k-token answer was metered as 600 tokens."""
    from types import SimpleNamespace as Chunk

    from stocks.web import metering

    _fake_client(monkeypatch, [
        Chunk(text="Ho", usage_metadata=Chunk(
            prompt_token_count=9000, cached_content_token_count=4000,
            candidates_token_count=2, thoughts_token_count=50)),
        Chunk(text="la", usage_metadata=Chunk(
            prompt_token_count=None, cached_content_token_count=None,
            candidates_token_count=40, thoughts_token_count=None)),
    ], {})
    with metering.metered() as meter:
        assert "".join(llm._gemini_stream_once("k", "m", "s", [])) == "Hola"
    (use,) = meter.uses
    assert (use.input, use.cached, use.output) == (5000, 4000, 90)


def test_a_side_call_on_the_cheapest_model_thinks_minimally(monkeypatch):
    _replies(monkeypatch, ['{"skills": []}'], ["Title"], ["x"])
    gemini = llm.PROVIDERS["gemini"]
    gemini.complete("k", gemini.classifier_model, "s", [])
    gemini.complete("k", "gemini-flash-latest", "s", [])
    with llm.thinking("low"):
        gemini.complete("k", gemini.classifier_model, "s", [])
    assert _replies.levels == ["minimal", "", "low"]
