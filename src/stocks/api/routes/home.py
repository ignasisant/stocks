"""The two Home reads and one write that no other route already answers.

`/market/quotes` is a live snapshot, and the Home watchlist is not: its column
says *last close*, and its day % is close-to-close — re-read from the quote
burst only for names whose own exchange is shut, where the newest daily bar can
be a flat premarket 0%. That is `home.py`'s `_watch_table`, and printing a live
premarket price under a "last close" header is the kind of small untruth this
page exists not to tell. So the rows get their own route, reading the page's
one year-of-closes download (`api/home.py`).

And the refresh. The Streamlit button drops the page's price caches and
reruns; the React one used to ask again, which answers from the same TTL caches
it meant to get past. `POST /home/refresh` is that button's server half.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from stocks.analysis.portfolio import market_active
from stocks.api import briefing, home, loaders
from stocks.api.deps import Account, Writer

router = APIRouter(tags=["home"])

# The shortest gap between two cache drops. The caches are process-wide — a
# price download is shared by every account tracking the same names, which is
# the point of them — so a button anybody can press is a button that could keep
# the whole deployment asking Yahoo, and Yahoo throttles datacenter IPs. Inside
# this window a press is still answered, it just does not drop anything twice.
REFRESH_COOLDOWN_S = 30.0

# Never, rather than zero: `time.monotonic()` can itself be under the cooldown
# on a container that booted seconds ago.
_last_refresh = float("-inf")
_refresh_lock = threading.Lock()


class CloseRow(BaseModel):
    ticker: str
    close: float | None = Field(
        default=None, description="Last daily close, in the name's own currency."
    )
    pct: float | None = Field(
        default=None,
        description=(
            "Day move as a fraction: close-to-close, or — for a name whose "
            "exchange is shut — the quote's pre/after-hours or last-session move."
        ),
    )
    as_of: str | None = Field(
        default=None,
        description="The session `pct` is from, when it came off a quote.",
    )
    active: bool = Field(
        description=(
            "Whether the name has a live quote now (regular session, or US "
            "pre/after-hours). False greys the day figure: it is real, but it "
            "is not moving."
        )
    )


class Closes(BaseModel):
    rows: list[CloseRow] = Field(default_factory=list)


class Refreshed(BaseModel):
    cleared: bool = Field(
        description=(
            "Whether this press dropped the caches. False inside the cooldown "
            "after somebody else's press — the prices are already that fresh."
        )
    )


@router.get("/home/closes", response_model=Closes, summary="Watchlist closes")
def closes(account: Account) -> Closes:
    """Last close and day % for every watchlist name, with `home.py`'s rule.

    One row per watchlist entry, in list order. A name the download missed
    still gets its row, with null figures, so the group keeps its shape and the
    cell says "n/a" instead of the name vanishing.
    """
    entries = home.holdings(account)
    if not entries:
        return Closes()
    tickers = list(dict.fromkeys(h.ticker for h in entries))
    try:
        year = home.year_closes(home.closes_tuple(entries, home.held(account)))
    except Exception:  # noqa: BLE001 — a throttled burst is n/a cells, not a 500
        year = {}
    moves = home.last_closes(tickers, year)
    return Closes(
        rows=[
            CloseRow(
                ticker=ticker,
                close=moves[ticker][0],
                pct=moves[ticker][1],
                as_of=moves[ticker][2],
                active=market_active(ticker),
            )
            for ticker in tickers
        ]
    )


@router.post("/home/refresh", response_model=Refreshed, summary="Refresh prices")
def refresh(account: Writer) -> Refreshed:
    """Drop the price caches, so the next reads download again.

    The same set `home.py`'s button clears — watchlist closes (the rows and the
    52-week scan), the book's close download and everything priced off it
    (positions, the basket, the history) — plus the quote burst, which is what
    the off-session day figures read. The ledger replays stay hot: a refresh is
    about prices, and the ledger only changes on an import, which rekeys its
    own entries by mtime.

    Process-wide, because the caches are: a price download is shared by every
    account tracking the same names. Hence the cooldown. A session only, like
    every other write — a bearer token has no business pressing buttons.
    """
    global _last_refresh
    now = time.monotonic()
    with _refresh_lock:
        if now - _last_refresh < REFRESH_COOLDOWN_S:
            return Refreshed(cleared=False)
        _last_refresh = now
    for memo in (
        loaders.watchlist_closes,
        loaders.held_closes,
        loaders.positions_table,
        loaders.basket_values,
        loaders.history,
        loaders.quotes,
        briefing._card_closes,
    ):
        # Looked up rather than assumed: every one of these is a `ttl_cache`
        # today, and a loader that stops being one should stop being cleared,
        # not turn the button into a 500.
        clear = getattr(memo, "cache_clear", None)
        if clear is not None:
            clear()
    return Refreshed(cleared=True)
