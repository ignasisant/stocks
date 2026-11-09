"""Reading a price frame's index, typed.

pandas types `DataFrame.index` as the plain `Index` base and attaches
`DatetimeIndex`'s own date fields dynamically, so a checker sees none of
`.normalize()`, `.day_of_week`, `.tz` or `.strftime` on a frame that plainly has
them. Every price history in the web layer is keyed by timestamp; naming that
once here keeps the suppressions off the call sites.
"""

from __future__ import annotations

from typing import cast

import pandas as pd


def dates(df: pd.DataFrame) -> pd.DatetimeIndex:
    """`df.index` as the DatetimeIndex it always is."""
    return cast(pd.DatetimeIndex, df.index)


def sessions(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Each bar's calendar day at midnight — intraday bars grouped by session."""
    return dates(df).normalize()


def midnights(index) -> pd.DatetimeIndex:
    """Any timestamp index at midnight — a series keyed by calendar day."""
    return pd.DatetimeIndex(index).normalize()


def midnight(stamp) -> pd.Timestamp:
    """One timestamp (or date) at midnight of its calendar day."""
    return cast(pd.Timestamp, pd.Timestamp(stamp)).normalize()


def weekdays(df: pd.DataFrame):
    """Monday=0 .. Sunday=6 for every bar."""
    return dates(df).day_of_week


def naive_dates(index) -> pd.DatetimeIndex:
    """`index` as a tz-naive DatetimeIndex.

    Price histories arrive with a mix of tz-aware and naive indexes depending
    on the market and the interval, and everything downstream compares them
    against plain dates — so they are flattened on the way in. pandas types a
    frame's `.index` as the plain `Index` base, which carries none of the
    datetime methods; naming the real class once, here, keeps every caller
    free of that.
    """
    out = pd.DatetimeIndex(pd.to_datetime(index))
    if out.tz is None:
        return out
    return out.tz_localize(None)


def naive_series(series: pd.Series) -> pd.Series:
    """`series` on naive dates, one value a day, oldest first, gaps dropped."""
    out = series.dropna().copy()
    out.index = naive_dates(out.index)
    return out[~out.index.duplicated(keep="last")].sort_index()
