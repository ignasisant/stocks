"""Run the chat's real LLM skill router over the trigger questions.

    uv run python scripts/eval_router.py [--provider free] [--skill ID ...]
                                         [--repeat N] [--pace S] [--strict]
                                         [--keyword]

The questions are `evals/router/triggers.yaml` (`stocks.chat.router_eval`):
per skill, ~6 it must be picked for and ~3 near-misses it must not be picked
for. Each one goes through `chat_skills.classify` on the provider's cheapest
model, exactly as an auto-mode turn does, and the per-skill hit rate and
false-positive rate are printed. A question the router failed on (None: a dead
key, a rate limit) counts as no pick and is reported at the end.

Opt-in and never in CI: it needs a key (<PROVIDER>_API_KEY for a bring-your-own
provider, the [free_llm] secrets for `free`) and costs one cheap call per
question (~150 questions). A measurement: the exit code is 0 unless --strict
(then 1 when any skill's recall is under 50 % or a near-miss leaks).
--keyword runs the offline keyword fallback instead, no key needed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from stocks import obs
from stocks.chat import router_eval
from stocks.web import chat_skills, llm


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", default="free", choices=sorted(llm.PROVIDERS))
    ap.add_argument("--skill", action="append", default=[],
                    help="only this skill's questions (repeatable)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="ask every question N times (models are not deterministic)")
    ap.add_argument("--pace", type=float, default=0.0,
                    help="seconds between calls (free-tier rate limits)")
    ap.add_argument("--keyword", action="store_true",
                    help="score the offline keyword fallback, no model")
    ap.add_argument("--verbose", action="store_true", help="list misses and leaks")
    ap.add_argument("--strict", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = _args()
    obs.setup(os.environ.get("STOCKS_LOG_LEVEL") or "WARNING")
    unknown = set(args.skill) - chat_skills.valid_ids()
    if unknown:
        print(f"unknown skill: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    failed = 0
    if args.keyword:
        def route(q: str) -> list[str] | None:
            return chat_skills.heuristic(q)
    else:
        provider = llm.PROVIDERS[args.provider]
        key = os.environ.get(f"{args.provider.upper()}_API_KEY", "")
        if provider.needs_key and not key:
            print(f"{args.provider.upper()}_API_KEY is not set", file=sys.stderr)
            return 2
        first = True

        def route(q: str) -> list[str] | None:
            nonlocal first, failed
            if args.pace and not first:
                time.sleep(args.pace)
            first = False
            ids = chat_skills.classify(provider, key, q)
            if ids is None:
                failed += 1
            return ids

    cases = router_eval.load()
    rows: dict[str, router_eval.Row] = {}
    for _ in range(max(1, args.repeat)):
        for sid, row in router_eval.score(route, cases, set(args.skill)).items():
            acc = rows.setdefault(sid, router_eval.Row(sid))
            acc.hit += row.hit
            acc.total += row.total
            acc.false_pos += row.false_pos
            acc.near += row.near
            acc.missed += row.missed
            acc.leaked += row.leaked

    print(f"{'skill':<17}{'hit':>8}{'recall':>8}{'leak':>8}")
    for sid, r in rows.items():
        print(f"{sid:<17}{f'{r.hit}/{r.total}':>8}{r.recall:>8.0%}"
              f"{f'{r.false_pos}/{r.near}':>8}")
        if args.verbose:
            for q in dict.fromkeys(r.missed):
                print(f"    miss  {q}")
            for q in dict.fromkeys(r.leaked):
                print(f"    leak  {q}")
    recall, fp = router_eval.totals(rows)
    print(f"{'ALL':<17}{'':>8}{recall:>8.0%}{fp:>8.0%}  "
          "(recall, near-miss false-positive rate)")
    if failed:
        print(f"{failed} call(s) failed and counted as no pick (dead key, "
              "rate limit?): read the rates with that in mind")
    bad = [r for r in rows.values() if r.recall < 0.5 or r.false_pos]
    return 1 if args.strict and bad else 0


if __name__ == "__main__":
    sys.exit(main())
