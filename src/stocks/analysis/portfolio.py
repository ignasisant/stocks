"""Portfolio analytics: allocation, concentration, risk, benchmarking.

Two layers:
  * pure functions over price/return frames and a weights dict — run offline,
    fully unit-tested;
  * a thin network layer (load_closes / load_meta / analyze) that pulls prices
    and profile data via yfinance and assembles a PortfolioReport.

Weighting: if any watchlist entry has `shares > 0`, the book is weighted by
market value across those positions; otherwise the whole watchlist is
equal-weighted so the risk/correlation view still works before you enter sizes.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC
from typing import TYPE_CHECKING

import pandas as pd

from stocks import obs
from stocks.analysis import naive_dates
from stocks.analysis.listing import price_units, quote_unit
from stocks.config import Holding, load_watchlist
from stocks.data.fx import ToBase, converter
from stocks.portfolio import transfers

if TYPE_CHECKING:
    from datetime import datetime

TRADING_DAYS = 252
# Default benchmarks: US large-cap, US tech, emerging markets.
DEFAULT_BENCHMARKS = ("SPY", "QQQ", "EEM")
# All three are US-listed and quoted in dollars. Named rather than assumed
# because a reader in another currency does not hold the index, they hold the
# index and the dollar — see `rebase_returns`.
BENCHMARK_CCY = "USD"


# ----------------------------------------------------------------- weighting
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


# ----------------------------------------------------------------- returns
def returns_frame(closes: dict[str, pd.Series]) -> pd.DataFrame:
    """Daily simple returns, tickers as columns, aligned on the date index."""
    px = pd.DataFrame({t: s for t, s in closes.items() if s is not None})
    return px.pct_change().iloc[1:]


def portfolio_returns(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Daily portfolio return, weights renormalised per date over tickers with data.

    Tickers with shorter histories (recent IPOs) contribute only from their first
    quote; earlier dates redistribute their weight over the rest of the book
    instead of truncating the whole series to the common history.
    """
    cols = [c for c in returns.columns if c in weights and weights[c]]
    if not cols:
        return pd.Series(dtype=float)
    r = returns[cols].dropna(how="all")
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
    df = pd.concat([asset, benchmark], axis=1).dropna()
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


def cumulative_returns(returns: pd.Series) -> pd.Series:
    """Cumulative growth path from daily returns (starts near 0)."""
    return (1 + returns).cumprod() - 1


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr()


# ----------------------------------------------------------------- concentration
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
    agg: dict[str, float] = {}
    for ticker, w in weights.items():
        row = meta.get(ticker) or {}
        if split := row.get(f"{key}_weights"):
            for label, share in split.items():
                agg[label] = agg.get(label, 0.0) + w * share
            if (rest := 1.0 - sum(split.values())) > 0.001:
                agg["Unknown"] = agg.get("Unknown", 0.0) + w * rest
            continue
        label = row.get(key) or "Unknown"
        agg[label] = agg.get(label, 0.0) + w
    return pd.Series(agg, dtype=float).sort_values(ascending=False)


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


# ------------------------------------------------------------ injected vs value
# (amount, currency, iso_date) -> the reporting currency, injectable so tests
# skip the network. The live one is stocks.data.fx.converter(base).
ToBaseFn = ToBase | None


def shares_frame(transactions, end: str | None = None) -> pd.DataFrame:
    """Daily shares held per ticker, replaying buys/sells in ledger order.

    Split-adjusted throughout: price history is back-adjusted, so a trade's
    quantity is scaled by every split that came after it and the split itself
    is not a step in the path. Stepping shares up on the split date instead
    would leave the pre-split stretch valued at post-split prices — the
    position reads ~1/ratio of its real size and its buys look like instant
    losses in the flow-adjusted return.

    Calendar-daily index from the first transaction to `end` (default today),
    forward-filled between events; 0 before a ticker's first buy. Moving shares
    between brokers changes no share count, so a matched pair of transfer legs
    nets out before the replay and only an unmatched arrival steps the path
    (see stocks.portfolio.transfers).
    """
    txs = sorted(transfers.normalize(transactions), key=lambda t: (t.date, t.id or 0))
    if not txs:
        return pd.DataFrame()
    splits: dict[str, list[tuple[str, float]]] = {}
    for t in txs:
        if t.action == "split" and t.quantity > 0:
            splits.setdefault(t.ticker, []).append((t.date, t.quantity))

    def adjusted(t) -> float:
        """Quantity in today's shares: splits strictly after the trade date.
        A split shares its date with post-split trades, which need no scaling."""
        return t.quantity * math.prod(
            ratio for day, ratio in splits.get(t.ticker, ()) if day > t.date
        )

    qty: dict[str, float] = {}
    snap: dict[str, dict[str, float]] = {}
    for t in txs:
        if t.action == "buy":
            qty[t.ticker] = qty.get(t.ticker, 0.0) + adjusted(t)
        elif t.action == "sell":
            qty[t.ticker] = qty.get(t.ticker, 0.0) - adjusted(t)
        else:
            continue
        snap.setdefault(t.date, {})[t.ticker] = qty[t.ticker]
    frame = pd.DataFrame.from_dict(snap, orient="index").sort_index()
    frame.index = pd.to_datetime(frame.index)
    idx = pd.date_range(frame.index[0], end or pd.Timestamp.today().normalize(), freq="D")
    return frame.reindex(idx).ffill().fillna(0.0).clip(lower=0.0)


def injected_series(
    transactions, to_base: ToBaseFn = None, base: str = "EUR"
) -> pd.Series:
    """Cumulative net cash put in, in `base` at each transaction date's rate.

    Buys add cost incl. commission; sells subtract net proceeds. Dividends and
    standalone fees don't move contributed capital, and neither does a transfer
    between brokers — only shares arriving from a book that never held them
    count, at the basis their statement reports. Index = transaction dates.
    """
    to_base = to_base or converter(base)
    flows: dict[str, float] = {}
    for t in sorted(transfers.normalize(transactions), key=lambda t: (t.date, t.id or 0)):
        if t.action == "buy":
            amt = to_base(t.quantity * t.price + t.fee, t.currency, t.date)
        elif t.action == "sell":
            amt = -to_base(t.quantity * t.price - t.fee, t.currency, t.date)
        else:
            continue
        flows[t.date] = flows.get(t.date, 0.0) + amt
    if not flows:
        return pd.Series(dtype=float)
    s = pd.Series(flows).sort_index()
    s.index = pd.to_datetime(s.index)
    return s.cumsum()


def injected_vs_value(
    transactions,
    closes: dict[str, pd.Series],
    fx: dict[str, pd.Series] | None = None,
    to_base: ToBaseFn = None,
    base: str = "EUR",
    units: dict[str, tuple[str, float]] | None = None,
) -> pd.DataFrame:
    """Daily injected capital vs mark-to-market value of the book, in `base`.

    `closes` = native-currency close series per ticker; `fx` = daily
    currency->`base` rate series (the base currency itself implied 1.0).
    `units` = ticker -> (ISO currency, scale) each close series is quoted in
    (stocks.analysis.listing.price_units); a ticker missing from it is taken
    to be quoted in its ledger rows' currency. The distinction is the whole
    point: an alias can price a dollar trade off a euro listing, and the close
    converts at the listing's rate — the trade currency only converts the
    cash, in `injected_series`. `fx` must carry every currency `units` names. Held
    days without a usable close/FX quote — ticker absent, delisted mid-hold, or
    (like a delisted ORGN) a stray quote outside the holding window — are
    carried at cost (cumulative net invested): no fake loss, no mark-to-market
    either.
    Columns: injected, value, pnl_pct. Tickers ever carried at cost
    while held are listed in df.attrs['carried_at_cost'].

    `base` is the reporting currency and is read, not assumed: this used to
    test each holding's currency against a literal "EUR", which for a book
    reported in anything else valued its own base-currency names at a rate of
    1.0 and left every *other* name without a series — carried at cost, flat,
    and listed as unpriced. A USD book of two names both up 20% read +4.8%.
    """
    shares = shares_frame(transactions)
    if shares.empty:
        return pd.DataFrame()
    idx = shares.index
    fx = fx or {}
    base = base.upper()
    # Normalised like `shares_frame` above, and for the same reason: a holding
    # that only ever arrived — an opening snapshot, shares moved in kind — has
    # no trade row to read a currency from, and falling back to the base
    # prices a USD position as if its closes were already in EUR.
    ccy_of = {
        t.ticker: t.currency
        for t in transfers.normalize(transactions)
        if t.action in ("buy", "sell")
    }
    units = units or {}

    value = pd.Series(0.0, index=idx)
    carried: list[str] = []
    for ticker in shares.columns:
        held = shares[ticker] > 0
        mtm = None
        px = closes.get(ticker)
        if px is not None and not px.empty:
            px = px.copy()
            px.index = naive_dates(px.index)
            px = px.reindex(idx).ffill()
            ccy, scale = units.get(ticker) or ((ccy_of.get(ticker) or base), 1.0)
            ccy = ccy.upper()
            px = px * scale
            if ccy == base:
                rate = pd.Series(1.0, index=idx)
            else:
                rate = fx.get(ccy)
            if rate is not None:
                rate = rate.copy()
                rate.index = pd.to_datetime(rate.index)
                rate = rate.reindex(idx).ffill().bfill()
                mtm = shares[ticker] * px * rate
        # Held days with no quote fall back to cost, never below zero.
        gap = held if mtm is None else (mtm.isna() & held)
        if gap.any():
            proxy = injected_series(
                [t for t in transactions if t.ticker == ticker], to_base, base
            ).reindex(idx).ffill().fillna(0.0)
            value += proxy.where(gap, 0.0).clip(lower=0.0)
            carried.append(ticker)
        if mtm is not None:
            value += mtm.fillna(0.0)

    injected = (
        injected_series(transactions, to_base, base).reindex(idx).ffill().fillna(0.0)
    )
    pct = pd.Series(float("nan"), index=idx)
    mask = injected > 0
    pct[mask] = value[mask] / injected[mask] - 1
    df = pd.DataFrame({"injected": injected, "value": value, "pnl_pct": pct})
    df.attrs["carried_at_cost"] = carried
    return df


def flow_series(
    transactions,
    to_base: ToBaseFn = None,
    tickers: set[str] | None = None,
    base: str = "EUR",
) -> pd.Series:
    """Net external cash flow per date in `base`: buys +, sells −.

    A dividend is deliberately NOT a flow here, and that is the opposite of
    what the textbook says — because the value path these flows are measured
    against is not a textbook one. `load_closes` fetches `auto_adjust=True`
    bars, so every close before an ex-date is scaled down by that dividend:
    the series is already a total return, and the payment shows up in it as a
    drop that never happens rather than as cash leaving. Counting it as a
    withdrawal on top credited it twice — measured on a real book, a KO close
    six months back sits 1.25% under its traded price, and a year of that is a
    year of return nobody earned. A broker transfer is not cash at
    all: matched legs net out (stocks.portfolio.transfers) so the
    return is untouched by the move, and an unmatched arrival reads as the
    contribution it is. Leave `tickers` unset when
    the value path carries unpriced names at cost (injected_vs_value); only
    restrict it when those names are absent from the value entirely, otherwise
    their buys read as instant losses in the TWR.
    """
    to_base = to_base or converter(base)
    flows: dict[str, float] = {}
    for t in transfers.normalize(transactions):
        if tickers is not None and t.ticker not in tickers:
            continue
        if t.action == "buy":
            amt = to_base(t.quantity * t.price + t.fee, t.currency, t.date)
        elif t.action == "sell":
            amt = -to_base(t.quantity * t.price - t.fee, t.currency, t.date)
        else:
            continue
        flows[t.date] = flows.get(t.date, 0.0) + amt
    s = pd.Series(flows, dtype=float).sort_index()
    s.index = pd.to_datetime(s.index)
    return s


def time_weighted_returns(value: pd.Series, flows: pd.Series) -> pd.Series:
    """Daily time-weighted returns from a value path and external flows.

    r_t = (V_t - F_t) / V_{t-1} - 1, flows treated as arriving at day-t close.
    Days with no prior value (before the first buy, or after the book was
    emptied) drop out; performance is unaffected by deposit/withdrawal timing.

    Days pricing below -100% also drop out, their dates listed in
    .attrs['dropped_days']: a long-only book cannot lose more than everything,
    so r <= -1 means the day's flow never landed in the value path (an
    unrecorded split, a corporate action, a ticker with no history). One such
    sample drives the cumulative path negative and takes the annualised
    return, volatility and drawdown down with it.
    """
    if value.empty:
        return pd.Series(dtype=float)
    f = flows.reindex(value.index, fill_value=0.0) if not flows.empty else 0.0
    prev = value.shift(1)
    r = (value - f) / prev - 1
    r = r[prev > 1e-9]
    impossible = r.index[r <= -1]
    if len(impossible):
        r = r.drop(impossible)
    r.attrs["dropped_days"] = list(impossible)
    return r


def money_weighted_return(
    value: pd.Series, flows: pd.Series, start: pd.Timestamp | None = None
) -> float:
    """Annualised money-weighted return (IRR) of the book over [start, end].

    Investor cash flows: the book's value at the window start counts as the
    buy-in, every external flow inside the window lands on its date (`flows`
    uses the flow_series convention — buys +, sells/dividends −), and the
    final value is the terminal payoff. Unlike the TWR, deposit/withdrawal
    *timing* moves this number: it answers "how did my money do", not "how
    did the strategy do". `start` before the first value falls back to the
    full history. NaN when the window is empty, has no time span, or no rate
    in (-99.99%, 1000%) prices the flows to zero.
    """
    value = value.dropna()
    if value.empty:
        return float("nan")
    if start is not None:
        clipped = value[value.index >= start]
        if not clipped.empty:
            value = clipped
    t0, t_end = value.index[0], value.index[-1]
    years = (t_end - t0).days / 365.25
    if years <= 0:
        return float("nan")
    # Flows arrive at day-t close (time_weighted_returns convention), so the
    # opening value already contains any day-t0 flow; count strictly later ones.
    cash = [(0.0, -float(value.iloc[0]))]
    if not flows.empty:
        inside = flows[(flows.index > t0) & (flows.index <= t_end)]
        cash += [((ts - t0).days / 365.25, -float(f)) for ts, f in inside.items()]
    cash.append((years, float(value.iloc[-1])))

    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** t for t, cf in cash)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if math.isnan(f_lo) or math.isnan(f_hi) or (f_lo > 0) == (f_hi > 0):
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        if (npv(mid) > 0) == (f_lo > 0):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ----------------------------------------------------------------- orchestration
@dataclass
class PortfolioReport:
    weights: dict[str, float]
    meta: dict[str, dict]
    returns: pd.DataFrame
    port_returns: pd.Series
    prices: dict[str, float] = field(default_factory=dict)
    bench_returns: dict[str, pd.Series] = field(default_factory=dict)
    # The download `returns` was taken from, kept so a caller that knows what
    # currency each name trades in can rebuild the returns on one footing
    # without paying for the prices twice (see `api.loaders.basket_report`).
    closes: dict[str, pd.Series] = field(default_factory=dict)

    @property
    def volatility(self) -> float:
        return annualized_volatility(self.port_returns)

    @property
    def cagr(self) -> float:
        return annualized_return(self.port_returns)

    @property
    def max_drawdown(self) -> float:
        return max_drawdown(cumulative_returns(self.port_returns) + 1)

    def beta_vs(self, benchmark: str) -> float:
        bench = self.bench_returns.get(benchmark)
        if bench is None:
            return float("nan")
        return beta(self.port_returns, bench)

    def allocation(self, key: str) -> pd.Series:
        return allocation(self.weights, self.meta, key)


def load_closes(
    tickers: list[str], period: str = "1y", adjusted: bool = True
) -> dict[str, pd.Series]:
    """Close series per ticker from ONE bulk download; no-data tickers drop out.

    Adjusted by default, which is what every *return* here is measured on: the
    series is then a total return and a dividend shows up as growth rather than
    as a drop nobody lost. `adjusted=False` keeps the prices as they printed —
    still split-corrected, because a 10-for-1 in the window would otherwise put
    the high ten times over the price. That is the one a 52-week edge wants: an
    adjusted high sits below the price that was actually paid, which quietly
    promotes a name to "at its high" that is nowhere near it.
    """
    # Imported here, not at module scope: this module is on the import chain of
    # every page (via web.portfolio_data), and pulling yfinance in costs ~150 ms
    # of a cold start for a dependency only the network functions below need.
    from stocks.data.fetch import fetch_many

    out: dict[str, pd.Series] = {}
    for t, df in fetch_many(tickers, period=period, auto_adjust=adjusted).items():
        s = df["Close"].dropna() if "Close" in df else pd.Series(dtype=float)
        if not s.empty:
            out[t] = s.rename(t)
    return out


# The actions that say the book held a security. A transfer leg is not a trade,
# but a holding that only ever arrived — an opening snapshot, shares moved from
# another broker — is held all the same, and every price series below exists to
# value what is held. Reading trades alone leaves those positions with no price
# series, no FX rate and no dividend history.
HELD_ACTIONS = ("buy", "sell", *transfers.TRANSFERS)


def book_history(
    transactions,
    base: str = "EUR",
    closes: dict[str, pd.Series] | None = None,
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Full-span daily history of one book: injected vs value, TWR, unpriced.

    The recipe every caller needs and nobody should assemble twice: relabel the
    ledger so a broker transfer is one position and not two, download (or reuse)
    a close series per held name, pull the daily FX path for every currency in
    the book, mark the value to market and take the flow-adjusted daily
    time-weighted returns of it.

    `closes` lets a caller hand in a price download it already holds — the web
    app shares one across the Home glance and the Portfolio page. Left out, the
    prices are fetched here, keyed on the ledger's own span.

    Returns (frame, twr, missing):

    * frame — columns injected/value/pnl_pct, indexed daily (injected_vs_value)
    * twr — daily time-weighted returns, flow-adjusted, so deposits and
      withdrawals do not read as performance
    * missing — held names with no usable price series, carried at cost in the
      value path. The caller has to disclose them: a total that quietly drops
      part of the book is a lie in smaller print.

    Relabelling matters before the ticker set is taken, not after: the download
    is keyed on the replay's label, and a DEGIRO→IBKR book asks for ISINs while
    it holds symbols, which prices nothing.
    """
    from datetime import date

    from stocks.data.fx import rates_range

    ledger = transfers.relabel(list(transactions))
    held = [t for t in ledger if t.action in HELD_ACTIONS]
    if not held:
        return pd.DataFrame(), pd.Series(dtype=float), []
    tickers = sorted({t.ticker for t in held})
    first = min(t.date for t in held)
    if closes is None:
        months = max(1, (pd.Timestamp.today() - pd.Timestamp(first)).days // 30 + 1)
        closes = load_closes(tickers, period=f"{months}mo")
    closes = {t: s for t, s in closes.items() if t in set(tickers)}
    # The closes convert at their listing's rate, the cash at the trade's —
    # so the FX paths are the union of both (stocks.analysis.listing).
    units = price_units(closes, {t.ticker: t.currency for t in held})
    fx = {
        ccy: pd.Series(rates_range(first, date.today().isoformat(), ccy, base))
        for ccy in {t.currency for t in held} | {u[0] for u in units.values()}
        if ccy != base
    }
    hist = injected_vs_value(ledger, closes, fx, base=base, units=units)
    if hist.empty:
        twr = pd.Series(dtype=float)
    else:
        # No ticker filter on the flows: unpriced names are carried at cost in
        # the value path, so their buys and sells must offset those value jumps.
        twr = time_weighted_returns(hist["value"], flow_series(ledger, base=base))
    missing = sorted(
        {t for t in tickers if t not in closes}
        | set(hist.attrs.get("carried_at_cost", []) if not hist.empty else [])
    )
    return hist, twr, missing



def _profile(ticker: str) -> dict:
    from stocks.data.crypto import split_pair
    from stocks.data.fetch import info as quote_info
    from stocks.data.funds import fetch_profile, remember, sector_split

    # Crypto pairs: yfinance has no sector/country for coins — label the
    # allocation bucket directly and skip the profile fetch.
    if pair := split_pair(ticker):
        return {"sector": "Crypto", "country": None, "currency": pair[1]}
    # Seen before: the four fields this needs never change, so a stock the
    # memo knows costs no request at all (data.profiles). Funds fall through —
    # their split is a look-through of holdings that `.info` alone lacks.
    from stocks.data.fetch import resolve
    from stocks.data.funds import is_fund_type
    from stocks.data.profiles import known

    stored = known(resolve(ticker))
    if stored and not is_fund_type(stored.get("quoteType")):
        remember(ticker, stored.get("quoteType"))
        return {
            "sector": stored.get("sector"),
            "country": stored.get("country"),
            "currency": stored.get("currency"),
        }
    try:
        info = quote_info(ticker)
    except Exception:
        info = {}
    remember(ticker, info.get("quoteType"))
    # A fund has no sector of its own; it has the sectors of what it holds.
    # `sector_split` turns that into the split `allocation` spreads the
    # position over, and the "Funds" label is only the fallback for a sleeve
    # with no equity sectors at all (a bond or commodity ETF). Country is left
    # unknown on purpose: Yahoo publishes no geographic breakdown for funds,
    # inventing one from the top ten holdings would be a guess dressed as
    # data, and "Unknown" is a bucket the geography donut names out loud.
    if fund := fetch_profile(ticker, info=info):
        return {
            "sector": "Funds",
            "sector_weights": sector_split(fund),
            "country": None,
            "currency": fund.currency,
        }
    return {
        "sector": info.get("sector"),
        "country": info.get("country"),
        "currency": info.get("currency"),
    }


def load_meta(tickers: list[str], max_workers: int = 8) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        profiles = pool.map(lambda t: (t, _profile(t)), tickers)
    return dict(profiles)


def holdings_from_positions(positions) -> list[Holding]:
    """Ledger positions as watchlist Holdings (shares + native avg cost)."""
    return [
        Holding(ticker=p.ticker, shares=p.quantity, cost=p.avg_cost_native)
        for p in positions
    ]


def market_value(
    ticker: str,
    quantity: float,
    currency: str,
    base: str = "EUR",
    scale: float = 1.0,
) -> float | None:
    """Live market value of a position in `base`; None if a lookup fails.

    `currency`/`scale` are the *listing's* (stocks.analysis.listing): the
    price is the resolved symbol's quote, so it converts at that venue's rate,
    pence scaled to pounds first.
    """
    from stocks.data.fetch import latest_price
    from stocks.data.fx import spot

    try:
        price = latest_price(ticker)
        rate = 1.0 if currency.upper() == base.upper() else spot(currency, base)[0]
    except Exception:
        return None
    return quantity * price * scale * rate


def market_values(
    positions, max_workers: int = 8, base: str = "EUR"
) -> dict[str, float]:
    """Live market value per open position in `base`, off the bulk price path.

    Shared by the CLI (positions/tax) and the dashboard. Prices come from
    `load_closes` — the same `data.fetch.fetch_many` download the basket chart
    and the watchlist rows read — whose last value is the current price during
    a session (yfinance hands back today's in-progress daily bar) and the last
    close outside one. So a tile can no longer disagree with the chart beside
    it.

    It used to fan out one `latest_price` per position instead: a quote request
    per name, 44 of them for a 44-name book, which is what trips Yahoo's rate
    limiter from a datacenter IP. Worse, every failure was swallowed into "no
    price", so a throttled burst rendered a whole book as €0 at -100% while the
    chart — on the history endpoint, which survived — still drew €120k beside
    it. Only names the bulk download has no column for fall back to a
    per-ticker lookup, concurrently.

    Each close converts at its own listing's rate, not the ledger row's
    (stocks.analysis.listing): an alias that prices Revolut's dollar ASML off
    the euro ASML.AS listing would otherwise read a euro close as dollars.

    Positions whose price or FX is unavailable are absent from the result. A
    wholesale throttle is not silent: if nothing could be priced and Yahoo
    refused us, the `YFRateLimitError` propagates so the caller degrades in
    place (and `st.cache_data` doesn't memoize the empty answer).
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.fx import spot

    if not positions:
        return {}

    units = price_units(
        [p.ticker for p in positions], {p.ticker: p.currency for p in positions}
    )

    def unit(p) -> tuple[str, float]:
        return units.get(p.ticker) or (str(p.currency).upper(), 1.0)

    # Warm the spot memo once per currency so nothing races N identical FX
    # fetches for the same pair.
    rates: dict[str, float] = {base.upper(): 1.0}
    for ccy in {unit(p)[0] for p in positions} - {base.upper()}:
        try:
            rates[ccy] = float(spot(ccy, base)[0])
        except Exception as exc:
            obs.warn("portfolio.fx_warmup_failed", ccy=ccy, base=base,
                     error_type=type(exc).__name__, error=str(exc)[:300])
            # left out of `rates`; the per-position fallback re-tries the pair

    throttled: YFRateLimitError | None = None
    try:
        closes = load_closes([p.ticker for p in positions], period="5d")
    except YFRateLimitError as exc:
        throttled, closes = exc, {}

    out: dict[str, float] = {}
    stragglers = []
    for p in positions:
        series = closes.get(p.ticker)
        ccy, scale = unit(p)
        rate = rates.get(ccy)
        if series is None or series.empty or rate is None:
            stragglers.append(p)
            continue
        out[p.ticker] = p.quantity * float(series.iloc[-1]) * scale * rate

    # A handful of names Yahoo won't bulk-quote (a delisting, a symbol the
    # download drops) are still worth one request each. A *majority* missing
    # means the bulk download or FX is down rather than those symbols being
    # odd — fanning out a request per position there would rebuild the very
    # burst this function exists to avoid, on the one occasion Yahoo is
    # already refusing us.
    budget = max(3, len(positions) // 4)
    if len(stragglers) > budget:
        obs.warn("portfolio.bulk_prices_missing", missing=len(stragglers),
                 positions=len(positions), priced=len(out))
        stragglers = []
    if stragglers:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            pairs = pool.map(
                lambda p: (
                    p.ticker,
                    market_value(p.ticker, p.quantity, unit(p)[0], base,
                                 scale=unit(p)[1]),
                ),
                stragglers,
            )
        out.update({t: v for t, v in pairs if v is not None})

    if not out and throttled is not None:
        raise throttled
    return out


def market_value_weights_base(
    positions,
    prices: dict[str, float],
    meta: dict[str, dict],
    base: str = "EUR",
) -> dict[str, float]:
    """Weights from qty * latest native price * native->`base` spot.

    Mixing currencies makes native-value weighting wrong for a multi-currency
    book (mostly USD with some EUR, say), so weights are put on one currency's
    footing here — the reporting currency, not necessarily EUR. Tickers without
    a price drop out and the rest renormalise. The sibling above weights raw
    shares * price and is right only for a single-currency book.

    A pair whose spot cannot be fetched drops out too. It used to fall back to
    a rate of 1.0, which is the one answer that is never right for a pair
    anybody had to look up: a dollar book weighted at parity reads ~8% heavier
    than it is, and that weight then carries into the volatility, the beta and
    every allocation slice. Dropping the row renormalises the rest and is at
    least a book somebody holds.
    """
    from stocks.data.fx import spot

    values: dict[str, float] = {}
    for p in positions:
        px = prices.get(p.ticker)
        if not px:
            continue
        # The profile's currency is the listing's, and may be a minor unit
        # (London in pence): scaled to the major one before any FX.
        ccy, scale = quote_unit((meta.get(p.ticker) or {}).get("currency"))
        if ccy is None:
            ccy, scale = str(p.currency).upper(), 1.0
        if ccy == base.upper():
            rate = 1.0
        else:
            try:
                rate, _ = spot(ccy, base)
            except Exception as exc:
                obs.warn("portfolio.weight_fx_failed", ticker=p.ticker, ccy=ccy,
                         base=base, error_type=type(exc).__name__,
                         error=str(exc)[:300])
                continue
        values[p.ticker] = p.quantity * px * scale * rate
    total = sum(values.values())
    return {t: v / total for t, v in values.items()} if total else {}


def positions_frame(
    positions,
    base: str = "EUR",
    values: dict[str, float] | None = None,
    units: dict[str, tuple[str, float]] | None = None,
) -> pd.DataFrame:
    """Per-position table in `base`: qty, cost, live value, unrealised P/L.

    `values` lets a caller hand in base-currency values it already holds. The
    dashboard passes the basket history's last row (`web.portfolio_data`),
    which it downloads anyway for the day/week/month chips — so the page makes
    one price download instead of two, and a tile can't disagree with the
    chart beside it. Left out (the CLI, the chat tools), the frame prices
    itself through `market_values`.

    `cost` comes from the lots, valued at each trade date's rate — so it only
    lines up with `value` when the ledger was replayed in this same base.

    `ccy` is the currency the row is *priced* in — its listing's, in the major
    unit (stocks.analysis.listing) — not the one it was bought in. It is the
    label on the one native figure the tables print, the share price backed
    out of `value` (value / shares / spot(ccy)), and that division only
    recovers a real quote at the rate `value` was built with. Everything else
    on the row is in `base`: cost at each trade date's rate, value at today's
    listing rate, so `pnl_pct` carries no phantom FX jump from reading one
    venue's price in another's currency. `units` is that answer when a caller
    already holds it; left out it is looked up (memo-first, no network for a
    name the profile memo knows).
    """
    if values is None:
        values = market_values(positions, base=base)
    if units is None:
        units = price_units(
            [p.ticker for p in positions], {p.ticker: p.currency for p in positions}
        )
    rows = []
    for p in positions:
        value = values.get(p.ticker)
        pnl = value - p.cost if value is not None else None
        pnl_pct = (value / p.cost - 1) if value and p.cost else None
        rows.append(
            {
                "ticker": p.ticker,
                "shares": p.quantity,
                "ccy": (units.get(p.ticker) or (p.currency,))[0],
                "cost": p.cost,
                "value": value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()


def priced_totals(tbl: pd.DataFrame) -> tuple[float, float, int]:
    """(cost, value, unpriced) over only the rows carrying a live value.

    `value` is NaN for any position the price pass had no series for — a
    throttled burst, a symbol Yahoo drops, a broker code with no alias yet.
    Summing the whole `cost` column against that partial `value` mixes
    denominators: the book's entire basis over a fraction of its market value,
    which prints an intact book at -60%. Both sums here come from the same
    rows, so the percentage between them is like-for-like, and `unpriced` is
    how many positions were left out — for the caller to disclose, because a
    total that quietly drops a third of the book is the same lie in smaller
    print.
    """
    if tbl.empty or "value" not in tbl:
        return 0.0, 0.0, len(tbl)
    priced = tbl[tbl["value"].notna()]
    cost = float(priced["cost"].sum()) if "cost" in priced else 0.0
    return cost, float(priced["value"].sum()), int(len(tbl) - len(priced))


def value_weights(tbl: pd.DataFrame) -> pd.Series:
    """Each priced row's share of the book, unpriced rows held at their cost.

    A weight is a share of market value, and a position the price pass missed
    has none — so it reads NaN and the column stops summing to 1. What it must
    not do is drop out of the denominator too: dividing by the priced slice
    alone hands the names that did price the missing ones' share, which is how
    a 6% ETF renders as 50% of a throttled book. The absent rows stand in the
    denominator at their ledger cost — stale, but far closer to their value
    than the zero they contribute otherwise.
    """
    if tbl.empty or "value" not in tbl:
        return pd.Series(dtype=float, index=tbl.index)
    priced = tbl["value"].notna()
    total = float(tbl.loc[priced, "value"].sum())
    if "cost" in tbl:
        total += float(tbl.loc[~priced, "cost"].sum())
    if not total:
        return pd.Series(float("nan"), index=tbl.index)
    return tbl["value"] / total


def fx_frame(
    currencies, index: pd.Index, base: str = "EUR"
) -> dict[str, pd.Series]:
    """{currency: daily rate into `base`} for `currencies`, aligned to `index`.

    `index` is any index of dates — it is read as a `DatetimeIndex` below, and
    the callers hand over a frame's own `.index`, which pandas only knows to be
    an `Index` however it was built.

    The base currency is not in the result — it is 1.0 by definition, and a
    caller that looks a rate up for it has asked the wrong question. A pair
    whose fetch fails is absent rather than 1.0: a position valued at a made-up
    parity is worse than one the caller knows it could not value.

    ffilled forwards *and* backwards, because the ECB publishes on business
    days and a price index does not: a Monday holiday would otherwise leave the
    first row of a window unvalued.
    """
    from datetime import date

    from stocks.data.fx import rates_range

    out: dict[str, pd.Series] = {}
    if not len(index):
        return out
    stamps = pd.DatetimeIndex(index)
    start = stamps[0].date().isoformat()
    for ccy in {str(c).upper() for c in currencies} - {base.upper()}:
        try:
            rates = rates_range(start, date.today().isoformat(), ccy, base)
        except Exception as exc:
            obs.warn("portfolio.fx_range_failed", ccy=ccy, base=base,
                     error_type=type(exc).__name__, error=str(exc)[:300])
            continue
        if rates:
            series = pd.Series(rates, dtype=float)
            series.index = pd.to_datetime(series.index)
            out[ccy] = series.reindex(stamps).ffill().bfill()
    return out


def rebase_report(
    report: PortfolioReport, positions, base: str = "EUR", period: str = "1y"
) -> PortfolioReport:
    """Re-read a watchlist-shaped report as the holder's own book, in `base`.

    `analyze` measures a list of tickers: native closes, native weights. A book
    is a different object — it has quantities, and it is read in one currency —
    and every risk figure changes accordingly. Both sides move here or neither
    does: weights on the reporting currency's footing (a mostly-USD book is
    weighted wrong by native prices), returns off per-position values in the
    same currency (a EUR reader's move in a US name includes the dollar's), and
    the benchmarks converted to match, because a beta with the currency on one
    side only measures nothing anybody holds.

    Mutates and returns the report it was given, so a cached `analyze` result
    stays the one download both front ends share.
    """
    values, _ = position_value_frames(
        positions, period=period, base=base, closes=report.closes
    )
    if not values.empty:
        # Quantities are fixed across the frame, so they cancel in the ratio:
        # this is the price-and-FX move of each name, not a flow-adjusted one.
        report.returns = values.pct_change().iloc[1:].dropna(how="all")
        rate = fx_frame([BENCHMARK_CCY], values.index, base).get(BENCHMARK_CCY)
        report.bench_returns = {
            name: rebase_returns(series, rate)
            for name, series in report.bench_returns.items()
        }
    report.weights = market_value_weights_base(
        positions, report.prices, report.meta, base
    )
    report.port_returns = portfolio_returns(report.returns, report.weights)
    return report


def rebase_returns(returns: pd.Series, rate: pd.Series | None) -> pd.Series:
    """A native-currency return series read from `base`'s side of the pair.

    `(1 + r_native) * (1 + r_fx) - 1`. What a EUR reader earned on an S&P
    tracker is the index's move *and* the dollar's, and a beta that measures
    the book with the currency in it against a benchmark without it is
    comparing two different investments. `rate` of None leaves the series
    alone, which is what a benchmark already quoted in `base` needs.
    """
    if rate is None or returns.empty:
        return returns
    move = rate.pct_change().reindex(returns.index).fillna(0.0)
    return (1 + returns) * (1 + move) - 1


def position_value_frames(
    positions,
    period: str = "3mo",
    base: str = "EUR",
    closes: dict[str, pd.Series] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(values at the daily FX, values at the window's closing FX).

    `closes` lets a caller hand in price series it already holds (the web
    layer's shared ledger download, sliced to the window) instead of paying a
    bulk request for the same names; `period` is then only the window label.

    One fetch, two readings of it. The first frame is what the book was worth
    each day and is what every caller wants; the second holds every exchange
    rate fixed at the last one in the window, so it moves only when a *price*
    moves. Subtracting one from the other separates the two things a EUR
    investor in US names sees blended into a single number — how the companies
    did, and how the dollar did — which is the question behind every "why is
    my portfolio down when the market was up".
    """
    if closes is None:
        closes = load_closes([p.ticker for p in positions], period=period)
    if not closes:
        return pd.DataFrame(), pd.DataFrame()
    px = pd.DataFrame(closes).sort_index()
    px.index = naive_dates(px.index)
    px = px.ffill()

    # Each series converts at its listing's rate, pence scaled to pounds —
    # not the ledger row's currency (stocks.analysis.listing).
    units = price_units(
        [p.ticker for p in positions if p.ticker in px.columns],
        {p.ticker: p.currency for p in positions},
    )
    fx = fx_frame({u[0] for u in units.values()}, px.index, base)

    values: dict[str, pd.Series] = {}
    frozen: dict[str, pd.Series] = {}
    for p in positions:
        if p.ticker not in px.columns or p.ticker not in units:
            continue
        # Keyed as `fx_frame` keys it (upper-case ISO), so a ledger row
        # carrying a lowercase code does not silently drop out of the frame.
        ccy, scale = units[p.ticker]
        native = p.quantity * px[p.ticker] * scale
        if ccy == base.upper():
            values[p.ticker] = native
            frozen[p.ticker] = native
        elif ccy in fx:
            rate = fx[ccy]
            values[p.ticker] = native * rate
            frozen[p.ticker] = native * float(rate.iloc[-1])
    return pd.DataFrame(values), pd.DataFrame(frozen)


def position_values_history(
    positions,
    period: str = "3mo",
    base: str = "EUR",
    closes: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """Daily `base` value per open position at *today's* quantities.

    Current shares × daily native close × daily ECB FX, forward-filled onto the
    price index. Powers the day/week/month change chips and the per-ticker day
    change, so a position's move includes its FX move — the book is judged in
    EUR. Flows inside the window are NOT adjusted (that's the TWR view's job).
    Tickers without a usable price (or FX) series are absent.
    """
    return position_value_frames(positions, period, base, closes=closes)[0]


def benchmark_changes(
    windows: list[int], ticker: str = "SPY", period: str = "1y"
) -> dict[int, float | None]:
    """{days: % change} for one index, read off daily closes. Empty on failure.

    The comparison the notifications make when they say a book "lagged": same
    anchoring as `basket_change`, so the two numbers in the sentence were
    measured between the same two dates. Deliberately in the index's own
    currency — a EUR reader asking whether they beat the S&P means the index,
    not the index plus the dollar, and the currency leg is reported separately
    (see `fx_share`).
    """
    series = load_closes([ticker], period=period).get(ticker)
    if series is None or series.empty:
        return {}
    frame = pd.DataFrame({ticker: series}).sort_index()
    out: dict[int, float | None] = {}
    for days in windows:
        change = basket_change(frame, days)
        out[days] = change[1] if change else None
    return out


def fx_share(values: pd.DataFrame, frozen: pd.DataFrame, days: int) -> float | None:
    """How much of the basket's `days`-window move was currency, in `base` money.

    The difference between the move as lived and the move the same prices would
    have produced at today's rates. Positive means the currency helped. None
    when either frame can't cover the window — and, deliberately, when the book
    is single-currency, where the answer is always a meaningless zero.
    """
    if values.empty or frozen.empty:
        return None
    lived = basket_change(values, days)
    at_todays_rate = basket_change(frozen, days)
    if lived is None or at_todays_rate is None:
        return None
    return lived[0] - at_todays_rate[0]


def basket_change(values: pd.DataFrame, days: int) -> tuple[float, float] | None:
    """(change, pct change) of the basket over the last ~`days` calendar days.

    `days=1` compares the last two rows (previous trading day); longer windows
    anchor on the last row at or before `end - days`. Only tickers priced at
    both endpoints count, so a name quoted only mid-window doesn't read as a
    gain. None when the frame doesn't cover the window.
    """
    if len(values) < 2:
        return None
    end = values.index[-1]
    if days <= 1:
        start = values.index[-2]
    else:
        prior = values.index[values.index <= end - pd.Timedelta(days=days)]
        if prior.empty:
            return None
        start = prior[-1]
    both = values.loc[start].notna() & values.loc[end].notna()
    v0 = float(values.loc[start, both].sum())
    v1 = float(values.loc[end, both].sum())
    if not v0:
        return None
    return v1 - v0, v1 / v0 - 1


def ticker_changes(values: pd.DataFrame, days: int) -> pd.Series:
    """Per-ticker % change over the last ~`days` calendar days.

    The per-name counterpart of `basket_change`, read off the same frame with
    the same anchoring: `days<=1` compares the last two rows, longer windows
    anchor on the last row at or before `end - days`. A ticker priced at only
    one endpoint (or starting from zero) is dropped rather than reported as an
    infinite move. Empty Series when the frame doesn't cover the window.
    """
    if len(values) < 2:
        return pd.Series(dtype=float)
    end = values.index[-1]
    if days <= 1:
        start = values.index[-2]
    else:
        prior = values.index[values.index <= end - pd.Timedelta(days=days)]
        if prior.empty:
            return pd.Series(dtype=float)
        start = prior[-1]
    first, last = values.loc[start], values.loc[end]
    both = first.notna() & last.notna() & (first != 0)
    return last[both] / first[both] - 1


def ticker_day_changes(
    values: pd.DataFrame, quotes: dict[str, dict] | None = None
) -> pd.Series:
    """Per-ticker move over one session, with off-hours quotes taking over.

    Close-to-close is the whole story only while the exchange is open. Outside
    it the daily bar can be a stale or flat premarket one, and the basket then
    reports a book that did not move at all — the "+0.00% today" a reader gets
    at eight in the morning. `quotes` is `session_quotes`' snapshot for the
    names whose own market is shut: the live pre/after-hours move while there
    is one, the last completed session once those windows close. Pass None
    inside the session, when the bars already are the live price.
    """
    changes = ticker_changes(values, 1)
    for ticker, quote in (quotes or {}).items():
        pct = quote.get("pct")
        if ticker in values.columns and pct is not None:
            changes.loc[ticker] = float(pct)
    return changes


def day_change(
    values: pd.DataFrame, quotes: dict[str, dict] | None = None
) -> tuple[float, float] | None:
    """(change, pct change) of the basket over one session — `basket_change`'s
    day window, able to read a quote where the daily bar says nothing yet.

    Each name's prior value is backed out of its own move (`v / (1 + pct)`)
    rather than read off the previous row, which is what lets a quoted
    override and a close-to-close row live in the same sum. Names without a
    move on both sides are left out of it entirely, so the percentage is
    measured over exactly the value it was earned on.
    """
    if quotes is None:
        return basket_change(values, 1)
    if values.empty:
        return None
    last = values.iloc[-1]
    moves = ticker_day_changes(values, quotes)
    gained = opening = 0.0
    for ticker, value in last.items():
        pct = moves.get(ticker)
        if pd.isna(value) or pct is None or pd.isna(pct) or pct == -1:
            continue
        prior = float(value) / (1 + float(pct))
        gained += float(value) - prior
        opening += prior
    return (gained, gained / opening) if opening else None


def ticker_money_changes(values: pd.DataFrame, days: int) -> pd.Series:
    """Per-ticker change in `base` money over the last ~`days` calendar days.

    The percentage a name moved is not what it did to the book: a 5% pop on a
    1% position is worth less than a 1.5% drift on a 30% one. This reads the
    same frame `ticker_changes` does, with the same anchoring, and returns the
    contribution in currency — so the sum over tickers is the basket change
    `basket_change` reports for the same window. A ticker priced at only one
    endpoint is dropped (it contributed nothing measurable, not a windfall).
    """
    if len(values) < 2:
        return pd.Series(dtype=float)
    end = values.index[-1]
    if days <= 1:
        start = values.index[-2]
    else:
        prior = values.index[values.index <= end - pd.Timedelta(days=days)]
        if prior.empty:
            return pd.Series(dtype=float)
        start = prior[-1]
    first, last = values.loc[start], values.loc[end]
    both = first.notna() & last.notna()
    return last[both] - first[both]


# --------------------------------------------------------------- market clock
# The day-change columns come from daily closes, so outside a live regular
# session they show the LAST completed session's move, not a live tick. These
# helpers flag that state so the UI can render those cells muted ("market
# closed — last close") instead of implying they're moving right now.
#
# Regular-session hours per exchange, keyed by the Yahoo symbol suffix
# (resolve() gives it — e.g. RCF -> TEP.PA -> "PA"). (IANA tz, open, close) in
# exchange-local time; continuous session (HK/Tokyo lunch breaks ignored — a
# soft cue, not a trading gate). No suffix / unknown = US.
_EXCHANGE_HOURS: dict[str, tuple[str, tuple[int, int], tuple[int, int]]] = {
    # Euronext + Southern Europe (CET)
    "PA": ("Europe/Paris", (9, 0), (17, 30)),
    "AS": ("Europe/Amsterdam", (9, 0), (17, 30)),
    "BR": ("Europe/Brussels", (9, 0), (17, 30)),
    "LS": ("Europe/Lisbon", (8, 0), (16, 30)),
    "MI": ("Europe/Rome", (9, 0), (17, 30)),
    "MC": ("Europe/Madrid", (9, 0), (17, 30)),
    "VI": ("Europe/Vienna", (9, 0), (17, 30)),
    # Germany (Xetra + Frankfurt floor)
    "DE": ("Europe/Berlin", (9, 0), (17, 30)),
    "F": ("Europe/Berlin", (8, 0), (20, 0)),
    # UK / Ireland
    "L": ("Europe/London", (8, 0), (16, 30)),
    "IR": ("Europe/Dublin", (8, 0), (16, 30)),
    # Switzerland + Nordics
    "SW": ("Europe/Zurich", (9, 0), (17, 30)),
    "ST": ("Europe/Stockholm", (9, 0), (17, 30)),
    "HE": ("Europe/Helsinki", (10, 0), (18, 30)),
    "CO": ("Europe/Copenhagen", (9, 0), (17, 0)),
    "OL": ("Europe/Oslo", (9, 0), (16, 30)),
    # Asia-Pacific
    "HK": ("Asia/Hong_Kong", (9, 30), (16, 0)),
    "T": ("Asia/Tokyo", (9, 0), (15, 0)),
    "SS": ("Asia/Shanghai", (9, 30), (15, 0)),
    "SZ": ("Asia/Shanghai", (9, 30), (15, 0)),
    "KS": ("Asia/Seoul", (9, 0), (15, 30)),
    "TW": ("Asia/Taipei", (9, 0), (13, 30)),
    "NS": ("Asia/Kolkata", (9, 15), (15, 30)),
    "BO": ("Asia/Kolkata", (9, 15), (15, 30)),
    "AX": ("Australia/Sydney", (10, 0), (16, 0)),
    # Other Americas
    "TO": ("America/Toronto", (9, 30), (16, 0)),
    "SA": ("America/Sao_Paulo", (10, 0), (17, 0)),
}


def _session_open(
    tz_name: str,
    open_hm: tuple[int, int],
    close_hm: tuple[int, int],
    now_utc: datetime | None = None,
) -> bool:
    """Whether `now` is inside a Mon–Fri open→close window in `tz_name`.

    Time-based only — ignores exchange holidays (a holiday reads as "open"),
    fine for a soft display cue. `now_utc` is injectable for tests."""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    now = (now_utc or datetime.now(UTC)).astimezone(ZoneInfo(tz_name))
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return time(*open_hm) <= now.time() < time(*close_hm)


def us_market_open(now_utc: datetime | None = None) -> bool:
    """Whether the US equity regular session (Mon–Fri, 09:30–16:00 America/
    New_York) is open right now. See `_session_open` for the holiday caveat."""
    return _session_open("America/New_York", (9, 30), (16, 0), now_utc)


def market_live(ticker: str, now_utc: datetime | None = None) -> bool:
    """Whether `ticker` is in a live regular session on its own exchange now.

    Crypto trades 24/7 (always live). Equities key off the Yahoo symbol suffix
    (`_EXCHANGE_HOURS`) so a Paris/London/HK name follows its local hours; an
    unsuffixed or unknown symbol falls back to US hours. Exchange-local, so a
    European stock reads open during CET hours even while US premarket is closed.
    """
    from stocks.data.crypto import is_crypto
    from stocks.data.fetch import resolve

    if is_crypto(ticker):
        return True
    symbol = resolve(ticker)
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    hours = _EXCHANGE_HOURS.get(suffix)
    return _session_open(*hours, now_utc) if hours else us_market_open(now_utc)


def us_extended_session(now_utc: datetime | None = None) -> str | None:
    """"pre" / "post" while a US extended-hours window is open, else None.

    Yahoo quotes those windows (04:00-09:30 and 16:00-20:00 America/New_York),
    so the day change keeps moving outside the regular session. Time-based, no
    network, same holiday caveat as `_session_open`."""
    if _session_open("America/New_York", (4, 0), (9, 30), now_utc):
        return "pre"
    if _session_open("America/New_York", (16, 0), (20, 0), now_utc):
        return "post"
    return None


def market_active(ticker: str, now_utc: datetime | None = None) -> bool:
    """Whether `ticker` has a live quote now: regular session OR US pre/post.

    Drives the dimmed day-change cells. A premarket quote is live data, so it
    reads in full colour; a name whose exchange is fully shut stays dimmed.
    Only US symbols get an extended feed here, so anything on a foreign
    exchange follows `market_live`."""
    if market_live(ticker, now_utc):
        return True
    from stocks.data.fetch import resolve

    symbol = resolve(ticker)
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    return suffix not in _EXCHANGE_HOURS and us_extended_session(now_utc) is not None


def _quote_date(quote: dict, *, today: bool = False) -> str | None:
    """The exchange-local trading date behind a quote, ISO, or None.

    `today` asks for the exchange's current date instead of the last regular
    trade's — what a premarket move belongs to, since `regularMarketTime` is
    still yesterday's close while the premarket quotes.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(str(quote.get("exchangeTimezoneName") or "America/New_York"))
    except Exception:
        zone = ZoneInfo("America/New_York")
    if today:
        return datetime.now(UTC).astimezone(zone).date().isoformat()
    stamp = quote.get("regularMarketTime")
    if hasattr(stamp, "astimezone"):
        return stamp.astimezone(zone).date().isoformat()
    if stamp is None:
        return None  # no trade stamp in the quote — the caller prints no date
    try:
        moment = datetime.fromtimestamp(float(stamp), UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return moment.astimezone(zone).date().isoformat()


def session_quote(ticker: str) -> dict | None:
    """Yahoo quote snapshot: `{"price", "pct", "session"}`, or None if missing.

    `pct` is the move since the previous regular close, extended hours
    included. Reads Yahoo's batch quote (`data.quotes`): during premarket
    `regularMarketPrice` is still the last close, so `preMarketPrice /
    regularMarketPrice - 1` is the move so far today; after the close
    `postMarketPrice / regularMarketPreviousClose - 1` compounds the session
    with after-hours. Outside those windows it falls back to the last completed
    session (`regularMarketPrice / regularMarketPreviousClose - 1`), which is
    what the daily close-to-close basket gets wrong (a stale/flat premarket bar
    collapses it to ~0%).

    `price` is the price `pct` was measured to — the extended-hours quote while
    one is trading, else the last regular price. `session` is "pre"/"post" only
    while that window is actually open per `marketState`, so a fully closed
    market reads None even though its last after-hours price is still used.

    `as_of` is the exchange-local trading date `pct` belongs to, which is the
    part a caller cannot infer: outside the session the move is the *last
    completed* session, so a card that calls it "today" is off by a day (or by
    a weekend). Premarket stamps today; every other branch stamps the regular
    session the quote closed. None when the quote carries no timestamp.
    """
    from stocks.data.quotes import quote as live_quote

    return _snapshot(live_quote(ticker))


def _snapshot(quote: dict) -> dict | None:
    """`session_quote`'s reading of one raw Yahoo quote row — pure, no network.

    Split out because the batch path parses the same rows: one place decides
    which price a day change is measured from, whoever fetched it.
    """
    with obs.swallow("quote.session"):
        state = str(quote.get("marketState") or "")
        regular = quote.get("regularMarketPrice")
        prev = quote.get("regularMarketPreviousClose")
        pre, post = quote.get("preMarketPrice"), quote.get("postMarketPrice")
        if state.startswith("PRE") and pre and regular:
            price = float(pre)
            return {
                "price": price,
                "pct": price / float(regular) - 1,
                "session": "pre",
                "as_of": _quote_date(quote, today=True),
            }
        if post and prev and not state.startswith("PRE"):
            price = float(post)
            return {
                "price": price,
                "pct": price / float(prev) - 1,
                "session": "post" if state.startswith("POST") else None,
                "as_of": _quote_date(quote),
            }
        if regular and prev:
            price = float(regular)
            return {
                "price": price,
                "pct": price / float(prev) - 1,
                "session": None,
                "as_of": _quote_date(quote),
            }
    return None


def _session_move(ticker: str) -> float | None:
    """Day % move from the quote (see `session_quote`), None when unavailable."""
    quote = session_quote(ticker)
    return quote["pct"] if quote else None


def session_quotes(tickers: list[str]) -> dict[str, dict]:
    """`session_quote` for every ticker, in ONE request. Missing quotes absent.

    The full snapshot rather than the bare percentage, because a day move is
    only half a fact: `as_of` says which session it is, and a caller that
    prints it as "today" without looking is how a Wednesday card ends up
    quoting Monday's close.

    This used to fan `.info` out over a thread pool — two requests per ticker,
    eight at a time, and a `with` block that waited on whatever hung. Off-
    session that is the whole book, and a throttled Yahoo turned a Home render
    into a nineteen-minute one. `data.quotes` asks once, under one budget.
    """
    from stocks.data.quotes import quotes as live_quotes

    if not tickers:
        return {}
    snapshots = (
        (t, _snapshot(row)) for t, row in live_quotes(list(tickers)).items()
    )
    return {t: q for t, q in snapshots if q and q.get("pct") is not None}


def session_moves(tickers: list[str]) -> dict[str, float]:
    """Day % move per ticker (native), extended hours included, concurrent.

    Feeds the off-session day-change cells: premarket / after-hours while those
    windows are open, the last completed session once they close — never the
    flat premarket 0% the daily basket can produce. Tickers whose quote is
    unavailable are absent (caller falls back to the basket value). Callers
    that will *write* the number into prose want `session_quotes` instead, for
    the `as_of` that says which session it is."""
    return {t: q["pct"] for t, q in session_quotes(tickers).items()}


def analyze(
    period: str = "1y",
    benchmarks: tuple[str, ...] = DEFAULT_BENCHMARKS,
    holdings: list[Holding] | None = None,
) -> PortfolioReport:
    """Fetch prices + profiles for the watchlist and build a PortfolioReport."""
    holdings = holdings if holdings is not None else load_watchlist()
    tickers = [h.ticker for h in holdings]
    # Watchlist + benchmarks in one bulk download.
    all_closes = load_closes([*tickers, *benchmarks], period=period)
    closes = {t: s for t, s in all_closes.items() if t in set(tickers)}
    latest = {t: float(s.iloc[-1]) for t, s in closes.items()}
    weights = weights_from_holdings(holdings, latest)
    returns = returns_frame(closes)
    port = portfolio_returns(returns, weights)
    bench_returns = {
        b: all_closes[b].pct_change().iloc[1:] for b in benchmarks if b in all_closes
    }
    return PortfolioReport(
        weights=weights,
        meta=load_meta(tickers),
        returns=returns,
        port_returns=port,
        prices=latest,
        bench_returns=bench_returns,
        closes=closes,
    )
