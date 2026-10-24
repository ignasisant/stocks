"""Writing the daily card over HTTP: the facts, the job, and what a poll sees.

A generation is a model call that can outlast a request, so the card is a
small machine built around requests:

* `POST /daily` asks for today's card. A stored one that still stands comes
  straight back and spends nothing. Otherwise the facts are built from this
  API's own loaders, one generation starts, and the request waits `GRACE_S` —
  a provider that answers inside it lands in the response; a slower one leaves
  a *job* behind and the response says `pending`, carrying the computed card so
  the section is never empty.
* `GET /daily` is what the client polls. It never starts anything (a GET that
  could spend the allowance is a GET a prefetch could empty), but it does see
  the job: pending while the thread runs, and — when the model gave nothing
  back — the computed card the job was holding, so a failed generation does
  not quietly hand the reader yesterday's briefing.

The job applies its own side effects when it finishes, on its own thread: the
spent free unit goes to prefs.json and the card to daily_action.json. Nothing
owns the request after it has answered, and a card that was paid for must be
stored whether or not anybody polls for it.

Attempted at most once per account per key (action day, language, session):
a provider that is down stays down for the next few seconds, and a client that
re-POSTs on every mount would otherwise spend the allowance on the same
failure. "Regenerate" is the explicit way past that guard, and it abandons a
job already in flight rather than waiting on it — the unit that job spent is
lost, which is the cheaper of the two prices.

Process-local, like every cache in this API. A second container knows nothing
of a job the first one started; the worst that costs is one more generation,
and the stored card makes even that rare.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime

import pandas as pd

from stocks import accounts, obs
from stocks.analysis import sentiment as sm
from stocks.analysis.portfolio import (
    basket_change,
    index_change,
    money_change,
    us_market_open,
)
from stocks.api import home, loaders
from stocks.api.cache import ttl_cache
from stocks.api.deps import reporting_currency
from stocks.chat import (
    daily,
    daily_book,
    daily_routines,
    engine,
    exit_judge,
    journal,
    routine_plan,
    signals,
    today_sections,
)
from stocks.data.crypto import is_crypto
from stocks.formatting import finite

# How long `POST /daily` holds the request for a briefing before answering
# `pending`. The free chain usually answers well inside it, and everything past
# it is a spinner on a card the reader could already be reading the computed
# version of.
GRACE_S = 2.5

# What the client is told to wait between polls. Reported, not enforced: the
# poll is a GET of a small JSON read.
POLL_S = 1.5


@dataclass
class Job:
    """One generation in flight (or just finished) for one account."""

    key: tuple
    forced: bool
    computed: daily.DailyAction | None
    started: float = field(default_factory=time.time)
    done: bool = False
    action: daily.DailyAction | None = None
    # Set by a Regenerate that overtook this job: it may finish, but it must
    # not store a card the reader already asked to replace.
    abandoned: bool = False


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def job_for(paths, key: tuple) -> Job | None:
    """The account's job for `key`, or None — a job for another key is stale."""
    with _lock:
        job = _jobs.get(str(paths.root))
    return job if job is not None and job.key == key else None


def running(paths) -> Job | None:
    """The account's job still out, whatever it was keyed on, or None.

    What makes `POST /today` idempotent: a page and its Home teaser asking in
    two languages a second apart must not abandon each other's generation.
    """
    with _lock:
        job = _jobs.get(str(paths.root))
    return job if job is not None and not job.done else None


def key_for(day: date, lang: str, session: str | None, brief: str = "") -> tuple:
    """What a card and its one generation attempt are keyed on.

    The session is in it for the reason `daily.is_fresh` gives: a card written
    before the open quotes the previous close, and when the next session lands
    that card is stale hours before the 09:00 rollover. Rekeying retires the
    "already tried" guard with it. So is the brief's wording
    (`daily_routines.signature`): a reader who rewrites it wants the card
    they just asked for, not the one tried this morning.
    """
    return (day.isoformat(), lang, session or "", brief)


# ------------------------------------------------------------------- facts

# The card's market lines need prices for symbols nobody holds, the one input
# Home does not already have in hand: SPY for the index and as the sector ETFs'
# benchmark, the eleven sector ETFs for rotation and trend breadth, EUR/USD for
# the currency line. Thirteen, not the Pulso page's fifty — Yahoo throttles
# datacenter IPs and the card runs on every Home load. Sorted so the tuple is
# stable. Two years, because trend breadth is read against a 200-session
# average and a one-year window leaves the first half of it undefined.
CARD_TICKERS: tuple[str, ...] = tuple(
    sorted({"SPY", "EURUSD=X", *sm.SECTOR_ETFS.values()})
)
CARD_PERIOD = "2y"
# The Today chart's longest fixed window (`daily_book.RANGES`), a little over;
# a book older than this is drawn against the indexes' "max".
COMPARE_PERIOD = "6y"


def _closes_since(first, index: str = daily_book.INDEX_SYMBOL) -> dict:
    """Index closes reaching back to `first`, the book's first day: the same
    money goes into the index from there, whatever window is drawn. The card's
    own two years when they reach (SPY, no request), else the indexes' six
    years, else their whole history."""
    # A download opens a week or so late on its own first day.
    def reaches(years: int) -> bool:
        floor = pd.Timestamp.today().normalize() - pd.DateOffset(years=years, days=-7)
        return first is None or pd.Timestamp(first) >= floor

    if index == daily_book.INDEX_SYMBOL and reaches(2):
        return _card_closes()
    return _compare_closes(COMPARE_PERIOD if reaches(6) else "max")


@ttl_cache(900.0, max_entries=1, persist="card_closes")
def _card_closes() -> dict[str, pd.Series]:
    """The market symbols the card reads, in ONE bulk request shared by every
    account in the process: an index close is not personal data."""
    from stocks.analysis.portfolio import load_closes

    return load_closes(list(CARD_TICKERS), period=CARD_PERIOD)


@ttl_cache(900.0, max_entries=2, persist="compare_closes")
def _compare_closes(period: str = COMPARE_PERIOD) -> dict[str, pd.Series]:
    """Every index the Today chart offers (`daily_book.INDEXES`) and the euro
    pair SPY is converted with, over its longest window, in one bulk request
    shared by every account — and only once someone asks for a pairing the
    card's own two years cannot draw."""
    from stocks.analysis.portfolio import load_closes

    return load_closes(sorted({*daily_book.INDEXES, "EURUSD=X"}), period=period)


@ttl_cache(86400.0, max_entries=32)
def _meta(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Sector / country / currency per ticker. These four fields do not move."""
    from stocks.analysis.portfolio import load_meta

    return load_meta(list(tickers))


def book_sectors(tbl) -> pd.Series:
    """The book's weights summed by sector, funds looked through — the split
    the card's sector-tilt line is written from, and the assistant's
    snapshot quotes. Empty when there is nothing weighted to split."""
    from stocks.analysis.portfolio import allocation

    weights = tbl["weight"].dropna() if tbl is not None and "weight" in tbl else None
    if weights is None or not len(weights):
        return pd.Series(dtype=float)
    names = tuple(sorted(str(t) for t in weights.index))
    return allocation(
        {str(t): float(w) for t, w in weights.items()}, _meta(names), "sector"
    )


def index_month_base(closes: dict[str, pd.Series], base: str = "EUR") -> float:
    """SPY's month, in the reader's own currency.

    The fallback when the book's own money cannot be replayed into the index
    (`index_change`): the book's month is in `base`; the index's comes
    off a series quoted in dollars. Subtracting one from the other without this
    conversion reports the currency's move as skill, in whichever direction it
    happened to go — which is the single easiest way for this card to tell a
    reader something false about their own performance.
    """
    in_base = index_in_base(closes, base)
    if in_base is None:
        return float("nan")
    return sm.pct_over(in_base, signals.MONTH_SESSIONS)


def index_in_base(closes: dict[str, pd.Series], base: str = "EUR") -> pd.Series | None:
    """SPY's closes in the reader's own currency, or None without them.

    Only the euro pair is downloaded, so any base other than EUR reads the
    index in its own dollars rather than inventing a cross rate.
    """
    index = closes.get("SPY")
    if index is None or index.dropna().empty:
        return None
    series = index.dropna()
    if base != "EUR":
        return series
    pair = closes.get("EURUSD=X")
    if pair is None or pair.dropna().empty:
        return None
    # EURUSD=X is dollars per euro, so dividing a dollar price by it gives the
    # price in euros. Both sides are reindexed onto the index's own sessions:
    # FX quotes on days the New York market is closed, and an unaligned divide
    # would compare Monday's price against Sunday's rate.
    rate = pair.dropna().reindex(series.index, method="ffill")
    in_base = (series / rate).dropna()
    return in_base if not in_base.empty else None


def _market(tbl, money, currency: str) -> list:
    """The market-wide candidates, or none of them.

    The one part of the card with a download of its own, and the only part
    that can be slow or fail on its own: a card that says nothing about the
    index is the card this was before, so any failure is an empty list.
    """
    try:
        closes = _card_closes()
        sectors = book_sectors(tbl)
        ccy = None
        if tbl is not None and not tbl.empty and {"ccy", "weight"} <= set(tbl.columns):
            ccy = tbl.groupby("ccy")["weight"].sum()
        # The book's month and the index's on the same money: the index
        # bought with the reader's own deposits, on their days. Without the
        # second there is no comparison to make, so neither is passed.
        month = money_change(money, 30) if money is not None else None
        index = index_in_base(closes, currency)
        bench = index_change(money, index, 30) if month else None
        return signals.market_candidates(
            closes,
            book_sectors=sectors,
            bench_sectors=loaders.benchmark_sectors(),
            currency_weights=ccy,
            book_month_pct=month[1] * 100 if month and bench else None,
            bench_month_pct=(
                bench[1] * 100 if bench else index_month_base(closes, currency) * 100
            ),
            currency=currency,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        obs.warn(
            "daily_action.market_unavailable",
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return []


@ttl_cache(3600.0, max_entries=4)
def _rates(sids: tuple[str, ...]) -> dict[str, pd.Series]:
    """The policy-rate series, off FRED (keyless; disk-cached six hours)."""
    from stocks.data import macro

    return macro.fred_many(list(sids), years=1)


def _macro(day: date, currency: str) -> list:
    """The rate-decision candidates, or none of them.

    The Fed for everyone — it prices the dollar and most of what a stock book
    holds — and the ECB for a euro book. The series are downloaded only when
    a decision is inside the card's window (`signals.macro_due`), which is a
    few days a year: the other days cost nothing.
    """
    from stocks.data import macro_calendar as cal

    banks = [
        b for b in ((cal.FED, cal.ECB) if currency == "EUR" else (cal.FED,))
        if signals.macro_due(b, day)
    ]
    if not banks:
        return []
    try:
        rates = _rates(tuple(sid for b in banks for sid in cal.RATE_SERIES[b]))
        return signals.macro_candidates(day, rates, banks=banks)
    except Exception as exc:  # noqa: BLE001 — best-effort, like the market block
        obs.warn("daily_action.macro_unavailable", error_type=type(exc).__name__)
        return []


def _jurisdiction(prefs: dict):
    """The account's tax jurisdiction, or None — only the harvest line reads it."""
    try:
        from stocks.portfolio import tax
        from stocks.portfolio.tax import prefs as tax_prefs

        return tax.get(tax_prefs.resolve(prefs)[0])
    except Exception:  # noqa: BLE001 — a calendar-year figure beats no card
        return None


def _tax_year_net(paths, prefs: dict, ccy: str, day: date):
    """(net taxable result of this tax year, the jurisdiction), from the tax tab's engine.

    Replayed under the jurisdiction's own matching rule and the same
    repurchase-rule netting the Tax tab shows, so "gains this year" on the card
    is the figure the user finds there. None when the book is in another
    currency than the jurisdiction's (the card's amounts are in the book's) or
    the engine cannot say.
    """
    try:
        from stocks.portfolio import tax
        from stocks.portfolio.tax import prefs as tax_prefs

        jurisdiction = tax.get(tax_prefs.resolve(prefs)[0])
        if jurisdiction.currency != ccy:
            return None
        db = str(paths.db)
        txs, _, sales = loaders.ledger_state(
            db, loaders.db_mtime(db), jurisdiction.currency, jurisdiction.matching
        )
        if not sales:
            return 0.0
        settings = tax_prefs.with_funds(tax_prefs.settings(prefs), tax.labels(txs))
        year = jurisdiction.tax_year_of(day.isoformat())
        period = jurisdiction.fiscal_year(sales, year, tax.buy_dates(txs), settings)
        return float(period.net_taxable)
    except Exception:  # noqa: BLE001 — the plain realised sum still stands
        return None


def _day_move(tbl, hist) -> tuple[float, float] | None:
    """The "Today" figure the KPI row shows, so the card cannot contradict it.

    In a regular US session the basket's close-to-close day; outside one, the
    per-row day (already re-read from the quote burst) summed against the
    value it moved from.
    """
    if tbl is None or tbl.empty:
        return None
    if not us_market_open():
        moved = float(tbl["day"].dropna().sum())
        value = float(tbl["value"].dropna().sum())
        start = value - moved
        return moved, (moved / start if start else 0.0)
    return basket_change(hist, 1) if hist is not None and not hist.empty else None


def build_facts(paths, prefs: dict, day: date, stored) -> dict | None:
    """What today's card is written from, or None when there is nothing to say.

    Positions, the basket history, the "Today" figure, the earnings pass, the
    52-week scan, the watchlist's alerts and the realised sales — read off the
    same loaders the other Home routes use, so the briefing is written from the
    numbers on the screen beside it and the downloads are the ones those routes
    already paid for. Each input degrades alone: a throttled calendar is a card
    with no earnings line, not a card that is not there.

    None for an account with neither a position nor a watchlist entry: there
    is nothing to brief on.
    """
    db = str(paths.db)
    mtime = loaders.db_mtime(db)
    ccy = reporting_currency(paths)
    positions, realized = [], []
    try:
        _, positions, realized = loaders.ledger_state(db, mtime, ccy)
    except Exception as exc:  # noqa: BLE001 — a watchlist-only card still stands
        obs.warn("daily_action.ledger_unavailable", error_type=type(exc).__name__)
    entries = home.holdings(paths)
    if not (positions or entries):
        return None

    tbl = hist = money = None
    if positions:
        try:
            tbl = home.enriched(db, mtime, ccy)
            hist = loaders.basket_values(db, mtime, ccy).dropna(how="all")
            money = _money(db, mtime, ccy)
        except Exception as exc:  # noqa: BLE001 — alerts and 52w still work
            obs.warn("daily_action.prices_unavailable", error_type=type(exc).__name__)
            tbl = hist = money = None

    owned = {p.ticker for p in positions}
    earn = _reporting(owned, entries)
    events, results = [], []
    try:
        if earn:
            upcoming, printed = loaders.earnings_calendar(earn)
            events, results = list(upcoming), list(printed)
    except Exception:  # noqa: BLE001
        events, results = [], []

    extremes: list = []
    closes: dict[str, list[float]] = {}
    try:
        year = home.year_closes(home.closes_tuple(entries, owned), *home.book(paths))
        extremes = home.scan_extremes(home.extremes_scope(entries, owned), year)
        # The whole year, not the last close: how long an alert has been past
        # its level is what tells a crossing from a state (signals.
        # _alert_signals), and a year of floats is already in hand.
        closes = dict(year)
    except Exception:  # noqa: BLE001
        pass

    # The reader's exit rules, measured on the same closes and positions, and
    # any met today marked hit before the card ranks them.
    rules = journal.safely(_criteria, paths.journal, closes, tbl, day) or []

    return daily.build_facts(
        tbl,
        hist,
        currency=ccy,
        day=_day_move(tbl, hist),
        earnings=events,
        extremes=extremes,
        index=_index(ccy, money) if positions else None,
        money=money,
        # The brief's lines alone: their data is fetched on the job's thread
        # (`start`), so the request is not held for it.
        brief=daily_routines.seeded(daily_routines.load(prefs, paths.chat)),
        signals=signals.candidates(
            holdings=entries,
            tbl=tbl,
            closes=closes,
            realized=realized,
            earnings=events,
            results=results,
            extremes=extremes,
            market=_market(tbl, money, ccy),
            macro=_macro(day, ccy),
            shown=stored.shown if stored else None,
            jurisdiction=_jurisdiction(prefs),
            currency=ccy,
            today=day,
            year_net=_tax_year_net(paths, prefs, ccy, day),
            criteria=rules,
        ),
    )


def _criteria(path, closes: dict, tbl, day: date) -> list[dict]:
    """`journal.measured` for the card, with today's hits written back. A
    guest (whose journal `safely` skips) has no rules to read either."""
    rows = journal.measured(journal.load(path), closes, tbl)
    return journal.mark_hit(path, rows, day)


def _money(db: str, mtime: float, ccy: str) -> pd.DataFrame | None:
    """The book's value and money put in, day by day (`loaders.history`):
    what every figure set beside an index is measured on (`money_change`,
    `index_change`, `daily_book.versus`); None when it has no history yet."""
    hist, _twr, _missing = loaders.history(db, mtime, ccy)
    return None if hist.empty else hist


def _index(currency: str, money: pd.DataFrame | None = None) -> dict | None:
    """The index's day, week and month for the Portfolio section, on the
    book's own money when `money` is given, or None — a section with the
    book's figures alone still stands."""
    try:
        return daily_book.index_facts(_card_closes(), currency, money)
    except Exception as exc:  # noqa: BLE001 — best-effort, like the market block
        obs.warn("daily_action.index_unavailable", error_type=type(exc).__name__)
        return None


def book_chart(paths, lang: str) -> list[dict]:
    """The Portfolio section's month, drawn: the book's value and the same
    money in the index (`daily_book.versus`). Off the loaders `build_facts`
    just warmed, so it costs no download; [] on any failure — the rows still
    stand."""
    from stocks.web.i18n import translate

    db = str(paths.db)
    ccy = reporting_currency(paths)
    try:
        money = _money(db, loaders.db_mtime(db), ccy)
        if money is None:
            return []
        return daily_book.versus(
            money, _closes_since(money.index[0]), ccy,
            label=translate("chat.chart_book", lang),
        )
    except Exception as exc:  # noqa: BLE001
        obs.warn("daily_action.chart_unavailable", error_type=type(exc).__name__)
        return []


def book_compare(paths, lang: str, span: str, index: str) -> list[dict]:
    """The Portfolio section's chart over another window or against another
    index: the book's value beside the same money in the index
    (`daily_book.versus`, off the Portfolio page's own history), so the
    index is bought with the reader's deposits on their days, from the
    book's first day (`_closes_since`). [] when it cannot be drawn."""
    from stocks.web.i18n import translate

    db = str(paths.db)
    mtime = loaders.db_mtime(db)
    ccy = reporting_currency(paths)
    days = daily_book.window_days(span)
    label = translate("chat.chart_book", lang)
    hist, _twr, _missing = loaders.history(db, mtime, ccy)
    closes = _closes_since(None if hist.empty else hist.index[0], index)
    return daily_book.versus(None if hist.empty else hist, closes, ccy,
                             label=label, days=days, index=index)


def _reporting(owned: set[str], entries) -> tuple[str, ...]:
    """The names whose earnings the card follows: held, favourite or tagged,
    coins and funds left out. Sorted, so the calendar's cache key is the same
    for every caller (`loaders.earnings_calendar`)."""
    tags = {h.ticker for h in entries if h.tags}
    favourites = {h.ticker for h in entries if h.favorite}
    return tuple(
        sorted(t for t in owned | favourites | tags if not is_crypto(t) and not _fund(t))
    )


def _printed(paths) -> list:
    """The followed names' prints the calendar knows — the same cached pass
    the card's own earnings line reads (`build_facts`), so the Today page's
    results rows cost no download of their own."""
    return list(loaders.earnings_calendar(_followed(paths))[1])


def _followed(paths) -> tuple[str, ...]:
    """`_reporting` for an account, read again on the job's thread: a
    routine about "my companies' results" means these. () when unreadable."""
    try:
        db = str(paths.db)
        _, positions, _ = loaders.ledger_state(
            db, loaders.db_mtime(db), reporting_currency(paths))
        return _reporting({p.ticker for p in positions}, home.holdings(paths))
    except Exception:  # noqa: BLE001 — the routine falls back to large caps
        return ()


def _sources(paths, prefs: dict, facts: dict) -> daily_routines.Sources:
    """What the brief is answered from, off the API's own cached loaders."""
    from stocks.chat import learnings
    from stocks.portfolio.tax import prefs as tax_prefs

    try:
        tax_code = tax_prefs.resolve(prefs)[0]
    except Exception:  # noqa: BLE001 — no tax calendar, the rest still stands
        tax_code = None
    try:
        notes = tuple(n for n in learnings.load(paths.learnings)
                      if n.kind in daily_routines.NOTE_KINDS)
    except Exception:  # noqa: BLE001
        notes = ()
    return daily_routines.Sources(
        calendar=loaders.earnings_calendar,
        insiders=loaders.insiders,
        eu_insiders=loaders.eu_insiders,
        news=loaders.headlines,
        filings=loaders.current_reports,
        holders=loaders.institutions,
        ex_dividends=loaders.ex_dividends,
        tax_code=tax_code,
        held=tuple(str(r["ticker"]) for r in facts.get("top_weights") or []),
        followed=_followed(paths),
        entries=tuple(home.holdings(paths)),
        notes=notes,
        criteria=tuple(journal.safely(_live_criteria, paths.journal) or ()),
    )


def _closes_on(ticker: str, days: list[date]) -> list[float | None]:
    """The close on or before each of `days` (`journal.ClosesOn`), off the
    cached window download the Review's return columns use."""
    import math

    series = loaders.window_closes(ticker, ",".join(d.isoformat() for d in days))
    values = [float(v) for v in series.tolist()] if len(series) == len(days) else []
    return [None if math.isnan(v) else v for v in values] or [None] * len(days)


def _live_criteria(path) -> list:
    return journal.criteria(journal.load(path))


# How long the card's job may spend on the slow exit rules before it writes
# the card anyway: what is left is checked on the next one.
SLOW_RULES_BUDGET_S = 25.0
# The 8-K items whose own document an event rule reads: an officer leaving,
# and the results release (where a guidance or dividend cut is announced).
_RULE_ITEMS = ("5.02", "2.02", "7.01", "8.01")


def _passages(ticker: str, since: date) -> list[dict]:
    """What an event rule is judged on: `ticker`'s 8-Ks since `since` that
    report an officer change or results (the filing's own words, or the
    release's), and its last days' headlines. A source that cannot be read
    is left out; both failing raises, so the rule waits for the next check."""
    from stocks.data import edgar

    out: list[dict] = []
    failed = 0
    try:
        reports = loaders.current_reports(ticker) or []
    except Exception:  # noqa: BLE001 — the headlines may still say it
        reports, failed = [], failed + 1
    for r in reports:
        if r.filed < since or not set(r.items) & set(_RULE_ITEMS):
            continue
        text = (edgar.earnings_release(ticker, r.filed) if "2.02" in r.items
                else None) or edgar.current_report_text(r.url)
        if text:
            items = ", ".join(r.topics)
            out.append({"source": f"{r.form} ({items})", "day": r.filed.isoformat(),
                        "text": text})
    try:
        news = loaders.headlines(ticker) or []
    except Exception:  # noqa: BLE001
        news, failed = [], failed + 1
    if failed == 2:
        raise RuntimeError("no source could be read")
    out.extend({"source": h.publisher or "news", "day": h.published.isoformat(),
                "text": h.title} for h in news if h.published >= since)
    return out


def _held(paths) -> set[str]:
    """The account's open positions' symbols, re-read on the job's thread."""
    try:
        db = str(paths.db)
        _, positions, _ = loaders.ledger_state(
            db, loaders.db_mtime(db), reporting_currency(paths))
        return {p.ticker for p in positions}
    except Exception:  # noqa: BLE001 — "watched" wording, not a lost line
        return set()


def with_fired(actions: list[dict], fired: list[dict], held: set[str],
               day: date) -> list[dict]:
    """The card's candidate actions with the exit rules the job found met
    today put first, the family's cap kept (`signals._FAMILY_CAP`): the
    reader's own rule outranks anything the app computed."""
    new = [s.to_dict() for s in signals._criterion_signals(fired, held, day)]
    keys = {a["key"] for a in new}
    rest = [a for a in actions if a.get("key") not in keys]
    cap = signals._FAMILY_CAP["criterion"]
    out, crit = [], 0
    for a in [*new, *rest]:
        if a.get("kind") in (signals.CRITERION_HIT, signals.CRITERION_NEAR):
            crit += 1
            if crit > cap:
                continue
        out.append(a)
    return out


def _fund(ticker: str) -> bool:
    """Cache-only fund check — funds do not report earnings."""
    from stocks.data.funds import is_fund

    try:
        return bool(is_fund(ticker, fetch=False))
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------- today


def _review_rows(paths) -> list:
    """The Review page's held rows for this account, off the route itself so
    the verdicts match the page to the figure. Its journal write is left
    unrun: what Today shows is journalled by `_store`."""
    from fastapi import BackgroundTasks

    from stocks.api.routes import review as review_route

    return list(review_route.review(paths, BackgroundTasks()).held)


def _alerted(facts: dict) -> list[str]:
    """Names whose alert or exit rule fired or nearly fired today — their
    news comes first."""
    return [str(a["ticker"]) for a in facts.get("actions") or []
            if isinstance(a, dict) and a.get("ticker")
            and a.get("kind") in (signals.CRITERION_HIT, signals.CRITERION_NEAR,
                                  signals.ALERT_HIT, signals.ALERT_NEAR)]


def gather_today(paths, prefs: dict, facts: dict, lang: str, day: date, stored,
                 reviewed: list | None = None) -> dict:
    """`today_sections.gather` for one account, off the API's cached loaders.

    `reviewed` is filled with the Review rows the comparisons used, for the
    journal. The 8-K source needs `EDGAR_USER_AGENT` (SEC's fair-access
    rule); without it the news section names EDGAR missing.
    """
    import os

    from stocks.web import auth

    db = str(paths.db)
    mtime = loaders.db_mtime(db)
    ccy = reporting_currency(paths)
    weights: dict[str, float] = {}
    try:
        tbl = home.enriched(db, mtime, ccy)
        if tbl is not None and not tbl.empty and "weight" in tbl:
            weights = {str(t): float(w) for t, w in tbl["weight"].items()
                       if finite(w) is not None}
    except Exception as exc:  # noqa: BLE001 — no positions, no sections
        obs.warn("today.positions_unavailable", error_type=type(exc).__name__)

    def verdicts() -> dict[str, dict]:
        rows = _review_rows(paths)
        if reviewed is not None:
            reviewed[:] = rows
        return {r.ticker: {"verdict": r.verdict, "sector": r.sector,
                           "quality": r.quality, "cheapness": r.cheapness}
                for r in rows}

    def closes() -> dict:
        return {**_card_closes(), **loaders.held_closes(db, mtime)}

    filings = None
    if os.environ.get("EDGAR_USER_AGENT"):
        filings = loaders.current_reports
    else:
        obs.warn_once("today.edgar_no_ua")

    def print_source(ticker: str, iso: str) -> dict:
        # The release is read only where EDGAR can be asked at all.
        return _print_source({"ticker": ticker, "date": iso},
                             release=filings is not None)

    return today_sections.gather(
        weights,
        profile=auth.load_profile(prefs),
        alerts=_alerted(facts),
        day=day,
        lang=lang,
        shown=stored.shown if stored else None,
        sources=today_sections.Sources(
            news=loaders.headlines,
            filings=filings,
            insiders=loaders.insiders,
            eu_insiders=loaders.eu_insiders,
            verdicts=verdicts,
            closes=closes,
            results=lambda: _printed(paths),
            print=print_source,
        ),
    )


# --------------------------------------------------------------------- job


def _save_counters(paths, prefs: dict) -> None:
    """Merge the free-allowance counters into prefs.json.

    Merged rather than the whole dict written back: the prefs were read when
    the work started, up to half a minute ago, and a settings change made in
    that window must not be undone by a card.
    """
    counters = {
        k: v for k, v in prefs.items()
        if k.startswith("free_msgs::") or k == daily.UNITS_KEY
    }
    try:
        accounts.update_prefs(paths.prefs, counters)
    except Exception as exc:  # noqa: BLE001 — a lost count, not a lost card
        obs.warn("daily_action.prefs_unsaved", error_type=type(exc).__name__)


def _store(paths, job: Job, prefs: dict, facts: dict, stored, spent: bool,
           reviewed: list | None = None) -> None:
    """Apply a finished generation's side effects.

    The card the reader is shown is stored whoever wrote it: the model's, or
    the computed stand-in when no model answered. Memory is about what the
    reader saw (`daily.to_store` stamps the triggers on screen, so tomorrow's
    card does not say them again), and a computed card left unstored was a day
    the card forgot. `daily.wants_upgrade` is what keeps a stored stand-in
    from ending the day's chances of a real briefing. It is filed in the chat
    too (`daily.record`), for the same reason: what the reader was told.
    """
    from stocks.web import auth

    if spent:
        _save_counters(paths, prefs)
    action = job.action or job.computed
    if action is None or job.abandoned:
        return
    if job.action is None and stored is not None and stored.from_model and daily.is_fresh(
        stored, date.fromisoformat(action.day), action.lang, action.as_of or None
    ) and stored.brief_sig == action.brief_sig:
        # A Regenerate that got nothing back leaves the written card standing
        # rather than swapping it for the stand-in — unless it was written
        # for another brief.
        return
    card = daily.to_store(stored, action, facts)
    card["thread"] = daily.filed(stored, action, paths.chat)
    try:
        auth.save_action(card, paths.action)
    except Exception as exc:  # noqa: BLE001 — the reader still gets the card
        obs.warn("daily_action.unsaved", error_type=type(exc).__name__)
    # The lines that propose something go in the decision journal, with the
    # figures behind each — for the same reason the card is stored at all:
    # this is what the reader was told.
    compared = {t for sec in action.today if sec["id"] == "compare"
                for r in sec["rows"] for t in r["tickers"]}
    shown_rows = [r for r in reviewed or [] if r.ticker in compared]
    journal.safely(journal.record, journal.path_for(paths.chat),
                   journal.from_card(action.entries, facts)
                   + journal.from_today(action.today)
                   + journal.from_review(shown_rows),
                   date.fromisoformat(action.day),
                   judged=journal.judged_in_review(shown_rows))


def spend_for_judge(prefs: dict, spend) -> bool:
    """Charge one exit-rule judgement to the free chain through `spend`, but
    only out of what the card cannot use: the rules are checked before the
    card is written, and a reader on the allowance keeps its FREE_UNITS."""
    if engine.free_left(prefs) <= daily.FREE_UNITS:
        return False
    return spend(prefs)


def start(
    paths,
    prefs: dict,
    facts: dict,
    lang: str,
    day: date,
    stored,
    *,
    key: tuple,
    forced: bool,
) -> Job:
    """Start one generation in a background thread, and wait GRACE_S for it.

    Returns the job either way; `done` says which of the two it is. A job this
    call overtakes (Regenerate while the automatic one is still out) is marked
    abandoned so it cannot store over the reader's fresh request.
    """
    from stocks.web import auth
    from stocks.web.i18n import translate

    chart = book_chart(paths, lang) if facts.get("index") else []
    drawn: dict[int, dict] = {}

    def stand_in() -> daily.DailyAction | None:
        return daily.with_today(
            daily.dressed(daily.computed(facts, lang, day), chart, drawn), facts)

    job = Job(key=key, forced=forced, computed=None if forced else stand_in())
    with _lock:
        previous = _jobs.get(str(paths.root))
        if previous is not None and not previous.done:
            previous.abandoned = True
        _jobs[str(paths.root)] = job

    profile = auth.load_profile(prefs)
    spent = False
    # The Review rows the comparisons were read from: what they show goes in
    # the journal as the Review page's own showing would.
    reviewed: list = []

    def spend(p: dict) -> bool:
        nonlocal spent
        ok = engine.spend_free_quota(p)
        spent = spent or ok
        return ok

    def _gather_brief() -> None:
        """The brief's data, fetched on the job's thread: the reader already
        has the stand-in, saying their card is on its way."""
        routines = daily_routines.load(prefs, paths.chat)
        if not routines:
            return
        try:
            # What the brief needs fetched, planned once per wording.
            routines = routine_plan.ensure(prefs, paths.chat, routines, day,
                                           spend_free=spend)
            found, charts = daily_routines.gather(
                routines,
                watchlist=paths.watchlist,
                db=paths.db,
                base=str(facts.get("currency") or "EUR"),
                translate=lambda k, **kw: translate(k, lang, **kw),
                day=day,
                sources=_sources(paths, prefs, facts),
            )
        except Exception as exc:  # noqa: BLE001 — unanswered, not uncarded
            obs.warn("daily_action.brief_failed", error_type=type(exc).__name__)
            found = {"asks": daily_routines.asks(routines), "missing": ["all"]}
            charts = {}
        facts["brief"] = found
        drawn.update(charts)

    def _gather_today() -> None:
        """The Today page's news, insiders and comparisons, fetched on the
        job's thread like the brief's data."""
        try:
            facts["today"] = gather_today(paths, prefs, facts, lang, day,
                                          stored, reviewed)
        except Exception as exc:  # noqa: BLE001 — the card stands without them
            obs.warn("today.gather_failed", error_type=type(exc).__name__)
            # Stamped all the same, so the card is not rewritten for them.
            facts["today"] = {"shape": today_sections.UNREAD, "sections": []}

    def _check_rules() -> None:
        """The reader's fundamental and event exit rules, checked on the
        job's thread (a statement, the filings, the news and maybe a model
        call), and any met today put on this very card."""
        fired = journal.safely(
            journal.check_slow, paths.journal, day,
            quarters_of=lambda t: _quarters(t)[0],
            passages_of=_passages,
            judge=exit_judge.make_judge(
                prefs, spend_free=lambda p: spend_for_judge(p, spend)),
            budget_s=SLOW_RULES_BUDGET_S,
        ) or []
        if fired:
            facts["actions"] = with_fired(facts.get("actions") or [], fired,
                                          _held(paths), day)

    def work() -> None:
        try:
            _gather_brief()
            _gather_today()
            _check_rules()
            # What the card proposed about today's names before, and what
            # came of it: a move the reader declined or let lapse is not
            # worth the same words again. Settled off the ledger first, so
            # a sale made yesterday reads as followed today.
            decisions = journal.path_for(paths.chat)
            journal.safely(journal.settle_from_db, decisions, paths.db, day)
            history = journal.safely(journal.history_for, decisions,
                                     daily.talked_names(facts), day) or []
            job.action = daily.with_today(daily.dressed(
                daily.generate(
                    prefs,
                    profile,
                    facts,
                    lang,
                    day,
                    recent=stored.recent if stored else [],
                    past=stored.past if stored else [],
                    history=history,
                    spend_free=spend,
                    chat_path=paths.chat,
                ),
                chart,
                drawn,
            ), facts)
        except Exception as exc:  # noqa: BLE001 — generate swallows its own; a
            # thread that died silently would leave the client polling forever.
            obs.warn(
                "daily_action.generate_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
        finally:
            try:
                if job.action is None and (job.computed is None or facts.get("brief")
                                           or facts.get("today")):
                    # A forced job that got nothing still owes the reader a
                    # card: the computed one, built now rather than up front
                    # so a Regenerate shows its wait line and not a stand-in.
                    # A brief no model wrote is rebuilt too, so the card
                    # says it was missed rather than still on its way.
                    job.computed = stand_in()
                _store(paths, job, prefs, facts, stored, spent, reviewed)
            finally:
                # Last, so a poll that sees `done` also sees the stored file.
                job.done = True
            # After the card is out, so no reader waits on it: the price read
            # back on the moves proposed a month and a quarter ago.
            journal.safely(journal.mark_outcomes, journal.path_for(paths.chat),
                           _closes_on, day)
            _review_memories()

    def _review_memories() -> None:
        """The weekly tidy-up of the saved memories, when it is due: on a
        thread of its own, after the card, which never waits for it."""
        from stocks.chat import memory_review

        try:
            memory_review.start(prefs, paths.chat, day=day.isoformat())
        except Exception as exc:  # noqa: BLE001 — a tidy-up never costs a card
            obs.warn("chat.memory_review.start_failed",
                     error_type=type(exc).__name__)

    thread = threading.Thread(target=work, name="daily-action", daemon=True)
    thread.start()
    thread.join(GRACE_S)
    return job


def now_day() -> tuple[datetime, date]:
    """The server's local now and the action day it falls in.

    The server's zone stands in for the reader's, as `GET /daily` has always
    done: the deploy runs in the zone its readers are in, and the card's
    freshness is judged on the day it was stamped with, not on a clock.
    """
    now = datetime.now().astimezone()
    return now, daily.action_day(now)


# ------------------------------------------------------------------ analysis
# The analysis behind one line, written on the reader's click. Synchronous:
# the reader asked and is watching the line for it, so there is no job to
# poll — one fetch and one call, a lock per account and line so a double click
# cannot pay twice, and the answer stored with the card so the second opening
# (and every other device) reads it for free.

_analysis_locks: dict[tuple[str, str], threading.Lock] = {}


def _analysis_lock(paths, key: str) -> threading.Lock:
    with _lock:
        return _analysis_locks.setdefault((str(paths.root), key), threading.Lock())


def _read_card(paths) -> daily.DailyAction | None:
    from stocks.web import auth

    return daily.DailyAction.from_dict(auth.load_action(paths.action))


@ttl_cache(6 * 3600.0, max_entries=64)
def _quarters(ticker: str) -> tuple[list, str | None]:
    """(quarters newest-first, their filing currency) — `routes.earnings`'s
    `_statements`, the same yfinance statement the result dialog reads."""
    from stocks.data.earnings import fetch_quarters, fetch_statement_currency

    quarters = fetch_quarters(ticker)
    return quarters, fetch_statement_currency(ticker) if quarters else None


@ttl_cache(6 * 3600.0, max_entries=64)
def _release(ticker: str, iso: str) -> str | None:
    from stocks.data import edgar

    return edgar.earnings_release(ticker, date.fromisoformat(iso))


def _print_source(action: dict, release: bool = True) -> dict:
    """What a print's paragraph can quote beyond EPS: the quarter's revenue
    and margin, and the company's own press release (US filers). `release`
    False leaves the release unread — a caller without `EDGAR_USER_AGENT`
    would only cache the refusal as "no release" (`edgar.earnings_release`)."""
    from stocks.data.earnings import match_quarter, pct_change, year_ago

    ticker = str(action.get("ticker") or "")
    source: dict = {"ticker": ticker}
    try:
        day = date.fromisoformat(str(action.get("date") or ""))
    except ValueError:
        return source
    try:
        quarters, currency = _quarters(ticker)
        quarter = match_quarter(quarters, day) if quarters else None
    except Exception:  # noqa: BLE001 — a throttled statement is no revenue line
        quarter, currency = None, None
    if quarter is not None and quarter.revenue:
        back = year_ago(quarters, quarter)
        yoy = pct_change(quarter.revenue, back.revenue if back else None)
        source |= {
            "quarter_end": quarter.end.isoformat(),
            "currency": currency or "USD",
            "revenue": round(float(quarter.revenue), 2),
            # The same figure in the units a paragraph writes it in, so "$96.2
            # billion" passes the audit as the number it is.
            "revenue_bn": round(float(quarter.revenue) / 1e9, 2),
            "revenue_mn": round(float(quarter.revenue) / 1e6, 1),
            "revenue_yoy_pct": None if yoy is None else round(yoy * 100, 1),
        }
        if quarter.operating_margin is not None:
            source["operating_margin_pct"] = round(quarter.operating_margin * 100, 1)
    text = _release(ticker, day.isoformat()) if release else None
    if text:
        source["release"] = text
        source["release_figures"] = daily.figures(text)
    return source


def _rate_source(action: dict) -> dict:
    """A rate paragraph's history: the bank's last few moves, off the series
    the card already downloaded."""
    from stocks.data import macro_calendar as cal

    bank = str(action.get("bank") or "")
    ids = cal.RATE_SERIES.get(bank, ())
    if not ids:
        return {}
    try:
        series = _rates(tuple(ids))[ids[-1]].dropna()
    except Exception:  # noqa: BLE001
        return {}
    moves = series[series.diff().fillna(1.0) != 0]
    return {
        "bank": bank,
        "history": [
            {"date": str(pd.Timestamp(i).date()), "rate": round(float(v), 2)}
            for i, v in moves.tail(4).items()
        ],
    }


def _analysed(paths, key: str) -> tuple[daily.DailyAction | None, dict | None]:
    """(the stored card, its stored analysis of `key` or None). The card is
    None when there is none, or no line `key` with a trigger behind it."""
    card = _read_card(paths)
    if card is None or key not in daily.keyed_actions(card.facts):
        return None, None
    return card, card.analysis.get(key) or None


def analysis(paths, prefs: dict, key: str) -> tuple[daily.DailyAction, dict] | None:
    """(the stored card, its analysis of line `key`), written if it has to be.
    None when there is no card, or no line `key` with a trigger behind it.

    The evidence is fetched (`api/evidence.py`), the model writes the verdict
    and the points from it, and the computed ones stand in when no model
    answers or every answer fails the audit — so this always ends in an
    analysis. Stored only onto the card it was written for: a card replaced
    while this ran keeps its own, and the reader still gets this one.
    """
    from stocks.api import evidence
    from stocks.chat import daily_analysis
    from stocks.web import auth

    card, body = _analysed(paths, key)
    if card is None:
        return None
    if body:
        return card, body
    with _analysis_lock(paths, key):
        # Again under the lock: a double click waited here for the first.
        card, body = _analysed(paths, key)
        if card is None:
            return None
        if body:
            return card, body
        found = evidence.gather(paths, card, key)
        spent = False

        def spend(p: dict) -> bool:
            nonlocal spent
            ok = engine.spend_free_quota(p)
            spent = spent or ok
            return ok

        written = daily_analysis.generate(
            prefs, auth.load_profile(prefs), card, key, found, card.lang,
            spend_free=spend, chat_path=paths.chat,
        )
        if spent:
            _save_counters(paths, prefs)
        body = daily_analysis.record(card, key, found, written, card.lang)
        # Read, merge, write under the account's own lock ("" is no line's
        # key): two lines opened at once must not store over each other.
        with _analysis_lock(paths, ""):
            raw = auth.load_action(paths.action)
            if raw.get("day") == card.day and raw.get("generated") == card.generated:
                stored = raw.get("analysis")
                stored = stored if isinstance(stored, dict) else {}
                raw["analysis"] = {**stored, key: body}
                try:
                    auth.save_action(raw, paths.action)
                except Exception as exc:  # noqa: BLE001 — the reader still gets it
                    obs.warn(
                        "daily_action.analysis_unsaved", error_type=type(exc).__name__
                    )
        # The reader opened the reasoning behind a proposal: its verdict is
        # kept on the journal entry, so the proposal reads with its argument.
        journal.safely(journal.attach, journal.path_for(paths.chat), "daily", key,
                       str(body.get("verdict") or ""))
        return replace(card, analysis={**card.analysis, key: body}), body


# ------------------------------------------------------------- market read
# The Today page's shared market read is written by the morning cron
# (`stocks today-market`). When a reader finds it missing, a session behind,
# or without their language, the API writes it once on a background thread:
# the request answers with whatever is stored (or none) and `market_stale`,
# and the page re-asks. One build per process at a time, and a failed one is
# not retried for `today_market.MIN_REBUILD_S` — a holiday or a throttled
# download must not cost a free-chain unit per page view.

_market_lock = threading.Lock()
_market_tried: dict[str, float] = {}


def _market_build(kind: str, lang: str) -> None:
    from stocks.chat import today_market

    try:
        with obs.timed("today.market_lazy", kind=kind, lang=lang):
            today_market.run(None, (lang,), refetch=kind == "refetch")
    except Exception as exc:  # noqa: BLE001 — the stored read keeps serving
        obs.warn("today.market_lazy_failed", kind=kind,
                 error_type=type(exc).__name__, error=str(exc)[:200])
    finally:
        loaders.today_market.cache_clear()  # ty: ignore[unresolved-attribute]
        _market_lock.release()


def market_day(lang: str, *, now: float | None = None) -> tuple[dict | None, bool]:
    """(the market read for `lang` as `today_market.card` shapes it, whether a
    newer one is on its way). Never fetches or calls a model on the request."""
    from stocks.chat import today_market

    stored = loaders.today_market()
    now = time.time() if now is None else now
    behind = today_market.stale(stored, today_market.expected_session(), now)
    card = today_market.card(stored, lang) if stored else None
    kind = "refetch" if behind else ("lang" if card is None else "")
    if behind and stored and now - float(stored.get("built_at") or 0) \
            > today_market.STALE_AFTER_S:
        obs.warn_once("today.cron_absent", key=stored.get("session") or "")
    if not kind:
        return card, False
    # A language another reader's build added counts as the same attempt.
    tried = _market_tried.get(kind if kind == "refetch" else f"lang:{lang}", 0.0)
    if now - tried < today_market.MIN_REBUILD_S:
        return card, _market_lock.locked()
    if not _market_lock.acquire(blocking=False):
        return card, True
    _market_tried[kind if kind == "refetch" else f"lang:{lang}"] = now
    _market_start(kind, lang)
    return card, True


def _market_start(kind: str, lang: str) -> None:
    """Start the build; it releases `_market_lock` when it ends. A seam: the
    test suite swaps it for one that fetches nothing."""
    threading.Thread(
        target=_market_build, args=(kind, lang), name="today-market", daemon=True
    ).start()
