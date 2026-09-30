"""What a money-market fund earns — the one number it is held for.

An accumulating money-market line (XEON, IB01) folds each day's interest back
into its price, so the price *is* the return: the gain over a window,
compounded to a year, is what the fund yields. Its chart is a straight line
and its RSI a permanent "overbought", which is why the ticker page shows this
instead, beside the central-bank rate the fund tracks.

A distributing US money-market fund keeps its price pinned at 1 and pays the
interest out; its price says nothing, and Yahoo's trailing yield stands in
(`is_flat`).

Pure: closes and FRED series in, fractions out.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

# A pinned-NAV fund wobbles by a rounding tick at most; an accumulating one at
# 2% a year moves 0.5% in a quarter.
_FLAT = 0.001
# A window is read only when the closes cover most of it — a fund listed six
# weeks ago has no three-month yield.
_COVER = 0.8


def _clean(close: pd.Series) -> pd.Series:
    series = pd.to_numeric(close, errors="coerce").dropna()
    series = series[series > 0]
    if series.empty:
        return series
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    return pd.Series(series.to_numpy(), index=index).sort_index()


def annualised(close: pd.Series, days: int) -> float | None:
    """The gain over the last `days` calendar days, compounded to a year.

    ``(last / first) ** (365 / span) - 1``, `first` being the first close on
    or after the window's start and `span` the calendar days actually
    between the two. None when the closes cover less than 80% of the window.
    """
    series = _clean(close)
    if len(series) < 2:
        return None
    end = series.index[-1]
    window = series[series.index >= end - pd.Timedelta(days=days)]
    if len(window) < 2:
        return None
    span = (end - window.index[0]).days
    if span < days * _COVER:
        return None
    return float((window.iloc[-1] / window.iloc[0]) ** (365 / span) - 1)


def is_flat(close: pd.Series, days: int = 365) -> bool:
    """True when the price barely moved over the window (a pinned-NAV fund)."""
    series = _clean(close)
    if series.empty:
        return False
    window = series[series.index >= series.index[-1] - pd.Timedelta(days=days)]
    return len(window) >= 2 and float(window.max() / window.min() - 1) < _FLAT


def policy_level(
    series_ids: tuple[str, ...], rates: dict[str, pd.Series]
) -> tuple[float, date] | None:
    """A bank's current rate as a fraction, and the day it was last printed.

    `series_ids` as `macro_calendar.RATE_SERIES` has them: one id for the
    ECB, the two bounds of the Fed's range — whose midpoint is the rate a
    dollar fund earns about. None when any of them is missing.
    """
    levels: list[float] = []
    stamps: list[date] = []
    for sid in series_ids:
        raw = rates.get(sid, pd.Series(dtype=float))
        series = pd.to_numeric(raw, errors="coerce").dropna()
        if series.empty:
            return None
        levels.append(float(series.iloc[-1]) / 100)
        # A FRED observation's index is its print date, never NaT.
        stamps.append(pd.Timestamp(series.index[-1]).date())  # ty: ignore[invalid-argument-type]
    return sum(levels) / len(levels), min(stamps)
