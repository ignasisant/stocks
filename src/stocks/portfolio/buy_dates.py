"""When a price was paid: the sessions whose range held it.

A holdings snapshot says what is held and, at best, the average paid — never
when. The ledger needs a date, and the price is the one clue: a session whose
low and high bracket it is a day the buy could have filled. Matching sessions
come in stretches (a stock trades through a price for a week, then leaves), so
each stretch is offered once, at its session whose close sat nearest.

Prices are the bars' as they come from Yahoo, split-adjusted, and so is what a
broker reports as an average after a split: the two compare as they are.
"""

from __future__ import annotations

import pandas as pd

LIMIT = 8


def runs(bars: pd.DataFrame, price: float, limit: int = LIMIT) -> list[dict]:
    """Stretches of sessions whose low-high range held `price`, newest first.

    Each is {start, end, day, close, sessions}: ISO first and last session,
    the session whose close was nearest the price (the date to offer), that
    close, and how many sessions the stretch ran. Empty when no session ever
    traded at the price, or the bars lack a range.
    """
    if price <= 0 or bars is None or bars.empty or not {"Low", "High"} <= set(bars):
        return []
    frame = bars[["Low", "High"] + (["Close"] if "Close" in bars else [])]
    frame = frame.apply(pd.to_numeric, errors="coerce").dropna(subset=["Low", "High"])
    if frame.empty:
        return []
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    frame.index = index.normalize()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    hit = (frame["Low"] <= price) & (price <= frame["High"])
    # A new stretch starts at every session that hits after one that missed.
    stretch = (hit & ~hit.shift(fill_value=False)).cumsum()[hit]
    found = []
    for _, days in frame[hit].groupby(stretch):
        close = days["Close"] if "Close" in days else (days["Low"] + days["High"]) / 2
        nearest = (close - price).abs().idxmin()
        found.append({
            "start": days.index[0].date().isoformat(),
            "end": days.index[-1].date().isoformat(),
            "day": nearest.date().isoformat(),
            "close": float(close[nearest]),
            "sessions": len(days),
        })
    found.reverse()
    return found[:limit]
