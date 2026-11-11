"""The upload: its request bodies, the decoded file, and who reads it."""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.notify import import_alert
from stocks.portfolio import (
    autodetect,
    diagnostics,
    llm_map,
    platforms,
    upload_guard,
)

# Statements are small — a Revolut CSV is tens of kilobytes and its PDF a
# couple of megabytes — but not all of them: a decade of IBKR activity as a
# PDF, or a bank's statement with a scanned page in it, runs to tens. The file
# is base64 inside a JSON body, so one request holds the text (4/3 of the
# file), the parsed JSON string and the decoded bytes at once — roughly three
# copies on a 1-vCPU, memory-capped Cloud Run worker. 50 MB decoded keeps a
# single upload well under ~250 MB of transient memory and still covers every
# real statement seen in the import diagnostics by an order of magnitude. The
# cap is on the decoded bytes, so a caller cannot spend the worker's memory by
# sending a gigabyte of base64 either.
MAX_BYTES = 50 * 1024 * 1024

# Nothing sane reaches this. It is here so that a client which lost its preview
# and started replaying garbage cannot ask for a million-row insert.
MAX_ROWS = 20_000


class Upload(BaseModel):
    model_config = {"extra": "forbid"}

    platform: str = Field(
        default="",
        description=(
            "The platform the reader named, from `/import/platforms` — its "
            "parser is tried first, and trusted no further: the model and "
            "every parser read the file, and the preview's `platform` says "
            "which one did. Empty, or `llm`, names none."
        ),
    )
    filename: str = Field(
        min_length=1,
        max_length=255,
        description="The export's own name — the parser reads its extension.",
    )
    content: str = Field(description="The file's bytes, base64-encoded.")
    surface: Literal["import", "paste"] = Field(
        default="import",
        description=(
            "How the file reached the client: picked from disk, or pasted as "
            "text into the fallback box. Only the anonymised import "
            "diagnostics read it — the two doors break differently (a paste "
            "loses its encoding and its line endings on the way), so they are "
            "recorded apart."
        ),
    )
    wipe: bool = Field(
        default=False,
        description=(
            "Read this statement as a replacement for the book rather than an "
            "addition to it. Validation then runs against an empty ledger, so "
            "nothing is flagged as a duplicate of a row that is about to be "
            "deleted and no sell is rejected against buys that are about to "
            "go — which is why it belongs on the preview too, where it does "
            "only that. On a commit it also empties the book, and there it "
            "needs `wipe_confirm`."
        ),
    )


class StatementRow(BaseModel):
    """One ledger row a preview showed, sent back to be written."""

    model_config = {"extra": "forbid"}

    date: str = Field(max_length=32)
    ticker: str = Field(max_length=64)
    action: str = Field(max_length=32)
    quantity: float = 0.0
    price: float = 0.0
    currency: str = Field(default="USD", max_length=8)
    fee: float = 0.0
    note: str = Field(default="", max_length=500)


class Commit(Upload):
    content: str = Field(
        default="",
        description=(
            "The file's bytes, base64-encoded — or nothing, when `rows` is "
            "sent instead."
        ),
    )
    rows: list[StatementRow] | None = Field(
        default=None,
        max_length=MAX_ROWS,
        description=(
            "The preview's importable rows, as it returned them. Sent, and "
            "they are validated again and written; the file is not read a "
            "second time, so a model's reading cannot change between what "
            "was shown and what is written."
        ),
    )
    keep_duplicates: bool = Field(
        default=False,
        description=(
            "Write the rows the ledger already holds too. Off, a commit adds "
            "only what is new — re-importing an overlapping statement leaves "
            "the book as it was — and the result says how many it left out. "
            "On only for movements the reader knows are separate (two "
            "identical fills on one day)."
        ),
    )
    broker: str = Field(
        default="",
        description=(
            "Origin to stamp on the rows, when the parser detected none. The "
            "fees and custody views read the book by it, so a batch committed "
            "without one is tedious to attribute afterwards."
        ),
    )
    expect: str = Field(
        default="",
        description=(
            "The `digest` a preview returned. Given, and a different file is "
            "refused rather than committed."
        ),
    )
    wipe_confirm: str = Field(
        default="",
        description=(
            "Required when `wipe` is set: the signed-in address, typed back. "
            "Emptying a book cannot be undone and no backup is taken, so the "
            "request has to name the book it is replacing — the same rule "
            "`DELETE /v1/portfolio/transactions` is under."
        ),
    )


def _decode(body: Upload, stage: str = "preview") -> bytes:
    """The upload's bytes, or the 4xx that says why there are none. Logged as
    `import.upload` either way, and a refusal is an alert: the file never
    reached a parser, so nothing else would record it."""
    def refuse(code: int, detail: str, why: str, size: int) -> HTTPException:
        obs.warn("import.refused", stage=stage, surface=body.surface, why=why,
                 bytes=size)
        import_alert.failed(
            brief(body.filename, body.surface, body.platform, bytes=size),
            stage=f"{stage}_upload_{why}", detail=detail,
        )
        return HTTPException(status_code=code, detail=detail)

    try:
        raw = base64.b64decode(body.content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise refuse(status.HTTP_422_UNPROCESSABLE_CONTENT,
                     "content must be base64", "not_base64",
                     len(body.content) * 3 // 4) from exc
    if not raw:
        raise refuse(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty file", "empty", 0)
    if len(raw) > MAX_BYTES:
        raise refuse(status.HTTP_413_CONTENT_TOO_LARGE,
                     f"statements are capped at {MAX_BYTES // (1024 * 1024)} MB",
                     "too_large", len(raw))
    try:
        upload_guard.check(raw)
    except upload_guard.TooCostly as exc:
        raise refuse(status.HTTP_413_CONTENT_TOO_LARGE, str(exc), "too_costly",
                     len(raw)) from exc
    obs.event("import.upload", stage=stage, surface=body.surface, bytes=len(raw),
              ext=_ext(body.filename), named=body.platform or "", wipe=body.wipe,
              digest=hashlib.sha256(raw).hexdigest()[:16])
    return raw


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower()[:8] if "." in filename else ""


def brief(filename: str, surface: str, platform: str, parsed=None, checked=None,
          **extra) -> dict:
    """A diagnostics-shaped record for an alert with no file to fingerprint —
    rows sent back from a preview, or bytes that never decoded."""
    return {
        "user": obs.current().get("user", "-"),
        "surface": surface,
        "platform": platform or "",
        "file": diagnostics.mask_digits(filename),
        "ext": _ext(filename),
        "imported": len(parsed.transactions) if parsed is not None else 0,
        "rejected": len(checked.rejected) if checked is not None else 0,
        **extra,
    }


def watch_preview(fp: dict, found, checked, rows: int, digest: str) -> None:
    """Log a finished preview and hand it to the owner's alert: watched until
    a commit when it has something to write, reported now when it has nothing
    (and not because every row is already in the book)."""
    holdings = len(found.holdings)
    obs.event(
        "import.preview",
        platform=found.platform,
        kind=found.kind,
        surface=fp.get("surface", ""),
        rows=rows,
        holdings=holdings,
        rejected=len(checked.rejected),
        flagged=len(checked.flagged),
        duplicates=len(checked.duplicates),
        skipped=len(found.result.skipped),
        unavailable=found.unavailable,
        digest=digest[:16],
    )
    if rows or holdings:
        import_alert.previewed(fp, digest=digest, importable=rows or holdings,
                               platform=found.platform)
    elif checked.duplicates:
        # Every row is already in the book: nothing left to finish.
        import_alert.committed()
    else:
        import_alert.failed(
            fp,
            stage="model_unavailable" if found.unavailable else "nothing_importable",
            detail=f"{len(checked.rejected)} rejected, "
                   f"{len(found.result.skipped)} skipped",
            digest=digest,
        )


def _platform(key: str):
    """The named parser, or 404.

    `platforms.by_key` falls back to the first platform for an unknown key,
    which is right for a selectbox restoring a stale session and wrong here:
    parsing a Trading 212 export with the Revolut parser would be answered with
    "0 importable rows" instead of "you asked for a platform I do not have".
    """
    for platform in platforms.PLATFORMS:
        if platform.key == key:
            return platform
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown platform: {key}"
    )


def _prefer(key: str) -> str | None:
    """The parser a reader named, to try first — None when they named none.

    Empty and `llm` (what a preview returns for a file the model read) name
    none. Anything else has to be a platform this app has: an unknown key is
    a client bug worth a 404, not a hint to drop quietly.
    """
    key = key.strip()
    if not key or key == autodetect.LLM_KEY:
        return None
    return _platform(key).key


def _provider(paths, held: dict[str, str] | None = None):
    """The provider that would answer this account, for the model's read.

    None when there is nothing to ask — a BYOK account with no key and no free
    chain. The read still runs: the parsers read without a model, and a file
    none of them owns comes back `unavailable` rather than blamed on the file.
    `held` is the session-only key the request carried (`chat.session_keys`):
    the reader who typed one for this tab expects the read to run on it too,
    not on a free chain that may have run dry.
    """
    from stocks import accounts
    from stocks.chat import engine

    prefs = accounts.load_prefs(paths.prefs)
    # `answerable`: the mapper's calls (up to MAX_PDF_CALLS a file) are never
    # charged to the allowance, so a free chain that has run dry today must
    # not be the provider they run on.
    for provider, key, _model in engine.answerable(prefs, engine.chain(prefs, held)):
        return provider, key
    return None, ""


def _read(
    account,
    filename: str,
    raw: bytes,
    *,
    held: dict[str, str] | None = None,
    prefer: str | None = None,
    mapping: dict | None = None,
) -> autodetect.Detected:
    """Read a statement the way both surfaces read it: model first, parsers as
    its check (`autodetect.read`), remembered per account so the commit that
    follows a preview does not pay for a second model call. A crypto export
    traded only against stablecoins is booked in the account's currency."""
    from stocks import accounts

    provider, api_key = _provider(account, held)
    return autodetect.read(
        filename,
        raw,
        provider,
        api_key,
        prefer=prefer,
        mapping=mapping,
        scope=str(account.db),
        fiat=accounts.load_prefs(account.prefs).get("currency") or "",
    )


def _held(x_chat_provider: str | None, x_chat_key: str | None):
    # Imported here: `chat` imports `chat_attach`, which imports this module.
    from stocks.api.routes.chat import session_keys

    return session_keys(x_chat_provider, x_chat_key)


def _unreadable(found: autodetect.Detected) -> str | None:
    """Why nothing at all could be read from this file, or None.

    A file with rows in it, a portfolio report (nothing dated to import, and
    the preview says so) and a file the model never got to judge are all
    answered with a preview. What is left is a file whose only skips are about
    the file itself — every parser declined or choked on it and the model
    found nothing — and that is the caller's file, not a server fault: the
    page refuses it with each reader's reason, as it always refused a file its
    parser could not read.
    """
    result = found.result
    if result.transactions or found.unavailable:
        return None
    if found.kind == llm_map.KIND_POSITIONS:
        return None
    if any(s.get("type") != "file" for s in result.skipped):
        return None
    reasons = "; ".join(str(s.get("reason", "")) for s in result.skipped)
    return (reasons or "nothing in this file reads as a transaction")[:300]
