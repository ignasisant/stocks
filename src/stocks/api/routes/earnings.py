"""When the watchlist reports, and what happened last time.

One endpoint rather than two: the fetch that finds the next date already
carries the past quarters' columns, so splitting them would double the requests
to Yahoo to say the same thing twice.

The filter sets ship with it. A client could rebuild "portfolio" from
`/portfolio/positions` and "favorites" from `/watchlist`, but the tag groups
would still have to be re-derived and the empty ones dropped — three round
trips and a rule, for something one pass over the same watchlist already knows.
"""

from __future__ import annotations

from fastapi import APIRouter

from stocks.api import loaders
from stocks.api.deps import Account
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import CalendarEvent, CalendarResult, EarningsCalendar
from stocks.config import load_watchlist
from stocks.data.crypto import is_crypto
from stocks.data.funds import is_fund

router = APIRouter(tags=["earnings"])


@router.get("/earnings", response_model=EarningsCalendar, summary="Reporting calendar")
def earnings(account: Account) -> EarningsCalendar:
    """The account's watchlist calendar: what is coming and what already printed.

    Coins and funds are dropped before the fetch — neither ever reports, and
    asking spends a request on Yahoo answering "no earnings dates found". They
    come back in `skipped` instead of vanishing, so a client showing a watchlist
    beside this does not have to explain the gap itself. Fund classification
    stays cache-only: a cold cache leaves a fund in the list rather than
    blocking the calendar on a lookup.
    """
    holdings = load_watchlist(account.watchlist)
    reporting = [
        h
        for h in holdings
        if not is_crypto(h.ticker) and not is_fund(h.ticker, fetch=False)
    ]
    covered = {h.ticker for h in reporting}
    skipped = [h.ticker for h in holdings if h.ticker not in covered]

    events, results = loaders.earnings_calendar(
        tuple(sorted(h.ticker for h in reporting))
    )

    # Portfolio = open ledger positions, plus any watchlist entry carrying
    # shares. The two disagree whenever a name was added by hand.
    db = str(account.db)
    held = set(loaders.held(db, loaders.db_mtime(db)))
    groups: dict[str, list[str]] = {}
    if portfolio := held | {h.ticker for h in reporting if h.is_position}:
        groups["portfolio"] = sorted(portfolio)
    if favorites := {h.ticker for h in reporting if h.favorite}:
        groups["favorites"] = sorted(favorites)
    tags: dict[str, set[str]] = {}
    for holding in reporting:
        for tag in holding.tags:
            tags.setdefault(tag, set()).add(holding.ticker)
    groups.update({tag: sorted(names) for tag, names in sorted(tags.items())})

    return EarningsCalendar(
        upcoming=[
            CalendarEvent(
                ticker=event.ticker,
                date=event.date.isoformat() if event.date else None,
                days_until=event.days_until,
            )
            for event in events
        ],
        results=[
            CalendarResult(
                ticker=result.ticker,
                date=result.date.isoformat(),
                eps_estimate=_num(result.eps_estimate),
                reported_eps=_num(result.reported_eps),
                surprise_pct=_num(result.surprise_pct),
                beat=result.beat,
            )
            for result in results
        ],
        groups=groups,
        skipped=skipped,
    )
