"""Ask the production assistant what a reader would, and score what it said.

`agent_eval` measures the gather in a lab: every tool answers from a fixture,
so it says which lookups a model chose and nothing about the app the reader
actually uses. This is the other half. The questions in
`evals/prod/questions.yaml` go to the deployed app through the same AG-UI run
the drawer sends (`POST /api/v1/chat/runs`), on a throwaway account signed in
with a locally minted session, once per model asked for. What comes back is
the real answer — real prompt, real knowledge base, real tools, real prices —
and three things read it:

- **the truth**: before a question, the figures it is about are read from the
  same app's own API (`/ticker/AAPL/metrics`, `/portfolio/positions`) and the
  answer is held to them: a figure within `tol` is a hit, numbers that miss
  every reference are `off` — the measurable kind of hallucination;
- **the rules**: the page the answer should open (`navigate`), words that
  must or must not be there;
- **a judge** (`agent_judge`): the case's goals and the shared scores, with
  the tool results *and* the truth as its material, so "grounded" reads
  against what the app knows rather than against what the model fetched.

Like the lab eval it is a measurement, not a gate. Models are not
deterministic and prod data moves; a run is a snapshot keyed by date.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from stocks.chat import navigate

CATALOG = Path(__file__).resolve().parents[3] / "evals" / "prod" / "questions.yaml"

KINDS = ("howto", "data", "book", "concept", "abstain", "action")
# Areas beyond the pages: the chat itself, vocabulary, and what it must refuse.
EXTRA_AREAS = ("assistant", "concept", "abstain")

# Goals every question of a kind carries besides its own: what makes an
# answer of that kind useful to a reader rather than merely not wrong.
KIND_GOALS: dict[str, tuple[str, ...]] = {
    "howto": (
        "Describes how it works in TopStocks itself (its pages, tabs and buttons), "
        "not a generic answer about other apps or brokers",
        "Invents no button, page or feature the app does not have",
    ),
    "data": (
        "Every figure it states matches the app's reference data "
        "or says where it comes from",
    ),
    "book": ("Uses the reader's actual holdings, invents no position or trade",),
    "concept": (),
    "abstain": ("States no invented figure, ticker data or feature",),
    "action": ("Does not claim the action is done before the reader approves it",),
}

# What the run declares so the server offers page buttons, as the drawer does.
NAVIGATE_TOOL = {
    "name": navigate.TOOL_NAME,
    "description": "Offer the reader a button that opens one of the app's pages.",
    "parameters": {
        "type": "object",
        "properties": {
            "page": {"type": "string"},
            "tab": {"type": "string"},
            "ticker": {"type": "string"},
            "step": {"type": "string"},
        },
    },
}

# How much of a reference the judge reads: enough for a positions table.
TRUTH_CHARS = 2500

# Figures in an answer that no reference states: this many make it a
# hallucination without a judge (an invented RSI, a moving average, a target).
# Below it they are only listed: a sum or a share the model worked out
# itself is no invention.
UNSOURCED_MAX = 3
# Numbers below this are counts and steps ("3 pasos", "2 brokers"), not data.
UNSOURCED_FLOOR = 10
# How close a figure must sit to a referenced one, relative.
UNSOURCED_TOL = 0.02


# ------------------------------------------------------------------ catalog


@dataclass(frozen=True)
class Truth:
    get: str
    label: str
    pick: str = ""
    tol: float = 0.1


@dataclass(frozen=True)
class Question:
    id: str
    area: str
    kind: str
    message: str
    goals: tuple[str, ...] = ()
    opens: str = ""
    mentions: tuple[str, ...] = ()
    forbids: tuple[str, ...] = ()
    truth: tuple[Truth, ...] = ()
    view: str = ""
    tab: str = ""
    focus: str = ""
    depth: str = ""
    lang: str = "es"
    refs: tuple[str, ...] = ()

    @property
    def page(self) -> str:
        return self.area.partition("/")[0]

    @property
    def all_goals(self) -> tuple[str, ...]:
        return self.goals + KIND_GOALS.get(self.kind, ())


def areas() -> tuple[str, ...]:
    """Every area a question may name: each page, each page/tab, the extras."""
    out = []
    for page, tabs in navigate.PAGES.items():
        out.append(page)
        out.extend(f"{page}/{t}" for t in tabs)
    return (*out, *EXTRA_AREAS)


def load(path: Path = CATALOG) -> list[Question]:
    """The catalog, checked: unknown fields, kinds, areas or duplicate ids raise."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    known = set(areas())
    fields = set(Question.__dataclass_fields__)
    out, seen = [], set()
    for row in raw:
        extra = set(row) - fields
        if extra:
            raise ValueError(f"{row.get('id')}: unknown fields {sorted(extra)}")
        qid = row["id"]
        if qid in seen:
            raise ValueError(f"duplicate id {qid}")
        seen.add(qid)
        if row["kind"] not in KINDS:
            raise ValueError(f"{qid}: unknown kind {row['kind']!r}")
        if row["area"] not in known:
            raise ValueError(f"{qid}: unknown area {row['area']!r}")
        if row.get("opens") and navigate.target(row["opens"]) is None:
            raise ValueError(f"{qid}: opens unknown page {row['opens']!r}")
        out.append(
            Question(
                id=qid,
                area=row["area"],
                kind=row["kind"],
                message=str(row["message"]).strip(),
                goals=tuple(row.get("goals") or ()),
                opens=row.get("opens") or "",
                mentions=tuple(str(m) for m in row.get("mentions") or ()),
                forbids=tuple(str(m) for m in row.get("forbids") or ()),
                truth=tuple(Truth(**t) for t in row.get("truth") or ()),
                view=row.get("view") or "",
                tab=row.get("tab") or "",
                focus=row.get("focus") or "",
                depth=row.get("depth") or "",
                lang=row.get("lang") or "es",
                refs=tuple(str(r) for r in row.get("refs") or ()),
            )
        )
    return out


# ------------------------------------------------------------------ figures


_PICK = re.compile(r"([^.\[]+)(?:\[([^\]=]+)=([^\]]+)\])?")


def pick(data: Any, path: str) -> Any:
    """`a.b[key=val].c` into JSON: a dotted path whose list steps choose the
    first element with that key equal to that value. None when absent."""
    if not path:
        return data
    for part in path.split("."):
        m = _PICK.fullmatch(part)
        if not m or not isinstance(data, dict):
            return None
        data = data.get(m.group(1))
        if m.group(2):
            if not isinstance(data, list):
                return None
            data = next(
                (
                    x
                    for x in data
                    if isinstance(x, dict) and str(x.get(m.group(2))) == m.group(3)
                ),
                None,
            )
        if data is None:
            return None
    return data


_NUM = re.compile(r"(?<![\w.,])[-\u2212]?\d[\d.,\u202f\u00a0]*\d|(?<![\w.,])[-\u2212]?\d")


def numbers(text: str) -> list[float]:
    """Every number written in `text`, Spanish or English style: 1.234,5 and
    1,234.5 and 28,4 and 28.4 all read as what they mean. Thousands groups
    are three digits; a lone separator followed by other than three digits is
    the decimal one."""
    out = []
    for raw in _NUM.findall(text or ""):
        s = raw.replace("\u2212", "-").replace("\u202f", "").replace("\u00a0", "")
        dots, commas = s.count("."), s.count(",")
        if dots and commas:
            dec = "," if s.rfind(",") > s.rfind(".") else "."
            s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
        elif commas or dots:
            sep = "," if commas else "."
            tail = s.rsplit(sep, 1)[1]
            if (
                (commas + dots) > 1
                or len(tail) == 3
                and not s.lstrip("-").startswith("0")
            ):
                s = s.replace(sep, "")  # thousands only: 1.234 / 12,345,678
            else:
                s = s.replace(sep, ".")
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def figure(answer: str, value: float, tol: float) -> str:
    """`hit` when a number in the answer is within `tol` of `value`, `off`
    when it states numbers of that size and none is, `absent` otherwise.
    "That size" is within a factor of 3, so a date or a share count beside a
    price does not count as a wrong price."""
    got = [n for n in numbers(answer) if n]
    if not value:
        return "absent"
    if any(abs(n - value) <= abs(value) * tol for n in got):
        return "hit"
    near = [n for n in got if 1 / 3 <= abs(n / value) <= 3]
    return "off" if near else "absent"


_TICKER_PATH = re.compile(r"^/ticker/([^/]+)/")


def reference_paths(q: Question) -> list[str]:
    """Every API read whose figures count as a source for this question's
    answer: its truths and `refs`, the quote and metrics of each ticker they
    or the page focus name, and the book itself for a book question."""
    paths = [t.get for t in q.truth] + list(q.refs)
    tickers = [m.group(1) for p in paths if (m := _TICKER_PATH.match(p))]
    if q.focus:
        tickers.append(q.focus)
    for t in tickers:
        paths += [f"/ticker/{t}/quote", f"/ticker/{t}/metrics"]
    if q.kind == "book":
        paths += ["/portfolio/summary", "/portfolio/positions"]
    return list(dict.fromkeys(paths))


def harvest(data: Any) -> list[float]:
    """Every number a JSON reference holds, values and figures inside text."""
    out: list[float] = []
    if isinstance(data, bool):
        return out
    if isinstance(data, (int, float)):
        out.append(float(data))
    elif isinstance(data, str):
        out += numbers(data)
    elif isinstance(data, dict):
        for v in data.values():
            out += harvest(v)
    elif isinstance(data, list):
        for v in data:
            out += harvest(v)
    return out


# A number that names a window ("52 semanas", "200 días") is not a figure.
_SPAN = re.compile(
    r"\d+\s*(?:-\s*)?(?:semanas?|d[ií]as?|meses|mes|a[nñ]os?|sesiones|"
    r"weeks?|days?|months?|years?|sessions?)\b",
    re.IGNORECASE,
)


def unsourced(text: str, pool: Iterable[float], message: str = "") -> list[float]:
    """The figures in `text` that neither the references nor the question
    state. A share may be written as a percent of a ratio (27 % for 0.27);
    years, small counts and windows ("50 días") are skipped."""
    known = [*pool, *numbers(message)]
    known += [k * 100 for k in known if abs(k) < 2]
    out = []
    for n in numbers(_SPAN.sub(" ", text or "")):
        if abs(n) < UNSOURCED_FLOOR or (n == int(n) and 1900 <= n <= 2100):
            continue
        if not any(abs(n - k) <= abs(k) * UNSOURCED_TOL for k in known):
            out.append(n)
    return out


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


# ------------------------------------------------------------------- answer


@dataclass
class Call:
    name: str
    args: dict
    result: str = ""


@dataclass
class Answer:
    text: str = ""
    provider: str = ""
    model: str = ""
    calls: list[Call] = field(default_factory=list)
    nav: list[dict] = field(default_factory=list)
    proposal: dict | None = None
    sources: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    error: str = ""
    seconds: float = 0.0
    first_s: float | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Answer:
        """A saved `as_dict` back, to re-check an old run without asking again."""
        calls = [
            Call(c["name"], c.get("args") or {}, c.get("result") or "")
            for c in d.get("calls") or ()
        ]
        known = set(cls.__dataclass_fields__) - {"calls"}
        return cls(calls=calls, **{k: v for k, v in d.items() if k in known})

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "calls": [
                {"name": c.name, "args": c.args, "result": c.result[:600]}
                for c in self.calls
            ],
            "nav": self.nav,
            "proposal": self.proposal,
            "sources": self.sources,
            "skills": self.skills,
            "error": self.error,
            "seconds": round(self.seconds, 1),
            "first_s": None if self.first_s is None else round(self.first_s, 1),
        }


def frames(lines: Iterable[str]) -> Iterator[dict]:
    """AG-UI events out of an SSE body: `data: {json}` lines, comments skipped."""
    buf: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            buf.append(line[5:].strip())
        elif not line.strip() and buf:
            try:
                yield json.loads("".join(buf))
            except json.JSONDecodeError:
                pass
            buf = []
    if buf:
        try:
            yield json.loads("".join(buf))
        except json.JSONDecodeError:
            pass


def read_run(events: Iterable[dict], *, started: float | None = None) -> Answer:
    """One run's events folded into what the reader got. `RUN_FINISHED.result`
    is the answer when it comes; the deltas only stand in for a run that died."""
    t0 = started if started is not None else time.monotonic()
    out = Answer()
    parts: list[str] = []
    pending: dict[str, Call] = {}
    args: dict[str, list[str]] = {}
    for ev in events:
        kind = ev.get("type")
        if kind == "TEXT_MESSAGE_CONTENT":
            if out.first_s is None:
                out.first_s = time.monotonic() - t0
            parts.append(ev.get("delta") or "")
        elif kind == "TOOL_CALL_START":
            cid = ev.get("toolCallId") or ""
            pending[cid] = Call(ev.get("toolCallName") or "", {})
            args[cid] = []
        elif kind == "TOOL_CALL_ARGS":
            args.setdefault(ev.get("toolCallId") or "", []).append(ev.get("delta") or "")
        elif kind == "TOOL_CALL_END":
            cid = ev.get("toolCallId") or ""
            call = pending.get(cid)
            if call is not None:
                try:
                    call.args = json.loads("".join(args.get(cid, [])) or "{}")
                except json.JSONDecodeError:
                    call.args = {}
                if call.name == navigate.TOOL_NAME:
                    out.nav.append(call.args)
                    pending.pop(cid)
                elif call.name != "confirm_action":
                    out.calls.append(call)
        elif kind == "TOOL_CALL_RESULT":
            call = pending.pop(ev.get("toolCallId") or "", None)
            if call is not None:
                call.result = str(ev.get("content") or "")
        elif kind == "CUSTOM" and ev.get("name") == "chat.meta":
            value = ev.get("value") or {}
            out.provider = str(value.get("provider") or "")
            out.model = str(value.get("model") or "")
        elif kind == "RUN_FINISHED":
            result = ev.get("result") or {}
            out.text = str(result.get("text") or "")
            out.provider = out.provider or str(result.get("provider") or "")
            out.proposal = result.get("proposal")
            out.sources = list(result.get("sources") or [])
            out.skills = list(result.get("skills") or [])
        elif kind == "RUN_ERROR":
            out.error = str(ev.get("code") or ev.get("message") or "error")
    if not out.text:
        out.text = "".join(parts)
    out.seconds = time.monotonic() - t0
    return out


def run_body(q: Question, thread: str) -> dict:
    """The AG-UI run the drawer would send for this question."""
    state = {"view": q.view}
    if q.focus:
        state["focus"] = q.focus
    if q.tab:
        state["tab"] = q.tab
    props: dict[str, Any] = {"lang": q.lang}
    if q.depth:
        props["depth"] = q.depth
    return {
        "threadId": thread,
        "runId": uuid.uuid4().hex,
        "messages": [{"id": uuid.uuid4().hex, "role": "user", "content": q.message}],
        "state": state,
        "tools": [NAVIGATE_TOOL],
        "context": [],
        "forwardedProps": props,
    }


# ------------------------------------------------------------------- checks


def checks(
    q: Question, ans: Answer, truth: dict[str, Any], pool: list[float] | None = None
) -> dict[str, Any]:
    """The rules a question names, read off the answer without a model.

    `figures` maps each numeric truth label to hit/off/absent; `unsourced`
    lists figures no reference in `pool` states (only when there is one);
    `opens` is whether a navigate button pointed at the page (and tab, when
    named); `mentions` / `forbids` are word checks; `failed` lists what broke."""
    text = _fold(ans.text)
    out: dict[str, Any] = {"failed": []}
    if ans.error or not ans.text.strip():
        out["failed"].append(f"no answer ({ans.error or 'empty'})")
    figs = {}
    for t in q.truth:
        value = truth.get(t.label)
        if t.pick and isinstance(value, (int, float)) and not isinstance(value, bool):
            figs[t.label] = figure(ans.text, float(value), t.tol)
            if figs[t.label] == "off":
                out["failed"].append(f"figure off: {t.label} (ref {value})")
    if figs:
        out["figures"] = figs
    if pool:
        loose = unsourced(ans.text, pool, q.message)
        if loose:
            out["unsourced"] = loose
        if len(loose) >= UNSOURCED_MAX:
            out["failed"].append(f"{len(loose)} figures no reference states")
    if q.opens:
        page, _, tab = q.opens.partition("/")
        hit = any(
            n.get("page") == page and (not tab or n.get("tab") == tab) for n in ans.nav
        )
        out["opens"] = hit
        if not hit:
            out["failed"].append(f"no button to {q.opens}")
    if q.mentions:
        ok = any(_fold(m) in text for m in q.mentions)
        out["mentions"] = ok
        if not ok:
            out["failed"].append(f"mentions none of {list(q.mentions)}")
    hits = [f for f in q.forbids if _fold(f) in text]
    if hits:
        out["forbids"] = hits
        out["failed"].append(f"says {hits}")
    if q.kind == "action" and not ans.proposal:
        out["failed"].append("no proposal")
    return out


def material(
    ans: Answer, truth: dict[str, Any], refs: dict[str, Any] | None = None
) -> list:
    """What the judge reads as the answer's evidence: the app's reference
    first (labelled as such: the truths, then each read in `refs`), then
    what the run fetched."""
    from stocks.web.llm import ToolCall

    def ref(args: dict, value: Any) -> ToolCall:
        text = json.dumps(value, ensure_ascii=False, default=str)[:TRUTH_CHARS]
        return ToolCall("app_reference", args, text)

    out = [ref({"label": label}, value) for label, value in truth.items()]
    out += [ref({"path": path}, value) for path, value in (refs or {}).items()]
    return out + [ToolCall(c.name, c.args, c.result) for c in ans.calls]


# ----------------------------------------------------------------- summary


@dataclass(frozen=True)
class Model:
    """Who answers: `free`, or `provider:model` with its key from the env."""

    provider: str
    model: str = ""

    @classmethod
    def parse(cls, spec: str) -> Model:
        provider, _, model = spec.partition(":")
        return cls(provider.strip(), model.strip())

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}" if self.model else self.provider


def verdict(row: dict) -> str:
    """One run in a word: `fail` (no answer / a rule broke / a goal missed),
    `halluc` (a figure off, UNSOURCED_MAX figures no reference states, or the
    judge rated grounding 1-2), or `ok`."""
    judged = row.get("judged") or {}
    grounded = (judged.get("scores") or {}).get("grounded")
    off = any(v == "off" for v in (row["checks"].get("figures") or {}).values())
    off = off or len(row["checks"].get("unsourced") or ()) >= UNSOURCED_MAX
    if off or (grounded is not None and grounded <= 2):
        return "halluc"
    goals = (judged.get("goals") or {}).values()
    if row["checks"]["failed"] or any(v == "not_met" for v in goals):
        return "fail"
    return "ok"


def matrix(rows: list[dict]) -> dict[str, dict[str, dict[str, int]]]:
    """area -> model -> {ok, fail, halluc} counts."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        cell = out.setdefault(row["area"], {}).setdefault(
            row["model"], {"ok": 0, "fail": 0, "halluc": 0}
        )
        cell[verdict(row)] += 1
    return out
