"""Run the chat's gather on the golden cases and score what it fetched.

    uv run python scripts/eval_agent.py --dry-run
    uv run python scripts/eval_agent.py [--provider free] [--model M] [--case ID ...]
                                        [--repeat N] [--max-usd X] [--timeout S]
                                        [--pace S] [--retry-dead N] [--verbose]
                                        [--save] [--baseline PATH|last]
                                        [--judge] [--judge-model M] [--judge-runs N]

The cases are `evals/agent/cases.yaml` (`stocks.chat.agent_eval`). Every tool
answers from a fixture, so a run reads no page and no ledger: what it costs
is the model's tokens, printed per run with the seconds it took and the
models that answered. A bring-your-own-key provider reads its key from
<PROVIDER>_API_KEY (ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY); the
free chain uses the [free_llm] secrets like the app does.

The gather gets the seconds a turn gives it in the app: --timeout (90, the
default of `engine.answer_stream`) or the profile's own when longer, so a
FAST run is not cut at 25 s where a reader's would go on.

A measurement, not a gate: the exit code is 0 unless --strict. Models are
not deterministic, the free ones least of all; --repeat runs every case N
times, a round of all of them at a time, and each case reads k/N. A
regression case must pass all N (pass^k), a capability case one (pass@k).
A run no model answered (a rate limit, a dead key) is retried after 30 s
(--retry-dead times) and then left out, not failed; --strict fails on it all
the same, since a case with no run cannot be said to pass. --max-usd stops
the run once it has spent that much. --save keeps the run under
evals/agent/runs/, each run's broken rules, tools and models included, and
--baseline compares this one with a saved run (`last`: the newest on the
same provider and model): pass rates, tokens, seconds and dollars.

On the free chain a FAST run spends ~6k tokens. groq allows 8k a minute:
back to back, the chain falls over to the OpenRouter slugs within a few runs
and the baseline mixes models; --pace 30 keeps every run on groq. It also
allows 200k a day, ~30 runs: a full 20-case baseline at --repeat 3 takes two
days, or a BYOK provider. Past the daily cap every run is a 90 s timeout on
the OpenRouter slugs, not a measurement.

--judge also writes the answer (the app's system prompt over what was
gathered, as a turn does) and has a model judge it (`stocks.chat.agent_judge`)
against the case's `goals` and the score rubrics, on the provider's default
model unless --judge-model. Two more model calls for each of the first
--judge-runs runs of a case (1; 0 judges every run). Still no gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from stocks import obs
from stocks.chat import agent, agent_eval, agent_judge
from stocks.web import llm, metering

# What a turn gives its gather in the app (`engine.answer_stream` timeout_s);
# the gather runs on the longer of it and the profile's own.
TURN_TIMEOUT_S = 90.0
# A run no model answered waits this long before it is tried again.
DEAD_WAIT_S = 30.0


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", default="free", choices=sorted(llm.PROVIDERS))
    ap.add_argument("--model", default="",
                    help="the answering model: deep cases run on it, fast "
                         "ones on the provider's classifier model")
    ap.add_argument("--case", action="append", default=[],
                    help="only these case ids (repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the cases and their routing, call no model")
    ap.add_argument("--repeat", type=int, default=1,
                    help="runs per case")
    ap.add_argument("--max-usd", type=float, default=None,
                    help="stop once the run has spent this many dollars")
    ap.add_argument("--timeout", type=float, default=TURN_TIMEOUT_S,
                    help="seconds a turn gives the gather, as the app does")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="seconds to wait between runs (30 keeps the free "
                         "chain on groq)")
    ap.add_argument("--retry-dead", type=int, default=1,
                    help="times a run no model answered is tried again")
    ap.add_argument("--verbose", action="store_true",
                    help="log each tool call and model answer")
    ap.add_argument("--save", action="store_true",
                    help="keep the run under evals/agent/runs/")
    ap.add_argument("--baseline", default="",
                    help="a saved run to compare with, or 'last'")
    ap.add_argument("--judge", action="store_true",
                    help="write each answer and have a model judge it")
    ap.add_argument("--judge-model", default="",
                    help="the judge's model (the provider's default)")
    ap.add_argument("--judge-runs", type=int, default=1,
                    help="judge the first N runs of each case (0: all)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a regression misses a run, a "
                         "capability passes none or a case has no run")
    return ap.parse_args()


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True,
                              cwd=agent_eval.CASES.parent).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def _prompt_hash() -> str:
    """The frozen gather prompt the run measured (tests/test_agent_eval.py)."""
    snap = agent_eval.CASES.parent / "prompts.snapshot"
    try:
        return hashlib.sha256(snap.read_bytes()).hexdigest()[:8]
    except OSError:
        return ""


def _baseline(arg: str, provider: str, model: str) -> dict | None:
    if not arg:
        return None
    path = (agent_eval.latest(provider, model) if arg == "last"
            else Path(arg))
    if path is None or not path.exists():
        print(f"\nno baseline {'on ' + provider if arg == 'last' else arg}")
        return None
    return {"path": path, **json.loads(path.read_text(encoding="utf-8"))}


def _mean(judged: dict[str, dict], sid: str) -> str:
    got = [j["scores"][sid] for j in judged.values()
           if j["scores"].get(sid) is not None]
    return f"{sum(got) / len(got):.1f}" if got else "-"


def _answer(provider, key: str, model: str, message: str,
            ev: agent.Evidence) -> str:
    """What a turn would say over `ev`: the app's own system prompt."""
    from stocks.chat import engine

    return provider.complete(
        key, model or provider.default_model, engine.system_prompt({}, ""),
        [{"role": "user", "content": ev.augment(message)}])


def _judged(provider, key: str, args, c, ev: agent.Evidence, sent: str
            ) -> agent_judge.Judgment | None:
    try:
        answer = _answer(provider, key, args.model, sent, ev)
        said = agent_judge.judge(provider, key, c.goals, c.message, ev.calls,
                                 answer, model=args.judge_model)
    except Exception as exc:  # noqa: BLE001 — a rate limit, off contract
        print(f"     judge: none ({type(exc).__name__})")
        return None
    met = sum(v == "met" for v in said.goals.values())
    scores = " ".join(f"{k}={'-' if v is None else v}"
                      for k, v in said.scores.items())
    print(f"     judge: goals {met}/{len(said.goals)}  {scores}")
    for goal, verdict in said.goals.items():
        if verdict != "met":
            print(f"       {verdict}: {goal} — {said.why.get(goal, '')}")
    return said


def main() -> int:
    args = _args()
    # Formatted, one line each, instead of the bare stderr of an unconfigured
    # root logger; INFO adds every tool call and model answer.
    obs.setup(os.environ.get("STOCKS_LOG_LEVEL")
              or ("INFO" if args.verbose else "WARNING"))
    cases = [c for c in agent_eval.load()
             if not args.case or c.id in args.case]
    if not cases:
        print("no case matches", file=sys.stderr)
        return 2

    if args.dry_run:
        for c in cases:
            routed = agent.profile_for(c.message, c.asked_depth()).name
            mark = "ok " if routed == c.profile else "BAD"
            print(f"{mark} {c.id:<20} {routed:<4} {c.kind[:3]}  {c.message}")
        return 0

    provider = llm.PROVIDERS[args.provider]
    key = os.environ.get(f"{args.provider.upper()}_API_KEY", "")
    if provider.needs_key and not key:
        print(f"{args.provider.upper()}_API_KEY is not set", file=sys.stderr)
        return 2
    if not provider.supports_tools():
        print(f"{args.provider} has no tool loop", file=sys.stderr)
        return 2

    if args.provider == "free" and args.model:
        print("the free chain picks its own model; --model ignored")
        args.model = ""

    repeat = max(1, args.repeat)
    spent, priced, stopped, dead = 0.0, True, "", 0
    runs: dict[str, list[agent_eval.Run]] = {c.id: [] for c in cases}
    judgments: dict[str, list[agent_judge.Judgment]] = {c.id: [] for c in cases}
    first = True
    with tempfile.TemporaryDirectory() as tmp:
        ctx = agent_eval.context(Path(tmp))
        # A round of every case at a time: a rate-limit window or the cap
        # then costs one run of several cases, not every run of one.
        for _ in range(repeat):
            for c in cases:
                if args.max_usd is not None and spent >= args.max_usd:
                    stopped = f"stopped at {_usd(spent)}, the --max-usd cap"
                    break
                if args.pace and not first:
                    time.sleep(args.pace)
                first = False
                profile = agent.profile_for(c.message, c.asked_depth())
                sent = c.sent(ctx)
                for tries in range(max(0, args.retry_dead) + 1):
                    if tries:
                        print(f"retry {c.id} in {DEAD_WAIT_S:.0f}s "
                              "(no model answered)")
                        time.sleep(DEAD_WAIT_S)
                    t0 = time.perf_counter()
                    with (agent_eval.fixture_tools(c),
                          metering.metered() as meter):
                        ev = agent.gather(
                            provider, key,
                            [{"role": "user", "content": sent}], ctx,
                            model=args.model, profile=profile,
                            timeout=max(args.timeout, profile.timeout))
                    seconds = time.perf_counter() - t0
                    if ev.ok:
                        break
                if not ev.ok:
                    # No model answered (rate limit, dead key): a fact about
                    # the provider, not the prompt, so it is not a run.
                    dead += 1
                    print(f"skip {c.id:<20} no model answered")
                    continue
                broke = agent_eval.score(c, ev.calls)
                if profile.name != c.profile:
                    broke.insert(0, f"routed {profile.name}, wanted {c.profile}")
                cost = meter.usd()
                priced = priced and cost is not None
                spent += cost or 0.0
                models = tuple(meter.models())
                print(f"{'FAIL' if broke else 'pass'} {c.id:<20} "
                      f"{profile.name:<4} {len(ev.calls):>2} calls "
                      f"{meter.tokens():>7} tok {_usd(cost):>9} "
                      f"{seconds:5.1f}s  {' '.join(ev.tools_used) or '-'}"
                      f"  [{', '.join(models) or '?'}]")
                for why in broke:
                    print(f"     - {why}")
                jtokens, jcost = 0, 0.0
                if args.judge and (not args.judge_runs
                                   or len(runs[c.id]) < args.judge_runs):
                    with metering.metered() as judging:
                        said = _judged(provider, key, args, c, ev, sent)
                    jtokens, jcost = judging.tokens(), judging.usd()
                    priced = priced and jcost is not None
                    spent += jcost or 0.0
                    if said is not None:
                        judgments[c.id].append(said)
                runs[c.id].append(agent_eval.Run(
                    tuple(broke), meter.tokens(), cost, round(seconds, 1),
                    tuple(ev.tools_used), models, jtokens, jcost))
                if args.max_usd is not None and (cost is None or jcost is None):
                    stopped = "stopped: the model is unpriced, so the cap can't hold"
                    break
            if stopped:
                break

    tallies = [agent_eval.tally(c, runs[c.id]) for c in cases if runs[c.id]]
    judged = {cid: agent_judge.summary(js) for cid, js in judgments.items() if js}
    print()
    for t in tallies:
        print(f"{t.mark:<5} {t.id:<20} {t.kind[:3]} {t.passes}/{t.runs}"
              f"{'' if t.ok else '  <- ' + ('flaky' if t.passes else 'missing')}")
    runs_n = sum(t.runs for t in tallies)
    passes = sum(t.passes for t in tallies)
    tokens = sum(t.tokens for t in tallies)
    jtokens = sum(t.judge_tokens for t in tallies)
    print(f"\n{passes}/{runs_n} runs pass · "
          f"{sum(t.ok for t in tallies)}/{len(tallies)} cases ok · "
          f"{tokens} tokens{f' · judge {jtokens} tokens' if jtokens else ''} · "
          f"{_usd(spent if priced else None)}")
    if judged:
        met = sum(j["met"] for j in judged.values())
        goals = sum(j["goals"] for j in judged.values())
        print(f"judge: {met}/{goals} goals met · "
              + " ".join(f"{s.id} {_mean(judged, s.id)}"
                         for s in agent_judge.SCORES))
    if dead:
        print(f"{dead} runs left out: no model answered")
    if stopped:
        print(stopped)

    run = agent_eval.record(
        tallies, at=datetime.now(UTC).isoformat(timespec="seconds"),
        sha=_sha(), prompt=_prompt_hash(), provider=args.provider,
        model=args.model, repeat=repeat, timeout=args.timeout, dead=dead,
        stopped=stopped, complete=not stopped and not dead)
    if judged:
        run["judged"] = judged
        run["judge_model"] = args.judge_model or provider.default_model
    base = _baseline(args.baseline, args.provider, args.model)
    if base is not None:
        if args.case:  # a partial run: the cases left out are not gone
            base["cases"] = {k: v for k, v in base.get("cases", {}).items()
                             if k in args.case}
        lines = agent_eval.compare(base, run) + agent_judge.compare(base, run)
        print(f"\nvs {base['path'].name} ({base.get('sha', '?')}, "
              f"{base.get('at', '?')}, repeat {base.get('repeat', '?')}, "
              f"timeout {base.get('timeout', 25.0)}s"
              f"{'' if base.get('complete') else ', partial'}):")
        print("\n".join(f"  {x}" for x in lines) or "  no change")
    if args.save:
        stamp = run["at"][:19].replace(":", "")
        name = (f"{stamp}-{run['sha']}-{args.provider}"
                f"{'-' + args.model.replace('/', '_') if args.model else ''}.json")
        print(f"saved {agent_eval.save(run, agent_eval.RUNS / name)}")

    if args.strict and (failed := agent_eval.verdict(cases, tallies)):
        print("\nstrict: " + "\n        ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
