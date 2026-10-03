"""Price history shaped for a chart: the range labels, the window, the breaks.

The Ticker page's period control is not a passthrough to yfinance. Each label
downloads more history than it shows — indicators need a run-up, and "1 month"
drawn from exactly one month of bars has no SMA50, let alone an SMA200 — and
then trims back to the window the label names. Intraday labels trim by trading
session instead of by calendar, because five days of 30-minute bars is five
*sessions*, not five days.

All of it is pandas over a downloaded frame, with no UI in it, so it lives here
rather than in the page.
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
    # Everything since the listing, untrimmed. The one label with no run-up:
    # there are no bars before the first one, so its SMA200 opens 200 sessions
    # in, which is also where the stock's own history gives it one.
    "max": ("max", "1d"),
}

# Display window per label for the daily-interval ranges, anchored at the last
# bar. Intraday labels (1d/1w) trim by trading session instead, and "max" is
# not trimmed at all.
WINDOW: dict[str, pd.DateOffset] = {
    "1m": pd.DateOffset(months=1),
    "3m": pd.DateOffset(months=3),
    "6m": pd.DateOffset(months=6),
    "1y": pd.DateOffset(years=1),
    "2y": pd.DateOffset(years=2),
    "5y": pd.DateOffset(years=5),
}


# "max" over an old listing is every session since it: ~11,500 daily bars for a
# stock listed in 1980, 2 MB of JSON and a candle per fraction of a pixel. It is
# drawn at the finest of these bar sizes that stays within MAX_BARS — about
# five years of dailies, the densest any other label draws — as Yahoo's own
# "Max" chart goes monthly. Bucket rule per bar size, for `DataFrame.resample`.
MAX_BARS = 1300
COARSER: dict[str, str] = {"1wk": "W-FRI", "1mo": "ME"}


def trim(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Cut an extended-history frame back to the label's display window."""
    if df.empty or label == "max":
        return df
    if label in ("1d", "1w"):
        sessions = frames.sessions(df)
        keep = sessions.unique()[-1 if label == "1d" else -5:]
        return df[sessions >= keep[0]]
    return df[df.index >= df.index[-1] - WINDOW[label]]


def listed(df: pd.DataFrame, label: str) -> str | None:
    """The listing's first trading day (``YYYY-MM-DD``), or None if unknown.

    Yahoo's `firstTradeDate` when the download carried it, but never later than
    a bar the frame actually holds — some listings have history from before the
    date Yahoo files as their first trade. Without it, only an untrimmed "max"
    frame knows where the history starts: its first bar.
    """
    first = df.attrs.get("first_trade")
    start = str(pd.Timestamp(df.index[0]).date()) if not df.empty else None
    if first and start:
        return min(first, start)
    return first or (start if label == "max" else None)


def ranges(df: pd.DataFrame, since: str | None) -> list[str]:
    """The labels worth offering for a listing whose history starts `since`.

    A window longer than the whole history draws exactly the bars "max" does
    under a label that overstates them — "5Y" over two years of trading — so
    those drop out. Intraday labels and "max" always stay; so does everything
    when the start is unknown, which is the page as it was before it knew.
    """
    if since is None or df.empty:
        return list(PERIODS)
    last = cast(pd.Timestamp, pd.Timestamp(df.index[-1]).tz_localize(None)).normalize()
    start = pd.Timestamp(since)
    return [
        label
        for label in PERIODS
        if label not in WINDOW or start <= last - WINDOW[label]
    ]


def coarsen(df: pd.DataFrame) -> pd.DataFrame:
    """A long daily frame regrouped into weekly or monthly bars (see MAX_BARS).

    The indicators were computed on the dailies and are sampled, not redone:
    the SMA200 on a monthly "max" is still the 200-session average the other
    labels draw, read at each month's last session. Each bar is dated by the
    last session it holds, so an event or a fill looked up as "the first bar
    on or after its day" lands in the bucket that contains it. The first bar
    stays the listing day on its own: the change "since inception" is measured
    from the first close, and a bucket's close is its last session's.

    The bar size goes in `attrs["interval"]`, the listing date in
    `attrs["first_trade"]` — the first bar no longer spans the whole start.
    """
    if len(df) <= MAX_BARS:
        return df
    how = {"Open": "first", "High": "max", "Low": "min",
           "Volume": "sum", "Dividends": "sum"}
    dated = df.assign(_at=df.index)
    agg = {column: how.get(column, "last") for column in dated.columns}
    out = df
    for interval, rule in COARSER.items():
        buckets = dated.iloc[1:].resample(rule).agg(agg)
        buckets = buckets[buckets["_at"].notna()]
        out = pd.concat([dated.iloc[:1], buckets]).set_index("_at")
        out.index.name = df.index.name
        out.attrs = {**df.attrs, "first_trade": listed(df, "max"), "interval": interval}
        if len(out) <= MAX_BARS:
            break
    return out


def rangebreaks(df: pd.DataFrame, interval: str) -> list[dict]:
    """Axis breaks hiding closed-market time so candles render contiguous.

    Weekends and holidays come from the days actually missing in the data,
    overnight hours (intraday bars only) from the observed session open/close
    — so US and EU tickers both work without an exchange calendar. Markets
    with weekend bars (crypto) get no breaks at all, and nor do weekly or
    monthly bars: a gap between them is the bar, not a closed market.
    """
    if df.empty or interval in COARSER or (frames.weekdays(df) >= 5).any():
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


def bars_download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """The extended-history frame a label's window is cut from, indicators on.

    Its own step so a cache can key it on what is actually downloaded —
    `PERIODS[label]` — rather than on the label: 1m, 3m, 6m and 1y are one
    2y/1d download, and a memo keyed by label fetched it four times over as a
    reader flipped through them.
    """
    from stocks.data.fetch import fetch_history

    return add_indicators(fetch_history(ticker, period=period, interval=interval))


def shape(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """`bars_download` cut to the label's window, index made timezone-naive.

    Naive on the way out: Plotly.js has no timezone support, so the bars carry
    exchange-local wall time and the hour-based rangebreaks line up with what
    the axis shows. Stamping them UTC instead would slide every session by its
    own offset.
    """
    df = trim(df, label)
    index = df.index
    if isinstance(index, pd.DatetimeIndex) and index.tz is not None:
        df = df.copy()
        df.index = index.tz_localize(None)
    return coarsen(df) if label == "max" else df


def bar_interval(df: pd.DataFrame, label: str) -> str:
    """The bar size `shape` drew the label at: its download's, unless coarsened."""
    return df.attrs.get("interval") or PERIODS[label][1]


def price_history(ticker: str, label: str) -> pd.DataFrame:
    """OHLCV plus indicator columns for one range label, trimmed to its window."""
    period, interval = PERIODS[label]
    return shape(bars_download(ticker, period, interval), label)
