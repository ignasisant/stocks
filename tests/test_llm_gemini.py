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
