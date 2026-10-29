"""Ask the production assistant the catalog's questions, on several models.

    uv run python scripts/eval_prod.py --dry-run
    uv run python scripts/eval_prod.py [--model SPEC ...] [--area A ...] [--case ID ...]
                                       [--judge SPEC] [--seed] [--pace S]
                                       [--timeout S] [--base URL] [--email E]
                                       [--keep] [--save]

The questions are `evals/prod/questions.yaml` (`stocks.chat.prod_eval`). Each
goes to the deployed app (`--base`, prod by default) as the drawer's own
AG-UI run, on a fresh thread that is deleted afterwards (`--keep` leaves it,
to read in the app). The account is a throwaway one (`--email`), signed in
with a session minted here: prod accepts it because both sides share
`[auth] cookie_secret`. It never touches a real reader's book. `--seed` gives
it the demo book (`POST /portfolio/demo`) when it is empty, which the `book`
questions need. Memory and recall are switched off on it, so no question
leaks into the next.

`--model` is `free` (the keyless chain every reader gets: what to measure
first) or `provider:model`, the key read from <PROVIDER>_API_KEY and sent
per request as the drawer sends a held key (`X-Chat-Key`), never stored.
OpenRouter reaches most models with one key:
`--model openrouter:deepseek/deepseek-v4.1-flash`. Repeat it to compare.

Each run is checked without a model (figures against the app's own API,
the page button, required and forbidden words) and, with `--judge SPEC`, by a
model against the question's goals (`agent_judge`): use a strong one, the
judge's key comes from the same env. Prod limits apply: 20 turns per 5
minutes per account (`--pace`, 16 s default, stays under it) and the free
chain's allowance: 5 messages on the account's first day (trial), 30 a day
after; once spent the free model is skipped. So a full free pass takes a
couple of days on one account, or narrow it with --area / --case; BYOK
models have no allowance.

The free chain runs on the operator's keys — the same Gemini / Groq /
OpenRouter quotas every reader's free turn draws from, and an agent turn is a
dozen model calls, not one. A full free pass on 2026-10-29 spent the day's
Gemini quota and left readers' Home briefing "sin IA". So `free` asks at most
`--free-max` questions a run (8 by default); a bigger pass is a choice made
out loud, and a BYOK model (`provider:model`) is the way to run the catalog.

`--save` writes evals/prod/runs/<stamp>.json (every answer, check and
judgment) and a .md report beside it: area x model with ok / fail / halluc,
then every failure with its question and answer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from stocks import session
from stocks.chat import agent_judge, prod_eval
from stocks.web import llm, upstream

RUNS = prod_eval.CATALOG.parent / "runs"
DEFAULT_EMAIL = "ai-eval@topstocks.eval"
# The free chain's walls (`engine.FREE_CAP_ERRORS`, all backends down): no
# point asking it the rest today.
FREE_DONE = {
    "chat.free_cap",
    "chat.free_cap_trial",
    "chat.free_cap_global",
    "chat.free_ineligible",
    "chat.free_exhausted",
}
# Questions a run asks of the free chain: its keys are the readers' (see above).
FREE_MAX = 8


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--model",
        action="append",
        default=[],
        help="free | provider:model (repeatable; default free)",
    )
    ap.add_argument(
        "--area",
        action="append",
        default=[],
        help="only these areas; a page name takes its tabs too",
    )
    ap.add_argument("--case", action="append", default=[], help="only these ids")
    ap.add_argument("--kind", action="append", default=[], help="only these kinds")
    ap.add_argument(
        "--judge",
        default="",
        help="provider:model that judges the goals (off when empty)",
    )
    ap.add_argument("--base", default=upstream.PROD_URL)
    ap.add_argument("--email", default=DEFAULT_EMAIL)
    ap.add_argument("--seed", action="store_true", help="demo book if empty")
    ap.add_argument(
        "--pace",
        type=float,
        default=16.0,
        help="seconds between turns (prod: 20 per 5 min)",
    )
    ap.add_argument(
        "--free-max",
        type=int,
        default=FREE_MAX,
        help="questions asked of the free chain per run (it spends readers' quota)",
    )
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--keep", action="store_true", help="keep the threads")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--recheck",
        default="",
        help="saved run .json: re-score its answers with today's rules, no model",
    )
    return ap.parse_args()


def _chosen(args: argparse.Namespace) -> list[prod_eval.Question]:
    qs = prod_eval.load()
    if args.case:
        qs = [q for q in qs if q.id in args.case]
    if args.area:
        qs = [q for q in qs if q.area in args.area or q.page in args.area]
    if args.kind:
        qs = [q for q in qs if q.kind in args.kind]
    return qs


def _key(provider: str) -> str:
    return os.environ.get(f"{provider.upper()}_API_KEY", "")


class Prod:
    """The deployed API as the throwaway account."""

    def __init__(self, base: str, email: str, timeout: float) -> None:
        cookie = session.mint({"email": email, "email_verified": True})
        if not cookie:
            sys.exit("no [auth] cookie_secret here: cannot sign in to prod")
        self.http = httpx.Client(
            base_url=base.rstrip("/") + "/api/v1",
            cookies={session.COOKIE: cookie, "ts_app": "1"},
            timeout=httpx.Timeout(timeout, connect=20.0),
        )

    def json(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, path, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    def reference(self, q: prod_eval.Question, cache: dict) -> tuple[dict, dict]:
        """The question's truths by label, and every read that sources it."""
        for path in prod_eval.reference_paths(q):
            if path not in cache:
                try:
                    cache[path] = self.json("GET", path)
                except httpx.HTTPError as exc:
                    cache[path] = {"_error": str(exc)}
        truth = {t.label: prod_eval.pick(cache[t.get], t.pick) for t in q.truth}
        refs = {p: cache[p] for p in prod_eval.reference_paths(q)}
        return truth, refs

    def ask(self, q: prod_eval.Question, headers: dict, keep: bool) -> prod_eval.Answer:
        # A network blip fails this question, not the run (2026-10-29: a read
        # timeout opening a thread killed 79 answers before anything was saved).
        try:
            thread = self.json(
                "POST", "/chat/conversations", json={"title": f"eval {q.id}"}
            )["id"]
        except httpx.HTTPError as exc:
            return prod_eval.Answer(error=f"{type(exc).__name__}: {exc}")
        try:
            for attempt in range(2):
                t0 = time.monotonic()
                with self.http.stream(
                    "POST",
                    "/chat/runs",
                    headers=headers,
                    json=prod_eval.run_body(q, thread),
                ) as r:
                    if r.status_code == 429 and attempt == 0:
                        wait = int(r.headers.get("Retry-After") or 60)
                        print(f"    429, waiting {wait}s", flush=True)
                        time.sleep(wait)
                        continue
                    if r.status_code >= 400:
                        r.read()
                        return prod_eval.Answer(
                            error=f"http {r.status_code}: {r.text[:200]}"
                        )
                    return prod_eval.read_run(
                        prod_eval.frames(r.iter_lines()), started=t0
                    )
            return prod_eval.Answer(error="rate limited")
        except httpx.HTTPError as exc:
            return prod_eval.Answer(error=f"{type(exc).__name__}: {exc}")
        finally:
            if not keep:
                try:
                    self.http.delete(f"/chat/conversations/{thread}")
                except httpx.HTTPError:
                    pass


def _judge(spec: prod_eval.Model | None, q, ans, truth, refs) -> dict | None:
    if spec is None or not ans.text.strip():
        return None
    provider = llm.PROVIDERS[spec.provider]
    try:
        j = agent_judge.judge(
            provider,
            _key(spec.provider),
            q.all_goals,
            q.message,
            prod_eval.material(ans, truth, refs),
            ans.text,
            model=spec.model,
        )
    except Exception as exc:  # noqa: BLE001 - a judge that fails is reported, not fatal
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"rubric": j.rubric, "goals": j.goals, "scores": j.scores, "why": j.why}


def _report(rows: list[dict], meta: dict) -> str:
    grid = prod_eval.matrix(rows)
    models = sorted({r["model"] for r in rows})
    out = [
        f"# Prod assistant eval {meta['stamp']}",
        "",
        f"Base {meta['base']} · commit {meta.get('commit') or '?'} · "
        f"judge {meta.get('judge') or 'off'}",
        "",
        "| area | " + " | ".join(models) + " |",
        "|---|" + "---|" * len(models),
    ]
    for area in sorted(grid):
        cells = []
        for m in models:
            c = grid[area].get(m)
            cells.append(
                "" if not c else f"{c['ok']} ok · {c['fail']} fail · {c['halluc']} halluc"
            )
        out.append(f"| {area} | " + " | ".join(cells) + " |")
    out += ["", "## Per model", ""]
    for m in models:
        mine = [r for r in rows if r["model"] == m]
        secs = sorted(r["answer"]["seconds"] for r in mine)
        scores = {}
        for s in agent_judge.SCORES:
            got = [
                v
                for r in mine
                if (v := ((r.get("judged") or {}).get("scores") or {}).get(s.id))
            ]
            scores[s.id] = round(sum(got) / len(got), 2) if got else None
        counts = {
            v: sum(prod_eval.verdict(r) == v for r in mine)
            for v in ("ok", "fail", "halluc")
        }
        out.append(
            f"- **{m}**: {counts['ok']}/{len(mine)} ok, {counts['halluc']} halluc · "
            f"median {secs[len(secs) // 2] if secs else 0:.0f}s · scores {scores}"
        )
    out += ["", "## Not ok", ""]
    for r in rows:
        v = prod_eval.verdict(r)
        if v == "ok":
            continue
        j = r.get("judged") or {}
        missed = [g for g, x in (j.get("goals") or {}).items() if x != "met"]
        a = r["answer"]
        out += [
            f"### {r['id']} · {r['model']} · {v}",
            "",
            f"> {r['message']}",
            "",
            f"- answered by: {a['model'] or a['provider']} "
            f"in {a['seconds']}s, tools {[c['name'] for c in a['calls']]}",
            f"- rules: {r['checks']['failed'] or 'ok'}",
            f"- unsourced figures: {r['checks'].get('unsourced') or '-'}",
            f"- goals missed: {missed or '-'}",
            f"- scores: {j.get('scores') or '-'}",
            "",
            "```",
            (r["answer"]["text"] or r["answer"]["error"])[:1500],
            "```",
            "",
        ]
    return "\n".join(out)


def _pool(refs: dict) -> list[float]:
    return [n for data in refs.values() for n in prod_eval.harvest(data)]


def _recheck(args, path: Path, catalog: dict, refs: dict) -> int:
    """Re-score a saved run's answers against fresh references: new rules
    without spending a turn. Prices have moved since, so a figure near a
    tolerance edge may flip."""
    saved = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in saved["rows"]:
        q = catalog.get(row["id"])
        if q is None:
            continue
        truth, ref = refs[q.id]
        ans = prod_eval.Answer.from_dict(row["answer"])
        rows.append(
            {**row, "truth": truth, "checks": prod_eval.checks(q, ans, truth, _pool(ref))}
        )
        print(
            f"  {prod_eval.verdict(rows[-1]):6} {q.id:28} "
            f"{rows[-1]['checks']['failed'] or ''}"
        )
    meta = {**{k: v for k, v in saved.items() if k != "rows"}, "rechecked": True}
    report = _report(rows, meta)
    print("\n" + report)
    if args.save:
        out = path.with_name(path.stem + "-recheck.json")
        out.write_text(
            json.dumps({**meta, "rows": rows}, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
        out.with_suffix(".md").write_text(report, encoding="utf-8")
    return 0


def main() -> int:
    args = _args()
    qs = _chosen(args)
    models = [prod_eval.Model.parse(m) for m in (args.model or ["free"])]
    judge = prod_eval.Model.parse(args.judge) if args.judge else None
    for m in [*models, *([judge] if judge else [])]:
        if m.provider not in llm.PROVIDERS:
            sys.exit(f"unknown provider {m.provider!r}")
        if m.provider != "free" and not _key(m.provider):
            sys.exit(f"{m.provider.upper()}_API_KEY is not set")

    print(f"{len(qs)} questions x {len(models)} models on {args.base}")
    if any(m.provider == "free" for m in models) and len(qs) > args.free_max:
        print(
            f"free: only the first {args.free_max} of {len(qs)} questions — the free "
            "chain spends the readers' quota (--free-max, or a BYOK --model)"
        )
    if args.dry_run:
        for q in qs:
            extra = [f"truth:{len(q.truth)}"] if q.truth else []
            extra += [f"opens:{q.opens}"] if q.opens else []
            print(f"  {q.area:22} {q.kind:8} {q.id:28} {' '.join(extra)}")
        return 0

    if args.recheck:
        ids = {r["id"] for r in json.loads(Path(args.recheck).read_text())["rows"]}
        qs = [q for q in qs if q.id in ids]
    prod = Prod(args.base, args.email, args.timeout)
    me = prod.json("GET", "/me")
    print(f"signed in as {me.get('email') or args.email}")
    cache: dict = {}
    refs = {q.id: prod.reference(q, cache) for q in qs}
    if args.recheck:
        return _recheck(args, Path(args.recheck), {q.id: q for q in qs}, refs)
    prod.json("PATCH", "/chat/settings", json={"memory": False, "recall": False})
    if args.seed:
        held = prod.json("GET", "/portfolio/positions").get("positions") or []
        if not held:
            print("seeding the demo book:", prod.json("POST", "/portfolio/demo"))

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S")
    meta = {
        "stamp": stamp,
        "base": args.base,
        "commit": upstream.prod_commit(args.base),
        "judge": judge.label if judge else "",
        "models": [m.label for m in models],
    }
    rows: list[dict] = []

    def save() -> None:
        # After every answer, so a run that dies keeps what it paid for.
        if not args.save:
            return
        RUNS.mkdir(parents=True, exist_ok=True)
        (RUNS / f"{stamp}.json").write_text(
            json.dumps({**meta, "rows": rows}, ensure_ascii=False, indent=1, default=str)
        )

    for model in models:
        headers = (
            {}
            if model.provider == "free"
            else {"X-Chat-Provider": model.provider, "X-Chat-Key": _key(model.provider)}
        )
        patch = {
            "provider": model.provider,
            **({"model": model.model} if model.model else {}),
        }
        prod.json("PATCH", "/chat/settings", json=patch, headers=headers)
        print(f"\n== {model.label}")
        for i, q in enumerate(qs):
            if i:
                time.sleep(args.pace)
            truth, ref = refs[q.id]
            ans = prod.ask(q, headers, args.keep)
            if model.provider != "free" and ans.provider not in ("", model.provider):
                # Our key failed before its first word and the chain moved on:
                # whatever came back is not this model's answer.
                ans.error = f"{model.provider} failed, fell back to {ans.provider}"
                ans.text = ""
            elif model.model and ans.model not in ("", model.model):
                # A saturated model hands the turn to a sibling on the same
                # key (engine._busy_siblings): busy, not this model's answer.
                ans.error = f"{model.model} busy, answered by {ans.model}"
                ans.text = ""
            elif model.provider != "free" and ans.error in FREE_DONE:
                ans.error = f"{model.provider} failed, free fallback capped"
            row = {
                "id": q.id,
                "area": q.area,
                "kind": q.kind,
                "message": q.message,
                "model": model.label,
                "truth": truth,
                "answer": ans.as_dict(),
                "checks": prod_eval.checks(q, ans, truth, _pool(ref)),
            }
            row["judged"] = _judge(judge, q, ans, truth, ref)
            rows.append(row)
            save()
            print(
                f"  {prod_eval.verdict(row):6} {q.id:28} {ans.seconds:5.0f}s "
                f"{ans.model or ans.provider or '-':30} {row['checks']['failed'] or ''}",
                flush=True,
            )
            if ans.error in FREE_DONE:
                print("  free allowance spent for today: skipping the rest of this model")
                break
            if model.provider == "free" and i + 1 >= args.free_max:
                break

    report = _report(rows, meta)
    print("\n" + report.split("\n## Not ok")[0])
    if args.save:
        save()
        (RUNS / f"{stamp}.md").write_text(report)
        print(f"saved {RUNS / stamp}.json and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
