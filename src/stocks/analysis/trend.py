"""Where a price stands in its own trend, and against its home market.

Only the reads with a long record behind them, and only as a timing and risk
overlay on a fundamental view, never as a thesis:

* **Price against its 200-session average**, and whether that average is
  rising. The classic trend filter (Faber 2007; Moskowitz, Ooi & Pedersen
  2012): below a falling average, losses tend to run.
* **12-1 momentum** — the return from twelve months ago to one month ago,
  skipping the last month, which tends to reverse (Jegadeesh & Titman 1993;
  Asness et al. 2013).
* **Distance from the 52-week high.** Names near their high tend to keep
  leading and names near their low to keep lagging (George & Hwang 2004).
* **Relative strength** against the index of the market the line trades on.

RSI and ATR ride along as context for the chat, not as verdicts: overbought
in an uptrend is strength, and RSI on a money-market fund is noise.

Windows are by date, not by bar count, so a coin trading 365 days a year and
a share trading 252 sessions read the same "twelve months". Every field is
None, not zero, when the history is too short to say.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from stocks.analysis import naive_dates
from stocks.analysis.indicators import atr, rsi, sma
from stocks.analysis.sentiment import INDICES, Index
from stocks.data.crypto import is_crypto

SMA_LONG = 200
SMA_MID = 50
# How far back the slope of the long average is read: a month of sessions.
SLOPE_SESSIONS = 21
# A window that opens this close after the series starts still counts: a 2y
# download whose first bar fell on a holiday must not lose its 12-month read.
_EDGE = pd.Timedelta(days=7)

_BY_TICKER = {index.ticker: index for index in INDICES}

# Listing suffix -> the index of that market. A share on the German floors
# reads against the DAX, the rest of the euro area against the Euro Stoxx 50.
_SUFFIX_INDEX: dict[str, str] = {
    ".MC": "^IBEX",
    ".PA": "^FCHI",
    ".L": "^FTSE",
    ".T": "^N225",
    ".HK": "^HSI",
    **dict.fromkeys((".DE", ".F", ".BE", ".MU", ".SG", ".DU", ".HM", ".HA"), "^GDAXI"),
    **dict.fromkeys((".AS", ".BR", ".MI", ".LS", ".IR", ".VI", ".HE"), "^STOXX50E"),
}
_GERMAN_FLOORS = frozenset(s for s, t in _SUFFIX_INDEX.items() if t == "^GDAXI")
_US_INDEX = "^GSPC"


def on_german_floor(symbol: str) -> bool:
    """Whether `symbol` trades on a German floor, where foreign names abound."""
    code = symbol.strip().upper()
    return "." in code and code[code.rfind("."):] in _GERMAN_FLOORS


def benchmark_for(symbol: str, country: str | None = None) -> Index | None:
    """The home index `symbol` is measured against, or None.

    A bare US code reads against the S&P 500. A foreign company quoted on a
    German floor (APC.DE is Apple) reads against its own country's index when
    `country` names one, accepting the currency mismatch: the question is
    whether the company led its market, and the DAX does not answer that for
    Apple. Coin pairs, indices and listings with no mapped market get None.
    """
    code = symbol.strip().upper()
    if not code or code.startswith("^") or is_crypto(code):
        return None
    suffix = code[code.rfind("."):] if "." in code else ""
    if suffix in _GERMAN_FLOORS and country and country != "Germany":
        home = next((i for i in INDICES if country in i.countries), None)
        if home is not None:
            return home
    if not suffix:
        return _BY_TICKER[_US_INDEX]
    ticker = _SUFFIX_INDEX.get(suffix)
    return _BY_TICKER[ticker] if ticker else None


def _clean(close: pd.Series) -> pd.Series:
    s = pd.to_numeric(close, errors="coerce").dropna()
    if s.empty:
        return s
    index = pd.DatetimeIndex(s.index)
    if index.tz is not None:
        index = naive_dates(index)
    s = pd.Series(s.to_numpy(dtype=float), index=index)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _asof(close: pd.Series, when: pd.Timestamp) -> float | None:
    """The last close on or before `when`; None before the series starts.

    A `when` a few days ahead of the first bar reads that bar (`_EDGE`).
    """
    if close.empty:
        return None
    first = close.index[0]
    if when < first:
        return float(close.iloc[0]) if first - when <= _EDGE else None
    value = close.asof(when)
    return None if pd.isna(value) else float(value)


def _change(close: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    a, b = _asof(close, start), _asof(close, end)
    if a is None or b is None or a <= 0:
        return None
    return b / a - 1.0


def momentum_12_1(close: pd.Series) -> float | None:
    """Return from twelve months ago to one month ago, as a fraction."""
    s = _clean(close)
    if s.empty:
        return None
    last = s.index[-1]
    return _change(s, last - pd.DateOffset(months=12), last - pd.DateOffset(months=1))


def _last_year(close: pd.Series) -> pd.Series:
    return close[close.index > close.index[-1] - pd.DateOffset(years=1)]


def from_high_52w(close: pd.Series) -> float | None:
    """Distance below the 52-week closing high (<= 0), as a fraction."""
    s = _clean(close)
    if s.empty:
        return None
    peak = float(_last_year(s).max())
    return float(s.iloc[-1]) / peak - 1.0 if peak > 0 else None


def excess_return(close: pd.Series, bench: pd.Series, months: int) -> float | None:
    """The line's return minus its index's over the last `months`, as a fraction.

    Both legs span the same calendar dates, ending on the line's last close, so
    an exchange holiday on one side shifts a day, not the window. A plain
    difference of two returns a reader can check, not a beta-adjusted alpha.
    """
    s, b = _clean(close), _clean(bench)
    if s.empty or b.empty:
        return None
    end = s.index[-1]
    start = end - pd.DateOffset(months=months)
    own, market = _change(s, start, end), _change(b, start, end)
    if own is None or market is None:
        return None
    return own - market


@dataclass(frozen=True)
class TrendRead:
    """One line's trend read. Fractions, not percentages; None = can't say."""

    price: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    sma200_rising: bool | None = None
    pct_vs_sma200: float | None = None
    mom_12_1: float | None = None
    pct_from_high: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    rs_6m: float | None = None
    rs_12m: float | None = None
    bench: str | None = None
    bench_name: str | None = None
    rsi14: float | None = None
    atr_pct: float | None = None
    sessions: int = 0
    # "up": above a rising 200-session average; "down": below a falling one;
    # "mixed": the two disagree; None: under SMA_LONG + SLOPE_SESSIONS bars.
    state: str | None = None


def _last(series: pd.Series) -> float | None:
    value = series.iloc[-1] if len(series) else None
    return None if value is None or pd.isna(value) else float(value)


def state_of(price: float, sma200: float, rising: bool) -> str:
    """"up" above a rising average, "down" below a falling one, else "mixed"."""
    if price > sma200 and rising:
        return "up"
    if price < sma200 and not rising:
        return "down"
    return "mixed"


def trend_read(
    df: pd.DataFrame,
    bench_close: pd.Series | None = None,
    bench: Index | None = None,
) -> TrendRead:
    """The trend read off a daily OHLCV frame (a Close column at least).

    `bench_close` is the home index's daily closes (`benchmark_for`); without
    it the relative-strength fields stay None.
    """
    if df is None or df.empty or "Close" not in df:
        return TrendRead()
    frame = df.copy()
    index = pd.DatetimeIndex(frame.index)
    frame.index = naive_dates(index) if index.tz is not None else index
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    close = _clean(frame["Close"])
    if close.empty:
        return TrendRead()
    price = float(close.iloc[-1])
    sessions = len(close)

    long_avg = sma(close, SMA_LONG)
    sma200 = _last(long_avg)
    rising = None
    if sessions > SMA_LONG + SLOPE_SESSIONS:
        before = long_avg.iloc[-1 - SLOPE_SESSIONS]
        if sma200 is not None and pd.notna(before):
            rising = bool(sma200 > before)

    year = _last_year(close)
    atr_now = _last(atr(frame.loc[close.index]))
    has_bench = bench_close is not None and bench is not None
    return TrendRead(
        price=price,
        sma50=_last(sma(close, SMA_MID)),
        sma200=sma200,
        sma200_rising=rising,
        pct_vs_sma200=price / sma200 - 1.0 if sma200 else None,
        mom_12_1=momentum_12_1(close),
        pct_from_high=from_high_52w(close),
        high_52w=float(year.max()),
        low_52w=float(year.min()),
        rs_6m=excess_return(close, bench_close, 6) if has_bench else None,
        rs_12m=excess_return(close, bench_close, 12) if has_bench else None,
        bench=bench.ticker if bench else None,
        bench_name=bench.name if bench else None,
        rsi14=_last(rsi(close, 14)),
        atr_pct=atr_now / price if atr_now is not None and price else None,
        sessions=sessions,
        state=state_of(price, sma200, rising) if sma200 and rising is not None else None,
    )


def below_sma(closes: Sequence[float], window: int = SMA_LONG) -> bool | None:
    """Whether the last close sits under its `window` average; None if shorter."""
    values = [float(v) for v in closes if v is not None and v == v]
    if len(values) < window:
        return None
    return values[-1] < sum(values[-window:]) / window


def below_sma_share(closes: Mapping[str, Sequence[float]]) -> tuple[int, int]:
    """(names under their 200-session average, names with enough history)."""
    reads = [below_sma(series) for series in closes.values()]
    measured = [r for r in reads if r is not None]
    return sum(measured), len(measured)


_STATE_WORDS = {
    "up": "uptrend",
    "down": "downtrend",
    "mixed": "mixed (price and average disagree)",
}


def _pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def _level(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:,.2f}"


def describe(symbol: str, read: TrendRead) -> str:
    """The read as a few plain lines for a model to quote, figures only.

    Every number a chat answer may cite is here, so it has no reason to name a
    level the data did not give it.
    """
    if read.price is None:
        return f"{symbol}: no daily price history to read a trend from."
    lines = []
    if read.state is None or read.pct_vs_sma200 is None:
        lines.append(
            f"{symbol} trend: only {read.sessions} daily bars, short of the ~11 "
            "months a 200-day average and its slope need."
        )
    else:
        side = "above" if read.pct_vs_sma200 >= 0 else "below"
        slope = "rising" if read.sma200_rising else "falling"
        lines.append(
            f"{symbol} trend (daily, {read.sessions} bars): {side} its 200-day "
            f"average ({_pct(read.pct_vs_sma200)}, average {slope}) — "
            f"{_STATE_WORDS[read.state]}"
        )
    year = []
    if read.mom_12_1 is not None:
        year.append(f"12-1 momentum {_pct(read.mom_12_1)}")
    off, high, low = read.pct_from_high, read.high_52w, read.low_52w
    if off is not None and high is not None and low is not None:
        year.append(
            f"{abs(off) * 100:.1f}% below the 52-week high "
            f"(high {_level(high)}, low {_level(low)})"
        )
    if year:
        lines.append(" · ".join(year))
    if read.bench_name and (read.rs_6m is not None or read.rs_12m is not None):
        legs = [
            f"{_pct(v)} over {m} months"
            for v, m in ((read.rs_6m, 6), (read.rs_12m, 12))
            if v is not None
        ]
        lines.append(
            f"vs {read.bench_name} (return minus the index's): {', '.join(legs)}"
        )
    context = []
    if read.rsi14 is not None:
        context.append(f"RSI14 {read.rsi14:.0f}")
    if read.atr_pct is not None:
        context.append(f"ATR14 {read.atr_pct * 100:.1f}% of price")
    if read.sma50 is not None:
        context.append(f"50-day avg {_level(read.sma50)}")
    if read.sma200 is not None:
        context.append(f"200-day avg {_level(read.sma200)}")
    if context:
        lines.append("context: " + " · ".join(context))
    return "\n".join(lines)
