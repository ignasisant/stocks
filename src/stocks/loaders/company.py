"""What a company reports and who trades it: earnings, statements,
estimates, options, insiders, headlines and filings.
"""

from __future__ import annotations

import threading
import time
from datetime import date

from stocks import obs
from stocks.analysis import kpis
from stocks.cache import disk_path, read_entry, ttl_cache, write_entry
from stocks.loaders.bars import _EVENTS_TTL
from stocks.loaders.names import display_symbol
from stocks.loaders.search import sec_title


# `disk_max` on the per-name memos below: the memo directory is RAM on Cloud
# Run (`cache.MEMO_DIR`), and eight memos each keeping the default 256 files
# was tens of MB of the 1 GiB for names nobody had opened in a week.
@ttl_cache(_EVENTS_TTL, max_entries=64, persist="earnings", disk_max=64)
def earnings(ticker: str):
    """(all known earnings dates, reported results) — one yfinance pass.

    Never raises: Yahoo throttles shared cloud IPs hard, and a calendar is
    garnish on a price chart. An empty answer degrades the markers; an
    exception would take the whole response down with them.
    """
    from stocks.data.earnings import fetch_earnings

    try:
        return fetch_earnings(ticker)
    except Exception as exc:
        obs.warn(
            "api.earnings_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return [], []


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="fundamentals", disk_max=64)
def fundamentals(ticker: str):
    """One yfinance fundamentals pull: info, income statements, cash flow.

    Three sections of the page read it — the KPI grid, the financials charts
    and the moat score — and each used to be its own cached call. One pull,
    one cache entry, three derivations.
    """
    from stocks.data import esef
    from stocks.data.fundamentals import fetch_fundamentals

    # EU/UK issuers' audited annual statements (ESEF) over Yahoo's. Disk only:
    # the first sight of a name returns Yahoo's frames and fetches the filing
    # in the background, so no page waits on it.
    return esef.overlay(fetch_fundamentals(ticker))


# The review page scores a whole book plus its watchlist — fifty names is a
# normal account — off the ticker page's KPIs. Holding each name's frames for
# that would blow `fundamentals`' cap (and memory) every visit, so the review
# keeps only the derived KPI dict: a few hundred bytes a name, a day old at
# worst. Statements move quarterly and the price-led ratios by a few percent
# a day, which no verdict threshold notices. A stale entry answers at once
# while it refreshes; the gate keeps those refreshes from leaving as one burst.
_METRICS_TTL = 4 * 3600.0
_metrics_gate = threading.BoundedSemaphore(6)


# The persisted name carries the metrics' version (`kpis.VERSION`): entries
# are mirrored to the bucket and read back by a new process, so a dict built
# before a KPI was added or redefined would otherwise be scored, and recorded
# in the map's history, for up to a day after the deploy that changed them.
@ttl_cache(
    _METRICS_TTL,
    max_entries=256,
    stale_s=20 * 3600.0,
    persist=f"review_metrics-{kpis.VERSION}",
)
def review_metrics(ticker: str) -> dict:
    """`compute_metrics` over `fundamentals(ticker)`, memoized as the dict."""
    from stocks.analysis.fundamentals import compute_metrics

    with _metrics_gate:
        return compute_metrics(fundamentals(ticker))


# Where each name's business stood at its last few filings, for the review
# map's "then" point. A filing lands once a quarter at most, so a day is fresh
# and a week still right; kept apart from `review_metrics` so the API's row
# metrics stay today's. Versioned with it: each entry is `compute_metrics`
# dicts, scored by the same lens.
@ttl_cache(
    24 * 3600.0,
    max_entries=256,
    stale_s=7 * 86400.0,
    persist=f"review_history-{kpis.VERSION}",
    disk_max=128,
)
def review_history(ticker: str) -> list[dict]:
    """`filed_history` over `fundamentals(ticker)`: [{filed, then, base}]."""
    from stocks.analysis.fundamentals import filed_history

    with _metrics_gate:
        return filed_history(fundamentals(ticker))


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="estimates", disk_max=64)
def estimates(ticker: str):
    """Analyst price targets, EPS/revenue consensus and ratings.

    Degrades to an empty RawEstimates per field rather than raising, so a name
    with no coverage renders as "no consensus" instead of failing the request.
    """
    from stocks.data.estimates import fetch_estimates

    return fetch_estimates(ticker)


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="rating_changes", disk_max=64)
def rating_changes(ticker: str) -> list[dict]:
    """Recent upgrades, downgrades, initiations and target changes, newest first.

    A refusal raises (never memoized as "no changes"); a name Yahoo has no
    coverage for answers `[]`.
    """
    from stocks.data.estimates import fetch_rating_changes
    from stocks.data.estimates import rating_changes as fold

    return fold(fetch_rating_changes(ticker), date.today())


# How long the last in-session options reading answers while the market is
# shut: a long weekend, Friday's close to Tuesday's open, and a little over.
_SESSION_KEEP_S = 5 * 86400.0


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="options", disk_max=64)
def options_view(ticker: str) -> dict | None:
    """ATM implied volatility and put/call ratios; None when nothing is listed.

    Cold this is an expiry list plus up to four chains (~3-6 s), which is why
    it has its own endpoint and slot. A refusal raises, so a throttled minute
    is never cached as "no options".
    """
    from stocks.data.options import closed, fetch_chains, summarize

    raw = fetch_chains(ticker)
    path = disk_path("options_session", (ticker,))
    if closed(raw):
        # Out of session the chain is zeroed; the last in-session reading is
        # what the market said, and it is still the latest thing it said.
        kept = read_entry(path, 0.0)
        if kept is not None and time.time() - kept[2] < _SESSION_KEEP_S:
            return kept[1]
        return None
    view = summarize(raw, date.today())
    if view is not None:
        with obs.swallow("options.keep_session"):
            write_entry(path, (time.monotonic(), view, time.time()))
    return view


@ttl_cache(_EVENTS_TTL, max_entries=32, persist="valuation", disk_max=64)
def valuation(ticker: str) -> dict:
    """P/E reconstructed against its own history: {source, pe, stats, current}.

    `source` says which filing feed backed it — SEC EDGAR, FMP, or None when
    neither yields quarterly EPS. A client has to print that: a multiple with
    no provenance is a number somebody will act on.
    """
    from stocks.analysis.pe_history import pe_vs_history

    try:
        return pe_vs_history(ticker)
    except Exception as exc:
        obs.warn(
            "api.pe_history_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return {"source": None, "pe": None, "stats": None, "current": None}


@ttl_cache(_EVENTS_TTL, max_entries=32)
def insiders(ticker: str):
    """Recent Form 4 lines, newest filing first; [] when the feed says nothing.

    US filers only through this path. The EU regulators publishing the same
    disclosure are `data.bafin` and `data.cnmv`, which the route folds in separately.
    """
    from stocks.data.insiders import insider_transactions

    try:
        return insider_transactions(ticker)
    except Exception as exc:
        obs.warn(
            "api.insiders_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return []


def issuer_name(ticker: str) -> str | None:
    """The company name a register or a headline is searched by.

    Yahoo's `longName` first. Then the fund catalog and the SEC map, without
    any watchlist: a name somebody typed on their own list is theirs, not the
    company's. Rarely reached: the common miss is Yahoo throttled, and a German
    issuer is then usually in neither list, so the caller says "not covered"
    rather than guessing.
    """
    issuer = str(fundamentals(ticker).info.get("longName") or "").strip()
    if issuer:
        return issuer
    try:
        from stocks.data.funds import fund_name

        resolved = display_symbol(ticker)
        return fund_name(resolved) or sec_title(resolved)
    except Exception:
        return None


@ttl_cache(_EVENTS_TTL, max_entries=32)
def _bafin_insiders(ticker: str):
    from stocks.data.bafin import insider_transactions

    issuer = issuer_name(ticker)
    return insider_transactions(ticker, issuer=issuer) if issuer else []


# CNMV reads PDFs in the background and report whether they all got read: a
# complete list is kept like any event feed, a partial one only briefly so the
# next load picks up what the workers have memoised since.
_CNMV_PARTIAL_TTL = 60.0
_CNMV_MAX = 32
_cnmv_cache: dict[str, tuple[float, list]] = {}
_cnmv_lock = threading.Lock()


def _cnmv_insiders(ticker: str):
    from stocks.data import cnmv

    key = ticker.upper()
    now = time.monotonic()
    with _cnmv_lock:
        hit = _cnmv_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    issuer = issuer_name(ticker)
    rows, complete = cnmv.read(ticker, issuer=issuer) if issuer else ([], True)
    ttl = _EVENTS_TTL if complete else _CNMV_PARTIAL_TTL
    with _cnmv_lock:
        if len(_cnmv_cache) >= _CNMV_MAX:
            _cnmv_cache.pop(min(_cnmv_cache, key=lambda k: _cnmv_cache[k][0]))
        _cnmv_cache[key] = (time.monotonic() + ttl, rows)
    return rows


def eu_insiders(ticker: str):
    """Art. 19 MAR notifications for a German (BaFin) or Spanish (CNMV) issuer,
    searched by the company's name; [] for any other listing, a name not found
    or a failed search (the registers' readers never raise)."""
    from stocks.data.bafin import german_listing
    from stocks.data.cnmv import spanish_listing

    if german_listing(ticker):
        return _bafin_insiders(ticker)
    if spanish_listing(ticker):
        return _cnmv_insiders(ticker)
    return []


def _clear_eu_insiders() -> None:
    getattr(_bafin_insiders, "cache_clear", lambda: None)()
    with _cnmv_lock:
        _cnmv_cache.clear()


@ttl_cache(3600.0, max_entries=64)
def headlines(ticker: str):
    """The last days' headlines that name `ticker`'s company (`data.news`).
    The SEC map's title first — a local file, no request — then Yahoo's name.
    Raises on a failed search."""
    from stocks.data import edgar, news

    try:
        name = edgar.title_for(ticker)
    except Exception:  # noqa: BLE001 — the name is a help, not a need
        name = None
    if not name:
        try:
            name = issuer_name(ticker)
        except Exception:  # noqa: BLE001
            name = None
    return news.headlines(ticker, name)


# 8-Ks are read a month back and narrowed by the caller: one cached feed per
# name serves a Monday card and a Thursday one alike.
FILINGS_DAYS = 30


@ttl_cache(10800.0, max_entries=64)
def current_reports(ticker: str):
    """`ticker`'s 8-Ks over FILINGS_DAYS (`data.edgar`); [] for a name that
    does not file with the SEC. Raises on a refused request."""
    from datetime import timedelta

    from stocks.data import edgar

    return edgar.current_reports(ticker, date.today() - timedelta(days=FILINGS_DAYS))


@ttl_cache(86400.0, max_entries=64)
def institutions(ticker: str):
    """`ticker`'s institutional holders (`data.holders`), or None. A day's
    ttl: the figures move once a quarter. Raises on a failed request."""
    from stocks.data import holders

    return holders.institutions(ticker)
