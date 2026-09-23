"""Price history shaped for a chart: the range labels, the window, the breaks.

The Ticker page's period control is not a passthrough to yfinance. Each label
downloads more history than it shows — indicators need a run-up, and "1 month"
drawn from exactly one month of bars has no SMA50, let alone an SMA200 — and
then trims back to the window the label names. Intraday labels trim by trading
session instead of by calendar, because five days of 30-minute bars is five
*sessions*, not five days.

All of it is pandas over a downloaded frame, with no UI in it, so it lives here
rather than in the page: the Streamlit page and the HTTP API both ask for "1y of
AAPL" and must get the same bars, the same indicator columns and the same axis
breaks. A chart that disagrees with itself across two front ends is worse than
either one being wrong.
"""

from __future__ import annotations

from typing import cast

import pandas as pd

from stocks import frames
from stocks.analysis.indicators import add_indicators

# label -> (download period, bar interval). The download is deliberately wider
# than the label: `trim` cuts it back once the indicators have their run-up,
# and the slowest overlay needs 200 bars of it before the window even opens.
# That is why every daily label under a year downloads two — a shorter history
# would draw an SMA200 that starts somewhere in the middle of the chart, or
# not at all. They share one download, so four labels are also one fetch.
PERIODS: dict[str, tuple[str, str]] = {
    "1d": ("5d", "5m"),
    "1w": ("1mo", "30m"),
    "1m": ("2y", "1d"),
    "3m": ("2y", "1d"),
    "6m": ("2y", "1d"),
    "1y": ("2y", "1d"),
    "2y": ("5y", "1d"),
    "5y": ("10y", "1d"),
}

# Display window per label for the daily-interval ranges, anchored at the last
# bar. Intraday labels (1d/1w) trim by trading session instead.
WINDOW: dict[str, pd.DateOffset] = {
    "1m": pd.DateOffset(months=1),
    "3m": pd.DateOffset(months=3),
    "6m": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
    "2y": pd.DateOffset(years=2),
    "5y": pd.DateOffset(years=5),
}


def trim(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Cut an extended-history frame back to the label's display window."""
    if df.empty:
        return df
    if label in ("1d", "1w"):
        sessions = frames.sessions(df)
        keep = sessions.unique()[-1 if label == "1d" else -5:]
        return df[sessions >= keep[0]]
    return df[df.index >= df.index[-1] - WINDOW[label]]


def rangebreaks(df: pd.DataFrame, interval: str) -> list[dict]:
    """Axis breaks hiding closed-market time so candles render contiguous.

    Weekends and holidays come from the days actually missing in the data,
    overnight hours (intraday bars only) from the observed session open/close
    — so US and EU tickers both work without an exchange calendar. Markets
    with weekend bars (crypto) get no breaks at all.
    """
    if df.empty or (frames.weekdays(df) >= 5).any():
        return []
    breaks = [dict(bounds=["sat", "mon"])]
    sessions = frames.sessions(df).unique()
    holidays = pd.bdate_range(sessions[0], sessions[-1]).difference(sessions)
    if len(holidays):
        breaks.append(dict(values=holidays.tolist()))
    if interval.endswith(("m", "h")):
        t = df.index.to_series()
        day = t.dt.normalize()
        hours = t.dt.hour + t.dt.minute / 60
        open_h = hours.groupby(day).min().median()
        close_h = (
            hours.groupby(day).max()
            + cast(pd.Timedelta, pd.Timedelta(interval))
            / cast(pd.Timedelta, pd.Timedelta(hours=1))
        ).median()
        if close_h != open_h:
            breaks.append(dict(bounds=[close_h % 24, open_h], pattern="hour"))
    return breaks


def price_history(ticker: str, label: str) -> pd.DataFrame:
    """OHLCV plus indicator columns for one range label, trimmed to its window.

    The index is made timezone-naive on the way out: Plotly.js has no timezone
    support, so the bars carry exchange-local wall time and the hour-based
    rangebreaks line up with what the axis shows. Stamping them UTC instead
    would slide every session by its own offset.
    """
    from stocks.data.fetch import fetch_history

    period, interval = PERIODS[label]
    df = trim(add_indicators(fetch_history(ticker, period=period, interval=interval)),
              label)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df
