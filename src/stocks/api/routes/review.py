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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date
from time import perf_counter
from typing import Annotated, TypedDict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from stocks import obs
from stocks.analysis import review as engine
from stocks.analysis.listing import quote_unit
from stocks.analysis.portfolio import risk_shares, value_weights
from stocks.api import loaders
from stocks.api.cache import carried
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import Review, ReviewLines, ReviewNote, ReviewPlan, ReviewRow
from stocks.chat import journal
from stocks.config import Holding, load_watchlist
from stocks.data import fx, profiles
from stocks.portfolio import tax
from stocks.portfolio.tax import prefs as tax_prefs

router = APIRouter(tags=["review"])

# Outside names are a fundamentals pull each. The watchlist's are already
# warm from Home; a cap keeps a long list from turning one page into a burst.
MAX_CANDIDATES = 30
MAX_ADDED = 10
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,19}$")
# One pool for every request: a fundamentals pull that misses the answer's
# budget keeps running here and lands in `loaders.review_metrics`' memo, so the
# reload a partial answer asks for finds it. `_metrics_gate` still caps how
# many leave for Yahoo at once.
_WORKERS = 8
_POOL = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="review")
# A wide book cold is a minute of pulls (150 names ≈ 60 s at six at a time):
# answer with what arrived and say how many are still coming.
GATHER_BUDGET_S = 20.0
_NOT_REPLAYED = object()
# Open losses weighed against the plan's gains, largest first: a replay each.
MAX_OFFSETS = 6
# A loss this small, or a saving this small, is not worth a line on the page.
# Euros' worth, read in the jurisdiction's currency (`_lines`): whether a sale
# is worth crossing does not depend on the book's size, and 150 crowns are
# small change.
OFFSET_LOSS_EUR = 150.0
OFFSET_MIN_EUR = 25.0


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


class _Place(TypedDict):
    sector: str | None
    country: str | None
    currency: str | None


def _profile(symbol: str) -> _Place:
    """Yahoo's sector, country and quote currency for a symbol, from the
    profile memo the metrics pull just filled (`data.profiles`) — no request
    of its own. A fund has no sector or country; GBp reads as GBP."""
    with obs.swallow("api.review_profile"):
        known = profiles.known(symbol) or {}
        return _Place(
            sector=known.get("sector"),
            country=known.get("country"),
            currency=quote_unit(known.get("currency"))[0],
        )
    return _Place(sector=None, country=None, currency=None)


def _metrics(symbol: str) -> dict | None:
    """The ticker page's KPIs for `symbol`, or None when Yahoo has none."""
    with obs.swallow("api.review_metrics"):
        return loaders.review_metrics(symbol)
    return None


def _symbol(ticker: str) -> str:
    with obs.swallow("api.review_symbol"):
        return loaders.display_symbol(ticker) or ticker
    return ticker


def _gather(
    symbols: list[str],
) -> tuple[dict[str, tuple[str | None, dict | None]], int]:
    """Kind and metrics per symbol, fetched side by side, and how many missed
    `GATHER_BUDGET_S`; a fund skips the metrics pull, since a wrapper has no ROIC to
    score. A late symbol is left out (its row reads unrated) while its pull
    finishes in the background."""

    def one(symbol: str) -> tuple[str | None, dict | None]:
        kind = _kind(symbol)
        if kind not in (None, "stock"):
            return kind, None
        return kind, _metrics(symbol)

    unique = list(dict.fromkeys(symbols))
    if not unique:
        return {}, 0
    futures = {_POOL.submit(carried(one), symbol): symbol for symbol in unique}
    done, late = wait(futures, timeout=GATHER_BUDGET_S)
    return {futures[f]: f.result() for f in done}, len(late)


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


def _order(
    book, ticker: str, weight: float, target: float, price: tuple[float, str] | None
) -> tuple[str, float, float, str] | None:
    """Selling down to `target` as the replay takes it: (ticker, shares,
    price, currency), or None when the book holds none or nothing prices it.

    `price` is the share price the row's value was built from, so the sale is
    weighed at the figure the page prints. Only a row the book could not price
    asks for a quote of its own."""
    from stocks.chat import whatif

    held = book.held(ticker)
    quoted = price or (whatif._price(held.ticker) if held is not None else None)
    if held is None or quoted is None:
        return None
    keep = target / weight if weight > 0 and target > 0 else 0.0
    return held.ticker, held.quantity * (1.0 - keep), quoted[0], quoted[1]


def _sale(
    book, ticker: str, weight: float, target: float, price: tuple[float, str] | None
):
    """Selling down to `target`, replayed: the `whatif.Scenario`, or None.
    `book` is the ledger replayed once for every sale on the page."""
    if book is None:
        return None
    with obs.swallow("api.review_tax"):
        order = _order(book, ticker, weight, target, price)
        return book.scenario(*order) if order is not None else None
    return None


def _rate(source: str, target: str) -> float | None:
    """Units of `target` per unit of `source`, or None when no rate is had."""
    if not source or not target or source.upper() == target.upper():
        return 1.0
    try:
        return fx.spot(source, target)[0]
    except Exception:  # noqa: BLE001 — a rate is a nicety here, never a failure
        obs.event("review.fx_missing", source=source.upper(), target=target.upper())
        return None


def _lines(book) -> tuple[float, float]:
    """(loss, saving) worth a line, in `book`'s jurisdiction currency."""
    rate = _rate("EUR", book.currency) if book is not None else 1.0
    rate = rate or 1.0
    return OFFSET_LOSS_EUR * rate, OFFSET_MIN_EUR * rate


def _unrealised(book, order: tuple[str, float, float, str]) -> float | None:
    """The open gain (negative: loss) of a whole-position `order`, in the
    jurisdiction's currency, against the replay's own cost: the sign tax
    sees, which a move in the exchange rate can flip from the page's."""
    ticker, shares, price, currency = order
    held = book.held(ticker)
    rate = _rate(currency, book.currency)
    if held is None or rate is None:
        return None
    return shares * price * rate - held.cost


def _offset(book, plan: list, losers: list, floor: float) -> engine.Note | None:
    """The open losses that would cut the tax the plan's sales add, sold
    with them: `plan` and `losers` are `_order` tuples, losers largest loss
    first. Each is replayed on top of the plan and kept only if it saves
    tax there — on its own lots it may not be a loss at all — then all the
    kept ones together, since the savings do not add up once the gains are
    cancelled. None when nothing saves `floor` (`_lines`)."""
    from stocks.chat.signals import _window_end

    if book is None or not plan or not losers:
        return None
    with obs.swallow("api.review_offset"):
        tax_of = lambda sales: book.after(sales)[1].estimated_tax  # noqa: E731
        planned = tax_of(plan)
        if planned <= book.before.estimated_tax:
            return None
        kept = [o for o in losers[:MAX_OFFSETS] if tax_of([*plan, o]) < planned]
        if not kept:
            return None
        saving = planned - tax_of([*plan, *kept])
        if saving < floor:
            return None
        window = book.jurisdiction.repurchase_window or ""
        clear = _window_end(date.fromisoformat(book.day), window) if window else None
        return engine.Note(
            engine.N_TAX_OFFSET,
            count=len(kept),
            amount=saving,
            tickers=tuple(o[0] for o in kept),
            day=clear.isoformat() if clear else None,
        )
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
    started = perf_counter()
    ccy = reporting_currency(account, base)
    added = _parse_added(add)
    today = date.today()
    db = str(account.db)
    mtime = loaders.db_mtime(db)
    # The jurisdiction the rest of the app taxes this account under: never
    # the browser's, or this page and Portfolio's tax tab would disagree.
    code, how = tax_prefs.resolve(tax_prefs.load(account.prefs))

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

    facts, pending = _gather(list(held_symbols.values()) + list(outside_symbols.values()))
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

    def symbol_of(label: str) -> str:
        return held_symbols.get(label) or _symbol(label)

    def kind_of(label: str) -> str:
        return facts.get(symbol_of(label), (None, None))[0] or "stock"

    sales: dict[tuple[str, float], object] = {}

    def sale(label: str, weight: float, target: float):
        """The replayed sale down to `target`, once per row and target."""
        nonlocal book
        key = (label, target)
        if key not in sales:
            if book is _NOT_REPLAYED:
                book = _replay(account)
            sales[key] = _sale(
                book, label, weight, target, _book_price(table.loc[label], ccy)
            )
        return sales[key]

    def tax_share(label: str, weight: float | None, verdict: engine.Verdict):
        """A concentration cut's tax over what it raises, both in the
        jurisdiction's currency; None for any other row."""
        if verdict.verdict != engine.TRIM or engine.R_CONCENTRATED not in verdict.reasons:
            return None
        if weight is None or verdict.target is None or total <= 0:
            return None
        scenario = sale(label, weight, verdict.target)
        if scenario is None:
            return None
        extra, raised = _num(scenario.extra_tax), _num(scenario.proceeds)
        return extra / raised if extra is not None and raised else None

    # Sizing reads the whole book: how many companies set where a
    # concentration starts, a cut too dear in tax is staged, and what the
    # sales free is spread — outside any sector already full — before a row
    # is drawn.
    places = {label: _profile(symbol_of(label)) for label in held_labels}
    sectors = {label: places[label]["sector"] for label in held_labels}
    names = sum(engine.company(kind_of(label)) for label in held_labels)
    rows = [
        engine.BookRow(
            kind_of(label),
            sectors[label],
            _num(weights.get(label)),
            places[label]["country"],
            places[label]["currency"],
        )
        for label in held_labels
    ]
    notes = engine.book_notes(rows, ccy)
    company_share = sum(r.weight or 0.0 for r in rows if engine.company(r.kind))
    first = engine.cap_small_sells(
        [
            engine.judge_held(
                facts.get(symbol_of(label), (None, None))[1],
                weight=_num(weights.get(label)),
                risk_share=shares.get(label, shares.get(symbol_of(label))),
                kind=kind_of(label),
                names=names,
                company_share=company_share or 1.0,
            )
            for label in held_labels
        ]
    )
    staged = []
    for label, verdict in zip(held_labels, first, strict=True):
        weight = _num(weights.get(label))
        share = tax_share(label, weight, verdict)
        staged.append((weight, engine.stage_for_tax(weight, verdict, share)))
    judged = engine.redeploy(staged, [sectors[label] for label in held_labels])

    # Losses the plan leaves open, against the gains its sales realise: the
    # names it sells or adds to are not the ones to sell for tax.
    if any(
        v.target is not None and w is not None and v.target < w
        for (w, _), v in zip(staged, judged, strict=True)
    ):
        if book is _NOT_REPLAYED:
            book = _replay(account)
        plan_orders, losers = [], []
        loss_line, floor = _lines(book)
        for label, (weight, _), verdict in zip(held_labels, staged, judged, strict=True):
            if book is None or weight is None:
                continue
            price = _book_price(table.loc[label], ccy)
            if verdict.target is not None and verdict.target < weight:
                order = _order(book, label, weight, verdict.target, price)
                if order is not None:
                    plan_orders.append(order)
            elif verdict.verdict != engine.ADD and price is not None:
                order = _order(book, label, weight, 0.0, price)
                loss = _unrealised(book, order) if order is not None else None
                if loss is not None and loss < -loss_line:
                    losers.append((loss, order))
        losers.sort(key=lambda pair: pair[0])
        if offset := _offset(book, plan_orders, [order for _, order in losers], floor):
            notes.append(offset)

    held_rows: list[ReviewRow] = []
    for label, verdict in zip(held_labels, judged, strict=True):
        symbol = symbol_of(label)
        kind = facts.get(symbol, (None, None))[0]
        row = table.loc[label]
        weight = _num(weights.get(label))
        risk = shares.get(label, shares.get(symbol))
        delta = tax_due = after = None
        if verdict.target is not None and weight is not None and total > 0:
            delta = (verdict.target - weight) * total
            if verdict.target < weight:
                scenario = sale(label, weight, verdict.target)
                tax_due = _num(scenario.extra_tax) if scenario is not None else None
            else:
                after = buy_after(label, symbol)
        held_rows.append(
            ReviewRow(
                ticker=label,
                symbol=symbol,
                kind=kind,
                **places[label],
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

    # What the sales free and the book's adds leave goes to the outside Buys,
    # best first, before it is cash with no home.
    outside = []
    for ticker, symbol in outside_symbols.items():
        kind, metrics = facts.get(symbol, (None, None))
        if kind == "index":
            continue
        verdict = engine.judge_candidate(metrics, kind=kind or "stock", names=names)
        outside.append((ticker, symbol, kind, _profile(symbol), verdict))
    placed, _ = engine.place_outside(
        [(w, v) for (w, _), v in zip(staged, judged, strict=True)],
        [sectors[label] for label in held_labels],
        [(verdict, place["sector"]) for *_, place, verdict in outside],
    )

    outside_rows: list[ReviewRow] = []
    for (ticker, symbol, kind, place, verdict), target in zip(
        outside, placed, strict=True
    ):
        delta = target * total if target is not None and total > 0 else None
        reasons = (
            [engine.R_REDEPLOY, *verdict.reasons] if delta else list(verdict.reasons)
        )
        outside_rows.append(
            ReviewRow(
                ticker=ticker,
                symbol=symbol,
                kind=kind,
                **place,
                held=False,
                verdict=verdict.verdict,
                reasons=reasons,
                quality=_num(verdict.quality),
                cheapness=_num(verdict.cheapness),
                metrics=verdict.metrics,
                target_weight=_num(target) if delta else None,
                delta=_num(delta),
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
    if idle := engine.cash_note(rows, [r.verdict for r in held_rows + outside_rows]):
        notes.append(idle)

    # What the page proposes goes in the decision journal once the answer is
    # on its way: the sells, trims, adds and buys it shows, and the end of any
    # it proposed before and no longer does.
    shown = held_rows + outside_rows
    background.add_task(
        journal.safely,
        journal.record,
        account.journal,
        journal.from_review(shown),
        today,
        judged=journal.judged_in_review(shown),
    )

    moves = [r.delta for r in shown if r.delta is not None]
    taxes = [r.tax for r in held_rows if r.tax is not None]
    unpriced = int(table["value"].isna().sum()) if not table.empty else 0
    # Which books use the page, in aggregate: never a ticker.
    obs.event(
        "api.review",
        jurisdiction=code,
        tax_status=how,
        base=ccy,
        held=len(held_rows),
        candidates=len(outside_rows),
        names=names,
        kinds=dict(Counter(r.kind or "stock" for r in held_rows)),
        verdicts=dict(Counter(r.verdict for r in shown)),
        notes=[n.key for n in notes],
        unpriced=unpriced,
        pending=pending,
        ms=round((perf_counter() - started) * 1000),
    )
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
        unpriced=unpriced,
        jurisdiction=code,
        tax_status=how,
        added=added,
        pending=pending,
        lines=ReviewLines(
            concentrated=engine.concentration_line(names),
            small=engine.small_line(names),
            add_to=engine.add_line(names),
            sector=engine.SECTOR_LINE,
        ),
        notes=[
            ReviewNote.model_validate(
                {**vars(note), "tickers": [symbol_of(t) for t in note.tickers]}
            )
            for note in notes
        ],
    )
