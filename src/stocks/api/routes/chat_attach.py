"""A statement dropped into the assistant, over HTTP.

The Streamlit drawer has taken attachments since the composer grew a paperclip
(`web/chat_core._ingest_uploads`): the file is detected — by a parser that owns
it, or by one cheap model call that maps its columns — validated against the
account's own ledger, previewed as a table inside the bubble, and written only
when the reader presses the button. This is that flow for any other front end,
split into the two calls the drawer makes in one process.

**Why it is not `/import/preview`.** That route takes the platform key the
Import page's selectbox chose, and refuses what no parser owns. The whole point
of attaching a file to a conversation is that nobody was asked to name their
broker first — so detection is the route's job here, and an export this app has
no parser for is mapped rather than rejected. The tiers differ for the same
reason: the page shows duplicates as warnings next to a wipe checkbox, the chat
holds them back and lets the preview opt them in.

**The rows come back on the commit, and the file does not.** Uploaded bytes are
never written to disk — an import is finished inside the session that started
it, and persisting the statement would leave a second copy of somebody's whole
trade history lying around for nothing. That rules out staging the batch server
side, and re-sending the file would mean a second model call whose mapping can
differ from the one that was previewed. So the client returns the rows it was
shown. It can only ever write rows to *its own* ledger, which is what uploading
a hand-written CSV to `/import/commit` already does, and it is checked on the
way in like any other body.

Both calls file an assistant turn on the thread, the way the drawer does: the
preview's note (what was found, in what) and the commit's receipt (how many
rows, and that they can be undone). A client that reloads mid-import therefore
finds the conversation saying what happened, even though the preview card
itself — which is not a turn — is gone.
"""

from __future__ import annotations

import base64
import binascii
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from stocks import accounts, obs
from stocks.accounts import UserPaths
from stocks.api.deps import ChatTurn, Writer
from stocks.api.jsonsafe import num as _num
from stocks.chat import engine
from stocks.data import fetch
from stocks.data.symbols import is_isin, symbol_for_isin
from stocks.portfolio import (
    autodetect,
    demo,
    diagnostics,
    last_import,
    llm_map,
    platforms,
)
from stocks.portfolio.ledger import Transaction, add_many, all_transactions
from stocks.portfolio.validate import known_tickers, validate
from stocks.web import i18n

router = APIRouter(prefix="/chat", tags=["chat"])

# The cap the composer is drawn with (`chat_core.MAX_UPLOAD_MB`), on the decoded
# bytes: a caller cannot spend the worker's memory by sending base64 instead.
MAX_UPLOAD_MB = 10
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Nothing sane reaches this. It is here so that a client which lost its preview
# and started replaying garbage cannot ask for a million-row insert.
MAX_ROWS = 20_000


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

    The same rule `POST /chat/messages` is under: turns land in the *active*
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


def _provider(paths: UserPaths):
    """The provider that would answer this account, for the column mapper.

    None when there is nothing to ask — a BYOK account with no key and no free
    chain. Detection still runs: a statement a parser owns never needed a model
    in the first place, and one that isn't comes back `unavailable` rather than
    blamed on the file.
    """
    prefs = accounts.load_prefs(paths.prefs)
    for provider, key, _model in engine.attempts(prefs):
        return provider, key
    return None, ""


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


def _issues(checked: list) -> list[Row]:
    from stocks.web import tx_text

    return [
        _row(c.tx, tx_text.issues_text(c.errors or c.warnings)) for c in checked
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
def attach(body: Attachment, paths: ChatTurn) -> Preview:
    """Detect, validate and preview one statement. Writes no ledger rows.

    A write all the same — it files the assistant's note on the thread, and on
    an unrecognised export it spends one model call — so it is `Writer` like
    every other route that costs the account something.

    Unlike the Import page this runs no live symbol-existence check: it costs a
    network round trip per unknown symbol against an API that already throttles
    us, and it can only ever soften a warning, never keep a bad row out. The
    one exception is an ISIN, resolved off the cached map the preview needs
    anyway to print a symbol.
    """
    raw = _decode(body.content)
    _file_at(paths, body.conversation)
    lang = _lang(paths, body.lang)

    provider, api_key = _provider(paths)
    found = autodetect.detect(body.filename, raw, provider, api_key)
    checked = validate(
        found.result,
        # Demo rows go on the first real commit, so checking against them
        # would raise duplicates that are about to stop existing.
        demo.without(all_transactions(paths.db)),
        known=known_tickers(paths.watchlist, paths.db),
        lookup=lambda t: True if is_isin(t) and symbol_for_isin(t) else None,
        # Asked about one symbol, and only when a sell overshoots: a bank PDF
        # prints the trades and leaves the 20:1 out, and rejecting that sell is
        # the rejection nobody can act on.
        splits=fetch.splits,
    )
    # The same anonymised record the Import page files, tagged with the surface
    # it came through: this path picks its parser by guessing, so its failures
    # break differently and are worth telling apart.
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
        duplicates=_issues(checked.duplicates),
        # Warnings worth reading are the ones about rows being committed; the
        # duplicates carry their own tier and their own explanation.
        flagged=_issues([c for c in checked.flagged if not c.duplicate]),
        rejected=_issues(checked.rejected),
        # Parsers add their own fields to a skip (`statement.skip_entry`), so
        # the three the preview prints are picked out rather than splatted.
        skipped=[
            Skipped(
                row=str(s.get("row", "")),
                type=str(s.get("type", "")),
                reason=str(s.get("reason", "")),
            )
            for s in found.result.skipped
        ],
        note=note,
        message=_say(paths, note),
        conversation=auth.active_conversation(paths.chat)["id"],
    )


@router.post(
    "/attachments/commit",
    response_model=Committed,
    summary="Write the previewed rows",
)
def commit(body: CommitRows, paths: Writer) -> Committed:
    """Append the rows the preview showed, and record the batch as undoable.

    The rows are taken as sent — see the module docstring for why they are not
    re-derived from the file — but every one of them is rebuilt through
    `Transaction`, so an unknown action is a 422 and not a row in the ledger.

    Nothing is deleted except the demo book, which the first real import always
    takes with it: an invented cost basis must never mix into a real one.
    """
    origin = body.broker.strip()
    if not origin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="rows need a broker to be filed under — send one as `broker`",
        )
    txs = platforms.stamp_broker([_transaction(r) for r in body.rows], origin)

    _file_at(paths, body.conversation)
    lang = _lang(paths, body.lang)

    demo.clear(paths.db)
    ids = add_many(txs, paths.db)
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
    note = (
        i18n.translate("chat.import_done", lang, n=len(ids), total=total)
        + " "
        + i18n.translate("chat.import_undo_hint", lang)
    )
    return Committed(
        imported=len(ids),
        tx_ids=ids,
        total=total,
        broker=origin,
        imported_at=stamped,
        message=_say(paths, note),
    )
