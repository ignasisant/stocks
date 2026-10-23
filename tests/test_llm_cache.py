"""The Anthropic paths mark the system prompt's parts as cache breakpoints."""

from __future__ import annotations

import sys
import types

from stocks.web import llm, metering


def test_a_plain_string_is_one_marked_block_and_a_prompt_one_per_part():
    assert llm._system_blocks("hello") == [
        {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}
    ]
    blocks = llm._system_blocks(llm.Prompt("head", "", "tail"))
    assert [b["text"] for b in blocks] == ["head", "tail"]
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)
    # Four breakpoints per request: three parts at most, the last message is
    # the fourth.
    assert len(llm._system_blocks(llm.Prompt("a", "b", "c", "d"))) == 3


def test_a_prompt_reads_as_its_whole_string_everywhere_else():
    p = llm.Prompt("head ", "book ", "tail")
    assert p == "head book tail" and len(p) == 14
    assert p.blocks == ("head ", "book ", "tail")
    assert f"{p}" == "head book tail" and p.split() == ["head", "book", "tail"]


class _Usage:
    input_tokens, cache_read_input_tokens = 10, 900
    cache_creation_input_tokens, output_tokens = 50, 20


def _fake_sdk(seen: dict) -> types.ModuleType:
    class _Stream:
        text_stream = iter(["ok"])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(usage=_Usage(), stop_reason="end_turn")

    class _Messages:
        def stream(self, **kw):
            seen["stream"] = kw
            return _Stream()

        def create(self, **kw):
            seen["create"] = kw
            return types.SimpleNamespace(
                usage=_Usage(), stop_reason="end_turn",
                content=[types.SimpleNamespace(type="text", text="done")])

    class Anthropic:
        def __init__(self, api_key):
            self.messages = _Messages()

    return types.SimpleNamespace(Anthropic=Anthropic)


def test_the_stream_sends_the_parts_and_a_breakpoint_on_the_last_turn(monkeypatch):
    seen: dict = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_sdk(seen))
    system = llm.Prompt("persona ", "book ", "view")
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"},
            {"role": "user", "content": "again"}]
    with metering.metered() as meter:
        out = "".join(llm._anthropic_stream("k", "claude-sonnet-5-5", system, msgs))
    assert out == "ok"
    sent = seen["stream"]
    assert [b["text"] for b in sent["system"]] == ["persona ", "book ", "view"]
    assert sent["messages"][-1]["content"] == [
        {"type": "text", "text": "again", "cache_control": {"type": "ephemeral"}}
    ]
    assert sent["messages"][0] == msgs[0]
    assert msgs[-1]["content"] == "again"  # the caller's history untouched
    assert meter.cached() == 900 and meter.cache_write() == 50


def test_the_tool_loop_marks_the_same_parts(monkeypatch):
    seen: dict = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_sdk(seen))
    run = llm._anthropic_tools("k", "m", llm.Prompt("persona ", "book"),
                               [{"role": "user", "content": "q"}], [],
                               lambda name, args: "", 2)
    assert run.text == "done"
    sent = seen["create"]
    assert [b["text"] for b in sent["system"]] == ["persona ", "book"]
    assert sent["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
