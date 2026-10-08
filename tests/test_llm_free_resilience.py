"""Free chain under load (prod 2026-10-06): short 429 waits, 402 memory,
OpenRouter's model list, tool results kept under a TPM cap. No network."""

import pytest

import stocks.web.llm as llm
from stocks.web.llm import FreeTierExhausted, _FreeBackend


class _HttpError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status_code = status


_GROQ_429 = ("Rate limit reached for model `openai/gpt-oss-120b` (TPM): Limit "
             "8000, Used 2953, Requested 5262. Please try again in {}.")


def _ok(bid, chunks):
    def stream(api_key, model, system, messages):
        yield from chunks

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream)


def _dead(bid, exc):
    def stream(api_key, model, system, messages):
        raise exc
        yield  # unreachable; makes this a generator like the real backends

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream)


@pytest.fixture(autouse=True)
def slept(monkeypatch):
    waits = []
    monkeypatch.setattr(llm, "_sleep", waits.append)
    monkeypatch.setattr(llm, "_free_dead", set())
    return waits


def test_short_wait_parses_the_retry_after_the_backend_names():
    def err(t, status=429):
        return _HttpError(status, _GROQ_429.format(t))

    assert llm._short_wait(err("1.6125s")) == pytest.approx(1.8625)
    assert llm._short_wait(err("307.5ms")) == pytest.approx(0.5575)
    assert llm._short_wait(err("7.9s")) is None  # past the bound: next backend
    assert llm._short_wait(err("6m7.3s")) is None
    assert llm._short_wait(err("1s", status=500)) is None
    assert llm._short_wait(RuntimeError("nothing")) is None


def test_a_short_rate_limit_is_waited_out_on_the_same_backend(monkeypatch, slept):
    calls = []

    def stream(api_key, model, system, messages):
        calls.append(model)
        if len(calls) == 1:
            raise _HttpError(429, _GROQ_429.format("1.6s"))
        yield "ok"

    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _FreeBackend("groq", "k", "m", stream), _ok("openrouter", ["x"])])
    assert list(llm._free_stream("", "auto", "sys", [])) == ["ok"]
    assert calls == ["m", "m"] and len(slept) == 1


def test_a_long_rate_limit_moves_on_without_sleeping(monkeypatch, slept):
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _dead("groq", _HttpError(429, _GROQ_429.format("21s"))),
        _ok("openrouter", ["x"])])
    assert list(llm._free_stream("", "auto", "sys", [])) == ["x"]
    assert slept == []


def test_the_wait_is_taken_once_per_backend(monkeypatch, slept):
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _dead("groq", _HttpError(429, _GROQ_429.format("1s")))])
    with pytest.raises(FreeTierExhausted):
        list(llm._free_stream("", "auto", "sys", []))
    assert len(slept) == 1


def test_a_402_marks_the_backend_dead_for_the_process(monkeypatch):
    secrets = {"groq": "g", "openrouter": "o"}
    monkeypatch.setattr(llm, "_free_secrets", lambda: dict(secrets))
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _dead("groq", _HttpError(402, "payment_required")),
        _ok("openrouter", ["x"])])
    assert list(llm._free_stream("", "auto", "sys", [])) == ["x"]
    assert "groq" in llm._free_dead
    monkeypatch.undo()
    monkeypatch.setattr(llm, "_free_dead", {"groq"})
    monkeypatch.setattr(llm, "_free_secrets", lambda: dict(secrets))
    assert {b.id for b in llm._free_backends()} == {"openrouter"}


def test_openrouter_falls_to_its_next_model_when_the_first_is_overloaded(monkeypatch):
    monkeypatch.setattr(llm, "_free_secrets", lambda: {"openrouter": "o"})
    got = llm._free_backends()
    assert got[0].model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert len(got) >= 2 and not got[1].primary

    seen = []

    def stream(api_key, model, system, messages):
        seen.append(model)
        if model.startswith("nvidia"):
            raise _HttpError(503, "Upstream error from Nvidia: overloaded")
        yield "ok"

    chain = [_FreeBackend("openrouter", "o", b.model, stream, primary=b.primary)
             for b in got]
    monkeypatch.setattr(llm, "_free_backends", lambda: chain)
    assert list(llm._free_stream("", "auto", "sys", [])) == ["ok"]
    assert seen[0].startswith("nvidia") and len(seen) == 2
    assert "openrouter" not in llm._free_live_model


def test_fallback_models_are_configurable(monkeypatch):
    monkeypatch.setattr(llm, "_free_secrets", lambda: {
        "openrouter": "o", "openrouter_fallback_models": "a:free, b:free,"})
    assert [b.model for b in llm._free_backends()][1:] == ["a:free", "b:free"]


def test_a_backend_that_streams_nothing_counts_as_failed(monkeypatch):
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _ok("groq", []), _ok("openrouter", ["x"])])
    assert list(llm._free_stream("", "auto", "sys", [])) == ["x"]


def test_tool_loop_retries_a_short_rate_limit_once(monkeypatch, slept):
    calls = []

    def backend(base_url, **_opts):
        def run(*a, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise _HttpError(429, _GROQ_429.format("2s"))
            return llm.ToolRun("DONE", [])
        return run

    monkeypatch.setattr(llm, "_openai_compat_tools", backend)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _FreeBackend("groq", "k", "m", None, "u")])
    run = llm._free_tools("", "", "sys", [], [], lambda *a: "", 2)
    assert run.text == "DONE" and len(calls) == 2 and len(slept) == 1


def test_tool_results_are_squeezed_to_the_backends_cap():
    from stocks.chat import tokens

    convo = [{"role": "system", "content": "sys"},
             {"role": "user", "content": "q"},
             {"role": "tool", "tool_call_id": "1", "content": "word " * 9000},
             {"role": "tool", "tool_call_id": "2", "content": "short"}]
    assert tokens.count_messages(convo) > 7000
    llm._squeeze_tool_results(convo, 7000)
    assert tokens.count_messages(convo) <= 7000
    assert convo[3]["content"] == "short" and convo[0]["content"] == "sys"
