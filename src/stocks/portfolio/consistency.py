"""Data that cannot all be true at once, said once in the logs.

A book can hold rows that contradict each other or the market: one AMZN
bought at $2050 on a day it closed at $104 (a split the statement never
printed), a sale of more shares than were ever bought, one trade imported
twice. Each place that notices one already does something about it — the
import refuses the row, the doctor proposes a fix, the Ticker page writes the
missing split — and the reader sees that. We saw nothing: the only way such a
book reached us was a feedback report.

`report` is the one line all of those places write. One event name,
`data.inconsistency`, with a closed list of kinds, so

    stocks logs stats --event data.inconsistency --by kind

says which contradictions keep turning up and `--by source` where we caught
them (the parser that let it through, or the replay that tripped on it).

What goes in the line is the shape of the contradiction, never the book:
ratios (`off=19.7`), dates of public events (a split's day), catalog symbols.
No quantities, prices or amounts — the same rule `diagnostics` keeps for a
failed import. Said once per account, kind, name and finding in a window,
because the replays that notice most of these run on every request. Nothing
here raises: it runs beside code that is already busy being right.
"""

from __future__ import annotations

import threading
import time
from typing import Literal, get_args

from stocks import obs

EVENT = "data.inconsistency"

Kind = Literal[
    # A buy priced at a split ratio times its day's split-adjusted close: the
    # ledger never heard of a split the market did (corporate.missing_splits).
    "split_missing",
    # A sale of more than the position held on its day (validate at import,
    # the position replay and the doctor afterwards).
    "oversold",
    # The same trade twice: exactly, or the same day and size at a price a
    # rounding apart (validate at import, the doctor afterwards).
    "duplicate",
    # quantity × price strays from the cash total the statement printed.
    "amount_mismatch",
    # Shares that changed broker, booked as a sale at one and a buy at the
    # other (doctor).
    "transfer_as_trade",
    # One company kept under two labels, an ISIN and a symbol (doctor).
    "two_labels",
    # Crypto bought with the fee's coins still counted as held (doctor).
    "fee_in_coins",
    # A name the book holds that no price source quotes: carried at cost.
    "unpriced_held",
]
KINDS: tuple[Kind, ...] = get_args(Kind)

Source = Literal["import", "page", "doctor", "replay"]
SOURCES: tuple[Source, ...] = get_args(Source)

# (kind, account, ticker, key) -> monotonic time it was last said. A book is
# replayed on every request, and one contradiction is one fact, not one line
# per page render.
_WINDOW_S = 6 * 3600.0
_MAX_SEEN = 4096
_seen: dict[tuple, float] = {}
_lock = threading.Lock()


def report(
    kind: Kind, *, source: Source, ticker: str = "", key: object = "", **evidence
) -> bool:
    """Log one contradiction, once per window for this account.

    `key` tells two findings of one kind on one name apart (the doctor's
    finding key, a trade's day) and is never written; `evidence` is. Returns
    whether the line was written.
    """
    try:
        if not _first((kind, obs.current().get("user", ""), ticker, key)):
            return False
        obs.warn(EVENT, kind=kind, source=source, ticker=ticker, **evidence)
        return True
    except Exception:  # noqa: BLE001 - a log line never breaks the page
        return False


def _first(seen: tuple) -> bool:
    """Whether `seen` is new this window; marks it seen."""
    now = time.monotonic()
    with _lock:
        last = _seen.get(seen)
        if last is not None and now - last < _WINDOW_S:
            return False
        if len(_seen) >= _MAX_SEEN:
            for old in [k for k, at in _seen.items() if now - at >= _WINDOW_S]:
                del _seen[old]
            if len(_seen) >= _MAX_SEEN:
                _seen.clear()
        _seen[seen] = now
    return True


def clear() -> None:
    """Forget what was said (tests, which share one process)."""
    with _lock:
        _seen.clear()


def ratio(part: float, whole: float) -> float | None:
    """`part / whole` rounded for a log line, None when there is no whole."""
    if not whole:
        return None
    return round(part / whole, 3)
