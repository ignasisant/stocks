"""What the book earned and what trading it cost: dividends and fees."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from urllib.error import URLError

from fastapi import APIRouter, Query
from yfinance.exceptions import YFRateLimitError

from stocks import loaders, obs
from stocks.api.deps import Account, Base, reporting_currency
from stocks.jsonsafe import num as _num
from stocks.portfolio import dividends, fees
from stocks.schemas import (
    BrokerCost,
    Dividends,
    DividendYear,
    Fees,
    ForwardHolding,
    UnbookedDividend,
    UnbookedDividends,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/fees", response_model=Fees, summary="What trading it cost")
def fees_(
    account: Account,
    base: Base = None,
    year: Annotated[
        int | None,
        Query(description="Only rows dated in this calendar year."),
    ] = None,
) -> Fees:
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
    txs = loaders.ledger_state(db, mtime, ccy).txs
    if year is not None:
        txs = [t for t in txs if t.date.startswith(f"{year}-")]
    brokers = fees.by_broker(txs, base=ccy)
    if not brokers:
        return Fees(base=ccy)

    # The spread needs the trade-day bars; the commissions do not. A throttled
    # or offline Yahoo therefore degrades this endpoint to its ledger half
    # instead of 503-ing a question the ledger can answer on its own — and so
    # does any other failure on that half (a malformed frame, an FX gap): it is
    # an estimate, and losing it must not take the ledger's facts down with it.
    # Only the unexpected ones are logged.
    spreads: dict[str, fees.SpreadStats] = {}
    measured = False
    try:
        spreads = fees.spread_by_broker(txs, loaders.trade_bars(db, mtime), base=ccy)
        measured = True
    except (YFRateLimitError, URLError):
        pass
    except Exception as exc:  # noqa: BLE001 — degrade, see above
        obs.error("api.fees_spread_failed", exc)

    rows = []
    for name in sorted(brokers, key=lambda n: -brokers[n].volume):
        broker, stats = brokers[name], spreads.get(name)
        spread = stats.spread if stats else (0.0 if measured else None)
        # A fill that beat the day's mid is reported, but never as a refund:
        # what the broker charged stays the floor of what trading cost.
        total = broker.explicit + max(spread or 0.0, 0.0) if measured else None
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
    cost = explicit + sum(max(s.spread, 0.0) for s in spreads.values())
    return Fees(
        base=ccy,
        brokers=rows,
        explicit=explicit,
        spread=_num(spread_total) if measured else None,
        cost=_num(cost) if measured else None,
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
    txs = loaders.ledger_state(db, mtime, ccy).txs
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


@router.get(
    "/dividends/unbooked",
    response_model=UnbookedDividends,
    summary="Dividends owed with no ledger row",
)
def dividends_unbooked(
    account: Account,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    base: Base = None,
) -> UnbookedDividends:
    """Each payment the shares were entitled to that the ledger never booked.

    `/dividends` sums these per year as `unrecorded`; this lists them, so a
    statement exported in July does not leave August's dividends out of the
    book's recent activity. A ledger dividend answers for one entitlement of
    its ticker that went ex in the quarter before it. Estimates throughout —
    gross, dated by the ex-date — and a throttled Yahoo is `available: false`,
    not an empty list that would read as nothing owed.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    try:
        rows = loaders.unbooked_dividends(db, loaders.db_mtime(db), ccy)
    except (YFRateLimitError, URLError):
        return UnbookedDividends(base=ccy)
    return UnbookedDividends(
        base=ccy,
        total=len(rows),
        available=True,
        payments=[
            UnbookedDividend(
                ticker=p.ticker,
                ex_date=p.ex_date,
                per_share=p.per_share,
                shares=p.shares,
                currency=p.currency,
                gross=_num(p.gross) or 0.0,
                amount=_num(amount),
            )
            for p, amount in rows[:limit]
        ],
    )
