"""The decision journal, for the reader to look back on.

What the app proposed and showed — card lines, Review verdicts, chat offers —
with the figures each was made on and what became of it (`chat/journal.py`).
The Perfil "Diario" tab lists it whole with filters; the ticker page's chip
asks for one ticker's entries. The proposals are read-only: they are written
by the surfaces that showed them, never edited by hand — a record the reader
could rewrite would stop being a record of what the app said. The one write
is retiring an exit rule, which is the reader's own (written through chat).

`Account`, not `Writer`, for the reads: a guest reads the shared demo book's
journal, which is always empty because nothing is recorded for the guest
directory.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response, status
from pydantic import BaseModel

from stocks import loaders
from stocks.api.deps import Account, Base, Writer, reporting_currency
from stocks.chat import journal

router = APIRouter(prefix="/journal", tags=["journal"])

Kind = Literal["proposal", "criterion", "event"]
Source = Literal["daily", "review", "chat"]
State = Literal["open", "followed", "declined", "lapsed", "hit", "retired"]


class JournalEntry(BaseModel):
    """One proposal as it was shown, and its fate.

    `subject` groups showings of the same proposal; `links` are the ids of
    the entries it replaced or was replaced by. `snapshot` holds the figures
    at the time, keyed as the surface that showed it names them: scalars,
    and on an exit rule the lists its checks keep (a thesis rule's
    `pillars`, the passages already read). `day`/`last` are the first and
    latest day on screen."""

    id: str
    type: Kind
    source: Source
    action: str
    subject: str
    ticker: str
    line: str
    reasons: list[str]
    snapshot: dict[str, float | int | bool | str | list[str] | None]
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
    filters given; `ticker` takes every line of its company
    (`journal.same_name`: SAP and SAP.DE, TM and 7203.T)."""
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


Family = Literal["thesis", "price", "fundamental", "event", "buy"]
Status = Literal["hit", "none", "gap", "review", "ok"]
AssetKind = Literal["stock", "fund", "crypto"]


class CoverageRule(BaseModel):
    """One live rule under a holding (`journal.rule_row`), with the line it
    is drawn on, its family, and why it wants a second look: `flag` "drift"
    (a floor the price ran far from), "cap" (a weight cap the position
    cannot reach soon) or "old" (a thesis written half a year ago)."""

    id: str
    ticker: str
    rule: str
    family: Family
    side: Literal["exit", "buy"]
    state: Literal["open", "hit"]
    since: str
    level: float | None = None
    quarters: int | None = None
    pillars: list[str] = []
    checked: str | None = None
    last_value: float | None = None
    watch: list[str] = []
    flag: Literal["drift", "cap", "old"] | None = None
    quote: str | None = None
    source: str | None = None
    source_day: str | None = None
    pillar: str | None = None
    verdict: str | None = None


class CoverageRow(BaseModel):
    """One holding: its weight (a fraction, null unpriced), the families its
    kind needs and has no exit rule for, and how it reads overall."""

    ticker: str
    kind: AssetKind
    weight: float | None
    status: Status
    missing: list[Family]
    # The families that apply to its kind at all: a fund has no thesis.
    applies: list[Family]
    rules: list[CoverageRule]
    retired: int = 0


class CoverageSummary(BaseModel):
    holdings: int
    # The share of the book, by value, whose every needed family is ruled.
    covered: float
    hit: int
    none: int
    gap: int
    review: int
    ok: int
    no_buy: int


class Coverage(BaseModel):
    rows: list[CoverageRow]
    summary: CoverageSummary


def _kind(ticker: str) -> str:
    """Stock, fund or crypto, off what is already on disk — never a lookup:
    one per holding is how a page gets throttled."""
    from stocks.data import asset_kind
    from stocks.data.crypto import is_crypto

    if is_crypto(ticker):
        return "crypto"
    if (
        ticker.upper().startswith("0P")
        or asset_kind.known(ticker) in asset_kind.FUND_KINDS
    ):
        return "fund"
    return "stock"


@router.get("/coverage", response_model=Coverage,
            summary="Rules by holding, heaviest first")
def coverage(account: Account, base: Base = None) -> Coverage:
    """What the book holds today, each name with its live exit and buy rules,
    what its kind still lacks (`journal.NEEDS`) and the rules due a second
    look. The weights and prices are the positions table's, already cached
    for Home: no quote of its own."""
    from stocks.analysis.portfolio import value_weights

    ccy = reporting_currency(account, base)
    db = str(account.db)
    table = loaders.positions_table(db, loaders.db_mtime(db), ccy)
    holdings: list[dict] = []
    if not table.empty:
        weights = value_weights(table)
        rates = loaders.spot_rates(
            tuple(sorted({str(c).upper() for c in table["ccy"] if c})), ccy)
        holdings = [{"ticker": str(t), "kind": _kind(str(t)),
                     "weight": weights.get(t),
                     "price": loaders.native_price(row, rates)}
                    for t, row in table.iterrows()]
    got = journal.coverage(journal.load(account.journal), holdings, date.today())
    return Coverage(**got)


EntryId = Annotated[str, Path(min_length=1, max_length=32,
                              pattern=r"^[A-Za-z0-9_-]+$")]


@router.delete("/criteria/{entry_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Retire one exit rule")
def retire(entry_id: EntryId, paths: Writer) -> None:
    """Take down one of the reader's exit rules. It stays in the journal as
    retired — the rule was theirs and they may drop it, but the record that
    it existed is kept. 404 on an id that is not a live rule."""
    if journal.retire(paths.journal, entry_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such exit rule")


@router.post("/criteria/{entry_id}/restore", status_code=status.HTTP_204_NO_CONTENT,
             summary="Put back a retired rule")
def restore(entry_id: EntryId, paths: Writer) -> None:
    """Undo a retire: the rule stands again in the state it was taken down
    in. 404 on an id that is not a retired rule; 409 when another live rule
    on the same ticker and measure has taken its place since."""
    rule = next((e for e in journal.load(paths.journal)
                 if e.id == entry_id and e.type == "criterion"), None)
    if rule is None or rule.state != "retired":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such retired rule")
    if journal.restore(paths.journal, entry_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a newer rule stands")
