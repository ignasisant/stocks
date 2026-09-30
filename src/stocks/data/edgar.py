"""SEC EDGAR client — primary source for US filers (10-K/10-Q facts).

Free, no API key. SEC requires a descriptive User-Agent with contact info:
set EDGAR_USER_AGENT in .env (e.g. "stocks-toolkit you@example.com").

Used to cross-check yfinance numbers against filed XBRL facts, per the
verification hierarchy in stocks.analysis.fundamentals.KPI_SOURCES.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date

import pandas as pd

from stocks import atomic
from stocks.config import DATA_DIR
from stocks.data.http import get_json
from stocks.fuzzy import FUZZY_CUTOFF, MIN_QUERY, fuzzy_ratio

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
TICKER_CACHE = DATA_DIR / "edgar_tickers.json"

# XBRL revenue tag varies by filer; try in order.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
NET_INCOME_TAGS = ["NetIncomeLoss"]
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]


def _user_agent() -> str:
    return os.getenv("EDGAR_USER_AGENT") or (
        "stocks-toolkit (set EDGAR_USER_AGENT in .env)"
    )


def _get_json(url: str) -> dict:
    return get_json(url, user_agent=_user_agent())


# ticker -> zero-padded CIK / company title, built once per process (the map
# file is ~10k rows; re-reading and linear-scanning it per lookup was the old
# behaviour). _ROWS keeps the file's order — roughly by market cap — so
# search results break rank ties sensibly.
_CIK_MAP: dict[str, str] | None = None
_TITLE_MAP: dict[str, str] | None = None
_ROWS: list[tuple[str, str, int]] | None = None


def _load_map() -> None:
    global _CIK_MAP, _TITLE_MAP, _ROWS
    if _CIK_MAP is not None:
        return
    if not TICKER_CACHE.exists():
        atomic.write_json(TICKER_CACHE, _get_json(TICKER_MAP_URL))
    table = json.loads(TICKER_CACHE.read_text())
    _CIK_MAP = {
        row["ticker"].upper(): str(row["cik_str"]).zfill(10)
        for row in table.values()
    }
    _TITLE_MAP = {
        row["ticker"].upper(): row["title"]
        for row in table.values()
        if row.get("title")
    }
    _ROWS = [
        (row["ticker"].upper(), row.get("title") or "", int(row["cik_str"]))
        for row in table.values()
    ]


def _cik_map() -> dict[str, str]:
    _load_map()
    return _CIK_MAP or {}


def _display_title(title: str) -> str:
    """SEC titles are often shouty ("MICROSOFT CORP"); title-case all-caps."""
    return title.title() if title.isupper() else title


def cik_for(ticker: str) -> str | None:
    """10-digit CIK for a ticker; ticker map cached under data/ and in memory."""
    return _cik_map().get(ticker.upper())


def title_for(ticker: str) -> str | None:
    """Company title from the SEC ticker map (US listings only), or None."""
    _load_map()
    title = (_TITLE_MAP or {}).get(ticker.upper())
    return _display_title(title) if title else None


def search_companies(query: str, limit: int = 8) -> list[tuple[str, str]]:
    """Search the SEC ticker map by symbol or company name.

    Up to `limit` (ticker, display name) pairs, best match first: exact
    ticker, then ticker prefix, then name word-prefix, then any substring
    of ticker or name (this last tier is what catches multi-word queries
    like "bank of america"). Ties keep the file order, which is roughly
    descending market cap. US listings only — the SEC map carries no
    foreign-exchange symbols.

    Hyphenated share classes of an already-matched company (BAC-PB and the
    other preferred series behind "bank of america") are skipped so a name
    query doesn't return one issuer `limit` times; distinct plain listings
    (GOOG next to GOOGL) survive.

    When no tier matches at all, a fuzzy pass catches typos ("nvidai",
    "microsft") — score-ordered, same share-class dedup.
    """
    q = query.strip().upper()
    if not q:
        return []
    _load_map()
    ranked: list[tuple[int, int, str, str]] = []
    seen_cik: set[int] = set()
    for i, (ticker, title, cik) in enumerate(_ROWS or []):
        name = title.upper()
        if ticker == q:
            rank = 0
        elif ticker.startswith(q):
            rank = 1
        elif any(word.startswith(q) for word in name.split()):
            rank = 2
        elif q in ticker or q in name:
            rank = 3
        else:
            continue
        if "-" in ticker and cik in seen_cik and ticker != q:
            continue
        seen_cik.add(cik)
        ranked.append((rank, i, ticker, title))
    if not ranked and len(q) >= MIN_QUERY:
        return _fuzzy_companies(q, limit)
    ranked.sort()
    return [(t, _display_title(n)) for _, _, t, n in ranked[:limit]]


def _fuzzy_companies(q: str, limit: int) -> list[tuple[str, str]]:
    """Typo fallback for `search_companies` — best fuzzy scores first."""
    scored: list[tuple[float, int, str, str]] = []
    seen_cik: set[int] = set()
    for i, (ticker, title, cik) in enumerate(_ROWS or []):
        score = max(fuzzy_ratio(q, ticker), fuzzy_ratio(q, title.upper()))
        if score < FUZZY_CUTOFF:
            continue
        if "-" in ticker and cik in seen_cik:
            continue
        seen_cik.add(cik)
        scored.append((-score, i, ticker, title))
    scored.sort()
    return [(t, _display_title(n)) for _, _, t, n in scored[:limit]]


def company_facts(ticker: str) -> dict | None:
    """Full XBRL companyfacts payload, or None for non-US filers."""
    cik = cik_for(ticker)
    return _get_json(FACTS_URL.format(cik=cik)) if cik else None


def latest_annual_fact(facts: dict, tags: list[str]) -> tuple[str, float] | None:
    """Most recent 10-K value for the first matching tag: (fy_end, value)."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {})
        annual = [
            f
            for f in units.get("USD", [])
            if f.get("form") == "10-K" and f.get("fp") == "FY" and "end" in f
        ]
        if annual:
            latest = max(annual, key=lambda f: f["end"])
            return latest["end"], float(latest["val"])
    return None


def cross_check(ticker: str) -> dict[str, tuple[str, float] | None]:
    """Latest filed annual revenue and net income — the 'fact' anchor."""
    facts = company_facts(ticker)
    if facts is None:
        return {"revenue": None, "net_income": None}
    return {
        "revenue": latest_annual_fact(facts, REVENUE_TAGS),
        "net_income": latest_annual_fact(facts, NET_INCOME_TAGS),
    }


def _duration_days(fact: dict) -> int | None:
    try:
        return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
    except (KeyError, ValueError):
        return None


def diluted_eps_facts(ticker: str) -> pd.DataFrame:
    """Raw diluted-EPS facts from XBRL: columns end/filed/eps/kind, oldest-first.

    `kind` is 'Q' for a discrete ~3-month period or 'FY' for a full fiscal year
    (10-Ks report the year, never a discrete Q4). Values are AS REPORTED — not
    split-adjusted and not Q4-reconstructed; both happen in analysis.pe_history,
    which must split-adjust to a common basis *before* deriving Q4 = FY − 3Q
    (a split mid-year otherwise mixes per-share bases and corrupts the result).

    `filed` is the earliest date each figure was public, so downstream TTM logic
    can avoid look-ahead bias. Empty for non-US filers (no CIK) or no EPS facts.
    """
    facts = company_facts(ticker)
    if facts is None:
        return pd.DataFrame(columns=["end", "filed", "eps", "kind"])
    gaap = facts.get("facts", {}).get("us-gaap", {})
    raw: list[dict] = []
    for tag in EPS_TAGS:
        for arr in gaap.get(tag, {}).get("units", {}).values():
            raw += arr
        if raw:
            break

    picked: dict[tuple[date, str], tuple[float, str]] = {}
    for f in raw:
        dur = _duration_days(f)
        if dur is None or "val" not in f:
            continue
        if 80 <= dur <= 100:
            kind = "Q"
        elif 350 <= dur <= 385:
            kind = "FY"
        else:
            continue
        end, filed, val = date.fromisoformat(f["end"]), f["filed"], float(f["val"])
        key = (end, kind)
        if key not in picked or filed < picked[key][1]:  # earliest filing wins
            picked[key] = (val, filed)

    rows = sorted((e, filed, val, kind) for (e, kind), (val, filed) in picked.items())
    return pd.DataFrame(rows, columns=["end", "filed", "eps", "kind"])


# ------------------------------------------------------------ press releases
# A US filer's earnings release is an 8-K under Item 2.02 with the release
# itself as exhibit 99.1 — the company's own account of the quarter, which is
# where "revenue up 94%, driven by data center" lives and the XBRL facts do
# not. Read only for the daily card's "see more" on a print, and cached on disk
# per (ticker, report date): a release never changes once filed, and every
# account that follows the name reads the same one.

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index.htm"
)
ARCHIVE_URL = "https://www.sec.gov{path}"
RELEASE_DIR = DATA_DIR / "edgar_releases"
# How far a filing may sit from the report date the calendar gives: the 8-K is
# usually filed the same day, a day late for an after-hours print.
RELEASE_SLACK_DAYS = 3
RELEASE_CHARS = 3000

_EXHIBIT_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r'href="(/Archives/[^"]+\.html?)"', re.IGNORECASE)


def _release_filing(cik: str, report: date) -> str | None:
    """Accession number of the Item 2.02 8-K filed around `report`, or None."""
    subs = _get_json(SUBMISSIONS_URL.format(cik=cik))
    recent = (subs.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    filed = recent.get("filingDate") or []
    items = recent.get("items") or []
    accessions = recent.get("accessionNumber") or []
    best: tuple[int, str] | None = None
    for form, day, item, accession in zip(forms, filed, items, accessions, strict=False):
        if form != "8-K" or "2.02" not in str(item):
            continue
        try:
            gap = abs((date.fromisoformat(day) - report).days)
        except ValueError:
            continue
        if gap <= RELEASE_SLACK_DAYS and (best is None or gap < best[0]):
            best = (gap, accession)
    return best[1] if best else None


def _exhibit_path(cik: str, accession: str) -> str | None:
    """The EX-99.1 document's archive path, off the filing's index page."""
    from stocks.data.http import get_bytes

    page = get_bytes(
        ARCHIVE_INDEX_URL.format(
            cik=int(cik), folder=accession.replace("-", ""), accession=accession
        ),
        user_agent=_user_agent(),
        timeout=20,
    ).decode("utf-8", "replace")
    for row in _EXHIBIT_ROW_RE.findall(page):
        if re.search(r">\s*EX-99(?:\.1|\.01)?\s*<", row, re.IGNORECASE):
            href = _HREF_RE.search(row)
            if href:
                return href.group(1)
    return None


def _release_text(raw: bytes) -> str:
    """The release's narrative: its paragraphs, before the tables."""
    from lxml import html as lxml_html

    try:
        doc = lxml_html.fromstring(raw)
    except Exception:  # noqa: BLE001 — an unparsable exhibit is no excerpt
        return ""
    for bad in doc.xpath("//script|//style|//table"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)
    paras = [" ".join(p.text_content().split()) for p in doc.xpath("//p|//div[not(*)]")]
    # The exhibit opens with EDGAR's own header cell ("EX-99.1 2 q2fy27pr.htm").
    text = " ".join(
        p for p in dict.fromkeys(paras) if len(p) > 40 and not p.startswith("EX-99")
    )
    if not text:
        text = " ".join(doc.text_content().split())
    return text[:RELEASE_CHARS]


def earnings_release(ticker: str, report: date) -> str | None:
    """The opening of `ticker`'s earnings press release for the print on
    `report`, or None — not a US filer, no Item 2.02 8-K near that date, a
    refused request. Never raises."""
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    cached = RELEASE_DIR / f"{ticker.upper().replace('/', '_')}_{report.isoformat()}.txt"
    if cached.exists():
        return cached.read_text() or None
    try:
        cik = cik_for(ticker)
        if not cik:
            return None
        accession = _release_filing(cik, report)
        path = _exhibit_path(cik, accession) if accession else None
        if not path:
            text = ""
        else:
            from stocks.data.http import get_bytes

            text = _release_text(
                get_bytes(
                    ARCHIVE_URL.format(path=path), user_agent=_user_agent(), timeout=20
                )
            )
    except Exception:  # noqa: BLE001 — the detail degrades to the EPS line
        return None
    # A miss is cached too (empty file): the filing will not appear later for a
    # print already days old, and asking again costs three SEC round trips.
    cached.write_text(text)
    return text or None
