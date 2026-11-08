"""A fund set against the book that would hold it: what it repeats, what it adds.

A world ETF bought beside Apple, Microsoft and Nvidia is not the
diversification it reads as on its own page: its top ten are mostly the
same names, and its biggest sector is the one the book is already heaviest
in. The page answers that with two reads off figures it already has —
the fund's disclosed top holdings matched to the book's positions, and the
book's sector split beside the fund's (and, for a fund already held, the
book's split without it).

Matching is by symbol first and then by the company's name, because a fund
files Taiwan Semiconductor as 2330.TW and the reader holds TSM: the name's
first two meaningful words are compared, which tells "Taiwan Semiconductor"
apart from "Taiwan Cement" and still finds Alibaba under its holding
company's longer name.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Words a company's legal name carries that say nothing about which company
# it is.
_FILLER = frozenset(
    "the co corp corporation inc incorporated ltd limited plc sa nv ag se spa "
    "company companies class holding holdings group adr ads cl ord shs new "
    "a b c".split()
)


def name_key(name: str | None) -> str:
    """The first two meaningful words of a company name, lower case."""
    words = [w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if w]
    return " ".join([w for w in words if w not in _FILLER][:2])


def _root(symbol: str) -> str:
    code = (symbol or "").strip().upper()
    return code[: code.rfind(".")] if "." in code else code


@dataclass(frozen=True)
class Held:
    label: str  # the ledger's name for the position
    symbol: str  # the Yahoo symbol it resolves to
    name: str
    weight: float  # fraction of the book


@dataclass(frozen=True)
class Overlap:
    symbol: str  # the fund's own symbol for the holding
    name: str
    fund_weight: float
    held: Held


def overlap(
    holdings: Sequence[tuple[str, str, float]], book: Sequence[Held]
) -> list[Overlap]:
    """The fund's `(symbol, name, weight)` holdings the book also holds directly."""
    by_symbol: dict[str, Held] = {}
    by_name: dict[str, Held] = {}
    for held in book:
        for code in (held.symbol, held.label):
            if code:
                by_symbol.setdefault(code.strip().upper(), held)
                by_symbol.setdefault(_root(code), held)
        if key := name_key(held.name):
            by_name.setdefault(key, held)
    out: list[Overlap] = []
    for symbol, name, weight in holdings:
        code = (symbol or "").strip().upper()
        held = (
            by_symbol.get(code)
            or (by_symbol.get(_root(code)) if code else None)
            or by_name.get(name_key(name))
        )
        if held is not None and not any(o.held is held for o in out):
            out.append(Overlap(symbol=symbol, name=name, fund_weight=weight, held=held))
    return out


@dataclass(frozen=True)
class SectorRow:
    label: str
    book: float
    fund: float
    without: float | None  # the book's share with the fund taken out


def sectors(
    book: Mapping[str, float],
    fund: Mapping[str, float],
    fund_share: float | None,
    limit: int = 8,
) -> list[SectorRow]:
    """The book's sector split beside the fund's, heaviest first.

    `book` is the book's split with funds already looked through, so a held
    fund's sectors are inside it; `fund_share` (its weight in the book) takes
    them back out for the `without` column. "Unknown" is left out: it is a
    gap in the data, not a sector to weigh.
    """
    share = fund_share if fund_share and 0 < fund_share < 1 else None
    labels = {k for k in (*book, *fund) if k and k != "Unknown"}
    rows = []
    for label in labels:
        b, f = float(book.get(label, 0.0)), float(fund.get(label, 0.0))
        without = None
        if share is not None:
            without = max(0.0, (b - share * f) / (1 - share))
        rows.append(SectorRow(label=label, book=b, fund=f, without=without))
    rows.sort(key=lambda r: -(r.book + r.fund))
    return rows[:limit]
