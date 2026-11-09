"""What the book holds: positions, totals, and the ledger rows behind them."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response, status

from stocks import loaders, obs
from stocks.analysis.portfolio import (
    market_active,
    market_live,
    positions_frame,
    priced_totals,
    value_weights,
)
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.paging import Page, page
from stocks.cache import carried, ttl_cache
from stocks.data import fetch
from stocks.jsonsafe import num as _num
from stocks.portfolio import demo, edits
from stocks.portfolio.custody import UNKNOWN as BROKER_UNKNOWN
from stocks.portfolio.custody import mix as custody_mix
from stocks.portfolio.platforms import broker_label
from stocks.schemas import (
    Custodian,
    Position,
    Positions,
    Summary,
    Transaction,
    Transactions,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _day_moves(
    db: str, ccy: str, table: pd.DataFrame
) -> dict[str, tuple[float | None, float | None]]:
    """{ticker: (today's move in `ccy`, as a fraction)} for the table's rows.

    The last two rows of the fixed-quantity basket (so the FX move is in it,
    and a deposit is not), then — for every name whose own exchange is shut —
    the session quote takes over, because the newest daily bar is stale or
    flat there and would print the "+0.00% today" a reader gets at eight in
    the morning. The money figure is re-derived from the row's own value so
    the amount and the percentage are always the same move.

    Best effort, and never the reason the table fails: the positions are the
    ledger's and their value is already priced; a throttled basket or quote
    burst leaves the day columns null ("n/a"), not the whole response a 503.
    """
    out: dict[str, tuple[float | None, float | None]] = {}
    with obs.swallow("api.positions_day"):
        mtime = loaders.db_mtime(db)
        frame = loaders.basket_values(db, mtime, ccy)
        if len(frame) >= 2:
            last, prev = frame.iloc[-1], frame.iloc[-2]
            for ticker in frame.columns:
                a, b = last.get(ticker), prev.get(ticker)
                if pd.notna(a) and pd.notna(b) and b:
                    out[str(ticker)] = (float(a - b), float(a / b - 1))
        off = tuple(str(t) for t in table.index if not market_live(str(t)))
        quotes = loaders.quotes(off) if off else {}
        for ticker, quote in quotes.items():
            pct = quote.get("pct")
            if ticker not in table.index or pct is None or pd.isna(pct):
                continue
            value = table.at[ticker, "value"]
            amount = (
                float(value) * float(pct) / (1 + float(pct))
                if pd.notna(value) and pct != -1
                else None
            )
            out[ticker] = (amount, float(pct))
    return out


def _custodians(brokers: dict) -> list[Custodian]:
    """One position's custody, largest share first, ready to print.

    No logo: the table prints names, and resolving a brand image per row would
    put a mirror fetch on the path of the page's first paint. `name` is empty
    for the two generic buckets, which the client words from its catalog — the
    same contract as the ticker header's marks.
    """
    return [
        Custodian(
            broker=key,
            name="" if key in ("manual", BROKER_UNKNOWN) else broker_label(key),
            shares=float(brokers[key].quantity),
            share=float(share),
        )
        for key, share in custody_mix(brokers)
    ]


@router.get("/positions", response_model=Positions, summary="Open positions")
def positions(
    account: Account,
    base: Base = None,
    priced: Annotated[
        bool,
        Query(
            description=(
                "false: the rows the ledger alone can answer — shares, cost, "
                "currency, custody — with every price field null, and no "
                "network. What a table draws while the priced call is out."
            )
        ),
    ] = True,
) -> Positions:
    ccy = reporting_currency(account, base)
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    if priced:
        table = loaders.positions_table(db, mtime, ccy)
    else:
        # `values={}` is "priced at nothing": the frame keeps its shape with
        # NaN values, and `positions_frame` never reaches for a quote.
        table = positions_frame(
            loaders.ledger_state(db, mtime, ccy).positions, base=ccy, values={}
        )
    if table.empty:
        return Positions(base=ccy, positions=[], unpriced=0)
    weights = value_weights(table)
    # One spot per currency, not per position, and read back out of the value
    # the price pass already fetched — a second quote per name to print a share
    # price is how a page gets itself throttled.
    # Two network reads that need nothing from each other, side by side: the
    # table costs the slower of them rather than their sum.
    pool = ThreadPoolExecutor(max_workers=2)
    spots = (
        pool.submit(
            carried(loaders.spot_rates),
            tuple(sorted({str(c).upper() for c in table["ccy"] if c})),
            ccy,
        )
        if priced
        else None
    )
    day = pool.submit(carried(_day_moves), db, ccy, table) if priced else None
    pool.shutdown(wait=False)
    held = loaders.custody(db, loaders.db_mtime(db))
    rates = spots.result() if spots else {}
    moves = day.result() if day else {}
    rows = [
        Position(
            ticker=str(ticker),
            shares=float(row["shares"]),
            currency=str(row["ccy"]),
            cost=float(row["cost"]),
            value=_num(row["value"]),
            price=loaders.native_price(row, rates),
            pnl=_num(row["pnl"]),
            pnl_pct=_num(row["pnl_pct"]),
            weight=_num(weights.get(ticker)),
            day=_num(moves.get(str(ticker), (None, None))[0]),
            day_pct=_num(moves.get(str(ticker), (None, None))[1]),
            market_active=market_active(str(ticker)),
            custody=_custodians(held.get(str(ticker), {})),
        )
        for ticker, row in table.iterrows()
    ]
    return Positions(
        base=ccy,
        positions=rows,
        unpriced=int(table["value"].isna().sum()),
        demo=demo.active(account.db),
    )


def _unpriced_tickers(table: pd.DataFrame) -> list[str]:
    """The rows `priced_totals` left out, by name."""
    if "value" not in table:
        return [str(t) for t in table.index]
    return [str(t) for t in table.index[table["value"].isna()]]


def _unpriced_cost(table: pd.DataFrame) -> float:
    """Basis of the rows `priced_totals` left out."""
    if table.empty or "cost" not in table:
        return 0.0
    if "value" not in table:
        return float(table["cost"].sum())
    return float(table.loc[table["value"].isna(), "cost"].sum())


def _stale_tickers(table: pd.DataFrame) -> list[str]:
    """Rows valued at the last kept close (`loaders._self_priced_positions`)."""
    if "stale" not in table:
        return []
    return sorted(str(t) for t in table.index[table["stale"].fillna(False).astype(bool)])


@router.get("/summary", response_model=Summary, summary="Book totals")
def summary(account: Account, base: Base = None) -> Summary:
    """Cost, value and P/L over the rows that priced.

    Both sums come from the same rows on purpose (`priced_totals`): summing the
    whole book's basis against a partial market value mixes denominators and
    renders an intact book at -60%. `unpriced` is how many positions were left
    out of both.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    table = loaders.positions_table(db, loaders.db_mtime(db), ccy)
    cost, value, unpriced = priced_totals(table)
    # The closed side of the same book, off the replay this loader already
    # holds. Deliberately FIFO and deliberately in the reporting currency:
    # `/portfolio/tax` answers the other question — what a jurisdiction
    # considers realized, under its own matching rule and its own currency —
    # and the two numbers are not interchangeable for anyone but an EUR-
    # reporting FIFO filer.
    _txs, _open, sales = loaders.ledger_state(db, loaders.db_mtime(db), ccy)
    return Summary(
        base=ccy,
        cost=cost,
        value=value,
        pnl=value - cost,
        pnl_pct=_num(value / cost - 1) if cost else None,
        positions=int(len(table)),
        unpriced=unpriced,
        unpriced_cost=_unpriced_cost(table),
        stale=_stale_tickers(table),
        # Which of the unpriced are a code Yahoo does not know, rather than a
        # feed that is down: those need an alias, and waiting will not help.
        unlisted=sorted(fetch.unlisted(_unpriced_tickers(table))) if unpriced else [],
        # Null, not zero, for a book that never sold: "no result" and "broke
        # even" are different facts and the tile has to be able to say so.
        realized=(_num(sum(s.proceeds - s.cost for s in sales)) if sales else None),
        realized_cost=_num(sum(s.cost for s in sales)) if sales else None,
        demo=demo.active(account.db),
    )


@router.get("/transactions", response_model=Transactions, summary="Ledger rows")
def transactions(
    account: Account,
    paging: Annotated[Page, page(200, 1000)],
    base: Base = None,
    ticker: Annotated[
        str,
        Query(
            max_length=40,
            description=(
                "The security, however it is known: the stored label, the "
                "label a transfer unifies it under, or the bare symbol across "
                "venues (`GRF` finds `GRF.MC`)."
            ),
        ),
    ] = "",
    broker: Annotated[
        str, Query(max_length=40, description="The note's first word, e.g. `ibkr`.")
    ] = "",
    action: Annotated[str, Query(max_length=20)] = "",
    since: Annotated[
        str, Query(alias="from", max_length=10, description="ISO date, inclusive.")
    ] = "",
    until: Annotated[
        str, Query(alias="to", max_length=10, description="ISO date, inclusive.")
    ] = "",
) -> Transactions:
    """The ledger, newest first, paged, optionally narrowed.

    Raw rows as imported — not relabelled and not netted. A caller reconciling
    against a broker statement wants exactly what is stored; the analytics
    endpoints are where transfers get unified into one position. The filters
    only choose rows; `total` counts the rows they chose.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    txs = loaders.ledger_state(db, loaders.db_mtime(db), ccy).txs
    wanted = edits.Selector(
        ticker=ticker, broker=broker, action=action, since=since, until=until
    )
    if not wanted.empty():
        txs = edits.select(txs, wanted)
    ordered = sorted(txs, key=lambda t: (t.date, t.id or 0), reverse=True)
    rows = paging.apply(ordered)
    return Transactions(
        total=len(txs),
        base=ccy,
        demo=demo.active(account.db),
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
                amount=_cash_in(t, ccy),
            )
            for t in rows
        ],
    )


def _cash_in(t, ccy: str) -> float | None:
    """The cash a row moved, in `ccy` at its trade date's rate, or None.

    A buy costs its shares plus the fee, a sale brings them in less the fee, a
    dividend or a return of capital is its amount and a fee is itself.
    A split or a transfer moves no cash, and a zero there would read as a free
    trade. The rate is the one the ledger replay above already prefetched, so
    this resolves from the on-disk FX cache; a date it cannot price is None,
    never today's rate passed off as that day's.
    """
    from stocks.data.fx import rate_on

    amount = {
        "buy": t.quantity * t.price + t.fee,
        "sell": t.quantity * t.price - t.fee,
        "dividend": t.price,
        "capital": t.price,
        "fee": t.fee,
    }.get(t.action)
    if amount is None:
        return None
    try:
        return _num(amount * rate_on(t.date, t.currency, ccy))
    except Exception:  # noqa: BLE001 — an unpriced row is n/a, not a 500
        return None


# ----------------------------------------------------------- taking it away
# The privacy policy promises the ledger is the account's own to take away, and
# "take away" has to mean a file. The Profile page has offered this download
# since before the API existed; the formatter is `web.exports.ledger_csv` and
# stays there — a second one here would drift the moment either grew a column.


@ttl_cache(3600.0, max_entries=8)
def _ledger_csv(db: str, mtime: float, base: str) -> bytes:
    """The export, memoized on (db, ledger mtime, base).

    Worth caching because it is not a dump: every row is priced at the ECB rate
    for its own trade date, which is a fetch per currency in the book.
    """
    from stocks.web.exports import ledger_csv

    return ledger_csv(db, base)


@router.get(
    "/transactions.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "The ledger."}},
    summary="The ledger as a file",
)
def transactions_csv(account: Account, base: Base = None) -> Response:
    """Every transaction as CSV, each row also converted to the reporting currency.

    The same bytes the Profile page's download button hands back, filename
    included, so a book exported from either side reconciles against the other.
    Best-effort on the rates: a row whose rate could not be fetched exports with
    an empty rate and an empty converted amount rather than a wrong one — the
    native columns are the ledger, and they are always there.

    A book with no transactions is a 404 rather than a zero-byte attachment:
    the page offers no button in that state, and a client should not hand
    somebody a file that turns out to be empty.
    """
    ccy = reporting_currency(account, base)
    db = str(account.db)
    body = _ledger_csv(db, loaders.db_mtime(db), ccy)
    if not body:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this book has no transactions to export",
        )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="aguait-ledger-{date.today():%Y-%m-%d}.csv"'
            )
        },
    )
