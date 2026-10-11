"""Review: what to sell, trim, keep or add to, and which outside names to buy.

One read over the account's book and its watchlist. The judging is
`stocks.analysis.review`, pure; this route gathers what it judges — the priced
positions, each name's share of the book's risk, the fundamentals the ticker
page already caches — and adds the two answers only the ledger has: the tax a
sale would add to this year's bill, and the day a buy stops undoing a loss sold
inside the repurchase window.

Outside names are the watchlist's unheld tickers plus `?add=`, which is how the
page weighs a name nobody follows yet without writing anything: the list rides
the URL, and following a name for good is the watchlist's own button. Every
row, held or not, says whether the watchlist has it, starred, and in which
groups — the page's "include" filter narrows the comparison by those.

A read, and a cheap one to repeat: each name's KPIs are one memo entry a day
old at worst (`loaders.review_metrics`), the risk split is the Portfolio risk
tab's own cached report, and the sales share one ledger replay priced at the
book's own figures. The three slow sources — the book's prices, its risk and
the names' KPIs — are asked side by side: the names come from the ledger, not
the priced table, so nothing waits on a download it does not read.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from stocks import obs
from stocks.analysis import review as engine
from stocks.analysis.portfolio import risk_shares, value_weights
from stocks.api import loaders
from stocks.api.cache import carried
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import Review, ReviewPlan, ReviewRow
from stocks.chat import journal
from stocks.config import Holding, load_watchlist
from stocks.data import profiles
from stocks.portfolio import tax
from stocks.portfolio.tax import prefs as tax_prefs

router = APIRouter(tags=["review"])

# Outside names are a fundamentals pull each. The watchlist's are already
# warm from Home; a cap keeps a long list from turning one page into a burst.
MAX_CANDIDATES = 30
MAX_ADDED = 10
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,19}$")
_WORKERS = 6
_NOT_REPLAYED = object()


def _parse_added(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.split(","):
        symbol = part.strip().upper()
        if not symbol:
            continue
        if not _SYMBOL.match(symbol):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"not a ticker: {part.strip()[:24]}",
            )
        if symbol not in out:
            out.append(symbol)
    if len(out) > MAX_ADDED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"at most {MAX_ADDED} tickers in add",
        )
    return out


def _kind(symbol: str) -> str | None:
    with obs.swallow("api.review_kind"):
        return loaders.asset_kind(symbol)
    return None


def _sector(symbol: str) -> str | None:
    """Yahoo's sector for a symbol, from the profile memo the metrics pull
    just filled (`data.profiles`) — no request of its own. A fund has none."""
    with obs.swallow("api.review_sector"):
        return (profiles.known(symbol) or {}).get("sector")
    return None


def _metrics(symbol: str) -> dict | None:
    """The ticker page's KPIs for `symbol`, or None when Yahoo has none."""
    with obs.swallow("api.review_metrics"):
        return loaders.review_metrics(symbol)
    return None


def _symbol(ticker: str) -> str:
    with obs.swallow("api.review_symbol"):
        return loaders.display_symbol(ticker) or ticker
    return ticker


def _gather(symbols: list[str]) -> dict[str, tuple[str | None, dict | None]]:
    """Kind and metrics per symbol, fetched side by side; a fund skips the
    metrics pull, since a wrapper has no ROIC to score."""

    def one(symbol: str) -> tuple[str | None, dict | None]:
        kind = _kind(symbol)
        if kind not in (None, "stock"):
            return kind, None
        return kind, _metrics(symbol)

    unique = list(dict.fromkeys(symbols))
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(unique))) as pool:
        return dict(zip(unique, pool.map(carried(one), unique), strict=True))


def _risk_shares(db: str, mtime: float, ccy: str) -> dict[str, float]:
    with obs.swallow("api.review_risk"):
        report = loaders.basket_report_since(db, mtime, ccy)
        if report is None or not report.weights:
            return {}
        shares = risk_shares(report.returns, report.port_returns, report.weights)
        return {
            str(name): value
            for name, raw in shares.items()
            if (value := _num(raw)) is not None
        }
    return {}


def _windows(account, code: str, today: date) -> dict[str, str]:
    """Ledger label -> the first day a buy no longer blocks a loss sale."""
    jurisdiction = tax.get(code)
    if not jurisdiction.repurchase_window:
        return {}
    db = str(account.db)
    with obs.swallow("api.review_windows"):
        txs, _, realized = loaders.ledger_state(
            db, loaders.db_mtime(db), jurisdiction.currency, jurisdiction.matching
        )
        out: dict[str, str] = {}
        for w in jurisdiction.open_windows(realized, tax.buy_dates(txs), today):
            day = w.clears.isoformat()
            out[w.ticker] = max(out.get(w.ticker, day), day)
        return out
    return {}


def _sale_tax(
    book, ticker: str, weight: float, target: float, price: tuple[float, str] | None
) -> float | None:
    """What selling down to `target` adds to this year's tax, or None.

    `book` is the ledger replayed once for every sale on the page; `price` the
    share price the row's value was built from, so the sale is weighed at the
    figure the page prints. Only a row the book could not price asks for a
    quote of its own."""
    from stocks.chat import whatif

    if book is None:
        return None
    with obs.swallow("api.review_tax"):
        held = book.held(ticker)
        quoted = price or (whatif._price(held.ticker) if held is not None else None)
        if held is None or quoted is None:
            return None
        keep = target / weight if weight > 0 and target > 0 else 0.0
        sale = book.scenario(
            held.ticker, held.quantity * (1.0 - keep), quoted[0], quoted[1]
        )
        return _num(sale.extra_tax) if sale is not None else None
    return None


def _replay(account):
    from stocks.chat import whatif

    with obs.swallow("api.review_replay"):
        return whatif.replay(db=account.db, prefs_path=account.prefs)
    return None


def _book_price(row, ccy: str) -> tuple[float, str] | None:
    """The share price, in `ccy`, a priced row's value stands for."""
    value, count = _num(row.get("value")), _num(row.get("shares"))
    if value is None or not count:
        return None
    return value / count, ccy


@router.get("/review", response_model=Review, summary="What to sell and what to add")
def review(
    account: Account,
    background: BackgroundTasks,
    base: Base = None,
    add: Annotated[
        str,
        Query(
            description=(
                "Comma-separated tickers to weigh beside the watchlist's, "
                f"at most {MAX_ADDED}. Nothing is written."
            )
        ),
    ] = "",
) -> Review:
    ccy = reporting_currency(account, base)
    added = _parse_added(add)
    today = date.today()
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    code, _ = tax_prefs.resolve(tax_prefs.load(account.prefs))

    # The held names are the ledger's, in the priced table's order; the prices
    # and the risk split download while the names' KPIs are fetched.
    pool = ThreadPoolExecutor(max_workers=2)
    pricing = pool.submit(carried(loaders.positions_table), db, mtime, ccy)
    risk = pool.submit(carried(_risk_shares), db, mtime, ccy)
    pool.shutdown(wait=False)
    held_labels = [str(p.ticker) for p in loaders.ledger_state(db, mtime, ccy)[1]]

    held_symbols = {label: _symbol(label) for label in held_labels}
    held_set = {s.upper() for s in held_symbols.values()} | {
        label.upper() for label in held_labels
    }
    # The watchlist twice over: its unheld names are the outside list, and
    # every row — held too — carries its star and groups, so the page can
    # narrow the comparison to "my favourites" or one group.
    entries: dict[str, Holding] = {}
    with obs.swallow("api.review_watchlist"):
        for entry in load_watchlist(account.watchlist):
            entries.setdefault(str(entry.ticker).upper(), entry)
    candidates = list(entries)
    candidates = [
        c
        for c in dict.fromkeys(added + candidates)
        if c not in held_set and _symbol(c).upper() not in held_set
    ][:MAX_CANDIDATES]
    outside_symbols = {c: _symbol(c) for c in candidates}

    facts = _gather(list(held_symbols.values()) + list(outside_symbols.values()))
    windows = _windows(account, code, today)
    window_by_symbol = {_symbol(label): day for label, day in windows.items()}

    table = pricing.result()
    shares = risk.result() if held_labels else {}
    held_labels = [str(t) for t in table.index] if not table.empty else []
    weights = value_weights(table) if not table.empty else {}
    # The denominator `value_weights` divides by — priced rows at value, the
    # rest at cost — so a weight times this is the money it stands for.
    total = 0.0
    if not table.empty:
        priced = table["value"].notna()
        total = float(table.loc[priced, "value"].sum())
        if "cost" in table:
            total += float(table.loc[~priced, "cost"].sum())
    book = _NOT_REPLAYED

    def buy_after(ticker: str, symbol: str) -> str | None:
        return windows.get(ticker) or window_by_symbol.get(symbol)

    def watch(ticker: str, symbol: str) -> dict:
        entry = entries.get(ticker.upper()) or entries.get(symbol.upper())
        if entry is None:
            return {}
        return {
            "watched": True,
            "favorite": bool(entry.favorite),
            "lists": list(dict.fromkeys(entry.tags)),
        }

    held_rows: list[ReviewRow] = []
    for label in held_labels:
        symbol = held_symbols.get(label) or _symbol(label)
        kind, metrics = facts.get(symbol, (None, None))
        row = table.loc[label]
        weight = _num(weights.get(label))
        risk = shares.get(label, shares.get(symbol))
        verdict = engine.judge_held(
            metrics, weight=weight, risk_share=risk, kind=kind or "stock"
        )
        delta = tax_due = after = None
        if verdict.target is not None and weight is not None and total > 0:
            delta = (verdict.target - weight) * total
            if verdict.target < weight:
                if book is _NOT_REPLAYED:
                    book = _replay(account)
                tax_due = _sale_tax(
                    book, label, weight, verdict.target, _book_price(row, ccy)
                )
            else:
                after = buy_after(label, symbol)
        held_rows.append(
            ReviewRow(
                ticker=label,
                symbol=symbol,
                kind=kind,
                sector=_sector(symbol),
                held=True,
                verdict=verdict.verdict,
                reasons=list(verdict.reasons),
                quality=_num(verdict.quality),
                cheapness=_num(verdict.cheapness),
                metrics=verdict.metrics,
                value=_num(row["value"]),
                weight=weight,
                risk_share=risk,
                pnl=_num(row["pnl"]),
                pnl_pct=_num(row["pnl_pct"]),
                target_weight=_num(verdict.target),
                delta=_num(delta),
                tax=tax_due,
                buy_after=after,
                **watch(label, symbol),
            )
        )

    outside_rows: list[ReviewRow] = []
    for ticker, symbol in outside_symbols.items():
        kind, metrics = facts.get(symbol, (None, None))
        if kind == "index":
            continue
        verdict = engine.judge_candidate(metrics, kind=kind or "stock")
        outside_rows.append(
            ReviewRow(
                ticker=ticker,
                symbol=symbol,
                kind=kind,
                sector=_sector(symbol),
                held=False,
                verdict=verdict.verdict,
                reasons=list(verdict.reasons),
                quality=_num(verdict.quality),
                cheapness=_num(verdict.cheapness),
                metrics=verdict.metrics,
                buy_after=buy_after(ticker, symbol)
                if verdict.verdict == engine.BUY
                else None,
                **watch(ticker, symbol),
            )
        )

    def order(r: ReviewRow):
        total_score = (
            (r.quality + r.cheapness) / 2
            if r.quality is not None and r.cheapness is not None
            else None
        )
        return engine.sort_key(r.verdict, total_score, r.weight, r.held)

    held_rows.sort(key=order)
    outside_rows.sort(key=order)

    # What the page proposes goes in the decision journal once the answer is
    # on its way: the sells, trims, adds and buys it shows, and the end of any
    # it proposed before and no longer does.
    shown = held_rows + outside_rows
    background.add_task(
        journal.safely, journal.record, account.journal,
        journal.from_review(shown), today, judged=journal.judged_in_review(shown),
    )

    moves = [r.delta for r in held_rows if r.delta is not None]
    taxes = [r.tax for r in held_rows if r.tax is not None]
    return Review(
        base=ccy,
        as_of=today.isoformat(),
        total=_num(total) if total > 0 else None,
        held=held_rows,
        candidates=outside_rows,
        plan=ReviewPlan(
            sells=-sum(d for d in moves if d < 0),
            buys=sum(d for d in moves if d > 0),
            tax=sum(taxes) if taxes else None,
            tax_currency=tax.get(code).currency,
        ),
        unpriced=int(table["value"].isna().sum()) if not table.empty else 0,
        jurisdiction=code,
        added=added,
    )
