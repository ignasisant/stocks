"""A statement dropped into the assistant, over HTTP.

The Streamlit drawer has taken attachments since the composer grew a paperclip
(`web/chat_core._ingest_uploads`): the file is detected — by a parser that owns
it, or by one cheap model call that maps its columns — validated against the
account's own ledger, previewed as a table inside the bubble, and written only
when the reader presses the button. This is that flow for any other front end,
split into the two calls the drawer makes in one process.

**It reads and validates the way `/import/preview` does, because it is that
code.** The model reads first and the parsers check it (`autodetect.read`), and
the rows are validated against the ledger with the page's own live lookups —
both taken from `import_statement`, so a statement that imports on the Import
page imports here, with the same rows and the same verdicts. What differs is
only what attaching a file to a conversation means: nobody was asked to name
their broker first, so no parser is preferred, and a file nothing could read
is answered in the thread rather than refused. The tiers are presented
differently for the same reason: the page shows duplicates as warnings next to
a wipe checkbox, the chat holds them back and lets the preview opt them in.

**The rows come back on the commit, and the file does not.** Uploaded bytes are
never written to disk — an import is finished inside the session that started
it, and persisting the statement would leave a second copy of somebody's whole
trade history lying around for nothing. That rules out staging the batch server
side, and re-sending the file would mean a second model call whose reading can
differ from the one that was previewed. So the client returns the rows it was
shown, and they are validated again against the ledger as it is now — the page's
commit does the same with the same rows — so a row that became a duplicate or
an oversell in between is dropped and named, not written. It can only ever
write rows to *its own* ledger, which is what uploading a hand-written CSV to
`/import/commit` already does.

Both calls file an assistant turn on the thread, the way the drawer does: the
preview's note (what was found, in what) and the commit's receipt (how many
rows, and that they can be undone). A client that reloads mid-import therefore
finds the conversation saying what happened, even though the preview card
itself — which is not a turn — is gone.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from stocks import accounts, obs
from stocks.accounts import UserPaths
from stocks.api.deps import ChatTurn, Writer
from stocks.api.jsonsafe import num as _num
from stocks.api.routes import import_statement as page
from stocks.chat import a2ui
from stocks.portfolio import (
    demo,
    diagnostics,
    last_import,
    llm_map,
    platforms,
)
from stocks.portfolio.ledger import Transaction, add_many, all_transactions
from stocks.portfolio.statement import ParseResult
from stocks.web import i18n, tx_text

router = APIRouter(prefix="/chat", tags=["chat"])

# The cap the composer is drawn with (`chat_core.MAX_UPLOAD_MB`), on the decoded
# bytes: a caller cannot spend the worker's memory by sending base64 instead.
MAX_UPLOAD_MB = 10
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024

MAX_ROWS = page.MAX_ROWS


# ------------------------------------------------------------------ schemas


class Row(BaseModel):
    """One ledger row, in both directions.

    `why` travels out on the flagged and rejected tiers and is ignored on the
    way back in — it is the reason a row was called out, not part of it.
    """

    model_config = {"extra": "forbid"}

    date: str = Field(max_length=32)
    ticker: str = Field(max_length=64)
    action: str = Field(max_length=32)
    quantity: float = 0.0
    price: float = 0.0
    currency: str = Field(default="USD", max_length=8)
    fee: float = 0.0
    note: str = Field(default="", max_length=500)
    why: str = ""


class Skipped(BaseModel):
    """A line the parser could not read at all, as the preview lists it."""

    row: str = ""
    type: str = ""
    reason: str = ""


class Broker(BaseModel):
    key: str
    label: str


class Message(BaseModel):
    """The assistant turn this call filed, so a client need not re-read."""

    role: str
    content: str
    action: str | None = None


class Attachment(BaseModel):
    model_config = {"extra": "forbid"}

    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(description="The file's bytes, base64-encoded.")
    conversation: str | None = Field(
        default=None,
        description="Thread to file the note on. Omitted means the active one.",
    )
    lang: str | None = None
    mapping: dict | None = Field(
        default=None,
        description=(
            "How to read the columns of an export no parser recognised — the "
            "`mapping` of a previous preview's surface, corrected by the "
            "reader. Applied as given, with no model call."
        ),
    )

    @field_validator("mapping")
    @classmethod
    def _small(cls, value: dict | None) -> dict | None:
        if value is not None and len(json.dumps(value)) > 4000:
            raise ValueError("a mapping is at most 4000 characters of JSON")
        return value


class Preview(BaseModel):
    """What the file turned out to be, and what committing it would write.

    `fresh` is what the button writes. `duplicates` are rows the ledger already
    holds — held back rather than written with a warning, and offered by the
    card's own checkbox for the honest repeat (two identical fills, a broker
    that really did pay the same dividend twice). `flagged` and `rejected` are
    about `fresh`: the first is going in with a caveat, the second is not going
    in at all.
    """

    filename: str
    label: str
    platform: str
    kind: str
    unavailable: bool = Field(
        description=(
            "The model that maps an unrecognised export never answered, so the "
            "file was never judged. Not the same as a file with nothing in it."
        )
    )
    broker: str
    needs_broker: bool
    brokers: list[Broker]
    fresh: list[Row]
    duplicates: list[Row]
    flagged: list[Row]
    rejected: list[Row]
    skipped: list[Skipped]
    note: str
    message: Message
    conversation: str | None = None
    surface: list[dict] | None = Field(
        default=None,
        description=(
            "An A2UI v0.9 surface showing how an unrecognised export's columns "
            "were read, with a way to correct them (`chat/a2ui.py`). Only on "
            "a file the column mapper read."
        ),
    )


class CommitRows(BaseModel):
    model_config = {"extra": "forbid"}

    filename: str = Field(min_length=1, max_length=255)
    platform: str = Field(
        default="",
        description="What the preview detected; stored on the undo record.",
    )
    broker: str = Field(
        default="",
        description=(
            "Origin to stamp on every row. Required: the fees and custody "
            "views read the book by it, and a batch that lands unattributed "
            "is tedious to repair afterwards."
        ),
    )
    rows: list[Row] = Field(min_length=1, max_length=MAX_ROWS)
    conversation: str | None = None
    lang: str | None = None


class Committed(BaseModel):
    imported: int
    tx_ids: list[int]
    total: int = Field(description="Rows in the ledger afterwards.")
    broker: str
    imported_at: str
    message: Message
    rejected: list[Row] = Field(
        default_factory=list,
        description=(
            "Rows sent back that no longer validate against the ledger as it "
            "is now — a duplicate of something committed since, a sell the "
            "book no longer covers — each with why. Not written."
        ),
    )


# ------------------------------------------------------------------ helpers


def _lang(paths: UserPaths, asked: str | None) -> str:
    prefs = accounts.load_prefs(paths.prefs)
    return (asked or prefs.get("language") or "en").strip().lower()


def _decode(content: str) -> bytes:
    try:
        raw = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="content must be base64",
        ) from exc
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty file"
        )
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"attachments are capped at {MAX_UPLOAD_MB} MB",
        )
    return raw


def _file_at(paths: UserPaths, cid: str | None) -> None:
    """Point the thread cursor at `cid`, or 404 if there is no such thread.

    The same rule `POST /chat/runs` is under: turns land in the *active*
    conversation, so naming one means activating it first.
    """
    from stocks.web import auth

    if cid is None:
        return
    if not any(c["id"] == cid for c in auth.list_conversations(paths.chat)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no conversation {cid}"
        )
    auth.set_active_conversation(cid, paths.chat)


def _say(paths: UserPaths, content: str) -> Message:
    """File one assistant turn on the active thread and hand it back."""
    from stocks.web import auth

    turn = {
        "role": "assistant",
        "content": content,
        "action": "import",
        "ts": time.time(),
    }
    history = auth.load_chat(paths.chat)
    history.append(turn)
    auth.save_chat(history, paths.chat)
    return Message(role="assistant", content=content, action="import")


def _row(tx: Transaction, why: str = "") -> Row:
    return Row(
        date=tx.date,
        ticker=tx.ticker,
        action=tx.action,
        quantity=_num(tx.quantity) or 0.0,
        price=_num(tx.price) or 0.0,
        currency=tx.currency,
        fee=_num(tx.fee) or 0.0,
        note=tx.note,
        why=why,
    )


def _issues(checked: list, lang: str) -> list[Row]:
    """Rows with their issues in the reader's language — passed in, because
    under the API `tx_text` has no Streamlit session to read one from."""
    return [
        _row(c.tx, tx_text.issues_text(c.errors or c.warnings, lang))
        for c in checked
    ]


def _transaction(row: Row) -> Transaction:
    """One client row as a ledger row, or a 422 naming what is wrong with it.

    `Transaction` refuses an action it does not know, which is the only field
    here whose values are a closed set — everything else is text and numbers
    the ledger has always taken from a parser.
    """
    try:
        return Transaction(
            date=row.date,
            ticker=row.ticker,
            action=row.action,
            quantity=float(row.quantity),
            price=float(row.price),
            currency=row.currency or "USD",
            fee=float(row.fee),
            note=row.note,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{row.ticker or 'a row'}: {exc}"[:200],
        ) from exc


def _note(lang: str, found: dict, filename: str) -> str:
    """What the assistant says about the file it just read.

    The drawer's own wording, key for key (`chat.import_*`): a count when there
    is something to import, the two "nothing to do" explanations when there is
    not, and the one about the model never answering — which is deliberately
    not advice to go and fix the export, because nothing was found wrong with
    it.
    """
    n, dupes = len(found["fresh"]), len(found["duplicates"])
    if n or dupes:
        if n and dupes:
            key = "chat.import_found_deduped"
        elif n:
            key = "chat.import_found"
        else:
            key = "chat.import_all_duplicates"
        return i18n.translate(
            key, lang, filename=filename, n=n, dupes=dupes, label=found["label"]
        )
    if found["unavailable"]:
        return i18n.translate("chat.import_unavailable", lang, filename=filename)
    if found["kind"] == llm_map.KIND_POSITIONS:
        return (
            i18n.translate("chat.import_positions", lang, filename=filename)
            + "\n\n"
            + i18n.translate("chat.import_positions_help", lang)
        )
    return (
        i18n.translate("chat.import_none", lang, filename=filename)
        + "\n\n"
        + i18n.translate("chat.import_none_help", lang)
    )


# ------------------------------------------------------------------- routes


@router.post(
    "/attachments",
    response_model=Preview,
    summary="Read a statement attached to the conversation",
)
def attach(
    body: Attachment,
    paths: ChatTurn,
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> Preview:
    """Read, validate and preview one statement. Writes no ledger rows.

    A write all the same — it files the assistant's note on the thread, and it
    spends the account's model calls on reading the file — so it is `Writer`
    like every other route that costs the account something.

    The read and the validation are the Import page's (`import_statement._read`
    and `_validated`), live symbol lookups included: they are bounded by the
    batch budget, and without them the same statement warned here and read
    clean on the page.
    """
    raw = _decode(body.content)
    _file_at(paths, body.conversation)
    lang = _lang(paths, body.lang)

    found = page._read(
        paths,
        body.filename,
        raw,
        held=page._held(x_chat_provider, x_chat_key),
        mapping=body.mapping,
    )
    checked, _disowned = page._validated(paths, found.result)
    # The same anonymised record the Import page files, tagged with the surface
    # it came through, so the two are told apart.
    diagnostics.report(
        found.platform, body.filename, raw, found.result, checked, surface="chat"
    )

    detected = platforms.detected_broker(checked.importable)
    summary = {
        "fresh": checked.fresh,
        "duplicates": checked.duplicates,
        "label": found.label or i18n.translate("chat.import_source_llm", lang),
        "unavailable": found.unavailable,
        "kind": found.kind,
    }
    note = _note(lang, summary, body.filename)

    from stocks.web import auth

    return Preview(
        filename=body.filename,
        label=summary["label"],
        platform=found.platform,
        kind=found.kind,
        unavailable=found.unavailable,
        broker=detected,
        # Only a batch that is actually going somewhere needs an origin; a file
        # with nothing in it must not put a picker in front of anyone.
        needs_broker=bool(checked.fresh or checked.duplicates) and not detected,
        brokers=[
            Broker(
                key=key,
                label=(
                    i18n.translate("chat.import_broker_other", lang)
                    if key == platforms.OTHER
                    else platforms.broker_label(key)
                ),
            )
            for key in platforms.broker_options()
        ],
        fresh=[_row(tx) for tx in checked.fresh],
        duplicates=_issues(checked.duplicates, lang),
        # Warnings worth reading are the ones about rows being committed; the
        # duplicates carry their own tier and their own explanation.
        flagged=_issues([c for c in checked.flagged if not c.duplicate], lang),
        rejected=_issues(checked.rejected, lang),
        # Parsers add their own fields to a skip (`statement.skip_entry`), so
        # the three the preview prints are picked out rather than splatted.
        skipped=[
            Skipped(
                row=str(s.get("row", "")),
                type=str(s.get("type", "")),
                reason=tx_text.skip_text(str(s.get("reason", "")), lang),
            )
            for s in found.result.skipped
        ],
        note=note,
        message=_say(paths, note),
        conversation=auth.active_conversation(paths.chat)["id"],
        surface=(
            a2ui.column_mapping(found.mapping, list(found.columns),
                                lambda key: i18n.translate(key, lang))
            if found.mapping and found.columns
            else None
        ),
    )


@router.post(
    "/attachments/commit",
    response_model=Committed,
    summary="Write the previewed rows",
)
def commit(body: CommitRows, paths: Writer) -> Committed:
    """Append the rows the preview showed, and record the batch as undoable.

    The rows are taken from the body — see the module docstring for why they
    are not re-derived from the file — rebuilt through `Transaction`, so an
    unknown action is a 422 and not a row in the ledger, and validated again
    against the ledger as it is now. What no longer validates is left out and
    handed back as `rejected`; a duplicate the preview opted in is still
    written, because it was sent on purpose.

    Nothing is deleted except the demo book, which the first real import always
    takes with it: an invented cost basis must never mix into a real one.
    """
    origin = body.broker.strip()
    if not origin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="rows need a broker to be filed under — send one as `broker`",
        )
    sent = ParseResult(transactions=[_transaction(r) for r in body.rows])
    checked, _disowned = page._validated(paths, sent)
    if not checked.importable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="none of these rows validates against the ledger any more",
        )
    txs = platforms.stamp_broker(checked.importable, origin)

    _file_at(paths, body.conversation)
    lang = _lang(paths, body.lang)

    demo.clear(paths.db)
    ids = add_many(txs, paths.db)
    if ids:
        page._retag(paths.db, checked.relabeled)
    stamped = datetime.now(UTC).isoformat(timespec="seconds")
    last_import.save(
        last_import.ImportRecord(
            filename=body.filename,
            imported_at=stamped,
            tx_ids=ids,
            wiped=False,
            platform=body.platform,
        ),
        paths.last_import,
    )
    total = len(all_transactions(paths.db))
    obs.event(
        "import.committed",
        platform=body.platform or "chat",
        broker=origin,
        n=len(ids),
        wiped=False,
        via="chat-api",
    )
    note = i18n.translate("chat.import_done", lang, n=len(ids), total=total)
    if checked.rejected:
        # Said in the turn itself: the card that showed them clean is gone.
        note += " " + i18n.translate(
            "chat.import_left_out",
            lang,
            n=len(checked.rejected),
            tickers=", ".join(sorted({c.tx.ticker for c in checked.rejected})),
        )
    note += " " + i18n.translate("chat.import_undo_hint", lang)
    return Committed(
        imported=len(ids),
        tx_ids=ids,
        total=total,
        broker=origin,
        imported_at=stamped,
        message=_say(paths, note),
        rejected=_issues(checked.rejected, lang),
    )
