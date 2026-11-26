"""The book's day, week and month: one answer for every screen that prints them.

Home's tiles (`GET /movers`), the daily card's facts and the Today page's
tiles all say how the book did today, this week and this month. Each used to
work it out on its own — the week off a basket held at today's quantities in
one place, off the book's own money in another, the day summed from the
positions table in a third — and the same morning read +402 € on one screen
and −110 € on the next. This is the one recipe:

- the day is the basket's last session, with the quote burst standing in for
  every name whose own exchange is shut (`day_change`): off-hours the newest
  daily bar is stale or flat; the names trading now have that last bar moved
  to the board's price (`live_frame`), a minute old at most;
- the week and the month are the book's own money (`money_change`): the value's
  move less what was put in or taken out, over the money at stake — the
  measure every index comparison uses (`index_change`), so the book's figure
  and the index's beside it read the same money;
- every window opens where `window_span` opens it, counted from today's date,
  so a screen that asks at breakfast and one that asks at noon agree.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from stocks import loaders
from stocks.analysis.portfolio import (
    day_change,
    market_live,
    money_change,
    us_market_open,
)
from stocks.frames import naive_dates

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


# How far one name's live price may sit from the bar it replaces before the
# reading is taken for a slip rather than a move. The bar is the same session,
# minutes old: a real name does not halve or double between two refreshes.
LIVE_SWING = (0.5, 2.0)


def live_frame(
    frame: pd.DataFrame, db: str, mtime: float
) -> tuple[pd.DataFrame, dict[str, dict]]:
    """`frame` with the last row of every name trading now moved to the
    board's price, and the snapshots that moved it.

    The frame is built off the book's closes, and rebuilding it is seconds of
    replay a book: it is refreshed every few minutes, not every minute. Its
    last row already carries the live price of the moment it was built
    (`loaders._overlay_live`); this scales that row by how far each live name
    has gone since (board price over the close it was built on), FX held where
    the frame had it. So a minute-old price reaches the tiles for the cost of
    one row.

    A name is left as built when its quote is for another session than its
    last bar (the frame is a day behind, or the quote is), when either side
    is missing, or when the two sit `LIVE_SWING` apart.
    """
    live = [str(t) for t in frame.columns if market_live(str(t))]
    if frame.empty or not live:
        return frame, {}
    snaps = loaders.quotes(tuple(sorted(live)))
    if not snaps:
        return frame, {}
    closes = loaders.held_closes(db, mtime)
    last_day = naive_dates(frame.index[-1:])[0]
    row = frame.iloc[-1]
    used: dict[str, dict] = {}
    scale: dict[str, float] = {}
    low, high = LIVE_SWING
    for ticker in live:
        snap, series = snaps.get(ticker) or {}, closes.get(ticker)
        price, day = snap.get("regular"), snap.get("regular_as_of")
        if not price or not day or series is None or series.empty:
            continue
        if pd.isna(row.get(ticker)):
            continue
        bar_day = naive_dates(series.index[-1:])[0]
        if bar_day != last_day or bar_day.date().isoformat() != day:
            continue
        bar = float(series.iloc[-1])
        if bar <= 0 or not low <= float(price) / bar <= high:
            continue
        used[ticker] = snap
        if float(price) != bar:
            scale[ticker] = float(price) / bar
    if scale:
        frame = frame.copy()
        for ticker, ratio in scale.items():
            frame.iloc[-1, frame.columns.get_loc(ticker)] *= ratio
    return frame, used


def quoted_at(*quotes: dict[str, dict] | None) -> str | None:
    """When the oldest moving price among `quotes` was read, ISO UTC.

    Moving means a live session or pre/after-hours: a shut market's last
    close is the same at any hour, and dating its read would claim a
    freshness the figure does not have. None when nothing is moving.
    """
    stamps = [
        float(q["fetched_at"])
        for group in quotes
        for t, q in (group or {}).items()
        if q.get("fetched_at") and (market_live(t) or q.get("session") in ("pre", "post"))
    ]
    if not stamps:
        return None
    return datetime.fromtimestamp(min(stamps), UTC).isoformat(timespec="seconds")


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
    if not frame.empty:
        frame = live_frame(frame, db, mtime)[0]
    out: dict[str, tuple[float, float] | None] = {
        "day": day(frame, session_quotes(frame)) if not frame.empty else None
    }
    for label, days in WINDOWS[1:]:
        out[label] = money_change(money, days)
    return out
