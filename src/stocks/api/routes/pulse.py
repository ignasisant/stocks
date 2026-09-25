"""What kind of market this is, and what it does to one particular book.

Two endpoints because they are two different kinds of fact. `/pulse` is the
same number for every reader — a composite of eight market inputs — so it takes
no account and every caller shares one cached build of it. `/pulse/book` is the
half nobody else can give: how much of the index's move lands on *this*
basket, whether its bonds still hedge its equities, and how much of its value
is priced in a currency its owner does not spend.

Every figure here can be null, and the difference matters. A component that
could not be built is named in `missing` rather than averaged away, and a book
with no price series gets nulls instead of a beta of zero — which would read as
a basket the market cannot move.
"""

from __future__ import annotations

from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from stocks.analysis import sentiment as sm
from stocks.analysis.portfolio import beta, portfolio_returns
from stocks.api import loaders
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import (
    BookBeta,
    Breadth,
    Pulse,
    PulseBook,
    PulseComponent,
    PulsePoint,
    TrendBlock,
    TrendRow,
    TrendTables,
)
from stocks.data import macro

router = APIRouter(tags=["pulse"])

# Windows the page quotes, in trading sessions. Named because they appear in
# several places and have to mean the same thing in all of them.
MONTH = 21
QUARTER = 63
# Rolling window for the beta and correlation series: short enough to move
# inside a regime, long enough not to be noise.
ROLL = 60
# How much of the composite's path a client needs to draw its sparkline. A
# quarter shows a shape; two years would be mostly flat at the right edge.
SPARK_DAYS = 90
# Dead band around a beta of 1. A book at 1.01 is not "leveraged to the index",
# and calling it that is how a rounding difference becomes a trading decision.
STANCE_BAND = 0.05
# The second line of betas, keyed by the i18n suffix the page already carries
# (`sentiment.beta_<key>`). Order is the card's reading order.
FACTOR_BETAS = (("duration", "TLT"), ("credit", "HYG"), ("em", "EEM"))
# What the sector ETFs' excess returns are measured against. SPY, not ^GSPC:
# the sector funds are total-return-ish ETFs and SPY is the ETF of the same
# index, so fund against fund keeps the dividend drag and the trading calendar
# on both sides. Streamlit's rotation table and book notes both read SPY, and
# the two apps must agree on which sectors "led".
ROTATION_BENCH = "SPY"


# Windows the page has always used: a year minus a quarter for the indices
# (200 sessions), the trend module's own slow average for the sectors, and a
# 60-session correlation read against where it stood a quarter back.
BREADTH_INDEX_WINDOW = 200
ROLL = 60
DRIFT_DAYS = 63


def _reason(exc: Exception) -> str:
    """Why a source died, as the key every block's `unavailable` carries.

    Three answers because the page says three different things: a Yahoo
    throttle clears in a minute, a network that is down does not, and anything
    else is a source that answered with nothing usable.
    """
    from urllib.error import URLError

    from yfinance.exceptions import YFRateLimitError

    if isinstance(exc, YFRateLimitError):
        return "rate_limited"
    return "offline" if isinstance(exc, URLError | OSError) else "no_data"


def _market_readings() -> tuple[
    Breadth | None, Breadth | None, float | None, float | None
]:
    """Breadth and the stock/bond correlation, or nothing at all.

    Never raises: these sit beside the composite and none of them is the reason
    a reader opened the page. A failed price burst costs the cards, not the
    score.
    """
    try:
        closes = loaders.pulse_closes()
    except Exception:
        return None, None, None, None

    def share(tickers: list[str], window: int) -> Breadth | None:
        hits, total = sm.above_ma_share(closes, tickers, window)
        # A denominator of zero is not "none are in an uptrend", it is "none
        # could be read" — and the card says nothing rather than saying that.
        return Breadth(hits=hits, total=total, window=window) if total else None

    indices = share([i.ticker for i in sm.INDICES], BREADTH_INDEX_WINDOW)
    sectors = share(list(sm.SECTOR_ETFS.values()), sm.TREND_SLOW)

    now = then = None
    spy, tlt = closes.get("SPY"), closes.get("TLT")
    if spy is not None and tlt is not None:
        series = sm.rolling_correlation(spy, tlt, window=ROLL)
        a, b = sm.drift(series, ago=DRIFT_DAYS)
        now, then = _num(a), _num(b)
    return indices, sectors, now, then


@router.get("/pulse", response_model=Pulse, summary="The market regime")
def pulse() -> Pulse:
    """The composite, its band, and the eight inputs behind it.

    `as_of` is not always today. The inputs do not land on one calendar — the
    volatility index prints an in-progress bar while equity closes are
    yesterday's and the credit spread arrives a day late — so the score is
    quoted from the last row that held enough of them, and this says which row
    that was.
    """
    # A throttle answers 200 with the reason, not a 503. The page draws four
    # blocks off this one call, and an error status would have each of them
    # drop its heading for a generic failure; a null score in the "unknown"
    # band with `unavailable` set lets every one keep its title and say which
    # source died — the same contract `/pulse/tables` keeps per block.
    try:
        built = loaders.market_pulse()
    except Exception as exc:
        return Pulse(regime="unknown", unavailable=_reason(exc), loaded_at=macro.as_of())
    history = built.history.dropna()
    tail = history.tail(SPARK_DAYS)
    # Three readings the composite does not contain and the page states beside
    # it: how broad the uptrend is, and whether bonds are still cushioning
    # equities. Market-wide, so they belong on this account-free endpoint —
    # `/pulse/book` answers the version of the correlation question that is
    # about one reader's own basket, which is a different pair entirely.
    indices, sectors, corr, corr_then = _market_readings()
    return Pulse(
        score=_num(built.score),
        regime=built.regime,
        as_of=str(pd.Timestamp(built.as_of).date()) if built.as_of is not None else None,
        run=sm.regime_run(history),
        components=[
            PulseComponent(
                key=component.key,
                score=_num(component.score),
                raw=_num(component.raw),
                # The reading in its own units, formatted by the registry that
                # knows them: the eight raws are a percent, a ratio, an index
                # level and a spread, and a client handed only `raw` has to
                # guess which — Streamlit prints exactly this string.
                text=component.text if component.raw == component.raw else None,
                then=_num(component.then),
            )
            for component in built.components
        ],
        missing=list(built.missing),
        history=[
            PulsePoint(date=str(pd.Timestamp(day).date()), score=float(score))
            for day, score in tail.items()
        ],
        breadth_indices=indices,
        breadth_sectors=sectors,
        stock_bond_correlation=corr,
        stock_bond_correlation_then=corr_then,
        # The page's "loaded …" caption, in the server's own clock and
        # spelling — `macro.as_of()`, the same call Streamlit makes — rather
        # than the browser's, which is neither UTC-honest on every device nor
        # the machine that fetched the prices.
        loaded_at=macro.as_of(),
    )


@router.get(
    "/pulse/book", response_model=PulseBook, summary="What the regime does here"
)
def book(account: Account, base: Base = None) -> PulseBook:
    """The regime restated as this account's own exposure.

    Each figure is computed only when the series it needs came back, and stays
    null otherwise. That is the difference between "the market cannot move this
    book" and "nobody could measure whether it does".
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    answer = PulseBook(base=ccy)
    # The replay prices the ledger, so it can hit the same throttle as the
    # benchmarks. Nothing below survives without it — not even the weights —
    # so this is the one failure that empties the card, and it still says why.
    try:
        report = loaders.basket_report(db, mtime, ccy, "2y")
    except Exception as exc:
        answer.unavailable = _reason(exc)
        return answer
    if report is None or not report.weights:
        return answer

    # The book's own shape first, because it needs no benchmark series: which
    # currencies the value is priced in and which sectors it sits in are read
    # off the positions, and a Yahoo throttle on the index closes is no reason
    # to blank them. `sentiment.py` keeps these tiles through the same outage.
    currency = report.allocation("currency")
    answer.currency_weights = {
        str(name): float(weight) for name, weight in currency.items()
    }
    answer.usd_share = float(answer.currency_weights.get("USD", 0.0))
    sectors = report.allocation("sector")
    answer.sector_weights = {
        str(name): float(weight) for name, weight in sectors.items() if weight == weight
    }

    # The benchmarks, degrading like `_market_readings`: a failed burst costs
    # the betas and correlations — each already null when its series is
    # absent — and names why, instead of erroring the whole response.
    try:
        closes = loaders.pulse_closes()
    except Exception as exc:
        closes = {}
        answer.unavailable = _reason(exc)
    returns = sm.naive_index(portfolio_returns(report.returns, report.weights))
    if returns.empty:
        return answer

    # How much of the index's move lands here, and whether that is drifting.
    spx = closes.get("^GSPC")
    if spx is not None and not spx.dropna().empty:
        bench = sm.naive_index(spx.dropna().pct_change().iloc[1:])
        value = beta(returns, bench)
        now, then = sm.drift(sm.rolling_beta(returns, bench, window=ROLL), ago=QUARTER)
        answer.beta = _num(value)
        answer.beta_rolling = _num(now)
        answer.beta_rolling_then = _num(then)
        if value == value:
            answer.stance = (
                "amplify"
                if value > 1 + STANCE_BAND
                else "cushion"
                if value < 1 - STANCE_BAND
                else "track"
            )

    # The other three betas the Streamlit card quotes: to the long bond, to
    # high-yield credit and to emerging markets. The same regression as the
    # equity one, on the same EUR-rebased basket returns — a product decision,
    # so all five tiles read on one currency basis rather than four in euros
    # and one in whatever each benchmark trades in. Each is its own row and
    # each can be null on its own: a missing HYG series costs the credit tile,
    # not the card.
    for key, ticker in FACTOR_BETAS:
        series = closes.get(ticker)
        if series is None or series.dropna().empty:
            answer.betas.append(BookBeta(key=key, ticker=ticker))
            continue
        bench = sm.naive_index(series.dropna().pct_change().iloc[1:])
        now, then = sm.drift(sm.rolling_beta(returns, bench, window=ROLL), ago=QUARTER)
        answer.betas.append(
            BookBeta(
                key=key,
                ticker=ticker,
                beta=_num(beta(returns, bench)),
                rolling=_num(now),
                rolling_then=_num(then),
            )
        )

    # Are the bonds still hedging the equities?
    tlt = closes.get("TLT")
    if tlt is not None and not tlt.dropna().empty:
        rolling = sm.rolling_correlation((1 + returns).cumprod(), tlt, window=ROLL)
        now, then = sm.drift(rolling, ago=QUARTER)
        answer.bond_correlation = _num(now)
        answer.bond_correlation_then = _num(then)

    # Currency: what last month's move in the dollar did to the return. The
    # share itself was filled above, before any series was needed.
    moves: dict[str, float] = {}
    eurusd = closes.get("EURUSD=X")
    if eurusd is not None and not eurusd.dropna().empty:
        # EURUSD=X is dollars per euro, so the dollar's own move against the
        # euro is the inverse of the pair's. Inverting here is the difference
        # between reporting a drag and reporting a tailwind.
        move = sm.pct_over(eurusd, MONTH)
        if move == move:
            moves["USD"] = 1.0 / (1.0 + move) - 1.0
    drag, _contributions = sm.fx_exposure(currency, moves, base=ccy)
    answer.fx_drag = _num(drag)

    # Sectors: how much of the month's rotation the book caught, and where it
    # actually sits against the benchmark.
    excess = sm.relative_strength(closes, sm.SECTOR_ETFS, ROTATION_BENCH, MONTH)
    if not sectors.empty and not excess.empty:
        answer.rotation_capture = _num(sm.rotation_capture(sectors, excess))
    benchmark = pd.Series(loaders.benchmark_sectors(), dtype=float)
    if not sectors.empty and not benchmark.empty:
        answer.sector_tilt = {
            str(name): float(weight)
            for name, weight in sm.tilt(sectors, benchmark).items()
            if weight == weight
        }
    return answer


# --------------------------------------------------------------- the detail
# Six blocks behind one tab strip on the page. They share two fetches, so they
# share one route: splitting them would have six clients warm the same two
# caches and would let the row shape drift apart six ways.

HORIZONS = {"week": 5, "month": 21, "quarter": 63, "year": 252}
BLOCKS = (
    "indices", "gauges", "rates", "inflation", "rotation", "cross", "factors",
)
# Rows each block is configured to carry — the tab badges. Read off the same
# registries the blocks iterate, so a series added to one of them moves its
# badge too. Fixed rather than counted from what drew: `sentiment.py` puts
# these on the tab strip before any fetch, and a tab whose count vanished
# during a throttle reads as a block with nothing in it. Inflation is its
# Eurostat areas plus the US CPI row `macro.inflation()` appends.
EXPECTED = {
    "indices": len(sm.INDICES),
    "gauges": len(sm.GAUGES),
    "rates": len(sm.RATE_ROWS),
    "inflation": len(macro.INFLATION_AREAS) + 1,
    "rotation": len(sm.SECTOR_ETFS),
    "factors": len(sm.FACTOR_PAIRS),
    "cross": len(sm.MACRO_ASSETS),
}
# A gauge whose last bar is more than a week behind the freshest bar in its own
# block has been dropped by its publisher. Measured against the block and not
# the calendar: on a Monday morning every gauge is Friday's and none is stale.
STALE_DAYS = 7


def _tail(series: pd.Series) -> list[float]:
    return [float(v) for v in series.dropna().iloc[-SPARK_DAYS:]]


def _price_row(key: str, series: pd.Series, *, name: str = "", welcome: int = 1):
    clean = series.dropna()
    return TrendRow(
        key=key,
        name=name,
        value=_num(clean.iloc[-1]),
        changes={k: float(v) for k, v in sm.pct_changes(clean, HORIZONS).items()},
        spark=_tail(clean),
        state=sm.trend_state(clean),
        welcome=welcome,
        as_of=str(pd.Timestamp(clean.index[-1]).date()),
    )


def _indices(closes: dict[str, pd.Series], weights: dict[str, float]) -> TrendBlock:
    """Headline indices, ordered by the geography the reader actually holds.

    An index with no country mapping keeps its place at the back rather than
    being dropped: the global read is still worth showing to someone holding
    only Spain.
    """
    order = (
        sm.pin_order(sm.INDICES, pd.Series(weights, dtype=float))
        if weights
        else list(sm.INDICES)
    )
    rows = []
    for index in order:
        series = closes.get(index.ticker)
        if series is None or series.dropna().empty:
            continue
        row = _price_row(index.ticker, series, name=index.name)
        share = sum(weights.get(country, 0.0) for country in index.countries)
        row.weight = share if share >= 0.01 else None
        rows.append(row)
    return TrendBlock(block="indices", unit="percent", rows=rows)


def _gauges(closes: dict[str, pd.Series]) -> TrendBlock:
    """Volatility gauges: level, direction, and where in their own year.

    The year figure is a percentile, not a twelve-month change: these series
    mean-revert, and a percent change over a year on one of them is close to
    meaningless.
    """
    bars = [
        closes[g.ticker].dropna().index[-1]
        for g in sm.GAUGES
        if g.ticker in closes and not closes[g.ticker].dropna().empty
    ]
    newest = max(bars) if bars else None
    rows = []
    for gauge in sm.GAUGES:
        series = closes.get(gauge.ticker)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        row = _price_row(
            gauge.ticker,
            clean,
            name=gauge.name,
            welcome=-1 if gauge.high_is_fear else 1,
        )
        row.changes.pop("year", None)
        row.percentile = _num(sm.percentile_now(clean))
        row.percentile_then = _num(sm.percentile_then(clean, ago=MONTH))
        behind = newest is not None and (newest - clean.index[-1]).days > STALE_DAYS
        row.stale = bool(behind)
        if row.stale:
            row.state = "stale"
        rows.append(row)
    return TrendBlock(block="gauges", unit="percent", rows=rows)


def _rates(series_by_id: dict[str, pd.Series]) -> TrendBlock:
    """Yields, curve slopes and credit spreads, quoted in basis points.

    A percent change of a percentage rate reads like a price move and is not
    one: "the 10-year rose 7.4%" is how a reader misreads 33 basis points.
    """
    rows = []
    for series_id, (suffix, welcome) in sm.RATE_ROWS.items():
        series = series_by_id.get(series_id)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        rows.append(
            TrendRow(
                key=series_id,
                name=suffix,
                value=_num(clean.iloc[-1]),
                changes={
                    k: float(v) * 100
                    for k, v in sm.changes(clean, HORIZONS).items()
                },
                spark=_tail(clean),
                # A policy rate steps when a committee decides and is flat in
                # between, so a moving-average trend label on it would be noise
                # dressed as a signal.
                state=None if welcome == 0 else sm.trend_state(clean),
                welcome=welcome,
            )
        )
    # The Chicago Fed's financial conditions index. `pulse_rate_rows` already
    # fetches it — it was being dropped on the floor here, so the page that
    # wanted to quote it could not, while the request paid for it anyway.
    # Kept out of RATE_ROWS because it is an index, not a rate: no basis
    # points, no curve, and a client renders it beside the table rather than
    # inside it.
    conditions = series_by_id.get("NFCI")
    if conditions is not None and not conditions.dropna().empty:
        clean = conditions.dropna()
        rows.append(
            TrendRow(
                key="NFCI",
                name="financial_conditions",
                value=_num(clean.iloc[-1]),
                changes={
                    k: float(v) for k, v in sm.changes(clean, HORIZONS).items()
                },
                spark=_tail(clean),
                state=sm.trend_state(clean),
                # Tighter conditions are the bad direction, and the index rises
                # as they tighten.
                welcome=-1,
                as_of=str(pd.Timestamp(clean.index[-1]).date()),
            )
        )
    return TrendBlock(block="rates", unit="basis_points", rows=rows)


def _inflation(frame: pd.DataFrame) -> TrendBlock:
    """Annual inflation per area. Percentage points, not percent of a percent.

    `macro.inflation()` is one ROW per area — area, period, headline, core,
    prior, six_months, momentum, path — and not a column per area of a daily
    series like everything else on this screen. So this block does not compute
    its own horizons: the source already decided which two comparisons mean
    something for a monthly print, and inventing a "week" change for a series
    published twelve times a year would be arithmetic on data that does not
    exist.

    `period` rides in `name` because each area prints on its own month: the
    euro-area flash estimate and the US CPI release are weeks apart, and one
    "latest" label over both silently misdates one of them.
    """
    rows = []
    for _, row in frame.iterrows():
        headline = _num(row.get("headline"))
        if headline is None:
            continue
        changes = {}
        prior, momentum = _num(row.get("prior")), _num(row.get("momentum"))
        if prior is not None:
            changes["print"] = headline - prior
        if momentum is not None:
            changes["half_year"] = momentum
        path = [float(v) for v in (row.get("path") or []) if v == v]
        rows.append(
            TrendRow(
                key=str(row.get("area") or ""),
                name=str(row.get("period") or ""),
                value=headline,
                changes=changes,
                spark=path,
                # A trend label wants a daily series behind a moving average.
                # Fourteen monthly points is not that, and `half_year` already
                # says which way this is going.
                state=None,
                # The rate with food and energy taken out. It is on the frame
                # and was being dropped; the headline alone cannot say whether
                # a fall is the oil price or the trend.
                core=_num(row.get("core")),
                welcome=-1,  # cooling inflation is the welcome direction
            )
        )
    return TrendBlock(block="inflation", unit="points", rows=rows)


def _rotation(
    closes: dict[str, pd.Series],
    sectors: dict[str, float],
    benchmark: dict[str, float] | None = None,
) -> TrendBlock:
    """Sector ETFs against the index, joined to the reader's own weights.

    `changes` here are excess returns over the S&P, not raw moves: the question
    the block answers is which sectors led, and a difference of two numbers the
    reader can both see is the answer to it.
    """
    rows = []
    for sector, ticker in sm.SECTOR_ETFS.items():
        series = closes.get(ticker)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        excess = {}
        bench = closes.get(ROTATION_BENCH)
        if bench is not None and not bench.dropna().empty:
            for name, days in HORIZONS.items():
                own, base = sm.pct_over(clean, days), sm.pct_over(bench, days)
                if own == own and base == base:
                    excess[name] = float(own - base)
        rows.append(
            TrendRow(
                key=ticker,
                name=sector,
                value=_num(clean.iloc[-1]),
                changes=excess,
                spark=_tail(clean),
                state=sm.trend_state(clean),
                welcome=1,
                # Zero and unknown are different facts and the block's own
                # caption depends on the difference: "a sector you do not hold
                # counts as zero" is only true for a reader who has a book at
                # all. Null is reserved for the reader who has none.
                weight=(
                    _num(sectors.get(sector, 0.0)) if sectors else None
                ),
                spy_weight=_num((benchmark or {}).get(sector)),
            )
        )
    return TrendBlock(block="rotation", unit="percent", rows=rows)


def _factors(closes: dict[str, pd.Series]) -> TrendBlock:
    """Factor pairs as one ratio each: growth over value, small over large.

    A pair rises when the first side leads. That is a tilt and not a signal,
    and the catalog's own help text says so — the block exists because "growth
    is up 4% and value is up 3%" is two numbers a reader has to subtract, and
    the subtraction is the reading.

    The ratio is built here rather than fetched because both legs are already
    in the same bulk download the rest of this file reads; a pair with either
    leg missing is dropped rather than half-drawn.
    """
    rows = []
    for key, first, second in sm.FACTOR_PAIRS:
        top, bottom = closes.get(first), closes.get(second)
        if top is None or bottom is None:
            continue
        ratio = (top / bottom).dropna()
        if ratio.empty:
            continue
        rows.append(
            TrendRow(
                key=key,
                name=f"{first}/{second}",
                value=_num(ratio.iloc[-1]),
                changes={
                    k: float(v) for k, v in sm.pct_changes(ratio, HORIZONS).items()
                },
                spark=_tail(ratio),
                state=sm.trend_state(ratio),
                # Neither side of a tilt is the good news: which one a reader
                # wants leading is a question about their own book.
                welcome=0,
                as_of=str(pd.Timestamp(ratio.index[-1]).date()),
            )
        )
    return TrendBlock(block="factors", unit="percent", rows=rows)


def _cross(closes: dict[str, pd.Series]) -> TrendBlock:
    """The dollar, metals, energy and crypto — the read behind the equity move."""
    rows = []
    for ticker, name, _fmt in sm.MACRO_ASSETS:
        series = closes.get(ticker)
        if series is None or series.dropna().empty:
            continue
        rows.append(_price_row(ticker, series, name=name, welcome=0))
    return TrendBlock(block="cross", unit="percent", rows=rows)


@router.get("/pulse/tables", response_model=TrendTables, summary="The detail blocks")
def tables(
    account: Account,
    base: Base = None,
    blocks: Annotated[
        str | None,
        Query(description=f"Comma-separated subset of {', '.join(BLOCKS)}."),
    ] = None,
) -> TrendTables:
    """Six blocks of the same row: level, four horizons, a spark, a trend state.

    Each block fails on its own. Yahoo throttles datacenter IPs and FRED
    tarpits some user agents, so a block whose source died keeps its place with
    `unavailable` set rather than vanishing — an absent block reads as "nothing
    is happening here", which is a different and wrong claim.

    Two of the six are personalised: the indices are ordered by the geography
    this account holds and carry that share, and the rotation rows carry the
    account's own sector weights.
    """
    wanted = BLOCKS
    if blocks:
        wanted = tuple(b.strip() for b in blocks.split(",") if b.strip())
        unknown = sorted(set(wanted) - set(BLOCKS))
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"unknown block(s): {', '.join(unknown)}",
            )

    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)

    def book_weights(key: str) -> dict[str, float]:
        """The account's own allocation, or nothing when it cannot be priced.

        A failure here personalises less; it never takes a block down, because
        the market read stands on its own for a reader with no book at all.
        """
        try:
            report = loaders.basket_report(db, mtime, ccy, "2y")
        except Exception:
            return {}
        if report is None or not report.weights:
            return {}
        return {str(k): float(v) for k, v in report.allocation(key).items()}

    out: list[TrendBlock] = []
    for name in wanted:
        try:
            if name == "inflation":
                out.append(_inflation(loaders.inflation()))
            elif name == "rates":
                out.append(_rates(loaders.pulse_rate_rows()))
            elif name == "indices":
                out.append(_indices(loaders.pulse_closes(), book_weights("country")))
            elif name == "gauges":
                out.append(_gauges(loaders.pulse_closes()))
            elif name == "rotation":
                # The benchmark's own split, so a reader's weight is an over-
                # or underweight against something rather than a bare number.
                # It never takes the block down: a failed look-through costs a
                # column, not the table.
                try:
                    bench = loaders.benchmark_sectors()
                except Exception:
                    bench = {}
                out.append(
                    _rotation(
                        loaders.pulse_closes(), book_weights("sector"), bench
                    )
                )
            elif name == "factors":
                out.append(_factors(loaders.pulse_closes()))
            else:
                out.append(_cross(loaders.pulse_closes()))
        except Exception as exc:
            out.append(TrendBlock(block=name, unit="percent", unavailable=_reason(exc)))
        out[-1].expected = EXPECTED.get(name)
        if not out[-1].rows and out[-1].unavailable is None:
            out[-1].unavailable = "no_data"
    return TrendTables(blocks=out)
