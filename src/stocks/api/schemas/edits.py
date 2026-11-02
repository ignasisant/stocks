"""Hand edits to the ledger, their plan and undo, and the book's checkup."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from stocks.api.schemas.book import Transaction

# ------------------------------------------------------------ hand edits
# `stocks.portfolio.edits`: an edit is planned (nothing written, its impact
# shown), then committed under the plan's token, then undoable by id.


class RowChange(BaseModel):
    """One row's fate. `before` is null for a new row, `after` for a deleted one."""

    id: int = Field(
        description="The row's id; negative in a plan for a row not written yet."
    )
    kind: Literal["added", "updated", "deleted"]
    before: Transaction | None = None
    after: Transaction | None = None


class EditEffect(BaseModel):
    """What an edit does to one security, in the currency it trades in."""

    ticker: str
    currency: str
    held_before: float
    held_after: float
    cost_before: float
    cost_after: float
    realized_before: dict[str, float] = Field(
        description="Realized gain per calendar year before the edit, FIFO."
    )
    realized_after: dict[str, float]


class EditPlan(BaseModel):
    ops: list[dict] = Field(description="The operations, as they will be applied.")
    changes: list[RowChange]
    effects: list[EditEffect] = Field(
        description="Only the securities whose holding or realized gain moves."
    )
    positions_before: int
    positions_after: int
    problems: list[str] = Field(
        description=(
            "What the edit would break — a sale left without the shares it "
            "sells. A plan with problems cannot be committed."
        )
    )
    token: str = Field(
        description=(
            "Names this edit on this exact book. Committing needs it back, and "
            "is refused once anything in the book has changed."
        )
    )
    ok: bool


class Change(BaseModel):
    """One committed edit in the book's history."""

    id: int
    at: str = Field(description="ISO-8601 UTC.")
    source: str = Field(
        description="chat, mcp, api or import (older rows may read 'telegram').")
    summary: str
    changes: list[RowChange]
    undone_at: str | None = None


class Changes(BaseModel):
    changes: list[Change]


class BookFinding(BaseModel):
    """Something that looks wrong in the book (`stocks.portfolio.doctor`)."""

    key: str = Field(description="Names this finding on this book; the same on a rescan.")
    kind: Literal["transfer", "two_labels", "oversold", "duplicate", "fee_in_coins"] = (
        Field(
            description=(
                "`transfer`: a sale at one broker and an arrival at another that "
                "are one move of shares. `two_labels`: one security kept under two "
                "labels. `oversold`: a sale of shares the book never saw arrive. "
                "`duplicate`: one trade imported from two brokers. `fee_in_coins`: "
                "Revolut crypto buys booked with the coins their fee took."
            )
        )
    )
    ticker: str = Field(description="The label a fix keeps.")
    ids: list[int] = Field(description="The ledger rows it is about.")
    fix: list[dict] = Field(
        description=(
            "The edit that would put it right, as `POST /portfolio/changes/plan` "
            "takes it. Empty when only the account can say what happened."
        )
    )
    detail: dict[str, Any] = Field(description="The facts behind it, for the copy.")
    weight: float = Field(
        description="What it is worth fixing, in the security's own currency."
    )
    cause: Literal["fee", "split", "transfer", "duplicate", "unexplained"] | None = Field(
        default=None,
        description=(
            "Why the book disagrees with itself, traced from the rows: a fee paid "
            "in units, an unrecorded split, a broker move, a trade imported twice, "
            "or `unexplained`. Null for a finding that is not a break."
        ),
    )


class BookHealth(BaseModel):
    findings: list[BookFinding] = Field(description="Costliest first.")
