"""Market indices by the name a reader knows them by.

An index has no SEC title, no fund catalog entry and no logo, and the bulk
name routes never fetch, so until a page had asked Yahoo for its profile the
chat's comparison drew "^IXIC" bare beside "^GSPC — S&P 500". Yahoo's own
names are no better once fetched: "ESTX 50 PR.EUR", "DAX PERFORMANCE-INDEX".
These are proper nouns, the same in every language the app speaks.
"""

from __future__ import annotations

NAMES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^NDX": "Nasdaq 100",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
    "^STOXX50E": "Euro Stoxx 50",
    "^STOXX": "Stoxx Europe 600",
    "^GDAXI": "DAX",
    "^IBEX": "IBEX 35",
    "^FCHI": "CAC 40",
    "^FTSE": "FTSE 100",
    "FTSEMIB.MI": "FTSE MIB",
    "^AEX": "AEX",
    "^SSMI": "SMI",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
}


def name(symbol: str) -> str | None:
    """The everyday name of a well-known index, or None for anything else."""
    return NAMES.get(symbol.upper())
