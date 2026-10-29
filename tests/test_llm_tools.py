"""llm: the per-provider tool loops behind Provider.run_tools."""

import json
from types import SimpleNamespace

import pytest

from stocks.web import llm
from stocks.web.llm import ToolSpec

_TOOLS = [ToolSpec("get_quotes", "live prices",
                   {"type": "object", "properties": {}})]


def _echo(name, args):
    return f"{name}:{sorted(args.items())}"


# ------------------------------------------------------------------ shapes


def test_only_the_providers_with_a_loop_report_tool_support():
    assert llm.PROVIDERS["anthropic"]._tools is not None
    assert llm.PROVIDERS["openai"]._tools is not None
    assert llm.PROVIDERS["free"]._tools is not None
    # Gemini's function calling has its own message shape and is not wired up;
    # it keeps the fixed pre-flight rather than half a loop.
    assert llm.PROVIDERS["gemini"]._tools is None
    assert not llm.PROVIDERS["gemini"].supports_tools()


def test_openrouter_runs_the_openai_loop_and_signs_in_by_pkce():
    openrouter = llm.PROVIDERS["openrouter"]
    assert openrouter.supports_tools()
    assert openrouter.connect_url == "https://openrouter.ai/auth"
    assert openrouter.connect_token_url == "https://openrouter.ai/api/v1/auth/keys"
    # The auto router never rots the way a pinned slug does.
    assert openrouter.models[-1] == "openrouter/auto"
    # Nobody else signs in: their keys are pasted.
    assert [p.id for p in llm.PROVIDERS.values() if p.connect_url] == ["openrouter"]


def test_an_openrouter_account_out_of_credits_is_told_so():
    broke = SimpleNamespace(status_code=402)
    assert llm._openrouter_error(broke) == "chat.no_credits"
    refused = SimpleNamespace(status_code=401)
    assert llm._openrouter_error(refused) == llm._openai_error(refused)


def test_a_saturated_claude_or_chatgpt_reads_as_busy_not_broken():
    # Busy is what lets the chat try the same key's other models
    # (engine._busy_siblings) instead of leaving for the free chain.
    import anthropic
    import httpx
    import openai

    def response(code):
        return httpx.Response(code, request=httpx.Request("POST", "https://x"))

    assert llm._anthropic_error(anthropic.OverloadedError(
        "overloaded", response=response(529), body=None)) == "chat.provider_busy"
    assert llm._anthropic_error(anthropic.InternalServerError(
        "boom", response=response(500), body=None)) == "chat.api_error"
    assert llm._openai_error(openai.InternalServerError(
        "busy", response=response(503), body=None)) == "chat.provider_busy"
    assert llm._openai_error(openai.InternalServerError(
        "boom", response=response(500), body=None)) == "chat.api_error"


def test_run_tools_on_a_provider_without_a_loop_is_a_clear_error():
    with pytest.raises(NotImplementedError):
        llm.PROVIDERS["gemini"].run_tools("k", "m", "s", [], _TOOLS, _echo)


# --------------------------------------------------------------- anthropic


class _AnthropicClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.sent = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.sent.append(kw)
        return self.responses.pop(0)


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _use(tid, name, args):
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=args)


@pytest.fixture
def anthropic_client(monkeypatch):
    import anthropic

    holder = {}

    def factory(*responses):
        client = _AnthropicClient(*responses)
        holder["client"] = client
        monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
        return client

    return factory


def test_anthropic_stops_when_the_model_asks_for_nothing(anthropic_client):
    client = anthropic_client(SimpleNamespace(content=[_text("DONE")]))
    run = llm._anthropic_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                               _TOOLS, _echo, 3)
    assert run.text == "DONE" and run.calls == []
    assert len(client.sent) == 1
    assert client.sent[0]["tools"][0]["name"] == "get_quotes"
    assert "input_schema" in client.sent[0]["tools"][0]  # not "parameters"


def test_anthropic_runs_a_tool_and_feeds_the_result_back(anthropic_client):
    client = anthropic_client(
        SimpleNamespace(content=[_use("tu_1", "get_quotes", {"tickers": ["NVDA"]})]),
        SimpleNamespace(content=[_text("DONE")]),
    )
    run = llm._anthropic_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                               _TOOLS, _echo, 3)
    assert [c.name for c in run.calls] == ["get_quotes"]
    assert run.calls[0].args == {"tickers": ["NVDA"]}
    sent = client.sent[1]["messages"]
    assert sent[-2]["role"] == "assistant"
    assert sent[-1] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_1",
         "content": "get_quotes:[('tickers', ['NVDA'])]"}]}


def test_anthropic_returns_parallel_results_in_one_user_message(anthropic_client):
    # Splitting them across messages teaches the model to stop asking for
    # parallel calls at all.
    client = anthropic_client(
        SimpleNamespace(content=[_use("a", "get_quotes", {}),
                                 _use("b", "get_quotes", {})]),
        SimpleNamespace(content=[_text("DONE")]),
    )
    llm._anthropic_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                         _TOOLS, _echo, 3)
    last = client.sent[1]["messages"][-1]
    assert last["role"] == "user" and len(last["content"]) == 2


def test_a_rounds_calls_run_at_once_and_answer_in_order(anthropic_client):
    # Three searches asked in one turn were asked independently; back to back
    # they are three times the wait.
    import threading
    import time

    inside, most = [0], [0]
    lock = threading.Lock()

    def slow(name, args):
        with lock:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        time.sleep(0.05 if args["n"] == 0 else 0.0)  # the first returns last
        with lock:
            inside[0] -= 1
        return f"r{args['n']}"

    client = anthropic_client(
        SimpleNamespace(content=[_use(f"t{n}", "get_quotes", {"n": n})
                                 for n in range(3)]),
        SimpleNamespace(content=[_text("DONE")]),
    )
    run = llm._anthropic_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                               _TOOLS, slow, 3)
    assert most[0] > 1
    assert [c.result for c in run.calls] == ["r0", "r1", "r2"]
    results = client.sent[1]["messages"][-1]["content"]
    assert [(r["tool_use_id"], r["content"]) for r in results] == [
        ("t0", "r0"), ("t1", "r1"), ("t2", "r2")]


def test_anthropic_stops_at_the_round_cap(anthropic_client):
    forever = [SimpleNamespace(content=[_use(f"t{i}", "get_quotes", {})])
               for i in range(10)]
    client = anthropic_client(*forever)
    run = llm._anthropic_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                               _TOOLS, _echo, 2)
    assert len(client.sent) == 2 and len(run.calls) == 2


def test_anthropic_ends_the_loop_when_told_to_stop(anthropic_client):
    client = anthropic_client(*[
        SimpleNamespace(content=[_use(f"t{i}", "get_quotes", {})])
        for i in range(5)])
    asked = []
    run = llm._anthropic_tools(
        "k", "m", "sys", [{"role": "user", "content": "hi"}], _TOOLS, _echo, 5,
        stop=lambda: asked.append(1) or len(asked) >= 2)
    assert len(client.sent) == 2 and len(run.calls) == 2 and run.text == ""


def test_an_empty_tool_result_is_still_sent_back(anthropic_client):
    # Anthropic rejects an empty tool_result content, and a dropped result
    # leaves the tool_use block unanswered.
    client = anthropic_client(
        SimpleNamespace(content=[_use("tu_1", "get_quotes", {})]),
        SimpleNamespace(content=[_text("DONE")]),
    )
    llm._anthropic_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                         _TOOLS, lambda n, a: "", 3)
    assert client.sent[1]["messages"][-1]["content"][0]["content"] == "(no result)"


# ----------------------------------------------------------- openai-compat


class _Message:
    def __init__(self, content=None, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls

    def model_dump(self, **kw):
        return {"role": "assistant", "content": self.content}


def _tool_call(cid, name, args):
    # `type` is the SDK's discriminator between function and custom tool
    # calls; only function calls carry `.function`.
    return SimpleNamespace(
        id=cid, type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class _OpenAIClient:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.sent.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=self.messages.pop(0))])


@pytest.fixture
def openai_client(monkeypatch):
    import openai

    def factory(*messages):
        client = _OpenAIClient(*messages)
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
        return client

    return factory


def test_openai_puts_the_system_prompt_in_the_messages(openai_client):
    client = openai_client(_Message(content="DONE"))
    run = llm._openai_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                            _TOOLS, _echo, 3)
    assert run.text == "DONE"
    assert client.sent[0]["messages"][0] == {"role": "system", "content": "sys"}
    fn = client.sent[0]["tools"][0]
    assert fn["type"] == "function" and fn["function"]["name"] == "get_quotes"


def test_openai_answers_each_tool_call_by_id(openai_client):
    client = openai_client(
        _Message(tool_calls=[_tool_call("c1", "get_quotes", {"tickers": ["NVDA"]})]),
        _Message(content="DONE"),
    )
    run = llm._openai_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                            _TOOLS, _echo, 3)
    assert run.calls[0].args == {"tickers": ["NVDA"]}
    assert client.sent[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "c1",
        "content": "get_quotes:[('tickers', ['NVDA'])]"}


def test_openai_answers_parallel_calls_in_the_order_asked(openai_client):
    import time

    def slow(name, args):
        time.sleep(0.05 if args["n"] == 0 else 0.0)
        return f"r{args['n']}"

    client = openai_client(
        _Message(tool_calls=[_tool_call(f"c{n}", "get_quotes", {"n": n})
                             for n in range(3)]),
        _Message(content="DONE"),
    )
    llm._openai_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                      _TOOLS, slow, 3)
    sent = client.sent[1]["messages"][-3:]
    assert [(m["tool_call_id"], m["content"]) for m in sent] == [
        ("c0", "r0"), ("c1", "r1"), ("c2", "r2")]


def test_unparseable_arguments_are_sent_back_not_run(openai_client):
    # Run with {}, the call failed on a missing argument and the model read a
    # refusal about the wrong thing.
    bad = SimpleNamespace(id="c1", type="function", function=SimpleNamespace(
        name="get_quotes", arguments="{not json"))
    client = openai_client(
        _Message(tool_calls=[bad, _tool_call("c2", "get_quotes", {"n": 1})]),
        _Message(content="DONE"))
    ran = []
    run = llm._openai_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                            _TOOLS, lambda n, a: ran.append(a) or "ok", 3)
    assert ran == [{"n": 1}] and [c.args for c in run.calls] == [{"n": 1}]
    sent = client.sent[1]["messages"][-2:]
    assert sent == [
        {"role": "tool", "tool_call_id": "c1", "content": llm.BAD_ARGS},
        {"role": "tool", "tool_call_id": "c2", "content": "ok"}]


def test_openai_ends_the_loop_when_told_to_stop(openai_client):
    # The budget is spent: the next call would only be told so.
    client = openai_client(*[
        _Message(tool_calls=[_tool_call(f"c{i}", "get_quotes", {})])
        for i in range(5)])
    run = llm._openai_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                            _TOOLS, _echo, 5, stop=lambda: True)
    assert len(client.sent) == 1 and run.text == "" and len(run.calls) == 1


def test_openai_stops_at_the_round_cap(openai_client):
    client = openai_client(*[
        _Message(tool_calls=[_tool_call(f"c{i}", "get_quotes", {})])
        for i in range(10)])
    llm._openai_tools("k", "m", "sys", [{"role": "user", "content": "hi"}],
                      _TOOLS, _echo, 2)
    assert len(client.sent) == 2


def test_a_reply_without_choices_names_the_upstream_error(monkeypatch):
    # OpenRouter answers an upstream failure with HTTP 200 and no choices; that
    # used to surface as "'NoneType' object is not subscriptable".
    import openai

    reply = SimpleNamespace(choices=None,
                            model_extra={"error": {"message": "provider down"}})
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kw: reply)))
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    with pytest.raises(RuntimeError, match="provider down"):
        llm._openai_tools("k", "m", "sys", [], _TOOLS, _echo, 2)


def test_the_free_chain_caps_retries_and_waits(monkeypatch):
    import openai

    made = []
    client = _OpenAIClient(_Message(content="DONE"))

    def factory(**kw):
        made.append(kw)
        return client

    monkeypatch.setattr(openai, "OpenAI", factory)
    monkeypatch.setattr(llm, "_free_secrets", lambda: {"groq": "gsk-x"})
    run = llm._free_tools("", "auto", "sys", [], _TOOLS, _echo, 2)
    assert run.text == "DONE"
    assert made[0]["max_retries"] == llm._FREE_CLIENT["max_retries"]
    assert made[0]["timeout"] == llm._FREE_CLIENT["timeout"]


# ------------------------------------------------------------- free chain


def test_the_free_chain_moves_on_when_a_backend_refuses(monkeypatch):
    tried = []

    def backend(base_url, **_opts):
        def run(api_key, model, system, messages, tools, execute, rounds,
                cap=0, stop=None):
            tried.append(base_url)
            if base_url == "one":
                raise RuntimeError("no tool support on this model")
            return llm.ToolRun("DONE", [])
        return run

    monkeypatch.setattr(llm, "_openai_compat_tools", backend)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        llm._FreeBackend("a", "k1", "m1", None, "one"),
        llm._FreeBackend("b", "k2", "m2", None, "two"),
    ])
    run = llm._free_tools("", "", "sys", [], _TOOLS, _echo, 3)
    assert tried == ["one", "two"] and run.text == "DONE"


def test_a_call_the_backend_could_not_parse_is_asked_again_once(monkeypatch):
    # Groq's 400 tool_use_failed is the model's slip, and the same request
    # usually parses on a second try: the next backend is a worse model.
    tried = []

    class Unparsed(Exception):
        status_code = 400

    def backend(base_url, **_opts):
        def run(api_key, model, system, messages, tools, execute, rounds,
                cap=0, stop=None):
            tried.append(base_url)
            if len(tried) == 1:
                raise Unparsed("Error code: 400 - {'code': 'tool_use_failed'}")
            return llm.ToolRun("DONE", [])
        return run

    monkeypatch.setattr(llm, "_openai_compat_tools", backend)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        llm._FreeBackend("a", "k1", "m1", None, "one"),
        llm._FreeBackend("b", "k2", "m2", None, "two"),
    ])
    assert llm._free_tools("", "", "sys", [], _TOOLS, _echo, 3).text == "DONE"
    assert tried == ["one", "one"]


def test_the_free_chain_raises_when_every_backend_refuses(monkeypatch):
    monkeypatch.setattr(llm, "_openai_compat_tools", lambda url, **_: (
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("429"))))
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        llm._FreeBackend("a", "k", "m", None, "one")])
    with pytest.raises(llm.FreeTierExhausted):
        llm._free_tools("", "", "sys", [], _TOOLS, _echo, 3)


def test_an_unconfigured_free_chain_has_nothing_to_run(monkeypatch):
    monkeypatch.setattr(llm, "_free_backends", lambda: [])
    with pytest.raises(llm.FreeTierExhausted):
        llm._free_tools("", "", "sys", [], _TOOLS, _echo, 3)


# ----------------------------------------------------------------- usage


def test_each_round_reports_its_tokens_to_the_turns_meter(monkeypatch):
    import openai

    from stocks.web import metering

    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=8,
                            prompt_tokens_details=None)
    replies = [_Message(tool_calls=[_tool_call("c1", "get_quotes", {})]),
               _Message(content="DONE")]
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=replies.pop(0))], usage=usage))))
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    with metering.metered() as m, metering.step("gather"):
        llm._openai_compat_tools(free=True)(
            "k", "gpt-4o", "sys", [{"role": "user", "content": "hi"}],
            _TOOLS, _echo, 3)
    assert [(u.step, u.input, u.output, u.free) for u in m.uses] == [
        ("gather", 120, 8, True)] * 2
    assert m.usd() == 0.0  # the free chain's


def test_anthropic_rounds_report_their_tokens(anthropic_client):
    from stocks.web import metering

    usage = SimpleNamespace(input_tokens=50, output_tokens=5,
                            cache_read_input_tokens=0,
                            cache_creation_input_tokens=0)
    anthropic_client(SimpleNamespace(content=[_text("DONE")], usage=usage))
    with metering.metered() as m:
        llm._anthropic_tools("k", "claude-haiku-4-5", "sys",
                             [{"role": "user", "content": "hi"}], _TOOLS,
                             _echo, 3)
    assert m.tokens() == 55 and m.usd() == pytest.approx(75e-6)
