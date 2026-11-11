"""The import itself: what can be read, preview, commit, and the last batch."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from stocks import loaders, obs
from stocks.api.deps import Account, Writer
from stocks.api.routes.import_statement.lookups import _within
from stocks.api.routes.import_statement.upload import (
    Commit,
    Upload,
    _decode,
    _held,
    _prefer,
    _read,
    _unreadable,
    brief,
    watch_preview,
)
from stocks.api.routes.import_statement.validation import (
    QUOTES_BUDGET_S,
    _gains,
    _real_rows,
    _retag,
    _row,
    _skipped,
    _statement_row,
    _validated,
)
from stocks.api.security import Authed
from stocks.notify import import_alert
from stocks.portfolio import (
    autodetect,
    demo,
    diagnostics,
    held,
    last_import,
    platforms,
    venue,
)
from stocks.portfolio.ledger import add_many, all_transactions, clear, delete_many
from stocks.portfolio.statement import ParseResult
from stocks.schemas import (
    ImportHolding,
    ImportPlatform,
    ImportPlatforms,
    ImportPreview,
    ImportResult,
    LastImport,
    Transaction,
)

router = APIRouter(prefix="/import", tags=["import"])


@router.get("/platforms", response_model=ImportPlatforms, summary="What can be read")
def registry() -> ImportPlatforms:
    return ImportPlatforms(
        platforms=[
            ImportPlatform(
                key=platform.key,
                label=platform.label,
                file_types=list(platform.file_types),
                hint=platform.hint,
                domain=platform.domain,
                logo=loaders.brand_logo(platform.key),
                has_sample=bool(platform.sample),
            )
            for platform in platforms.PLATFORMS
        ],
        accepts=list(autodetect.supported_types()),
    )


@router.post("/preview", response_model=ImportPreview, summary="What it would do")
def preview(
    account: Writer,
    body: Annotated[Upload, ...],
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> ImportPreview:
    """Read and validate a statement, writing nothing.

    A session like every other non-GET here, even though this one changes
    nothing: a rule with an exception in it is a rule nobody can check. It
    also spends the account's model calls, which is one more reason.

    `platform` in the answer is what read the file — the named parser, another
    one, or `llm` for the model — so a page that preselected Revolut can say
    "read as Trading 212" instead of letting the reader assume.
    """
    prefer = _prefer(body.platform)
    raw = _decode(body)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        found = _read(
            account,
            body.filename,
            raw,
            held=_held(x_chat_provider, x_chat_key),
            prefer=prefer,
        )
        why = _unreadable(found)
        if why:
            fp = diagnostics.report(
                found.platform, body.filename, raw, found.result, surface=body.surface
            )
            obs.warn("import.refused", stage="preview", surface=body.surface,
                     why="unreadable", platform=found.platform)
            import_alert.failed(fp, stage="preview_unreadable", detail=why,
                                digest=digest)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=why
            )
        checked, disowned = _validated(account, found.result, wipe=body.wipe)
    except HTTPException:
        raise
    except Exception as exc:
        _crashed(body, raw, "preview", exc, digest)
        raise
    # The anonymised record the page files for every outcome, which is what
    # turns "some brokers fail" into a queryable fact.
    fp = diagnostics.report(
        found.platform, body.filename, raw, found.result, checked,
        surface=body.surface,
    )
    watch_preview(fp, found, checked, len(checked.fresh), digest)
    importable = checked.importable
    detected = platforms.detected_broker(importable)
    rows = [c for c in checked.checked if not c.errors]
    # How each row has done: the book it lands in for a sale's cost, and one
    # bounded quote request for the buys — a throttled Yahoo costs the column,
    # never the preview.
    prior = [] if body.wipe else venue.relabeled(_real_rows(account), checked.relabeled)
    bought = tuple(sorted({c.tx.ticker for c in rows if c.tx.action == "buy"}))
    prices = (
        _within(lambda: loaders.quotes(bought), QUOTES_BUDGET_S, {}, quotes=len(bought))
        if bought
        else {}
    )
    gains = _gains(rows, prior, prices)
    return ImportPreview(
        platform=found.platform,
        label=found.label,
        kind=found.kind,
        unavailable=found.unavailable,
        filename=body.filename,
        digest=digest,
        importable=[_row(c, gain) for c, gain in zip(rows, gains, strict=True)],
        rejected=[_row(c) for c in checked.rejected],
        duplicates=len(checked.duplicates),
        skipped=[_skipped(s) for s in found.result.skipped],
        broker=detected,
        needs_broker=bool(importable or found.holdings) and not detected,
        holdings=[ImportHolding(**held) for held in found.holdings],
        unlisted=sorted(disowned & {c.tx.ticker for c in rows}),
    )


def _crashed(body: Upload, raw: bytes, stage: str, exc: Exception,
             digest: str) -> None:
    """A read or a validation that raised: filed, logged and alerted before
    the 500 goes out, since the reader is left with nothing."""
    fp = diagnostics.report("", body.filename, raw, surface=body.surface, error=exc)
    obs.error("import.crashed", exc, stage=stage, surface=body.surface)
    import_alert.failed(fp, stage=f"{stage}_crash", detail=str(exc)[:300],
                        digest=digest)


class ClientFailure(BaseModel):
    """A statement the browser picked and then could not read."""

    model_config = {"extra": "forbid"}

    platform: str = Field(default="", max_length=64)
    filename: str = Field(
        default="",
        max_length=255,
        description="Masked before it is kept: its digits go, its extension stays.",
    )
    bytes: int = Field(default=0, ge=0, description="The size the browser claimed.")
    error: str = Field(
        default="Error",
        max_length=64,
        description="The exception's name — `NotReadableError`, `NotFoundError`.",
    )
    message: str = Field(default="", max_length=500)


@router.post(
    "/client-failure",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="A file the browser could not read",
)
def client_failure(account: Writer, body: Annotated[ClientFailure, ...]) -> None:
    """File the anonymised diagnostic for a read that never reached `/preview`.

    The page reads the file before it sends anything, so a phone that hands
    over a file it cannot open — one still in Drive, one shared out of a chat
    app — failed with no request at all, and so with no record anywhere. A
    session like every other write, which also caps who can fill
    `data/imports/` to the people who could import in the first place.
    """
    fp = diagnostics.client_failure(
        body.platform, body.filename, body.bytes, body.error, body.message
    )
    obs.warn("import.refused", stage="browser_read", surface="import",
             why=body.error, bytes=body.bytes)
    import_alert.failed(fp, stage="browser_read", detail=body.error)


@router.post("/commit", response_model=ImportResult, summary="Write the rows")
def commit(
    caller: Authed,
    account: Writer,
    body: Annotated[Commit, ...],
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> ImportResult:
    """Validate and append the importable rows the ledger does not hold yet.

    The rows a preview showed come back as `rows` and are validated again
    here, never taken on the preview's word. The ledger is shared mutable
    state: a row that validated clean a moment ago can be a duplicate now, and
    committing a remembered verdict would be committing an answer to a
    question about a ledger that no longer exists. Without `rows`, the file is
    read again, exactly as its preview read it.

    `wipe` replaces the book rather than adding to it, and the order below is
    the whole reason it lives here instead of being left to two calls: the
    statement is read, validated and found to carry rows worth writing
    *before* anything is deleted. A client that wiped first and then failed its
    commit would be holding an empty ledger and no undo.
    """
    prefer = _prefer(body.platform)
    if body.wipe and body.wipe_confirm.strip().lower() != (caller.email or "").lower():
        # The reader's to fix, so logged only: if they give up instead, the
        # preview's watch reports it as abandoned.
        obs.warn("import.refused", stage="commit", surface=body.surface,
                 why="wipe_confirm")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="wipe_confirm must be the signed-in address, exactly",
        )
    raw, report, digest = b"", False, body.expect
    if body.rows is not None:
        parsed = ParseResult(transactions=[_statement_row(r) for r in body.rows])
        read_by = prefer or autodetect.LLM_KEY
        obs.event("import.upload", stage="commit", surface=body.surface,
                  rows=len(body.rows), named=body.platform or "", wipe=body.wipe,
                  digest=digest[:16])
    else:
        raw = _decode(body, "commit")
        digest = hashlib.sha256(raw).hexdigest()
        if body.expect and body.expect != digest:
            detail = "this is not the file that was previewed"
            obs.warn("import.refused", stage="commit", surface=body.surface,
                     why="digest_mismatch")
            import_alert.failed(
                brief(body.filename, body.surface, body.platform, bytes=len(raw)),
                stage="commit_digest_mismatch", detail=detail, digest=digest,
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
        try:
            found = _read(
                account,
                body.filename,
                raw,
                held=_held(x_chat_provider, x_chat_key),
                prefer=prefer,
            )
        except Exception as exc:
            _crashed(body, raw, "commit", exc, digest)
            raise
        # Reported only when no preview was claimed: a commit carrying
        # `expect` is of bytes its preview already filed a diagnostic for (the
        # digest matched just above), and a second record would count one
        # upload twice. A client that commits blind is the one whose attempt
        # would otherwise go unseen.
        report = not body.expect
        why = _unreadable(found)
        if why:
            fp = (
                diagnostics.report(
                    found.platform, body.filename, raw, found.result,
                    surface=body.surface,
                )
                if report
                else brief(body.filename, body.surface, found.platform,
                           found.result, bytes=len(raw))
            )
            obs.warn("import.refused", stage="commit", surface=body.surface,
                     why="unreadable", platform=found.platform)
            import_alert.failed(fp, stage="commit_unreadable", detail=why,
                                digest=digest)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=why
            )
        parsed, read_by = found.result, found.platform
    checked, _disowned = _validated(account, parsed, wipe=body.wipe)
    if report:
        diagnostics.report(
            read_by, body.filename, raw, parsed, checked, surface=body.surface
        )
    importable = checked.importable if body.keep_duplicates else checked.fresh
    left_out = 0 if body.keep_duplicates else len(checked.duplicates)
    if not importable:
        detail = (
            "every row in this statement is already in the book"
            if left_out
            else "nothing in this statement is importable"
        )
        obs.warn("import.refused", stage="commit", surface=body.surface,
                 why="all_duplicates" if left_out else "nothing_importable",
                 platform=read_by, rejected=len(checked.rejected))
        if left_out:
            # Not a failure: the book already holds the statement.
            import_alert.committed()
        else:
            import_alert.failed(
                brief(body.filename, body.surface, read_by, parsed, checked),
                stage="commit_nothing_importable", detail=detail, digest=digest,
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail
        )
    origin = platforms.detected_broker(importable) or body.broker.strip()
    if not origin:
        detail = "this statement names no broker — send one as `broker`"
        obs.warn("import.refused", stage="commit", surface=body.surface,
                 why="no_broker", platform=read_by)
        import_alert.failed(
            brief(body.filename, body.surface, read_by, parsed, checked),
            stage="commit_no_broker", detail=detail, digest=digest,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail
        )

    # Activation, read before anything is written: the account's first real
    # import is the one the funnel counts, and a wipe-and-reimport is not it.
    first = not demo.has_real(account.db)
    if body.wipe:
        # Past the last refusal: the statement is going in, so the book it
        # replaces can go. `clear` takes the demo rows with it.
        clear(account.db)
    else:
        # The first real import is what the demo book was borrowed against: an
        # invented cost basis must never end up mixed into a real one.
        demo.clear(account.db)
    ids = add_many(platforms.stamp_broker(importable, origin), account.db)
    if ids:
        _retag(account.db, checked.relabeled)
    # A sale refused only for want of shares is usually waiting on a split or a
    # transfer that has not landed yet: kept, Import offers it back once the
    # book can carry it (`GET /import/checkup`).
    held.seen_broker(origin, account.db)
    held.keep(checked.rejected, origin, account.db)
    stamped = datetime.now(UTC).isoformat(timespec="seconds")
    last_import.save(
        last_import.ImportRecord(
            filename=body.filename,
            imported_at=stamped,
            tx_ids=ids,
            wiped=body.wipe,
            platform=read_by,
        ),
        account.last_import,
    )
    # The denominator for every failure rate: without it the logs say how often
    # an import breaks but not out of how many.
    obs.event(
        "import.committed",
        platform=read_by,
        broker=origin,
        n=len(ids),
        wiped=body.wipe,
        first=first,
        via="api",
    )
    import_alert.committed()
    return ImportResult(
        platform=read_by,
        filename=body.filename,
        imported=len(ids),
        duplicates=left_out,
        tx_ids=ids,
        broker=origin,
        imported_at=stamped,
        rejected=[_row(c) for c in checked.rejected],
    )


@router.get("/last", response_model=LastImport, summary="The last batch")
def last(account: Account) -> LastImport:
    """What the last commit did, and how much of it is left.

    The count it was committed with and the count still in the ledger are two
    different numbers: rows can be deleted one at a time afterwards. Offering
    to undo "120 rows" when 40 of them are already gone promises something the
    undo cannot do, so both are sent, along with the surviving rows — seeing
    them is the only way to check a count nobody can verify from outside.
    """
    record = last_import.load(account.last_import)
    if record is None:
        return LastImport()
    batch = set(record.tx_ids)
    surviving = [t for t in all_transactions(account.db) if t.id in batch]
    return LastImport(
        filename=record.filename,
        imported_at=record.imported_at,
        imported_on=last_import.imported_on(record),
        platform=record.platform,
        rows=len(record.tx_ids),
        still_here=len(surviving),
        transactions=[
            Transaction(
                id=t.id,
                date=t.date,
                ticker=t.ticker,
                action=t.action,
                quantity=t.quantity,
                price=t.price,
                currency=t.currency,
                fee=t.fee,
                note=t.note,
            )
            for t in surviving
        ],
        wiped=record.wiped,
    )


@router.delete("/last", response_model=LastImport, summary="Undo it")
def undo(account: Writer) -> LastImport:
    """Delete exactly the rows the last commit inserted.

    By id, not by re-reading the file: a statement re-parsed against a ledger
    that has moved does not identify the same rows, and anything broader than
    those ids would take somebody else's import with it.
    """
    record = last_import.load(account.last_import)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no import to undo"
        )
    removed = delete_many(record.tx_ids, account.db)
    last_import.forget(account.last_import)
    return LastImport(
        filename=record.filename,
        imported_at=record.imported_at,
        platform=record.platform,
        rows=removed,
        wiped=record.wiped,
    )


@router.delete(
    "/record", response_model=LastImport, summary="Forget the note, keep the rows"
)
def dismiss(account: Writer) -> LastImport:
    """Drop the last-import record. The transactions stay exactly where they are.

    Three things the page keeps apart, because what separates them is the
    ledger itself:

    * `DELETE /import/last` — *clear last import*: deletes the rows that batch
      inserted, by id, and forgets the record.
    * `DELETE /import/record` — *dismiss*: forgets the record and nothing else.
      The rows are the account's; it has only stopped being offered the undo.
    * `DELETE /v1/portfolio/transactions` — *delete everything*: empties the
      book — every import, and every row typed in by hand years ago — and
      forgets the record too, because an undo pointing into a book that is gone
      would be a lie.

    `rows` here is what was left behind, not what was removed. Nothing was.
    """
    record = last_import.load(account.last_import)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no import record to dismiss"
        )
    last_import.forget(account.last_import)
    return LastImport(
        filename=record.filename,
        imported_at=record.imported_at,
        platform=record.platform,
        rows=len(record.tx_ids),
        wiped=record.wiped,
    )
