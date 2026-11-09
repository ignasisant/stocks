"""Pure statistics over price/return frames and a weights dict: weighting,
returns and risk, concentration. No network.
"""

from __future__ import annotations

import math
from typing import cast

import pandas as pd

from stocks.config import Holding
from stocks.data.crypto import is_crypto
from stocks.frames import naive_dates

TRADING_DAYS = 252


def equal_weights(tickers: list[str]) -> dict[str, float]:
    n = len(tickers)
    return {t: 1 / n for t in tickers} if n else {}


def market_value_weights(
    shares: dict[str, float], prices: dict[str, float]
) -> dict[str, float]:
    """Weights proportional to shares * price. Tickers without a price drop out."""
    values = {t: shares[t] * prices[t] for t in shares if prices.get(t)}
    total = sum(values.values())
    return {t: v / total for t, v in values.items()} if total else {}


def weights_from_holdings(
    holdings: list[Holding], prices: dict[str, float]
) -> dict[str, float]:
    """Market-value weights over real positions, else equal-weight watchlist."""
    positions = {h.ticker: h.shares for h in holdings if h.is_position}
    if positions:
        return market_value_weights(positions, prices)
    return equal_weights([h.ticker for h in holdings])


def returns_frame(closes: dict[str, pd.Series]) -> pd.DataFrame:
    """Daily simple returns, tickers as columns, aligned on the date index."""
    px = pd.DataFrame({t: s for t, s in closes.items() if s is not None})
    return px.pct_change().iloc[1:]


def portfolio_returns(
    returns: pd.DataFrame,
    weights: dict[str, float],
    since: dict[str, pd.Timestamp] | None = None,
) -> pd.Series:
    """Daily portfolio return, weights renormalised per date over tickers with data.

    Tickers with shorter histories (recent IPOs) contribute only from their first
    quote; earlier dates redistribute their weight over the rest of the book
    instead of truncating the whole series to the common history.

    `since` masks a ticker's return before its own date to missing, the same
    way a short price history does — a name bought last month at today's
    weight otherwise backdates that whole weight onto years it was never
    held, and earns a rally the book never lived.
    """
    cols = [c for c in returns.columns if c in weights and weights[c]]
    if not cols:
        return pd.Series(dtype=float)
    r = returns[cols].dropna(how="all")
    if since:
        r = r.copy()
        naive = naive_dates(r.index)
        for c in cols:
            start = since.get(c)
            if start is not None:
                r.loc[naive < start, c] = float("nan")
    w = pd.Series({c: weights[c] for c in cols})
    present = r.notna().mul(w, axis=1).sum(axis=1)
    port = r.fillna(0.0).mul(w, axis=1).sum(axis=1) / present
    return port[present > 0]


def samples_per_year(returns: pd.Series, default: int = TRADING_DAYS) -> float:
    """How many of these samples a year holds, read off the index.

    Both annualisers below used to assume 252 — right for a series taken off
    closes, wrong for the one the book's own return is measured on. The TWR is
    sampled on a *calendar* day (`shares_frame` reindexes to every date so a
    flow lands on the day it happened), so a year of it is 365 samples, and
    annualising it at 252 understated a real book's return by seven points:
    +15.0% printed where +22.4% was earned. Reading the span instead of taking
    a constant means neither caller has to remember which kind it holds.
    """
    index = getattr(returns, "index", None)
    if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
        span = (index[-1] - index[0]).days
        if span > 0:
            return len(index) * 365.25 / span
    return float(default)


def annualized_volatility(returns: pd.Series, periods: float | None = None) -> float:
    """Annualised standard deviation. `periods` defaults to the index's own."""
    if returns.empty:
        return float("nan")
    per = samples_per_year(returns) if periods is None else periods
    return float(returns.std(ddof=0) * per**0.5)


def annualized_return(returns: pd.Series, periods: float | None = None) -> float:
    """Geometric annualised return from a daily-return series."""
    n = len(returns)
    if n == 0:
        return float("nan")
    growth = float((1 + returns).prod())
    if growth <= 0:
        return float("nan")
    per = samples_per_year(returns) if periods is None else periods
    return growth ** (per / n) - 1


def beta(asset: pd.Series, benchmark: pd.Series) -> float:
    """Population beta of asset vs benchmark on their common dates."""
    df = pd.concat([asset, benchmark], axis=1, sort=True).dropna()
    if len(df) < 2:
        return float("nan")
    a, b = df.iloc[:, 0], df.iloc[:, 1]
    var = ((b - b.mean()) ** 2).mean()
    if not var:
        return float("nan")
    cov = ((a - a.mean()) * (b - b.mean())).mean()
    return float(cov / var)


def max_drawdown(prices: pd.Series) -> float:
    """Worst peak-to-trough decline over the series (<= 0)."""
    prices = prices.dropna()
    if prices.empty:
        return float("nan")
    return float((prices / prices.cummax() - 1).min())


def drawdown_span(prices: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """(peak, trough) dates of `max_drawdown`'s fall; None when it never fell.

    A drawdown alone does not say *when*, and on a TWR path that matters: every
    day weighs the same whatever the book held, so a fall taken while it was a
    few hundred euros of two names reads as large as one on today's book.
    """
    prices = prices.dropna()
    if prices.empty:
        return None
    dd = prices / prices.cummax() - 1
    if not (dd < 0).any():
        return None
    trough = dd.idxmin()
    return cast(pd.Timestamp, prices[:trough].idxmax()), cast(pd.Timestamp, trough)


def cumulative_returns(returns: pd.Series) -> pd.Series:
    """Cumulative growth path from daily returns (starts near 0)."""
    return (1 + returns).cumprod() - 1


# Days a daily-return series needs before its tail says anything. The 5th
# percentile of fifteen days is the worst one; of a hundred it is a reading.
MIN_VAR_DAYS = 60


def historical_var(returns: pd.Series, level: float = 0.95) -> float:
    """One-day historical value at risk: the daily return that `level` of the
    series' days beat, as a return (<= 0 on any book that ever fell).

    Historical, not parametric: the empirical quantile of the days as they
    were, so a fat left tail counts as it happened rather than as a normal
    curve would smooth it. NaN under `MIN_VAR_DAYS` days — a quantile of a
    handful of days is one of those days, not a risk figure.
    """
    returns = returns.dropna()
    if len(returns) < MIN_VAR_DAYS:
        return float("nan")
    return float(returns.quantile(1 - level, interpolation="linear"))


# A pair needs this many shared days to be compared: a coin listed last week
# otherwise "diversifies" the book on three data points.
MIN_CORR_DAYS = 30


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr(min_periods=MIN_CORR_DAYS)


def risk_shares(
    returns: pd.DataFrame, port: pd.Series, weights: dict[str, float]
) -> dict[str, float]:
    """Each name's share of the basket's variance: w·cov(name, basket) / var.

    The Euler split of portfolio risk — a name that moves with the rest
    carries more of it than its weight, a diversifier less (below zero when it
    hedges). Normalised over the names it can measure, so the shares sum to
    one even where the basket renormalised weights over a short history.
    """
    raw: dict[str, float] = {}
    for name, weight in weights.items():
        if not weight or name not in returns:
            continue
        pair = pd.concat([returns[name], port], axis=1, sort=True).dropna()
        if len(pair) < 2:
            continue
        cov = float(pair.cov(ddof=0).iloc[0, 1])
        if math.isfinite(cov):
            raw[name] = weight * cov
    total = sum(raw.values())
    if not total:
        return {}
    return {name: value / total for name, value in raw.items()}


def hhi(weights: dict[str, float]) -> float:
    """Herfindahl-Hirschman index (sum of squared weights); 1.0 = single name."""
    return float(sum(w**2 for w in weights.values()))


def effective_positions(weights: dict[str, float]) -> float:
    """1 / HHI — how many equal-sized names the book behaves like."""
    h = hhi(weights)
    return float(1 / h) if h else float("nan")


def top_n_weight(weights: dict[str, float], n: int = 5) -> float:
    return float(sum(sorted(weights.values(), reverse=True)[:n]))


def allocation(weights: dict[str, float], meta: dict[str, dict], key: str) -> pd.Series:
    """Sum weights grouped by a metadata field ('sector' | 'country' | 'currency').

    A fund carries a *split* instead of one label: `meta[ticker]["<key>_weights"]`
    maps bucket -> fraction of that holding (see `_profile`), and the holding's
    weight is spread across them. That look-through is the difference between
    "38% Unknown" and a sector pie that reads the book as it actually is — an
    S&P 500 ETF next to four tech names is mostly one bet, and only the split
    shows it. Fractions that don't sum to 1 (Yahoo rounding, an undisclosed
    remainder) leave the missing part in "Unknown" rather than being scaled up.
    """
    agg = {
        label: sum(parts.values())
        for label, parts in allocation_parts(weights, meta, key).items()
    }
    return pd.Series(agg, dtype=float).sort_values(ascending=False)


def allocation_parts(
    amounts: dict[str, float], meta: dict[str, dict], key: str
) -> dict[str, dict[str, float]]:
    """`allocation` before the sum: each bucket's amount, by the ticker it came from.

    Linear in `amounts`, so the same grouping takes weights, market values or
    cost bases alike — a fund's value and its cost are spread over its split
    by the same fractions, and a bucket's P/L is then like-for-like. The
    per-ticker detail is what lets a slice say which holdings it is made of.
    """
    parts: dict[str, dict[str, float]] = {}

    def add(label: str, ticker: str, amount: float) -> None:
        bucket = parts.setdefault(label, {})
        bucket[ticker] = bucket.get(ticker, 0.0) + amount

    for ticker, amount in amounts.items():
        row = meta.get(ticker) or {}
        if split := row.get(f"{key}_weights"):
            for label, share in split.items():
                add(label, ticker, amount * share)
            if (rest := 1.0 - sum(split.values())) > 0.001:
                add("Unknown", ticker, amount * rest)
            continue
        # A coin has no country: its own bucket, not "Unknown" (a data gap).
        none = "Crypto" if key == "country" and is_crypto(ticker) else "Unknown"
        add(row.get(key) or none, ticker, amount)
    return parts


def position_table(holdings: list[Holding], prices: dict[str, float]) -> pd.DataFrame:
    """Value and unrealised P/L per real position (shares > 0)."""
    rows = []
    for h in holdings:
        if not h.is_position:
            continue
        price = prices.get(h.ticker)
        value = h.shares * price if price else None
        pnl = pnl_pct = None
        if price and h.cost and value is not None:
            basis = h.shares * h.cost
            pnl = value - basis
            pnl_pct = value / basis - 1 if basis else None
        rows.append(
            {
                "ticker": h.ticker,
                "shares": h.shares,
                "cost": h.cost,
                "price": price,
                "value": value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()
