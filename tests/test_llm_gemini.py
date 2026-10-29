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
    queue = list(answers)

    def once(api_key, model, system, messages):
        calls.append(model)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        yield from answer

    monkeypatch.setattr(llm, "_gemini_stream_once", once)
    monkeypatch.setattr(llm, "GEMINI_BUSY_RETRY_S", 0)
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

    def half(api_key, model, system, messages):
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
