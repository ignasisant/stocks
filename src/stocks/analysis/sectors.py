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
3. Small and mid caps growing fast (`growth_candidates`): a Yahoo screen, not
   a model, for the names neither of the above reaches — under $10B, sales up
   more than 15 % on the year, with a positive EBITDA margin. They sit in the
   table beside the cohort (`SectorScan.growth_metrics`) but are scored and
   medalled nowhere: a podium of the S&P's largest names does not change
   because eight small ones were listed next to it, and neither do the peer
   medians the company page reads off `metrics`.

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
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from stocks import atomic, obs, storage
from stocks.analysis.fundamentals import comp_medals, comp_scores
from stocks.analysis.screener import fetch_metrics_many
from stocks.analysis.sentiment import SECTOR_ETFS
from stocks.analysis.technicals import (
    technical_medals,
    technical_scores,
    technical_snapshot,
)
from stocks.config import DATA_DIR
from stocks.data import frames
from stocks.data.fetch import fetch_many

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
    """One sector's cohort, scored. `podium` is best-first and may be empty.

    `tech_*` mirrors `metrics`/`scores`/`podium` for the technical-momentum
    podium — a separate ranking over price/volume signals rather than
    valuation and quality. Empty on a scan taken before this existed, or when
    the OHLC pull for the cohort failed: the fundamentals half never waits on
    the technical half.
    """

    sector: str
    as_of: str
    tickers: tuple[str, ...]
    metrics: tuple[dict, ...]
    scores: dict[str, float]
    podium: tuple[str, ...]
    # Defaulted, unlike the fields above: existing call sites (tests,
    # `SectorScan.from_dict` reading an older saved scan)
    # construct a scan with no idea these exist.
    tech_metrics: tuple[dict, ...] = ()
    tech_scores: dict[str, float] = field(default_factory=dict)
    tech_podium: tuple[str, ...] = ()
    # The small, fast-growing names (`growth_candidates`): rows like
    # `metrics`, kept apart so no score, podium or peer median counts them.
    growth_metrics: tuple[dict, ...] = ()

    @property
    def growth_tickers(self) -> tuple[str, ...]:
        return tuple(str(m.get("ticker") or "") for m in self.growth_metrics)

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
            "tech_metrics": [_plain(m) for m in self.tech_metrics],
            "tech_scores": {k: float(v) for k, v in self.tech_scores.items()},
            "tech_podium": list(self.tech_podium),
            "growth_metrics": [_plain(m) for m in self.growth_metrics],
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
            tech_metrics=tuple(
                m for m in raw.get("tech_metrics") or () if isinstance(m, dict)
            ),
            tech_scores={
                str(k): float(v) for k, v in (raw.get("tech_scores") or {}).items()
            },
            tech_podium=tuple(str(t) for t in raw.get("tech_podium") or ()),
            growth_metrics=tuple(
                m for m in raw.get("growth_metrics") or () if isinstance(m, dict)
            ),
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


def industry_rivals(
    scans: dict[str, SectorScan],
    ticker: str,
    industry: str | None = None,
    limit: int = 6,
) -> list[str]:
    """Names in the nightly cohorts filed under `ticker`'s industry, cohort
    order (the ETF's by weight, then the validated extras).

    Same industry, not same sector: XLK puts a chip designer beside a phone
    maker and a software house. `industry` defaults to the one the scan
    recorded for `ticker`; a name outside every cohort needs it passed in.
    """
    subject = ticker.upper()
    rows = [m for scan in scans.values() for m in scan.metrics]
    if industry is None:
        industry = next(
            (
                m.get("industry")
                for m in rows
                if str(m.get("ticker", "")).upper() == subject
            ),
            None,
        )
    if not industry:
        return []
    out: list[str] = []
    for m in rows:
        name = str(m.get("ticker") or "")
        same = m.get("industry") == industry
        if name and name.upper() != subject and same and name not in out:
            out.append(name)
    return out[:limit]


#: Fewer same-industry names than this in the scan and the industry's middle
#: is a handful of companies: the sector cohort reads it instead.
PEER_INDUSTRY_MIN = 5


def peer_rows(
    scans: dict[str, SectorScan],
    ticker: str,
    industry: str | None,
    sector: str | None,
) -> tuple[str, str, list[dict]] | None:
    """(kind, name, rows) the company grid reads its rivals' middle off:
    every scanned name in `ticker`'s industry, across cohorts, when there are
    `PEER_INDUSTRY_MIN`; else its sector's cohort. The subject is never in
    the rows. None when neither has anyone to read.

    The scan's rows, not a fetch: a night old, and free.
    """
    subject = ticker.upper()

    def others(rows) -> list[dict]:
        seen: set[str] = set()
        out = []
        for m in rows:
            name = str(m.get("ticker") or "").upper()
            if name and name != subject and name not in seen:
                seen.add(name)
                out.append(m)
        return out

    if industry:
        same = others(
            m for scan in scans.values() for m in scan.metrics
            if m.get("industry") == industry
        )
        if len(same) >= PEER_INDUSTRY_MIN:
            return "industry", industry, same
    cohort = scans.get(sector or "")
    if cohort is not None:
        rows = others(cohort.metrics)
        if rows:
            return "sector", cohort.sector, rows
    return None


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


# ------------------------------------------------- small and growing fast

#: The dollar band a growth name's market cap must sit in: small and mid caps.
#: Under the floor a name is too thin to act on a screen's say-so; over the
#: ceiling the ETF basket and the proposed peers already cover its size.
GROWTH_CAP_USD = (300e6, 10e9)

#: Growth names per sector, at most. Each costs the nightly scan ~5 Yahoo
#: requests, so eleven sectors of these is ~440 more on a throttled IP.
GROWTH_PER_SECTOR = 8

#: How many of them come from US exchanges before Europe's get their turn.
GROWTH_US = 5

# Primary exchanges only. Yahoo's US set also holds the pink sheets (PNK),
# and Vienna (VIE) lists half of Nasdaq; Xetra (GER) does too, which is what
# the country check in `growth_candidates` is for.
_US_EXCHANGES = ("NMS", "NGM", "NCM", "NYQ", "ASE")
_EU_EXCHANGES = ("PAR", "AMS", "BRU", "LIS", "MCE", "GER", "MIL", "STO",
                 "CPH", "HEL", "OSL", "LSE", "EBS")

_PREFERRED = re.compile(r"-P[A-Z]?$")

#: Sales growth over the last twelve months, percent, a name must beat.
GROWTH_MIN_PCT = 15
#: Twelve months' sales a name must have (listing currency): not a story yet.
GROWTH_MIN_REVENUE = 100e6


def _screen(sector: str, exchanges: tuple[str, ...], cap: tuple[float, float],
            size: int) -> list[dict]:
    """Yahoo's screener: `sector` names on `exchanges` growing fast and
    with a positive EBITDA margin, fastest first. `cap` bounds are in each
    listing's own currency — Yahoo's, not ours to choose."""
    import yfinance as yf
    from yfinance import EquityQuery

    from stocks.data import fetch

    def Q(op: str, operand: list) -> EquityQuery:  # noqa: N802 - reads as yfinance's
        # yfinance types an operand as all strings or all numbers; a field
        # name followed by its bounds is what it actually takes.
        return EquityQuery(cast("Any", op), cast("Any", operand))

    query = Q("and", [
        Q("eq", ["sector", sector]),
        Q("is-in", ["exchange", *exchanges]),
        Q("btwn", ["intradaymarketcap", cap[0], cap[1]]),
        Q("gt", ["totalrevenues1yrgrowth.lasttwelvemonths", GROWTH_MIN_PCT]),
        Q("gt", ["totalrevenues.lasttwelvemonths", GROWTH_MIN_REVENUE]),
        # A positive EBITDA margin: what keeps the pre-revenue story stocks out,
        # which a sales-growth sort alone puts first.
        Q("gt", ["ebitdamargin.lasttwelvemonths", 0]),
    ])
    found = fetch.retry(lambda: yf.screen(
        query, sortField="totalrevenues1yrgrowth.lasttwelvemonths",
        sortAsc=False, size=size,
    ))
    quotes = found.get("quotes") if isinstance(found, dict) else None
    return [q for q in quotes or () if isinstance(q, dict) and q.get("symbol")]


def _usd_rate(currency: str | None) -> float | None:
    """Dollars per unit of a listing's major currency; None when unquoted."""
    from stocks.data import fx
    from stocks.data.listing import quote_unit

    iso = quote_unit(currency)[0]
    if not iso:
        return None
    if iso == "USD":
        return 1.0
    try:
        return fx.spot(iso, "USD")[0]
    except Exception:  # noqa: BLE001 - an unquoted currency drops the name
        return None


def _with_cap_usd(rows: list[dict]) -> list[dict]:
    """Copies of `rows` carrying `market_cap_usd`. Yahoo states the cap in
    the quote currency's major unit (pounds for a pence line), so only the
    rate applies. Kept here, not in `compute_metrics`: no score reads it."""
    out = []
    for r in rows:
        cap, rate = r.get("market_cap"), _usd_rate(r.get("currency"))
        priced = isinstance(cap, (int, float)) and cap and rate
        usd = float(cap) * rate if priced else None
        out.append({**r, "market_cap_usd": usd})
    return out


def in_growth_band(cap_usd: float | None) -> bool:
    low, high = GROWTH_CAP_USD
    return cap_usd is not None and low <= cap_usd <= high


def growth_candidates(
    sector: str, *, known: tuple[str, ...] = (), limit: int = GROWTH_PER_SECTOR
) -> list[str]:
    """Small and mid caps in `sector` growing sales fastest, US first, then
    Europe. Two screener requests, plus one profile per European pick.

    Not validated the way a model's proposals are, and not needing it: the
    symbols come from Yahoo's own index, filed under the sector by Yahoo.
    A rate limit propagates, like `validate_symbols`.
    """
    from stocks.data import fetch

    if sector not in SECTOR_ETFS:
        raise ValueError(f"unknown sector: {sector!r}")
    seen = {s.upper() for s in known}
    picks: list[str] = []

    def take(symbol: str) -> None:
        seen.add(symbol)
        picks.append(symbol)

    us = [str(q["symbol"]).upper()
          for q in _screen(sector, _US_EXCHANGES, GROWTH_CAP_USD, 15)]
    # A preferred share (SLG-PI) is the company's debt, not its growth.
    us = [symbol for symbol in us if not _PREFERRED.search(symbol)]
    for symbol in us:
        if len(picks) >= GROWTH_US:
            break
        if symbol not in seen:
            take(symbol)

    # European bounds wide in the listing's currency (a $10B Swedish company
    # is ~100B SEK); the dollar band is applied per name below.
    for quote in _screen(sector, _EU_EXCHANGES, (GROWTH_CAP_USD[0], 150e9), 25):
        if len(picks) >= limit:
            break
        symbol = str(quote["symbol"]).upper()
        if symbol in seen:
            continue
        rate = _usd_rate(quote.get("currency"))
        cap = quote.get("marketCap")
        if rate is None or not cap or not in_growth_band(float(cap) * rate):
            continue
        # Xetra lists Nasdaq's companies too: a US company's German line is
        # the US name twice, and in euros.
        if str(fetch.info(symbol).get("country") or "") in ("United States", ""):
            obs.event("sector.growth_cross_listing", symbol=symbol, sector=sector)
            continue
        take(symbol)

    # Europe short (Real Estate, Utilities): the US list fills the rest.
    for symbol in us:
        if len(picks) >= limit:
            break
        if symbol not in seen:
            take(symbol)
    return picks


_TechScan = tuple[list[dict], dict[str, float], tuple[str, ...]]


def _scan_technicals(cohort: list[str]) -> _TechScan:
    """Technical snapshot + score + podium for a cohort, or empty on any failure.

    A single bulk OHLC pull (`fetch_many`) for the whole cohort — one extra
    batched request per sector, not one per ticker. Best-effort: a throttled
    or offline Yahoo loses the technical podium for tonight, not the
    fundamentals one, which is already computed by the time this runs.
    """
    if not cohort:
        return [], {}, ()
    try:
        history = fetch_many(cohort, period="1y")
    except Exception as exc:
        obs.warn("sector.technicals_failed", cohort=len(cohort),
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return [], {}, ()
    rows = []
    for ticker, df in history.items():
        snapshot = technical_snapshot(df)
        if snapshot:
            rows.append({"ticker": ticker, **snapshot})
    scores = technical_scores(rows)
    podium = tuple(technical_medals(rows))
    return rows, scores, podium


# Figures off the statements alone: two share classes of one company (GOOG and
# GOOGL, FOX and FOXA) file the same accounts and match on every one, while
# two companies never match on all of them.
_FILED = ("roic", "op_margin", "gross_margin", "net_margin", "revenue_cagr", "moat")


def _one_class(metrics: list[dict]) -> list[dict]:
    """`metrics` with a company's second share class left out (the ETF lists
    both), so one business does not take two places on the podium."""
    seen: set[tuple] = set()
    out = []
    for row in metrics:
        filed = tuple(
            round(v, 9) if isinstance(v, float) else v
            for v in (row.get(k) for k in _FILED)
        )
        if sum(v is not None for v in filed) >= 4:
            if filed in seen:
                continue
            seen.add(filed)
        out.append(row)
    return out


def scan_sector(
    sector: str,
    extra: tuple[str, ...] = (),
    *,
    growth: tuple[str, ...] = (),
    as_of: str | None = None,
) -> SectorScan:
    """Fetch and score one sector's cohort.

    `extra` is already validated — this does not re-check it, so callers that
    got their names from a model run them through `validate_symbols` first.
    `growth` (`growth_candidates`) is fetched beside the cohort and kept out
    of its scores; a name that has left the dollar band since it was found is
    dropped.
    """
    if sector not in SECTOR_ETFS:
        raise ValueError(f"unknown sector: {sector!r}")
    cohort = list(dict.fromkeys([*etf_candidates(sector),
                                 *(s.upper() for s in extra)]))
    fetched = fetch_metrics_many(cohort, drop_funds=True) if cohort else []
    metrics = _with_cap_usd(_one_class(fetched))
    # The technical table keeps to the same names: one class per company.
    twins = {r.get("ticker") for r in fetched} - {r.get("ticker") for r in metrics}
    cohort = [t for t in cohort if t not in twins]
    # Gaps in US names' rows read from the SEC's filed figures, one frames
    # download for the whole scan (data.frames) — never over a Yahoo figure.
    filled = frames.fill_gaps(metrics) if metrics else 0
    scores = comp_scores(metrics)
    # comp_medals owns the "a 2-horse race has no podium" rule and returns its
    # winners in rank order; reading the keys keeps that rule in one place.
    podium = tuple(comp_medals(metrics))
    tech_metrics, tech_scores, tech_podium = _scan_technicals(cohort)
    growth_metrics = _scan_growth(growth, {str(m.get("ticker") or "") for m in metrics})
    obs.event("sector.scanned", sector=sector, cohort=len(cohort), filled=filled,
              scored=len(scores), podium=len(podium), tech_podium=len(tech_podium),
              growth=len(growth_metrics))
    return SectorScan(
        sector=sector,
        as_of=as_of or date.today().isoformat(),
        tickers=tuple(str(m.get("ticker") or "") for m in metrics),
        metrics=tuple(metrics),
        scores=scores,
        podium=podium,
        tech_metrics=tuple(tech_metrics),
        tech_scores=tech_scores,
        tech_podium=tech_podium,
        growth_metrics=tuple(growth_metrics),
    )


def _scan_growth(growth: tuple[str, ...], cohort: set[str]) -> list[dict]:
    """The growth names' rows, minus any the cohort already has and any whose
    dollar cap is unknown or out of the band. Best-effort: Yahoo failing here
    costs tonight's growth names, never the cohort scored above."""
    wanted = [s.upper() for s in dict.fromkeys(growth) if s.upper() not in cohort]
    if not wanted:
        return []
    try:
        rows = fetch_metrics_many(wanted, drop_funds=True)
    except Exception as exc:
        obs.warn("sector.growth_failed", names=len(wanted),
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return []
    rows = [r for r in _with_cap_usd(rows) if in_growth_band(r.get("market_cap_usd"))]
    if rows:
        frames.fill_gaps(rows)
    return rows


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
    atomic.write_json(SCAN_FILE, payload, indent=0, sort_keys=True)
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
    propose: Callable[[str, tuple[str, ...], int], list[str]] | None = None,
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

    `propose(sector, known, count)` widens each ETF cohort with candidate
    names (the CLI passes `chat.sector_ai.widen`); without it the cohort is
    the ETF basket alone. Its symbols are validated here, never trusted.
    """
    import time

    wanted = tuple(names) or SECTORS
    stored = load_scan()
    status: dict[str, str] = {}

    for index, sector in enumerate(wanted):
        if index:
            time.sleep(pause_s)
        extra: tuple[str, ...] = ()
        if propose is not None:
            # A widening that fails is a sector with its ETF cohort — worse,
            # but working. It must never cost the scan.
            try:
                base = tuple(etf_candidates(sector))
                proposed = propose(sector, base, EXTRA_PER_SECTOR)
                extra = tuple(validate_symbols(proposed, sector, known=base))
            except Exception as exc:
                obs.warn("sector.widen_failed", sector=sector,
                         error_type=type(exc).__name__, error=str(exc)[:200])
        # Same policy: no growth names tonight is a sector without them.
        growth: tuple[str, ...] = ()
        try:
            growth = tuple(growth_candidates(sector, known=extra))
        except Exception as exc:
            obs.warn("sector.growth_screen_failed", sector=sector,
                     error_type=type(exc).__name__, error=str(exc)[:200])
            # Last night's names, refetched: a screen that failed is not a
            # sector whose small companies all stopped growing.
            if sector in stored:
                growth = stored[sector].growth_tickers
        try:
            scan = scan_sector(sector, extra, growth=growth)
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
