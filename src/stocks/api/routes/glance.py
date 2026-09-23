"""The dashboard's opening: the briefing, the movers, the 52-week edges.

Three small reads rather than one "home" blob, because they are three different
facts with three different lifetimes — a briefing is written once a day, movers
change every few minutes, and an extreme changes on a close. A client that wants
all three asks for all three; one that only shows movers does not pay for a
model's prose.

The rest of that page is already here: the KPI row is `/portfolio/summary` and
`/portfolio/performance`, the transactions strip is `/portfolio/transactions`,
the calendar is `/earnings`, and the groups are `/watchlist`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from stocks.analysis.portfolio import (
    basket_change,
    day_change,
    market_live,
    ticker_changes,
    ticker_day_changes,
    us_market_open,
)
from stocks.api import loaders
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import DailyCard, Extreme, Extremes, Mover, Movers
from stocks.chat import daily
from stocks.config import load_watchlist

router = APIRouter(tags=["glance"])

# The windows the dashboard offers, in calendar days. Named so "week" means the
# same five days here as it does on the page.
WINDOWS = {"day": 1, "week": 7, "month": 30}

# How many names each side of a movers card shows. More than this and it stops
# being a glance.
SHOWN = 6

# How close to an extreme still counts as being at it. A stock 1.4% off its
# 52-week high is at its high in every sense a reader cares about.
EDGE_BAND = 0.02


@router.get("/daily", response_model=DailyCard, summary="Today's briefing")
def card(
    account: Account,
    lang: Annotated[
        str,
        Query(
            min_length=2,
            max_length=8,
            description="Language the freshness check judges the card in.",
        ),
    ] = "en",
) -> DailyCard:
    """The stored card, and whether it is still the right one.

    Freshness is not just the date. The card is prose, so a reader who switched
    the app to Spanish should not be left with yesterday's English briefing; and
    a card written before the open quotes the previous close, so once the next
    session lands its every figure is a day behind while the calendar date has
    not moved yet. Both are checked here.
    """
    now = datetime.now().astimezone()
    day = daily.action_day(now)
    stored = daily.DailyAction.from_dict(
        loaders.stored_action(str(account.action), loaders.file_mtime(account.action))
    )
    answer = DailyCard(
        action_day=day.isoformat(), cutoff_hour=daily.CUTOFF_HOUR, fresh=False
    )
    if stored is None:
        return answer
    return DailyCard(
        day=stored.day,
        headline=stored.headline,
        bullets=list(stored.bullets),
        focus=list(stored.focus),
        as_of=stored.as_of or None,
        lang=stored.lang,
        source=stored.source,
        action_day=day.isoformat(),
        cutoff_hour=daily.CUTOFF_HOUR,
        fresh=daily.is_fresh(stored, day, lang, _last_session(account)),
    )


def _last_session(account) -> str | None:
    """The newest close date across this account's holdings, ISO, or None.

    A card is stale the moment a session it does not quote has closed, and the
    calendar cannot see that. Read off the book's own shared price download, so
    it costs nothing a portfolio read has not already paid for.
    """
    db = str(account.db)
    closes = loaders.held_closes(db, loaders.db_mtime(db))
    latest = [s.index[-1] for s in closes.values() if not s.empty]
    return str(pd.Timestamp(max(latest)).date()) if latest else None


@router.get("/movers", response_model=Movers, summary="What moved")
def movers(
    account: Account,
    window: Annotated[str, Query(description="day | week | month.")] = "day",
    base: Base = None,
) -> Movers:
    """The book's best and worst names over one window, and the book itself.

    The book's move comes back as both money and a percentage, because a tile
    that shows only the percentage twice is showing one thing twice: `amount`
    is what moved, `basket` is what that was worth relatively. The currency
    matters to both — the basket is valued in the reporting currency, so a
    position's move includes its FX move, which is how the book is judged.

    Measured on a basket held at today's quantities (`loaders.basket_values`),
    never on the book's own value history: that one carries deposits and
    imports, and a €12k book that took €38k on a Monday would read "+316% this
    week" with the market flat.

    The day window is the one that cannot be read off closes alone. Outside a
    regular session the newest daily bar is stale or flat, and the basket then
    reports a book that never moved — so the names whose own exchange is shut
    are re-read from `session_quotes`: the live pre/after-hours move while
    there is one, the last completed session afterwards. `as_of` says which
    session that was, and `unpriced` how much of the book is missing from all
    of it.
    """
    if window not in WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"window must be one of {', '.join(WINDOWS)}",
        )
    days = WINDOWS[window]
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    ccy = reporting_currency(account, base)
    held = loaders.ledger_state(db, mtime, ccy)[1]
    frame = loaders.basket_values(db, mtime, ccy).dropna(how="all")
    answer = Movers(
        window=window,
        base=ccy,
        positions=len(held),
        unpriced=len([p for p in held if p.ticker not in frame.columns]),
    )
    if frame.empty:
        return answer

    quotes: dict[str, dict] | None = None
    if days <= 1 and not us_market_open():
        # Only the names actually outside their own session: a Paris listing
        # is live at 10:00 CET with New York hours away, and crypto never
        # shuts. Costs one quote burst, cached, and only while the US is shut.
        off = tuple(t for t in frame.columns if not market_live(str(t)))
        quotes = loaders.quotes(off) if off else {}

    if days <= 1:
        changes = ticker_day_changes(frame, quotes)
        whole = day_change(frame, quotes)
    else:
        changes = ticker_changes(frame, days)
        whole = basket_change(frame, days)
    changes = changes.dropna().sort_values(ascending=False)

    answer.gainers = [
        Mover(ticker=str(t), pct=float(v))
        for t, v in changes[changes > 0].head(SHOWN).items()
    ]
    answer.losers = [
        Mover(ticker=str(t), pct=float(v))
        for t, v in changes[changes < 0].tail(SHOWN).sort_values().items()
    ]
    if whole:
        answer.amount, answer.basket = _num(whole[0]), _num(whole[1])
    answer.as_of = _as_of(frame, quotes)
    return answer


def _as_of(frame: pd.DataFrame, quotes: dict[str, dict] | None) -> str | None:
    """Which session the figures are from: the quotes' own, else the last bar.

    The quotes agree with each other in practice (they are one burst against
    one clock) but not necessarily with the bars, and the newest of the two is
    the one a reader is looking at.
    """
    stamps = {q["as_of"] for q in (quotes or {}).values() if q.get("as_of")}
    if stamps:
        return max(stamps)
    return str(pd.Timestamp(frame.index[-1]).date()) if len(frame.index) else None


@router.get("/extremes", response_model=Extremes, summary="At a 52-week edge")
def extremes(account: Account) -> Extremes:
    """Watchlist names sitting within 2% of a 52-week high or low.

    One bulk year of closes over the watchlist, shared with any other account
    tracking the same names. `distance` is null at or beyond the edge, which is
    a different fact from being 0% away from it.
    """
    tickers = tuple(sorted({h.ticker for h in load_watchlist(account.watchlist)}))
    year = loaders.watchlist_closes(tickers)
    out: list[Extreme] = []
    for ticker in tickers:
        series = year.get(ticker)
        closes = [] if series is None else [float(v) for v in series.dropna()]
        if len(closes) < 2:
            continue
        last, high, low = closes[-1], max(closes), min(closes)
        if high and last >= high * (1 - EDGE_BAND):
            out.append(
                Extreme(
                    ticker=ticker,
                    price=last,
                    edge="high",
                    distance=None if last >= high else last / high - 1,
                )
            )
        elif low and last <= low * (1 + EDGE_BAND):
            out.append(
                Extreme(
                    ticker=ticker,
                    price=last,
                    edge="low",
                    distance=None if last <= low else last / low - 1,
                )
            )
    return Extremes(extremes=out)
