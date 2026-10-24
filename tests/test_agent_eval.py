"""agent_eval: the gather's golden cases, their routing, and the frozen prompt.

The cases themselves run against a real model in scripts/eval_agent.py; what
needs no model is checked here."""

import json
import os
from pathlib import Path

import pytest

from stocks.chat import agent, agent_eval, toolbox
from stocks.web.llm import ToolCall

CASES = agent_eval.load()


def test_every_case_names_real_tools_and_a_real_profile():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
    for c in CASES:
        named = {*c.must, *c.any_of, *c.must_not, *c.fixtures, *c.fails}
        assert named <= set(toolbox.TOOLS), (c.id, named - set(toolbox.TOOLS))
        assert c.profile in ("fast", "deep") and c.depth in ("", "fast", "deep")
        assert c.kind in agent_eval.KINDS


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_each_case_is_routed_to_its_profile(case):
    assert agent.profile_for(case.message, case.asked_depth()).name == case.profile


def test_a_brief_case_names_an_angle_and_its_page(monkeypatch, tmp_path):
    from stocks.chat import brief

    briefed = [c for c in CASES if c.brief]
    assert briefed
    for c in briefed:
        assert c.brief in brief.ANGLES and c.ticker, c.id
    monkeypatch.setattr(brief, "build", lambda angle, ticker, **kw: brief.Brief(
        angle, ticker, brief.Facts(ticker), [], f" [{angle} on {ticker}]"))
    ctx = agent_eval.context(tmp_path)
    assert briefed[0].sent(ctx).endswith(f" [{briefed[0].brief} on {briefed[0].ticker}]")
    assert CASES[0].sent(ctx) == CASES[0].message
    assert agent_eval.Case("c", "m", brief="full").asked_depth() == "deep"
    assert agent_eval.Case("c", "m", brief="full", depth="fast").asked_depth() == "fast"


def _calls(*names):
    return [ToolCall(n, {}, "x") for n in names]


def test_the_rubric_says_which_rule_broke():
    case = agent_eval.Case("c", "m", must=("search_web",),
                           any_of=("get_quotes", "read_page"),
                           must_not=("portfolio_snapshot",), max_calls=2)
    assert agent_eval.score(case, _calls("search_web", "read_page")) == []
    assert agent_eval.score(case, _calls("portfolio_snapshot", "x", "y")) == [
        "did not call search_web", "called none of get_quotes, read_page",
        "called portfolio_snapshot", "3 calls, over 2"]


def test_fetch_nothing_is_a_rule_of_its_own():
    case = agent_eval.Case("c", "m", max_calls=0)
    assert agent_eval.score(case, []) == []
    assert agent_eval.score(case, _calls("search_web")) == ["1 calls, over 0"]


def test_a_run_reads_fixtures_and_leaves_the_real_tools_in_place(tmp_path):
    real = dict(toolbox.TOOLS)
    case = agent_eval.Case("c", "m", fixtures={"get_quotes": "ASML 600 EUR"})
    with agent_eval.fixture_tools(case):
        run = toolbox.executor(agent_eval.context(tmp_path))
        assert run("get_quotes", {"tickers": ["ASML"]}) == "ASML 600 EUR"
        assert run("search_web", {"query": "q"}) == (
            toolbox.UNTRUSTED + agent_eval.DEFAULT_FIXTURES["search_web"])
    assert toolbox.TOOLS == real


def test_a_failing_tool_raises_and_the_model_reads_that_it_failed(tmp_path):
    case = agent_eval.Case("c", "m", fails=("get_quotes",))
    with agent_eval.fixture_tools(case):
        run = toolbox.executor(agent_eval.context(tmp_path))
        assert run("get_quotes", {"tickers": ["NVDA"]}) == (
            "get_quotes failed: ConnectionError.")
        assert run("search_web", {"query": "q"}) == (
            toolbox.UNTRUSTED + agent_eval.DEFAULT_FIXTURES["search_web"])


def _ran(passed: bool = True, tokens: int = 10, usd: float | None = 0.0,
         **more) -> agent_eval.Run:
    return agent_eval.Run(() if passed else ("did not call get_quotes",),
                          tokens, usd, 1.0, **more)


def test_a_regression_must_pass_every_run_and_a_capability_one():
    reg = agent_eval.Case("r", "m")
    cap = agent_eval.Case("c", "m", kind="capability")
    two_of_three = [_ran(), _ran(False), _ran()]
    flaky = agent_eval.tally(reg, two_of_three)
    assert (flaky.passes, flaky.runs, flaky.mark, flaky.ok) == (
        2, 3, "flaky", False)
    assert agent_eval.tally(cap, two_of_three).ok
    assert not agent_eval.tally(cap, [_ran(False)]).ok
    assert agent_eval.tally(reg, [_ran()] * 3).ok


def test_one_unpriced_run_leaves_the_case_without_a_cost():
    t = agent_eval.tally(agent_eval.Case("r", "m"),
                         [_ran(usd=0.01), _ran(usd=None)])
    assert t.usd is None and t.tokens == 20


def test_a_tally_keeps_each_run_and_what_the_judge_spent():
    t = agent_eval.tally(agent_eval.Case("r", "m"), [
        _ran(tools=("search_web",), models=("openai/gpt-oss-120b",),
             judge_tokens=300, judge_usd=0.002),
        _ran(False, judge_tokens=200, judge_usd=None)])
    assert t.detail[0]["models"] == ("openai/gpt-oss-120b",)
    assert t.detail[1]["broke"] == ("did not call get_quotes",)
    assert (t.judge_tokens, t.judge_usd, t.usd) == (500, None, 0.0)
    back = json.loads(json.dumps(agent_eval.record([t], provider="free")))
    assert back["cases"]["r"]["detail"][0]["tools"] == ["search_web"]


def test_a_case_with_no_run_fails_a_strict_run():
    cases = [agent_eval.Case("a", "m"), agent_eval.Case("b", "m")]
    ran = [agent_eval.tally(cases[0], [_ran()])]
    assert agent_eval.verdict(cases, ran) == ["1 cases have no run: b"]
    assert agent_eval.verdict(cases[:1], ran) == []
    assert agent_eval.verdict(cases, []) == ["2 cases have no run: a, b"]


def _run(**cases):
    """Each case as (passes, runs, tokens)."""
    return agent_eval.record(
        [agent_eval.Tally(cid, "regression", runs=runs, passes=passes,
                          tokens=tokens)
         for cid, (passes, runs, tokens) in cases.items()], provider="free")


def test_compare_names_what_got_worse_first_then_better_then_spend():
    old = _run(a=(3, 3, 100), b=(1, 3, 100), c=(3, 3, 100), d=(3, 3, 100))
    new = _run(a=(2, 3, 100), b=(3, 3, 110), c=(3, 3, 200), e=(1, 1, 50))
    assert agent_eval.compare(old, new) == [
        "worse  a: 3/3 -> 2/3",
        "better b: 1/3 -> 3/3",
        "better e: new case, 1/1",
        "spend  c: 33 -> 67 tokens a run",
        "gone   d: dropped"]
    assert agent_eval.compare(old, old) == []


def test_compare_names_a_prompt_change_and_slower_or_dearer_runs():
    def run(prompt, seconds, usd):
        return agent_eval.record([
            agent_eval.Tally("a", "regression", runs=2, passes=2, tokens=100,
                             seconds=seconds, usd=usd)], prompt=prompt)

    assert agent_eval.compare(run("p1", 20.0, 0.01), run("p2", 40.0, 0.02)) == [
        "prompt p1 -> p2",
        "spend  a: 10.0s -> 20.0s a run",
        "spend  a: $0.0050 -> $0.0100 a run"]
    assert agent_eval.compare(run("p1", 20.0, None), run("p1", 22.0, 0.5)) == []


def test_latest_is_the_newest_run_on_the_same_provider_and_model(tmp_path):
    for at, provider in (("2026-10-01", "free"), ("2026-10-03", "free"),
                         ("2026-10-05", "anthropic")):
        agent_eval.save({"at": at, "provider": provider, "model": ""},
                        tmp_path / f"{at}-{provider}.json")
    (tmp_path / "junk.json").write_text("{", encoding="utf-8")
    assert agent_eval.latest("free", "", tmp_path).name == "2026-10-03-free.json"
    assert agent_eval.latest("openai", "", tmp_path) is None


def test_the_eval_context_offers_the_engines(tmp_path):
    names = {s.name for s in toolbox.specs(agent_eval.context(tmp_path),
                                           engines=True)}
    assert toolbox.ENGINES | {"decisions"} <= names


# --------------------------------------------------------------- snapshot
# The gather's prompt and tool descriptions are what the eval measured. A
# change to either is a change in behaviour that the cases should be run
# against before it ships, so it shows up here as a diff to accept:
#   UPDATE_PROMPT_SNAPSHOT=1 uv run pytest tests/test_agent_eval.py


SNAPSHOT = Path(__file__).resolve().parents[1] / "evals" / "agent" / "prompts.snapshot"


def _prompts() -> str:
    tools = [{"name": spec.name, "description": spec.description,
              "schema": spec.schema} for spec, _ in toolbox.TOOLS.values()]
    return ("# GATHER_SYSTEM\n" + agent.GATHER_SYSTEM
            + "\n\n# DEEP_SYSTEM\n" + agent.DEEP_SYSTEM
            + "\n\n# ALERT_NUDGE\n" + agent.ALERT_NUDGE
            + "\n\n# TOOLS\n" + json.dumps(tools, indent=1, sort_keys=True,
                                          ensure_ascii=False) + "\n")


def test_the_gather_prompt_is_the_one_the_eval_measured():
    if os.environ.get("UPDATE_PROMPT_SNAPSHOT"):
        SNAPSHOT.write_text(_prompts(), encoding="utf-8")
    assert _prompts() == SNAPSHOT.read_text(encoding="utf-8"), (
        "the gather prompt changed: run scripts/eval_agent.py, then "
        "UPDATE_PROMPT_SNAPSHOT=1 to accept it")
