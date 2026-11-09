"""Review: what to sell, trim, keep or add to, and which outside names to buy.

The read is `stocks.views.review`; this route speaks HTTP for it — the
reporting currency from `?base=`, the import wall, a bad ticker list as a 422,
and the score trail and journal written after the answer has gone.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from stocks import accounts, obs
from stocks.api.deps import Account, Base, reporting_currency
from stocks.schemas import Review, ReviewReturns
from stocks.views import review as view

router = APIRouter(tags=["review"])


def _judge(account, background: BackgroundTasks, ccy: str, add: str) -> Review:
    try:
        return view.judge(account, ccy, add, background.add_task)
    except view.BadTickers as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/review", response_model=Review, summary="What to sell and what to add")
def review(
    account: Account,
    background: BackgroundTasks,
    base: Base = None,
    add: Annotated[
        str,
        Query(
            description=(
                "Comma-separated tickers to weigh beside the watchlist's, "
                f"at most {view.MAX_ADDED}. Nothing is written."
            )
        ),
    ] = "",
) -> Review:
    ccy = reporting_currency(account, base)
    # An account with nothing of its own to judge gets the wall, not a review
    # of the starter watchlist: the page is the reason to import. The guest
    # dir is the demo book every visitor reads, so a guest is never walled.
    if account.root != accounts.GUEST_DIR and not view.imported(account):
        obs.event("review.locked", base=ccy)
        return Review(base=ccy, as_of=date.today().isoformat(), locked=True)
    return _judge(account, background, ccy, add)


@router.get(
    "/review/preview",
    response_model=Review,
    summary="The demo book judged, for the wall of an account with no import",
)
def preview(background: BackgroundTasks, base: Base = None) -> Review:
    guest = accounts.guest_paths()
    return _judge(guest, background, reporting_currency(guest, base), "")


@router.get(
    "/review/returns",
    response_model=ReviewReturns,
    summary="What each name returned, beside the index and its sector",
)
def returns(
    account: Account,
    names: Annotated[
        str,
        Query(
            description=(
                f"Comma-separated symbols, at most {view.MAX_RETURNS}: the review's "
                "rows as `symbol`."
            )
        ),
    ] = "",
    base: Base = None,
) -> ReviewReturns:
    """Total return in the reader's money over 1m, 6m, 1y and 2y per name,
    and the same for SPY and each name's sector ETF, so the page can say by
    how much a name led or lagged either (`views.review.returns`)."""
    ccy = reporting_currency(account, base)
    try:
        return view.returns(account, ccy, names)
    except view.BadTickers as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
