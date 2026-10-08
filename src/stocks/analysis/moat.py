"""Quantitative moat proxies from filed statement history [derived].

A durable competitive advantage leaves numeric traces: returns on capital
that stay above the cost of capital, operating margins that hold under
attack, growth that persists, profits that convert to cash, a share count
that does not bloat. This module scores those traces 0-100 from
the same yfinance statements the KPI block uses, so tests run offline.

What it cannot see: brand, network effects, switching costs, regulation —
the *causes* of a moat. Treat the score as a screen that asks "do the
numbers look like a moat exists?", never as the qualitative verdict itself.

Two choices keep it from rewarding the wrong things. Margins are judged on
how *steady* they are against their own size, not on their level: a gross
margin of 60% is software's normal and a retailer's impossibility, so a level
scale reads sector, not moat — Costco's thin, unshakeable margin is the
evidence. And buybacks earn nothing past a flat share count: shrinking it
with borrowed money is capital allocation, not an advantage; only dilution,
which can hide a weak business, costs points.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from stocks.data.fundamentals import RawFundamentals

# Pillar weights — returns on capital dominate (the moat's bottom line),
# margin durability second (pricing power), cash and growth after; the share
# count is a small penalty, since it says more about management than moat.
PILLAR_WEIGHTS: dict[str, float] = {
    "roic": 0.35,
    "op_margin": 0.25,
    "growth": 0.15,
    "fcf": 0.20,
    "dilution": 0.05,
}

# Composite bands: >=70 wide, >=45 narrow, below no moat.
WIDE_THRESHOLD = 70.0
NARROW_THRESHOLD = 45.0

# Fewer scored pillars than this and the composite is meaningless.
_MIN_PILLARS = 3

# ROIC above this clears any sane cost of capital.
_ROIC_HURDLE = 0.10

# Where each level scale tops out. Set where good stops and exceptional starts,
# so the great compounders do not all pin at 100 and read alike.
_ROIC_TOP = 0.35
_FCF_MARGIN_TOP = 0.30
_CAGR_TOP = 0.20

# Margin swings are measured against the margin's own size, floored here so a
# 1% margin wobbling by 1pp is not scored as wildly unstable — nor a thin one
# as perfectly steady because its absolute moves are tiny.
_MARGIN_FLOOR = 0.05
# A yearly σ this large relative to the margin, or a fall this large since
# the first year, scores nothing.
_MARGIN_SPREAD_MAX = 0.30
_MARGIN_FALL_MAX = 0.30
# Fewer years than this and a σ is two points and a ruler.
_MARGIN_MIN_YEARS = 3

# Share count growth a year that scores nothing; flat or shrinking scores 100.
_DILUTION_MAX = 0.03


@dataclass(frozen=True)
class MoatPillar:
    key: str
    label: str
    score: float | None  # 0-100, None when the inputs are missing
    detail: str  # what the score was computed from, for tooltips/reports
    # The same detail as data, for a client that words it in its own language:
    # `kind` names the template ("roic", "margin_snapshot", "missing"…) and
    # `facts` fills it — fractions as fractions, counts as ints.
    kind: str = "missing"
    facts: dict[str, float | int] = field(default_factory=dict)


@dataclass(frozen=True)
class MoatScore:
    ticker: str
    pillars: tuple[MoatPillar, ...]
    score: float | None  # weighted composite 0-100, None when < _MIN_PILLARS
    rating: str | None  # "wide" | "narrow" | "no moat" | None
    years: int  # annual statement years backing the score


def _row(df: pd.DataFrame, label: str) -> pd.Series | None:
    """Numeric annual series for one statement row, or None when absent."""
    if df is None or df.empty or label not in df.index:
        return None
    row = pd.to_numeric(df.loc[label], errors="coerce").dropna()
    return row if not row.empty else None


def _scale(value: float, lo: float, hi: float) -> float:
    """Linear map of value onto 0-100 between lo and hi, clamped."""
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))


def _series_cagr(series: pd.Series) -> float | None:
    """CAGR oldest->newest across annual columns; None when undefined."""
    if len(series) < 2:
        return None
    seq = series.sort_index()
    oldest, newest = float(seq.iloc[0]), float(seq.iloc[-1])
    if oldest <= 0 or newest <= 0:
        return None
    return (newest / oldest) ** (1 / (len(seq) - 1)) - 1


def _roic_pillar(raw: RawFundamentals) -> MoatPillar:
    """Level + persistence of ROIC: 60% median level (5%..35% -> 0..100),
    40% share of years clearing the 10% hurdle."""
    ebit = _row(raw.income, "EBIT")
    tax = _row(raw.income, "Tax Rate For Calcs")
    invested = _row(raw.balance, "Invested Capital")
    if ebit is None or tax is None or invested is None:
        return MoatPillar(
            "roic", "ROIC", None, "EBIT / tax rate / invested capital rows missing"
        )
    roic = (ebit * (1 - tax) / invested[invested > 0]).dropna()
    if roic.empty:
        return MoatPillar("roic", "ROIC", None, "no overlapping statement years")
    median = float(roic.median())
    above = int((roic >= _ROIC_HURDLE).sum())
    score = 0.6 * _scale(median, 0.05, _ROIC_TOP) + 0.4 * (above / len(roic)) * 100
    detail = f"median ROIC {median:.0%}, ≥10% in {above}/{len(roic)} years"
    facts = {"roic": median, "above": above, "years": len(roic)}
    return MoatPillar("roic", "ROIC", score, detail, "roic", facts)


def _margin_pillar(raw: RawFundamentals) -> MoatPillar:
    """Operating-margin durability, whatever its level: 70% how little it
    swings (yearly σ over the margin's own size, floored at _MARGIN_FLOOR),
    30% how little it has fallen since the first year on the same measure.
    A median loss scores 0 — losing money steadily is not pricing power."""
    label = "Margin stability"
    rev = _row(raw.income, "Total Revenue")
    op = _row(raw.income, "Operating Income")
    if op is None:
        op = _row(raw.income, "EBIT")
    if rev is None or op is None:
        return MoatPillar(
            "op_margin", label, None, "operating income or revenue rows missing"
        )
    margin = (op / rev[rev > 0]).dropna().sort_index()
    if len(margin) < _MARGIN_MIN_YEARS:
        return MoatPillar(
            "op_margin", label, None, f"needs ≥{_MARGIN_MIN_YEARS} margin years"
        )
    median = float(margin.median())
    std = float(margin.std())
    change = float(margin.iloc[-1] - margin.iloc[0])
    facts = {"margin": median, "sd": std, "change": change, "years": len(margin)}
    if median <= 0:
        detail = f"median operating margin {median:.0%} over {len(margin)} years"
        return MoatPillar("op_margin", label, 0.0, detail, "op_margin_loss", facts)
    size = max(abs(median), _MARGIN_FLOOR)
    steady = _scale(-std / size, -_MARGIN_SPREAD_MAX, 0.0)
    held = _scale(min(0.0, change) / size, -_MARGIN_FALL_MAX, 0.0)
    detail = (
        f"median operating margin {median:.0%}, σ {std * 100:.1f}pp, "
        f"{change * 100:+.1f}pp over {len(margin)} years"
    )
    return MoatPillar(
        "op_margin", label, 0.7 * steady + 0.3 * held, detail, "op_margin", facts
    )


def _growth_pillar(raw: RawFundamentals) -> MoatPillar:
    """Revenue durability: 50% CAGR level (0%..20% -> 0..100), 50% share of
    up years — steady single-digit growth outscores one lucky spike."""
    rev = _row(raw.income, "Total Revenue")
    if rev is None or len(rev) < 2:
        return MoatPillar("growth", "Growth", None, "needs ≥2 revenue years")
    changes = rev.sort_index().pct_change().dropna()
    up = float((changes > 0).mean())
    ups = int((changes > 0).sum())
    growth = _series_cagr(rev)
    if growth is None:
        score = up * 100
        detail = f"revenue up in {ups}/{len(changes)} years (CAGR undefined)"
        facts: dict[str, float | int] = {"up": ups, "years": len(changes)}
        return MoatPillar("growth", "Growth", score, detail, "growth_no_cagr", facts)
    score = 0.5 * _scale(growth, 0.0, _CAGR_TOP) + 0.5 * up * 100
    detail = f"revenue CAGR {growth:.0%}, up in {ups}/{len(changes)} years"
    facts = {"cagr": growth, "up": ups, "years": len(changes)}
    return MoatPillar("growth", "Growth", score, detail, "growth", facts)


def _fcf_pillar(raw: RawFundamentals) -> MoatPillar:
    """Cash generation: 60% median FCF margin (0%..30% -> 0..100), 40% share
    of FCF-positive years."""
    fcf = _row(raw.cashflow, "Free Cash Flow")
    rev = _row(raw.income, "Total Revenue")
    if fcf is None or rev is None:
        return MoatPillar("fcf", "FCF", None, "free cash flow or revenue rows missing")
    margin = (fcf / rev[rev > 0]).dropna()
    if margin.empty:
        return MoatPillar("fcf", "FCF", None, "no overlapping statement years")
    median = float(margin.median())
    positive = float((margin > 0).mean())
    positives = int((margin > 0).sum())
    score = 0.6 * _scale(median, 0.0, _FCF_MARGIN_TOP) + 0.4 * positive * 100
    detail = (
        f"median FCF margin {median:.0%}, positive in {positives}/{len(margin)} years"
    )
    facts = {"margin": median, "positive": positives, "years": len(margin)}
    return MoatPillar("fcf", "FCF", score, detail, "fcf", facts)


def _dilution_pillar(raw: RawFundamentals) -> MoatPillar:
    """Share-count discipline: flat or shrinking -> 100, +3%/y dilution -> 0.
    Buybacks earn nothing beyond flat — see the module docstring."""
    shares = _row(raw.income, "Diluted Average Shares")
    growth = _series_cagr(shares) if shares is not None else None
    if growth is None:
        return MoatPillar("dilution", "Dilution", None, "diluted share history missing")
    return MoatPillar(
        "dilution",
        "Dilution",
        _scale(-growth, -_DILUTION_MAX, 0.0),
        f"share count {growth:+.1%}/year",
        "dilution",
        {"shares": growth},
    )


def moat_rating(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= WIDE_THRESHOLD:
        return "wide"
    if score >= NARROW_THRESHOLD:
        return "narrow"
    return "no moat"


def moat_score(raw: RawFundamentals) -> MoatScore:
    """Score one ticker's moat evidence. Missing pillars are dropped and the
    rest reweighted; fewer than _MIN_PILLARS scored -> composite None."""
    pillars = (
        _roic_pillar(raw),
        _margin_pillar(raw),
        _growth_pillar(raw),
        _fcf_pillar(raw),
        _dilution_pillar(raw),
    )
    scored = [(p.score, PILLAR_WEIGHTS[p.key]) for p in pillars if p.score is not None]
    if len(scored) >= _MIN_PILLARS:
        total_weight = sum(w for _, w in scored)
        composite = sum(s * w for s, w in scored) / total_weight
    else:
        composite = None
    rev = _row(raw.income, "Total Revenue")
    return MoatScore(
        ticker=raw.ticker,
        pillars=pillars,
        score=composite,
        rating=moat_rating(composite),
        years=len(rev) if rev is not None else 0,
    )
