"""The reader's entry criteria: what a company has to meet before they buy it
or add to it.

Exit rules (`chat.journal`, kill criteria) are written per holding and say
when to let one go. Entry criteria are the other side, and come two ways:

  - **The checklist** (here): lines every buy or add is held to, whatever the
    name — "growing at least 15 %", "a forward P/E under 30", "never over
    8 % of the book". They sit beside the investor plan, under their own
    key (`PREFS_KEY`), with a short note of principles in the reader's words
    ("no pre-revenue biotech"), which the assistant reads and nothing
    measures.
  - **A buy zone per name** (`chat.journal`, `BUY_RULES`): "buy NVDA under
    120", armed like an exit rule and met on the morning card.

The checklist only ever tells: Review keeps its own verdict and shows which
lines a buy or an add would break; the ticker page counts how many it meets.
A figure the feed did not give is "unknown", never a pass or a fail.

Pure: a row's metrics in (`analysis.review._shown`'s keys, fractions as
fractions), readings out. Nothing here fetches.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

PREFS_KEY = "entry_criteria"

# What a checklist line can read, and which way it passes. A `pct` line is
# written as a percent (15 for 15 %) and read against a fraction; an `x` line
# is a multiple, written and read as is.
#   revenue_growth_min  — revenue growth, the last year (else the long run);
#   op_margin_min       — operating income over revenue;
#   fcf_yield_min       — free cash flow over market value;
#   roic_min            — return on invested capital (goodwill aside when
#                         that reads higher, as Review does);
#   pe_fwd_max          — forward P/E; a loss (negative P/E) fails it;
#   net_debt_ebitda_max — net debt over EBITDA; net cash passes it;
#   dilution_max        — yearly growth of the share count;
#   dividend_yield_min  — the dividend over the price;
#   weight_max          — what the position already weighs in the book: an
#                         add is held to it, a name not held passes.
RULES: dict[str, tuple[str, str]] = {
    "revenue_growth_min": ("min", "pct"),
    "op_margin_min": ("min", "pct"),
    "fcf_yield_min": ("min", "pct"),
    "roic_min": ("min", "pct"),
    "pe_fwd_max": ("max", "x"),
    "net_debt_ebitda_max": ("max", "x"),
    "dilution_max": ("max", "pct"),
    "dividend_yield_min": ("min", "pct"),
    "weight_max": ("max", "pct"),
}
# The note is read by the assistant in every answer: a few lines, not an essay.
MAX_NOTE = 600
# The most lines a checklist keeps, one per measure.
MAX_RULES = len(RULES)
# A percent line beyond this is a typo (a 500 % margin); a multiple beyond
# MAX_MULTIPLE too.
_PCT_RANGE = (-100.0, 1000.0)
MAX_MULTIPLE = 500.0

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"


@dataclass(frozen=True)
class Rule:
    rule: str
    level: float  # as written: a percent for `pct` rules, a multiple for `x`


@dataclass(frozen=True)
class Checklist:
    rules: tuple[Rule, ...] = ()
    note: str = ""

    @property
    def empty(self) -> bool:
        return not self.rules and not self.note


@dataclass(frozen=True)
class Reading:
    """One line read on one company: the figure in the line's own unit
    (a percent or a multiple), None when the feed lacks it."""

    rule: str
    level: float
    value: float | None
    state: str  # PASS | FAIL | UNKNOWN
    # Which figure was read when a line can read two: "ex_goodwill" when ROIC
    # came from capital without goodwill, so a page beside the reported ROIC
    # can say why the two differ.
    basis: str | None = None

    def as_dict(self) -> dict:
        return {"rule": self.rule, "level": self.level, "value": self.value,
                "state": self.state, "basis": self.basis}


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str):
        value = value.replace(",", ".").strip().rstrip("%").strip()
    try:
        x = float(value)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def clean(rules: Iterable[Mapping] | None) -> tuple[Rule, ...]:
    """The lines worth keeping, the last one per measure winning, in the
    catalog's order: a known rule with a level in its range. A multiple is
    over zero (a P/E under 0 is no line); a percent may be zero or negative
    ("growing at all", "dilution under -1 %": buying back)."""
    out: dict[str, Rule] = {}
    for item in rules or ():
        if not isinstance(item, Mapping):
            continue
        rule = str(item.get("rule") or "").strip().lower()
        level = _finite(item.get("level"))
        if rule not in RULES or level is None:
            continue
        unit = RULES[rule][1]
        if unit == "x" and not 0 < level <= MAX_MULTIPLE:
            continue
        if unit == "pct" and not _PCT_RANGE[0] < level < _PCT_RANGE[1]:
            continue
        if rule == "weight_max" and not 0 < level <= 100:
            continue
        out[rule] = Rule(rule, round(level, 4))
    return tuple(out[r] for r in RULES if r in out)


def parse(raw) -> Checklist | None:
    """The stored checklist, or None when it draws no line and says nothing."""
    if not isinstance(raw, Mapping):
        return None
    note = str(raw.get("note") or "").strip()[:MAX_NOTE]
    out = Checklist(clean(raw.get("rules")), note)
    return None if out.empty else out


def load(prefs: Mapping | None) -> Checklist | None:
    return parse((prefs or {}).get(PREFS_KEY))


def stored(checklist: Checklist | None) -> dict | None:
    """The checklist as prefs keep it (and `PUT /plan/entry` takes it)."""
    if checklist is None or checklist.empty:
        return None
    return {"rules": [{"rule": r.rule, "level": r.level} for r in checklist.rules],
            "note": checklist.note}


def _figure(rule: str, metrics: Mapping, weight: float | None) -> float | None:
    """What `rule` reads on a company, as a fraction or a multiple."""
    m = metrics or {}
    if rule == "revenue_growth_min":
        recent = _finite(m.get("revenue_growth"))
        return recent if recent is not None else _finite(m.get("revenue_cagr"))
    if rule == "roic_min":
        seen = [v for v in (_finite(m.get("roic")), _finite(m.get("roic_ex_goodwill")))
                if v is not None]
        return max(seen) if seen else None
    if rule == "weight_max":
        return weight if weight is not None else 0.0
    key = {
        "op_margin_min": "op_margin",
        "fcf_yield_min": "fcf_yield",
        "pe_fwd_max": "pe_fwd",
        "net_debt_ebitda_max": "net_debt_ebitda",
        "dilution_max": "share_dilution",
        "dividend_yield_min": "dividend_yield",
    }.get(rule)
    if key is None:
        return None
    value = _finite(m.get(key))
    if rule == "dividend_yield_min" and value is None:
        # No dividend on file is no dividend, once the feed answered at all.
        return 0.0 if any(_finite(v) is not None for v in m.values()) else None
    return value


def _basis(rule: str, metrics: Mapping) -> str | None:
    """`ex_goodwill` when `_figure` took ROIC without goodwill over the reported one."""
    if rule != "roic_min":
        return None
    m = metrics or {}
    reported = _finite(m.get("roic"))
    ex = _finite(m.get("roic_ex_goodwill"))
    if ex is not None and (reported is None or ex > reported):
        return "ex_goodwill"
    return None


def read(rule: Rule, metrics: Mapping, weight: float | None = None) -> Reading:
    side, unit = RULES[rule.rule]
    raw = _figure(rule.rule, metrics, weight)
    if raw is None:
        return Reading(rule.rule, rule.level, None, UNKNOWN)
    value = raw * 100 if unit == "pct" else raw
    basis = _basis(rule.rule, metrics)
    if rule.rule == "pe_fwd_max" and value <= 0:
        # A forward loss has no P/E to be under a line: it fails it.
        return Reading(rule.rule, rule.level, round(value, 2), FAIL)
    ok = value >= rule.level if side == "min" else value <= rule.level
    return Reading(rule.rule, rule.level, round(value, 2), PASS if ok else FAIL, basis)


def check(checklist: Checklist | None, metrics: Mapping | None,
          weight: float | None = None) -> list[Reading]:
    """Every line of the checklist on one company, in the catalog's order.
    `metrics` are a Review row's (`analysis.review._shown`), `weight` the
    position's share of the book as a fraction, None when not held."""
    if checklist is None or not checklist.rules:
        return []
    return [read(r, metrics or {}, weight) for r in checklist.rules]


def summary(readings: Iterable[Reading]) -> dict:
    """{met, failed, unknown, total}: what a chip prints."""
    rows = list(readings)
    return {
        "met": sum(r.state == PASS for r in rows),
        "failed": sum(r.state == FAIL for r in rows),
        "unknown": sum(r.state == UNKNOWN for r in rows),
        "total": len(rows),
    }


_WORDS = {
    "revenue_growth_min": "revenue growth at least {v}",
    "op_margin_min": "operating margin at least {v}",
    "fcf_yield_min": "free-cash-flow yield at least {v}",
    "roic_min": "ROIC at least {v}",
    "pe_fwd_max": "forward P/E at most {v}",
    "net_debt_ebitda_max": "net debt at most {v} EBITDA",
    "dilution_max": "share count growing at most {v} a year",
    "dividend_yield_min": "dividend yield at least {v}",
    "weight_max": "never adding past {v} of the book",
}


def rule_text(rule: Rule) -> str:
    """One line in English, as the assistant is told it."""
    unit = RULES[rule.rule][1]
    v = f"{rule.level:g}%" if unit == "pct" else f"{rule.level:g}x"
    return _WORDS[rule.rule].format(v=v)


def describe(checklist: Checklist | None) -> str:
    """The checklist as one sentence for the assistant, "" without one."""
    if checklist is None or checklist.empty:
        return ""
    parts = []
    if checklist.rules:
        parts.append(
            "Their entry criteria, which a buy or an add should meet: "
            + "; ".join(rule_text(r) for r in checklist.rules) + "."
        )
    if checklist.note:
        parts.append(f'Their buying principles, in their words: "{checklist.note}".')
    parts.append(
        "Before suggesting a buy or an add, check the name against them and "
        "say which it breaks; never drop a suggestion silently for it. "
    )
    return " ".join(parts)
