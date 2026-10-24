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
    # A dividend yield or payout no payer has, dropped from the KPIs: the
    # feed's unit or currency slipped (fundamentals).
    "feed_dividend",
    # Statements filed in one currency, the price quoted in another, and no
    # rate between them: the cash-flow ratios read blank (fundamentals).
    "feed_currency",
    # A name the review page could not price on its cash flow: an FCF yield
    # too high to be a price, or an enterprise value at or under zero.
    "metric_suspect",
    # A buy priced far from its day's close on a scale no split explains —
    # pence booked as pounds, the wrong name under a symbol, a typo. Found
    # where the split check already fetched the close (corporate).
    "price_off_market",
    # A quote whose price and previous close sit a multiple apart no session
    # produces: the feed mixed units or currencies, or kept a stale close
    # across a split. Past `QUOTE_JUMP_DROPPED` the day move is not shown.
    "quote_jump",
    # A fill or a close a hundred times off its counterpart: pence booked as
    # pounds, or the feed quoting in minor units the book does not (replay,
    # corporate). Split from `price_off_market` so the unit slips, which a
    # scale fixes, count apart from the wrong-name ones.
    "currency_off",
    # A buy or sell dated on a day its market printed no bar, nor the day
    # before: a weekday holiday, a date shifted by a parser (replay).
    "trade_off_calendar",
    # A day the whole book's value moved past `QUOTE_JUMP_SAID` net of its
    # flows — a price slip, or a flow the ledger never saw (replay).
    "twr_jump",
]
KINDS: tuple[Kind, ...] = get_args(Kind)

Source = Literal["import", "page", "doctor", "replay", "feed", "review", "sweep"]
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


# Off by about a hundred, either way: the minor-unit slip (GBp against GBP,
# ZAc against ZAR, ILA against ILS). Wide enough for a session's drift on
# top of the 100x, narrow enough that no split ratio this side of 50:1 lands
# in it.
UNIT_SLIP = (50.0, 200.0)


def unit_slip(off: float | None) -> bool:
    """Whether `off`, a price over its counterpart, is the minor-unit slip."""
    if not off or off <= 0:
        return False
    low, high = UNIT_SLIP
    return low <= off <= high or low <= 1 / off <= high


# A price this many times its previous close, either way, is not a session's
# move. Said from 3x: real ones exist (a biotech on a trial result) but are
# rare enough to look at. Dropped from 10x: no continuing listing prints one,
# and the feed's own slips land there — pence against pounds (100x), a close
# left unadjusted across a 20:1 split (20x), a currency mixed in a row.
QUOTE_JUMP_SAID = 3.0
QUOTE_JUMP_DROPPED = 10.0


def day_move(
    price: float | None, prev: float | None, *, ticker: str = "", source: Source = "feed"
) -> float | None:
    """`price / prev - 1`, or None when the two cannot be one session apart.

    The one place a day move is measured from a quote — the portfolio's
    session snapshot and the chat's live block both come here — so a feed
    glitch is said once and shown nowhere, instead of landing on a card as
    "+9,900 % today". None as well when either side is missing or zero.
    """
    if not price or not prev or price < 0 or prev < 0:
        return None
    off = price / prev
    if off >= QUOTE_JUMP_SAID or off <= 1 / QUOTE_JUMP_SAID:
        report("quote_jump", source=source, ticker=ticker, off=round(off, 3))
        if off >= QUOTE_JUMP_DROPPED or off <= 1 / QUOTE_JUMP_DROPPED:
            return None
    return off - 1
