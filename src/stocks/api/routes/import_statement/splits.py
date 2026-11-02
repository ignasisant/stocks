"""Splits the book never heard about: scan the holdings, apply the picked ones."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api.deps import Account, Writer
from stocks.api.jsonsafe import num as _num
from stocks.api.routes.import_statement.validation import _real_rows
from stocks.data import fetch
from stocks.portfolio import (
    corporate,
)
from stocks.portfolio.ledger import add_many

router = APIRouter(prefix="/import", tags=["import"])


# A statement prints trades and not the 20:1 split between them, so a position
# bought before one and never sold keeps a pre-split share count and a pre-split
# cost basis for ever, and reads as a loss nobody took. The import-time rescue
# in validate.py only fires when a *sell* comes up short, and a position nobody
# sold never comes up short — so this repair has to be reachable without an
# import at all.


class SplitGap(BaseModel):
    """One split the ledger is missing, with the evidence that found it.

    The evidence travels with the proposal because the proposal is only worth
    acting on beside it: this holding was bought at `priced_at` on `priced_on`,
    a day whose split-adjusted close was `market_close`, and the quotient of
    those two is a split the ledger never recorded.
    """

    ticker: str
    date: str = Field(description="The split's own day, YYYY-MM-DD.")
    ratio: float = Field(
        description="Shares out per share in — 20.0 for a 20-for-1 split."
    )
    held_before: float | None = Field(
        description="Shares the ledger holds the day before the split."
    )
    held_after: float | None = Field(
        description="Shares it would hold after — what applying this corrects."
    )
    priced_at: float | None = Field(
        description="The pre-split buy price the evidence came from."
    )
    priced_on: str = Field(description="…and that buy's date.")
    market_close: float | None = Field(
        description="Yahoo's split-adjusted close on `priced_on`."
    )
    currency: str = Field(description="What `priced_at` and `market_close` are in.")


class SplitGaps(BaseModel):
    splits: list[SplitGap] = Field(
        default_factory=list, description="Oldest first, the order they apply in."
    )
    throttled: bool = Field(
        default=False,
        description=(
            "Yahoo was refusing this deployment while the scan ran, so an empty "
            "list means 'could not tell' rather than 'nothing missing'. A "
            "throttled lookup answers with silence instead of an error — right "
            "for a page that still has to render, and not enough for a client "
            "about to show a clean bill of health."
        ),
    )


class SplitPick(BaseModel):
    """One scanned split, named by the two fields that identify it."""

    model_config = {"extra": "forbid"}

    ticker: str = Field(min_length=1, max_length=32)
    date: str = Field(
        min_length=10, max_length=10, description="YYYY-MM-DD, as the scan gave it."
    )


class ApplySplits(BaseModel):
    model_config = {"extra": "forbid"}

    splits: list[SplitPick] = Field(
        min_length=1,
        max_length=200,
        description=(
            "Which of the scanned splits to write. Named rather than 'all': the "
            "scan shows its evidence one row at a time, and a reader who "
            "believes one of them and not another has to be able to say so."
        ),
    )


class SplitsApplied(BaseModel):
    applied: int = Field(description="Split rows written.")
    tx_ids: list[int] = Field(
        default_factory=list,
        description="Their ledger ids — `DELETE /v1/portfolio/transactions` "
        "aside, this is the only handle on them afterwards.",
    )
    splits: list[SplitGap] = Field(
        default_factory=list, description="What was written, as the scan described it."
    )


def _gap(gap: corporate.MissingSplit) -> SplitGap:
    return SplitGap(
        ticker=gap.ticker,
        date=gap.tx.date,
        ratio=gap.ratio,
        held_before=_num(gap.held_before),
        held_after=_num(gap.held_after),
        priced_at=_num(gap.priced_at),
        priced_on=gap.priced_on,
        market_close=_num(gap.market_close),
        currency=gap.tx.currency,
    )


def _missing_splits(account) -> list[corporate.MissingSplit]:
    rows = _real_rows(account)
    if not rows:
        return []
    return corporate.missing_splits(
        rows, splits=fetch.splits, close_on=fetch.close_on
    )


@router.get(
    "/splits/scan", response_model=SplitGaps, summary="Splits the ledger is missing"
)
def splits_scan(account: Account) -> SplitGaps:
    """Price this book's holdings against Yahoo and report the splits it lacks.

    A GET although it is the expensive call here — a round-trip per ticker, and
    seconds rather than milliseconds. It takes no body, reads the account's own
    ledger and a public corporate-actions history, and writes nothing, so it is
    safe and idempotent and there is no second thing for a POST to mean.
    Spending "this is not a read" on "this is not cheap" would leave the verb
    saying nothing about either.
    """
    found = _missing_splits(account)
    return SplitGaps(
        splits=[_gap(gap) for gap in found],
        throttled=fetch.throttle_remaining() > 0,
    )


@router.post(
    "/splits/apply", response_model=SplitsApplied, summary="Write the split rows"
)
def splits_apply(account: Writer, body: Annotated[ApplySplits, ...]) -> SplitsApplied:
    """Write the named splits, and only those.

    The body says *which* split, never what it is: the ratio, the date and the
    row that lands in the ledger all come from a scan run here and now. So a
    client cannot invent a 1000-for-1 split by asking for one, and cannot
    replay a stale answer — a split another client applied a second ago is not
    missing any more, and writing it again would square the share count.

    A name this scan does not propose is a 409 and nothing is written, rather
    than a silent skip that would read as success.
    """
    found = {(gap.ticker, gap.tx.date): gap for gap in _missing_splits(account)}
    picked: list[corporate.MissingSplit] = []
    seen: set[tuple[str, str]] = set()
    for pick in body.splits:
        key = (pick.ticker.strip().upper(), pick.date.strip())
        if key in seen:
            continue
        seen.add(key)
        gap = found.get(key)
        if gap is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{key[0]} on {key[1]} is not a split this ledger is missing "
                    "— scan again"
                ),
            )
        picked.append(gap)
    ids = add_many([gap.tx for gap in picked], account.db)
    obs.event("import.splits_applied", n=len(ids), via="api")
    return SplitsApplied(
        applied=len(ids), tx_ids=ids, splits=[_gap(gap) for gap in picked]
    )
