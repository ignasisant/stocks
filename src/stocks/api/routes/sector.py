"""Sector cohorts: who a company is actually comparable to, and who wins.

Market-wide, so these two take no account — same shape as `/quotes` and
`/comparables`. A client that wants to mark the rows it already holds joins
them against `/portfolio/positions` itself; putting an account on a cohort
every reader shares would make a shared file look personal.

The written verdict under the podium is one write here: a generated answer
with a per-account daily budget. `GET …/verdict` serves what is stored (or the
computed stand-in) and never spends; `POST …/verdict` writes one.

The other is the live rescan — the Streamlit page's "refresh this sector"
button. `POST …/rescan` starts one sector's scan in a background thread and
answers at once; `GET …/rescan` is what a client polls until it lands.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from stocks import accounts
from stocks.analysis import sectors as sector_scan
from stocks.analysis.screener import DEFAULT_COLUMNS, LOWER_IS_BETTER, METRIC_ORDER
from stocks.analysis.sectors import SECTORS
from stocks.analysis.sentiment import SECTOR_ETFS
from stocks.api import loaders
from stocks.api.deps import Account, Writer
from stocks.api.jsonsafe import num as _num
from stocks.api.schemas import (
    CohortRow,
    SectorCohort,
    Sectors,
    SectorSummary,
)

router = APIRouter(tags=["sector"])

# The page's own default: rank on return on invested capital, best first. A
# cohort ordered by nothing in particular reads as a list of tickers.
_DEFAULT_SORT = "roic"


def _resolve(name: str) -> str:
    """The canonical spelling of a sector, or 404.

    Matched case-insensitively because a sector arrives in a URL, where nobody
    types "Consumer Defensive" with the capitals intact — but it is resolved to
    the catalog's own spelling before anything reads it, since that spelling is
    what `info["sector"]` joins on.
    """
    for sector in SECTORS:
        if sector.casefold() == name.casefold():
            return sector
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown sector: {name}"
    )


# ------------------------------------------------------------ the live rescan
# One sector rebuilt on demand, held in this process beside the nightly file.
#
# In memory and not merged into `sector_scan.json`, which is what the Streamlit
# button does too (its `_live` is a cache entry, never a save): the stored file
# is the nightly job's, it is mirrored to the bucket, and a reader's click
# should not be what publishes a cohort to every other instance. A live scan
# wins only while it is at least as new as the stored one — the next nightly
# run supersedes it without anybody having to evict it.
_live: dict[str, sector_scan.SectorScan] = {}
_jobs: dict[str, RescanStatus] = {}
_jobs_lock = threading.Lock()

# A rescan is one sector's cohort at five Yahoo requests a company — about a
# minute, and exactly the burst that got this project throttled from a
# datacenter IP once. A handful an hour per account is a reader checking, not
# a loop. Keyed apart from the chat budget: spending one must not starve the
# other.
RESCAN_MAX = 4
RESCAN_WINDOW_S = 3600


def _scans() -> dict:
    """The stored nightly scans, with any fresher live rescan laid over them.

    ISO dates compare as strings, so "at least as new" needs no parsing. A tie
    goes to the live scan: the nightly job runs before the day starts, so a
    rescan dated the same day was fetched after it — and it carries the
    nightly cohort's own widened peers (see `_rescan`), so it is never the
    narrower of the two. Tomorrow's nightly file is dated later and wins.
    """
    stored = dict(loaders.sector_scans())
    for name, scan in list(_live.items()):
        kept = stored.get(name)
        if kept is None or not kept.tickers or scan.as_of >= kept.as_of:
            stored[name] = scan
    return stored


@router.get("/sectors", response_model=Sectors, summary="Every sector, scanned or not")
def sectors() -> Sectors:
    """All eleven, including the ones the nightly scan has not reached.

    A sector with no scan comes back with `as_of: null` and an empty cohort
    rather than being left out: "not scanned yet" and "does not exist" are
    different answers, and a picker built from this list has to offer both.
    """
    scans = _scans()
    return Sectors(
        sectors=[
            SectorSummary(
                sector=name,
                etf=SECTOR_ETFS.get(name, ""),
                as_of=scan.as_of if (scan := scans.get(name)) else None,
                cohort=len(scan.tickers) if scan else 0,
                podium=list(scan.podium) if scan else [],
            )
            for name in SECTORS
        ]
    )


@router.get(
    "/sectors/{sector}",
    response_model=SectorCohort,
    summary="One sector's cohort, ranked",
)
def cohort(
    sector: str,
    sort: Annotated[
        str, Query(description=f"Metric to rank by; default {_DEFAULT_SORT}.")
    ] = _DEFAULT_SORT,
    ascending: Annotated[
        bool | None,
        Query(
            description=(
                "Sort direction. Left out, it follows `lower_is_better` for the "
                "metric, so the most attractive row is always first."
            )
        ),
    ] = None,
) -> SectorCohort:
    """The cohort with its raw numbers, ordered, plus what a table needs to
    redraw it without asking again — the metric keys, the default columns and
    which metrics read better small.

    Numbers only. The labels are localized and come from `/i18n/{lang}` under
    `kpi.<key>.label`, which is where the pages read them too, so this endpoint
    never has to know what language anyone is in.
    """
    name = _resolve(sector)
    if sort not in METRIC_ORDER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unknown metric: {sort}",
        )
    descending = not (ascending if ascending is not None else sort in LOWER_IS_BETTER)

    shell = SectorCohort(
        sector=name,
        etf=SECTOR_ETFS.get(name, ""),
        sort=sort,
        ascending=not descending,
        metric_keys=list(METRIC_ORDER),
        default_columns=[c for c in DEFAULT_COLUMNS if c in METRIC_ORDER],
        lower_is_better=sorted(LOWER_IS_BETTER & set(METRIC_ORDER)),
    )
    scan = _scans().get(name)
    if scan is None or not scan.tickers:
        return shell

    rows = [
        CohortRow(
            ticker=str(metrics.get("ticker") or "").upper(),
            score=_num(scan.scores.get(str(metrics.get("ticker") or "").upper())),
            metrics={key: _num(metrics.get(key)) for key in METRIC_ORDER},
        )
        for metrics in scan.metrics
    ]
    # A row with no value for the sort metric sinks to the bottom whichever way
    # the rest is going — same rule as `screener.rank`. Sorting it as zero would
    # put "we could not measure this" at the top of a cheapness ranking.
    def order(row: CohortRow) -> tuple[bool, float]:
        value = row.metrics.get(sort)
        return (value is None, -(value or 0.0) if descending else (value or 0.0))

    rows.sort(key=order)
    for place, row in enumerate(rows, start=1):
        row.rank = place

    shell.as_of = scan.as_of
    shell.podium = list(scan.podium)
    shell.rows = rows
    return shell


# ----------------------------------------------------------- the verdict


class SectorVerdict(BaseModel):
    """One sector's written read, or the computed stand-in for one.

    `written` is the whole distinction a client has to draw: True when a model
    wrote this against tonight's scan and it was checked figure by figure
    (`sector_ai.audit`), False when nothing was generated and this is what the
    podium cannot say for itself. The stand-in is always there, so a page never
    has to render "no verdict" as a hole.
    """

    sector: str
    as_of: str
    lang: str
    headline: str
    bullets: list[str]
    written: bool


def _held(db) -> tuple[str, ...]:
    """Open positions, for the "you already own this one" line. Offline:
    quantities need no FX, and an unreadable ledger holds nothing."""
    try:
        from stocks.portfolio.ledger import all_transactions
        from stocks.portfolio.positions import build

        positions, _ = build(all_transactions(db), to_base=lambda a, c, d: a)
        return tuple(p.ticker for p in positions)
    except Exception:
        return ()


def _answer(verdict, *, written: bool) -> SectorVerdict:
    return SectorVerdict(
        sector=verdict.sector,
        as_of=verdict.as_of,
        lang=verdict.lang,
        headline=verdict.headline,
        bullets=list(verdict.bullets),
        written=written,
    )


def _stored(paths, scan, lang: str):
    """The verdict already paid for, if it read this scan in this language.

    Keyed by (sector, the scan's date, language), as the Streamlit card keys it:
    re-opening a sector the same night is free, and a new nightly scan is what
    makes a read worth paying for again. Only a model's answer is ever stored —
    a stand-in is free to rebuild, and keeping one would block the upgrade to a
    real read once the allowance resets.
    """
    from stocks.chat import sector_ai
    from stocks.web import auth

    raw = auth.load_verdicts(paths.verdicts).get(scan.sector)
    if not isinstance(raw, dict):
        return None
    verdict = sector_ai.Verdict.from_dict(raw)
    fresh = (verdict.sector, verdict.as_of, verdict.lang) == (
        scan.sector, scan.as_of, lang
    )
    return verdict if fresh and verdict.source == "llm" else None


def _scan_or_404(name: str):
    scan = _scans().get(name)
    if scan is None or not scan.tickers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{name} has not been scanned yet",
        )
    return scan


def _lang(paths, asked: str | None) -> str:
    prefs = accounts.load_prefs(paths.prefs)
    return (asked or prefs.get("language") or "en").strip().lower()


@router.get(
    "/sectors/{sector}/verdict",
    response_model=SectorVerdict,
    summary="The written read under the podium, if one is stored",
)
def verdict(
    sector: str,
    paths: Account,
    lang: Annotated[str | None, Query(max_length=8)] = None,
) -> SectorVerdict:
    """The stored read when there is one for tonight's scan, else the stand-in.

    Spends nothing, ever: a GET that could charge the allowance would be a GET
    a prefetch could empty. Asking for one to be written is the POST.
    """
    from stocks.chat import sector_ai

    scan = _scan_or_404(_resolve(sector))
    code = _lang(paths, lang)
    stored = _stored(paths, scan, code)
    if stored is not None:
        return _answer(stored, written=True)
    facts = sector_ai.build_facts(scan, _held(paths.db))
    return _answer(sector_ai.computed(facts, code), written=False)


@router.post(
    "/sectors/{sector}/verdict",
    response_model=SectorVerdict,
    summary="Have the read written",
)
def write_verdict(
    sector: str,
    paths: Writer,
    lang: Annotated[str | None, Query(max_length=8)] = None,
) -> SectorVerdict:
    """Write the read for tonight's scan, spending one unit of the allowance.

    Answered in the request rather than queued: the generation is bounded by
    `sector_ai.TIMEOUT_S` (the daily card's budget), and a client already has
    a skeleton to hold the space for that long. A stored read for the same
    scan is returned without spending anything, so pressing twice costs once.

    When no model answers — no provider, allowance gone, every backend down —
    the stand-in comes back with `written: false` rather than an error: the
    reader asked for a read and gets the one that exists.
    """
    from stocks.chat import engine, sector_ai
    from stocks.web import auth

    scan = _scan_or_404(_resolve(sector))
    code = _lang(paths, lang)
    stored = _stored(paths, scan, code)
    if stored is not None:
        return _answer(stored, written=True)

    facts = sector_ai.build_facts(scan, _held(paths.db))
    prefs = accounts.load_prefs(paths.prefs)
    spent = False

    def spend(p: dict) -> bool:
        nonlocal spent
        ok = engine.spend_free_quota(p)
        spent = spent or ok
        return ok

    written = sector_ai.generate(prefs, facts, code, spend_free=spend)
    if spent:
        auth.save_prefs(prefs, paths.prefs)
    if written is None:
        return _answer(sector_ai.computed(facts, code), written=False)
    kept = auth.load_verdicts(paths.verdicts)
    kept[written.sector] = written.to_dict()
    auth.save_verdicts(kept, paths.verdicts)
    return _answer(written, written=True)


# ------------------------------------------------------------ the rescan


class RescanStatus(BaseModel):
    """Where one sector's live rescan stands.

    Shared across readers, like the cohort it rebuilds: two people pressing
    the button on the same sector get the same job, not two bursts of Yahoo.
    `idle` means nothing was asked since this process started — which is also
    what a poll landing on a fresh instance sees, and the client treats it as
    "finished, reload".
    """

    sector: str
    state: str = Field(description="idle | running | done | failed")
    started_at: str | None = None
    finished_at: str | None = None
    as_of: str | None = Field(
        default=None, description="The rebuilt cohort's date, once it landed."
    )
    cohort: int = Field(default=0, description="Companies the rescan scored.")
    reason: str | None = Field(
        default=None,
        description=(
            "Why a failed rescan failed: rate_limited | offline | no_data | "
            "error. The stored cohort still stands either way."
        ),
    )


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _why(exc: Exception) -> str:
    from urllib.error import URLError

    from yfinance.exceptions import YFRateLimitError

    if isinstance(exc, YFRateLimitError):
        return "rate_limited"
    return "offline" if isinstance(exc, URLError | OSError) else "error"


def _rescan(name: str) -> None:
    """The job: scan one sector and lay it over the stored one.

    The stored cohort's own tickers ride along as `extra`. The Streamlit
    button rescans the ETF basket alone, which silently drops the non-US peers
    the nightly job validated — a refresh that shrinks the cohort is not a
    refresh. They were validated when they were proposed, so passing them back
    is exactly the contract `scan_sector` asks of `extra`.
    """
    from stocks import obs

    kept = loaders.sector_scans().get(name)
    extra = tuple(kept.tickers) if kept else ()
    try:
        scan = sector_scan.scan_sector(name, extra)
    except Exception as exc:
        obs.warn("sector.rescan_failed", sector=name,
                 error_type=type(exc).__name__, error=str(exc)[:200])
        outcome = {"state": "failed", "reason": _why(exc)}
    else:
        if scan.tickers:
            _live[name] = scan
            outcome = {"state": "done", "as_of": scan.as_of,
                       "cohort": len(scan.tickers)}
        else:
            # Yahoo dropped the basket. Laying an empty cohort over a good one
            # would turn a failed refresh into a missing sector.
            outcome = {"state": "failed", "reason": "no_data"}
    with _jobs_lock:
        _jobs[name] = _jobs[name].model_copy(
            update={**outcome, "finished_at": _now()}
        )


def _spawn(job) -> None:
    """Run `job` off the request thread. A seam, so a test can run it inline."""
    threading.Thread(target=job, daemon=True, name="sector-rescan").start()


@router.get(
    "/sectors/{sector}/rescan",
    response_model=RescanStatus,
    summary="Where a live rescan stands",
)
def rescan_status(sector: str) -> RescanStatus:
    """What the client polls after starting one. Spends nothing."""
    name = _resolve(sector)
    with _jobs_lock:
        return _jobs.get(name) or RescanStatus(sector=name, state="idle")


@router.post(
    "/sectors/{sector}/rescan",
    response_model=RescanStatus,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Rescan one sector now",
)
def rescan(sector: str, paths: Writer) -> RescanStatus:
    """Start a live rescan of one sector and answer at once.

    A job already running for this sector is returned as it stands and costs
    nothing: pressing twice, or two readers pressing together, is one scan.
    Otherwise it spends one of the account's `RESCAN_MAX` an hour — a 429 with
    `Retry-After` past that — and a session only, like every write: a bearer
    token naming somebody could otherwise spend Yahoo's patience in their name.
    """
    from stocks.web import ratelimit

    name = _resolve(sector)
    with _jobs_lock:
        current = _jobs.get(name)
        if current is not None and current.state == "running":
            return current
    key = f"sector_rescan::{paths.root}"
    if not ratelimit.allow(key, max_events=RESCAN_MAX, window_s=RESCAN_WINDOW_S):
        wait = ratelimit.retry_after(key, window_s=RESCAN_WINDOW_S)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="sector.rescan_limited",
            headers={"Retry-After": str(max(1, wait))},
        )
    with _jobs_lock:
        # Checked again under the lock: another request may have started the
        # job between the first look and the budget spend.
        current = _jobs.get(name)
        if current is not None and current.state == "running":
            return current
        started = RescanStatus(sector=name, state="running", started_at=_now())
        _jobs[name] = started
    _spawn(lambda: _rescan(name))
    return started
