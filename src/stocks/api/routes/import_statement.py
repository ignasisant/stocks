"""Turning a broker statement into ledger rows, over HTTP.

The flow the page has always had: upload, read (writing nothing), validate
against the ledger, look at the tiers, commit. Split here into a preview and a
commit, because the safety property is that a reader — or a client — sees what
a file will do before it does it.

**The model reads first, and the parsers check it.** Every statement goes to
the column mapper (`portfolio.llm_map`) and to every parser that takes its
extension, and `autodetect.read` keeps whichever read more of it — a parser on
a tie, because a parser that owns the layout is exact where a model is only
likely. The platform the page's picker names is tried first and trusted no
further: a Revolut PDF whose layout moved under its parser still imports, read
by the model, instead of arriving as "0 rows", and the preview says who read
it. The chat's attachment runs this same read and this same validation
(`chat_attach` takes both from here), so a file that imports on one surface
imports on the other.

**The file arrives as base64 in a JSON body, not as multipart.** That is a
deliberate choice and not an oversight: a cross-site HTML form *can* send
multipart, so accepting it would hand back the CSRF hole that every other write
here avoids by requiring `application/json`. The ~33% encoding overhead is
nothing against a statement.

**Commit re-validates the rows it was shown.** Reading the file again would
be a second model call, whose answer can differ from the one previewed, on
whichever instance the request lands on rather than the one that remembers the
first. So a client sends back the preview's rows — which it could always do by
uploading them as a generic CSV — and they are rebuilt through the ledger's
`Transaction` and validated again against the ledger as it is now: the ledger
moves, and a row that was importable ten seconds ago may be a duplicate of one
another client just committed. A commit that sends the file instead is read
again (the model's answer is remembered for a few minutes per account, so this
is usually the preview's own read); `expect` lets it assert the bytes are the
ones it previewed. Nothing lets either assert the ledger is.

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
from concurrent.futures import ThreadPoolExecutor, wait
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from stocks import obs
from stocks.analysis.listing import quote_unit
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
from stocks.data import fetch, fx, symbols
from stocks.portfolio import (
    autodetect,
    corporate,
    demo,
    diagnostics,
    last_import,
    ledger,
    llm_map,
    platforms,
    positions,
    transfers,
    venue,
)
from stocks.portfolio.ledger import add_many, all_transactions, clear, delete_many
from stocks.portfolio.statement import ParseResult
from stocks.portfolio.validate import known_tickers, validate
from stocks.web import tx_text

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
    follows a preview does not pay for a second model call."""
    provider, api_key = _provider(account, held)
    return autodetect.read(
        filename,
        raw,
        provider,
        api_key,
        prefer=prefer,
        mapping=mapping,
        scope=str(account.db),
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
_UNANSWERED = object()  # a search `_within` gave up on, told apart from "no"
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


def _charted(ticker: str, budget: float) -> bool | None:
    """Does Yahoo have bars for this symbol? Its own last word on a code.

    The quote check cannot always say: yfinance 1.7 raises the same KeyError
    on a symbol Yahoo has no quote for as on a reply it could not read. The
    bulk download can — it hears Yahoo's 404 reason, "No data found", and
    files the code under `fetch.unlisted`, the verdict the price pass reaches
    on the book. Five days of bars, asked only once nothing else could place
    the code. None when the download did not finish or Yahoo is throttled.
    """
    if budget <= 0 or fetch.throttle_remaining() > 0:
        return None
    priced = _within(
        lambda: fetch.fetch_many([ticker], period="5d", budget=budget),
        budget,
        None,
        ticker=ticker,
    )
    if priced is None:
        return None
    if ticker in priced:
        return True
    return False if fetch.unlisted({ticker}) else None


class _Lookup:
    """`validate`'s `lookup`, bounded: one instance per statement.

    The batch deadline starts when the instance is made, so a statement of two
    hundred unfamiliar symbols spends at most `BATCH_BUDGET_S` finding out
    which of them trade, and the rest stay "could not check".

    A symbol the price pass already heard Yahoo disown (`fetch.unlisted`) is
    answered False without asking again: that verdict came from the download
    that prices the book, which is the one that matters.

    Anything short of a quote is not the last word, though. A bare code Yahoo
    does not quote is usually a European line printed without its venue —
    Revolut's SIE is Yahoo's SIE.DE — so the code is looked up in Yahoo's
    search, on the venues its trade currency (`currencies`) trades on
    (`symbols.symbol_for_code`). That includes a quote check that could not
    say: yfinance 1.7 raises on a symbol it has no quote for (KeyError
    'currentTradingPeriod') rather than answering empty, which reads as None,
    and a statement of nine euro codes then warned on every row without the
    search ever being asked. A hit is remembered for good, so the price
    download resolves the code through it (`fetch.resolve`) and the row is
    known. `disowned` collects what is still False after that, so the preview
    can name the rows that will import unpriced.

    Answers are kept per instance: validation asks once per row, and a code a
    statement trades nine times would otherwise spend nine quote checks of the
    one budget.

    The search is told what the statement knows of each code, so it can land
    on the issuer's home line rather than a German regional floor (MEQA is
    MRL.MC in Madrid, not MEQA.F): the ISIN the statement prints beside it
    (`isins`), and the code's fills (`samples`), which a line found by name
    has to have closed near (`venue.agrees`). `home` asks the same of the
    codes the map already holds on a floor.
    """

    def __init__(
        self,
        currencies: dict[str, str] | None = None,
        isins: dict[str, str] | None = None,
        samples: dict[str, list[tuple[str, float]]] | None = None,
    ) -> None:
        self.deadline = time.monotonic() + BATCH_BUDGET_S
        self.currencies = currencies or {}
        self.isins = isins or {}
        self.samples = samples or {}
        self.disowned: set[str] = set()
        self.answers: dict[str, bool | None] = {}

    def __call__(self, ticker: str) -> bool | None:
        if ticker in self.answers:
            return self.answers[ticker]
        answer = self._ask(ticker)
        if answer is not True:
            listed = self._listed(ticker)
            # A venue found is a listing whatever the quote check said; no
            # venue only confirms a False — it cannot turn "could not ask"
            # into "unlisted". The chart can: a code nothing placed is asked
            # once more, of the download that will price it.
            if listed or (listed is None and answer is False):
                answer = listed
            elif listed is False and answer is None:
                answer = _charted(
                    ticker, min(LOOKUP_BUDGET_S, self.deadline - time.monotonic())
                )
        if answer is False:
            self.disowned.add(ticker)
        self.answers[ticker] = answer
        return answer

    def _listed(self, ticker: str) -> bool | None:
        """Whether the search places this code on a venue (SIE -> SIE.DE).

        None when the search ran out of time: its thread still finishes into
        the cache, so the next preview may know, and "unpriced" would be a
        verdict nobody reached.
        """
        if symbols.code_symbol(ticker):
            return True
        left = self.deadline - time.monotonic()
        if left <= 0:
            return False
        found = _within(
            lambda: self._search(ticker),
            min(LOOKUP_BUDGET_S, left),
            _UNANSWERED,
            ticker=ticker,
        )
        return None if found is _UNANSWERED else bool(found)

    def home(self) -> None:
        """Ask for the home line of each code here the map holds on a floor.

        `__call__` only reaches codes the book does not know, and a code
        imported before the search looked past the floors is known: without
        this its MEQA.F would stand for good. All at once, within one lookup's
        budget; a search still running then finishes into the map, and one
        that could not decide is asked again by the next statement.
        """
        floored = [
            ticker
            for ticker in self.currencies
            if symbols.on_floor(symbols.code_symbol(ticker) or "")
        ]
        left = self.deadline - time.monotonic()
        if not floored or left <= 0:
            return
        pool = ThreadPoolExecutor(max_workers=min(len(floored), _HOME_WORKERS))
        try:
            asked = [pool.submit(self._search, ticker) for ticker in floored]
            wait(asked, timeout=min(LOOKUP_BUDGET_S, left))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _search(self, ticker: str) -> str | None:
        currency = self.currencies.get(ticker, "")
        samples = self.samples.get(ticker)

        def vet(symbol: str) -> bool | None:
            return venue.agrees(symbol, samples or [], currency, _close)

        return symbols.symbol_for_code(
            ticker,
            currency,
            isin=self.isins.get(ticker, ""),
            vet=vet if samples else None,
        )

    def _ask(self, ticker: str) -> bool | None:
        if fetch.unlisted({ticker}):
            return False
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


_HOME_WORKERS = 4


def _close(symbol: str, day: str) -> float | None:
    """`fetch.close_on`, bounded, and not asked of a throttled host."""
    if fetch.throttle_remaining() > 0:
        return None
    return _within(
        lambda: fetch.close_on(symbol, day), LOOKUP_BUDGET_S, None, ticker=symbol
    )


def _splits(ticker: str) -> list[tuple[str, float]]:
    """`fetch.splits`, bounded. Already memoized and throttle-aware there; the
    budget is the one thing it lacks for a caller holding a worker thread."""
    return _within(lambda: fetch.splits(ticker), SPLITS_BUDGET_S, [], ticker=ticker)


def _row(checked, gain: float | None = None) -> ImportRow:
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
        gain=gain,
    )


def _skipped(skip: dict) -> dict:
    """A parser's skip, with the catalog stem that names its reason and whether
    it leaves the reader a step to take — the `key` an issue carries, for a
    reason that is otherwise only the parser's English."""
    stem, manual = tx_text.skip_reason(str(skip.get("reason", "")))
    return {**skip, "reason_key": stem, "manual": manual}


QUOTES_BUDGET_S = 4.0  # today's prices for the buys' gain; the preview waits no longer


def _native(amount: float, currency: str, day: str) -> float:
    """`positions.build`'s converter, converting nothing: a sale's gain is read
    in the currency it traded in, so the replay needs no rate and no network."""
    return amount


def _realized(book: list) -> dict[tuple[str, str], tuple[float, float]]:
    """(label, sale day) -> (cost, proceeds) of what that day's sales realized.

    FIFO, as the app's own analytics replay. One security at a time, so a sale
    the book cannot cover — a statement that starts after the shares were
    bought elsewhere — loses that security's answer and nobody else's; and only
    a security traded in one currency, because `_native` would add a dollar
    cost to a euro one without a word.
    """
    groups: dict[str, list] = {}
    for tx in transfers.relabel(book):
        groups.setdefault(tx.ticker, []).append(tx)
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for group in groups.values():
        if len({tx.currency for tx in group}) != 1:
            continue
        try:
            _, sales = positions.build(group, to_base=_native, matching="fifo")
        except ValueError:
            continue
        for sale in sales:
            key = (sale.ticker, sale.sell_date)
            cost, proceeds = out.get(key, (0.0, 0.0))
            out[key] = (cost + sale.cost, proceeds + sale.proceeds)
    return out


def _gains(rows: list, prior: list, prices: dict[str, dict]) -> list[float | None]:
    """How each preview row has done, as a fraction; None where it cannot say.

    A buy against today's quote (`prices`, `session_quotes` snapshots), its
    fee in the cost as the book counts it — and only when the quote is in the
    row's own currency, minor units resolved (`quote_unit`): a London line
    quoted in pence beside a buy in pounds is a hundredfold, not a gain. A sale
    against the cost it realized, replayed over the book it lands in plus this
    batch (`_realized`); two sales of one security on one day share a figure.
    Every other action has no gain to show.
    """
    book = prior + [c.tx for c in rows if not c.duplicate]
    # The replay speaks in one label per security (an ISIN row becomes its
    # symbol), so each row is looked up under the label it replayed as.
    label = {
        tx.ticker: moved.ticker
        for tx, moved in zip(book, transfers.relabel(book), strict=True)
    }
    realized = _realized(book)
    out: list[float | None] = []
    for checked in rows:
        tx = checked.tx
        gain = None
        if tx.action == "buy":
            quote = prices.get(tx.ticker) or {}
            have, unit = quote_unit(quote.get("currency"))
            paid, scale = quote_unit(tx.currency)
            cost = (tx.quantity * tx.price + tx.fee) * scale
            if quote.get("price") and have == paid and cost > 0:
                gain = tx.quantity * quote["price"] * unit / cost - 1
        elif tx.action == "sell":
            key = (label.get(tx.ticker, tx.ticker), tx.date)
            cost, proceeds = realized.get(key, (0.0, 0.0))
            if cost > 0:
                gain = proceeds / cost - 1
        out.append(_num(gain))
    return out


def _real_rows(account) -> list:
    """The account's own transactions, without the demo book.

    Every repair and every validation here reads this rather than the raw
    table. The demo rows are fabricated and the next commit deletes them, so
    counting them as prior holdings would validate a real statement against
    lots that are about to stop existing, and would offer to repair a split on
    a position nobody owns.
    """
    return demo.without(all_transactions(account.db))


RELABEL_BUDGET_S = 12.0  # every listing check one statement makes, together
_RELABEL_WORKERS = 4


def _relabels(rows: list, prior: list) -> dict[tuple[str, str], str]:
    """The bare codes this batch, or the book it lands in, really traded as.

    `venue.pick` per code, with every question it asks bounded like the
    lookups above: the per-call budget, one deadline for the statement, and
    nothing asked of a throttled host. A code still undecided at the deadline
    stays as printed — see `stocks.portfolio.venue` for why that is safe.
    """
    keys = venue.keys(rows, prior)
    if not keys:
        return {}
    asker = _Lookup()
    asker.deadline = time.monotonic() + RELABEL_BUDGET_S

    def left() -> float:
        return asker.deadline - time.monotonic()

    def quoted(code: str) -> bool:
        # A code watchlist.yaml (or an earlier search) already maps is
        # priced as that answer; the hand-written one wins.
        return fetch.resolve(code) == code and asker._ask(code) is True

    def candidates(code: str, currency: str) -> list[str]:
        if left() <= 0:
            return []
        return _within(
            lambda: symbols.listings_for_code(code, currency),
            min(LOOKUP_BUDGET_S, left()),
            [],
            ticker=code,
        )

    def close(symbol: str, day: str) -> float | None:
        if left() <= 0 or fetch.throttle_remaining() > 0:
            return None
        return _within(
            lambda: fetch.close_on(symbol, day),
            min(LOOKUP_BUDGET_S, left()),
            None,
            ticker=symbol,
        )

    def usd_rate(currency: str, day: str) -> float | None:
        if left() <= 0:
            return None
        return _within(
            lambda: fx.rate_on(day, "USD", currency),
            min(LOOKUP_BUDGET_S, left()),
            None,
            ticker=currency,
        )

    pool = ThreadPoolExecutor(max_workers=_RELABEL_WORKERS)
    try:
        asked = {
            pool.submit(
                venue.pick,
                key,
                rows,
                prior,
                quoted=quoted,
                candidates=candidates,
                close=close,
                usd_rate=usd_rate,
            ): key
            for key in keys
        }
        done, _ = wait(asked, timeout=RELABEL_BUDGET_S)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    moved: dict[tuple[str, str], str] = {}
    for future in done:
        if future.exception() is not None:
            obs.warn(
                "api.import_relabel_failed",
                error_type=type(future.exception()).__name__,
                ticker=asked[future][0],
            )
        elif symbol := future.result():
            moved[asked[future]] = symbol
    if moved:
        obs.event(
            "api.import_relabeled",
            n=len(moved),
            codes=sorted(f"{c}/{cur}->{s}" for (c, cur), s in moved.items()),
        )
    return moved


def _retag(db: Path, moved: dict[tuple[str, str], str]) -> int:
    """Move the book's own rows of each relabeled code to its listing.

    Called after the batch is written and only then: a commit that writes
    nothing (refused, or every row a duplicate) leaves the book as it found
    it, and the next import that writes asks again.
    """
    return sum(
        ledger.retag(code, symbol, db, currency=currency)
        for (code, currency), symbol in moved.items()
    )


def _validated(account, parsed: ParseResult, *, wipe: bool = False):
    """Validate a read against this account's own ledger and watchlist.

    `wipe` empties the baseline rather than the book: a statement that is about
    to replace the ledger has to be read against the ledger it will leave
    behind, or every row it re-imports comes back flagged as a duplicate of one
    that is on its way out.

    Validated with the Streamlit page's two live lookups (`_Lookup`, `_splits`)
    — without them the same statement read clean on one surface and warned or
    rejected on the other. An ISIN the cached map resolves is known without
    asking Yahoo, which quotes symbols, not ISINs.

    `known` loses whatever Yahoo has disowned since: a bare broker code that
    is already in the ledger would otherwise pass as known on every later
    statement, and hold at cost with no price and no warning, forever.

    A bare code traded outside dollars is read under the listing its price
    says it was traded on (`_relabels`: Revolut's euro ALV is ALV.DE), in the
    statement and in the baseline alike, so a re-import still finds its
    duplicates. `parsed` is relabeled in place, split rows included; the
    commit moves the book's rows to match (`Validation.relabeled`, `_retag`).

    Returns the validation and the tickers Yahoo said it does not list
    (`_Lookup.disowned`).
    """
    prior = [] if wipe else _real_rows(account)
    known = known_tickers(account.watchlist, account.db)
    known -= fetch.unlisted(known)
    moved = _relabels(parsed.transactions, prior)
    if moved:
        parsed.transactions = venue.relabeled(parsed.transactions, moved)
        venue.relabel_skipped(parsed.skipped, moved)
        prior = venue.relabeled(prior, moved)
        known |= set(moved.values())
    currencies: dict[str, str] = {}
    for tx in parsed.transactions:
        currencies.setdefault(tx.ticker, tx.currency)
    samples = {
        ticker: venue.samples((ticker, currency), parsed.transactions)
        for ticker, currency in currencies.items()
    }
    lookup = _Lookup(currencies, parsed.isins, samples)
    lookup.home()

    def listed(ticker: str) -> bool | None:
        if symbols.is_isin(ticker) and symbols.symbol_for_isin(ticker):
            return True
        return lookup(ticker)

    validation = validate(parsed, prior, known=known, lookup=listed, splits=_splits)
    validation.relabeled = moved
    return validation, lookup.disowned


def _statement_row(row: StatementRow) -> ledger.Transaction:
    """One client row as a ledger row, or a 422 naming what is wrong with it.

    `Transaction` refuses an action it does not know, which is the only field
    here whose values are a closed set — everything else is text and numbers
    the ledger has always taken from a parser.
    """
    try:
        return ledger.Transaction(
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
    found = _read(
        account,
        body.filename,
        raw,
        held=_held(x_chat_provider, x_chat_key),
        prefer=prefer,
    )
    why = _unreadable(found)
    if why:
        diagnostics.report(
            found.platform, body.filename, raw, found.result, surface=body.surface
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=why
        )
    checked, disowned = _validated(account, found.result, wipe=body.wipe)
    # The anonymised record the page files for every outcome, which is what
    # turns "some brokers fail" into a queryable fact.
    diagnostics.report(
        found.platform, body.filename, raw, found.result, checked,
        surface=body.surface,
    )
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
        digest=hashlib.sha256(raw).hexdigest(),
        importable=[_row(c, gain) for c, gain in zip(rows, gains, strict=True)],
        rejected=[_row(c) for c in checked.rejected],
        duplicates=len(checked.duplicates),
        skipped=[_skipped(s) for s in found.result.skipped],
        broker=detected,
        needs_broker=bool(importable) and not detected,
        unlisted=sorted(disowned & {c.tx.ticker for c in rows}),
    )


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
    diagnostics.client_failure(
        body.platform, body.filename, body.bytes, body.error, body.message
    )


@router.post("/commit", response_model=ImportResult, summary="Write the rows")
def commit(
    caller: Authed,
    account: Writer,
    body: Annotated[Commit, ...],
    x_chat_provider: str | None = Header(default=None),
    x_chat_key: str | None = Header(default=None),
) -> ImportResult:
    """Validate and append the importable rows.

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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="wipe_confirm must be the signed-in address, exactly",
        )
    raw, report = b"", False
    if body.rows is not None:
        parsed = ParseResult(transactions=[_statement_row(r) for r in body.rows])
        read_by = prefer or autodetect.LLM_KEY
    else:
        raw = _decode(body)
        digest = hashlib.sha256(raw).hexdigest()
        if body.expect and body.expect != digest:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this is not the file that was previewed",
            )
        found = _read(
            account,
            body.filename,
            raw,
            held=_held(x_chat_provider, x_chat_key),
            prefer=prefer,
        )
        # Reported only when no preview was claimed: a commit carrying
        # `expect` is of bytes its preview already filed a diagnostic for (the
        # digest matched just above), and a second record would count one
        # upload twice. A client that commits blind is the one whose attempt
        # would otherwise go unseen.
        report = not body.expect
        why = _unreadable(found)
        if why:
            if report:
                diagnostics.report(
                    found.platform, body.filename, raw, found.result,
                    surface=body.surface,
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=why
            )
        parsed, read_by = found.result, found.platform
    checked, _disowned = _validated(account, parsed, wipe=body.wipe)
    if report:
        diagnostics.report(
            read_by, body.filename, raw, parsed, checked, surface=body.surface
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
    if ids:
        _retag(account.db, checked.relabeled)
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
        via="api",
    )
    return ImportResult(
        platform=read_by,
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


# ------------------------------------------- the line a code was traded on
# A code the search could not place anywhere imports unpriced, held at cost
# (`ImportPreview.unlisted`). The reader usually knows the security, though:
# they name it ("Merlin"), are shown the lines that name finds on the code's
# currency's venues, each priced on the days their fills were, and pick one.
# The pick is the code's answer in `CODE_CACHE`, which is one map for every
# account, so it is held to what a search answer would be: a real line on
# those venues that closed near the fills, for a code nothing answers yet.

VENUES_BUDGET_S = 10.0  # every option's closes, together
_VENUE_WORKERS = 6


class VenueFill(BaseModel):
    """One trade of the code, as the preview showed it."""

    model_config = {"extra": "forbid"}

    date: str = Field(min_length=10, max_length=32, description="YYYY-MM-DD…")
    price: float = Field(gt=0, description="Per share, in the code's currency.")


class VenueAsk(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(
        min_length=1, max_length=32, description="As the statement prints it."
    )
    currency: str = Field(min_length=3, max_length=4)
    fills: list[VenueFill] = Field(
        min_length=1,
        max_length=500,
        description="The preview's trades of the code; its latest two days count.",
    )
    query: str = Field(
        default="",
        max_length=80,
        description="The security's name as the reader puts it; the code when empty.",
    )


class VenueOption(BaseModel):
    symbol: str
    name: str
    exchange: str
    close: float | None = Field(
        description="Its close on `VenueOptions.day`; null when Yahoo could not say."
    )
    agrees: bool | None = Field(
        description=(
            "Closed near the fills on every sampled day; null when no sampled day "
            "has a close. Only a true one can be picked."
        )
    )


class VenueOptions(BaseModel):
    code: str
    currency: str
    day: str = Field(description="The latest fill's day, the one `close` is on.")
    price: float = Field(description="The fill on `day`.")
    options: list[VenueOption] = Field(default_factory=list)
    throttled: bool = Field(
        default=False,
        description="Yahoo was refusing this host, so a null `close` is not a verdict.",
    )


class VenuePick(VenueAsk):
    symbol: str = Field(min_length=1, max_length=32)


class VenuePicked(BaseModel):
    code: str
    symbol: str


def _venue_key(code: str) -> str:
    return code.strip().upper()


def _option(line: tuple[str, str, str], sampled, currency: str) -> VenueOption:
    symbol, name, exchange = line
    return VenueOption(
        symbol=symbol,
        name=name,
        exchange=exchange,
        close=_num(_close(symbol, sampled[0][0])),
        agrees=venue.agrees(symbol, sampled, currency, _close),
    )


@router.post("/venues", response_model=VenueOptions, summary="Lines a code could be")
def venues(account: Writer, body: Annotated[VenueAsk, ...]) -> VenueOptions:
    """The lines `query` finds on the code's currency's venues, each priced on
    the days the code was traded.

    A POST because the fills travel in the body; it writes nothing. Every
    option's closes are asked at once within `VENUES_BUDGET_S`, and one still
    out then comes back unpriced rather than holding the others.
    """
    del account  # a session, like every other non-GET here
    sampled = venue.latest((fill.date, fill.price) for fill in body.fills)
    currency = body.currency.strip().upper()
    lines = symbols.lines_for(body.query.strip() or body.code, currency)
    options: list[VenueOption] = []
    if lines:
        pool = ThreadPoolExecutor(max_workers=min(len(lines), _VENUE_WORKERS))
        try:
            asked = [pool.submit(_option, line, sampled, currency) for line in lines]
            wait(asked, timeout=VENUES_BUDGET_S)
            for line, future in zip(lines, asked, strict=True):
                done = future.done() and not future.exception()
                options.append(
                    future.result()
                    if done
                    else VenueOption(
                        symbol=line[0],
                        name=line[1],
                        exchange=line[2],
                        close=None,
                        agrees=None,
                    )
                )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    return VenueOptions(
        code=_venue_key(body.code),
        currency=currency,
        day=sampled[0][0],
        price=sampled[0][1],
        options=options,
        throttled=fetch.throttle_remaining() > 0,
    )


@router.post("/venue", response_model=VenuePicked, summary="The line a code is")
def venue_pick(account: Writer, body: Annotated[VenuePick, ...]) -> VenuePicked:
    """Remember `symbol` as the code's line, for every price lookup after.

    Checked here, not believed, because the map is every account's: the code
    has to be one nothing prices — no alias, no map answer, no bare quote, and
    a search that still cannot place it — and the symbol a line of the code's
    currency's venues that closed near the fills on the days they were made
    (`venue.agrees`, priced now). Anything else is a 409 and nothing is
    written; a Yahoo that could not be asked is a 503, to try again.
    """
    del account  # a session, like every other non-GET here
    code = _venue_key(body.code)
    symbol = body.symbol.strip().upper()
    currency = body.currency.strip().upper()

    def refuse(detail: str, kind: int = status.HTTP_409_CONFLICT):
        return HTTPException(status_code=kind, detail=detail)

    held = fetch.resolve(code)
    if held != code:
        raise refuse(f"{code} is already priced as {held}")
    if not fetch.unlisted({code}):
        quoted = _within(lambda: _ticker_exists(code), LOOKUP_BUDGET_S, None, ticker=code)
        if quoted is None:
            quoted = _charted(code, LOOKUP_BUDGET_S)
        if quoted is None:
            raise refuse("Yahoo could not be asked", status.HTTP_503_SERVICE_UNAVAILABLE)
        if quoted:
            raise refuse(f"Yahoo quotes {code} as it is")
    found = _within(
        lambda: symbols.symbol_for_code(code, currency),
        LOOKUP_BUDGET_S,
        _UNANSWERED,
        ticker=code,
    )
    if found is _UNANSWERED:
        raise refuse("Yahoo could not be asked", status.HTTP_503_SERVICE_UNAVAILABLE)
    if found:
        raise refuse(f"{code} is priced as {found} now")
    if not symbols.on_venues(symbol, currency):
        raise refuse(f"{symbol} is not a {currency} line")
    sampled = venue.latest((fill.date, fill.price) for fill in body.fills)
    if venue.agrees(symbol, sampled, currency, _close) is not True:
        raise refuse(f"{symbol} did not close near {code}'s fills")
    symbols.remember_code(code, symbol)
    fetch.relisted(code)
    obs.event("import.venue_picked", code=code, symbol=symbol)
    return VenuePicked(code=code, symbol=symbol)


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
