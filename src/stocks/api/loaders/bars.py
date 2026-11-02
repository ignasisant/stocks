"""One symbol's price bars and closes, and the day's FX."""

from __future__ import annotations

import pandas as pd

from stocks import obs
from stocks.analysis.history import PERIODS, bars_download, shape
from stocks.api.cache import carried, ttl_cache
from stocks.api.loaders.keys import _PRICES_TTL
from stocks.frames import midnights

# Ranges and quotes move all day; a company's calendar does not. The ttls below
# mirror what the Ticker page uses for the same loads.
_HISTORY_TTL = 300.0
_EVENTS_TTL = 3600.0


@ttl_cache(_HISTORY_TTL, max_entries=64, persist="bars", disk_max=64)
def _bars_download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return bars_download(ticker, period, interval)


def price_bars(ticker: str, label: str) -> pd.DataFrame:
    """OHLCV plus indicators for one range label, shaped by `analysis.history`.

    The memo is on the download, not the label: the four daily labels under a
    year are one 2y frame cut four ways, and keying by label fetched it four
    times as a reader flipped through them.
    """
    period, interval = PERIODS[label]
    return shape(_bars_download(ticker, period, interval), label)


price_bars.cache_clear = _bars_download.cache_clear  # ty: ignore[unresolved-attribute]


def bar_closes(ticker: str, label: str) -> pd.Series:
    """Adjusted daily closes behind `label`, untrimmed — its whole download.

    The comparison card reads other listings at the subject's first day, which
    can sit a session before their own trimmed window opens. Same memo as
    `price_bars`, so a name the reader also charts costs nothing more.
    """
    period, interval = PERIODS[label]
    df = _bars_download(ticker, period, interval)
    if df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    return df["Close"]


def daily_bars(ticker: str) -> pd.DataFrame:
    """The chart's 2y daily OHLCV download, untrimmed, index made tz-naive.

    The trend read needs the year before the chart's window too (a 12-month
    momentum, a rising 200-session average), and this is the frame the 1y
    chart was cut from — the same memo entry, so no second download.
    """
    df = _bars_download(ticker, "2y", "1d")
    if df is None or df.empty:
        return pd.DataFrame()
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        df = df.copy()
        df.index = index.tz_localize(None)
    return df


# The review's return columns: a book of 150 names would evict every chart
# the ticker pages keep warm in `_bars_download`'s 64 entries, and needs five
# closes of each, not five years. So the download is its own and only the
# closes on the days a window opens or ends are kept.
@ttl_cache(_PRICES_TTL, max_entries=512)
def window_closes(ticker: str, days: str) -> pd.Series:
    """Adjusted close in the listing's own money on each of `days` (ISO,
    comma-separated — `analysis.compare.window_axis`): the last close on or
    before each, NaN before the listing's history."""
    from stocks.analysis.compare import on_axis
    from stocks.data.fetch import fetch_history

    df = fetch_history(ticker, period="5y", interval="1d")
    if df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    return on_axis(df["Close"], pd.DatetimeIndex(days.split(",")))


@ttl_cache(_PRICES_TTL, max_entries=32)
def spot_rates(ccys: tuple[str, ...], base: str = "EUR") -> dict[str, float]:
    """{currency: native->`base` spot} for the currencies a book trades in.

    Every money figure here is computed *in* the reporting currency, so
    dividing one back by its rate is how a share price gets quoted in the
    currency its market quotes it in. Pairs whose lookup fails are absent —
    the caller prints nothing rather than a dollar figure under a euro sign.
    """
    from concurrent.futures import ThreadPoolExecutor

    from stocks.data.fx import spot

    def rate(ccy: str) -> float | None:
        if str(ccy).upper() == base.upper():
            return 1.0
        with obs.swallow("fx.spot", ccy=ccy, base=base):
            return float(spot(ccy, base)[0])
        return None

    # One request per pair, side by side: a book in six currencies waited for
    # six round trips in a row on every cold Posiciones load.
    unique = list(dict.fromkeys(ccys))
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(unique), 8)) as pool:
        rates = list(pool.map(carried(rate), unique))
    return {ccy: r for ccy, r in zip(unique, rates, strict=True) if r is not None}


def daily_closes(ticker: str, period: str = "max") -> pd.Series:
    """Daily closes over `period` off the shared bar download, or empty."""
    try:
        df = _bars_download(ticker, period, "1d")
    except Exception as exc:
        obs.warn(
            "api.daily_closes_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return pd.Series(dtype=float)
    if df is None or df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    close.index = midnights(pd.DatetimeIndex(close.index).tz_localize(None))
    return close[~close.index.duplicated(keep="last")]
