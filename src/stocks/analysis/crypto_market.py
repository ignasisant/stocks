"""How a coin is read when there are no accounts to read: cycle, crowd, supply.

A share is anchored by what the company earns. A coin has no such anchor, so
the figures that stand in for one are about *where in its cycle* the price
sits and *how crowded* the trade is:

* **Distance from the all-time high.** A coin 60% under its peak is the normal
  state of the asset, not a tail event — the line a crypto reader looks at
  first, where a share reader looks at the P/E.
* **Mayer multiple and the 200-week average.** Price against its 200-day
  average (Trace Mayer's 2.4 marked every prior blow-off top) and against the
  200-week one (which prior bear markets bottomed near). Both are cycle
  *context*, not forecasts, and the copy says so.
* **Realised volatility**, annualised over a 365-day year: a coin trades every
  day of it.
* **Strength against bitcoin.** An altcoin that rose 20% while bitcoin rose
  40% lost ground; the base currency hides that.
* **Funding.** What longs pay shorts on a perpetual swap every few hours. The
  exchanges' resting rate is 0.01% per eight hours; well above it is leverage
  piling in on one side.
* **Supply.** How much of the eventual supply is already out, and the fully
  diluted value against today's — a token with most of its supply still to
  unlock carries the dilution in its price.

Every band below is coloured the way the RSI already is on this page
(`analysis.fundamentals`, oversold green, overbought red): stretched to the
downside reads green, stretched to the upside red. The tone marks where a
figure sits in its own history; it is not advice to buy or sell.

Pure: series and numbers in, numbers and band keys out. No fetch, no cache.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from stocks.data.crypto import HALVINGS, NEXT_HALVING_EST

# A coin trades every day of the year.
YEAR_DAYS = 365

# The exchanges' resting funding rate per eight hours (0.01%): the interest
# component alone, what a perpetual pays when longs and shorts are balanced.
FUNDING_BASE_8H = 0.0001


@dataclass(frozen=True)
class Band:
    """A figure's band key (an i18n suffix) and its tone."""

    key: str
    tone: str


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _closes(close: pd.Series) -> pd.Series:
    out = pd.to_numeric(close, errors="coerce").dropna()
    return out[out > 0]


# ----------------------------------------------------------------- the price


def from_peak(price: float | None, peak: float | None) -> float | None:
    """The price against its all-time high as a fraction (-0.62 = 62% under).

    Zero, never positive, when the price is above the peak it is measured
    against: that peak is a night old, and the coin has set a new one since.
    """
    price, peak = _finite(price), _finite(peak)
    if price is None or peak is None or price <= 0 or peak <= 0:
        return None
    return min(0.0, price / peak - 1.0)


def realized_vol(close: pd.Series, days: int = 30) -> float | None:
    """Annualised standard deviation of daily log returns over `days`."""
    series = _closes(close)
    if len(series) < days + 1:
        return None
    returns = (series.tail(days + 1).apply(math.log)).diff().dropna()
    if len(returns) < 2:
        return None
    return float(returns.std(ddof=1) * math.sqrt(YEAR_DAYS))


def mayer_multiple(close: pd.Series) -> float | None:
    """Last close over the 200-day simple average; None under 200 closes."""
    series = _closes(close)
    if len(series) < 200:
        return None
    return float(series.iloc[-1] / series.tail(200).mean())


def ratio_200w(close: pd.Series) -> float | None:
    """Last close over the 200-WEEK simple average of weekly closes.

    Weekly closes rather than 1,400 daily ones: the average this line is
    known by is drawn on a weekly chart, and the two differ by a weekend's
    weight. None with fewer than 200 weeks of history.
    """
    series = _closes(close)
    if series.empty or not isinstance(series.index, pd.DatetimeIndex):
        return None
    weekly = series.resample("W").last().dropna()
    if len(weekly) < 200:
        return None
    return float(series.iloc[-1] / weekly.tail(200).mean())


def relative_return(
    asset: pd.Series, against: pd.Series, days: int = 90
) -> float | None:
    """How much `asset` beat (+) or lagged (-) `against` over `days`.

    A ratio of growths, not a difference of returns: +40% against +20% is
    (1.4 / 1.2) - 1 = +16.7%, what holding one instead of the other made.
    Both are read off the same calendar span ending at the later of the two
    last dates they share.
    """
    a, b = _closes(asset), _closes(against)
    if a.empty or b.empty:
        return None
    a.index = pd.DatetimeIndex(a.index).normalize()
    b.index = pd.DatetimeIndex(b.index).normalize()
    shared = a.index.intersection(b.index)
    if len(shared) < 2:
        return None
    end = shared.max()
    start = end - pd.Timedelta(days=days)
    window = shared[shared >= start]
    if len(window) < 2 or (window.min() - start).days > 7:
        return None
    first = window.min()
    grow_a = a.loc[end] / a.loc[first]
    grow_b = b.loc[end] / b.loc[first]
    if isinstance(grow_a, pd.Series) or isinstance(grow_b, pd.Series):
        return None
    return float(grow_a / grow_b - 1.0)


# ----------------------------------------------------------------- the cycle


@dataclass(frozen=True)
class Halving:
    last: str
    days_since: int
    next_est: str
    days_to_next: int
    # Share of the way from the last halving to the next one, 0..1.
    progress: float


def halving_phase(today: date | None = None) -> Halving | None:
    """Where today sits between bitcoin's last halving and the next one."""
    day = today or date.today()
    past = [date.fromisoformat(d) for d in HALVINGS if date.fromisoformat(d) <= day]
    if not past:
        return None
    last = past[-1]
    upcoming = date.fromisoformat(NEXT_HALVING_EST)
    span = max(1, (upcoming - last).days)
    since = (day - last).days
    return Halving(
        last=last.isoformat(),
        days_since=since,
        next_est=upcoming.isoformat(),
        days_to_next=max(0, (upcoming - day).days),
        progress=min(1.0, max(0.0, since / span)),
    )


# ------------------------------------------------------------------ the bands


def mayer_band(value: float | None) -> Band | None:
    """Mayer's own reading: under 0.8 has marked prior bottoms, over 2.4 tops."""
    if value is None:
        return None
    if value < 0.8:
        return Band("deep", "green")
    if value < 1.0:
        return Band("below", "gray")
    if value < 2.4:
        return Band("normal", "gray")
    return Band("stretched", "red")


def ratio_200w_band(value: float | None) -> Band | None:
    """Under the 200-week average is rare and has been bear-market territory."""
    if value is None:
        return None
    if value < 1.0:
        return Band("under", "green")
    if value < 2.5:
        return Band("over", "gray")
    return Band("far_over", "orange")


def fear_greed_band(value: float | None) -> Band | None:
    """alternative.me's own five bands, in this page's contrarian colours."""
    if value is None:
        return None
    if value < 25:
        return Band("extreme_fear", "green")
    if value < 45:
        return Band("fear", "gray")
    if value <= 55:
        return Band("neutral", "gray")
    if value <= 75:
        return Band("greed", "orange")
    return Band("extreme_greed", "red")


def per_8h(rate: float | None, interval_hours: float | None) -> float | None:
    """A funding rate restated per eight hours, the interval it is quoted in.

    Some perpetuals settle every four hours, or every hour: their rate is a
    fraction of the eight-hour one and reads as calm when it is not.
    """
    rate = _finite(rate)
    hours = _finite(interval_hours) or 8.0
    if rate is None or hours <= 0:
        return None
    return rate * 8.0 / hours


def annualized_funding(rate_8h: float | None) -> float | None:
    """What a long paid over a year at this rate: three settlements a day."""
    return None if rate_8h is None else rate_8h * 3 * YEAR_DAYS


def funding_band(rate_8h: float | None) -> Band | None:
    """Funding per eight hours against the 0.01% resting rate.

    Negative is shorts paying longs — the crowd leaning bearish. Up to 1.5x
    the resting rate is balanced; up to five times it, longs paying up; past
    that, the leverage that has preceded the sharpest flushes.
    """
    if rate_8h is None:
        return None
    if rate_8h < 0:
        return Band("negative", "green")
    if rate_8h <= FUNDING_BASE_8H * 1.5:
        return Band("neutral", "gray")
    if rate_8h <= FUNDING_BASE_8H * 5:
        return Band("hot", "orange")
    return Band("extreme", "red")


# ----------------------------------------------------------------- the supply


def issued_share(circulating: float | None, maximum: float | None) -> float | None:
    """Circulating supply as a share of the hard cap; None for an uncapped coin."""
    circulating, maximum = _finite(circulating), _finite(maximum)
    if circulating is None or maximum is None or maximum <= 0:
        return None
    return min(1.0, circulating / maximum)


def fdv_ratio(fdv: float | None, market_cap: float | None) -> float | None:
    """Fully diluted value over market cap: 1.0 is everything already out."""
    fdv, market_cap = _finite(fdv), _finite(market_cap)
    if fdv is None or market_cap is None or market_cap <= 0 or fdv <= 0:
        return None
    return fdv / market_cap


def dilution_band(ratio: float | None) -> Band | None:
    """Supply still to come, priced in: over 1.5x is a third or more unlocked
    later, and every unlock is supply the market has to absorb."""
    if ratio is None:
        return None
    if ratio <= 1.1:
        return Band("none", "gray")
    if ratio <= 1.5:
        return Band("some", "gray")
    return Band("heavy", "orange")
