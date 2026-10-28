"""ESEF annual reports — audited IFRS fundamentals for EU and UK issuers.

EDGAR gives US filers a primary source (`stocks.data.edgar`); EU names only had
Yahoo. Every EU-listed issuer files its annual report as inline XBRL (ESEF,
IFRS taxonomy), and https://filings.xbrl.org indexes them for free, no key,
with each filing's facts as xBRL-JSON. UK issuers file the same format
(UKSEF) and are indexed there too. Germany is NOT: filings.xbrl.org holds no
German filer, so a ".DE" name never qualifies.

The chain: symbol -> LEI -> filing list -> one facts file per year -> the
handful of concepts the analysis reads, as yfinance-shaped rows. The LEI comes
from an ISIN through GLEIF when the ISIN is known, otherwise from the issuer's
name against filings.xbrl.org's own entity list (only listed issuers file
there, so a name that matches is already verified to be a reporting company).

Cost shapes everything below. A facts file is 3-20 MB of JSON (a few hundred
KB gzipped) and an annual report changes once a year, so:

* Only the extracted rows are kept — a few KB per issuer under `data/esef/`,
  mirrored to the storage bucket like every other file there.
* Nothing here runs in a page's request. `cached` reads the file; a missing or
  stale one starts `warm`, one daemon thread at a time, and the NEXT read has
  it. Upstream failures degrade to "no ESEF" and are logged, never raised.
* A re-check is one small list request a week; a facts file is downloaded only
  for a year not already held. A miss (no LEI, no filings) is remembered for
  days, not forever.
"""

from __future__ import annotations

import gzip
import json
import re
import threading
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR
from stocks.data import http
from stocks.fuzzy import fuzzy_ratio

ROOT = "https://filings.xbrl.org"
ENTITIES_URL = f"{ROOT}/api/entities"
FILINGS_URL = f"{ROOT}/api/filings"
GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"

ESEF_DIR = DATA_DIR / "esef"
LEI_MAP = "leis.json"  # ticker -> {"lei": str | None, "at": epoch}

SOURCE = "ESEF"
SOURCE_LABEL = "ESEF"

# Annual reports change yearly: re-ask for a new filing weekly, retry a miss
# (no LEI, no filings, upstream down) after three days.
RECHECK_S = 7 * 86400.0
MISS_S = 3 * 86400.0
# Filings to read per issuer: the newest two carry 3-4 years of income and
# cash flow (a report shows two or three) and two balance sheets each.
FILINGS_READ = 2
# A decompressed facts file past this is skipped: parsed JSON weighs ~7x its
# text, and a 40 MB file peaked near 300 MB RSS on a 1 GiB instance. Typical
# reports are 3-20 MB, so this skips only the outliers.
MAX_DOC_BYTES = 24 * 1024 * 1024
TIMEOUT_S = 60

# Venue suffixes whose issuers file in ESEF/UKSEF. Not .DE/.F/.SW: nothing of
# theirs is indexed (Germany) or they are outside the regime (Switzerland).
VENUES = (
    ".MC",
    ".AS",
    ".PA",
    ".MI",
    ".BR",
    ".LS",
    ".L",
    ".ST",
    ".HE",
    ".CO",
    ".OL",
    ".VI",
    ".IR",
    ".AT",
    ".WA",
    ".PR",
    ".BD",
    ".TL",
    ".RG",
    ".VS",
    ".LU",
)

# When False, `overlay` never starts a background fetch (tests, one-off scripts).
BACKGROUND = True


def _get(url: str, *, gzip_ok: bool = False) -> bytes:
    headers = {"Accept": "application/json"}
    if gzip_ok:
        headers["Accept-Encoding"] = "gzip"
    return http.get_bytes(
        url, user_agent="stocks-toolkit", timeout=TIMEOUT_S, headers=headers
    )


def _json(url: str) -> Any:
    return json.loads(_get(url))


# ---------------------------------------------------------------- eligibility


def eligible(ticker: str, info: dict | None = None) -> bool:
    """Whether `ticker` could be an EU/UK reporting issuer (no network)."""
    t = (ticker or "").upper()
    if not t.endswith(VENUES):
        return False
    quote = str((info or {}).get("quoteType") or "EQUITY").upper()
    return quote == "EQUITY"


# ------------------------------------------------------------- LEI resolution

_SUFFIX = {
    "SA",
    "NV",
    "PLC",
    "AG",
    "SE",
    "SPA",
    "AB",
    "ASA",
    "OYJ",
    "AS",
    "BV",
    "LTD",
    "LIMITED",
    "INC",
    "CORP",
    "SAB",
    "SAE",
    "CO",
    "COMPANY",
    "HOLDING",
    "HOLDINGS",
    "GROUP",
    "THE",
    "DE",
    "DEL",
    "DI",
    "NA",
    "PUBLIC",
}


def _norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text.replace(".", ""))
    words = [w for w in text.split() if w not in _SUFFIX]
    return " ".join(words)


def _name_match(wanted: str, candidate: str) -> bool:
    a, b = _norm(wanted), _norm(candidate)
    if not a or not b:
        return False
    if a == b:
        return True
    return fuzzy_ratio(a, b) >= 0.92 and fuzzy_ratio(b, a) >= 0.92


def lei_from_isin(isin: str) -> str | None:
    """GLEIF's LEI for the issuer of `isin`, or None."""
    url = f"{GLEIF_URL}?" + urllib.parse.urlencode({"filter[isin]": isin})
    rows = _json(url).get("data") or []
    lei = str(rows[0].get("id") or "") if rows else ""
    return lei if len(lei) == 20 else None


def lei_from_name(name: str) -> str | None:
    """LEI of the filer whose name matches `name`, from filings.xbrl.org."""
    norm = _norm(name)
    if not norm:
        return None
    word = max(norm.split(), key=len)
    flt = json.dumps([{"name": "name", "op": "ilike", "val": f"%{word}%"}])
    url = f"{ENTITIES_URL}?" + urllib.parse.urlencode({"filter": flt})
    hits = [
        row["attributes"]
        for row in _json(url).get("data") or []
        if _name_match(name, row["attributes"].get("name", ""))
    ]
    # Two filers matching one name is a coin flip; say nothing instead.
    return hits[0]["identifier"] if len(hits) == 1 else None


def _read_map() -> dict:
    try:
        data = json.loads((ESEF_DIR / LEI_MAP).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, obj: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(path, obj, sort_keys=True)
        storage.persist(path)
    except Exception as exc:  # noqa: BLE001 - a cache write is never the page
        obs.warn("esef.persist_failed", path=path.name, error=str(exc)[:120])


_lock = threading.Lock()


def resolve_lei(ticker: str, name: str = "", isin: str = "") -> str | None:
    """Ticker -> LEI, remembered on disk (a hit for good, a miss for days).

    Network: GLEIF by ISIN when one is known, else the entity list by name.
    """
    key = ticker.upper()
    with _lock:
        known = _read_map().get(key)
    if known:
        if known.get("lei"):
            return known["lei"]
        if time.time() - float(known.get("at") or 0) < MISS_S:
            return None
    lei = None
    if not isin:
        from stocks.data import symbols

        isin = next(
            (k for k, v in symbols._load_isin_cache().items() if v.upper() == key), ""
        )
    if isin:
        lei = lei_from_isin(isin)
    if not lei and name:
        lei = lei_from_name(name)
    with _lock:
        table = _read_map()
        table[key] = {"lei": lei, "at": time.time()}
        _write(ESEF_DIR / LEI_MAP, table)
    return lei


# ------------------------------------------------------------------ filings


def list_filings(lei: str, limit: int = FILINGS_READ) -> list[dict]:
    """The newest annual filings, one per period end, newest first.

    The index holds several records for one report (a UK copy of a Spanish
    filing, reprocessed duplicates); take the one with the fewest errors,
    preferring a record carrying a publication date.
    """
    query = urllib.parse.urlencode(
        {
            "filter[entity.identifier]": lei,
            "sort": "-period_end",
            "page[size]": "30",
        },
        safe="[]",
    )
    best: dict[str, dict] = {}
    for row in _json(f"{FILINGS_URL}?{query}").get("data") or []:
        a = row.get("attributes") or {}
        if not a.get("period_end") or not a.get("json_url"):
            continue
        rank = (
            int(a.get("error_count") or 0),
            a.get("published") is None,
            -int(row["id"]),
        )
        if a["period_end"] not in best or rank < best[a["period_end"]]["_rank"]:
            best[a["period_end"]] = {
                "period_end": a["period_end"],
                "json_url": a["json_url"],
                "published": (a.get("published") or "")[:10] or None,
                "_rank": rank,
            }
    rows = sorted(best.values(), key=lambda r: r["period_end"], reverse=True)
    return [{k: v for k, v in r.items() if k != "_rank"} for r in rows[:limit]]


# ------------------------------------------------------------ concept mapping
# yfinance row label -> ifrs-full concepts, first one the filing reports wins.
# Flow concepts are annual durations, stock concepts instants at year end.

INCOME: dict[str, tuple[str, ...]] = {
    "Total Revenue": (
        "Revenue",
        "RevenueFromContractsWithCustomers",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ),
    "Gross Profit": ("GrossProfit",),
    "Operating Income": ("ProfitLossFromOperatingActivities",),
    "Pretax Income": ("ProfitLossBeforeTax",),
    "Net Income Including Noncontrolling Interests": ("ProfitLoss",),
    "Interest Expense": ("InterestExpense", "FinanceCosts"),
    "Diluted EPS": (
        "DilutedEarningsLossPerShare",
        "DilutedEarningsLossPerShareFromContinuingOperations",
    ),
    "Basic EPS": (
        "BasicEarningsLossPerShare",
        "BasicEarningsLossPerShareFromContinuingOperations",
    ),
    "Diluted Average Shares": ("AdjustedWeightedAverageShares",),
}
NET_INCOME = ("ProfitLossAttributableToOwnersOfParent", "ProfitLoss")

CASHFLOW: dict[str, tuple[str, ...]] = {
    "Operating Cash Flow": ("CashFlowsFromUsedInOperatingActivities",),
}
CAPEX = (
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
)
CAPEX_INTANGIBLE = ("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",)
DIVIDENDS = (
    "DividendsPaidClassifiedAsFinancingActivities",
    "DividendsPaidToEquityHoldersOfParentClassifiedAsFinancingActivities",
)

BALANCE: dict[str, tuple[str, ...]] = {
    "Total Assets": ("Assets",),
    "Total Equity Gross Minority Interest": ("Equity",),
    "Cash And Cash Equivalents": ("CashAndCashEquivalents",),
    "Goodwill": ("Goodwill",),
}
OWNERS_EQUITY = ("EquityAttributableToOwnersOfParent", "Equity")
DEBT_PARTS = (
    ("CurrentBorrowings", "CurrentPortionOfLongtermBorrowings"),
    ("NoncurrentBorrowings", "LongtermBorrowings"),
    ("CurrentLeaseLiabilities",),
    ("NoncurrentLeaseLiabilities",),
)

_ANNUAL_DAYS = range(340, 390)


def _day(stamp: str, *, end: bool) -> date:
    """The calendar day an xBRL-JSON period bound means.

    The format writes a bound as midnight at the START of the day after the
    period's last day ("2026-01-01T00:00:00" closes FY2025); a bare date is
    that day itself.
    """
    when = date.fromisoformat(stamp[:10])
    return when - timedelta(days=1) if end and "T" in stamp else when


def _facts(doc: dict) -> tuple[dict, dict, str | None]:
    """(flows, stocks, currency): {(concept, period_end_iso): value}.

    Only undimensioned numeric facts count — a dimensioned one is a segment or
    a component, not the statement line. Flows are annual durations only.
    """
    flows: dict[tuple[str, str], float] = {}
    stocks: dict[tuple[str, str], float] = {}
    currencies: dict[str, int] = {}
    for fact in (doc.get("facts") or {}).values():
        dims = fact.get("dimensions") or {}
        if len(dims) != 4 or "period" not in dims:
            continue
        concept = str(dims.get("concept", ""))
        if not concept.startswith("ifrs-full:"):
            continue
        try:
            value = float(fact["value"])
        except (KeyError, TypeError, ValueError):
            continue
        name, unit, period = (
            concept.split(":", 1)[1],
            str(dims.get("unit", "")),
            dims["period"],
        )
        if unit.startswith("iso4217:") and "/" not in unit:
            currencies[unit.split(":")[1]] = currencies.get(unit.split(":")[1], 0) + 1
        try:
            if "/" in period:
                start, close = period.split("/")
                if (
                    _day(close, end=True) - _day(start, end=False)
                ).days + 1 not in _ANNUAL_DAYS:
                    continue
                flows.setdefault((name, _day(close, end=True).isoformat()), value)
            else:
                stocks.setdefault((name, _day(period, end=True).isoformat()), value)
        except ValueError:
            continue
    currency = max(currencies, key=lambda c: currencies[c]) if currencies else None
    return flows, stocks, currency


def _first(table: dict, names: tuple[str, ...], day: str) -> float | None:
    for name in names:
        if (name, day) in table:
            return table[(name, day)]
    return None


def extract(doc: dict) -> dict[str, dict]:
    """One filing's facts -> {period_end: {currency, income, balance, cashflow}}.

    Pure. Rows carry yfinance's labels and signs (capex and dividends paid
    negative) so the analysis reads them unchanged; a row the filing does not
    report is simply absent.
    """
    flows, stocks, currency = _facts(doc)
    if not currency:
        return {}
    years: dict[str, dict] = {}
    for day in sorted({d for (_, d) in flows}):
        if (
            _first(
                flows, ("Revenue", "RevenueFromContractsWithCustomers", "ProfitLoss"), day
            )
            is None
        ):
            continue  # a stub period (a quarter's comparative), not the year
        income: dict[str, float] = {}
        for label, names in INCOME.items():
            if (v := _first(flows, names, day)) is not None:
                income[label] = v
        if (v := _first(flows, NET_INCOME, day)) is not None:
            income["Net Income"] = v
            income["Net Income Common Stockholders"] = v
        pretax, interest = income.get("Pretax Income"), income.get("Interest Expense")
        if pretax is not None and interest is not None:
            income["EBIT"] = pretax + interest
        if "Interest Expense" in income:
            income["Interest Expense"] = abs(income["Interest Expense"])

        cash: dict[str, float] = {}
        for label, names in CASHFLOW.items():
            if (v := _first(flows, names, day)) is not None:
                cash[label] = v
        capex = _first(flows, CAPEX, day)
        if capex is not None:
            capex += _first(flows, CAPEX_INTANGIBLE, day) or 0.0
            cash["Capital Expenditure"] = -abs(capex)
            if "Operating Cash Flow" in cash:
                cash["Free Cash Flow"] = cash["Operating Cash Flow"] - abs(capex)
        if (v := _first(flows, DIVIDENDS, day)) is not None:
            cash["Cash Dividends Paid"] = -abs(v)

        balance: dict[str, float] = {}
        for label, names in BALANCE.items():
            if (v := _first(stocks, names, day)) is not None:
                balance[label] = v
        if (v := _first(stocks, OWNERS_EQUITY, day)) is not None:
            balance["Stockholders Equity"] = v
            balance["Common Stock Equity"] = v
        assets, total = (
            balance.get("Total Assets"),
            balance.get("Total Equity Gross Minority Interest"),
        )
        if (v := _first(stocks, ("Liabilities",), day)) is not None:
            balance["Total Liabilities Net Minority Interest"] = v
        elif assets is not None and total is not None:
            balance["Total Liabilities Net Minority Interest"] = assets - total
        parts = [_first(stocks, names, day) for names in DEBT_PARTS]
        # Debt is the borrowings and the leases; a filing that splits only some
        # of them would understate it, so a partial sum is not a figure.
        if parts[0] is not None and parts[1] is not None:
            debt = sum(p or 0.0 for p in parts)
            balance["Total Debt"] = debt
            if "Cash And Cash Equivalents" in balance:
                balance["Net Debt"] = debt - balance["Cash And Cash Equivalents"]
        years[day] = {
            "currency": currency,
            "income": income,
            "balance": balance,
            "cashflow": cash,
        }
    return years


# --------------------------------------------------------------------- store


def _path(lei: str):
    return ESEF_DIR / f"{lei}.json"


def _read(lei: str) -> dict | None:
    try:
        data = json.loads(_path(lei).read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _doc(url: str) -> dict | None:
    raw = _get(ROOT + url, gzip_ok=True)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if len(raw) > MAX_DOC_BYTES:
        obs.warn("esef.too_big", url=url, bytes=len(raw))
        return None
    text = raw.decode("utf-8", "replace")
    del raw  # not both copies alive while the tree is built
    return json.loads(text)


def refresh(ticker: str, name: str = "", isin: str = "") -> dict | None:
    """Network: bring the issuer's stored years up to date. Never raises.

    Returns the stored record, or None when there is nothing for this name.
    """
    with obs.swallow("esef.refresh", ticker=ticker) as _:
        lei = resolve_lei(ticker, name, isin)
        if not lei:
            return None
        held = _read(lei) or {"lei": lei, "years": {}, "filings": []}
        filings = list_filings(lei)
        done = {f["period_end"]: f for f in held.get("filings", [])}
        for filing in filings:
            if filing["period_end"] in done:
                continue
            doc = _doc(filing["json_url"])
            if doc is None:
                continue
            for day, year in extract(doc).items():
                held["years"].setdefault(day, year)  # newest filing's figures win
            done[filing["period_end"]] = {
                k: filing[k] for k in ("period_end", "published")
            }
        held.update(
            lei=lei,
            name=name or held.get("name", ""),
            filings=sorted(done.values(), key=lambda f: f["period_end"], reverse=True),
            checked=time.time(),
        )
        _write(_path(lei), held)
        obs.event(
            "esef.refreshed",
            ticker=ticker,
            lei=lei,
            years=sorted(held["years"]),
            listed=len(filings),
        )
        return held
    return None


_inflight: set[str] = set()
_gate = threading.Semaphore(1)


def warm(ticker: str, name: str = "", isin: str = "") -> bool:
    """Start `refresh` in the background, one issuer at a time. False if one is
    already running for this ticker or background work is off."""
    key = ticker.upper()
    if not BACKGROUND:
        return False
    with _lock:
        if key in _inflight:
            return False
        _inflight.add(key)

    def run() -> None:
        try:
            with _gate:  # one facts file in memory at a time
                refresh(key, name, isin)
        finally:
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=run, name=f"esef-{key}", daemon=True).start()
    return True


@dataclass(frozen=True)
class Annuals:
    lei: str
    years: dict[str, dict] = field(default_factory=dict)  # period_end -> rows

    @property
    def currency(self) -> str | None:
        return next((y["currency"] for y in self.years.values()), None)


def cached(ticker: str, name: str = "", isin: str = "") -> Annuals | None:
    """What is stored for `ticker` — disk only, never the network.

    A missing or week-old record starts a background refresh; the caller gets
    whatever is held now (None the first time).
    """
    key = ticker.upper()
    known = _read_map().get(key) or {}
    lei = known.get("lei")
    held = _read(lei) if lei else None
    stale = held is None if lei else time.time() - float(known.get("at") or 0) >= MISS_S
    if held and time.time() - float(held.get("checked") or 0) >= RECHECK_S:
        stale = True
    if stale:
        warm(key, name, isin)
    if not held or not held.get("years"):
        return None
    return Annuals(lei=str(held["lei"]), years=dict(held["years"]))


# ------------------------------------------------------------------- overlay


def _column(frame: pd.DataFrame, day: str):
    """The frame column whose period end is within six weeks of `day`."""
    target = pd.Timestamp(day)
    for col in frame.columns:
        try:
            if abs((pd.Timestamp(col) - target).days) <= 45:
                return col
        except (TypeError, ValueError):
            continue
    return None


def _merge(frame: pd.DataFrame, rows: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Write each year's rows into `frame` (labels x period ends, newest first):
    over the matching column, or as a new one for a year Yahoo no longer shows.
    A year whose revenue is off by 2x either way from Yahoo's is skipped whole —
    a unit or currency mismatch, not a restatement."""
    out = frame.copy() if frame is not None and not frame.empty else pd.DataFrame()
    for day in sorted(rows):
        values = rows[day]
        if not values:
            continue
        col = _column(out, day) if not out.empty else None
        if col is None:
            col = pd.Timestamp(day)
            out[col] = float("nan")
        else:
            mine, theirs = (
                values.get("Total Revenue"),
                (out.at["Total Revenue", col] if "Total Revenue" in out.index else None),
            )
            if mine and theirs and not pd.isna(theirs) and not 0.5 <= mine / theirs <= 2:
                obs.warn("esef.mismatch", day=day, esef=mine, other=float(theirs))
                continue
        for label, value in values.items():
            if label not in out.index:
                out.loc[label] = float("nan")
            out.at[label, col] = value
    return (
        out.reindex(sorted(out.columns, reverse=True), axis=1) if not out.empty else out
    )


def overlay(raw):
    """`raw` with ESEF's audited annual rows laid over Yahoo's, or `raw` as is.

    Only for issuers that qualify and only from what is already on disk — a
    first sight returns Yahoo's frames and has the facts fetched for next
    time. Skipped when the statements' currency is not the one ESEF reports
    (Yahoo's `financialCurrency`). Never raises.
    """
    try:
        info = raw.info or {}
        if not eligible(raw.ticker, info):
            return raw
        held = cached(
            raw.ticker, str(info.get("longName") or info.get("shortName") or "")
        )
        if held is None:
            return raw
        theirs = str(info.get("financialCurrency") or "").upper()
        if theirs and held.currency and theirs != held.currency.upper():
            obs.warn(
                "esef.currency_clash", ticker=raw.ticker, esef=held.currency, yahoo=theirs
            )
            return raw
        pick = lambda key: {d: y[key] for d, y in held.years.items()}  # noqa: E731
        import dataclasses

        return dataclasses.replace(
            raw,
            income=_merge(raw.income, pick("income")),
            balance=_merge(raw.balance, pick("balance")),
            cashflow=_merge(raw.cashflow, pick("cashflow")),
            source=SOURCE,
            source_years=tuple(sorted(held.years, reverse=True)),
        )
    except Exception as exc:  # noqa: BLE001 - Yahoo's figures are the floor
        obs.warn(
            "esef.overlay_failed", ticker=getattr(raw, "ticker", ""), error=str(exc)[:160]
        )
        return raw
