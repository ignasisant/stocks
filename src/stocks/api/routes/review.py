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
from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import date
from time import perf_counter
from typing import Annotated, TypedDict, cast

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from stocks import accounts, obs
from stocks.analysis import review as engine
from stocks.analysis.compare import (
    closes_by_day,
    rates_into,
    window_axis,
    window_days,
    window_returns,
)
from stocks.analysis.listing import listing_currencies, quote_unit
from stocks.analysis.portfolio import risk_shares, value_weights
from stocks.analysis.sentiment import SECTOR_ETFS
from stocks.api import loaders
from stocks.api.cache import carried
from stocks.api.deps import Account, Base, reporting_currency
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import (
    NameReturns,
    Review,
    ReviewLines,
    ReviewNote,
    ReviewPlan,
    ReviewReturns,
    ReviewRow,
)
from stocks.chat import journal
from stocks.config import Holding, load_watchlist
from stocks.data import fx, profiles
from stocks.data.crypto import is_crypto
from stocks.frames import midnight
from stocks.portfolio import consistency, demo, tax
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
# The return columns: every name a table can show, held and outside, and the
# index each is measured against. A download each, on a pool of their own so
# they never queue behind the fundamentals pulls the same visit started.
MAX_RETURNS = 200
INDEX = "SPY"
_RETURNS_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="returns")
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
) -> tuple[dict[str, tuple[str | None, dict | None]], set[str]]:
    """Kind and metrics per symbol, fetched side by side, and the symbols that
    missed `GATHER_BUDGET_S`; a fund skips the metrics pull, since a wrapper
    has no ROIC to score. A late symbol is left out (its row reads unrated)
    while its pull finishes in the background."""

    def one(symbol: str) -> tuple[str | None, dict | None]:
        kind = _kind(symbol)
        if kind not in (None, "stock"):
            return kind, None
        return kind, _metrics(symbol)

    unique = list(dict.fromkeys(symbols))
    if not unique:
        return {}, set()
    futures = {_POOL.submit(carried(one), symbol): symbol for symbol in unique}
    done, late = wait(futures, timeout=GATHER_BUDGET_S)
    return {futures[f]: f.result() for f in done}, {futures[f] for f in late}


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


class _Clock:
    """Milliseconds per phase of one read, summed over repeats, so a slow
    answer says which source it waited on."""

    def __init__(self) -> None:
        self.ms: dict[str, int] = {}

    @contextmanager
    def __call__(self, phase: str) -> Generator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            spent = round((perf_counter() - started) * 1000)
            self.ms[phase] = self.ms.get(phase, 0) + spent


# An unrated row is expected for a fund, cash or a coin; any other is a
# source that failed the read, and these say which.
_UNRATED_WHY = (engine.R_SUSPECT, engine.R_FCF_FLOAT, engine.R_NO_DATA)
# Too many sells or blanks among a book's companies is a calibration that
# misreads a kind of book (a bank-heavy one, a foreign one), not a verdict.
ODD_MIN_NAMES = 5
ODD_SHARE = 0.5


def _venue(symbol: str) -> str:
    """The exchange suffix of a symbol (MC, L, DE), "none" for a bare one:
    where a failure keeps turning up, never which name."""
    head, dot, tail = symbol.rpartition(".")
    return tail.upper() if dot and head and tail.isalpha() and len(tail) <= 3 else "none"


def _unrated_cause(row: ReviewRow, metrics: dict | None, late: set[str]) -> str | None:
    """Why a company's row reads unrated, or None for a scored row or one a
    kind leaves unrated on purpose."""
    if row.verdict != engine.UNRATED or not engine.company(row.kind or "stock"):
        return None
    if row.symbol in late:
        return "pending"
    if metrics is None:
        return "no_metrics"
    return next((r for r in row.reasons if r in _UNRATED_WHY), "other")


def _user() -> str:
    return str(obs.current().get("user", ""))


def _invariants(
    held: list[ReviewRow], outside: list[ReviewRow], *, replayed: bool
) -> list[str]:
    """Plans that cannot be right, each said once per account and window as
    `review.invariant`: the weights do not add up, a target falls outside
    the book, a move goes against its verdict, or a sale went out without
    its tax. Targets may sum past 1: adds are sized on today's total and
    the plan's net buys are new money. Returns the kinds found, for the
    read's own line."""
    found: dict[str, dict] = {}
    current = [r.weight for r in held if r.weight is not None]
    if current and abs(sum(current) - 1.0) > 0.005:
        found["weights_off"] = {"total": round(sum(current), 4)}
    rows = held + outside
    wild = [
        r.target_weight
        for r in rows
        if r.target_weight is not None and not 0.0 <= r.target_weight <= 1.0
    ]
    if wild:
        found["target_out_of_range"] = {"count": len(wild)}
    against = [
        r.verdict
        for r in rows
        if r.delta
        and (
            (r.delta > 0 and r.verdict in (engine.SELL, engine.TRIM))
            or (r.delta < 0 and r.verdict in (engine.ADD, engine.BUY))
        )
    ]
    if against:
        found["delta_against_verdict"] = {"verdicts": dict(Counter(against))}
    untaxed = sum(
        1 for r in held if r.delta is not None and r.delta < 0 and r.tax is None
    )
    if untaxed:
        found["sale_untaxed"] = {"count": untaxed, "replayed": replayed}
    for kind, evidence in found.items():
        obs.warn_once("review.invariant", (kind, _user()), kind=kind, **evidence)
    return list(found)


def _audit_names(
    rows: list[ReviewRow], facts: dict[str, tuple[str | None, dict | None]]
) -> None:
    """What the feed got wrong about a name, said once: a name priced off a
    cash flow too good to be true (`data.inconsistency` metric_suspect), and
    an industry that sounds like a bank, landlord or utility but that no lens
    lists (`review.industry_unmapped`, by industry, never a ticker)."""
    for row in rows:
        metrics = facts.get(row.symbol, (None, None))[1] or {}
        if engine.R_SUSPECT in row.reasons:
            fcf, ev = metrics.get("fcf_yield"), metrics.get("ev")
            consistency.report(
                "metric_suspect",
                source="review",
                ticker=row.symbol,
                fcf_yield=round(fcf, 3) if isinstance(fcf, (int, float)) else None,
                ev_not_positive=isinstance(ev, (int, float)) and ev <= 0,
            )
        industry = metrics.get("industry")
        if engine.unmapped_industry(industry):
            obs.warn_once("review.industry_unmapped", industry, industry=industry)


def _odd_read(held: list[ReviewRow], unrated: Counter, **shape) -> None:
    """A read where most of the companies are sold, or most read blank for a
    reason other than a late pull: a kind of book the engine misreads.
    Logged with the book's shape, once per account and window."""
    companies = [r for r in held if engine.company(r.kind or "stock")]
    if len(companies) < ODD_MIN_NAMES:
        return
    sells = sum(r.verdict == engine.SELL for r in companies) / len(companies)
    blank = (sum(unrated.values()) - unrated.get("pending", 0)) / len(companies)
    for kind, share in (("sells", sells), ("unrated", blank)):
        if share > ODD_SHARE:
            obs.warn_once(
                "review.odd_read",
                (kind, _user()),
                kind=kind,
                share=round(share, 2),
                companies=len(companies),
                **shape,
            )


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
    # An account with nothing of its own to judge gets the wall, not a review
    # of the starter watchlist: the page is the reason to import. The guest
    # dir is the demo book every visitor reads, so a guest is never walled.
    if account.root != accounts.GUEST_DIR and not _imported(account):
        obs.event("review.locked", base=ccy)
        return Review(base=ccy, as_of=date.today().isoformat(), locked=True)
    return _judge(account, background, ccy, add)


@router.get(
    "/review/preview",
    response_model=Review,
    summary="The demo book judged, for the wall of an account with no import",
)
def preview(background: BackgroundTasks, base: Base = None) -> Review:
    guest = accounts.guest_paths()
    return _judge(guest, background, reporting_currency(guest, base), "")


@router.get(
    "/review/returns",
    response_model=ReviewReturns,
    summary="What each name returned, beside the index and its sector",
)
def returns(
    account: Account,
    names: Annotated[
        str,
        Query(
            description=(
                f"Comma-separated symbols, at most {MAX_RETURNS}: the review's "
                "rows as `symbol`."
            )
        ),
    ] = "",
    base: Base = None,
) -> ReviewReturns:
    """Total return in the reader's money over 1m, 6m, 1y and 2y per name,
    and the same for SPY and each name's sector ETF, so the page can say by
    how much a name led or lagged either.

    Its own request, after the review has answered: the verdicts do not wait
    on five years of closes per name. Every window ends on the same day for
    every name (`analysis.compare.window_returns`), so a gap is a gap in
    performance. Downloads past the budget keep going and are counted in
    `pending`; asking again finds them.
    """
    ccy = reporting_currency(account, base)
    asked = _parse_names(names)
    etfs = {
        name: None if is_crypto(name) else SECTOR_ETFS.get(_profile(name)["sector"] or "")
        for name in asked
    }
    benchmarks = list(dict.fromkeys([INDEX, *(etf for etf in etfs.values() if etf)]))
    every = list(dict.fromkeys([*asked, *benchmarks]))
    day, days = _window_calendar()
    axis = window_axis(day, days)
    key = ",".join(str(one.date()) for one in axis)

    closes: dict[str, Future] = {
        name: _RETURNS_POOL.submit(carried(_window_closes), name, key) for name in every
    }
    quoted = _RETURNS_POOL.submit(carried(listing_currencies), every)
    wait([*closes.values(), quoted], timeout=GATHER_BUDGET_S)
    currencies = quoted.result() if quoted.done() and not quoted.exception() else {}
    landed = {name: future.result() for name, future in closes.items() if future.done()}
    pending = {name for name in every if name not in landed}
    rates, unpriced = rates_into(
        ccy, axis, {name: currencies.get(name) for name in landed}
    )

    def measured(name: str) -> NameReturns | None:
        series = landed.get(name)
        if series is None or name in unpriced or series.dropna().empty:
            return None
        out = window_returns(series, rates.get(name), day, days)
        if all(value is None for value in out.values()):
            return None
        return NameReturns(ticker=name, returns=out, sector_etf=etfs.get(name))

    rows = {name: measured(name) for name in every if name not in pending}
    obs.event(
        "api.review_returns",
        base=ccy,
        names=len(asked),
        benchmarks=len(benchmarks),
        pending=len(pending),
        missing=sum(1 for name in asked if name not in pending and rows[name] is None),
    )
    return ReviewReturns(
        base=ccy,
        as_of=str(day.date()),
        names=[row for name in asked if (row := rows.get(name)) is not None],
        benchmarks=[row for name in benchmarks if (row := rows.get(name)) is not None],
        missing=[name for name in asked if name not in pending and rows[name] is None],
        pending=sum(1 for name in asked if name in pending),
    )


def _parse_names(raw: str) -> list[str]:
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
    if len(out) > MAX_RETURNS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"at most {MAX_RETURNS} names",
        )
    return out


def _window_calendar() -> tuple[pd.Timestamp, dict[str, pd.Timestamp]]:
    """The day every window ends on and the day each opens on: SPY's last
    session, and its sessions cut the way the price chart cuts them. The plan's
    chart draws on SPY's axis, so a column and the line beside it read one
    stretch. Today by the calendar when SPY's bars will not come."""
    try:
        sessions = pd.DatetimeIndex(closes_by_day(loaders.bar_closes(INDEX, "2y")).index)
    except Exception as exc:  # noqa: BLE001
        obs.warn(
            "api.review_returns_failed",
            symbol=INDEX,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        sessions = pd.DatetimeIndex([])
    if len(sessions) == 0:
        day = midnight(date.today())
        return day, window_days(day)
    day = cast(pd.Timestamp, pd.Timestamp(sessions[-1]))
    return day, window_days(day, sessions)


def _window_closes(symbol: str, days: str) -> pd.Series | None:
    """`loaders.window_closes`, or None when Yahoo has none or refused: a
    blank cell, not a failed column."""
    try:
        return loaders.window_closes(symbol, days)
    except Exception as exc:  # noqa: BLE001
        obs.warn(
            "api.review_returns_failed",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return None


def _imported(account) -> bool:
    try:
        return demo.has_real(account.db)
    except Exception:
        return False  # unreadable/missing ledger reads as "nothing imported"


def _judge(account, background: BackgroundTasks, ccy: str, add: str) -> Review:
    started = perf_counter()
    clock = _Clock()
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

    with clock("gather"):
        facts, late = _gather(
            list(held_symbols.values()) + list(outside_symbols.values())
        )
    pending = len(late)
    with clock("windows"):
        windows = _windows(account, code, today)
    window_by_symbol = {_symbol(label): day for label, day in windows.items()}

    with clock("prices"):
        table = pricing.result()
    with clock("risk"):
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
                with clock("replay"):
                    book = _replay(account)
            with clock("sales"):
                sales[key] = _sale(
                    book, label, weight, target, _book_price(table.loc[label], ccy)
                )
        return sales[key]

    def tax_share(label: str, weight: float | None, verdict: engine.Verdict):
        """A concentration cut's or a sale's tax over what it raises, both in
        the jurisdiction's currency; None for any other row (a crumb's sale
        too: its tax is crumbs)."""
        cut = verdict.verdict == engine.TRIM and engine.R_CONCENTRATED in verdict.reasons
        sold = verdict.verdict == engine.SELL and engine.R_SMALL not in verdict.reasons
        if not (cut or sold):
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
    # A move the page proposed before and still stands holds to the plain
    # line; a new one has to clear the margin past it (`engine.judge_held`).
    proposed: dict[str, str] = {}
    with obs.swallow("api.review_journal"):
        proposed = journal.open_in_review(account.journal)

    def was(ticker: str, symbol: str) -> str | None:
        return proposed.get(ticker.upper()) or proposed.get(symbol.upper())

    first = engine.cap_small_sells(
        [
            engine.judge_held(
                facts.get(symbol_of(label), (None, None))[1],
                weight=_num(weights.get(label)),
                risk_share=shares.get(label, shares.get(symbol_of(label))),
                kind=kind_of(label),
                names=names,
                company_share=company_share or 1.0,
                was=was(label, symbol_of(label)),
            )
            for label in held_labels
        ]
    )
    staged = []
    for label, verdict in zip(held_labels, first, strict=True):
        weight = _num(weights.get(label))
        share = tax_share(label, weight, verdict)
        verdict = engine.hold_for_cost(verdict, share)
        staged.append((weight, engine.stage_for_tax(weight, verdict, share)))
    judged = engine.redeploy(staged, [sectors[label] for label in held_labels])

    # Losses the plan leaves open, against the gains its sales realise: the
    # names it sells or adds to are not the ones to sell for tax.
    if any(
        v.target is not None and w is not None and v.target < w
        for (w, _), v in zip(staged, judged, strict=True)
    ):
        if book is _NOT_REPLAYED:
            with clock("replay"):
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
        with clock("offset"):
            offset = _offset(book, plan_orders, [order for _, order in losers], floor)
        if offset:
            notes.append(offset)

    held_rows: list[ReviewRow] = []
    for label, verdict in zip(held_labels, judged, strict=True):
        symbol = symbol_of(label)
        kind = facts.get(symbol, (None, None))[0]
        row = table.loc[label]
        weight = _num(weights.get(label))
        risk = shares.get(label, shares.get(symbol))
        delta = tax_due = after = wish = None
        if verdict.want is not None and weight is not None and total > 0:
            start = verdict.target if verdict.target is not None else weight
            wish = (verdict.want - start) * total
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
                new_money=_num(wish),
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
        verdict = engine.judge_candidate(
            metrics, kind=kind or "stock", names=names, was=was(ticker, symbol)
        )
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
    waiting = [r for r in held_rows if r.new_money and r.verdict == engine.HOLD]
    if idle := engine.cash_note(
        rows, [r.verdict for r in held_rows + outside_rows], waiting=len(waiting)
    ):
        notes.append(idle)

    # What the page proposes goes in the decision journal once the answer is
    # on its way: the sells, trims, adds and buys it shows, and the end of any
    # it proposed before and no longer does. A plan that moves nothing is
    # advice too, and goes in as one stay on the whole book.
    shown = held_rows + outside_rows
    moves = [r.delta for r in shown if r.delta is not None]
    stay = bool(held_rows) and total > 0 and not moves
    proposals = journal.from_review(shown)
    if stay:
        proposals.append(journal.stay_in_review(_num(total), ccy))
    background.add_task(
        journal.safely,
        journal.record,
        account.journal,
        proposals,
        today,
        judged=journal.judged_in_review(shown),
    )

    taxes = [r.tax for r in held_rows if r.tax is not None]
    unpriced = int(table["value"].isna().sum()) if not table.empty else 0
    # Which books use the page and where it fails them, in aggregate: never a
    # ticker. A source that failed one name is in `unrated`, by cause and by
    # exchange; a plan that cannot be right is its own warning.
    metrics_of = {r.symbol: facts.get(r.symbol, (None, None))[1] for r in shown}
    causes = {
        r.symbol: cause
        for r in shown
        if (cause := _unrated_cause(r, metrics_of[r.symbol], late))
    }
    unrated = Counter(causes.values())
    scored = [m for r in shown if (m := metrics_of[r.symbol]) is not None]
    blank_added = [a for a in added if causes.get(_symbol(a)) == "no_metrics"]
    invariants = _invariants(
        held_rows, outside_rows, replayed=book not in (None, _NOT_REPLAYED)
    )
    _audit_names(shown, facts)
    verdicts = dict(Counter(r.verdict for r in shown))
    lenses = dict(Counter(engine.lens(m) for m in scored))
    _odd_read(
        held_rows,
        Counter(causes[r.symbol] for r in held_rows if r.symbol in causes),
        jurisdiction=code,
        base=ccy,
        verdicts=verdicts,
        lenses=lenses,
    )
    obs.event(
        "api.review",
        jurisdiction=code,
        tax_status=how,
        base=ccy,
        held=len(held_rows),
        candidates=len(outside_rows),
        names=names,
        kinds=dict(Counter(r.kind or "stock" for r in held_rows)),
        verdicts=verdicts,
        lenses=lenses,
        stages=dict(Counter(engine.stage(m) for m in scored)),
        notes=[n.key for n in notes],
        unpriced=unpriced,
        pending=pending,
        unrated=dict(unrated),
        unrated_venues=dict(Counter(_venue(s) for s in causes)),
        no_industry=sum(1 for m in scored if not m.get("industry")),
        added=len(added),
        added_blank=len(blank_added),
        added_venues=dict(Counter(_venue(a) for a in blank_added)),
        invariants=invariants,
        stay=stay,
        new_money_names=sum(1 for r in held_rows if r.new_money),
        close_calls=sum(1 for r in shown if engine.R_CLOSE_CALL in r.reasons),
        costly_holds=sum(1 for r in held_rows if engine.R_SALE_COSTLY in r.reasons),
        held_by_journal=sum(1 for r in shown if was(r.ticker, r.symbol)),
        phases=clock.ms,
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
            new_money=sum(r.new_money or 0.0 for r in held_rows),
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
