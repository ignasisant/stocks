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

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stocks import obs
from stocks.analysis import naive_dates
from stocks.analysis.listing import price_units, quote_unit
from stocks.analysis.portfolio.clock import (
    _session_move,
    _snapshot,
    market_active,
    market_live,
    session_moves,
    session_quote,
    session_quotes,
    us_extended_session,
    us_market_open,
)
from stocks.analysis.portfolio.flows import (
    Leg,
    Legs,
    Sleeve,
    ToBaseFn,
    complete_download,
    flow_matched_curves,
    flow_series,
    injected_series,
    injected_vs_value,
    money_weighted_return,
    plausible_closes,
    project_sleeves,
    shares_frame,
    sleeve_stats,
    time_weighted_returns,
)
from stocks.analysis.portfolio.stats import (
    MIN_CORR_DAYS,
    MIN_VAR_DAYS,
    TRADING_DAYS,
    allocation,
    allocation_parts,
    annualized_return,
    annualized_volatility,
    beta,
    correlation_matrix,
    cumulative_returns,
    drawdown_span,
    effective_positions,
    equal_weights,
    hhi,
    historical_var,
    market_value_weights,
    max_drawdown,
    portfolio_returns,
    position_table,
    returns_frame,
    risk_shares,
    samples_per_year,
    top_n_weight,
    weights_from_holdings,
)
from stocks.config import Holding, load_watchlist
from stocks.frames import midnights
from stocks.portfolio import consistency, transfers

__all__ = [
    "BENCHMARK_CCY",
    "DEFAULT_BENCHMARKS",
    "HELD_ACTIONS",
    "Leg",
    "Legs",
    "MIN_CORR_DAYS",
    "MIN_VAR_DAYS",
    "PortfolioReport",
    "Sleeve",
    "TRADING_DAYS",
    "ToBaseFn",
    "_audit_twr",
    "_profile",
    "_session_move",
    "_snapshot",
    "allocation",
    "allocation_parts",
    "analyze",
    "annualized_return",
    "annualized_volatility",
    "basket_change",
    "benchmark_changes",
    "beta",
    "book_history",
    "complete_download",
    "correlation_matrix",
    "cumulative_returns",
    "day_change",
    "drawdown_span",
    "effective_positions",
    "equal_weights",
    "first_owned",
    "flow_matched_curves",
    "flow_series",
    "fx_frame",
    "fx_share",
    "hhi",
    "historical_var",
    "holdings_from_positions",
    "index_change",
    "injected_series",
    "injected_vs_value",
    "load_closes",
    "load_meta",
    "market_active",
    "market_live",
    "market_value",
    "market_value_weights",
    "market_value_weights_base",
    "market_values",
    "max_drawdown",
    "money_change",
    "money_weighted_return",
    "plausible_closes",
    "portfolio_returns",
    "position_table",
    "position_value_frames",
    "position_values_history",
    "positions_frame",
    "priced_totals",
    "project_sleeves",
    "rebase_report",
    "rebase_returns",
    "returns_frame",
    "risk_shares",
    "same_money",
    "samples_per_year",
    "session_moves",
    "session_quote",
    "session_quotes",
    "shares_frame",
    "sleeve_stats",
    "ticker_changes",
    "ticker_day_changes",
    "ticker_money_changes",
    "time_weighted_returns",
    "top_n_weight",
    "us_extended_session",
    "us_market_open",
    "value_weights",
    "weights_from_holdings",
    "window_span",
]

# Default benchmarks: US large-cap, US tech, emerging markets.
DEFAULT_BENCHMARKS = ("SPY", "QQQ", "EEM")
# All three are US-listed and quoted in dollars. Named rather than assumed
# because a reader in another currency does not hold the index, they hold the
# index and the dollar — see `rebase_returns`.
BENCHMARK_CCY = "USD"


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
    tickers: list[str],
    period: str = "1y",
    adjusted: bool = True,
    currencies: dict[str, str] | None = None,
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
    # every screen (via api.loaders), and pulling yfinance in costs ~150 ms of a
    # cold start for a dependency only the network functions below need.
    from stocks.data.fetch import fetch_many

    out: dict[str, pd.Series] = {}
    frames = fetch_many(
        tickers, period=period, auto_adjust=adjusted, currencies=currencies
    )
    for t, df in frames.items():
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
        traded_in = {t.ticker: t.currency for t in held if t.action in ("buy", "sell")}
        closes = load_closes(tickers, period=f"{months}mo", currencies=traded_in)
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
        _audit_twr(twr)
    unpriced = sorted({t for t in tickers if t not in closes})
    if unpriced:
        # Every render says "sin histórico" to the reader and nothing to us —
        # the only way a name like this reaches a human today is someone
        # noticing the caption and asking. One line per name is enough for
        # `stocks logs stats --event data.inconsistency --by ticker` to show
        # which keep turning up, without a second sink to maintain: unlike an
        # import failure, there is no user file to redact here, just our own
        # catalog symbols. Once per window, since every request replays it.
        for ticker in unpriced:
            consistency.report("unpriced_held", source="replay", ticker=ticker)
    missing = sorted(
        set(unpriced)
        | set(hist.attrs.get("carried_at_cost", []) if not hist.empty else [])
    )
    return hist, twr, missing


def _audit_twr(twr: pd.Series) -> None:
    """Say a book whose value path jumps further in a day than a book moves.

    A diversified book does not triple or lose two thirds net of its flows in
    one session; when its path does, a price slipped or a flow never reached
    the ledger, and the chart and every return read off it carry the step.
    One line per book: how many such days, the worst, and the days the TWR
    already dropped as below -100 %.
    """
    said = consistency.QUOTE_JUMP_SAID
    offs = 1 + twr
    jumps = offs[(offs >= said) | (offs <= 1 / said)]
    dropped = twr.attrs.get("dropped_days", [])
    if jumps.empty and not dropped:
        return
    worst = None
    if not jumps.empty:
        worst = max(jumps.index, key=lambda d: max(jumps[d], 1 / jumps[d]))
    consistency.report(
        "twr_jump",
        source="replay",
        key="book",
        n=len(jumps),
        dropped=len(dropped),
        day=(worst if worst is not None else min(dropped)).date().isoformat(),
        off=round(float(jumps[worst]), 3) if worst is not None else None,
    )


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


def first_owned(transactions) -> dict[str, pd.Timestamp]:
    """Each resolved ticker's earliest buy date, for `portfolio_returns`' `since`.

    Relabelled first (`transfers.relabel`): a book moved between brokers books
    the same security under two spellings, and the backtest weight is on the
    resolved symbol, not either broker's own label.
    """
    since: dict[str, pd.Timestamp] = {}
    for tx in transfers.relabel(list(transactions)):
        if tx.action != "buy":
            continue
        date = pd.Timestamp(tx.date).normalize()  # ty: ignore[unresolved-attribute]
        earliest = since.get(tx.ticker)
        if earliest is None or date < earliest:
            since[tx.ticker] = date
    return since


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


def market_values(positions, max_workers: int = 8, base: str = "EUR") -> dict[str, float]:
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
    place (and the cache over it doesn't memoize the empty answer).
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
            obs.warn(
                "portfolio.fx_warmup_failed",
                ccy=ccy,
                base=base,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
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
        obs.warn(
            "portfolio.bulk_prices_missing",
            missing=len(stragglers),
            positions=len(positions),
            priced=len(out),
        )
        stragglers = []
    if stragglers:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            pairs = pool.map(
                lambda p: (
                    p.ticker,
                    market_value(
                        p.ticker, p.quantity, unit(p)[0], base, scale=unit(p)[1]
                    ),
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
                obs.warn(
                    "portfolio.weight_fx_failed",
                    ticker=p.ticker,
                    ccy=ccy,
                    base=base,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                )
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
    API passes the basket history's last row (`api.loaders._priced_positions`),
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


def fx_frame(currencies, index: pd.Index, base: str = "EUR") -> dict[str, pd.Series]:
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
            obs.warn(
                "portfolio.fx_range_failed",
                ccy=ccy,
                base=base,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
            continue
        if rates:
            series = pd.Series(rates, dtype=float)
            series.index = pd.to_datetime(series.index)
            out[ccy] = series.reindex(stamps).ffill().bfill()
    return out


def rebase_report(
    report: PortfolioReport,
    positions,
    base: str = "EUR",
    period: str = "1y",
    since: dict[str, pd.Timestamp] | None = None,
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
    report.port_returns = portfolio_returns(report.returns, report.weights, since=since)
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
    open where `_window` opens them. Only tickers priced at
    both endpoints count, so a name quoted only mid-window doesn't read as a
    gain. None when the frame doesn't cover the window.
    """
    window = _window(values.index, days)
    if window is None:
        return None
    start, end = window
    both = values.loc[start].notna() & values.loc[end].notna()
    v0 = float(values.loc[start, both].sum())
    v1 = float(values.loc[end, both].sum())
    if not v0:
        return None
    return v1 - v0, v1 / v0 - 1


# How far behind today a frame's last row may sit and still be read as
# today's book: a long weekend, a feed a day late. Older, it is history, and its
# windows count back from its own last row.
_FRESH = pd.Timedelta(days=4)


def _reference(end: pd.Timestamp) -> pd.Timestamp:
    """The day a window counts back from: today, while `end` is recent.

    Not the frame's last row. That row turns from yesterday to today the
    moment anything prices today (a coin at midnight, Europe at nine), and a
    week counted back from it opens a day later than it did at breakfast —
    one ugly session in or out of "this week", thousands on a big book, with
    nothing having traded. Counted from the calendar, every screen that asks
    for a week the same day opens it on the same close.
    """
    tz = getattr(end, "tz", None)
    today = pd.Timestamp.now(tz=tz).normalize()
    return today if end <= today < end + _FRESH else end


def _window(idx: pd.Index, days: int):
    """(start, end) of a ~`days` calendar-day window on `idx`; None when `idx`
    does not reach that far.

    One session for `days <= 1` (the last two rows); longer windows open on
    the last row at or before `days` before today (`_reference`) and end on
    the newest. Every book figure over a window — `basket_change`,
    `money_change`, `index_change`, the per-name changes, the Today card's
    index — opens here, so two screens never disagree about where a week
    began."""
    if len(idx) < 2:
        return None
    end = idx[-1]
    if days <= 1:
        return idx[-2], end
    prior = idx[np.asarray(idx <= _reference(end) - pd.Timedelta(days=days))]
    return None if prior.empty else (prior[-1], end)


window_span = _window


def _naive_index(series: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = series.set_axis(midnights(idx))
    return out[~out.index.duplicated(keep="last")].sort_index()


def _at_stake(value: pd.Series, flows: pd.Series, start, end) -> float:
    """The money a window put to work: the book's value where it opens plus
    every euro put in across it. Withdrawals do not shrink it — money taken
    out was at work until it left."""
    put = flows[(flows.index > start) & (flows.index <= end)]
    return float(value.loc[start] + put[put > 0].sum())


def money_change(hist: pd.DataFrame | None, days: int) -> tuple[float, float] | None:
    """(gain, pct) of the book over ~`days` calendar days, on its own money.

    The gain is the value's move less the money put in or taken out over the
    window; the pct is that gain over the money at stake (`_at_stake`). How
    much was in the book, and when, is the whole point: a good month on
    5,000 € is not a good month on 100,000 €. `index_change` reads an index on
    exactly this money, so the two are comparable. Anchored as
    `basket_change`; None when `hist` does not cover the window.
    """
    if hist is None or len(hist) < 2:
        return None
    value = _naive_index(hist["value"])
    injected = _naive_index(hist["injected"])
    window = _window(pd.DatetimeIndex(value.index), days)
    if window is None:
        return None
    start, end = window
    if not value.loc[start] > 0:
        return None
    flows = injected.diff().fillna(0.0)
    put_in = injected.loc[end] - injected.loc[start]
    gain = float(value.loc[end] - value.loc[start] - put_in)
    stake = _at_stake(value, flows, start, end)
    return gain, gain / stake if stake else 0.0


def same_money(
    hist: pd.DataFrame | None, closes: pd.Series | None, start=None
) -> pd.Series | None:
    """What the book's own money would be worth in an index, day by day.

    From `start` (the book's first day by default) the index is bought with
    the book's value that day, then with every euro put in and sold for every
    euro taken out, on the same days, at that day's close — the book's cash
    flows replayed into the index. The fair comparison: an index that had all
    of today's money from the first day credits the book's timing to the
    market, and a time-weighted return ignores how much money was in at each
    moment. `closes` in the book's currency. None when the index does not
    cover the window.
    """
    if hist is None or hist.empty or closes is None or closes.dropna().empty:
        return None
    value = _naive_index(hist["value"])
    injected = _naive_index(hist["injected"])
    days = value.index
    if start is not None:
        days = days[np.asarray(days >= pd.Timestamp(start))]
    if len(days) < 2:
        return None
    price = _naive_index(closes.dropna()).reindex(days, method="ffill")
    if price.isna().any() or not (price > 0).all():
        return None
    flows = injected.reindex(days).diff()
    flows.iloc[0] = value.loc[days[0]]
    units = (flows / price).cumsum()
    return units * price


def index_change(
    hist: pd.DataFrame | None, closes: pd.Series | None, days: int
) -> tuple[float, float] | None:
    """(gain, pct) the book's own money would have made in an index over ~`days`
    calendar days (`same_money`), over the same money at stake as
    `money_change` — the index's figure to set beside the book's."""
    if hist is None or len(hist) < 2:
        return None
    value = _naive_index(hist["value"])
    injected = _naive_index(hist["injected"])
    window = _window(pd.DatetimeIndex(value.index), days)
    if window is None or not value.loc[window[0]] > 0:
        return None
    start, end = window
    shadow = same_money(hist, closes, start)
    if shadow is None:
        return None
    put = injected.loc[end] - injected.loc[start]
    gain = float(shadow.iloc[-1] - shadow.iloc[0] - put)
    stake = _at_stake(value, injected.diff().fillna(0.0), start, end)
    return gain, gain / stake if stake else 0.0


def ticker_changes(values: pd.DataFrame, days: int) -> pd.Series:
    """Per-ticker % change over the last ~`days` calendar days.

    The per-name counterpart of `basket_change`, read off the same frame with
    the same window (`_window`). A ticker priced at only
    one endpoint (or starting from zero) is dropped rather than reported as an
    infinite move. Empty Series when the frame doesn't cover the window.
    """
    span = _window(values.index, days)
    if span is None:
        return pd.Series(dtype=float)
    start, end = span
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
    span = _window(values.index, days)
    if span is None:
        return pd.Series(dtype=float)
    start, end = span
    first, last = values.loc[start], values.loc[end]
    both = first.notna() & last.notna()
    return last[both] - first[both]


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
