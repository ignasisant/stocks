"""Changes to the ledger: wipe, planned edits and their undo, the book's
health check and the demo rows.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api import loaders
from stocks.api.deps import Account, Writer
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import (
    BookFinding,
    BookHealth,
    Change,
    Changes,
    EditEffect,
    EditPlan,
    LedgerCleared,
    RowChange,
    Transaction,
)
from stocks.api.security import Authed
from stocks.portfolio import demo, doctor, edits, last_import
from stocks.portfolio.ledger import all_transactions, clear

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ------------------------------------------------------------- starting over
# The page offers this as a checkbox beside the upload ("wipe first"), which is
# the right shape there: a person is looking at their own book and at the file
# that will replace it. It is the wrong shape for a client, where a stray
# boolean on an unrelated request would destroy a ledger nobody can restore —
# so here it is a route of its own, and it has to be told what it is deleting.


class Wipe(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: str = Field(
        description=(
            "The signed-in address, typed back. This deletes every transaction "
            "and there is no undo, so the request has to name the book it is "
            "emptying — a client cannot do this by accident."
        )
    )


@router.delete(
    "/transactions",
    response_model=LedgerCleared,
    summary="Delete every transaction",
)
def wipe(caller: Authed, account: Writer, body: Wipe) -> LedgerCleared:
    """Empty the book. There is no undo, and no backup is taken.

    `DELETE /import/last` is what almost every caller wants instead: it removes
    one batch, by the ids that batch inserted. This removes everything, including
    rows typed in by hand years ago and every import before the last one.
    """
    if body.confirm.strip().lower() != (caller.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="confirm must be the signed-in address, exactly",
        )
    removed = len(all_transactions(account.db))
    clear(account.db)
    # The last-import record points at ids that no longer exist, and offering
    # an undo of a batch inside a book that is gone would be a lie.
    last_import.forget(account.last_import)
    obs.event("ledger.wiped", rows=removed, via="api")
    return LedgerCleared(removed=removed)


# ---------------------------------------------------------------- hand edits
# One path for every edit a person asks for — here, in the chat
# or through the Claude connector (`stocks.portfolio.edits`). Planning writes
# nothing and returns what the edit does to holdings and realized gains;
# committing needs the plan's token back, so what is applied is what was
# shown, on the book it was shown on. Every commit can be undone by its id.


class EditOps(BaseModel):
    model_config = {"extra": "forbid"}

    ops: list[dict] = Field(
        min_length=1,
        max_length=edits.MAX_OPS,
        description=(
            "Applied in order. `add{row}`, `update{id, fields}`, `delete{ids}`, "
            "`set_action{ids, action}`, `relabel{ids, to}`, "
            "`split_row{id, quantity}`. A row an earlier op adds is addressed "
            "as -1, -2, … by later ones."
        ),
    )


class EditCommit(EditOps):
    token: str = Field(
        min_length=1, max_length=64, description="The token the plan returned."
    )
    summary: str = Field(
        default="", max_length=300, description="What the edit is, in words."
    )


def _row_change(c: edits.RowChange) -> RowChange:
    return RowChange(
        id=c.id,
        kind=c.kind,
        before=Transaction(id=c.id, **c.before) if c.before else None,
        after=Transaction(id=c.id, **c.after) if c.after else None,
    )


def _change(c: edits.Changeset) -> Change:
    return Change(
        id=c.id,
        at=c.at,
        source=c.source,
        summary=c.summary,
        changes=[_row_change(r) for r in c.changes],
        undone_at=c.undone_at,
    )


@router.post("/changes/plan", response_model=EditPlan, summary="Preview an edit")
def plan_change(account: Writer, body: EditOps) -> EditPlan:
    """What an edit would do. Nothing is written.

    A plan with `problems` is still returned — the caller shows why it cannot
    go ahead — but it cannot be committed.
    """
    try:
        planned = edits.plan(body.ops, account.db)
    except edits.EditError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return EditPlan(
        ops=planned.ops,
        changes=[_row_change(c) for c in planned.changes],
        effects=[EditEffect(**vars(e)) for e in planned.effects],
        positions_before=planned.positions_before,
        positions_after=planned.positions_after,
        problems=planned.problems,
        token=planned.token,
        ok=planned.ok,
    )


@router.post(
    "/changes",
    response_model=Change,
    status_code=status.HTTP_201_CREATED,
    summary="Apply a planned edit",
)
def commit_change(account: Writer, body: EditCommit) -> Change:
    """Apply an edit `POST /changes/plan` showed, journalled and undoable.

    409 when the book changed since the plan (or the token is another plan's):
    plan again and show that. 422 when the edit is malformed or would leave a
    sale without the shares it sells.
    """
    try:
        done = edits.commit(
            body.ops, body.token, source="api", summary=body.summary, path=account.db
        )
    except edits.Stale as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except edits.EditError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    obs.event("ledger.edited", rows=len(done.changes), via="api")
    return _change(done)


@router.get("/changes", response_model=Changes, summary="Edit history")
def list_changes(
    account: Account, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> Changes:
    """The book's hand edits, newest first, each with the rows it touched."""
    return Changes(changes=[_change(c) for c in edits.history(account.db, limit)])


@router.delete("/changes/{change_id}", response_model=Change, summary="Undo an edit")
def undo_change(account: Writer, change_id: int) -> Change:
    """Put back what one edit replaced.

    409 when any of its rows was changed again since: half an undo is a book
    nobody wrote, so it is all or nothing.
    """
    try:
        done = edits.undo(change_id, path=account.db)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except edits.Conflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    obs.event("ledger.undone", rows=len(done.changes), via="api")
    return _change(done)


@router.get("/health", response_model=BookHealth, summary="What looks wrong")
def health(account: Account) -> BookHealth:
    """Mistakes two statements make together, each with the edit that fixes it.

    Shares that only changed broker but read as a sale, one company under two
    labels, a trade imported twice, a sale of shares that never arrived. Reads
    the ledger and the label lookup the rest of the app already caches; the
    demo book is left out, since nobody owns its mistakes.
    """
    rows = demo.without(all_transactions(account.db))
    return BookHealth(
        findings=[
            BookFinding(
                key=f.key,
                kind=f.kind,
                ticker=f.ticker,
                ids=list(f.ids),
                fix=f.fix,
                detail=f.detail,
                weight=_num(f.weight) or 0.0,
                cause=f.cause,
            )
            for f in doctor.scan(rows, resolve=loaders.display_symbol)
        ]
    )


# ---------------------------------------------------------------- the demo book
# Everything on this page derives from the ledger, so an account that has not
# imported yet finds positions, P/L, allocation, risk, dividends, fees and the
# tax report blank at once. The example statement (`GET /v1/import/sample`) is
# the honest answer for a reader ready to import; this is the other half of it,
# for one who wants to look first. Fabricated rows in an app that also files
# tax reports are only safe while both promises hold: every row is marked
# `demo` (the note's first word, which is what `fees.broker_of` reads), and the
# first real import deletes them — `POST /v1/import/commit` still does, so a
# book seeded from here cannot leak an invented cost basis into a real one.


class DemoBook(BaseModel):
    active: bool = Field(description="Whether the book holds demo rows now.")
    rows: int = Field(description="Demo rows this call wrote, or removed.")


@router.post("/demo", response_model=DemoBook, summary="Fill an empty book")
def seed_demo(account: Writer) -> DemoBook:
    """Write the demo book, if this ledger is empty.

    409 when it is not, rather than a quiet `rows: 0`: `demo.seed` refuses a
    ledger holding anything at all — a double click and a stale retry both
    arrive here, and a second copy of the book would be a doubled cost basis —
    and a client told "ok, 0" would show a book that was never written.
    """
    ids = demo.seed(account.db)
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this book already holds the demo rows"
                if demo.active(account.db)
                else "this book holds transactions; the demo one is only for an "
                "empty ledger"
            ),
        )
    obs.event("demo.seeded", rows=len(ids), via="api")
    return DemoBook(active=True, rows=len(ids))


@router.delete("/demo", response_model=DemoBook, summary="Remove the demo rows")
def clear_demo(account: Writer) -> DemoBook:
    """Delete every demo row, and only those.

    Matched on the `demo` origin rather than on the ids that were seeded, so a
    book seeded twice in two sessions still comes out clean. Real rows are
    never touched: a note beginning with any other word is somebody's own.
    """
    removed = demo.clear(account.db)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this book holds no demo rows",
        )
    obs.event("demo.cleared", rows=removed, via="api")
    return DemoBook(active=False, rows=removed)
