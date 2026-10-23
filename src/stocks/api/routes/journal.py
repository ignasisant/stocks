"""The decision journal, for the reader to look back on.

What the app proposed and showed — card lines, Review verdicts, chat offers —
with the figures each was made on and what became of it (`chat/journal.py`).
The Perfil "Diario" tab lists it whole with filters; the ticker page's chip
asks for one ticker's entries. Read-only: the journal is written by the
surfaces that showed the proposals, never edited by hand — a record the
reader could rewrite would stop being a record of what the app said.

`Account`, not `Writer`: a guest reads the shared demo book's journal, which
is always empty because nothing is recorded for the guest directory.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from stocks.api.deps import Account
from stocks.chat import journal

router = APIRouter(prefix="/journal", tags=["journal"])

Kind = Literal["proposal", "criterion", "event"]
Source = Literal["daily", "review", "chat"]
State = Literal["open", "followed", "declined", "lapsed"]


class JournalEntry(BaseModel):
    """One proposal as it was shown, and its fate.

    `subject` groups showings of the same proposal; `links` are the ids of
    the entries it replaced or was replaced by. `snapshot` holds the figures
    at the time (scalars only), keyed as the surface that showed it names
    them. `day`/`last` are the first and latest day on screen."""

    id: str
    type: Kind
    source: Source
    action: str
    subject: str
    ticker: str
    line: str
    reasons: list[str]
    snapshot: dict[str, float | int | bool | str | None]
    evidence: str
    state: State
    day: str
    last: str
    times: int
    links: list[str]
    updated: str
    # "chat" when the reader answered a card, "ledger:<date>" when a trade
    # in the book settled it, "" when the app set the state on its own.
    settled: str = ""
    # The price read back after the fact: "then" (close on the first day
    # shown), "d30"/"d90" (% move since). Empty until a mark is due.
    outcome: dict[str, float] = {}


class Record(BaseModel):
    """What became of the proposals, counted (`journal.track_record`)."""

    proposed: int
    open: int
    followed: int
    declined: int
    lapsed: int
    # Moves whose price has been read back, and those that went the way
    # the move bet on at their latest mark.
    marked: int = 0
    its_way: int = 0
    by_source: dict[str, dict[str, int]]


class Journal(BaseModel):
    entries: list[JournalEntry]
    # Matches before `limit`, and per state over the same filters bar state:
    # the tab's state chips count what each would show.
    total: int
    states: dict[str, int]
    # Over the whole journal, whatever the filters: the tab's one-line record.
    record: Record


@router.get("", response_model=Journal, summary="The decision journal")
def entries(
    paths: Account,
    ticker: str = Query("", max_length=32),
    type: Kind | None = None,
    state: State | None = None,
    source: Source | None = None,
    since: str = Query("", max_length=10, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    limit: int = Query(500, ge=1, le=journal.MAX_ENTRIES),
) -> Journal:
    """Entries newest first (by the latest day shown), narrowed by any of the
    filters given; `ticker` ignores the exchange suffix."""
    saved = journal.load(paths.journal)
    scope = journal.query(saved, ticker=ticker, type=type or "",
                          source=source or "", since=since)
    states = {s: 0 for s in journal.STATES}
    for entry in scope:
        states[entry.state] = states.get(entry.state, 0) + 1
    hits = [e for e in scope if not state or e.state == state]
    return Journal(
        entries=[JournalEntry(**e.as_dict()) for e in hits[:limit]],
        total=len(hits),
        states=states,
        record=Record(**journal.track_record(saved)),
    )


@router.get(
    ".md",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {}},
                     "description": "The whole journal as one Markdown file."}},
    summary="The decision journal as a file",
)
def export(paths: Account) -> Response:
    """The journal whole, as a notes app reads it: Obsidian block ids and
    wikilinks between the entries that replaced each other, tags per ticker,
    state and source (`journal.to_markdown`). Always on offer — an empty
    journal exports as its heading — since the tab shows the link from the
    first visit."""
    today = date.today()
    body = journal.to_markdown(journal.load(paths.journal), today)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="decisions-{today:%Y-%m-%d}.md"'},
    )
