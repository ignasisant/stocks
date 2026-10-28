"""Big investors — who holds a company, and which way the money moved.

Funds managing over $100M file their US holdings each quarter (13F), up to 45
days after the quarter ends; Yahoo aggregates the filings into a company's top
institutional holders, each with its stake and how much it grew or shrank
over the quarter. That last figure is the "where is the money going" a reader
asks about: a holder adding a fifth to its stake is a vote, a holder halving
it is the opposite.

Two sources, in this order: the SEC's 13F data sets (`data.thirteenf`: shares,
dollars, and new / added / cut / sold-out per manager, built from the filings
into a local index) and Yahoo's aggregate for whatever the index lacks.

So the figures are a quarter old by construction, and every summary carries
the date they were reported as of — a card must never present them as this
week's flows. Percentages are kept as percent numbers (8.06, not 0.0806):
that is how a reader writes them and how the card's audit checks them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

# A stake that moved less than this over the quarter is "held", not a move.
MOVE_PCT = 2.0
TOP = 10


@dataclass(frozen=True)
class Holder:
    name: str
    pct_held: float | None
    change_pct: float | None
    # Only from the SEC's own 13F index (`data.thirteenf`): the position, in
    # shares and dollars, and what it did over the quarter: "new", "added",
    # "cut", "held" or "sold_out". Yahoo carries percentages alone.
    shares: int | None = None
    value: float | None = None
    status: str | None = None


@dataclass(frozen=True)
class Institutions:
    as_of: date | None
    institutions_pct: float | None
    insiders_pct: float | None
    holders: list[Holder] = field(default_factory=list)
    sold_out: list[Holder] = field(default_factory=list)
    source: str = "yahoo"

    @property
    def new(self) -> list[Holder]:
        return [h for h in self.holders if h.status == "new"]

    @property
    def adding(self) -> list[Holder]:
        return [h for h in self.holders
                if h.change_pct is not None and h.change_pct >= MOVE_PCT]

    @property
    def cutting(self) -> list[Holder]:
        return [h for h in self.holders
                if h.change_pct is not None and h.change_pct <= -MOVE_PCT]


def _pct(value) -> float | None:
    """A fraction from Yahoo as a percent, two decimals; None for a gap."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else round(number * 100, 2)


def _day(value) -> date | None:
    if hasattr(value, "date"):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def parse(table, major) -> Institutions | None:
    """Yahoo's `institutional_holders` frame and `major_holders` frame as one
    summary, or None when neither says anything."""
    holders: list[Holder] = []
    reported: list[date] = []
    if table is not None and not getattr(table, "empty", True):
        for row in table.head(TOP).to_dict("records"):
            name = " ".join(str(row.get("Holder") or "").split())
            if not name:
                continue
            holders.append(Holder(name=name[:80], pct_held=_pct(row.get("pctHeld")),
                                  change_pct=_pct(row.get("pctChange"))))
            if (day := _day(row.get("Date Reported"))) is not None:
                reported.append(day)
    shares: dict[str, float | None] = {}
    if major is not None and not getattr(major, "empty", True):
        column = major.columns[0]
        for key in ("institutionsPercentHeld", "insidersPercentHeld"):
            if key in major.index:
                shares[key] = _pct(major.loc[key, column])
    if not holders and not any(v is not None for v in shares.values()):
        return None
    return Institutions(
        as_of=max(reported) if reported else None,
        institutions_pct=shares.get("institutionsPercentHeld"),
        insiders_pct=shares.get("insidersPercentHeld"),
        holders=holders,
    )


def from_13f(found) -> Institutions:
    """The SEC 13F index's answer (`thirteenf.Holdings`) as a summary."""

    def holder(p) -> Holder:
        return Holder(name=p.manager, pct_held=None, change_pct=p.change_pct,
                      shares=p.shares, value=round(p.value, 2), status=p.status)

    return Institutions(
        as_of=found.as_of, institutions_pct=None, insiders_pct=None,
        holders=[holder(p) for p in found.top],
        sold_out=[holder(p) for p in found.sold_out], source="13f")


def institutions(ticker: str) -> Institutions | None:
    """`ticker`'s institutional holders: the SEC's 13F filings when the local
    index knows the name (US listings), else Yahoo's aggregate, else None
    (most non-US listings, every crypto pair). Raises on a Yahoo network
    failure; the 13F index is a local file and never does."""
    import yfinance as yf

    from stocks.data import thirteenf

    try:
        found = thirteenf.holdings(ticker)
    except Exception:  # noqa: BLE001 - a bad index falls back to Yahoo
        found = None
    if found is not None:
        return from_13f(found)

    stock = yf.Ticker(ticker)
    return parse(stock.institutional_holders, stock.major_holders)
