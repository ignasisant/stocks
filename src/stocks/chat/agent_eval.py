"""Golden cases for the gather: what a question should make the model fetch.

The cases live in `evals/agent/cases.yaml`. Each names a message and what a
good gather does with it: the profile the router sends it to, the tools it
must call, the ones it must not, and how many calls are too many. Scoring is
a deterministic rubric over the calls the gather made, so a failure says
which rule broke. The answer is judged apart, by a model and only when asked
(`agent_judge`, `--judge`): against the case's `goals`.

Two runners share them. The test suite checks the routing offline (no model
involved: `profile_for` is a regex). `scripts/eval_agent.py` runs the real
gather on a real model with every tool answered from a fixture, so a run
costs model tokens and nothing else, and prints the cost per case. That one
is a measurement, not a CI gate: models drift and the free chain changes
model under us, so its result is read, not asserted.

A case is a regression (what the gather already does and must keep doing,
every time) or a capability (what it should learn to do; one pass in the
runs counts). Run each case k times and the two read differently: a
regression that passes 2 of 3 is flaky, a capability that passes 0 of 3 is
missing. A run can be saved and a later one compared with it, cost and
seconds included, so a prompt that passes more by spending twice the tokens
says so.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Generator, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from stocks import atomic
from stocks.chat import toolbox
from stocks.web.llm import ToolCall

CASES = Path(__file__).resolve().parents[3] / "evals" / "agent" / "cases.yaml"
RUNS = CASES.parent / "runs"

KINDS = ("regression", "capability")

# What a tool answers in a run when the case gives it nothing of its own:
# plausible, short, and the same every run.
DEFAULT_FIXTURES: dict[str, str] = {
    "search_web": ("[1] Shares fall after results\nhttps://example.com/news\n"
                   "The stock fell 6% after the company cut its full-year "
                   "guidance, citing weaker demand in China."),
    "read_page": ("Results release. Revenue 7.5bn (+12% y/y), gross margin "
                  "51.2%, full-year guidance lowered to 28-29bn."),
    "get_quotes": "NVDA 182.40 USD (+1.2% today)",
    "ticker_data": ("NVDA as the app's ticker page shows it.\n## overview\n"
                    "Price 182.40 USD; -12.0% from the high\n- P/E (TTM): "
                    "38.1x [fact] (expensive)\n- P/E (fwd): 27.4x [consensus]"
                    "\n## dcf\nValue 160.00 USD a share vs price 182.40\n"
                    "## analysts\nEPS consensus next FY: 6.65; revisions up "
                    "4 / down 1"),
    "technicals": ("NVDA trend (daily, 500 bars): above its 200-day average "
                   "(+14.2%, average rising) — uptrend\n12-1 momentum +38.5% · "
                   "6.1% below the 52-week high (high 194.20, low 86.60)\n"
                   "vs S&P 500 (return minus the index's): +9.8% over 6 "
                   "months, +21.4% over 12 months\ncontext: RSI14 58 · ATR14 "
                   "3.1% of price · 50-day avg 176.90 · 200-day avg 159.70"),
    "portfolio_snapshot": ("Value 98,400 EUR. Positions: NVDA 24% (+61%), "
                           "ASML 18% (-4%), MELI 12% (+22%), VWCE 30%, "
                           "cash 16%."),
    "trade_history": ("Recorded trades of NVDA (2), oldest first:\n"
                      "- 2024-03-11 buy 20 NVDA @ 88.40 USD, fee 1.00 USD\n"
                      "- 2025-06-02 buy 10 NVDA @ 136.10 USD, fee 1.00 USD\n"
                      "Open lots under FIFO (ES), in the order the next sale "
                      "takes them:\n"
                      "- NVDA bought 2024-03-11: 20 shares, cost 1,769.00 USD = "
                      "1,632.40 EUR (81.62 each, fee included)\n"
                      "- NVDA bought 2025-06-02: 10 shares, cost 1,362.00 USD = "
                      "1,196.80 EUR (119.68 each, fee included)"),
    "recall": "2026-10-02: you said you would trim NVDA above 25% weight.",
    "decisions": "2026-10-09 proposal: trim ASML 10% — state: shown.",
    "lookup_knowledge": ("[importing] DEGIRO: export Account statement as "
                         "CSV, then drop it on Import."),
    "simulate_sale": ("Selling 50 NVDA: proceeds 9,120 EUR, gain 3,480 EUR, "
                      "tax 731 EUR (19-21%)."),
    "harvest_losses": "ASML: unrealised loss 1,210 EUR, no repurchase in 2 months.",
    "rebalance": "To reach 20% NVDA: sell 8 shares (1,459 EUR).",
    "allocation": "Tech 46%, Consumer 12%, World ETF 30%, Cash 12%.",
    "propose_action": "Drafted: the change. The reader gets a card to approve it.",
}


@dataclass(frozen=True)
class Case:
    """One question and the rules a good gather for it keeps.

    `depth` is what the reader asked for ("" lets the router decide), and
    `profile` what the turn must end up on. `must` are each called at least
    once; one of `any_of`, when given, is called; none of `must_not` is.
    `max_calls` None leaves the count alone; 0 means fetch nothing. The
    tools in `fails` raise instead of answering, as a dead service would.
    `goals` are what the answer should show, for the judge (`agent_judge`).
    `brief` is an "Analyse with AI" angle (`chat/brief.py`): `message` is
    then the button's label, `ticker` the page it was pressed on, and the
    gather reads the brief the server appends to it."""

    id: str
    message: str
    kind: str = "regression"
    profile: str = "fast"
    depth: str = ""
    must: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    must_not: tuple[str, ...] = ()
    max_calls: int | None = None
    fixtures: dict[str, str] = field(default_factory=dict)
    fails: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    brief: str = ""
    ticker: str = ""

    def asked_depth(self) -> str:
        """The depth the turn asks for: a full brief asks for the deep
        gather, as `engine.prepare` does (`Brief.deep`)."""
        return self.depth or ("deep" if self.brief == "full" else "")

    def sent(self, ctx: toolbox.Context) -> str:
        """The message as the gather reads it: with the brief appended, as
        `engine.prepare` appends it. Built live (the profile, the calendar):
        the eval is a measurement, and the brief is what the model saw."""
        if not self.brief or ctx.watchlist is None or ctx.db is None:
            return self.message
        from stocks.chat import brief

        built = brief.build(self.brief, self.ticker, watchlist=ctx.watchlist,
                            db=ctx.db)
        return self.message + (built.text if built else "")


def load(path: Path = CASES) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out = []
    for item in raw:
        item = dict(item)
        for key in ("must", "any_of", "must_not", "fails", "goals"):
            item[key] = tuple(item.get(key) or ())
        item["fixtures"] = dict(item.get("fixtures") or {})
        out.append(Case(**item))
    return out


def score(case: Case, calls: list[ToolCall]) -> list[str]:
    """The rules `calls` broke, as sentences; empty is a pass."""
    used = [c.name for c in calls]
    out = [f"did not call {t}" for t in case.must if t not in used]
    if case.any_of and not set(case.any_of) & set(used):
        out.append(f"called none of {', '.join(case.any_of)}")
    out += [f"called {t}" for t in case.must_not if t in used]
    if case.max_calls is not None and len(used) > case.max_calls:
        out.append(f"{len(used)} calls, over {case.max_calls}")
    return out


@dataclass(frozen=True)
class Run:
    """One run of a case: the rules it broke (none is a pass), what it spent,
    the tools it called and the models that answered it (`Meter.models`) —
    on the free chain, not always the same one. The judge's spend is its
    own, so the gather's cost reads the same with and without `--judge`."""

    broke: tuple[str, ...] = ()
    tokens: int = 0
    usd: float | None = 0.0
    seconds: float = 0.0
    tools: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    judge_tokens: int = 0
    judge_usd: float | None = 0.0

    @property
    def passed(self) -> bool:
        return not self.broke


@dataclass(frozen=True)
class Tally:
    """One case over its runs: how many passed, and what they spent.
    `usd` is None when any run was on an unpriced model. `detail` keeps each
    run as it went, so a saved run says which rule broke and on what model."""

    id: str
    kind: str
    runs: int
    passes: int
    tokens: int = 0
    usd: float | None = 0.0
    seconds: float = 0.0
    judge_tokens: int = 0
    judge_usd: float | None = 0.0
    detail: tuple[dict, ...] = ()

    @property
    def ok(self) -> bool:
        """A regression passes every run (pass^k), a capability one (pass@k)."""
        if self.kind == "capability":
            return self.passes > 0
        return self.passes == self.runs

    @property
    def mark(self) -> str:
        if self.passes == self.runs:
            return "pass"
        if self.passes == 0:
            return "FAIL"
        return "flaky"


def _sum(costs: list[float | None]) -> float | None:
    if None in costs:
        return None
    return round(sum(c for c in costs if c is not None), 6)


def tally(case: Case, runs: Iterable[Run]) -> Tally:
    runs = list(runs)
    return Tally(case.id, case.kind, len(runs), sum(r.passed for r in runs),
                 sum(r.tokens for r in runs), _sum([r.usd for r in runs]),
                 round(sum(r.seconds for r in runs), 1),
                 sum(r.judge_tokens for r in runs),
                 _sum([r.judge_usd for r in runs]),
                 tuple(asdict(r) for r in runs))


def verdict(cases: list[Case], tallies: list[Tally]) -> list[str]:
    """Why a strict run fails, empty when it passes: a case with no run
    (no model answered, or the cap stopped it) cannot be said to pass."""
    ran = {t.id for t in tallies}
    out = [f"{t.id}: {t.passes}/{t.runs}, {'flaky' if t.passes else 'missing'}"
           for t in tallies if not t.ok]
    missing = [c.id for c in cases if c.id not in ran]
    if missing:
        out.append(f"{len(missing)} cases have no run: {', '.join(missing)}")
    return out


def record(tallies: list[Tally], **meta: object) -> dict:
    """A run as JSON-ready data: what `compare` reads back."""
    return {**meta, "cases": {t.id: asdict(t) for t in tallies}}


def save(run: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(path, json.dumps(run, indent=1, sort_keys=True) + "\n")
    return path


def latest(provider: str, model: str, root: Path = RUNS) -> Path | None:
    """The newest saved run on the same provider and model."""
    found = []
    for path in root.glob("*.json"):
        with contextlib.suppress(ValueError, OSError):
            run = json.loads(path.read_text(encoding="utf-8"))
            if (run.get("provider"), run.get("model")) == (provider, model):
                found.append((run.get("at", ""), path))
    return max(found)[1] if found else None


# A per-case change in tokens smaller than this share is noise: free models
# word the same gather differently from one run to the next.
DRIFT = 0.25


def _rate(t: dict) -> float:
    return t["passes"] / t["runs"] if t["runs"] else 0.0


def _moved(was: float, now: float) -> bool:
    return bool(was) and abs(now - was) / was >= DRIFT


def compare(old: dict, new: dict) -> list[str]:
    """What changed from `old` to `new`, worst first: cases that pass less,
    then more, then spend more or less — tokens, seconds and dollars a run.
    Cases in only one run are named, and a different prompt is said first:
    the comparison across prompts is the point, but it should read as one."""
    head = []
    if old.get("prompt") and old.get("prompt") != new.get("prompt"):
        head.append(f"prompt {old['prompt']} -> {new.get('prompt') or '?'}")
    worse, better, spend = [], [], []
    before, after = old.get("cases", {}), new.get("cases", {})
    for cid, t in after.items():
        was = before.get(cid)
        if was is None:
            better.append(f"{cid}: new case, {t['passes']}/{t['runs']}")
            continue
        a, b = _rate(was), _rate(t)
        line = (f"{cid}: {was['passes']}/{was['runs']} -> "
                f"{t['passes']}/{t['runs']}")
        if b < a:
            worse.append(line)
        elif b > a:
            better.append(line)
        n_old, n_new = max(1, was["runs"]), max(1, t["runs"])
        per_old, per_new = was["tokens"] / n_old, t["tokens"] / n_new
        if _moved(per_old, per_new):
            spend.append(f"{cid}: {per_old:.0f} -> {per_new:.0f} tokens a run")
        s_old = was.get("seconds", 0) / n_old
        s_new = t.get("seconds", 0) / n_new
        if _moved(s_old, s_new):
            spend.append(f"{cid}: {s_old:.1f}s -> {s_new:.1f}s a run")
        if was.get("usd") is not None and t.get("usd") is not None:
            u_old, u_new = was["usd"] / n_old, t["usd"] / n_new
            if _moved(u_old, u_new):
                spend.append(f"{cid}: ${u_old:.4f} -> ${u_new:.4f} a run")
    gone = [f"{cid}: dropped" for cid in before if cid not in after]
    return (head + [f"worse  {x}" for x in worse]
            + [f"better {x}" for x in better]
            + [f"spend  {x}" for x in spend] + [f"gone   {x}" for x in gone])


@contextlib.contextmanager
def fixture_tools(case: Case) -> Generator[None]:
    """Every tool answers from the case's fixtures (or the defaults) for the
    block, or raises when the case `fails` it: no page is fetched and no
    ledger is read."""
    saved = dict(toolbox.TOOLS)
    canned = {**DEFAULT_FIXTURES, **case.fixtures}

    def dead(args: dict, ctx: toolbox.Context) -> str:
        raise ConnectionError("service unavailable")

    try:
        for name, (spec, _) in saved.items():
            text = canned.get(name, f"({name}: nothing found)")
            toolbox.TOOLS[name] = (spec, dead if name in case.fails else
                                   (lambda args, ctx, text=text: text))
        yield
    finally:
        toolbox.TOOLS.clear()
        toolbox.TOOLS.update(saved)


def context(root: Path) -> toolbox.Context:
    """A Context whose files exist, so every tool is on offer (`specs` holds
    back the engines without a ledger and `decisions` without a journal)."""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("portfolio.db", "prefs.json", "journal.json"):
        (root / name).touch()
    return toolbox.Context(db=root / "portfolio.db",
                           prefs_path=root / "prefs.json",
                           journal=root / "journal.json",
                           watchlist=root / "watchlist.yaml", proposes=True)
