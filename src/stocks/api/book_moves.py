"""The book's day, week and month: one answer for every screen that prints them.

Home's tiles (`GET /movers`), the daily card's facts and the Today page's
tiles all say how the book did today, this week and this month. Each used to
work it out on its own — the week off a basket held at today's quantities in
one place, off the book's own money in another, the day summed from the
positions table in a third — and the same morning read +402 € on one screen
and −110 € on the next. This is the one recipe:

- the day is the basket's last session, with the quote burst standing in for
  every name whose own exchange is shut (`day_change`): off-hours the newest
  daily bar is stale or flat;
- the week and the month are the book's own money (`money_change`): the value's
  move less what was put in or taken out, over the money at stake — the
  measure every index comparison uses (`index_change`), so the book's figure
  and the index's beside it read the same money;
- every window opens where `window_span` opens it, counted from today's date,
  so a screen that asks at breakfast and one that asks at noon agree.
"""

from __future__ import annotations

import pandas as pd

from stocks.analysis.portfolio import (
    day_change,
    market_live,
    money_change,
    us_market_open,
)
from stocks.api import loaders

# (window, calendar days), in the order the tiles print them.
WINDOWS = (("day", 1), ("week", 7), ("month", 30))
DAYS = dict(WINDOWS)


def session_quotes(frame: pd.DataFrame) -> dict[str, dict] | None:
    """The quote burst for the names outside their own session, or None in
    a regular US session, when the daily bars already are the live price.

    Only the names actually shut: a Paris listing is live at 10:00 CET with
    New York hours away, and crypto never shuts. Sorted, so every caller
    shares one cached burst.
    """
    if us_market_open():
        return None
    off = tuple(sorted(str(t) for t in frame.columns if not market_live(str(t))))
    return loaders.quotes(off) if off else {}


def day(
    frame: pd.DataFrame, quotes: dict[str, dict] | None
) -> tuple[float, float] | None:
    """(amount, fraction) the book moved over its last session."""
    return day_change(frame, quotes) if not frame.empty else None


def moves(db: str, mtime: float, ccy: str) -> dict[str, tuple[float, float] | None]:
    """{window: (amount, fraction) or None} for every window in `WINDOWS`."""
    frame = loaders.basket_values(db, mtime, ccy).dropna(how="all")
    hist = loaders.history(db, mtime, ccy)[0]
    money = None if hist.empty else hist
    out: dict[str, tuple[float, float] | None] = {
        "day": day(frame, session_quotes(frame)) if not frame.empty else None
    }
    for label, days in WINDOWS[1:]:
        out[label] = money_change(money, days)
    return out
