"""Shares that only changed custodian: find the pairs, apply the picked ones."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import loaders, obs
from stocks.api.deps import Account, Writer
from stocks.api.routes.import_statement.validation import _real_rows
from stocks.jsonsafe import num as _num
from stocks.portfolio import (
    edits,
    transfers,
)

router = APIRouter(prefix="/import", tags=["import"])


# No statement can say "these shares moved": DEGIRO prints the departure as a
# sale at the day's price and the receiving broker prints the arrival as a
# balance. Imported literally that is a realized gain the account never made,
# a tax bill nobody owes, and a holding period restarted for no reason.
# `transfers.propose` finds the pairs from the one thing a sale and repurchase
# could not produce — an arrival carrying the basis the shares already had.


class ProposedMove(BaseModel):
    """One departure and one arrival that look like the same shares."""

    ticker_out: str = Field(description="How the losing broker's rows label it.")
    ticker_in: str = Field(
        description=(
            "How the receiving broker's do — and the label that survives: "
            "accepting renames every `ticker_out` row to this one, so the "
            "replay can see that the shares never left the book."
        )
    )
    quantity: float | None
    broker_out: str
    broker_in: str
    date_out: str = Field(description="The day the shares left.")
    date_in: str = Field(description="…and the day they turned up.")
    booked_at: float | None = Field(
        description="Per-share price the departure was recorded at — the market "
        "print the statement happened to show."
    )
    basis_out: float | None = Field(
        description="Per-share cost of the lots that left, FIFO."
    )
    basis_in: float | None = Field(
        description=(
            "Per-share cost the receiving broker reports. That this matches "
            "`basis_out` and not `booked_at` is the whole of the evidence: a "
            "real sale followed by a real repurchase reports the repurchase "
            "price instead."
        )
    )
    phantom_gain: float | None = Field(
        description="The gain the book currently reports for shares nobody "
        "sold, in `currency`."
    )
    currency: str
    rekey: bool = Field(
        description="Whether accepting also has to unify the two labels."
    )
    out_ids: list[int] = Field(description="Ledger ids of the departure rows.")
    in_id: int | None = Field(description="Ledger id of the arrival row.")


class ProposedMoves(BaseModel):
    moves: list[ProposedMove] = Field(
        default_factory=list,
        description="Largest phantom gain first — what accepting would correct.",
    )


class MovePick(BaseModel):
    """One scanned move, named by the ledger rows it is made of."""

    model_config = {"extra": "forbid"}

    out_ids: list[int] = Field(min_length=1, max_length=32)
    in_id: int | None = None


class ApplyMoves(BaseModel):
    model_config = {"extra": "forbid"}

    moves: list[MovePick] = Field(
        min_length=1,
        max_length=200,
        description=(
            "Which of the scanned moves to record. Named rather than 'all': "
            "the evidence is per holding and so is believing it."
        ),
    )


class MovesApplied(BaseModel):
    applied: int = Field(description="Moves recorded as transfers.")
    moves: list[ProposedMove] = Field(default_factory=list)


def _proposed_move(move: transfers.Move) -> ProposedMove:
    return ProposedMove(
        ticker_out=move.ticker_out,
        ticker_in=move.ticker_in,
        quantity=_num(move.quantity),
        broker_out=move.broker_out,
        broker_in=move.broker_in,
        date_out=move.date_out,
        date_in=move.date_in,
        booked_at=_num(move.booked_at),
        basis_out=_num(move.basis_out),
        basis_in=_num(move.basis_in),
        phantom_gain=_num(move.phantom_gain),
        currency=move.currency,
        rekey=move.rekey,
        out_ids=list(move.out_ids),
        in_id=move.in_id,
    )


def _move_key(move: transfers.Move) -> tuple[tuple[int, ...], int | None]:
    return tuple(sorted(move.out_ids)), move.in_id


def _propose(account) -> list[transfers.Move]:
    """Moves this ledger's own rows look like, ISIN lookups included.

    `loaders.display_symbol` is the app's cached ISIN -> symbol lookup. One
    resolver for one question, or two surfaces offering one repair would come
    to mean two different things by "the same security".
    `transfers.propose` consults it only for a departure that already matches
    an arrival on every other count, so a book with nothing to repair asks
    nobody anything.
    """
    rows = _real_rows(account)
    return transfers.propose(rows, resolve=loaders.display_symbol) if rows else []


@router.get(
    "/moves/scan",
    response_model=ProposedMoves,
    summary="Holdings that only changed broker",
)
def moves_scan(account: Account) -> ProposedMoves:
    """Departures and arrivals in this book that are one move of shares.

    A GET for the reason the split scan is one, and cheap besides: this reads
    the ledger and, at most, an ISIN lookup for a pair that already matches on
    everything else. It proves nothing by itself — the numbers are here so the
    account can decide, which is why nothing is written until it says so.
    """
    return ProposedMoves(moves=[_proposed_move(m) for m in _propose(account)])


@router.post(
    "/moves/apply", response_model=MovesApplied, summary="Record them as transfers"
)
def moves_apply(account: Writer, body: Annotated[ApplyMoves, ...]) -> MovesApplied:
    """Book the named moves as what they were (`transfers.accept`).

    The departure stops being a disposal, the arrival stops being a purchase,
    and where the two brokers spelled the security differently both labels
    become one. Nothing else about the rows changes: the lots keep their
    original dates and their original cost.

    Named by the ledger ids the scan handed back rather than by ticker and
    date, because two equal parcels of one security leaving the same broker on
    the same day differ in nothing else — accepting "one of them" under a name
    they share would accept both. The ids are also exactly what `accept` acts
    on. Re-proposed first, for the reason a commit re-parses: a move somebody
    already recorded is not a candidate any more, and only a fresh proposal
    knows that.
    """
    fresh = {_move_key(m): m for m in _propose(account)}
    picked: list[transfers.Move] = []
    seen: set[tuple[tuple[int, ...], int | None]] = set()
    for pick in body.moves:
        key = (tuple(sorted(pick.out_ids)), pick.in_id)
        if key in seen:
            continue
        seen.add(key)
        move = fresh.get(key)
        if move is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"rows {sorted(pick.out_ids)} are not a move this ledger "
                    "proposes — scan again"
                ),
            )
        picked.append(move)
    try:
        applied = transfers.accept(picked, account.db)
    except edits.Stale as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the ledger changed while these were being recorded — scan again",
        ) from exc
    except edits.EditError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    obs.event("import.moves_applied", n=applied, via="api")
    return MovesApplied(
        applied=applied, moves=[_proposed_move(m) for m in picked]
    )
