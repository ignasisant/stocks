"""The book checkup: held sales, statements worth re-uploading, doctor fixes."""

from __future__ import annotations

from typing import Annotated, Literal, cast, get_args

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api import loaders
from stocks.api.deps import Account, Writer
from stocks.api.jsonsafe import num as _num
from stocks.api.routes.import_statement.validation import _real_rows
from stocks.api.schemas import (
    BookFinding,
)
from stocks.portfolio import (
    doctor,
    edits,
    heal,
    held,
    platforms,
)
from stocks.portfolio.ledger import add_many

router = APIRouter(prefix="/import", tags=["import"])


# What Import's repairs card shows besides moves and splits: the sales an
# import held back that the book can carry now, the statements worth uploading
# again (a split written after them, `portfolio.held`), the doctor's findings
# that come with their fix, and the repairs the app made by itself
# (`portfolio.heal`), each with the way back.

# Transfers have their own list (`/import/moves`) and an oversold position has
# no fix but a missing statement, which `reupload` names when it can.
_FIXABLE = ("two_labels", "duplicate", "fee_in_coins")


class HeldSale(BaseModel):
    id: int = Field(description="Names it for `POST /import/held/apply`.")
    date: str
    ticker: str
    action: str
    quantity: float
    price: float
    currency: str
    broker: str = Field(description="The statement it came from.")


class ReuploadHint(BaseModel):
    key: str = Field(description="For `POST /import/reupload/dismiss`.")
    broker: str
    ticker: str
    split_date: str = Field(description="The split written after that import.")


HealKind = Literal["fee_in_coins", "net_dividends"]


class Healed(BaseModel):
    kind: HealKind = Field(
        description="Which repair it was."
    )
    change_id: int = Field(description="`DELETE /portfolio/changes/{id}` undoes it.")
    rows: int = Field(description="Ledger rows it changed.")
    at: str
    summary: str


class Checkup(BaseModel):
    held: list[HeldSale] = Field(
        default_factory=list,
        description="Sales an import held back that the book can carry now.",
    )
    reupload: list[ReuploadHint] = Field(
        default_factory=list,
        description=(
            "Statements imported before a split on a name they still show open: "
            "uploading one again recovers a sale lost then, and adds nothing else."
        ),
    )
    findings: list[BookFinding] = Field(
        default_factory=list, description="What looks wrong and has a fix."
    )
    healed: list[Healed] = Field(
        default_factory=list, description="Repairs the app wrote by itself."
    )


class HeldPick(BaseModel):
    model_config = {"extra": "forbid"}

    ids: list[int] = Field(min_length=1, max_length=200)


class HeldApplied(BaseModel):
    applied: int
    tx_ids: list[int] = Field(default_factory=list)


class Dismiss(BaseModel):
    model_config = {"extra": "forbid"}

    key: str = Field(min_length=1, max_length=200)


class FixPick(BaseModel):
    model_config = {"extra": "forbid"}

    key: str = Field(min_length=1, max_length=4000)


class FixApplied(BaseModel):
    change_id: int = Field(description="`DELETE /portfolio/changes/{id}` undoes it.")
    rows: int


def _finding(f: doctor.Finding) -> BookFinding:
    return BookFinding(
        key=f.key,
        kind=f.kind,
        ticker=f.ticker,
        ids=list(f.ids),
        fix=f.fix,
        detail=f.detail,
        weight=_num(f.weight) or 0.0,
        cause=f.cause,
    )


@router.get("/checkup", response_model=Checkup, summary="What the book can fix now")
def checkup(account: Account) -> Checkup:
    """Everything the repairs card offers besides moves and splits. Reads the
    ledger only; the one write is dropping held sales the book already has."""
    rows = _real_rows(account)
    if not rows:
        return Checkup()
    return Checkup(
        held=[
            HeldSale(
                id=h.id, date=h.tx.date, ticker=h.tx.ticker, action=h.tx.action,
                quantity=h.tx.quantity, price=h.tx.price, currency=h.tx.currency,
                broker=platforms.broker_of(h.tx),
            )
            for h in held.ready(account.db)
        ],
        reupload=[
            ReuploadHint(
                key=r.key, broker=r.broker, ticker=r.ticker, split_date=r.split_date
            )
            for r in held.reuploads(rows, account.db)
        ],
        findings=[
            _finding(f)
            for f in doctor.scan(rows, resolve=loaders.display_symbol)
            if f.kind in _FIXABLE and f.fix
        ],
        healed=[
            Healed(
                kind=cast(HealKind, kind), change_id=c.id, rows=len(c.changes),
                at=c.at, summary=c.summary,
            )
            for kind, c in heal.recent(account.db)
            if kind in get_args(HealKind)
        ],
    )


@router.post("/held/apply", response_model=HeldApplied, summary="Write held sales")
def held_apply(account: Writer, body: Annotated[HeldPick, ...]) -> HeldApplied:
    """Write the named held sales, if the book can carry all of them now; a
    409 and nothing written otherwise (one is gone, or would oversell)."""
    picked = held.take(sorted(set(body.ids)), account.db)
    if picked is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the book cannot carry these sales now — check again",
        )
    ids = add_many(picked, account.db)
    held.drop(sorted(set(body.ids)), account.db)
    obs.event("import.held_applied", n=len(ids), via="api")
    return HeldApplied(applied=len(ids), tx_ids=ids)


@router.delete("/held/{held_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Forget a held sale")
def held_forget(account: Writer, held_id: int) -> Response:
    held.drop([held_id], account.db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reupload/dismiss", status_code=status.HTTP_204_NO_CONTENT,
             summary="Stop suggesting a re-upload")
def reupload_dismiss(account: Writer, body: Annotated[Dismiss, ...]) -> Response:
    held.dismiss(body.key.strip(), account.db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/fix", response_model=FixApplied, summary="Apply a finding's fix")
def fix(account: Writer, body: Annotated[FixPick, ...]) -> FixApplied:
    """Apply the fix of the finding `key` names, as a scan run here and now
    finds it — never the client's copy of the ops. Journalled, so
    `DELETE /portfolio/changes/{id}` takes it back. 409 once it is gone."""
    rows = _real_rows(account)
    found = doctor.by_key(rows, body.key.strip(), resolve=loaders.display_symbol)
    if found is None or found.kind not in _FIXABLE or not found.fix:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that finding is not on this book any more — check again",
        )
    try:
        planned = edits.plan(found.fix, account.db)
        done = edits.commit(
            found.fix, planned.token, source="api",
            summary=f"{found.kind} {found.ticker}", path=account.db,
        )
    except edits.EditError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    obs.event("import.fix_applied", kind=found.kind, rows=len(found.ids), via="api")
    return FixApplied(change_id=done.id, rows=len(done.changes))
