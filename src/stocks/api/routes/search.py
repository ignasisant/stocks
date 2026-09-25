"""The ticker search box, and the short history behind it.

The ranking is not here and must not be: `stocks.search` owns which tier
answers first and how the tiers dedup, and the Streamlit top bar reads it from
the same place. This route is the binding — the account's own list, the caches
that keep a keystroke off the network, and the JSON shape.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query

from stocks import accounts, search
from stocks.api import loaders
from stocks.api.deps import Account, Writer
from stocks.api.schemas import Recents, SearchMatch, SearchResults
from stocks.config import load_watchlist

router = APIRouter(tags=["search"])


def _catalog(account) -> search.Catalog:
    db = str(account.db)
    return search.account_catalog(
        load_watchlist(account.watchlist),
        loaders.held(db, loaders.db_mtime(db)),
        loaders.sec_title,
    )


@router.get("/search", response_model=SearchResults, summary="Find a ticker")
def find(
    account: Account,
    q: Annotated[str, Query(description="Symbol, company name or tag group.")] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResults:
    """Every tier for `q`, deduped and already in the order to draw.

    An empty query answers with no matches rather than the whole watchlist:
    the box is a search, and a client that wants the list has `/watchlist`.
    """
    rows = search.ranked(
        q,
        _catalog(account),
        crypto=loaders.coin_matches,
        funds=loaders.fund_matches,
        sec=loaders.sec_matches,
        world=loaders.world_matches,
        limit=limit,
    )
    return SearchResults(
        query=q.strip().upper(),
        matches=[
            SearchMatch(
                ticker=row.ticker,
                name=row.name,
                kind=row.kind,
                mark=row.mark,
                exchange=row.exchange,
            )
            for row in rows
        ],
    )


@router.get("/search/recent", response_model=Recents, summary="Recently opened")
def recent(account: Account) -> Recents:
    """What the box offers an empty, focused field — the same list the app shows."""
    return Recents(tickers=accounts.load_recent_searches(account.prefs))


@router.post("/search/recent", response_model=Recents, summary="Record one")
def remember(
    account: Writer,
    ticker: Annotated[str, Body(embed=True, max_length=32)],
) -> Recents:
    """Push a ticker onto the account's recent list.

    It exists because a recents list that never grows is worse than none: the
    reader would see five names frozen at whatever the Streamlit page last
    stored.

    A session only, like every write here. A bearer token names nobody and any
    holder can name any account, so a token that could write this would be able
    to plant entries in anybody's search history.

    It is a JSON body rather than a form or a query, which is what makes it safe
    under cookie auth: a cross-site form post cannot set
    `Content-Type: application/json`, and a cross-site `fetch` that does gets
    preflighted — and nothing here answers a preflight.
    """
    return Recents(tickers=accounts.push_recent_search(account.prefs, ticker))
