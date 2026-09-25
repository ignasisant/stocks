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

from stocks.analysis.history import PERIODS, WINDOW, trim
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
