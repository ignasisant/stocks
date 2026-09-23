"""The book: positions, totals, the ledger itself, and how it has done."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from urllib.error import URLError

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from yfinance.exceptions import YFRateLimitError

from stocks import obs
from stocks.analysis.portfolio import (
    annualized_return,
    annualized_volatility,
    correlation_matrix,
    cumulative_returns,
    effective_positions,
    flow_series,
    max_drawdown,
    money_weighted_return,
    priced_totals,
    top_n_weight,
    value_weights,
)
from stocks.api import loaders
from stocks.api.cache import ttl_cache
from stocks.api.deps import Account, Base, Writer, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import (
    AllocationSlice,
    BrokerCost,
    Dividends,
    DividendYear,
    Fees,
    ForwardHolding,
    LedgerCleared,
    Performance,
    Position,
    Positions,
    Risk,
    RiskCurves,
    Summary,
    TaxAllYears,
    TaxKpi,
    TaxReport,
    TaxSale,
    Transaction,
    Transactions,
)
from stocks.api.schemas import TaxPeriod as TaxPeriodOut
from stocks.api.security import Authed
from stocks.portfolio import custody, demo, dividends, fees, last_import, tax
from stocks.portfolio.ledger import all_transactions, clear
from stocks.portfolio.tax import month_range
from stocks.portfolio.tax import prefs as tax_prefs

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# Windows the basket report will measure over. A period nobody defined is
# refused rather than guessed at: yfinance takes whatever string it is handed
# and an unknown one comes back as an empty frame, which would read as a book
# with no risk at all.
_RISK_PERIODS = ("6mo", "1y", "2y", "5y", "max")

# Windows the daily series is offered over, in calendar days — the union of the
# two range controls the app already has, under the same codes, so a client and
# a page open on two screens draw the same span: the Portfolio page's chart
# (1m/3m/6m/1y) and the Home sparkline's (1w/1m/6m/1y/2y/5y). "ytd" and "all"
# are spelled out below because neither is a fixed number of days.
_HISTORY_SPANS = {
    "1w": 7,
    "1m": 30,
    "3m": 91,
    "6m": 182,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}
_HISTORY_WINDOWS = (*_HISTORY_SPANS, "ytd", "all")


def _native_price(row, rates: dict[str, float]) -> float | None:
    """One share's price in the currency it trades in, backed out of `value`.

    `value` is shares * price * rate, so dividing by the shares and the rate
    recovers the quote. Null rather than a guess when the row has no value or
    the pair is missing: a price under the wrong symbol is worse than none.
    """
    shares, value = row.get("shares"), row.get("value")
    rate = rates.get(str(row.get("ccy") or "").upper())
    if not shares or not rate or value is None or pd.isna(value):
        return None
    return float(value) / float(shares) / rate


@router.get("/positions", response_model=Positions, summary="Open positions")
def positions(account: Account, base: Base = None) -> Positions:
    ccy = reporting_currency(account, base)
    db = str(account.db)
    table = loaders.positions_table(db, loaders.db_mtime(db), ccy)
    if table.empty:
        return Positions(base=ccy, positions=[], unpriced=0)
    weights = value_weights(table)
    # One spot per currency, not per position, and read back out of the value
    # the price pass already fetched — a second quote per name to print a share
    # price is how a page gets itself throttled.
    rates = loaders.spot_rates(
        tuple(sorted({str(c).upper() for c in table["ccy"] if c})), ccy
    )
    rows = [
        Position(
            ticker=str(ticker),
            shares=float(row["shares"]),
            currency=str(row["ccy"]),
            cost=float(row["cost"]),
            value=_num(row["value"]),
            price=_native_price(row, rates),
            pnl=_num(row["pnl"]),
            pnl_pct=_num(row["pnl_pct"]),
            weight=_num(weights.get(ticker)),
        )
        for ticker, row in table.iterrows()
    ]
    return Positions(
        base=ccy, positions=rows, unpriced=int(table["value"].isna().sum())
    )


@router.get("/summary", response_model=Summary, summary="Book totals")
def summary(account: Account, base: Base = None) -> Summary:
    """Cost, value and P/L over the rows that priced.

    Both sums come from the same rows on purpose (`priced_totals`): summing the
    whole book's basis against a partial market value mixes denominators and
    renders an intact book at -60%. `unpriced` is how many positions were left
    out of both.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    table = loaders.positions_table(db, loaders.db_mtime(db), ccy)
    cost, value, unpriced = priced_totals(table)
    # The closed side of the same book, off the replay this loader already
    # holds. Deliberately FIFO and deliberately in the reporting currency:
    # `/portfolio/tax` answers the other question — what a jurisdiction
    # considers realized, under its own matching rule and its own currency —
    # and the two numbers are not interchangeable for anyone but an EUR-
    # reporting FIFO filer.
    _txs, _open, sales = loaders.ledger_state(db, loaders.db_mtime(db), ccy)
    return Summary(
        base=ccy,
        cost=cost,
        value=value,
        pnl=value - cost,
        pnl_pct=_num(value / cost - 1) if cost else None,
        positions=int(len(table)),
        unpriced=unpriced,
        # Null, not zero, for a book that never sold: "no result" and "broke
        # even" are different facts and the tile has to be able to say so.
        realized=(
            _num(sum(s.proceeds - s.cost for s in sales)) if sales else None
        ),
        realized_cost=_num(sum(s.cost for s in sales)) if sales else None,
        demo=demo.active(account.db),
    )


@router.get("/transactions", response_model=Transactions, summary="Ledger rows")
def transactions(
    account: Account,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    base: Base = None,
) -> Transactions:
    """The ledger, newest first, paged.

    Raw rows as imported — not relabelled and not netted. A caller reconciling
    against a broker statement wants exactly what is stored; the analytics
    endpoints are where transfers get unified into one position.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    txs = loaders.ledger_state(db, loaders.db_mtime(db), ccy)[0]
    ordered = sorted(txs, key=lambda t: (t.date, t.id or 0), reverse=True)
    page = ordered[offset : offset + limit]
    return Transactions(
        total=len(txs),
        demo=demo.active(account.db),
        transactions=[
            Transaction(
                id=t.id,
                date=t.date,
                ticker=t.ticker,
                action=t.action,
                quantity=t.quantity,
                price=t.price,
                currency=t.currency,
                fee=t.fee,
                note=t.note,
            )
            for t in page
        ],
    )


@router.get("/performance", response_model=Performance, summary="TWR and IRR")
def performance(account: Account, base: Base = None) -> Performance:
    """How the book has done, both ways of asking.

    TWR strips flow timing out, so it measures the selection and is comparable
    against an index. IRR leaves flow timing in, so it measures what the money
    actually did. They answer different questions and routinely disagree —
    hence both, never one standing in for the other.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    hist, twr, missing = loaders.history(db, mtime, ccy)
    if hist.empty:
        return Performance(base=ccy, missing=missing)

    cumulative = float((1 + twr).prod() - 1) if not twr.empty else float("nan")
    # Over the span the return was actually measured on, not the ledger's:
    # a book that sat empty for a year has no return for it, and dividing the
    # compounding by those months understates what the money that was in did.
    annualised = annualized_return(twr) if not twr.empty else float("nan")
    txs = loaders.ledger_state(db, mtime, ccy)[0]
    irr = money_weighted_return(hist["value"], flow_series(txs, base=ccy))

    return Performance(
        base=ccy,
        start=str(pd.Timestamp(hist.index[0]).date()),
        end=str(pd.Timestamp(hist.index[-1]).date()),
        injected=_num(hist["injected"].iloc[-1]),
        value=_num(hist["value"].iloc[-1]),
        twr_cumulative=_num(cumulative),
        twr_annualised=_num(annualised),
        # Volatility and drawdown of the flow-adjusted path, which is the only
        # series either can be taken over honestly: the book's own value moves
        # every time money is added, and a deposit is not a return.
        twr_volatility=_num(annualized_volatility(twr)),
        twr_max_drawdown=_num(max_drawdown(cumulative_returns(twr) + 1)),
        dropped_days=[
            str(pd.Timestamp(day).date()) for day in twr.attrs.get("dropped_days", ())
        ],
        irr=_num(irr),
        missing=missing,
    )


# ------------------------------------------------------------- the daily path
# `/performance` is the last point of this series and three numbers taken over
# it. A chart needs the series itself, and the two lines it draws are not the
# same shape: money-in-versus-worth is a pair of levels in the reporting
# currency, while the cumulative return is an index that rebases at whatever
# window is on screen. Both come out of one `loaders.history` call — the same
# recipe (`analysis.portfolio.book_history`) the Portfolio page charts, so the
# page and a client cannot disagree about what the book did.


class HistoryPoint(BaseModel):
    """One day of the book. Every figure may be null, and null is not zero."""

    date: str
    injected: float | None = Field(
        description=(
            "Capital put in by this date, cumulative and net of what was taken "
            "out — the flat reference line the value is read against."
        )
    )
    value: float | None = Field(
        description=(
            "Mark-to-market worth of everything held that day. A held name "
            "with no usable close is carried at its cost rather than dropped, "
            "so this stays comparable to `injected`; `missing` names them."
        )
    )
    pnl_pct: float | None = Field(
        description="value/injected - 1. Null before anything was put in."
    )
    twr: float | None = Field(
        description=(
            "Cumulative time-weighted return since the start of THIS window, "
            "flow-adjusted, so deposits do not read as performance. Rebased by "
            "the window, so two windows give the same day two different values "
            "— that is the point of the line. Null on a day the return could "
            "not be taken (see `dropped_days`, and the book's first day, which "
            "has no prior close to measure against)."
        )
    )


class History(BaseModel):
    base: str
    window: str
    start: str | None = None
    end: str | None = None
    points: list[HistoryPoint] = []
    missing: list[str] = Field(
        default=[],
        description=(
            "Held names with no usable price series, carried at cost inside "
            "`value`. Disclose them: a total that quietly drops part of the "
            "book is a lie in smaller print."
        ),
    )
    dropped_days: list[str] = Field(
        default=[],
        description=(
            "Days whose return priced below -100% and were excluded from the "
            "TWR — an unrecorded split or corporate action, never a real loss. "
            "One such sample drags the whole cumulative line negative."
        ),
    )


@router.get("/history", response_model=History, summary="The book, day by day")
def history(
    account: Account,
    base: Base = None,
    window: Annotated[
        str,
        Query(description=f"One of {', '.join(_HISTORY_WINDOWS)}."),
    ] = "all",
    since: Annotated[
        date | None,
        Query(alias="from", description="Explicit range start, ISO. Excludes `window`."),
    ] = None,
    until: Annotated[
        date | None,
        Query(alias="to", description="Explicit range end, ISO. Excludes `window`."),
    ] = None,
) -> History:
    """Injected capital, market value and the TWR index, one point per day.

    The window is clipped here rather than by the client, because the TWR index
    has to be rebased to whatever is on screen — a client that fetched `all` and
    sliced it locally would draw a one-month chart starting at last year's
    cumulative return. The level lines (`injected`, `value`) are absolute and
    survive slicing; the index is not, which is why they travel together.

    `from`/`to` and `window` are mutually exclusive: a request that named both
    is refused rather than served the one this route happened to prefer.
    """
    explicit = since is not None or until is not None
    if explicit and window != "all":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="pass either window or from/to, not both",
        )
    if not explicit and window not in _HISTORY_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(_HISTORY_WINDOWS)}",
        )
    if since is not None and until is not None and since > until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="from must not be later than to",
        )

    ccy = reporting_currency(account, base)
    db = str(account.db)
    hist, twr, missing = loaders.history(db, loaders.db_mtime(db), ccy)
    label = "custom" if explicit else window
    if hist.empty:
        return History(base=ccy, window=label, missing=missing)

    if explicit:
        if since is not None:
            hist = hist[hist.index >= pd.Timestamp(since)]
        if until is not None:
            hist = hist[hist.index <= pd.Timestamp(until)]
    elif window in _HISTORY_SPANS:
        # Counted back from the series' own last day rather than from today, so
        # a book whose newest close is stale still gets a full month of days
        # instead of a window that silently shortens whenever Yahoo goes quiet.
        hist = hist[
            hist.index >= hist.index.max() - pd.Timedelta(days=_HISTORY_SPANS[window])
        ]
    elif window == "ytd":
        hist = hist[hist.index >= pd.Timestamp(date.today().year, 1, 1)]
    if hist.empty:
        return History(base=ccy, window=label, missing=missing)

    # Rebased on the window, exactly as the page's cumulative-return chart does
    # it, then put back on the daily index: a day the TWR dropped reads null
    # here rather than repeating the day before it, which would draw a flat
    # stretch nobody measured.
    index = pd.Series(dtype=float)
    if not twr.empty:
        clipped = twr[twr.index >= hist.index[0]]
        if not clipped.empty:
            index = cumulative_returns(clipped).reindex(hist.index)

    return History(
        base=ccy,
        window=label,
        start=str(pd.Timestamp(hist.index[0]).date()),
        end=str(pd.Timestamp(hist.index[-1]).date()),
        points=[
            HistoryPoint(
                date=str(pd.Timestamp(day).date()),
                injected=_num(row["injected"]),
                value=_num(row["value"]),
                pnl_pct=_num(row["pnl_pct"]),
                twr=_num(index.get(day)) if not index.empty else None,
            )
            for day, row in hist.iterrows()
        ],
        missing=missing,
        dropped_days=[
            str(pd.Timestamp(day).date())
            for day in twr.attrs.get("dropped_days", ())
            if hist.index[0] <= pd.Timestamp(day) <= hist.index[-1]
        ],
    )


# ----------------------------------------------------------- taking it away
# The privacy policy promises the ledger is the account's own to take away, and
# "take away" has to mean a file. The Profile page has offered this download
# since before the API existed; the formatter is `web.exports.ledger_csv` and
# stays there — a second one here would drift the moment either grew a column.


@ttl_cache(3600.0, max_entries=8)
def _ledger_csv(db: str, mtime: float, base: str) -> bytes:
    """The export, memoized on (db, ledger mtime, base) like the page's copy.

    Worth caching because it is not a dump: every row is priced at the ECB rate
    for its own trade date, which is a fetch per currency in the book.
    """
    # Imported here, not at module scope: `stocks.web` pulls Streamlit in, and
    # a headless caller of this API should never need it loaded.
    from stocks.web.exports import ledger_csv

    return ledger_csv(db, base)


@router.get(
    "/transactions.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "The ledger."}},
    summary="The ledger as a file",
)
def transactions_csv(account: Account, base: Base = None) -> Response:
    """Every transaction as CSV, each row also converted to the reporting currency.

    The same bytes the Profile page's download button hands back, filename
    included, so a book exported from either side reconciles against the other.
    Best-effort on the rates: a row whose rate could not be fetched exports with
    an empty rate and an empty converted amount rather than a wrong one — the
    native columns are the ledger, and they are always there.

    A book with no transactions is a 404 rather than a zero-byte attachment:
    the page offers no button in that state, and a client should not hand
    somebody a file that turns out to be empty.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    body = _ledger_csv(db, loaders.db_mtime(db), ccy)
    if not body:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this book has no transactions to export",
        )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aguait-ledger-{date.today():%Y-%m-%d}.csv"'
            )
        },
    )


@router.get("/fees", response_model=Fees, summary="What trading it cost")
def fees_(account: Account, base: Base = None) -> Fees:
    """Commission the broker charged, and the spread it charged silently.

    They are never added into one number without both being present: the
    commission is a ledger fact and the spread an estimate against the trade
    day's mid, so a book whose bars could not be fetched reports the ledger
    half and `spread_measured: false` rather than a total that reads as
    "traded at the mid".
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    txs = loaders.ledger_state(db, mtime, ccy)[0]
    brokers = fees.by_broker(txs, base=ccy)
    if not brokers:
        return Fees(base=ccy)

    # The spread needs the trade-day bars; the commissions do not. A throttled
    # or offline Yahoo therefore degrades this endpoint to its ledger half
    # instead of 503-ing a question the ledger can answer on its own.
    spreads: dict[str, fees.SpreadStats] = {}
    measured = False
    try:
        spreads = fees.spread_by_broker(
            txs, loaders.trade_bars(db, mtime), base=ccy
        )
        measured = True
    except (YFRateLimitError, URLError):
        pass

    rows = []
    for name in sorted(brokers, key=lambda n: -brokers[n].volume):
        broker, stats = brokers[name], spreads.get(name)
        spread = stats.spread if stats else (0.0 if measured else None)
        total = broker.explicit + (spread or 0.0) if measured else None
        rows.append(
            BrokerCost(
                broker=name,
                trades=broker.trades,
                volume=broker.volume,
                commission=broker.commission,
                other_fees=broker.other_fees,
                spread=_num(spread) if measured else None,
                spread_bps=_num(stats.spread_bps) if stats else None,
                measured=stats.measured if stats else 0,
                skipped=stats.skipped if stats else 0,
                outside_range=stats.outside_range if stats else 0.0,
                total=_num(total),
                cost_pct=_num(total / broker.volume)
                if total is not None and broker.volume
                else None,
            )
        )

    volume = sum(b.volume for b in brokers.values())
    explicit = sum(b.explicit for b in brokers.values())
    spread_total = sum(s.spread for s in spreads.values()) if measured else None
    cost = explicit + (spread_total or 0.0)
    return Fees(
        base=ccy,
        brokers=rows,
        explicit=explicit,
        spread=_num(spread_total) if measured else None,
        volume=volume,
        cost_pct=_num(cost / volume) if volume else None,
        spread_measured=measured,
    )


@router.get("/dividends", response_model=Dividends, summary="Income, booked and due")
def dividends_(account: Account, base: Base = None) -> Dividends:
    """What the ledger was paid, and what the shares were entitled to.

    The two never merge. A dividend is owed to whoever held the share the day
    before it went ex whether or not the import carried a row for it, so the
    estimate is the only way to see a broker whose dividends never import — but
    it is a guess, and a guess added to a receipt is neither.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    txs = loaders.ledger_state(db, mtime, ccy)[0]
    booked = dividends.by_year(txs, base=ccy)

    estimated: dict[int, dividends.EstimatedYear] = {}
    forward: list[dividends.ForwardIncome] = []
    totals: dict[str, float] = {}
    unrecorded: dict[int, float] = {}
    available = False
    try:
        estimated, forward, totals, unrecorded = loaders.dividend_estimates(
            db, mtime, ccy
        )
        available = True
    except (YFRateLimitError, URLError):
        pass

    this_year = date.today().year
    years = [
        DividendYear(
            year=year,
            gross=row.gross,
            withheld=row.withheld,
            net=row.net,
            creditable=row.creditable,
            reclaimable=row.reclaimable,
            estimated_gross=(
                _num(estimated[year].gross) if available and year in estimated else None
            ),
            unrecorded=_num(unrecorded.get(year)) if available else None,
        )
        for year, row in sorted(booked.items())
    ]
    # A year the shares were paid in but the ledger never booked has no row
    # above, and leaving it out is how an import gap stays invisible.
    for year in sorted(set(estimated) - set(booked)) if available else ():
        years.append(
            DividendYear(
                year=year,
                gross=0.0,
                withheld=0.0,
                net=0.0,
                creditable=0.0,
                reclaimable=0.0,
                estimated_gross=_num(estimated[year].gross),
                unrecorded=_num(unrecorded.get(year)),
            )
        )
    years.sort(key=lambda row: row.year)

    return Dividends(
        base=ccy,
        years=years,
        booked_total=sum(row.gross for row in booked.values()),
        booked_ytd=booked[this_year].gross if this_year in booked else 0.0,
        estimated_total=(
            _num(sum(e.gross for e in estimated.values())) if available else None
        ),
        estimated_ytd=(
            _num(estimated[this_year].gross)
            if available and this_year in estimated
            else (0.0 if available else None)
        ),
        forward_annual=_num(sum(totals.values())) if available else None,
        forward=[
            ForwardHolding(
                ticker=holding.ticker,
                shares=holding.shares,
                per_share=holding.per_share,
                payments=holding.payments,
                currency=holding.currency,
                gross=_num(holding.gross) or 0.0,
                gross_base=_num(totals.get(holding.ticker)),
                last_ex=holding.last_ex,
            )
            for holding in forward
        ],
        estimates_available=available,
    )


@router.get("/tax", response_model=TaxReport, summary="Realized result and tax")
def tax_(account: Account) -> TaxReport:
    """The book's realized result under the account's own jurisdiction.

    There is no `?base=` here, and that is deliberate: the ledger is replayed
    *at* the jurisdiction's currency and under its own share-matching rule
    rather than converted afterwards. A US filer's basis is USD at each trade
    date — two rates, not one — and a UK replay pools shares, so its parcels
    are not the FIFO ones the rest of the API reports.

    `resolved` says how the jurisdiction was arrived at. A caller that gets
    `unmodelled` is being shown somebody else's rules and has to say so.
    """
    prefs = tax_prefs.load(account.prefs)
    code, how = tax_prefs.resolve(prefs)
    jurisdiction = tax.get(code)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    txs, _, realized = loaders.ledger_state(
        db, mtime, jurisdiction.currency, jurisdiction.matching
    )
    # Under the replay's labels, not the ledger's: the exemption is applied by
    # testing a sale's ticker against this set (see tax.labels).
    settings = tax_prefs.with_funds(tax_prefs.settings(prefs), tax.labels(txs))
    report = TaxReport(
        jurisdiction=code,
        resolved=how,
        currency=jurisdiction.currency,
        matching=jurisdiction.matching,
        funds_classified=bool(settings.fund_tickers),
    )
    if not realized:
        return report

    # Relabelled inside: a RealizedSale carries the replay's label and the raw
    # ledger does not, so a repurchase booked under the other spelling of the
    # same security is invisible to every repurchase rule. See tax.buy_dates.
    buy_dates = tax.buy_dates(txs)

    def period(value) -> TaxPeriodOut:
        return TaxPeriodOut(
            period=value.period,
            realized_gain=_num(value.realized_gain) or 0.0,
            realized_loss=_num(value.realized_loss) or 0.0,
            disallowed_loss=_num(value.disallowed_loss) or 0.0,
            recovered_loss=_num(value.recovered_loss) or 0.0,
            deductible_loss=_num(value.deductible_loss) or 0.0,
            net_taxable=_num(value.net_taxable) or 0.0,
            estimated_tax=_num(value.estimated_tax) or 0.0,
            carryforward_loss=_num(value.carryforward_loss) or 0.0,
            sales=len(value.sales),
            kpis=[
                TaxKpi(name=k.key, value=_num(k.value) or 0.0, help=k.help_key)
                for k in value.kpis()
            ],
        )

    # Tax years, not calendar years — the UK's open on 6 April.
    years = sorted({jurisdiction.tax_year_of(s.sell_date) for s in realized})
    months = sorted({s.sell_date[:7] for s in realized})
    periods = [
        jurisdiction.fiscal_year(realized, year, buy_dates, settings)
        for year in years
    ]
    report.years = [period(value) for value in periods]
    # The years added up, which is a history and not a period: `tax.total_of`
    # sums each year's own figures rather than replaying the ledger as one long
    # one, because allowances reset and brackets restart — a decade run up a
    # single progressive scale would invent a tax nobody owes. One year is
    # already all of them, so it gets no aggregate.
    if len(periods) > 1:
        total = tax.total_of(periods)
        report.all_years = TaxAllYears(
            years=list(total.years),
            realized_gain=_num(total.realized_gain) or 0.0,
            realized_loss=_num(total.realized_loss) or 0.0,
            disallowed_loss=_num(total.disallowed_loss) or 0.0,
            recovered_loss=_num(total.recovered_loss) or 0.0,
            deductible_loss=_num(total.deductible_loss) or 0.0,
            sales=len(total.sales),
            kpis=[
                TaxKpi(name=k.key, value=_num(k.value) or 0.0, help=k.help_key)
                for k in total.kpis()
            ],
        )
    # Quiet months included (month_range), so a client charting this does not
    # have to invent the gaps between two sales.
    report.months = [
        period(jurisdiction.fiscal_period(realized, month, buy_dates, settings))
        for month in month_range(months[0], months[-1])
    ]
    report.sales = [
        TaxSale(
            ticker=sale.ticker,
            buy_date=sale.buy_date,
            sell_date=sale.sell_date,
            quantity=sale.quantity,
            cost=sale.cost,
            proceeds=sale.proceeds,
            gain=sale.gain,
            matched=sale.matched,
        )
        for sale in sorted(realized, key=lambda s: s.sell_date)
    ]
    return report


@router.get("/risk", response_model=Risk, summary="Risk of the current basket")
def risk(
    account: Account,
    base: Base = None,
    period: Annotated[
        str,
        Query(description="Return window: 6mo, 1y, 2y, 5y, max."),
    ] = "1y",
) -> Risk:
    """Today's holdings backtested at fixed weights over `period`.

    A profile of what is held *now*, which is not what the book did — that is
    `/portfolio/performance`, and the two disagree by exactly as much as the
    book has changed shape. Weights are put on the reporting currency's footing
    before anything is measured, because a mostly-USD book with some EUR in it
    is weighted wrong by native prices.
    """
    if period not in _RISK_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"period must be one of {', '.join(_RISK_PERIODS)}",
        )
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    report = loaders.basket_report(db, mtime, ccy, period)
    if report is None or not report.weights:
        return Risk(base=ccy, period=period)

    allocations = {
        key: [
            AllocationSlice(label=str(label), weight=float(weight))
            for label, weight in report.allocation(key).items()
        ]
        for key in ("sector", "country", "currency")
    }
    # Custody joins only when the book actually spans brokers: a single-broker
    # 100% slice says nothing. It reuses the weights above, so it costs no fetch.
    by_broker = custody.broker_weights(loaders.custody(db, mtime), report.weights)
    if len(by_broker) > 1:
        allocations["broker"] = [
            AllocationSlice(label=broker, weight=float(weight))
            for broker, weight in sorted(by_broker.items(), key=lambda kv: -kv[1])
        ]

    corr = correlation_matrix(report.returns)
    # The book's own line, which the report knows nothing about: `basket_report`
    # backtests today's holdings, and what the account actually earned is the
    # flow-adjusted history. Both belong on one axis or neither says much — the
    # gap between them is exactly how much the book has changed shape.
    _hist, twr, missing = loaders.history(db, mtime, ccy)
    return Risk(
        base=ccy,
        period=period,
        volatility=_num(report.volatility),
        max_drawdown=_num(report.max_drawdown),
        effective_names=_num(effective_positions(report.weights)),
        top5_weight=_num(top_n_weight(report.weights, 5)),
        betas={
            bench: value
            for bench in report.bench_returns
            if (value := _num(report.beta_vs(bench))) is not None
        },
        weights=report.weights,
        allocation={k: v for k, v in allocations.items() if v},
        correlation={
            str(row): {
                str(col): value
                for col, raw in corr.loc[row].items()
                if (value := _num(raw)) is not None
            }
            for row in corr.index
        },
        curves=_curves(report, twr),
        missing=missing,
        dropped_days=[
            str(pd.Timestamp(day).date()) for day in twr.attrs.get("dropped_days", ())
        ],
    )


def _series(values: pd.Series | None, axis: pd.DatetimeIndex) -> list[float | None]:
    """A cumulative series read on `axis`, as JSON-safe floats.

    Reindexed, never interpolated: the axis is a subset of the calendar the
    book's return is sampled on, so every date either has a figure or gets a
    null. Filling one forward would draw a flat weekend as a fact.
    """
    if values is None or values.empty:
        return [None] * len(axis)
    return [_num(v) for v in cumulative_returns(values).reindex(axis)]


def _curves(report, twr: pd.Series) -> RiskCurves | None:
    """The three lines on one axis: the book, today's basket, the benchmarks.

    The axis is the basket's trading days, and everything else is clipped to
    its first day before compounding — a benchmark that starts from its own
    zero two years earlier is not being compared to anything.
    """
    axis = report.returns.index
    if axis.empty:
        return None
    start = pd.Timestamp(axis[0])
    # An axis whose first entry is not a date has no window to clip to, and
    # `NaT` is what pandas hands back for one — it is also the reason this is
    # an isinstance check and not a truth test.
    if not isinstance(start, pd.Timestamp):
        return None
    if start.tz is not None:
        start = start.tz_localize(None)
    window = twr[twr.index >= start.normalize()] if not twr.empty else twr
    return RiskCurves(
        dates=[str(pd.Timestamp(day).date()) for day in axis],
        portfolio=_series(window, axis),
        basket=_series(report.port_returns, axis),
        benchmarks={
            name: _series(series, axis)
            for name, series in report.bench_returns.items()
        },
    )


# ------------------------------------------------------------- starting over
# The page offers this as a checkbox beside the upload ("wipe first"), which is
# the right shape there: a person is looking at their own book and at the file
# that will replace it. It is the wrong shape for a client, where a stray
# boolean on an unrelated request would destroy a ledger nobody can restore —
# so here it is a route of its own, and it has to be told what it is deleting.


class Wipe(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: str = Field(
        description=(
            "The signed-in address, typed back. This deletes every transaction "
            "and there is no undo, so the request has to name the book it is "
            "emptying — a client cannot do this by accident."
        )
    )


@router.delete(
    "/transactions",
    response_model=LedgerCleared,
    summary="Delete every transaction",
)
def wipe(caller: Authed, account: Writer, body: Wipe) -> LedgerCleared:
    """Empty the book. There is no undo, and no backup is taken.

    `DELETE /import/last` is what almost every caller wants instead: it removes
    one batch, by the ids that batch inserted. This removes everything, including
    rows typed in by hand years ago and every import before the last one.
    """
    if body.confirm.strip().lower() != (caller.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="confirm must be the signed-in address, exactly",
        )
    removed = len(all_transactions(account.db))
    clear(account.db)
    # The last-import record points at ids that no longer exist, and offering
    # an undo of a batch inside a book that is gone would be a lie.
    last_import.forget(account.last_import)
    obs.event("ledger.wiped", rows=removed, via="api")
    return LedgerCleared(removed=removed)


# ---------------------------------------------------------------- the demo book
# Everything on this page derives from the ledger, so an account that has not
# imported yet finds positions, P/L, allocation, risk, dividends, fees and the
# tax report blank at once. The example statement (`GET /v1/import/sample`) is
# the honest answer for a reader ready to import; this is the other half of it,
# for one who wants to look first. Fabricated rows in an app that also files
# tax reports are only safe while both promises hold: every row is marked
# `demo` (the note's first word, which is what `fees.broker_of` reads), and the
# first real import deletes them — `POST /v1/import/commit` still does, so a
# book seeded from here cannot leak an invented cost basis into a real one.


class DemoBook(BaseModel):
    active: bool = Field(description="Whether the book holds demo rows now.")
    rows: int = Field(description="Demo rows this call wrote, or removed.")


@router.post("/demo", response_model=DemoBook, summary="Fill an empty book")
def seed_demo(account: Writer) -> DemoBook:
    """Write the demo book, if this ledger is empty.

    409 when it is not, rather than a quiet `rows: 0`: `demo.seed` refuses a
    ledger holding anything at all — a double click and a stale retry both
    arrive here, and a second copy of the book would be a doubled cost basis —
    and a client told "ok, 0" would show a book that was never written.
    """
    ids = demo.seed(account.db)
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this book already holds the demo rows"
                if demo.active(account.db)
                else "this book holds transactions; the demo one is only for an "
                "empty ledger"
            ),
        )
    obs.event("demo.seeded", rows=len(ids), via="api")
    return DemoBook(active=True, rows=len(ids))


@router.delete("/demo", response_model=DemoBook, summary="Remove the demo rows")
def clear_demo(account: Writer) -> DemoBook:
    """Delete every demo row, and only those.

    Matched on the `demo` origin rather than on the ids that were seeded, so a
    book seeded twice in two sessions still comes out clean. Real rows are
    never touched: a note beginning with any other word is somebody's own.
    """
    removed = demo.clear(account.db)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this book holds no demo rows",
        )
    obs.event("demo.cleared", rows=removed, via="api")
    return DemoBook(active=False, rows=removed)
