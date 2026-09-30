"""Every range label downloads enough history for the lines it draws.

The chart's slowest overlay is a 200-bar average, and a line that only starts
two thirds of the way across the window is worse than no line: it reads as the
price having gone somewhere, not as the indicator warming up. `PERIODS`
therefore downloads well past the window each label shows — this pins that,
since the download period and the display window are two constants that can
drift apart silently.
"""

from __future__ import annotations

import pandas as pd

from stocks.analysis.history import (
    MAX_BARS,
    PERIODS,
    WINDOW,
    bar_interval,
    coarsen,
    listed,
    rangebreaks,
    ranges,
    shape,
    trim,
)
from stocks.analysis.indicators import add_indicators

# Sessions per download period, and bars per session at each interval: a year
# is ~252 sessions, and a US session is 78 five-minute or 13 half-hour bars.
_SESSIONS = {"5d": 5, "1mo": 22, "6mo": 126, "1y": 252, "2y": 504, "5y": 1260,
             "10y": 2520}
_PER_SESSION = {"1d": 1, "30m": 13, "5m": 78}
# What the intraday labels show — `trim` cuts those by session, not by calendar.
_INTRADAY_SESSIONS = {"1d": 1, "1w": 5}
_SLOWEST = 200


def _shown_sessions(label: str) -> float:
    if label in _INTRADAY_SESSIONS:
        return _INTRADAY_SESSIONS[label]
    window = WINDOW[label].kwds
    return 252 * (window.get("years", 0) + window.get("months", 0) / 12)


def _synthetic(bars: int, interval: str) -> pd.DataFrame:
    freq = "B" if interval == "1d" else interval.replace("m", "min")
    index = pd.date_range("2020-01-01 09:30", periods=bars, freq=freq)
    close = pd.Series(range(1, bars + 1), dtype=float)
    return pd.DataFrame({"Close": close.to_numpy()}, index=index)


def test_every_label_downloads_the_slowest_averages_warmup():
    for label, (period, interval) in PERIODS.items():
        if label == "max":  # everything there is: no bars before the first
            continue
        per_session = _PER_SESSION[interval]
        downloaded = _SESSIONS[period] * per_session
        warmup = downloaded - _shown_sessions(label) * per_session
        assert warmup >= _SLOWEST, (
            f"{label} downloads {period}: only {warmup:.0f} bars of warm-up "
            f"before the window opens, and SMA200 needs {_SLOWEST}"
        )


def test_the_slowest_line_spans_a_daily_window():
    """The one that used to fail: a month drawn off six months of bars."""
    for label in ("1m", "3m", "6m", "1y"):
        period, interval = PERIODS[label]
        bars = _SESSIONS[period] * _PER_SESSION[interval]
        window = trim(add_indicators(_synthetic(bars, interval)), label)
        assert not window["SMA200"].isna().any(), f"{label} opens on an SMA200 gap"


def _dated(start: str, end: str) -> pd.DataFrame:
    index = pd.bdate_range(start, end)
    return pd.DataFrame({"Close": range(1, len(index) + 1)}, index=index, dtype=float)


def test_max_keeps_every_bar():
    df = _dated("2019-01-01", "2024-06-28")
    assert len(trim(df, "max")) == len(df)


def test_a_young_listing_offers_no_window_longer_than_itself():
    """Two and a half years of trading: 5Y would draw what Max draws under a
    label that overstates it."""
    df = _dated("2022-01-03", "2024-06-28")
    offered = ranges(df, listed(df, "max"))
    assert "5y" not in offered
    assert {"1d", "1w", "1m", "1y", "2y", "max"} <= set(offered)


def test_a_listing_older_than_every_window_offers_them_all():
    df = _dated("2023-01-02", "2024-06-28")
    df.attrs["first_trade"] = "1980-12-12"
    assert ranges(df, listed(df, "1y")) == list(PERIODS)


def test_the_listing_date_is_never_after_a_bar_the_frame_holds():
    df = _dated("2010-01-04", "2024-06-28")
    df.attrs["first_trade"] = "2012-05-18"
    assert listed(df, "max") == "2010-01-04"


def test_a_trimmed_frame_without_yahoos_date_knows_no_listing():
    """Its first bar is where the download started, not where trading did."""
    df = _dated("2022-06-28", "2024-06-28")
    assert listed(df, "1y") is None
    assert ranges(df, None) == list(PERIODS)


def test_the_listing_date_survives_the_indicators():
    df = _dated("2023-01-02", "2024-06-28")
    df.attrs["first_trade"] = "2001-03-05"
    assert trim(add_indicators(df), "1y").attrs["first_trade"] == "2001-03-05"


def _ohlc(start: str, end: str) -> pd.DataFrame:
    df = _dated(start, end)
    close = df["Close"]
    return df.assign(Open=close - 0.5, High=close + 1, Low=close - 1, Volume=10.0,
                     Dividends=0.0)


def test_a_max_that_fits_stays_daily():
    df = _ohlc("2020-01-01", "2024-06-28")
    assert len(df) <= MAX_BARS
    out = shape(df, "max")
    assert len(out) == len(df) and bar_interval(out, "max") == "1d"


def test_a_long_max_is_drawn_weekly():
    """Twenty years of sessions: ~5,000 candles, a few to each pixel."""
    df = _ohlc("2004-01-05", "2024-06-28")
    out = shape(df, "max")
    assert bar_interval(out, "max") == "1wk"
    assert len(out) <= MAX_BARS < len(df)


def test_a_max_too_long_even_weekly_is_drawn_monthly():
    df = _ohlc("1980-12-12", "2024-06-28")
    out = coarsen(df)
    assert out.attrs["interval"] == "1mo" and len(out) <= MAX_BARS
    assert rangebreaks(out, "1mo") == []


def test_the_first_bar_stays_the_listing_day():
    """So "since inception" is measured from the first close, not from the
    close of the listing's first week."""
    df = _ohlc("2004-01-05", "2024-06-28")
    out = coarsen(df)
    assert out.index[0] == df.index[0]
    assert out["Close"].iloc[0] == df["Close"].iloc[0]
    assert out.attrs["first_trade"] == "2004-01-05"


def test_a_bucket_is_dated_by_its_last_session():
    """An event looked up as "the first bar on or after its day" must land in
    the week holding it — a Friday holiday dates the week on its Thursday."""
    df = _ohlc("2004-01-05", "2024-06-28").drop(pd.Timestamp("2024-06-21"))
    out = coarsen(df)
    assert pd.Timestamp("2024-06-20") in out.index
    assert pd.Timestamp("2024-06-21") not in out.index
    wednesday = out.index[out.index >= pd.Timestamp("2024-06-12")][0]
    assert wednesday == pd.Timestamp("2024-06-14")


def test_a_bucket_holds_its_sessions_ohlc():
    df = _ohlc("2004-01-05", "2024-06-28")
    df.loc[pd.Timestamp("2024-06-19"), "Dividends"] = 0.25
    week = df.loc["2024-06-17":"2024-06-21"]
    bar = coarsen(df).loc[pd.Timestamp("2024-06-21")]
    assert bar["Open"] == week["Open"].iloc[0]
    assert bar["High"] == week["High"].max() and bar["Low"] == week["Low"].min()
    assert bar["Close"] == week["Close"].iloc[-1]
    assert bar["Volume"] == week["Volume"].sum() and bar["Dividends"] == 0.25


def test_the_indicators_are_read_at_the_buckets_last_session():
    """Sampled, not recomputed: the SMA200 is still 200 sessions, not weeks."""
    df = add_indicators(_ohlc("2004-01-05", "2024-06-28"))
    bar = coarsen(df).loc[pd.Timestamp("2024-06-21")]
    assert bar["SMA200"] == df.loc[pd.Timestamp("2024-06-21"), "SMA200"]
