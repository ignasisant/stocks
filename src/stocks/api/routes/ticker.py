"""One company's page: its bars, its live quote, its calendar, your position.

Split along the same lines the Ticker page redraws: the range control changes
the bars and nothing else, so the bars are their own request. What is *not*
split off is presentation — no hover strings, no formatted money, no colours.
A day move is a fraction and a session label; how it reads in Spanish is the
client's problem, and duplicating that here is how two front ends start
disagreeing about what a number says.
"""

from __future__ import annotations

from typing import Annotated, cast

import pandas as pd
from fastapi import APIRouter, HTTPException, Path, Query, status

from stocks import obs
from stocks.analysis.fundamentals import (
    FUNDAMENTAL_TILES,
    KPI_SOURCES,
    METRIC_ORDER,
    annual_financials,
    compute_metrics,
    format_value,
    quarterly_eps,
    verdict,
)
from stocks.analysis.history import PERIODS, rangebreaks
from stocks.analysis.moat import PILLAR_WEIGHTS, moat_score
from stocks.analysis.pe_history import DISPLAY_WINDOWS, window_stats
from stocks.analysis.portfolio import market_live, session_quote
from stocks.api import loaders
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.jsonsafe import scalar as _scalar
from stocks.api.schemas import (
    AnnualRow,
    AssetStats,
    Bars,
    Custodian,
    EarningsEvent,
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
    Peer,
    Peers,
    PriceEvents,
    Profile,
    ProjectedRow,
    Quote,
    TickerPosition,
    Trade,
    Valuation,
    ValuationWindow,
)
from stocks.config import CURRENCIES
from stocks.data.bafin import insider_transactions as bafin_transactions
from stocks.data.crypto import is_crypto, split_pair
from stocks.data.estimates import estimate_currency, projection
from stocks.data.funds import is_fund
from stocks.data.insiders import summarize
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
        return Bars(ticker=ticker, range=label, interval=PERIODS[label][1], dates=[])
    # The momentum read on the newest bar, banded in the domain. The page
    # prints it under the RSI figure; shipping only the number would make each
    # front end pick its own thresholds for "overbought".
    latest_rsi = next((v for v in reversed(_column(df, "RSI14")) if v is not None), None)
    banded = verdict("rsi", latest_rsi)
    return Bars(
        ticker=ticker,
        range=label,
        interval=PERIODS[label][1],
        dates=[str(ts) for ts in df.index],
        series={name: _column(df, name) for name in _SERIES},
        dividends=_column(df, "Dividends"),
        rsi_verdict=banded[0] if banded else None,
        rsi_tone=banded[1] if banded else None,
        rangebreaks=rangebreaks(df, PERIODS[label][1]),
    )


@router.get("/{symbol}/quote", response_model=Quote, summary="Live quote")
def quote(symbol: Symbol) -> Quote:
    """Current price and day move, with the session the move belongs to.

    `market_open` is what the page uses to decide whether to override the last
    bar: inside the regular session the fetched history already tracks the live
    price, and only outside it does this quote say something the bars do not.
    """
    ticker = symbol.strip().upper()
    snapshot = session_quote(ticker) or {}
    return Quote(
        ticker=ticker,
        price=snapshot.get("price"),
        pct=snapshot.get("pct"),
        session=snapshot.get("session"),
        as_of=snapshot.get("as_of"),
        market_open=market_live(ticker),
    )


@router.get("/{symbol}/events", response_model=PriceEvents, summary="Chart events")
def events(symbol: Symbol) -> PriceEvents:
    """Reporting dates and what printed, for the verticals on the price chart.

    Dividends are deliberately absent: they ride in the history frame, so
    `/bars` already carries them and a second round trip would only risk the
    two disagreeing.

    A fund pays distributions but never reports, and a coin does neither, so
    both come back empty without spending a request on Yahoo answering "no
    earnings dates found".
    """
    ticker = symbol.strip().upper()
    if is_crypto(ticker) or is_fund(ticker):
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
    fills = _trades(db, mtime, ticker)
    held = loaders.native_positions(db, mtime).get(ticker)
    if held is None:
        # Closed, or never opened. The fills still travel: a chart that forgets
        # where somebody entered is missing the only part of it that was theirs.
        return TickerPosition(ticker=ticker, held=False, trades=fills)

    ccy = reporting_currency(account, base)
    table = loaders.positions_table(db, mtime, ccy)
    value = None
    weight = None
    if not table.empty and ticker in table.index:
        raw = table.at[ticker, "value"]
        if pd.notna(raw):
            from stocks.analysis.portfolio import value_weights

            value = float(raw)
            share = value_weights(table).get(ticker)
            weight = None if share is None or pd.isna(share) else float(share)

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
        trades=fills,
        brokers={name: c.quantity for name, c in brokers.items()},
        custody=marks,
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
    return Metrics(
        ticker=ticker,
        currency=cast(str | None, computed.get("currency")),
        quote_type=cast(str | None, computed.get("quote_type")),
        kpis=[_kpi(key, computed.get(key)) for key in METRIC_ORDER],
        grid=[
            MetricTile(key=tile.key, label_key=tile.label, help_key=tile.help)
            for tile in FUNDAMENTAL_TILES
        ],
        market_cap_base=cap,
        market_cap_base_formatted=(
            format_value("market_cap", cap) if cap is not None else None
        ),
        fx_rate=rate,
        fx_as_of=as_of,
        base=ccy,
    )


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


def _kpi(key: str, value) -> Kpi:
    """One KPI row, with its band's label AND the tone that band carries.

    Both, because the labels are a growing set — "net cash", "buybacks",
    "heavy dilution" — and a client colouring by label shows every band it has
    not heard of as neutral.
    """
    banded = verdict(key, value)
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
        estimate_ccy = estimate_currency(raw_estimates.earnings_estimate)
        frame = projection(raw_estimates, int(annual.index[-1]))
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
    )


def _trades(db: str, mtime: float, ticker: str) -> list[Trade]:
    """The caller's buys and sells of one name, chart-ready.

    Relabelling and split-scaling both live in `corporate.own_fills`, which the
    Streamlit page calls too — the two corrections are invisible when missing,
    and one place to forget them is enough.
    """
    from stocks.portfolio.corporate import own_fills

    return [
        Trade(date=f.date, action=f.action, price=f.price, quantity=f.quantity)
        for f in own_fills(loaders.ledger_state(db, mtime)[0], ticker)
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
    _, quote = split_pair(ticker) or (ticker, "USD")
    return AssetStats(
        ticker=ticker,
        quote=quote,
        market_cap=_num(info.get("marketCap")),
        volume_24h=_num(info.get("volume24Hr") or info.get("volume")),
        circulating_supply=_num(info.get("circulatingSupply")),
        high_52w=_num(info.get("fiftyTwoWeekHigh")),
        low_52w=_num(info.get("fiftyTwoWeekLow")),
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
    return Profile(
        ticker=ticker,
        symbol=resolved,
        name=loaders.company_name(ticker, str(account.watchlist)) or "",
        logo=loaders.logo(ticker),
        is_crypto=is_crypto(resolved),
        is_fund=is_fund(resolved),
    )


@router.get("/{symbol}/peers", response_model=Peers, summary="Suggested comparables")
def peers(symbol: Symbol) -> Peers:
    """Who this company might reasonably be compared against.

    Suggestions only. Nothing is compared until a caller picks — the app makes
    the same choice, and for the same reason: each peer is a fundamentals pull,
    and a table nobody asked for spends them on a guess.

    Names come from the SEC map, so a non-US listing arrives as a bare symbol
    rather than as a second network round-trip per suggestion.
    """
    ticker = symbol.strip().upper()
    return Peers(
        ticker=ticker,
        related=[
            Peer(ticker=other, name=loaders.sec_title(other) or "")
            for other in loaders.related(ticker)
            if not is_crypto(other)
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

    return Valuation(
        ticker=ticker,
        source=result.get("source"),
        current=_num(result.get("current")),
        dates=[str(pd.Timestamp(ts).date()) for ts in series.index]
        if series is not None and not series.empty
        else [],
        pe=[_num(v) for v in series] if series is not None and not series.empty else [],
        windows=windows,
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
    return Moat(
        ticker=ticker,
        score=_num(scored.score),
        rating=scored.rating,
        years=scored.years,
        pillars=[
            MoatPillar(
                key=p.key,
                label=p.label,
                score=_num(p.score),
                weight=PILLAR_WEIGHTS[p.key],
                detail=p.detail,
            )
            for p in scored.pillars
        ],
    )


@router.get("/{symbol}/insiders", response_model=Insiders, summary="Insider dealing")
def insiders(symbol: Symbol) -> Insiders:
    """Who inside the company has been buying or selling, and on what scale.

    SEC Form 4 where the name files there; BaFin's Art. 19 MAR notifications
    for a German issuer, which publish the same disclosure in EUR. `source`
    says which, and is null when neither covers the name — an empty list on its
    own would read as "no insider has traded", which is a different claim.
    """
    ticker = symbol.strip().upper()
    trades = loaders.insiders(ticker)
    source = "SEC" if trades else None

    if not trades:
        issuer = str(loaders.fundamentals(ticker).info.get("longName") or "").strip()
        if issuer:
            trades = bafin_transactions(ticker, issuer=issuer)
            source = "BaFin" if trades else None

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
                # Signed so a table can sort and sum without re-deriving the
                # direction from a separate flag.
                shares=t.shares if t.acquired else -t.shares,
                price=_num(t.price),
                value=_num(t.value if t.acquired else -(t.value or 0.0)),
                is_open_market=t.is_open_market,
                currency=getattr(t, "currency", None),
            )
            for t in trades
        ],
        sec_filer=_sec_filer(ticker),
    )


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
    """What an ETF or mutual fund is and what it holds.

    `is_fund: false` for an ordinary company, which is an answer and not an
    error: the page asks every ticker and shows this section for the ones that
    have it.
    """
    ticker = symbol.strip().upper()
    profile = loaders.fund_profile(ticker)
    if profile is None:
        return Fund(ticker=ticker, is_fund=False)
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
        is_bond_fund=profile.is_bond_fund,
        holdings=[
            FundHolding(symbol=h.symbol, name=h.name, weight=h.weight)
            for h in profile.holdings
        ],
        disclosed_weight=profile.disclosed_weight,
        sectors=[[label, weight] for label, weight in profile.sectors],
        asset_classes=[[label, weight] for label, weight in profile.asset_classes],
    )
