"""A read statement checked against the ledger, row by row."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

from fastapi import HTTPException, status

from stocks import obs
from stocks.api.routes.import_statement.lookups import (
    LOOKUP_BUDGET_S,
    SPLITS_BUDGET_S,
    _Lookup,
    _within,
)
from stocks.api.routes.import_statement.upload import StatementRow
from stocks.data import fetch, fx, openfigi, symbols
from stocks.data.listing import quote_unit
from stocks.jsonsafe import num as _num
from stocks.portfolio import (
    demo,
    ledger,
    positions,
    transfers,
    venue,
)
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.statement import ParseResult
from stocks.portfolio.validate import known_tickers, validate
from stocks.schemas import (
    ImportIssue,
    ImportRow,
)
from stocks.web import tx_text


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


def _place_isins(isins: set[str]) -> None:
    """Ask OpenFIGI for every ISIN of the statement in one batched request,
    so the per-code lookups after it (`symbols.symbol_for_code`, run in
    parallel) find their listings cached instead of each making a request.
    Bounded like every lookup here; a throttled or offline OpenFIGI leaves the
    lookups on Yahoo, as they were."""
    if isins:
        _within(lambda: openfigi.securities(isins), LOOKUP_BUDGET_S, None)


def _validated(account, parsed: ParseResult, *, wipe: bool = False):
    """Validate a read against this account's own ledger and watchlist.

    `wipe` empties the baseline rather than the book: a statement that is about
    to replace the ledger has to be read against the ledger it will leave
    behind, or every row it re-imports comes back flagged as a duplicate of one
    that is on its way out.

    Validated with the two live lookups (`_Lookup`, `_splits`). An ISIN the
    cached map resolves is known without asking Yahoo, which quotes symbols,
    not ISINs.

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
    _place_isins(
        set(parsed.isins.values()) | {t for t in currencies if symbols.is_isin(t)}
    )
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
