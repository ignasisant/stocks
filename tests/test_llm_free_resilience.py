"""Free chain under load (prod 2026-10-06): short 429 waits, 402 memory,
OpenRouter's model list, tool results kept under a TPM cap. No network."""

import pytest

import stocks.llm as llm
from stocks.llm import FreeTierExhausted, ToolSpec, _FreeBackend


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
    monkeypatch.setattr(llm, "_free_resting", {})
    monkeypatch.setattr(llm, "_free_slow", {})
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
    assert llm._retry_after(err("6m7.3s")) == pytest.approx(367.3)


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


def test_a_long_rate_limit_rests_the_backend_until_the_wait_it_named(
        monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: now[0])
    calls = []

    def groq(api_key, model, system, messages):
        calls.append("groq")
        if len(calls) == 1:
            raise _HttpError(429, _GROQ_429.format("20s"))
        yield "g"

    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _FreeBackend("groq", "k", "m", groq), _ok("openrouter", ["x"])])
    assert list(llm._free_stream("", "auto", "sys", [])) == ["x"]
    # Inside the window the next turn goes straight to the next backend...
    assert list(llm._free_stream("", "auto", "sys", [])) == ["x"]
    assert calls == ["groq"]
    # ...and once it lifts, groq answers again.
    now[0] += 21
    assert list(llm._free_stream("", "auto", "sys", [])) == ["g"]
    assert calls == ["groq", "groq"]


def test_a_rate_limited_model_leaves_the_backends_next_model_awake(monkeypatch):
    """groq counts tokens per model: its 120b waiting a minute says nothing
    about its qwen, which used to rest with it (ERR-03, triage 2026-11-05)."""
    calls = []

    def groq(api_key, model, system, messages):
        calls.append(model)
        if model == "gpt-oss-120b":
            raise _HttpError(429, _GROQ_429.format("40s"))
        yield model

    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _FreeBackend("groq", "k", "gpt-oss-120b", groq),
        _FreeBackend("groq", "k", "qwen3.8-27b", groq, primary=False),
        _ok("openrouter", ["x"])])
    assert list(llm._free_stream("", "auto", "sys", [])) == ["qwen3.8-27b"]
    # The next turn skips the resting model, not the backend.
    assert list(llm._free_stream("", "auto", "sys", [])) == ["qwen3.8-27b"]
    assert calls == ["gpt-oss-120b", "qwen3.8-27b", "qwen3.8-27b"]


def test_a_resting_backend_is_still_tried_when_it_is_the_last_awake(
        monkeypatch):
    monkeypatch.setattr(llm, "_free_resting",
                        {("groq", "model-groq"): float("inf")})
    monkeypatch.setattr(llm, "_free_backends", lambda: [_ok("groq", ["g"])])
    assert list(llm._free_stream("", "auto", "sys", [])) == ["g"]


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
        if model == got[0].model:
            raise _HttpError(503, "Upstream error from Nvidia: overloaded")
        yield "ok"

    chain = [_FreeBackend("openrouter", "o", b.model, stream, primary=b.primary)
             for b in got]
    monkeypatch.setattr(llm, "_free_backends", lambda: chain)
    assert list(llm._free_stream("", "auto", "sys", [])) == ["ok"]
    assert seen == [got[0].model, got[1].model]
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
    from stocks.llm import tokens

    convo = [{"role": "system", "content": "sys"},
             {"role": "user", "content": "q"},
             {"role": "tool", "tool_call_id": "1", "content": "word " * 9000},
             {"role": "tool", "tool_call_id": "2", "content": "short"}]
    assert tokens.count_messages(convo) > 7000
    llm._squeeze_tool_results(convo, 7000)
    assert tokens.count_messages(convo) <= 7000
    assert convo[3]["content"] == "short" and convo[0]["content"] == "sys"


class _Clock:
    """`llm._clock`, moved forward by hand by the stream."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _thinking(bid, clock, seconds, then=("late",)):
    """A backend that sends reasoning frames for `seconds`, then text."""

    def stream(api_key, model, system, messages):
        for _ in range(int(seconds)):
            clock.now += 1
            yield llm.Idle()
        yield from then

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream)


def test_a_model_still_thinking_past_the_deadline_gives_way(monkeypatch):
    # prod 2026-10-28: nemotron-3-ultra reasoned 59-242 s before a word while
    # dots-3 answered in 5 s. Reasoning frames keep httpx's read timeout alive.
    clock = _Clock()
    monkeypatch.setattr(llm, "_clock", clock)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _thinking("openrouter", clock, 300), _ok("groq", ["fast"])])

    assert "".join(llm._free_stream("", "", "sys", [])) == "fast"
    assert clock.now == pytest.approx(llm._FIRST_TEXT_S + 1)
    # and it sits out the next turns rather than costing each one 20 s
    assert llm._slow(_FreeBackend("openrouter", "k", "model-openrouter", None))


def test_thinking_frames_never_reach_the_reader(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(llm, "_clock", clock)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _thinking("openrouter", clock, 5, then=("a", "b")), _ok("groq", ["x"])])

    chunks = list(llm._free_stream("", "", "sys", []))
    assert chunks == ["a", "b"]
    assert not llm._free_slow


def test_the_last_model_left_may_think_longer(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(llm, "_clock", clock)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _thinking("openrouter", clock, 150)])

    assert "".join(llm._free_stream("", "", "sys", [])) == "late"


def test_the_last_model_left_still_stops_once_every_caller_has_gone(monkeypatch):
    # prod 2026-11-03: nemotron-3.5-lightning wrote its first word at 585 s,
    # in a worker thread whose caller had timed out minutes before.
    clock = _Clock()
    monkeypatch.setattr(llm, "_clock", clock)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _thinking("openrouter", clock, 585)])

    with pytest.raises(FreeTierExhausted):
        "".join(llm._free_stream("", "", "sys", []))
    assert clock.now == pytest.approx(llm._LAST_FIRST_TEXT_S + 1)


def test_a_model_that_only_thinks_is_no_answer(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(llm, "_clock", clock)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _thinking("openrouter", clock, 3, then=()), _ok("groq", ["x"])])

    assert "".join(llm._free_stream("", "", "sys", [])) == "x"


def _watch(monkeypatch):
    warned = []
    monkeypatch.setattr(llm.obs, "warn", lambda name, **kw: warned.append((name, kw)))
    return warned


def test_a_model_writing_one_line_over_and_over_is_stopped(monkeypatch):
    """Prod 2026-11-10: one line of reasoning 850 times, 226k characters."""
    line = "The user is questioning the daily move shown in the card. Let me check.\n"
    sent = []

    def stream(api_key, model, system, messages):
        for _ in range(1000):
            sent.append(line)
            yield from (line[:30], line[30:])

    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _FreeBackend("openrouter", "k", "nemotron", stream)])
    warned = _watch(monkeypatch)
    out = list(llm._free_stream("", "auto", "sys", []))
    assert "".join(out) == line * 2
    assert isinstance(out[-1], llm.Cut)
    assert len(sent) == 2  # the host's stream was closed, not drained
    assert warned == [("llm.free.degenerate", {
        "backend": "openrouter", "model": "nemotron", "why": "loop",
        "chars": 2 * len(line), "duration_ms": warned[0][1]["duration_ms"]})]


def test_an_answer_past_the_paid_room_is_cut(monkeypatch):
    words = [f"word {i} " for i in range(30_000)]  # no line ever repeats
    monkeypatch.setattr(llm, "_free_backends", lambda: [_ok("groq", words)])
    warned = _watch(monkeypatch)
    out = list(llm._free_stream("", "auto", "sys", []))
    assert isinstance(out[-1], llm.Cut)
    assert llm._MAX_ANSWER_CHARS < len("".join(out)) < llm._MAX_ANSWER_CHARS + 20
    assert warned[0][1]["why"] == "size"


def test_short_repeated_lines_are_prose_not_a_loop(monkeypatch):
    table = ["| a | b |\n", "|---|---|\n", "|---|---|\n", "- yes\n", "- yes\n", "end"]
    monkeypatch.setattr(llm, "_free_backends", lambda: [_ok("groq", table)])
    warned = _watch(monkeypatch)
    assert "".join(llm._free_stream("", "auto", "sys", [])) == "".join(table)
    assert not [w for w in warned if w[0] == "llm.free.degenerate"]


# ------------------------------------------------- tool loop across models


class _Scripted:
    """An OpenAI client whose replies, or raised errors, come from a script."""

    def __init__(self, *script):
        from types import SimpleNamespace

        self.script, self.sent = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        from types import SimpleNamespace

        self.sent.append(kw)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        call = None
        if step == "tool":
            call = [SimpleNamespace(id="c1", type="function", function=SimpleNamespace(
                name="get_quotes", arguments="{}"))]
        msg = SimpleNamespace(
            content=None if call else step, tool_calls=call,
            model_dump=lambda **_: {"role": "assistant", "content": None})
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _tool_loop(monkeypatch, client, *models):
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    monkeypatch.setattr(llm, "_free_gone", set())
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _FreeBackend("groq", "k", m, None, "u", primary=i == 0)
        for i, m in enumerate(models)])
    tools = [ToolSpec("get_quotes", "quotes", {"type": "object", "properties": {}})]
    return llm._free_tools("", "", "sys", [{"role": "user", "content": "q"}],
                           tools, lambda n, a: "quoted", 3)


def test_a_round_groq_rate_limits_goes_on_with_its_next_model(monkeypatch, slept):
    """A deep turn sat out six 10-36 s waits on gpt-oss-120b while qwen, counted
    apart, was idle (prod 2026-11-10, 205 s). The rounds already run stay."""
    client = _Scripted("tool", _HttpError(429, _GROQ_429.format("36s")), "DONE")
    run = _tool_loop(monkeypatch, client, "gpt-oss-120b", "qwen3.8-27b")
    assert run.text == "DONE" and slept == []
    assert [kw["model"] for kw in client.sent] == [
        "gpt-oss-120b", "gpt-oss-120b", "qwen3.8-27b"]
    assert client.sent[2]["messages"][-1] == {
        "role": "tool", "tool_call_id": "c1", "content": "quoted"}
    assert ("groq", "gpt-oss-120b") in llm._free_resting


def test_with_no_model_awake_a_round_sits_out_the_wait_once(monkeypatch, slept):
    client = _Scripted("tool", _HttpError(429, _GROQ_429.format("20s")), "DONE")
    run = _tool_loop(monkeypatch, client, "gpt-oss-120b")
    assert run.text == "DONE" and slept == [pytest.approx(20.25)]
    assert len(client.sent) == 3


def test_a_short_rate_limit_in_a_round_waits_on_the_same_model(monkeypatch, slept):
    client = _Scripted("tool", _HttpError(429, _GROQ_429.format("2s")), "DONE")
    run = _tool_loop(monkeypatch, client, "gpt-oss-120b", "qwen3.8-27b")
    assert run.text == "DONE" and slept == [pytest.approx(2.25)]
    assert [kw["model"] for kw in client.sent][-1] == "gpt-oss-120b"


def test_a_host_hiccup_in_a_round_is_asked_again_once(monkeypatch, slept):
    client = _Scripted("tool", _HttpError(503, "overloaded"),
                       _HttpError(503, "overloaded"), "DONE")
    run = _tool_loop(monkeypatch, client, "gpt-oss-120b", "qwen3.8-27b")
    # Twice down on the one model: the chain's turn, which moves to qwen.
    assert run.text == "DONE"
    assert [kw["model"] for kw in client.sent] == [
        "gpt-oss-120b", "gpt-oss-120b", "gpt-oss-120b", "qwen3.8-27b"]
