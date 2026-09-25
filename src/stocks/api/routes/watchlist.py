"""The account's watchlist, as stored.

Prices are deliberately absent: a watchlist is a list of names, and pricing it
here would fetch a batch nobody asked for. A caller that wants both reads this
and `/market/quotes`, which is one extra request and one cache the whole
deployment shares.
"""

from __future__ import annotations

from fastapi import APIRouter

from stocks.api.deps import Account
from stocks.api.schemas import Watchlist, WatchlistEntry
from stocks.config import load_watchlist
from stocks.data.crypto import is_crypto

router = APIRouter(tags=["watchlist"])


@router.get("/watchlist", response_model=Watchlist, summary="Tracked tickers")
def watchlist(account: Account) -> Watchlist:
    return Watchlist(
        entries=[
            WatchlistEntry(
                ticker=holding.ticker,
                name=holding.name,
                favorite=holding.favorite,
                tags=list(holding.tags),
                # 0 and None are both "no position" on disk; one spelling on
                # the wire, so the client's empty cell means one thing.
                shares=holding.shares or None,
                cost=holding.cost or None,
                is_crypto=is_crypto(holding.ticker),
            )
            for holding in load_watchlist(account.watchlist)
        ]
    )
