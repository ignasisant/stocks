"""The lifetimes and cache keys every loader shares: ledger state and file
mtimes.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from stocks.api.cache import ttl_cache
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.positions import build

# Held prices move all day but a book's shape does not; these mirror the ttls
# the pages use for the same loads.
_LEDGER_TTL = 3600.0
_PRICES_TTL = 900.0
_QUOTES_TTL = 300.0


def db_mtime(db: str) -> float:
    """The ledger file's mtime, or 0.0 when it does not exist yet.

    Part of every loader's cache key, so a committed import invalidates exactly
    the entries that read the file it rewrote.
    """
    path = Path(db)
    return path.stat().st_mtime if path.exists() else 0.0


class LedgerState(NamedTuple):
    """One replay of the ledger. Shared by every caller of the memo: read it,
    never change the lists in place."""

    txs: list
    positions: list
    realized: list


def ledger_state(
    db: str, mtime: float, base: str = "EUR", matching: str = "fifo"
) -> LedgerState:
    """Ledger + share-matching replay: `.txs`, `.positions`, `.realized`.

    `matching` is in the key as well as the arguments: FIFO and s.104 produce
    different realized parcels — and different basis left behind — from the
    very same trades.

    Spelled out before the memo: `ttl_cache` keys on the arguments as passed,
    so `ledger_state(db, mtime)`, `(db, mtime, "EUR")` and `base="EUR"` were
    three entries and three replays of one book — seconds each on a long
    ledger, from routes that run side by side on the same page.
    """
    return _ledger_state(db, mtime, base, matching)


@ttl_cache(_LEDGER_TTL, max_entries=32)
def _ledger_state(db: str, mtime: float, base: str, matching: str) -> LedgerState:
    txs = all_transactions(Path(db))
    positions, realized = build(txs, base=base, matching=matching) if txs else ([], [])
    return LedgerState(txs, positions, realized)


ledger_state.cache_clear = _ledger_state.cache_clear  # ty: ignore[unresolved-attribute]


# How long the book's last prices answer at once while the next download runs
# behind them. The download is twenty seconds to a minute on the production
# vCPU, and every Home, Posiciones and Pulso read waits on it: with a 45-minute
# window, the first visit of every morning (and the first after any hour away)
# paid all of it. Past the quiet window the answer is marked stale, so the
# page says how old its figures are until the refresh has landed. Persisted,
# so a new process answers from the last one's prices the same way — they are
# a fraction of the frames' size, one Series per name.
_HELD_STALE = 2 * 86400.0
_HELD_QUIET = 3 * _PRICES_TTL



def file_mtime(path: Path) -> float:
    """Any account file's mtime, or 0.0 when it does not exist yet.

    The sibling of `db_mtime` for the JSON files beside the ledger: part of a
    cache key so a rewrite invalidates exactly the entry that read it.
    """
    return path.stat().st_mtime if path.exists() else 0.0
