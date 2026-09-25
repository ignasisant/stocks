"""Turning a broker statement into ledger rows, over HTTP.

The flow the page has always had: pick a platform, upload, parse (writing
nothing), validate against the ledger, look at the tiers, commit. Split here
into a preview and a commit, because the safety property is that a reader —
or a client — sees what a file will do before it does it.

**The file arrives as base64 in a JSON body, not as multipart.** That is a
deliberate choice and not an oversight: a cross-site HTML form *can* send
multipart, so accepting it would hand back the CSRF hole that every other write
here avoids by requiring `application/json`. The ~33% encoding overhead is
nothing against a statement.

**Commit re-parses and re-validates.** It does not trust the preview, and it
cannot: the ledger moves, and a row that was importable ten seconds ago may now
be a duplicate of one another client just committed. `expect` lets a caller
assert the bytes are the same ones it previewed; nothing lets it assert the
ledger is.

**Replacing a ledger is a confirmation, not a flag.** The page offers a
"wipe first" checkbox, and the two halves of it have to travel together: a
client that emptied the book with `DELETE /v1/portfolio/transactions` and then
failed to commit has destroyed a book nobody can restore and put nothing in
its place. So `commit` takes `wipe` — and takes `wipe_confirm` with it, the
signed-in address typed back, which is the same confirmation that route
demands, because "name the book you are emptying" is not a rule worth having
two versions of. Nothing is deleted until the statement has parsed, validated
and produced rows worth writing.

**The demo rows are never the baseline.** A commit clears them (an invented
cost basis must not mix into a real one), so validating an incoming batch
against them would be checking it against lots that are about to stop
existing — `demo.without`, exactly as the page does.

**The two repairs sit beside the import**, because a statement cannot express
either: splits the book never heard about (`stocks.portfolio.corporate`, which
prices every holding against Yahoo) and shares that only changed broker but
read as a sale (`stocks.portfolio.transfers`, from the ledger alone). Each
scans and each applies, and an apply names what it accepts: the scan shows the
evidence first, and a client that could only say "yes to everything" would be
a worse offer than the page it replaces.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.api import loaders
from stocks.api.deps import Account, Writer
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import (
    ImportIssue,
    ImportPlatform,
    ImportPlatforms,
    ImportPreview,
    ImportResult,
    ImportRow,
    LastImport,
    Transaction,
)
from stocks.api.security import Authed
from stocks.data import fetch
from stocks.portfolio import (
    corporate,
    demo,
    diagnostics,
    last_import,
    platforms,
    transfers,
)
from stocks.portfolio.ledger import add_many, all_transactions, clear, delete_many
from stocks.portfolio.validate import known_tickers, validate

router = APIRouter(prefix="/import", tags=["import"])

# Statements are small — a Revolut CSV is tens of kilobytes and its PDF a
# couple of megabytes — but not all of them: a decade of IBKR activity as a
# PDF, or a bank's statement with a scanned page in it, runs to tens. The
# Streamlit uploader takes 200 MB (its default; `.streamlit/config.toml` sets
# no `maxUploadSize`), and a file that page accepts should not be one this
# route refuses. It cannot take the same 200 MB, though: here the file is
# base64 inside a JSON body, so one request holds the text (4/3 of the file),
# the parsed JSON string and the decoded bytes at once — roughly three copies
# on a 1-vCPU, memory-capped Cloud Run worker. 50 MB decoded keeps a single
# upload well under ~250 MB of transient memory and still covers every real
# statement seen in the import diagnostics by an order of magnitude. The cap
# is on the decoded bytes, so a caller cannot spend the worker's memory by
# sending a gigabyte of base64 either.
MAX_BYTES = 50 * 1024 * 1024


class Upload(BaseModel):
    model_config = {"extra": "forbid"}

    platform: str = Field(description="Platform key, from `/import/platforms`.")
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
            "loses its encoding and its line endings on the way), and the "
            "Streamlit page records them apart for that reason."
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


class Commit(Upload):
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


def _decode(body: Upload) -> bytes:
    try:
        raw = base64.b64decode(body.content, validate=True)
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
            detail=f"statements are capped at {MAX_BYTES // (1024 * 1024)} MB",
        )
    return raw


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


def _parse(platform, filename: str, raw: bytes, *, surface: str | None = None):
    """Run the platform's parser; a parser that raises is the caller's 422.

    `surface` set means "report this attempt" (see `_checked`): a parser that
    raises used to reach the reader as an error and reach us not at all, and
    the anonymised fingerprint is what names the encoding or the header row
    that broke it.
    """
    try:
        return platform.parse(filename, raw)
    except Exception as exc:
        # A statement this parser cannot read is the caller's file, not a
        # server fault — and the reason is the only useful part of the answer.
        obs.warn(
            "api.import_parse_failed",
            platform=platform.key,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        if surface:
            diagnostics.report(platform.key, filename, raw, surface=surface, error=exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{platform.label} could not read this file: {exc}"[:300],
        ) from exc


# ------------------------------------------------ the live lookups validation uses
# Validation asks the market two things the ledger cannot answer, exactly as
# the Streamlit page asks them (`import_transactions._ticker_exists` and
# `fetch.splits`): does a symbol the EDGAR map and the watchlist have never
# heard of trade at all — so an ordinary European listing stops arriving with
# an "unknown ticker" warning — and did a ticker whose sells overshoot split
# in between, so a statement that prints trades and no corporate actions is
# rescued with the split row instead of rejected as an oversell.
#
# The page can afford to ask naively: a Streamlit run is one reader waiting on
# one spinner. Here the same call holds an ASGI worker thread, so every answer
# is bounded — per symbol, and in total per statement — and a throttled host
# is not asked at all. Running out of budget answers None, which validation
# already reads as "could not check": the warning stays, nothing is rejected
# on its account, and the reader is exactly where they were before this
# lookup existed. Only definite answers are remembered — "network down" is not
# "ticker invalid", and caching it would make the outage outlive itself.

LOOKUP_BUDGET_S = 4.0  # one symbol's existence check
SPLITS_BUDGET_S = 8.0  # one ticker's corporate-actions history
BATCH_BUDGET_S = 15.0  # every existence check one statement makes, together
_EXISTS_TTL_S = 24 * 3600.0
_EXISTS_MAX = 2048

_exists_memo: dict[str, tuple[float, bool]] = {}
_exists_lock = threading.Lock()


def _within(fn, budget: float, default, **fields):
    """`fn()` on a worker, or `default` once `budget` seconds have passed.

    No `with` on the pool, for the reason `fetch._budgeted` gives: shutting it
    down and waiting would block on exactly the hung call the timeout escaped.
    The abandoned thread finishes into nothing — yfinance bounds each request.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=max(budget, 0.0))
    except FuturesTimeout:
        obs.warn("api.import_lookup_budget_spent", budget_s=budget, **fields)
        return default
    except Exception as exc:  # a lookup that breaks is a lookup that could not say
        obs.warn("api.import_lookup_failed", error_type=type(exc).__name__, **fields)
        return default
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _ticker_exists(ticker: str) -> bool | None:
    """Does Yahoo quote this symbol? None when it could not be asked.

    The Streamlit page's check, verbatim in what it asks: a last price means a
    listing. A rate limit trips the host-wide cooldown (`fetch.trip_throttle`)
    so the next statement does not ask again into a throttle and deepen it.
    """
    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError

    try:
        return bool(yf.Ticker(ticker).fast_info.get("lastPrice"))
    except YFRateLimitError:
        fetch.trip_throttle()
        return None
    except Exception:
        return None  # network down ≠ ticker invalid


class _Lookup:
    """`validate`'s `lookup`, bounded: one instance per statement.

    The batch deadline starts when the instance is made, so a statement of two
    hundred unfamiliar symbols spends at most `BATCH_BUDGET_S` finding out
    which of them trade, and the rest stay "could not check".
    """

    def __init__(self) -> None:
        self.deadline = time.monotonic() + BATCH_BUDGET_S

    def __call__(self, ticker: str) -> bool | None:
        now = time.monotonic()
        with _exists_lock:
            hit = _exists_memo.get(ticker)
        if hit is not None and now - hit[0] < _EXISTS_TTL_S:
            return hit[1]
        left = self.deadline - now
        if left <= 0 or fetch.throttle_remaining() > 0:
            return None
        answer = _within(
            lambda: _ticker_exists(ticker),
            min(LOOKUP_BUDGET_S, left),
            None,
            ticker=ticker,
        )
        if answer is not None:
            with _exists_lock:
                _exists_memo[ticker] = (now, answer)
                while len(_exists_memo) > _EXISTS_MAX:
                    _exists_memo.pop(next(iter(_exists_memo)))
        return answer


def _splits(ticker: str) -> list[tuple[str, float]]:
    """`fetch.splits`, bounded. Already memoized and throttle-aware there; the
    budget is the one thing it lacks for a caller holding a worker thread."""
    return _within(lambda: fetch.splits(ticker), SPLITS_BUDGET_S, [], ticker=ticker)


def _row(checked) -> ImportRow:
    tx = checked.tx
    return ImportRow(
        date=tx.date,
        ticker=tx.ticker,
        action=tx.action,
        quantity=tx.quantity,
        price=tx.price,
        currency=tx.currency,
        fee=tx.fee,
        note=tx.note,
        issues=[
            ImportIssue(
                severity=issue.severity,
                field=issue.field,
                key=issue.key,
                params=issue.params,
                message=issue.message,
            )
            for issue in checked.issues
        ],
        duplicate=checked.duplicate,
    )


def _real_rows(account) -> list:
    """The account's own transactions, without the demo book.

    Every repair and every validation here reads this rather than the raw
    table. The demo rows are fabricated and the next commit deletes them, so
    counting them as prior holdings would validate a real statement against
    lots that are about to stop existing, and would offer to repair a split on
    a position nobody owns.
    """
    return demo.without(all_transactions(account.db))


def _checked(
    account,
    platform,
    filename: str,
    raw: bytes,
    *,
    wipe: bool = False,
    surface: str | None = None,
):
    """Parse and validate against this account's own ledger and watchlist.

    `wipe` empties the baseline rather than the book: a statement that is about
    to replace the ledger has to be read against the ledger it will leave
    behind, or every row it re-imports comes back flagged as a duplicate of one
    that is on its way out.

    Validated with the Streamlit page's two live lookups (`_Lookup`, `_splits`)
    — without them the same statement read clean on one surface and warned or
    rejected on the other.

    `surface` ("import" / "paste") files the anonymised diagnostic the page
    files for every outcome (`portfolio.diagnostics.report`) — the parser
    raising, a file with nothing in it, and the full parse-and-validate record
    — which is what turns "some brokers fail" into a queryable fact. None
    reports nothing: a commit of a file its preview already reported would
    count one upload twice.

    A statement the parser read without error but found nothing in — no
    transaction and not even a skipped line — is refused as unreadable (422),
    as the page refuses it: that is a file from the wrong platform or the
    wrong export, and an empty preview would only say "0 rows".
    """
    parsed = _parse(platform, filename, raw, surface=surface)
    if not parsed.transactions and not parsed.skipped:
        if surface:
            diagnostics.report(platform.key, filename, raw, parsed, surface=surface)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{platform.label} found no transactions in this file",
        )
    prior = [] if wipe else _real_rows(account)
    known = known_tickers(account.watchlist, account.db)
    validation = validate(parsed, prior, known=known, lookup=_Lookup(), splits=_splits)
    if surface:
        diagnostics.report(
            platform.key, filename, raw, parsed, validation, surface=surface
        )
    return parsed, validation


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
        ]
    )


@router.post("/preview", response_model=ImportPreview, summary="What it would do")
def preview(account: Writer, body: Annotated[Upload, ...]) -> ImportPreview:
    """Parse and validate a statement, writing nothing.

    A session like every other non-GET here, even though this one changes
    nothing: a rule with an exception in it is a rule nobody can check.
    """
    platform = _platform(body.platform)
    raw = _decode(body)
    parsed, checked = _checked(
        account, platform, body.filename, raw, wipe=body.wipe, surface=body.surface
    )
    importable = checked.importable
    detected = platforms.detected_broker(importable)
    return ImportPreview(
        platform=platform.key,
        filename=body.filename,
        digest=hashlib.sha256(raw).hexdigest(),
        importable=[_row(c) for c in checked.checked if not c.errors],
        rejected=[_row(c) for c in checked.rejected],
        duplicates=len(checked.duplicates),
        skipped=list(parsed.skipped),
        broker=detected,
        needs_broker=bool(importable) and not detected,
    )


@router.post("/commit", response_model=ImportResult, summary="Write the rows")
def commit(
    caller: Authed, account: Writer, body: Annotated[Commit, ...]
) -> ImportResult:
    """Parse, validate and append the importable rows.

    Everything is redone rather than taken from the preview. The ledger is
    shared mutable state: a row that validated clean a moment ago can be a
    duplicate now, and committing a remembered verdict would be committing an
    answer to a question about a ledger that no longer exists.

    `wipe` replaces the book rather than adding to it, and the order below is
    the whole reason it lives here instead of being left to two calls: the
    statement is parsed, validated and found to carry rows worth writing
    *before* anything is deleted. A client that wiped first and then failed its
    commit would be holding an empty ledger and no undo.
    """
    platform = _platform(body.platform)
    if body.wipe and body.wipe_confirm.strip().lower() != (caller.email or "").lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="wipe_confirm must be the signed-in address, exactly",
        )
    raw = _decode(body)
    digest = hashlib.sha256(raw).hexdigest()
    if body.expect and body.expect != digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this is not the file that was previewed",
        )

    # Reported only when no preview was claimed: a commit carrying `expect` is
    # of bytes its preview already filed a diagnostic for (the digest matched
    # just above), and a second record would count one upload twice. A client
    # that commits blind is the one whose attempt would otherwise go unseen.
    _parsed, checked = _checked(
        account,
        platform,
        body.filename,
        raw,
        wipe=body.wipe,
        surface=None if body.expect else body.surface,
    )
    importable = checked.importable
    if not importable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="nothing in this statement is importable",
        )
    origin = platforms.detected_broker(importable) or body.broker.strip()
    if not origin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="this statement names no broker — send one as `broker`",
        )

    if body.wipe:
        # Past the last refusal: the statement is going in, so the book it
        # replaces can go. `clear` takes the demo rows with it.
        clear(account.db)
    else:
        # The first real import is what the demo book was borrowed against: an
        # invented cost basis must never end up mixed into a real one.
        demo.clear(account.db)
    ids = add_many(platforms.stamp_broker(importable, origin), account.db)
    stamped = datetime.now(UTC).isoformat(timespec="seconds")
    last_import.save(
        last_import.ImportRecord(
            filename=body.filename,
            imported_at=stamped,
            tx_ids=ids,
            wiped=body.wipe,
            platform=platform.key,
        ),
        account.last_import,
    )
    # The denominator for every failure rate: without it the logs say how often
    # an import breaks but not out of how many.
    obs.event(
        "import.committed",
        platform=platform.key,
        broker=origin,
        n=len(ids),
        wiped=body.wipe,
        via="api",
    )
    return ImportResult(
        platform=platform.key,
        filename=body.filename,
        imported=len(ids),
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


# ------------------------------------------ splits the book never heard about
# A statement prints trades and not the 20:1 split between them, so a position
# bought before one and never sold keeps a pre-split share count and a pre-split
# cost basis for ever, and reads as a loss nobody took. The import-time rescue
# in validate.py only fires when a *sell* comes up short, and a position nobody
# sold never comes up short — so this repair has to be reachable without an
# import at all.


class SplitGap(BaseModel):
    """One split the ledger is missing, with the evidence that found it.

    The evidence travels with the proposal because the proposal is only worth
    acting on beside it: this holding was bought at `priced_at` on `priced_on`,
    a day whose split-adjusted close was `market_close`, and the quotient of
    those two is a split the ledger never recorded.
    """

    ticker: str
    date: str = Field(description="The split's own day, YYYY-MM-DD.")
    ratio: float = Field(
        description="Shares out per share in — 20.0 for a 20-for-1 split."
    )
    held_before: float | None = Field(
        description="Shares the ledger holds the day before the split."
    )
    held_after: float | None = Field(
        description="Shares it would hold after — what applying this corrects."
    )
    priced_at: float | None = Field(
        description="The pre-split buy price the evidence came from."
    )
    priced_on: str = Field(description="…and that buy's date.")
    market_close: float | None = Field(
        description="Yahoo's split-adjusted close on `priced_on`."
    )
    currency: str = Field(description="What `priced_at` and `market_close` are in.")


class SplitGaps(BaseModel):
    splits: list[SplitGap] = Field(
        default_factory=list, description="Oldest first, the order they apply in."
    )
    throttled: bool = Field(
        default=False,
        description=(
            "Yahoo was refusing this deployment while the scan ran, so an empty "
            "list means 'could not tell' rather than 'nothing missing'. A "
            "throttled lookup answers with silence instead of an error — right "
            "for a page that still has to render, and not enough for a client "
            "about to show a clean bill of health."
        ),
    )


class SplitPick(BaseModel):
    """One scanned split, named by the two fields that identify it."""

    model_config = {"extra": "forbid"}

    ticker: str = Field(min_length=1, max_length=32)
    date: str = Field(
        min_length=10, max_length=10, description="YYYY-MM-DD, as the scan gave it."
    )


class ApplySplits(BaseModel):
    model_config = {"extra": "forbid"}

    splits: list[SplitPick] = Field(
        min_length=1,
        max_length=200,
        description=(
            "Which of the scanned splits to write. Named rather than 'all': the "
            "scan shows its evidence one row at a time, and a reader who "
            "believes one of them and not another has to be able to say so."
        ),
    )


class SplitsApplied(BaseModel):
    applied: int = Field(description="Split rows written.")
    tx_ids: list[int] = Field(
        default_factory=list,
        description="Their ledger ids — `DELETE /v1/portfolio/transactions` "
        "aside, this is the only handle on them afterwards.",
    )
    splits: list[SplitGap] = Field(
        default_factory=list, description="What was written, as the scan described it."
    )


def _gap(gap: corporate.MissingSplit) -> SplitGap:
    return SplitGap(
        ticker=gap.ticker,
        date=gap.tx.date,
        ratio=gap.ratio,
        held_before=_num(gap.held_before),
        held_after=_num(gap.held_after),
        priced_at=_num(gap.priced_at),
        priced_on=gap.priced_on,
        market_close=_num(gap.market_close),
        currency=gap.tx.currency,
    )


def _missing_splits(account) -> list[corporate.MissingSplit]:
    rows = _real_rows(account)
    if not rows:
        return []
    return corporate.missing_splits(
        rows, splits=fetch.splits, close_on=fetch.close_on
    )


@router.get(
    "/splits/scan", response_model=SplitGaps, summary="Splits the ledger is missing"
)
def splits_scan(account: Account) -> SplitGaps:
    """Price this book's holdings against Yahoo and report the splits it lacks.

    A GET although it is the expensive call here — a round-trip per ticker, and
    seconds rather than milliseconds. It takes no body, reads the account's own
    ledger and a public corporate-actions history, and writes nothing, so it is
    safe and idempotent and there is no second thing for a POST to mean.
    Spending "this is not a read" on "this is not cheap" would leave the verb
    saying nothing about either.
    """
    found = _missing_splits(account)
    return SplitGaps(
        splits=[_gap(gap) for gap in found],
        throttled=fetch.throttle_remaining() > 0,
    )


@router.post(
    "/splits/apply", response_model=SplitsApplied, summary="Write the split rows"
)
def splits_apply(account: Writer, body: Annotated[ApplySplits, ...]) -> SplitsApplied:
    """Write the named splits, and only those.

    The body says *which* split, never what it is: the ratio, the date and the
    row that lands in the ledger all come from a scan run here and now. So a
    client cannot invent a 1000-for-1 split by asking for one, and cannot
    replay a stale answer — a split another client applied a second ago is not
    missing any more, and writing it again would square the share count.

    A name this scan does not propose is a 409 and nothing is written, rather
    than a silent skip that would read as success.
    """
    found = {(gap.ticker, gap.tx.date): gap for gap in _missing_splits(account)}
    picked: list[corporate.MissingSplit] = []
    seen: set[tuple[str, str]] = set()
    for pick in body.splits:
        key = (pick.ticker.strip().upper(), pick.date.strip())
        if key in seen:
            continue
        seen.add(key)
        gap = found.get(key)
        if gap is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{key[0]} on {key[1]} is not a split this ledger is missing "
                    "— scan again"
                ),
            )
        picked.append(gap)
    ids = add_many([gap.tx for gap in picked], account.db)
    obs.event("import.splits_applied", n=len(ids), via="api")
    return SplitsApplied(
        applied=len(ids), tx_ids=ids, splits=[_gap(gap) for gap in picked]
    )


# ----------------------------------------- shares that only changed custodian
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

    `loaders.display_symbol` is this API's cached copy of the app's ISIN ->
    symbol lookup, which answers what `web.logos.yahoo_symbol` answers for the
    page. One resolver for one question, or two surfaces offering one repair
    would come to mean two different things by "the same security".
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
    applied = transfers.accept(picked, account.db)
    obs.event("import.moves_applied", n=applied, via="api")
    return MovesApplied(
        applied=applied, moves=[_proposed_move(m) for m in picked]
    )


# -------------------------------------------------------- the example statement
# Shipped beside the app (`web/assets/`), because a reader with no statement to
# hand has nothing to import and therefore nothing to look at.

_ASSETS = Path(__file__).resolve().parents[2] / "web" / "assets"

_SAMPLE_MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get(
    "/sample",
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "The example statement, as a file.",
        }
    },
    summary="An example statement",
)
def sample(
    platform: Annotated[
        str,
        Query(
            description=(
                "Platform key. `has_sample` on `/import/platforms` says which "
                "ship one; today only Revolut does."
            )
        ),
    ],
) -> Response:
    """The shipped example export, byte for byte.

    These bytes go back through `/import/preview` and `/import/commit` like any
    other upload — base64 in the JSON body, the same parse, the same
    validation, the same last-import record and the same undo. That is the
    whole point of shipping a real statement rather than a fabricated ledger: a
    separate "load the demo" route would be the one that drifts from the real
    one, and the reader would learn a flow they will never use again.

    404 both where the platform ships no example and where a trimmed deploy
    left the file out — the page says nothing rather than failing in that
    state, and a client should be able to do the same.

    When to offer it is the client's to get right, and the page's rule is
    worth copying: only to an account with nothing to lose. Committing someone
    else's trades into a real book is a trap rather than a tour, and nothing
    here can tell the two apart. For a reader who has not decided to import
    anything yet, `POST /v1/portfolio/demo` is the other answer.
    """
    chosen = _platform(platform)
    if not chosen.sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{chosen.label} ships no example statement",
        )
    path = _ASSETS / chosen.sample
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this deployment shipped without the example statement",
        )
    return Response(
        content=path.read_bytes(),
        media_type=_SAMPLE_MEDIA.get(
            path.suffix.lstrip(".").lower(), "application/octet-stream"
        ),
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
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
