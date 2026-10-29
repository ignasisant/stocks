"""One company's page: its bars, its live quote, its calendar, your position.

Split along the same lines the Ticker page redraws: the range control changes
the bars and nothing else, so the bars are their own request. What is *not*
split off is presentation — no hover strings, no formatted money, no colours.
A day move is a fraction and a session label; how it reads in Spanish is the
client's problem, and duplicating that here is how two front ends start
disagreeing about what a number says.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal, cast

import pandas as pd
from fastapi import APIRouter, HTTPException, Path, Query, status
from yfinance.exceptions import YFRateLimitError

from stocks import obs
from stocks.analysis import crypto_market, review
from stocks.analysis import dcf as dcf_model
from stocks.analysis import trend as trend_model
from stocks.analysis.compare import (
    INDICES,
    OFFERED_PEERS,
    OPENING_PEERS,
    day_index,
    rates_into,
)
from stocks.analysis.compare import MAX_OTHERS as MAX_COMPARED
from stocks.analysis.compare import RANGES as COMPARE_RANGES
from stocks.analysis.compare import lines as compare_lines
from stocks.analysis.fundamentals import (
    KPI_SOURCES,
    METRIC_ORDER,
    annual_financials,
    compute_metrics,
    format_value,
    fundamental_tiles,
    lens_verdict,
    missing_reasons,
    peer_band,
    quarterly_eps,
    verdict,
)
from stocks.analysis.history import PERIODS, bar_interval, listed, rangebreaks, ranges
from stocks.analysis.listing import (
    listing_currencies,
    restate_position,
    restate_trades,
)
from stocks.analysis.moat import PILLAR_WEIGHTS, moat_score
from stocks.analysis.pe_history import DISPLAY_WINDOWS, window_stats
from stocks.analysis.portfolio import market_live, session_quote
from stocks.analysis.sentiment import SECTOR_ETFS
from stocks.api import loaders
from stocks.api.cache import carried
from stocks.api.deps import Account, Base, Writer, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.jsonsafe import scalar as _scalar
from stocks.api.schemas import (
    AnalystMonth,
    Analysts,
    AnalystTargets,
    AnnualRow,
    AssetStats,
    Bars,
    CashYield,
    ClosedEnd,
    CompareLine,
    CompareOffer,
    Comparison,
    Custodian,
    CycleEvent,
    Dcf,
    EarningsEvent,
    EpsRevisionRow,
    EuShortPositions,
    Financials,
    Fund,
    FundHolding,
    Insiders,
    InsiderSummary,
    InsiderTrade,
    Kpi,
    Metrics,
    MetricTile,
    Moat,
    MoatPillar,
    OptionsView,
    Peer,
    Peers,
    PeerScope,
    PriceEvents,
    Profile,
    ProjectedRow,
    Quote,
    RatingChange,
    ShortHolderRow,
    Shorts,
    SourceCheck,
    SourcedFigure,
    TickerJudged,
    TickerPosition,
    TickerSplit,
    TickerSplitPick,
    TickerSplits,
    TickerSplitsApplied,
    Trade,
    Trend,
    UsShortInterest,
    Valuation,
    ValuationWindow,
)
from stocks.config import CURRENCIES
from stocks.data import shorts as short_data
from stocks.data.asset_kind import BOND_FUND, CRYPTO, FUND_KINDS, MONEY_MARKET
from stocks.data.bafin import insider_transactions as bafin_transactions
from stocks.data.cnmv import insider_transactions as cnmv_transactions
from stocks.data.cnmv import spanish_listing
from stocks.data.crypto import COIN_CATEGORY, CYCLE_EVENTS, is_crypto, split_pair
from stocks.data.estimates import (
    MIN_COVERAGE,
    consensus,
    eps_revisions,
    estimate_currency,
    projection,
    rating_trend,
    target_dispersion,
)
from stocks.data.funds import is_fund
from stocks.data.insiders import CODE_LABELS, summarize
from stocks.portfolio import platforms
from stocks.portfolio.custody import UNKNOWN as BROKER_UNKNOWN
from stocks.portfolio.custody import mix as custody_mix

router = APIRouter(prefix="/ticker", tags=["ticker"])

Symbol = Annotated[
    str, Path(min_length=1, max_length=32, description="Ticker, e.g. AAPL or BTC-EUR.")
]
Range = Annotated[
    str,
    Query(
        alias="range",
        description=f"Display range. One of: {', '.join(PERIODS)}.",
    ),
]

# Indicator columns `analysis.history` appends. Named here so the response shape
# is a promise rather than whatever the frame happened to carry.
_SERIES = (
    "Open", "High", "Low", "Close", "Volume", "SMA20", "SMA50", "SMA200", "RSI14",
)

# The two custody buckets that are not brands: a hand-entered row, and shares
# no import note attributes. They ship without a name because theirs is a
# translated string — see `schemas.Custodian`.
_GENERIC_BROKERS = frozenset({"manual", BROKER_UNKNOWN})


def _column(df: pd.DataFrame, name: str) -> list[float | None]:
    """One column as JSON, with NaN as null.

    An indicator's warm-up is genuinely absent, not zero: SMA50 has no value
    for the first 49 bars, and a chart that plots those as 0 draws a cliff.
    """
    if name not in df:
        return []
    return [None if pd.isna(v) else float(v) for v in df[name]]


@router.get("/{symbol}/bars", response_model=Bars, summary="Price history")
def bars(symbol: Symbol, range: Range = "1y") -> Bars:
    """OHLCV plus indicators for one range label, trimmed to its window.

    Timestamps are exchange-local wall time with no zone, matching the axis the
    app draws: Plotly.js has no timezone support, so stamping them UTC would
    slide every session by its own offset. `rangebreaks` is what hides the
    closed-market gaps — pass it straight to the x-axis.
    """
    label = range.strip().lower()
    if label not in PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"range must be one of {', '.join(PERIODS)}",
        )
    ticker = symbol.strip().upper()
    df = loaders.price_bars(ticker, label)
    if df.empty:
        return Bars(
            ticker=ticker,
            range=label,
            interval=PERIODS[label][1],
            dates=[],
            ranges=list(PERIODS),
        )
    since = listed(df, label)
    size = bar_interval(df, label)
    return Bars(
        ticker=ticker,
        range=label,
        interval=size,
        dates=[str(ts) for ts in df.index],
        series={name: _column(df, name) for name in _SERIES},
        dividends=_column(df, "Dividends"),
        rangebreaks=rangebreaks(df, size),
        listed=since,
        ranges=ranges(df, since),
    )


@router.get("/{symbol}/trend", response_model=Trend, summary="Trend against its index")
def trend(symbol: Symbol) -> Trend:
    """The price against its 200-session average, its 12-1 momentum and 52-week
    high, and its return against the index of the market it trades on.

    Read off the chart's own 2y daily download (`loaders.daily_bars`), so a
    page that drew the 1y chart pays nothing more; the index closes are one
    shared memo entry per market. A money-market or bond fund gets the empty
    read: its price is a yield accruing, and "below its average" means
    nothing there.
    """
    ticker = symbol.strip().upper()
    return Trend(ticker=ticker, **asdict(read_trend(ticker)))


def read_trend(ticker: str) -> trend_model.TrendRead:
    """`trend`'s read, for the chat and the connector to share with the page."""
    if loaders.asset_kind(ticker) in (MONEY_MARKET, BOND_FUND):
        return trend_model.TrendRead()
    # The company's country only matters on a German floor, where APC.DE is
    # Apple and the DAX says nothing about it; elsewhere it is not asked.
    country = (
        loaders.listing_country(ticker) if trend_model.on_german_floor(ticker) else None
    )
    bench = trend_model.benchmark_for(ticker, country)
    with ThreadPoolExecutor(max_workers=2) as pool:
        bars = pool.submit(loaders.daily_bars, ticker)
        index = pool.submit(loaders.daily_closes, bench.ticker, "2y") if bench else None
        return trend_model.trend_read(
            bars.result(), index.result() if index else None, bench
        )


@router.get("/{symbol}/compare", response_model=Comparison, summary="Against the index")
def compare(
    symbol: Symbol,
    account: Account,
    range: Annotated[
        str,
        Query(alias="range", description=f"One of: {', '.join(COMPARE_RANGES)}."),
    ] = "1y",
    others: Annotated[
        str | None,
        Query(
            alias="with",
            description=(
                "Comma-separated symbols to draw beside this one, at most "
                f"{MAX_COMPARED}. Omitted: {', '.join(INDICES)}, the sector's ETF "
                f"and {OPENING_PEERS} related names. Empty: none."
            ),
        ),
    ] = None,
    base: Base = None,
) -> Comparison:
    """This listing against others over one window, in the reader's money.

    Every line is the total return of one unit of `base` put in on the
    subject's first session of the window (`analysis.compare`). The bars come
    off the same memo as `/bars`, so the subject — and an index another page
    already drew — costs no download.
    """
    label = range.strip().lower()
    if label not in COMPARE_RANGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"range must be one of {', '.join(COMPARE_RANGES)}",
        )
    ticker = symbol.strip().upper()
    ccy = reporting_currency(account, base)
    with ThreadPoolExecutor(max_workers=MAX_COMPARED + 4) as pool:
        shown = pool.submit(carried(loaders.price_bars), ticker, label)
        sector = pool.submit(carried(_sector_of), ticker)
        related = pool.submit(carried(_related_or_none), ticker)
        # An explicit list starts downloading at once; the opening one waits
        # on the sector and the rivals it is made of.
        asked = _compared(ticker, others) if others is not None else []
        closes = {
            name: pool.submit(carried(_closes_or_none), name, label)
            for name in [ticker, *asked]
        }
        own_sector = sector.result()
        peers = related.result()
        etf = SECTOR_ETFS.get(own_sector or "")
        shares = [peer for peer in peers if peer != ticker and not is_crypto(peer)]
        if others is None:
            opening = [*INDICES, *([etf] if etf else []), *shares[:OPENING_PEERS]]
            asked = _compared(ticker, ",".join(opening))
            closes |= {
                name: pool.submit(carried(_closes_or_none), name, label)
                for name in asked
            }
        names = [ticker, *asked]
        quoted = pool.submit(carried(listing_currencies), names)
        # Beside the downloads, not after them: a cold name is a spark request.
        labels = pool.submit(
            carried(loaders.listing_names),
            [*shares[:OFFERED_PEERS], *(n for n in names if n not in INDICES)],
        )
        df = shown.result()
        got = {name: future.result() for name, future in closes.items()}
        currencies = quoted.result()
        named = labels.result()

    offered = [CompareOffer(ticker=index, role="index") for index in INDICES]
    if etf and etf != ticker:
        offered.append(CompareOffer(ticker=etf, role="sector", sector=own_sector))
    offered += [
        CompareOffer(ticker=peer, name=named.get(peer, ""), role="peer")
        for peer in shares[:OFFERED_PEERS]
    ]
    if df.empty:
        return Comparison(ticker=ticker, range=label, base=ccy, dates=[], offered=offered)

    axis = day_index(df.index)
    rates, unpriced = rates_into(
        ccy, axis, {name: currencies.get(name) for name in names}
    )
    drawn = compare_lines(
        {name: s for name, s in got.items() if s is not None and name not in unpriced},
        rates,
        axis,
    )

    def role(name: str) -> Literal["subject", "index", "sector", "peer", "pick"]:
        if name == ticker:
            return "subject"
        if name in INDICES:
            return "index"
        if name == etf:
            return "sector"
        return "peer" if name in peers else "pick"

    return Comparison(
        ticker=ticker,
        range=label,
        base=ccy,
        dates=[str(day.date()) for day in axis],
        lines=[
            CompareLine(
                ticker=name,
                name="" if name in INDICES else named.get(name, ""),
                role=role(name),
                points=drawn[name],
            )
            for name in names
            if name in drawn
        ],
        offered=offered,
        missing=[name for name in asked if name not in drawn],
    )


def _compared(ticker: str, asked: str | None) -> list[str]:
    """The names `?with=` asks for, cleaned: upper-case, once each, never the
    subject, at most `MAX_COMPARED`."""
    raw = [part.strip().upper() for part in (asked or "").split(",")]
    out: list[str] = []
    for name in raw:
        if name and name != ticker and name not in out and len(name) <= 32:
            out.append(name)
    return out[:MAX_COMPARED]


def _closes_or_none(ticker: str, label: str) -> pd.Series | None:
    """One listing's closes, or None when Yahoo has none or refused: a line
    the card leaves off, not a failed card."""
    try:
        closes = loaders.bar_closes(ticker, label)
    except Exception as exc:  # noqa: BLE001
        obs.warn("api.compare_closes_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None
    return None if closes.dropna().empty else closes


def _sector_of(ticker: str) -> str | None:
    """The yfinance sector of a company, or None for a coin, a fund or a name
    Yahoo files none for. The profile memo first; `info` records into it."""
    from stocks.data.fetch import info, resolve
    from stocks.data.profiles import known

    if is_crypto(ticker):
        return None
    stored = known(resolve(ticker))
    if stored is not None:
        return stored.get("sector") or None
    try:
        return info(ticker).get("sector") or None
    except Exception:  # noqa: BLE001
        return None


def _related_or_none(ticker: str) -> tuple[str, ...]:
    return () if is_crypto(ticker) else loaders.related(ticker)


@router.get("/{symbol}/quote", response_model=Quote, summary="Live quote")
def quote(symbol: Symbol, base: Base = None) -> Quote:
    """Current price and day move, with the session the move belongs to.

    `market_open` is what the page uses to decide whether to override the last
    bar: inside the regular session the fetched history already tracks the live
    price, and only outside it does this quote say something the bars do not.

    `currency` and `price_base` are the one place this page says "that figure
    is not in your money" — the header otherwise prints a bare number a reader
    has no reason to doubt. No account dependency, like `/metrics`: the rate
    applies only when `?base=` is asked for explicitly.
    """
    ticker = symbol.strip().upper()
    snapshot = session_quote(ticker) or {}
    price = snapshot.get("price")
    ccy = _base_currency(base)
    currency = price_base = rate = as_of = None
    # Only when `?base=` asks for the conversion. The quote row names its own
    # currency; the fundamentals pull — seconds on a name the page has not
    # loaded yet, and this header is the first thing it draws — is asked only
    # when that row did not.
    if ccy and not is_crypto(ticker):
        currency = cast(str | None, snapshot.get("currency")) or cast(
            str | None, loaders.fundamentals(ticker).info.get("currency")
        )
        if price is not None and currency:
            price_base, rate, as_of = _price_in(ticker, price, currency, ccy)
    return Quote(
        ticker=ticker,
        price=price,
        pct=snapshot.get("pct"),
        session=snapshot.get("session"),
        as_of=snapshot.get("as_of"),
        market_open=market_live(ticker),
        currency=currency,
        price_base=price_base,
        fx_rate=rate,
        fx_as_of=as_of,
        base=ccy,
        high_52w=snapshot.get("high_52w"),
        low_52w=snapshot.get("low_52w"),
    )


def _price_in(
    ticker: str, price: float, native: str, base: str
) -> tuple[float | None, float | None, str | None]:
    """`price` restated in `base`, minor units (GBp) resolved first.

    Nothing when the two already agree, and nothing when the rate cannot be
    fetched — the same refusal `_market_cap_in` makes, generalised past
    dollars: a listing's own quote currency can be anything, not just USD.
    """
    from stocks.analysis.listing import quote_unit
    from stocks.data.fx import spot

    iso, scale = quote_unit(native)
    if iso is None or iso == base:
        return None, None, None
    try:
        rate, as_of = spot(iso, base)
    except Exception as exc:
        obs.warn("api.quote_fx_failed", ticker=ticker, native=iso, base=base,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None, None, None
    return price * scale * rate, rate, as_of


@router.get("/{symbol}/events", response_model=PriceEvents, summary="Chart events")
def events(symbol: Symbol) -> PriceEvents:
    """Reporting dates and what printed, for the verticals on the price chart.

    Dividends are deliberately absent: they ride in the history frame, so
    `/bars` already carries them and a second round trip would only risk the
    two disagreeing.

    A fund pays distributions but never reports, and a coin does neither, so
    both come back empty without spending a request on Yahoo answering "no
    earnings dates found". A coin's verticals are its cycle instead: the
    halvings, an ETF approval — dates of record, from `data.crypto`.
    """
    ticker = symbol.strip().upper()
    # A closed-end fund is asked from the cache only: `/profile` settles it on
    # the page's first request, and this one must not wait on EDGAR again.
    if pair := split_pair(ticker):
        return PriceEvents(
            ticker=ticker,
            cycle=[CycleEvent(date=day, kind=kind)
                   for day, kind in CYCLE_EVENTS.get(pair[0], ())],
        )
    if is_fund(ticker) or loaders.is_closed_end(ticker, fetch=False):
        return PriceEvents(ticker=ticker, earnings=[])
    dates, results = loaders.earnings(ticker)
    reported = {r.date: r for r in results}
    return PriceEvents(
        ticker=ticker,
        earnings=[
            EarningsEvent(
                date=str(day),
                eps_estimate=(r := reported.get(day)) and r.eps_estimate,
                reported_eps=r.reported_eps if r else None,
                surprise_pct=r.surprise_pct if r else None,
                beat=r.beat if r else None,
            )
            for day in dates
        ],
    )


@router.get(
    "/{symbol}/position",
    response_model=TickerPosition,
    summary="This account's holding in one ticker",
)
def position(symbol: Symbol, account: Account, base: Base = None) -> TickerPosition:
    """Shares, average buy price and broker split for one name.

    Cost is in the position's **own** currency, not the reporting one: pricing
    the whole book to answer a question about a single name is a round trip the
    page does not make either. `value` is the exception — it comes off the
    book's shared pricing pass, and is null while that pass has nothing (a
    throttled Yahoo, a symbol with no series). Null means unknown here, never
    zero.
    """
    ticker = symbol.strip().upper()
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    # The chart this answers for is the priced listing's series, and a
    # watchlist alias can make that another venue than the one the shares
    # were bought on (Revolut's dollar ASML, charted off the euro ASML.AS).
    # The basis and the fills are restated into the listing's quote so they
    # sit on the chart's axis (stocks.analysis.listing.restate_trades).
    code = listing_currencies([ticker]).get(ticker)
    fills = _trades(db, mtime, ticker, code)
    held = restate_position(
        loaders.native_positions(db, mtime).get(ticker),
        loaders.ledger_state(db, mtime)[0],
        code,
    )
    if held is None:
        # Closed, or never opened. The fills still travel: a chart that forgets
        # where somebody entered is missing the only part of it that was theirs.
        return TickerPosition(ticker=ticker, held=False, trades=fills)

    ccy = reporting_currency(account, base)
    # The book's pricing pass is the one network-bound step here, and the
    # fills above do not need it. A throttled Yahoo must cost the reply its
    # value and weight, not the whole answer: a 5xx here took every buy and
    # sell marker off the chart with it.
    try:
        table = loaders.positions_table(db, mtime, ccy)
    except Exception as exc:
        obs.warn("api.position_value_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        table = pd.DataFrame()
    value = None
    weight = None
    cost_base = None
    if not table.empty and ticker in table.index:
        raw = table.at[ticker, "value"]
        if pd.notna(raw):
            from stocks.analysis.portfolio import value_weights

            value = float(raw)
            share = value_weights(table).get(ticker)
            weight = None if share is None or pd.isna(share) else float(share)
            # The same row's basis, in the reporting currency at each trade
            # date's rate: what the page subtracts to print the gain the
            # Portfolio page prints, rather than a native gain restated today.
            basis = table.at[ticker, "cost"] if "cost" in table else None
            cost_base = None if basis is None or pd.isna(basis) else float(basis)

    brokers = loaders.custody(db, mtime).get(ticker, {})
    # Largest custodian first, and resolved here rather than by the client: the
    # key -> brand table is this package's, and a front end re-deriving it is a
    # second place for a rename to be missed.
    marks = [
        Custodian(
            broker=key,
            name="" if key in _GENERIC_BROKERS else platforms.broker_label(key),
            logo=loaders.brand_logo(key),
            shares=brokers[key].quantity,
            share=share,
        )
        for key, share in custody_mix(brokers)
    ]
    return TickerPosition(
        ticker=ticker,
        held=True,
        shares=held.quantity,
        currency=held.currency,
        cost_native=held.cost_native,
        avg_cost_native=held.avg_cost_native,
        base=ccy,
        value=value,
        weight=weight,
        cost_base=cost_base,
        trades=fills,
        brokers={name: c.quantity for name, c in brokers.items()},
        custody=marks,
    )


# A broker statement prints trades, not corporate actions, so a share bought
# before a split arrives as one AMZN at $2050 rather than twenty at $102.50, and
# the page then reads a 20x cost basis against today's price. The evidence is
# on this very page — the buy price against that day's close — so the page asks
# for it and repairs the book itself, through the edit journal so the reader
# can take it back (`corporate.missing_splits` holds the evidence rule).


def _split_gaps(db, ticker: str) -> list:
    """`corporate.missing_splits` for one name, on the unified labels.

    Relabelled like `own_fills`: the URL speaks the label `positions.build`
    unifies to, and a book that booked the buy under its ISIN would otherwise
    have nothing to price. No buy, no Yahoo round trip.
    """
    from stocks.data import fetch
    from stocks.portfolio import corporate, demo, transfers
    from stocks.portfolio.ledger import all_transactions

    rows = [
        tx
        for tx in transfers.relabel(demo.without(all_transactions(db)))
        if tx.ticker.upper() == ticker
    ]
    if not any(tx.action == "buy" for tx in rows):
        return []
    return corporate.missing_splits(
        rows, splits=fetch.splits, close_on=fetch.close_on, source="page"
    )


def _declined(db, ticker: str) -> set[str]:
    """Split days of this name the reader has written and then undone."""
    from stocks.portfolio import split_sweep

    return {day for _, day in split_sweep.declined(db, ticker)}


def _split(gap, declined: set[str] | None = None) -> TickerSplit:
    return TickerSplit(
        date=gap.tx.date,
        ratio=gap.ratio,
        held_before=gap.held_before,
        held_after=gap.held_after,
        priced_at=gap.priced_at,
        priced_on=gap.priced_on,
        market_close=gap.market_close,
        currency=gap.tx.currency,
        declined=gap.tx.date in (declined or set()),
    )


@router.get(
    "/{symbol}/splits",
    response_model=TickerSplits,
    summary="Splits this name's ledger is missing",
)
def missing_splits(symbol: Symbol, account: Account) -> TickerSplits:
    """Forward splits the book lacks for this name, oldest first.

    Its own request rather than a field on `/position`: the evidence is a
    Yahoo round trip (memoized per process), and the position's chart markers
    must not wait on it. Writes nothing.
    """
    from stocks.data import fetch

    ticker = symbol.strip().upper()
    gaps = _split_gaps(account.db, ticker)
    declined = _declined(account.db, ticker) if gaps else set()
    return TickerSplits(
        ticker=ticker,
        splits=[_split(gap, declined) for gap in gaps],
        throttled=fetch.throttle_remaining() > 0,
    )


@router.post(
    "/{symbol}/splits",
    response_model=TickerSplitsApplied,
    status_code=status.HTTP_201_CREATED,
    summary="Write the missing splits",
)
def apply_missing_splits(
    symbol: Symbol, account: Writer, body: TickerSplitPick
) -> TickerSplitsApplied:
    """Write the named splits as one journalled, undoable edit.

    The body names the days; the ratio and the row come from a scan run here
    and now, so a client cannot invent a split nor replay a stale one — a
    split another tab wrote a second ago is no longer missing. A day this scan
    does not propose is a 409 and nothing is written.
    """
    from stocks.portfolio import edits

    ticker = symbol.strip().upper()
    found = {gap.tx.date: gap for gap in _split_gaps(account.db, ticker)}
    picked = []
    for day in dict.fromkeys(d.strip() for d in body.dates):
        gap = found.get(day)
        if gap is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{ticker} on {day} is not a split this ledger is missing",
            )
        picked.append(gap)
    ops = [
        {"op": "add", "row": {k: getattr(gap.tx, k) for k in edits.FIELDS}}
        for gap in picked
    ]
    summary = ", ".join(f"{ticker} {gap.ratio:g}:1 split {gap.tx.date}" for gap in picked)
    try:
        planned = edits.plan(ops, account.db)
        done = edits.commit(
            ops, planned.token, source="api", summary=summary, path=account.db
        )
    except edits.Stale as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except edits.EditError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    obs.event("ledger.splits_repaired", n=len(picked), ticker=ticker, via="ticker")
    return TickerSplitsApplied(
        ticker=ticker, change_id=done.id, splits=[_split(gap) for gap in picked]
    )


# --------------------------------------------------- fundamentals and derivatives


@router.get("/{symbol}/metrics", response_model=Metrics, summary="KPI grid")
def metrics(symbol: Symbol, base: Base = None) -> Metrics:
    """Every KPI the framework tracks, raw and formatted, with its provenance.

    `level` rides on each one because it is the difference between a filed
    number and a forecast, and a screen that prints them alike is how a
    consensus figure ends up wearing a filing's authority. `verdict` is the
    cheap/fair/expensive band where one exists, and absent where it does not —
    never a neutral default, which would read as "fairly valued".
    """
    ticker = symbol.strip().upper()
    raw = loaders.fundamentals(ticker)
    computed = compute_metrics(raw)
    # No account dependency: every figure here is the company's, not the
    # reader's, and a route that demanded one would stop answering the scripts
    # that hold a token and name nobody. The single per-reader line — the market
    # cap in their own money — is asked for explicitly with `?base=`.
    ccy = _base_currency(base)
    cap, rate, as_of = _market_cap_in(computed, ccy) if ccy else (None, None, None)
    equity = str(computed.get("quote_type") or "EQUITY").upper() == "EQUITY"
    view = review.lens(computed)
    tiles = fundamental_tiles(view) if equity else fundamental_tiles(review.STANDARD)
    keys = list(dict.fromkeys([*METRIC_ORDER, *(tile.key for tile in tiles)]))
    scope, band = (
        _peer_band(ticker, computed, raw, [tile.key for tile in tiles])
        if equity
        else (None, {})
    )
    normal = review.peak_pe(computed) if equity else None
    if equity:
        _log_missing(ticker, raw, computed, view, [tile.key for tile in tiles])
    return Metrics(
        ticker=ticker,
        currency=cast(str | None, computed.get("currency")),
        quote_type=cast(str | None, computed.get("quote_type")),
        kpis=[_kpi(key, computed.get(key), computed, band.get(key)) for key in keys],
        grid=[
            MetricTile(key=tile.key, label_key=tile.label, help_key=tile.help)
            for tile in tiles
        ],
        lens=view,
        peers=scope,
        normal_pe=normal,
        reported_pe=_num(computed.get("pe_ttm_reported")),
        cautions=review.cautions(computed) if equity else [],
        judged=_judged(computed) if equity else None,
        market_cap_base=cap,
        market_cap_base_formatted=(
            format_value("market_cap", cap) if cap is not None else None
        ),
        fx_rate=rate,
        fx_as_of=as_of,
        base=ccy,
    )


def _judged(computed: dict) -> TickerJudged:
    """`review.judge_candidate` on the grid's own metrics: no request of its
    own, and the verdict the Review page gives the name as an outside row."""
    verdict = review.judge_candidate(computed, kind="stock")
    return TickerJudged(
        verdict=verdict.verdict,
        reasons=list(verdict.reasons),
        quality=_num(verdict.quality),
        cheapness=_num(verdict.cheapness),
    )


def _log_missing(ticker: str, raw, computed: dict, view: str, keys: list[str]) -> None:
    """One `data.missing` line per blank tile, once a window per ticker.

    `stocks logs stats --event data.missing --by reason` tells the gaps a
    company has (a loss has no P/E per growth) from the ones the feed left
    (no statements, a Yahoo field that never came), and `--by kpi` which tile
    goes blank most. A log line never fails the grid.
    """
    with obs.swallow("data.missing_failed", ticker=ticker):
        for key, reason in missing_reasons(raw, computed, keys).items():
            if obs.first_sighting("data.missing", (ticker, key)):
                obs.event("data.missing", ticker=ticker, kpi=key, reason=reason,
                          lens=view)


def _peer_band(
    ticker: str, computed: dict, raw, keys: list[str]
) -> tuple[PeerScope | None, dict[str, tuple[float, float, float]]]:
    """The rivals' P25/median/P75 per KPI, off the nightly sector scan.

    The scan, never a fetch: forty rivals' fundamentals would be the slowest
    thing on the page, and a night-old middle is the same middle. Nothing on
    any failure — a reference line must never be what fails the grid.
    """
    from stocks.analysis.sectors import peer_rows

    try:
        industry = cast(str | None, computed.get("industry"))
        sector = raw.info.get("sector")
        if not industry and not sector:
            return None, {}
        found = peer_rows(loaders.sector_scans(), ticker, industry, sector)
    except Exception as exc:
        obs.warn("api.peer_band_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None, {}
    if found is None:
        return None, {}
    kind, name, rows = found
    scope = PeerScope(kind=kind, name=name, count=len(rows))
    return scope, peer_band([computed, *rows], keys)


def _base_currency(asked: str | None) -> str | None:
    """`?base=` as a currency code, or None when the caller did not ask."""
    if not asked:
        return None
    code = asked.strip().upper()
    if code not in CURRENCIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"base must be one of {', '.join(CURRENCIES)}",
        )
    return code


def _market_cap_in(
    computed: dict, base: str
) -> tuple[float | None, float | None, str | None]:
    """Market cap restated in the reporting currency, when that says something.

    Only for a company quoting in dollars, which is what the page converts: a
    market cap is the one figure on this grid a reader compares against their
    own book, and the book is in their currency. Nothing when the two already
    agree, and nothing when the rate cannot be fetched — a page that cannot
    price it says so rather than printing an unconverted number as converted.
    """
    cap = computed.get("market_cap")
    if not cap or computed.get("currency") != "USD" or base == "USD":
        return None, None, None
    try:
        from stocks.data.fx import spot

        rate, as_of = spot("USD", base)
    except Exception as exc:
        obs.warn("api.market_cap_fx_failed", ticker=computed.get("ticker"),
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None, None, None
    return float(cap) * rate, rate, as_of


def _kpi(
    key: str,
    value,
    metrics: dict,
    band: tuple[float, float, float] | None = None,
) -> Kpi:
    """One KPI row, with its band's label AND the tone that band carries.

    Both, because the labels are a growing set — "net cash", "buybacks",
    "heavy dilution" — and a client colouring by label shows every band it has
    not heard of as neutral. Banded on the company's own lens
    (`lens_verdict`), and with its rivals' middle when the scan has one.
    """
    banded = lens_verdict(key, value, metrics)
    return Kpi(
        key=key,
        label=KPI_SOURCES[key].label,
        value=_scalar(value),
        formatted=format_value(key, value),
        unit=KPI_SOURCES[key].unit,
        level=KPI_SOURCES[key].level,
        verdict=banded[0] if banded else None,
        verdict_tone=banded[1] if banded else None,
        desc=KPI_SOURCES[key].desc,
        peer_band=list(band) if band else None,
    )


@router.get("/{symbol}/financials", response_model=Financials, summary="Statements")
def financials(symbol: Symbol) -> Financials:
    """Reported annual revenue / net income / EPS, quarterly EPS, and the
    consensus path beyond the last reported year.

    Reported and projected are separate fields rather than one series with a
    flag, so a caller cannot draw them as the same thing by forgetting to look.
    """
    ticker = symbol.strip().upper()
    raw = loaders.fundamentals(ticker)
    annual = annual_financials(raw)
    quarterly = quarterly_eps(raw)

    rows = [
        AnnualRow(
            year=str(year),
            revenue=_num(row.get("Revenue")),
            net_income=_num(row.get("Net Income")),
            eps=_num(row.get("EPS")),
        )
        for year, row in annual.iterrows()
    ] if not annual.empty else []

    projected: list[ProjectedRow] = []
    estimate_ccy = None
    if not annual.empty:
        raw_estimates = loaders.estimates(ticker)
        # Revenue's currency first, EPS's as the fallback, for when only one
        # table carries a code.
        estimate_ccy = estimate_currency(
            raw_estimates.revenue_estimate
        ) or estimate_currency(raw_estimates.earnings_estimate)
        frame = (
            pd.DataFrame()
            if _currency_clash(raw.info.get("financialCurrency"), estimate_ccy)
            else projection(raw_estimates, int(annual.index[-1]))
        )
        projected = [
            ProjectedRow(
                period=str(period),
                revenue=_num(row.get("Revenue")),
                revenue_low=_num(row.get("RevenueLow")),
                revenue_high=_num(row.get("RevenueHigh")),
                # True once the path runs past the last published estimate and
                # is carried forward on a growth rate. The page draws those
                # bars as "extrapolated" rather than "consensus", and a client
                # that cannot tell them apart is presenting a guess as a poll.
                revenue_extrapolated=bool(row.get("RevenueExt")),
                eps=_num(row.get("EPS")),
                eps_low=_num(row.get("EPSLow")),
                eps_high=_num(row.get("EPSHigh")),
                eps_extrapolated=bool(row.get("EPSExt")),
            )
            for period, row in frame.iterrows()
        ] if not frame.empty else []

    return Financials(
        ticker=ticker,
        currency=cast(str | None, raw.info.get("currency")),
        annual=rows,
        quarterly_eps=[
            {"period": str(period), "eps": _num(row.iloc[0])}
            for period, row in quarterly.iterrows()
        ] if not quarterly.empty else [],
        projection=projected,
        estimate_currency=estimate_ccy,
        source=getattr(raw, "source", None),
        source_years=list(getattr(raw, "source_years", ())),
    )


def _currency_clash(statements: str | None, estimates: str | None) -> bool:
    """Are the statements and the consensus in different currencies?

    An ADR is the case this exists for: TSMC files in TWD while its analysts
    quote per USD ADS, so the "forecast" bar would sit next to the reported ones
    thirty-odd times too short. The whole path is dropped then rather than
    converted — a share-count ratio sits between the two as well as a rate —
    and on the server, so no client can forget the check and draw the cliff.
    Unknown on either side is not a clash: most names carry no
    `financialCurrency` and are fine.
    """
    return bool(statements and estimates and statements != estimates)


def _trades(
    db: str, mtime: float, ticker: str, code: str | None = None
) -> list[Trade]:
    """The caller's buys and sells of one name, chart-ready.

    Relabelling and split-scaling both live in `corporate.own_fills`: the two
    corrections are invisible when missing, and one place to forget them is
    enough. `code` is the charted listing's
    quote currency: the fills are priced in it first, so a dollar buy of a
    name charted in euros marks the euro price it paid.
    """
    from stocks.portfolio.corporate import own_fills

    rows = restate_trades(loaders.ledger_state(db, mtime)[0], ticker, code)
    return [
        Trade(date=f.date, action=f.action, price=f.price, quantity=f.quantity)
        for f in own_fills(rows, ticker)
    ]


@router.get("/{symbol}/crypto", response_model=AssetStats, summary="Coin stats")
def crypto_stats(symbol: Symbol) -> AssetStats:
    """Market cap, 24h volume, supply and the 52-week range for a coin pair.

    The stand-in for the fundamentals, insider and comps blocks, none of which
    mean anything for a currency pair. Empty fields for anything that is not
    one, rather than a 404 — a client asking is not an error.
    """
    ticker = symbol.strip().upper()
    if not is_crypto(ticker):
        return AssetStats(ticker=ticker)
    info = loaders.crypto_info(ticker)
    coin, quote = split_pair(ticker) or (ticker, "USD")
    high_52w = _num(info.get("fiftyTwoWeekHigh"))
    circulating = _num(info.get("circulatingSupply"))
    # Peak, dilution and supply come from last night's scan, in the pair's own
    # currency. A coin it does not cover still gets a peak line — the 52-week
    # high, labelled as such — and no supply lines, never a guess.
    entry = (loaders.crypto_scan().get("coins") or {}).get(coin) or {}
    q = quote.lower()
    ath = _num((entry.get("ath") or {}).get(q))
    source = "scan" if ath is not None else ("52w" if high_52w is not None else None)
    if ath is not None and high_52w is not None:
        # A peak set since the scan ran is in the 52-week high already.
        ath = max(ath, high_52w)
    fdv = _num((entry.get("fdv") or {}).get(q))
    ratio = crypto_market.fdv_ratio(fdv, _num((entry.get("market_cap") or {}).get(q)))
    dilution = crypto_market.dilution_band(ratio)
    max_supply = _num(entry.get("max_supply"))
    rank = entry.get("rank")
    return AssetStats(
        ticker=ticker,
        quote=quote,
        market_cap=_num(info.get("marketCap")),
        volume_24h=_num(info.get("volume24Hr") or info.get("volume")),
        circulating_supply=circulating,
        high_52w=high_52w,
        low_52w=_num(info.get("fiftyTwoWeekLow")),
        ath=ath if ath is not None else high_52w,
        ath_date=(entry.get("ath_date") or {}).get(q) if source == "scan" else None,
        ath_source=source,
        fdv=fdv,
        fdv_ratio=ratio,
        dilution=dilution.key if dilution else None,
        max_supply=max_supply,
        total_supply=_num(entry.get("total_supply")),
        issued_pct=crypto_market.issued_share(
            _num(entry.get("circulating")) or circulating, max_supply),
        rank=int(rank) if isinstance(rank, (int, float)) else None,
        category=COIN_CATEGORY.get(coin),
    )


@router.get("/{symbol}/profile", response_model=Profile, summary="Name, logo, kind")
def profile(symbol: Symbol, account: Account) -> Profile:
    """What to put in the page header before any figure has arrived.

    Account-scoped because the name is: a watchlist entry is where someone
    writes down what they call a holding, and that must not leak between
    accounts.
    """
    ticker = symbol.strip().upper()
    resolved = loaders.display_symbol(ticker)
    # The name and the logo are the two lookups that can reach the network on
    # a cold memo, and neither needs the other: side by side, the header waits
    # for the slower one rather than for both. This is the first answer the
    # page draws and the one that gates its company sections, so its cold
    # cost is paid by every section under it. The asset kind rides alongside:
    # it settles which sections exist at all (a listed closed-end fund is a
    # fund although Yahoo calls it EQUITY, an index has no company), and after
    # the first visit it is a cache read.
    with ThreadPoolExecutor(max_workers=3) as pool:
        name = pool.submit(loaders.company_name, ticker, str(account.watchlist))
        logo = pool.submit(loaders.logo, ticker)
        kind = pool.submit(loaders.asset_kind, resolved)
        asset = kind.result()
        # After the kind, not beside it: both read the same `.info`, and the
        # kind has memoized it by now. A bare code is what a non-US listing
        # nobody holds gets from every local source, and "005930.KS" alone
        # does not say Samsung.
        known = name.result() or (
            "" if asset == CRYPTO else loaders.listing_name(resolved) or ""
        )
        missing = loaders.missing(ticker, str(account.db), known)
        return Profile(
            ticker=ticker,
            symbol=resolved,
            name=known,
            logo=logo.result(),
            is_crypto=asset == CRYPTO or is_crypto(resolved),
            is_fund=asset in FUND_KINDS,
            asset=None if missing else asset,
            found=not missing,
        )


@router.get("/{symbol}/peers", response_model=Peers, summary="Suggested comparables")
def peers(symbol: Symbol) -> Peers:
    """Who this company might reasonably be compared against.

    Suggestions only. Nothing is compared until a caller picks — the app makes
    the same choice, and for the same reason: each peer is a fundamentals pull,
    and a table nobody asked for spends them on a guess.

    Names from the SEC map and the profile memo, and one spark request for
    every twenty they leave unnamed (`loaders.listing_names`) — not a
    round-trip per suggestion, and not "7974.T" where Nintendo was meant.
    """
    ticker = symbol.strip().upper()
    rivals, watched = loaders.peer_groups(ticker)
    groups: tuple[tuple[tuple[str, ...], Literal["rival", "watched"]], ...] = (
        (rivals, "rival"),
        (watched, "watched"),
    )
    tagged = [
        (other, source)
        for group, source in groups
        for other in group
        if not is_crypto(other)
    ]
    named = loaders.listing_names([other for other, _ in tagged])
    return Peers(
        ticker=ticker,
        related=[
            Peer(ticker=other, name=named.get(other, ""), source=source)
            for other, source in tagged
        ],
    )


@router.get("/{symbol}/valuation", response_model=Valuation, summary="P/E history")
def valuation(symbol: Symbol) -> Valuation:
    """Today's P/E against its own past, and where in that distribution it sits.

    `source` is not decoration. The multiple is reconstructed from a filing
    feed, and which feed it came from — or that neither had the quarters — is
    what stops the number being acted on as if it were quoted.
    """
    ticker = symbol.strip().upper()
    result = loaders.valuation(ticker)
    series = result.get("pe")
    # The page's four ranges, not the domain's default set: half a year of a
    # company's own history cannot answer "is this expensive for this company",
    # and the app offers 1y/3y/5y/10y for exactly that reason. Recomputed here
    # rather than re-fetched — it is a pandas pass over a series already held.
    stats = (
        window_stats(series, windows=DISPLAY_WINDOWS)
        if series is not None and not series.empty
        else result.get("stats")
    )

    windows = [
        ValuationWindow(
            window=str(label),
            days=DISPLAY_WINDOWS.get(str(label), 0),
            mean=_num(row.get("mean")),
            median=_num(row.get("median")),
            low=_num(row.get("low")),
            high=_num(row.get("high")),
            percentile=_num(row.get("percentile")),
            premium=_num(row.get("premium")),
        )
        for label, row in stats.iterrows()
    ] if stats is not None and not stats.empty else []

    current = _num(result.get("current"))
    # Banded here, like every other verdict: a client picking its own P/E
    # thresholds is a second place for "expensive" to mean something else.
    banded = verdict("pe_ttm", current)
    return Valuation(
        ticker=ticker,
        source=result.get("source"),
        current=current,
        current_verdict=banded[0] if banded else None,
        current_tone=banded[1] if banded else None,
        dates=[str(pd.Timestamp(ts).date()) for ts in series.index]
        if series is not None and not series.empty
        else [],
        pe=[_num(v) for v in series] if series is not None and not series.empty else [],
        windows=windows,
    )


@router.get("/{symbol}/dcf", response_model=Dcf, summary="Discounted cash flow")
def dcf(symbol: Symbol) -> Dcf:
    """A plain five-year DCF on the firm's free cash flow, and its sensitivity.

    Not a price target: every input rides along so the page can show and edit
    them. A business with no positive trailing FCF, or one judged on a lens
    where FCF is not owner cash (banks, REITs, utilities), comes back with a
    `reason` and no number.
    """
    ticker = symbol.strip().upper()
    raw = loaders.fundamentals(ticker)
    out = dcf_model.compute(raw, compute_metrics(raw))
    return Dcf(
        ticker=ticker,
        reason=out.reason,
        currency=out.currency,
        price=_num(out.price),
        fcf=_num(out.fcf),
        net_debt=_num(out.net_debt),
        shares=_num(out.shares),
        growth=_num(out.growth),
        growth_source=out.growth_source,
        wacc=out.wacc,
        terminal=out.terminal,
        value=_num(out.value),
        upside=_num(out.upside),
        waccs=list(out.waccs),
        terminals=list(out.terminals),
        grid=[[_num(v) for v in row] for row in out.grid],
    )


@router.get("/{symbol}/moat", response_model=Moat, summary="Moat evidence")
def moat(symbol: Symbol) -> Moat:
    """A weighted read on durable advantage, pillar by pillar.

    Unscored pillars come back with a null score rather than a zero, and the
    composite is null when too few of them scored — a moat rating assembled
    from two pillars would be a guess with a number attached.
    """
    ticker = symbol.strip().upper()
    scored = moat_score(loaders.fundamentals(ticker))
    # The tone off the same band table the KPI grid's verdicts use.
    banded = verdict("moat", scored.score)
    return Moat(
        ticker=ticker,
        score=_num(scored.score),
        rating=scored.rating,
        rating_key=(
            f"ticker.moat_rating_{scored.rating.replace(' ', '_')}"
            if scored.rating
            else None
        ),
        rating_tone=banded[1] if banded else None,
        years=scored.years,
        pillars=[
            MoatPillar(
                key=p.key,
                label=p.label,
                label_key=f"ticker.moat_pillar_{p.key}",
                score=_num(p.score),
                # Each bar on the composite's own bands, so a pillar reads
                # strong or weak on the same scale as the rating chip.
                tone=_band_tone("moat", p.score),
                weight=PILLAR_WEIGHTS[p.key],
                detail=p.detail,
                detail_key=f"ticker.moat_detail_{p.kind}",
                facts={k: v for k, v in p.facts.items() if _num(v) is not None},
            )
            for p in scored.pillars
        ],
    )


def _band_tone(key: str, value: float | None) -> str | None:
    banded = verdict(key, value)
    return banded[1] if banded else None


@router.get("/{symbol}/analysts", response_model=Analysts, summary="Sell-side view")
def analysts(symbol: Symbol) -> Analysts:
    """The analysts' verdict, their price targets and where EPS is being revised.

    One pull of the same consensus the annual chart projects with. Nothing
    here is fact, and below `MIN_COVERAGE` ratings `covered` is false so a
    page says "too few analysts" instead of drawing one opinion as a split.
    """
    ticker = symbol.strip().upper()
    # Side by side: the rating changes are their own Yahoo call, and queued
    # behind the estimates they would add a second wait to a cold card.
    with ThreadPoolExecutor(max_workers=1) as pool:
        moved = pool.submit(carried(_rating_changes_or_none), ticker)
        raw = loaders.estimates(ticker)
        changes = moved.result()
    cons = consensus(raw)
    months = rating_trend(raw, date.today())
    latest = months[-1] if months else None
    count = latest.total if latest else 0

    targets = None
    if cons.target_mean is not None:
        price = cons.price

        def _upside(target: float | None) -> float | None:
            return _num(target / price - 1) if target is not None and price else None

        targets = AnalystTargets(
            low=_num(cons.target_low),
            median=_num(cons.target_median),
            mean=_num(cons.target_mean),
            high=_num(cons.target_high),
            upside_mean=_upside(cons.target_mean),
            upside_median=_upside(cons.target_median),
            dispersion=_num(target_dispersion(cons)),
        )

    return Analysts(
        ticker=ticker,
        currency=_quote_currency(ticker),
        price=_num(cons.price),
        analysts=count,
        covered=count >= MIN_COVERAGE,
        min_coverage=MIN_COVERAGE,
        rating=cons.rating,
        rating_mean=_num(cons.rating_mean),
        months=[
            AnalystMonth(
                month=m.month,
                strong_buy=m.counts.get("strongBuy", 0),
                buy=m.counts.get("buy", 0),
                hold=m.counts.get("hold", 0),
                sell=m.counts.get("sell", 0),
                strong_sell=m.counts.get("strongSell", 0),
                total=m.total,
                mean=_num(m.mean),
            )
            for m in months
        ],
        targets=targets,
        revisions=[
            EpsRevisionRow(
                period=r.period,
                current=_num(r.current),
                change_7d=_num(r.change(7)),
                change_30d=_num(r.change(30)),
                change_90d=_num(r.change(90)),
                up_7d=r.up_7d,
                up_30d=r.up_30d,
                down_7d=r.down_7d,
                down_30d=r.down_30d,
            )
            for r in eps_revisions(raw)
        ],
        changes=[RatingChange(**c) for c in changes],
    )


def _rating_changes_or_none(ticker: str) -> list[dict]:
    """The recent rating moves, or [] when Yahoo refuses: the card keeps the
    consensus it has and just has no moves to list."""
    try:
        return loaders.rating_changes(ticker)
    except Exception as exc:  # noqa: BLE001 — one missing block, not a 500
        obs.warn(
            "api.rating_changes_failed", ticker=ticker, error_type=type(exc).__name__
        )
        return []


@router.get("/{symbol}/options", response_model=OptionsView, summary="Options-implied")
def options(symbol: Symbol) -> OptionsView:
    """Implied volatility and the put/call balance from the listed options.

    Its own request because cold it is an expiry list plus a few chains. A
    name without listed options answers `listed: false`, not an error; a
    throttled Yahoo is the app-wide 503, which the card reads as "nothing to
    show" without caching it as a verdict.
    """
    ticker = symbol.strip().upper()
    if is_crypto(ticker):
        return OptionsView(ticker=ticker, listed=False)
    try:
        view = loaders.options_view(ticker)
    except YFRateLimitError:
        raise
    except Exception as exc:  # noqa: BLE001
        obs.warn("api.options_failed", ticker=ticker, error_type=type(exc).__name__)
        return OptionsView(ticker=ticker, listed=False)
    if view is None:
        return OptionsView(ticker=ticker, listed=False)
    return OptionsView(ticker=ticker, listed=True, **view)


def _quote_currency(ticker: str) -> str | None:
    """The currency the share quotes in, which its price targets are set in.

    Off the fundamentals pull the KPI grid already made, so it costs a cache
    read; None when that pull failed — a target then prints without a mark
    rather than with a wrong one.
    """
    try:
        info = loaders.fundamentals(ticker).info or {}
    except Exception:  # noqa: BLE001 — a missing mark is not a failed section
        return None
    currency = info.get("currency")
    return str(currency) if currency else None


@router.get("/{symbol}/insiders", response_model=Insiders, summary="Insider dealing")
def insiders(symbol: Symbol) -> Insiders:
    """Who inside the company has been buying or selling, and on what scale.

    SEC Form 4 where the name files there; Art. 19 MAR notifications for a
    German (BaFin) or Spanish (CNMV) issuer, which publish the same disclosure
    in EUR. `source`
    says which, and is null when neither covers the name — an empty list on its
    own would read as "no insider has traded", which is a different claim.
    """
    ticker = symbol.strip().upper()
    trades = loaders.insiders(ticker)
    source = "SEC" if trades else None
    filer = _sec_filer(ticker)

    # BaFin only for a symbol the SEC has never heard of. A US filer in a quiet
    # quarter is an empty Form 4 list, not a German issuer, and asking BaFin by
    # its name would spend a request and could match an unrelated company whose
    # name happens to overlap.
    if not trades and filer is False:
        issuer = _issuer_name(ticker)
        if issuer and spanish_listing(ticker):
            trades = cnmv_transactions(ticker, issuer=issuer)
            source = "CNMV" if trades else None
        elif issuer:
            trades = bafin_transactions(ticker, issuer=issuer)
            source = "BaFin" if trades else None

    # Newest first, undated last: the table shows the first thirty and a feed
    # that arrives filing-ordered (or BaFin's publication order) would otherwise
    # decide which thirty. The whole list still travels — the monthly flow
    # chart and the summary read every row.
    trades = sorted(
        trades, key=lambda t: (t.date is not None, t.date or date.min), reverse=True
    )

    return Insiders(
        ticker=ticker,
        source=source,
        summary=_insider_summary(trades) if trades else None,
        trades=[
            InsiderTrade(
                date=str(t.date) if t.date else None,
                insider=t.insider.title(),
                role=t.relationship,
                code=t.code,
                label=CODE_LABELS.get(t.code, t.code),
                # Signed so a table can sort and sum without re-deriving the
                # direction from a separate flag.
                shares=t.shares if t.acquired else -t.shares,
                price=_num(t.price),
                # Null with no notional, never a signed zero: a sale with no
                # price printed as "-0" reads as a trade worth nothing.
                value=_num(t.value if t.acquired else -t.value) if t.value else None,
                is_open_market=t.is_open_market,
                currency=getattr(t, "currency", None),
            )
            for t in trades
        ],
        sec_filer=filer,
    )


@router.get("/{symbol}/shorts", response_model=Shorts, summary="Short selling")
def shorts(symbol: Symbol) -> Shorts:
    """What is being bet against the company.

    US names: Yahoo's short interest (already in the fundamentals pull) and
    FINRA's daily short volume. European names: the net short positions of 0.5 %
    or more that the AFM, the Federal Gazette (BaFin) and the FCA publish, read
    from the stored registers. Neither blocks: a register still downloading is
    answered with what is stored, and a name no register matches is null, not
    "no short sellers".
    """
    ticker = symbol.strip().upper()
    out = Shorts(ticker=ticker)
    short_data.ensure_fresh()
    if short_data.eu_listing(ticker):
        entry = short_data.net_short(_issuer_name(ticker))
        if entry is not None:
            out.eu = EuShortPositions(
                source=entry.source,
                issuer=entry.issuer,
                total_pct=entry.total_pct,
                as_of=str(entry.as_of) if entry.as_of else None,
                holders=[
                    ShortHolderRow(
                        name=h.name, pct=h.pct, date=str(h.date) if h.date else None
                    )
                    for h in entry.holders[: short_data.TOP_HOLDERS]
                ],
                holders_count=len(entry.holders),
            )
    elif "." not in ticker and not is_crypto(ticker):
        try:
            info = loaders.fundamentals(ticker).info or {}
        except Exception as exc:  # noqa: BLE001 — a missing section is not a failed page
            obs.warn(
                "api.shorts_info_failed", ticker=ticker, error_type=type(exc).__name__
            )
            info = {}
        interest = short_data.from_info(info)
        volume = short_data.short_volume(ticker)
        if interest is not None or volume is not None:
            out.us = UsShortInterest(
                pct_float=interest.pct_float if interest else None,
                shares_short=_num(interest.shares_short) if interest else None,
                days_to_cover=_num(interest.days_to_cover) if interest else None,
                change_pct=interest.change_pct if interest else None,
                as_of=str(interest.as_of) if interest and interest.as_of else None,
                volume_ratio=volume.ratio if volume else None,
                volume_days=volume.days if volume else None,
                volume_as_of=str(volume.as_of) if volume else None,
            )
    return out


def _issuer_name(ticker: str) -> str | None:
    """The company name BaFin's and the CNMV's registers are searched by
    (`loaders.issuer_name`)."""
    return loaders.issuer_name(ticker)


def _insider_summary(trades) -> InsiderSummary:
    """The aggregate, including the two things `asdict` cannot see.

    `net_value` and `cluster_buy` are properties on the domain's summary, and a
    dataclass-to-dict conversion drops properties silently — leaving a payload
    that says the net is zero for every company on earth. Named field by field
    here so a reader can check the list against the model.
    """
    summary = summarize(trades)
    return InsiderSummary(
        window_days=summary.window_days,
        buy_count=summary.buy_count,
        sell_count=summary.sell_count,
        buy_shares=summary.buy_shares,
        sell_shares=summary.sell_shares,
        buy_value=summary.buy_value,
        sell_value=summary.sell_value,
        buyers=summary.buyers,
        sellers=summary.sellers,
        net_value=summary.net_value,
        cluster_buy=summary.cluster_buy,
    )


def _sec_filer(ticker: str) -> bool | None:
    """Does the SEC's ticker map know this symbol? None when it could not say.

    The same map `insider_transactions` keys off, so asking costs a cached
    lookup and answers which of the two empty states a page should print.
    """
    try:
        from stocks.data.edgar import cik_for

        return cik_for(ticker) is not None
    except Exception:
        return None


@router.get("/{symbol}/fund", response_model=Fund, summary="Fund profile")
def fund(symbol: Symbol) -> Fund:
    """What an ETF, mutual fund or listed closed-end fund is and what it holds.

    `is_fund: false` for an ordinary company, which is an answer and not an
    error: the page asks every ticker and shows this section for the ones that
    have it. A closed-end fund answers from its own filings and NAV line
    (`closed_end`), since Yahoo has no fund data for it.
    """
    ticker = symbol.strip().upper()
    profile = loaders.fund_profile(ticker)
    if profile is None:
        cef = loaders.closed_end(ticker)
        if cef is None:
            return Fund(ticker=ticker, is_fund=False)
        return _closed_end_fund(ticker, cef)
    kind = loaders.asset_kind(ticker)
    return Fund(
        ticker=ticker,
        is_fund=True,
        name=profile.name,
        quote_type=profile.quote_type,
        currency=profile.currency,
        category=profile.category,
        family=profile.family,
        expense_ratio=_num(profile.expense_ratio),
        aum=_num(profile.aum),
        dividend_yield=_num(profile.dividend_yield),
        turnover=_num(profile.turnover),
        description=profile.description,
        legal_type=profile.legal_type,
        bond_duration=_num(profile.bond_duration),
        # The kind knows a bond fund by its name too; Yahoo publishes no asset
        # mix for most UCITS bond lines.
        is_bond_fund=profile.is_bond_fund or kind == BOND_FUND,
        holdings=[
            FundHolding(symbol=h.symbol, name=h.name, weight=h.weight)
            for h in profile.holdings
        ],
        disclosed_weight=profile.disclosed_weight,
        sectors=[[label, weight] for label, weight in profile.sectors],
        asset_classes=[[label, weight] for label, weight in profile.asset_classes],
        cash=_cash_yield(ticker, profile) if kind == MONEY_MARKET else None,
    )


def _cash_yield(ticker: str, profile) -> CashYield | None:
    """A money-market fund's yield off its own price, beside its bank's rate.

    The year of bars is the chart's own download. A pinned-NAV fund's price
    says nothing, so Yahoo's trailing yield stands in for it.
    """
    from stocks.analysis.cash import annualised, is_flat

    try:
        close = loaders.price_bars(ticker, "1y")["Close"]
    except Exception as exc:
        obs.warn("api.cash_yield_failed", ticker=ticker, error_type=type(exc).__name__)
        close = pd.Series(dtype=float)
    if not close.empty and is_flat(close):
        out = CashYield(yield_1y=_num(profile.dividend_yield), source="distribution")
    else:
        out = CashYield(
            yield_3m=_num(annualised(close, 91)),
            yield_1y=_num(annualised(close, 365)),
        )
    if out.yield_3m is None and out.yield_1y is None:
        return None
    if not close.empty:
        out.as_of = pd.Timestamp(close.index[-1]).date().isoformat()
    if policy := loaders.policy_rate(profile.currency or ""):
        out.bank, out.policy_rate, stamp = policy[0], _num(policy[1]), policy[2]
        out.policy_as_of = stamp.isoformat()
    return out


def _figure(figure) -> SourcedFigure:
    return SourcedFigure(
        value=_num(figure.value),
        source=figure.source if figure.value is not None else None,
        as_of=figure.as_of,
        tried=list(figure.tried),
    )


def _closed_end_fund(ticker: str, cef) -> Fund:
    """A closed-end fund in the ETF shape, plus the figures only it has.

    The shared fields (expense ratio, assets, yield, holdings, asset mix) are
    filled so the page's fund layout reads the same for both kinds; `aum` is
    the N-PORT net assets and `dividend_yield` the distribution rate.
    """
    return Fund(
        ticker=ticker,
        is_fund=True,
        name=cef.name,
        quote_type="CEF",
        currency=cef.currency,
        expense_ratio=_num(cef.expense_ratio.value),
        aum=_num(cef.net_assets.value),
        dividend_yield=_num(cef.distribution_rate.value),
        description=cef.description,
        legal_type="Closed-End Fund",
        is_bond_fund=cef.is_bond_fund,
        holdings=[
            FundHolding(symbol=h.symbol, name=h.name, weight=h.weight)
            for h in cef.holdings
        ],
        disclosed_weight=cef.disclosed_weight,
        asset_classes=[[label, weight] for label, weight in cef.asset_classes],
        closed_end=ClosedEnd(
            nav_symbol=cef.nav_symbol,
            nav=_figure(cef.nav),
            price=_figure(cef.price),
            premium=_figure(cef.premium),
            distribution_rate=_figure(cef.distribution_rate),
            expense_ratio=_figure(cef.expense_ratio),
            net_assets=_figure(cef.net_assets),
            total_assets=_figure(cef.total_assets),
            leverage=_figure(cef.leverage),
            holdings_count=cef.holdings_count,
            holdings_as_of=cef.holdings_as_of,
            checks=[
                SourceCheck(
                    metric=c.metric,
                    as_of=c.as_of,
                    official=c.official,
                    official_source=c.official_source,
                    market=_num(c.market),
                    market_source=c.market_source,
                    agree=c.agree,
                    tolerance=c.tolerance,
                )
                for c in cef.checks
            ],
        ),
    )
