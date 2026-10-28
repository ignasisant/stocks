"""SEC XBRL frames — one concept, every US filer, one call.

`companyfacts` is one company's whole filing history (a megabyte or three);
`frames/{taxonomy}/{concept}/{unit}/{period}` is the other axis: one concept
at one period for every filer that reported it, one value per company. A
cross-section (the sector scan's cohorts, ~190 names) costs a handful of calls
here instead of a download per name, and what the filings say is the SEC's own
number, not Yahoo's.

Used to fill the gaps in a scan's rows (`fill_gaps`): where Yahoo answered
nothing for revenue, free cash flow, book value, return on equity or earnings
the filed figures stand in. Never to overwrite what Yahoo said.

Frames semantics that shape the code:

* One value per CIK per period. The period is the calendar frame the filing's
  own period fits best (a January fiscal year-end lands in the previous
  calendar year: Nvidia's year to 2026-01-25 is CY2025). Each stored value
  keeps its real end date.
* Companies pick different XBRL tags for the same thing, so each KPI is a
  list of aliases (Revenues vs RevenueFromContractWithCustomer...); a company
  is read from the first alias it uses, or the largest for revenue, where the
  tags are nested (total revenues >= revenue from contracts).
* Flows (revenue, income, cash flow) are the latest *annual* frame — a 10-K's
  figure, which is the only complete one frames carries for the fiscal Q4;
  stocks (equity, shares) are instants at that year's end / latest quarter.
* The index is early in January: a year is used once its frames hold
  `MIN_POINTS` companies, else the year before.

Stored in data/edgar_frames.json (a MB or so: only CIKs the SEC ticker map
lists are kept) and mirrored to the bucket; refreshed after `MAX_AGE_DAYS`.
A failed refresh keeps the old file.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR
from stocks.data import edgar
from stocks.data.http import get_json

FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{period}.json"
FRAMES_FILE = DATA_DIR / "edgar_frames.json"

# Quarterly data: a month is plenty (a quarter's 10-Qs land over six weeks).
MAX_AGE_DAYS = 35
# A frame with fewer companies than this is a period still filling in.
MIN_POINTS = 3000
# SEC fair access is 10 requests a second; stay well under it.
PAUSE_S = 0.2


@dataclass(frozen=True)
class Concept:
    key: str
    kind: str  # "flow" (annual duration) or "stock" (instant)
    unit: str
    aliases: tuple[tuple[str, str], ...]
    pick: str = "first"  # or "max"


CONCEPTS: tuple[Concept, ...] = (
    Concept("revenue", "flow", "USD", (
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
        ("us-gaap", "SalesRevenueNet"),
    ), pick="max"),
    Concept("net_income", "flow", "USD", (
        ("us-gaap", "NetIncomeLoss"),
        ("us-gaap", "ProfitLoss"),
    )),
    Concept("op_cash_flow", "flow", "USD", (
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    )),
    Concept("capex", "flow", "USD", (
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireProductiveAssets"),
    )),
    Concept("equity", "stock", "USD", (
        ("us-gaap", "StockholdersEquity"),
        ("us-gaap",
         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    )),
    Concept("shares", "stock", "shares", (
        ("dei", "EntityCommonStockSharesOutstanding"),
    )),
)


def _get(url: str) -> dict:
    return get_json(url, user_agent=edgar._user_agent(), timeout=60)


def _quarters_back(today: date, count: int):
    """(year, quarter) from the last finished calendar quarter backwards."""
    year, quarter = today.year, (today.month - 1) // 3 + 1
    for _ in range(count):
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
        yield year, quarter


def _frame(concept: Concept, period: str, wanted: set[int] | None = None,
           pause: float = PAUSE_S) -> tuple[dict[int, tuple[float, str]], int]:
    """Per CIK, the value of the first alias that has one (or the largest),
    as (value, end date), and the biggest alias frame's point count.
    A missing frame (404: no filer used that tag then) is an empty one."""
    out: dict[int, tuple[float, str]] = {}
    biggest = 0
    for taxonomy, tag in concept.aliases:
        try:
            payload = _get(FRAMES_URL.format(
                taxonomy=taxonomy, concept=tag, unit=concept.unit, period=period))
        except Exception as exc:  # noqa: BLE001 — a tag nobody used is a 404
            if getattr(exc, "code", None) != 404:
                raise
            payload = {}
        time.sleep(pause)
        data = payload.get("data") or []
        biggest = max(biggest, len(data))
        for row in data:
            try:
                cik, value, end = int(row["cik"]), float(row["val"]), str(row["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if wanted is not None and cik not in wanted:
                continue
            if cik not in out or (concept.pick == "max" and value > out[cik][0]):
                out[cik] = (value, end)
    return out, biggest


def refresh(today: date | None = None, *, pause: float = PAUSE_S) -> dict:
    """Download every concept's latest complete frame and keep the filers
    the SEC ticker map knows. Raises on a failed request."""
    today = today or date.today()
    wanted = edgar.all_ciks()
    # The annual year: the latest whose net-income frame is complete.
    year = today.year - 1
    for _ in range(2):
        _, points = _frame(Concept("probe", "flow", "USD", CONCEPTS[1].aliases[:1]),
                           f"CY{year}", set(), pause)
        if points >= MIN_POINTS:
            break
        year -= 1
    rows: dict[str, dict[str, list]] = {}
    periods: dict[str, str] = {}
    for concept in CONCEPTS:
        if concept.kind == "flow":
            candidates = [f"CY{year}"]
        elif concept.key == "shares":
            candidates = [f"CY{y}Q{q}I" for y, q in _quarters_back(today, 4)]
        else:
            candidates = [f"CY{year}Q4I"]
        for period in candidates:
            values, points = _frame(concept, period, wanted, pause)
            if points >= MIN_POINTS or period == candidates[-1]:
                break
        periods[concept.key] = period
        for cik, (value, end) in values.items():
            rows.setdefault(str(cik), {})[concept.key] = [value, end]
    payload = {"fetched": today.isoformat(), "periods": periods, "rows": rows}
    atomic.write_json(FRAMES_FILE, payload, indent=0, sort_keys=True)
    if storage.enabled():
        with obs.swallow("frames.persist"):
            storage.persist(FRAMES_FILE)
    obs.event("frames.refreshed", companies=len(rows), periods=periods)
    return payload


_loaded: tuple[float, dict] | None = None


def load(*, restore: bool = True) -> dict:
    """The stored frames ({} when there are none), read once per file
    version."""
    global _loaded
    if restore and not FRAMES_FILE.exists() and storage.enabled():
        with obs.swallow("frames.restore"):
            storage.restore(FRAMES_FILE)
    try:
        stamp = FRAMES_FILE.stat().st_mtime
    except OSError:
        return {}
    if _loaded is not None and _loaded[0] == stamp:
        return _loaded[1]
    try:
        payload = json.loads(FRAMES_FILE.read_text())
    except (OSError, ValueError):
        return {}
    payload = payload if isinstance(payload, dict) else {}
    _loaded = (stamp, payload)
    return payload


def ensure(today: date | None = None) -> dict:
    """Frames at most `MAX_AGE_DAYS` old, refreshed when older. A failed
    refresh serves the old ones (or {}): the scan fills fewer gaps, no more."""
    today = today or date.today()
    have = load()
    try:
        age = (today - date.fromisoformat(have.get("fetched", ""))).days
    except ValueError:
        age = None
    if have and age is not None and age <= MAX_AGE_DAYS:
        return have
    try:
        return refresh(today)
    except Exception as exc:  # noqa: BLE001
        obs.warn("frames.refresh_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return have


def figures(ticker: str, payload: dict | None = None) -> dict[str, float]:
    """`ticker`'s filed figures by KPI key; {} when it files nothing here."""
    payload = payload if payload is not None else load()
    cik = edgar.cik_for(ticker)
    row = (payload.get("rows") or {}).get(str(int(cik))) if cik else None
    return {k: float(v[0]) for k, v in (row or {}).items()}


def _div(top: float | None, bottom: float | None) -> float | None:
    return top / bottom if top is not None and bottom else None


def fill_row(row: dict, f: dict[str, float]) -> list[str]:
    """Put the filed figures in `row`'s empty KPI slots; the keys filled.

    Only gaps: a figure Yahoo gave stands. The filed figures are the last
    fiscal year's, in dollars, so a row quoted in another currency is left
    alone (its ratios would mix currencies).
    """
    if str(row.get("currency") or "USD").upper() != "USD" or not f:
        return []
    filled: list[str] = []

    def put(key: str, value: float | None) -> None:
        if row.get(key) is None and value is not None:
            row[key] = value
            filled.append(key)

    price, revenue = row.get("price"), f.get("revenue")
    income, equity = f.get("net_income"), f.get("equity")
    if row.get("market_cap") is None and price and f.get("shares"):
        put("market_cap", float(price) * f["shares"])
    cap = row.get("market_cap")
    fcf = (f["op_cash_flow"] - f["capex"]
           if "op_cash_flow" in f and "capex" in f else None)
    if revenue and revenue > 0:
        put("revenue", revenue)
        put("net_margin", _div(income, revenue))
        put("ps", _div(cap, revenue))
    book = equity if equity and equity > 0 else None
    put("pb", _div(cap, book))
    put("roe", _div(income, book))
    if income and income > 0:
        put("pe_ttm", _div(cap, income))
    put("fcf", fcf)
    put("fcf_yield", _div(fcf, cap))
    put("fcf_margin", _div(fcf, revenue) if revenue and revenue > 0 else None)
    put("cash_conversion", _div(fcf, income) if income and income > 0 else None)
    return filled


def fill_gaps(rows: list[dict], payload: dict | None = None) -> int:
    """Fill every scan row's gaps from the filed frames; the figures filled.
    Never raises: no frames, no fill."""
    try:
        payload = payload if payload is not None else ensure()
        total = 0
        for row in rows:
            total += len(fill_row(row, figures(str(row.get("ticker") or ""), payload)))
        return total
    except Exception as exc:  # noqa: BLE001 — the scan never waits on this
        obs.warn("frames.fill_failed", error_type=type(exc).__name__,
                 error=str(exc)[:200])
        return 0
