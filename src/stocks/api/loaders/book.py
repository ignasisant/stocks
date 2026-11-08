"""The book priced: positions, value, weights, history and the basket report."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stocks import obs
from stocks.analysis import naive_dates
from stocks.analysis.portfolio import (
    book_history,
    plausible_closes,
    position_values_history,
    positions_frame,
)
from stocks.api.cache import ttl_cache
from stocks.api.loaders.closes import _close_series, _held, _on_download, _stored_base
from stocks.api.loaders.keys import (
    _HELD_QUIET,
    _HELD_STALE,
    _LEDGER_TTL,
    _PRICES_TTL,
    ledger_state,
)
from stocks.portfolio.custody import Custody, by_position
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.positions import build


@_on_download
def _priced_positions(db: str, mtime: float, base: str, closes) -> pd.DataFrame:
    positions = ledger_state(db, mtime, base).positions
    vals = position_values_history(positions, base=base, closes=closes)
    latest = (
        {t: float(v) for t, v in vals.iloc[-1].items() if pd.notna(v)}
        if not vals.empty
        else None
    )
    return positions_frame(positions, base=base, values=latest)


@ttl_cache(_PRICES_TTL, max_entries=16)
def _self_priced_positions(db: str, mtime: float, base: str) -> pd.DataFrame:
    """The table while Yahoo refuses the book's download.

    The live pass alone priced 7 of 47 names one throttled morning, and the
    Home row then set a 28k "Valor hoy" beside the 111k that went in. Whatever
    it misses reads the book's last kept frames instead (`_stored_base`) — a
    close a day old at most, flagged `stale` so the page can say so — and
    only a name those never held stays NaN.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.analysis import portfolio as analysis

    positions = ledger_state(db, mtime, base).positions
    try:
        values = analysis.market_values(positions, base=base)
    except YFRateLimitError:
        values = {}
    missing = [p for p in positions if p.ticker not in values]
    kept = _kept_values(db, missing, base) if missing else {}
    if not values and not kept:
        # Nothing at all: the caller's own degrade path, as before.
        raise YFRateLimitError()
    table = positions_frame(positions, base=base, values={**kept, **values})
    if not table.empty:
        table["stale"] = table.index.isin(list(kept))
    return table


def _kept_values(db: str, positions: list, base: str) -> dict[str, float]:
    """`base` value per position at its last close in the kept frames."""
    held = _stored_base(db)
    if held is None:
        return {}
    txs, _tickers = _held(db)
    closes = plausible_closes(_close_series(held[1], "Adj Close"), txs)
    with obs.swallow("prices.kept_values"):
        vals = position_values_history(positions, base=base, closes=closes)
        if not vals.empty:
            return {t: float(v) for t, v in vals.iloc[-1].items() if pd.notna(v)}
    return {}


def positions_table(db: str, mtime: float, base: str = "EUR") -> pd.DataFrame:
    """Per-position frame in `base`: shares, cost, live value, unrealised P/L.

    Values are the last row of `held_closes`, the download `history()` and
    `basket_values()` are built from too (`_on_download`), so every tile that
    prints the book's value reads the same prices.

    A name it has no series for reads NaN in `value` rather than zero, which
    is what keeps `priced_totals` from dividing an intact book's whole basis
    by a fraction of its market value. Prices itself only when `held_closes`
    refuses an incomplete download — Yahoo throttling — and then the history
    endpoints are refusing too, rather than disagreeing with it.
    """
    from yfinance.exceptions import YFRateLimitError

    try:
        return _priced_positions(db, mtime, base)
    except YFRateLimitError:
        return _self_priced_positions(db, mtime, base)


def book_value_today(
    db: str, mtime: float, base: str, hist: pd.DataFrame
) -> float | None:
    """What the book is worth today, one figure for every tile that prints it.

    The Positions tile sums the priced table; the Overview, the Risk tab and
    the projection read the last point of the replayed value path. The two are
    built off the same download, but by different arithmetic, and they landed
    a euro apart on a six-figure book ("Valor hoy" 146.196 against 146.197).
    The table is what the rest of the app quotes, so when every position
    priced it is the figure; otherwise the path (which carries the unpriced at
    cost) stands.
    """
    from stocks.analysis.portfolio import priced_totals

    table = positions_table(db, mtime, base)
    if not table.empty and "value" in table:
        _cost, value, unpriced = priced_totals(table)
        if not unpriced and value > 0:
            return float(value)
    series = hist["value"].dropna() if "value" in hist else pd.Series(dtype=float)
    return float(series.iloc[-1]) if not series.empty else None


def allocation_weights(
    db: str, mtime: float, base: str, meta: dict[str, dict], key: str, fallback
) -> dict[str, float]:
    """`key`'s buckets as shares of the book, off the priced positions table.

    The Allocation tab and the Pulse card each read their own backtest report,
    whose weights come from that download's last close and drop whatever has no
    series in its window — so one book printed Technology at 36% on one and
    41.6% on the other, and USD at 81% against 80.6%. Both read this instead:
    the rows the tiles print, priced ones only, as the slices' own value and
    cost sums already do. `fallback` is the report's own split, for a table
    with nothing priced.
    """
    from stocks.analysis.portfolio import allocation_parts

    table = positions_table(db, mtime, base)
    if table.empty or "value" not in table:
        return dict(fallback)
    amounts = {
        str(ticker): float(value) for ticker, value in table["value"].dropna().items()
    }
    parts = allocation_parts(amounts, meta, key)
    sums = {label: sum(held.values()) for label, held in parts.items()}
    total = sum(sums.values())
    if not total:
        return dict(fallback)
    return dict(sorted(((k, v / total) for k, v in sums.items()), key=lambda kv: -kv[1]))


def _clear_positions() -> None:
    _priced_positions.cache_clear()
    _self_priced_positions.cache_clear()  # ty: ignore[unresolved-attribute]


positions_table.cache_clear = _clear_positions  # ty: ignore[unresolved-attribute]


@_on_download
def history(db: str, mtime: float, base: str, closes):
    """Full-span daily history: (injected-vs-value frame, daily TWR, unpriced).

    Built from the same download as `positions_table`, so its last value is
    the one the Posiciones tile prints. No timer of its own: a rebuild is a
    third of a second, and an hour-old copy is what used to show a different
    "Valor de mercado" on Rendimiento real than on Posiciones.
    """
    return book_history(all_transactions(Path(db)), base=base, closes=closes)


# How far back the fixed basket reaches. The movers card's longest window is a
# month, and three months covers it with room to spare.
_BASKET_MONTHS = 3


@_on_download
def basket_values(db: str, mtime: float, base: str, closes) -> pd.DataFrame:
    """Daily `base` value per open position at *today's* quantities.

    The frame the day/week/month deltas are measured on, and NOT
    `history()`'s `value` column: that one is the book as it happened, so a
    deposit or an import inside the window lands in it and reads as a gain —
    a €12k book that took €38k on a Monday shows "+316% this week" when
    nothing moved. A basket held at today's shares cannot say that: every day
    carries the same quantities, so money moving in or out is invisible to it
    and only prices and rates move the line.

    Which also makes the question it answers a hypothetical one — what today's
    book would have done over the window, a name bought yesterday included,
    priced back across days nobody held it. That is the right question for
    "how is my portfolio doing" and the wrong one for "what did this account
    earn", which is `history()` and `/portfolio/performance`. A name with no
    price at one end of a window drops out there (`basket_change`) rather than
    being counted from zero.

    Values rather than closes, because the shares are in them: a book is
    judged in its reporting currency, so a position's move includes its FX
    move. Prices come off the book's shared download, sliced to the window —
    no request of its own.
    """
    positions = ledger_state(db, mtime, base).positions
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(months=_BASKET_MONTHS)
    window = {}
    for ticker, series in closes.items():
        # Series arrive naive or stamped in the exchange's zone depending on
        # the market; `naive_dates` is where the app flattens that.
        tail = series[naive_dates(series.index) >= cutoff]
        if not tail.empty:
            window[ticker] = tail
    return position_values_history(
        positions, period=f"{_BASKET_MONTHS}mo", base=base, closes=window
    )


def native_price(row, rates: dict[str, float]) -> float | None:
    """One share's price in the currency it trades in, backed out of `value`.

    `value` is shares * price * rate, so dividing by the shares and the rate
    (`spot_rates`) recovers the quote. Null rather than a guess when the row
    has no value or the pair is missing: a price under the wrong symbol is
    worse than none.
    """
    shares, value = row.get("shares"), row.get("value")
    rate = rates.get(str(row.get("ccy") or "").upper())
    if not shares or not rate or value is None or pd.isna(value):
        return None
    return float(value) / float(shares) / rate


@ttl_cache(_LEDGER_TTL, max_entries=32)
def native_positions(db: str, mtime: float):
    """Open positions carrying *native-currency* cost — identity FX, no network.

    What a per-ticker view needs: the share count and the average buy price in
    the currency the position actually trades in. Converting those to a
    reporting currency would price the whole book to answer a question about
    one name.
    """
    txs = all_transactions(Path(db))
    positions, _ = build(txs, to_base=lambda amount, ccy, day: amount)
    return {p.ticker: p for p in positions}


@ttl_cache(_LEDGER_TTL, max_entries=32)
def custody(db: str, mtime: float) -> dict[str, dict[str, Custody]]:
    """Open shares per (ticker, broker): which broker's account holds them.

    Identity FX like `native_positions` — the split is a share count, not a
    basis, so this stays off the network too.
    """
    return by_position(all_transactions(Path(db)), to_base=lambda a, c, d: a)


# Persisted and served stale like the book's own download (`_HELD_STALE`): the
# backtest downloads every held name again over its own window, seconds cold,
# and the risk tab and both Pulso cards wait on it. ~2 MB a book.
@ttl_cache(
    _LEDGER_TTL,
    max_entries=16,
    stale_s=_HELD_STALE,
    quiet_s=_HELD_QUIET,
    persist="basket_report",
    disk_max=8,
)
def basket_report(db: str, mtime: float, base: str, period: str):
    """Today's holdings backtested at fixed `base` weights over `period`.

    A risk profile of what is held *now* — not a performance figure, which is
    what `history` returns. The weights are rebuilt on one currency's footing
    after the fetch, because `analyze` weights in native prices and a book that
    is mostly USD with some EUR is measured wrong by that.

    So are the returns, and for the same reason. `analyze` reads them off
    native closes, which measured a book whose *weights* were in the reporting
    currency against moves that were not: the volatility, the drawdown, the
    betas and the whole correlation matrix came out with the currency leg
    missing — for a EUR reader in US names, the seven-odd annual points of
    EUR/USD simply were not in the answer. Per-position values in `base` are
    the same prices times the daily rate, and their ratio is the move that
    reader actually lived. The benchmarks are converted with them
    (`rebase_returns`), because a beta with the dollar on one side only is not
    a beta.
    """
    from stocks.analysis.portfolio import (
        analyze,
        first_owned,
        holdings_from_positions,
        rebase_report,
    )

    txs, positions, _ = ledger_state(db, mtime, base)
    if not positions:
        return None
    report = analyze(period=period, holdings=holdings_from_positions(positions))
    return rebase_report(report, positions, base, period, since=first_owned(txs))


def inception_period(first_trade: str) -> str:
    """The shortest fetch window that reaches back to the book's first trade.

    The same ladder the Portfolio page climbs for its "since inception" choice:
    yfinance only takes named periods, so the fetch is the next one up and the
    slice to the first trade happens afterwards (`basket_report_since`).
    """
    span = (pd.Timestamp.today().normalize() - pd.Timestamp(first_trade)).days
    if span <= 360:
        return "1y"
    if span <= 700:
        return "2y"
    if span <= 1780:
        return "5y"
    return "max"


def basket_report_since(db: str, mtime: float, base: str):
    """`basket_report` clipped to the book's first trade — the page's default.

    Measured from the stock's IPO the backtest would score years the reader
    never held anything: a volatility and a drawdown for money that was not
    there, and betas taken over the same borrowed past. So the basket returns,
    each benchmark's returns and the correlation input all start at the first
    transaction.

    A copy, never the cached report mutated in place: `basket_report` is
    memoized and shared with every other window (and with the Pulse page), and
    slicing it here would quietly shorten theirs too. After the rebase, not
    before — `rebase_report` rebuilds `returns` from the full download and
    would undo the slice.

    Not memoized: the slice is a few filters, and a memo of its own would keep
    the report it was cut from — and that report's stale mark — for an hour
    after `basket_report` had refreshed.
    """
    from dataclasses import replace

    txs = ledger_state(db, mtime, base).txs
    if not txs:
        return None
    first = min(t.date for t in txs)
    report = basket_report(db, mtime, base, inception_period(first))
    if report is None:
        return None
    start = pd.Timestamp(first)

    def since(obj):
        # Series come back naive or stamped in an exchange's zone depending on
        # the market; compare on the naive calendar date either way.
        return obj[naive_dates(obj.index) >= start]

    # The basket's daily return is sliced rather than rebuilt: it is weighted
    # per date (`portfolio_returns` renormalises each day over the names that
    # traded), so a day's figure does not depend on the days before it and the
    # slice is exactly what a rebuild over the clipped frame would give.
    return replace(
        report,
        returns=since(report.returns),
        bench_returns={b: since(r) for b, r in report.bench_returns.items()},
        port_returns=since(report.port_returns),
    )
