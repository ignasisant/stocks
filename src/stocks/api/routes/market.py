"""Live market data — the same single-request quote burst the pages use."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from stocks.analysis.portfolio import (
    market_active,
    market_live,
    us_extended_session,
    us_market_open,
)
from stocks.api import loaders
from stocks.api.deps import Account
from stocks.api.schemas import Profile, Profiles, Quote, Quotes

router = APIRouter(prefix="/market", tags=["market"])

# One request covers the batch, but Yahoo throttles shared cloud IPs hard, so
# the batch is not unbounded: a caller wanting more asks twice.
_MAX_TICKERS = 50


@router.get("/quotes", response_model=Quotes, summary="Live quotes for tickers")
def quotes(
    tickers: Annotated[
        str, Query(description="Comma-separated tickers, e.g. AAPL,MSFT,BTC-EUR.")
    ],
) -> Quotes:
    """Current price and day move per ticker, in ONE upstream request.

    A ticker with no quote — unknown symbol, or a throttled fetch — comes back
    under `unavailable` rather than as a zero. Read `as_of` before printing the
    move as today's: off-hours it is the last completed session.
    """
    wanted = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="tickers must name at least one symbol",
        )
    if len(wanted) > _MAX_TICKERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"at most {_MAX_TICKERS} tickers per request",
        )
    # Deduplicated and ordered so two spellings of the same request share one
    # cache entry instead of each fetching the batch again.
    found = loaders.quotes(tuple(sorted(set(wanted))))
    return Quotes(
        quotes=[
            Quote(
                ticker=ticker,
                price=snapshot.get("price"),
                pct=snapshot.get("pct"),
                session=snapshot.get("session"),
                as_of=snapshot.get("as_of"),
            )
            for ticker, snapshot in found.items()
        ],
        unavailable=[t for t in wanted if t not in found],
    )


@router.get("/profiles", response_model=Profiles, summary="Names and logos in bulk")
def profiles(account: Account, tickers: Annotated[str, Query(
    description="Comma-separated tickers, e.g. AAPL,MSFT,BTC-EUR.",
)]) -> Profiles:
    """What a list of tickers is called, and the logo to draw beside each.

    Every screen that lists holdings needs both: the house rule is that a
    ticker on screen is a logo and a link, never a bare symbol. Asking
    `/ticker/{symbol}/profile` per row makes a seventeen-name cohort seventeen
    requests, which is how a table gets itself rate limited.

    Account-scoped for the same reason the single one is: the name can be what
    this reader wrote on their own watchlist, and that must not leak between
    accounts.

    No fetch. Names and logos come from caches the account has already warmed,
    so a name nobody knows is an empty string and a logo nobody has is null —
    never a guess, and never a request per row.
    """
    wanted = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="tickers must name at least one symbol",
        )
    if len(wanted) > _MAX_TICKERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"at most {_MAX_TICKERS} tickers per request",
        )
    from stocks.data.crypto import is_crypto
    from stocks.data.funds import is_fund

    watchlist = str(account.watchlist)
    out: list[Profile] = []
    # Ordered as asked, deduplicated: a caller drawing a table wants its own
    # order back, not a sorted one it has to re-join against.
    for ticker in dict.fromkeys(wanted):
        resolved = loaders.display_symbol(ticker)
        out.append(
            Profile(
                ticker=ticker,
                symbol=resolved,
                name=loaders.company_name(ticker, watchlist) or "",
                logo=loaders.logo(ticker),
                is_crypto=is_crypto(resolved),
                is_fund=is_fund(resolved),
            )
        )
    return Profiles(profiles=out)


# ------------------------------------------------------------- open or shut
# Not account data and not a computation on anybody's book — the clock and a
# table of exchange hours. It is served rather than left to the client because
# the app already answers it (`analysis.portfolio.market_active`) and a second
# copy of "which exchange is open when" in JavaScript is a copy that drifts on
# the first venue whose hours change.
#
# Models inline, like `routes/me.py` and `routes/i18n.py` do it.


class TickerSession(BaseModel):
    ticker: str
    live: bool = Field(
        description="The ticker's own exchange is in its regular session now."
    )
    active: bool = Field(
        description=(
            "There is a live quote to read: the regular session, or a US "
            "pre/after-hours window. This is the one that decides whether a "
            "day-change figure is dimmed — a premarket quote is live data."
        )
    )


class MarketStatus(BaseModel):
    as_of: str = Field(description="When this was answered, UTC, ISO 8601.")
    us_open: bool = Field(description="The US equity regular session, 09:30-16:00 ET.")
    us_extended: str | None = Field(
        default=None,
        description='"pre" or "post" while that US window is open, else null.',
    )
    note: str | None = Field(
        default=None,
        description=(
            "Which caveat to print under a day-change figure, as a catalog key "
            'stem: "premarket", "postmarket" or "market_closed". The page '
            "prefixes its own page — `home.premarket_note`, "
            "`portfolio.market_closed_note` — so the wording stays the page's "
            "and only the decision is shared. Null while the session is open, "
            "when a day change needs no caveat at all."
        ),
    )
    tickers: list[TickerSession] = []


@router.get("/status", response_model=MarketStatus, summary="Open, shut or extended")
def status_(
    tickers: Annotated[
        str | None,
        Query(
            description=(
                "Optional comma-separated tickers to report per-exchange state "
                "for, e.g. AAPL,SAN.MC,BTC-EUR."
            )
        ),
    ] = None,
) -> MarketStatus:
    """Whether a figure on screen is live, and what to say when it is not.

    Two different questions, which is why there are two answers. The US block
    is the one the page-level note is written from; the per-ticker rows are
    what dims an individual cell, and they disagree with it routinely — a Paris
    name is live at 10:00 CET while New York is hours from opening, and crypto
    is live always.

    No account and no fetch: exchange hours are a table and a clock. Holidays
    are NOT modelled, so a closed holiday reads as open — a soft display cue,
    never a trading gate, exactly as the pages treat it.
    """
    open_now = us_market_open()
    extended = None if open_now else us_extended_session()
    wanted: list[str] = []
    if tickers:
        wanted = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        if len(wanted) > _MAX_TICKERS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"at most {_MAX_TICKERS} tickers per request",
            )
    return MarketStatus(
        as_of=datetime.now(UTC).isoformat(),
        us_open=open_now,
        us_extended=extended,
        note=None
        if open_now
        else "premarket"
        if extended == "pre"
        else "postmarket"
        if extended == "post"
        else "market_closed",
        # Ordered as asked and deduplicated, like `/market/profiles`: a caller
        # drawing a table wants its own order back.
        tickers=[
            TickerSession(
                ticker=ticker,
                live=market_live(ticker),
                active=market_active(ticker),
            )
            for ticker in dict.fromkeys(wanted)
        ],
    )
