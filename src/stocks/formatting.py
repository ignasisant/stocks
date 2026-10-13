"""Shared value and display helpers (pure).

KPI-table formatting with explicit units stays in
stocks.analysis.fundamentals.format_value (driven by KPI_SOURCES); these are
the small generic helpers the rest of the tree kept reinventing.
"""

from __future__ import annotations

import math


def finite(value) -> float | None:
    """`value` as a finite float, or None for anything else — NaN, ±inf, pd.NA,
    text, missing.

    Both halves matter where the result is serialized: json.dumps writes NaN
    and Infinity as bare literals that strict parsers reject, so an LLM prompt
    or a cached payload must never carry one.
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def pct(x: float | None, signed: bool = False, na: str = "n/a") -> str:
    """Percent string for a fraction (0.15 -> '15.0%'); `na` when missing."""
    if x is None:
        return na
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def compact_money(v: float, symbol: str = "$") -> str:
    """Compact currency label, e.g. $394.3B / -$1.2M / $950."""
    a = abs(v)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{symbol}{v / div:.1f}{suffix}"
    return f"{symbol}{v:,.0f}"


def fmt_num(value: float, digits: int = 2, lang: str = "en", signed: bool = False) -> str:
    """`value` grouped and rounded in the reader's language.

    "1,234.50" in English, "1.234,50" in Spanish. Grouping is always on, even
    for four digits, so one app never mixes "9411" with "27.246". Text the LLM
    will quote goes through this, so the answer repeats numbers the way the
    screens print them.
    """
    text = f"{value:{'+' if signed else ''},.{digits}f}"
    if (lang or "en").split("-")[0].lower() == "es":
        text = text.translate({ord(","): ".", ord("."): ","})
    return text


def fmt_pct(
    fraction: float, digits: int = 1, lang: str = "en", signed: bool = False
) -> str:
    """A fraction as a percentage in the reader's language: 0.0129 -> "1,3%"."""
    return f"{fmt_num(fraction * 100, digits, lang, signed)}%"


def bound(lang: str):
    """`(num, pct)` formatters with `lang` already applied, for long f-strings."""
    return (
        lambda v, d=2, signed=False: fmt_num(v, d, lang, signed),
        lambda v, d=1, signed=False: fmt_pct(v, d, lang, signed),
    )
