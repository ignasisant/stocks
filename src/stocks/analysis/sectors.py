"""Sector cohorts: who competes with whom, and which three screen best.

A screen over your own watchlist can only rank names you already chose. This
module builds the other half — a cohort per sector that you do not have to
have heard of — and hands it to the ranking the comps table already uses.

The cohort is assembled from two sources, in this order:

1. The sector ETF's disclosed basket (`SECTOR_ETFS` -> XLK, XLV, ...). One
   request, no guessing, and Yahoo publishes the top ten by weight. These are
   US mega-caps, which is the whole limitation: XLK is not "technology", it is
   "large American technology".
2. Names proposed by the assistant to cover what (1) structurally cannot —
   Europe, EM, Asia. Those arrive as text from a language model, so nothing
   here trusts them: `validate_symbols` makes Yahoo confirm both that the
   symbol exists and that it is filed under this sector, and drops it
   otherwise. An invented ticker never reaches a podium.

The score is `analysis.fundamentals.comp_scores`, unchanged — a cross-sectional
percentile over 18 valuation and quality KPIs. Two things follow from that, and
both belong in the copy, not just here:

* It is **relative to the cohort**. The podium says "the best three of these
  eighteen", never "the best three in the world".
* It measures **valuation and quality only**. No momentum, no analyst upside,
  no margin of safety. A cheap, profitable, shrinking company scores well.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from stocks import obs, storage
from stocks.analysis.fundamentals import comp_medals, comp_scores
from stocks.analysis.screener import fetch_metrics_many
from stocks.analysis.sentiment import SECTOR_ETFS
from stocks.config import DATA_DIR

# The 11 sectors, spelled the way `info["sector"]` spells them — so the sector
# a company reports joins onto this table with no mapping layer.
SECTORS: tuple[str, ...] = tuple(SECTOR_ETFS)

# How many of the ETF's disclosed lines to take. Yahoo publishes ten.
ETF_TOP = 10

# How many extra names to ask the assistant for per sector. Eighteen-ish in a
# cohort is comfortably above comp_scores' own floor and still one screenful.
EXTRA_PER_SECTOR = 8

# Where the nightly scan lands. Market-wide, not per-account: every reader
# gets the same cohorts, so this is a shared file like the free-tier counter,
# NOT an entry in `web.auth.UserPaths`.
SCAN_FILE = DATA_DIR / "sector_scan.json"


@dataclass(frozen=True)
class SectorScan:
    """One sector's cohort, scored. `podium` is best-first and may be empty."""

    sector: str
    as_of: str
    tickers: tuple[str, ...]
    metrics: tuple[dict, ...]
    scores: dict[str, float]
    podium: tuple[str, ...]

    @property
    def medals(self) -> dict[str, str]:
        """ticker -> 🥇🥈🥉, empty when the cohort was too thin to rank."""
        return dict(zip(self.podium, ("🥇", "🥈", "🥉"), strict=False))

    def to_dict(self) -> dict:
        return {
            "sector": self.sector,
            "as_of": self.as_of,
            "tickers": list(self.tickers),
            "metrics": [_plain(m) for m in self.metrics],
            "scores": {k: float(v) for k, v in self.scores.items()},
            "podium": list(self.podium),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> SectorScan:
        return cls(
            sector=str(raw.get("sector") or ""),
            as_of=str(raw.get("as_of") or ""),
            tickers=tuple(str(t) for t in raw.get("tickers") or ()),
            metrics=tuple(m for m in raw.get("metrics") or () if isinstance(m, dict)),
            scores={str(k): float(v) for k, v in (raw.get("scores") or {}).items()},
            podium=tuple(str(t) for t in raw.get("podium") or ()),
        )


def _plain(metrics: dict) -> dict:
    """A metrics row as JSON will take it.

    compute_metrics reads half its numbers out of pandas, so the row is full of
    numpy scalars and NaN — both of which `json.dumps` either refuses or turns
    into the literal `NaN`, which is not JSON and which no other reader parses.
    """
    out: dict = {}
    for key, value in metrics.items():
        if value is None or isinstance(value, str):
            out[key] = value
            continue
        if isinstance(value, bool):
            out[key] = value
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            out[key] = str(value)
            continue
        out[key] = number if number == number else None  # NaN -> null
    return out


# ------------------------------------------------------------- the cohort


def etf_candidates(sector: str, limit: int = ETF_TOP) -> list[str]:
    """The sector ETF's disclosed holdings, heaviest first. One request.

    Empty when Yahoo drops the basket — a sector with no cohort is skipped, not
    an error: the other ten still have one.
    """
    from stocks.data import funds

    etf = SECTOR_ETFS.get(sector)
    if not etf:
        raise ValueError(f"unknown sector: {sector!r}")
    profile = funds.fetch_profile(etf)
    if profile is None or not profile.holdings:
        obs.warn("sector.etf_basket_empty", sector=sector, etf=etf)
        return []
    return [h.symbol.upper() for h in profile.holdings[:limit] if h.symbol]


def validate_symbols(
    proposed: list[str], sector: str, *, known: tuple[str, ...] = ()
) -> list[str]:
    """The proposals Yahoo confirms, in order. Everything else is dropped.

    Two gates, because a language model can fail either way. The first catches
    the symbol it invented; the second catches the real symbol it filed under
    the wrong sector, which is the more dangerous of the two — it would rank
    against companies it does not compete with.

    A rate limit propagates: mid-throttle every candidate would "fail
    validation" and the sector would quietly shrink to its ETF.
    """
    from stocks.data import fetch, symbols

    seen = {s.upper() for s in known}
    keep: list[str] = []
    for raw in proposed:
        symbol = (raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        if not any(m[0].upper() == symbol for m in symbols.search_symbols(symbol)):
            obs.event("sector.symbol_unknown", symbol=symbol, sector=sector)
            continue
        filed = str(fetch.info(symbol).get("sector") or "")
        if filed != sector:
            obs.event("sector.symbol_misfiled", symbol=symbol,
                      sector=sector, filed=filed or "none")
            continue
        keep.append(symbol)
    return keep


def scan_sector(
    sector: str, extra: tuple[str, ...] = (), *, as_of: str | None = None
) -> SectorScan:
    """Fetch and score one sector's cohort.

    `extra` is already validated — this does not re-check it, so callers that
    got their names from a model run them through `validate_symbols` first.
    """
    if sector not in SECTOR_ETFS:
        raise ValueError(f"unknown sector: {sector!r}")
    cohort = list(dict.fromkeys([*etf_candidates(sector),
                                 *(s.upper() for s in extra)]))
    metrics = fetch_metrics_many(cohort, drop_funds=True) if cohort else []
    scores = comp_scores(metrics)
    # comp_medals owns the "a 2-horse race has no podium" rule and returns its
    # winners in rank order; reading the keys keeps that rule in one place.
    podium = tuple(comp_medals(metrics))
    obs.event("sector.scanned", sector=sector, cohort=len(cohort),
              scored=len(scores), podium=len(podium))
    return SectorScan(
        sector=sector,
        as_of=as_of or date.today().isoformat(),
        tickers=tuple(str(m.get("ticker") or "") for m in metrics),
        metrics=tuple(metrics),
        scores=scores,
        podium=podium,
    )


# ----------------------------------------------------------- the stored scan


def load_scan(*, restore: bool = True) -> dict[str, SectorScan]:
    """Every stored sector, by name. Empty when there is nothing yet.

    Best-effort in both directions: a missing file, a corrupt one or a bucket
    that will not answer all mean "no scan", which the page renders as an empty
    state. Erring the other way would be a stack trace on a cold container.
    """
    if restore and storage.enabled():
        with obs.swallow("sector.scan_restore"):
            storage.restore(SCAN_FILE)
    try:
        raw = json.loads(SCAN_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, SectorScan] = {}
    for name, entry in (raw.get("sectors") or {}).items():
        if isinstance(entry, dict):
            out[str(name)] = SectorScan.from_dict(entry)
    return out


def save_scan(scans: dict[str, SectorScan]) -> None:
    """Write the whole map and mirror it to the bucket.

    Callers merge into what `load_scan` gave them rather than writing only the
    sectors that succeeded: a sector Yahoo refused tonight keeps yesterday's
    cohort, and the file is never published half-empty.
    """
    payload = {
        "saved": date.today().isoformat(),
        "sectors": {name: scan.to_dict() for name, scan in scans.items()},
    }
    SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCAN_FILE.write_text(json.dumps(payload, indent=0, sort_keys=True))
    if storage.enabled():
        with obs.swallow("sector.scan_persist"):
            storage.persist(SCAN_FILE)


# ------------------------------------------------------------------ the run

# Between sectors. Each one is a burst of ~18 companies at five requests each
# through a thread pool; the pause is what keeps eleven of those from reading
# as one continuous assault on an endpoint that has already rate-limited this
# project from a datacenter IP once.
PAUSE_S = 5.0


def run_scan(
    names: tuple[str, ...] = (),
    *,
    widen: bool = True,
    pause_s: float = PAUSE_S,
    dry_run: bool = False,
) -> dict[str, str]:
    """Scan every sector and merge the result into the stored file.

    Returns {sector: status} for the caller to print — "scanned", "kept"
    (Yahoo refused, yesterday's cohort stands) or "empty".

    Merging rather than replacing is the whole failure policy: a sector that
    fails tonight keeps the cohort it had, and the file is never published
    half-empty. A throttle part-way through costs the sectors after it, not
    the ones already stored.
    """
    import time

    from stocks.chat import engine, sector_ai

    wanted = tuple(names) or SECTORS
    stored = load_scan()
    status: dict[str, str] = {}

    for index, sector in enumerate(wanted):
        if index:
            time.sleep(pause_s)
        extra: tuple[str, ...] = ()
        if widen:
            # A widening that fails is a sector with its ETF cohort — worse,
            # but working. It must never cost the scan.
            try:
                base = tuple(etf_candidates(sector))
                proposed = sector_ai.propose_peers(
                    {}, sector, base, EXTRA_PER_SECTOR,
                    spend_free=engine.spend_free_global,
                )
                extra = tuple(validate_symbols(proposed, sector, known=base))
            except Exception as exc:
                obs.warn("sector.widen_failed", sector=sector,
                         error_type=type(exc).__name__, error=str(exc)[:200])
        try:
            scan = scan_sector(sector, extra)
        except Exception as exc:
            obs.warn("sector.scan_failed", sector=sector,
                     error_type=type(exc).__name__, error=str(exc)[:200])
            status[sector] = "kept" if sector in stored else "failed"
            continue
        if not scan.tickers:
            status[sector] = "empty"
            continue
        stored[sector] = scan
        status[sector] = f"scanned {len(scan.tickers)}"

    if not dry_run:
        save_scan(stored)
    return status
