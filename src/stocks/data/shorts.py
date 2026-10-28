"""Short selling — what the market is betting against a company.

Two readings, one per side of the Atlantic, because the disclosure regimes
differ:

* **US**: short interest is a position count the exchanges publish twice a
  month. Yahoo's `info` carries it (`shortPercentOfFloat`, `sharesShort`,
  `shortRatio` = days to cover, `sharesShortPriorMonth`, `dateShortInterest`),
  so `from_info` only reads what the fundamentals pull already holds. FINRA adds
  the daily *short volume* — the share of each day's trading that was a short
  sale — from one pipe-delimited file a day for the whole market
  (`cdn.finra.org/equity/regsho/daily/CNMSshvol<YYYYMMDD>.txt`, ~0.5 MB, keyless).
  Short volume is not short interest (market makers short as part of making a
  market, so the ratio sits around 40-50 % for most names); the card shows it as
  a five-day average, labelled as volume, never as a position.

* **EU**: under the Short Selling Regulation a holder of a net short position
  of 0.5 % of a company's shares or more is published by its national
  authority. Probed 2026-10-27, the ones that serve a machine-readable *current*
  list without a bot wall:

  - **AFM** (Netherlands): CSV of every current position, per holder, with date.
  - **Bundesanzeiger** (Germany; BaFin's register): an HTML list, 100 rows a
    page behind a cookie session, per holder with date.
  - **FCA** (UK): a CSV of the *aggregate* net short per issuer only. The
    per-holder file FCA links is the historic one, so holders are unknown here.

  Not usable: CNMV answers 403 to a non-browser client, Consob serves a captcha
  page where its xlsx should be, AMF's register is a single-page app with no
  documented API.

A register is one download per authority per day, shared by every ticker, kept
on disk (and in the bucket) and refreshed *behind* a request: `ensure_fresh`
starts one background pass when a register is stale, and `stocks shorts` runs
the same pass from a cron. A failed or empty download never replaces the last
good one — a blank register is an outage, not "nobody is short".
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from http.cookiejar import CookieJar

from stocks import atomic, obs
from stocks.config import DATA_DIR
from stocks.data import http

USER_AGENT = "Mozilla/5.0 (compatible; stocks-toolkit)"
TIMEOUT = 25

REGISTER_FILE = DATA_DIR / "shorts.json"
VOLUME_FILE = DATA_DIR / "short_volume.json"
REGISTER_TTL_S = 20 * 3600.0
VOLUME_TTL_S = 6 * 3600.0
VOLUME_DAYS = 5
MIN_NAMES = 1000  # a whole market is ~12k names; fewer is a broken file

AFM_URL = (
    "https://www.afm.nl/export.aspx?type=8a46a4ef-f196-4467-a7ab-1ae1cb58f0e7&format=csv"
)
FCA_URL = (
    "https://www.fca.org.uk/publication/documents/aggregated-current-net-short-positions.csv"
)
BUNDESANZEIGER_URL = "https://www.bundesanzeiger.de/pub/en/to_nlp_start"
BUNDESANZEIGER_PAGES = 12  # 477 rows on 2026-10-27 = 5 pages of 100
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt"

TOP_HOLDERS = 5

# Listings the EU/UK registers can speak for (Yahoo suffixes).
EU_VENUES = (
    ".AS", ".DE", ".F", ".BE", ".DU", ".HM", ".HA", ".MU", ".SG", ".MC", ".PA",
    ".MI", ".L", ".BR", ".LS", ".VI", ".HE", ".CO", ".ST", ".OL", ".IR", ".AT",
    ".WA", ".PR", ".BD", ".IL",
)


def eu_listing(ticker: str) -> bool:
    return ticker.upper().endswith(EU_VENUES)


# --- value types -------------------------------------------------------------------


@dataclass(frozen=True)
class ShortHolder:
    name: str
    pct: float
    date: date | None


@dataclass(frozen=True)
class NetShort:
    """One issuer's disclosed net short positions at one authority."""

    source: str
    issuer: str
    isin: str
    total_pct: float
    as_of: date | None
    holders: list[ShortHolder] = field(default_factory=list)


@dataclass(frozen=True)
class UsShort:
    pct_float: float | None  # percent, 6.4 not 0.064
    shares_short: float | None
    days_to_cover: float | None
    prior_shares: float | None
    change_pct: float | None  # shares short vs the month before, percent
    as_of: date | None


@dataclass(frozen=True)
class ShortVolume:
    ratio: float  # percent of the window's volume that was a short sale
    days: int
    as_of: date


# --- names -------------------------------------------------------------------------

_LEGAL = {
    "nv", "plc", "se", "ag", "sa", "spa", "ab", "oyj", "asa", "as", "bv", "ltd",
    "limited", "inc", "corp", "corporation", "co", "kgaa", "sab", "nyrt", "oy",
    "aktiengesellschaft", "public", "company", "holding", "holdings", "group",
}


def name_key(name: str) -> str:
    """A company name as the registers and Yahoo agree on it: accents, case,
    punctuation and legal-form words gone ("Akzo Nobel N.V." -> "akzo nobel")."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ")
    words = re.sub(r"[^a-z0-9]+", " ", text.replace(".", "")).split()
    kept = [w for w in words if w not in _LEGAL]
    return " ".join(kept or words)


# --- pure parsers ------------------------------------------------------------------


def _pct(raw) -> float | None:
    try:
        value = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _day(raw) -> date | None:
    text = str(raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _group(rows: list[tuple[str, str, str, float, date | None]], source: str) -> dict:
    """(holder, issuer, isin, pct, day) rows as one NetShort per issuer.

    A holder appears once, at its latest date; zero or negative positions are a
    closed position and drop out; the total is the sum of what is disclosed.
    """
    latest: dict[tuple[str, str], tuple[str, str, str, float, date | None]] = {}
    for row in rows:
        holder, _, isin, pct, day = row
        if pct <= 0 or not holder:
            continue
        key = (holder, isin)
        old = latest.get(key)
        if old is None or (day or date.min) >= (old[4] or date.min):
            latest[key] = row
    by_issuer: dict[str, list] = {}
    for row in latest.values():
        by_issuer.setdefault(row[2] or name_key(row[1]), []).append(row)
    out = {}
    for isin, group in by_issuer.items():
        group.sort(key=lambda r: r[3], reverse=True)
        days = [r[4] for r in group if r[4]]
        out[isin] = NetShort(
            source=source,
            issuer=group[0][1],
            isin=group[0][2],
            total_pct=round(sum(r[3] for r in group), 2),
            as_of=max(days) if days else None,
            holders=[ShortHolder(r[0], r[3], r[4]) for r in group],
        )
    return out


def parse_afm(text: str) -> dict[str, NetShort]:
    """AFM's `;`-separated export: holder, issuer, ISIN, net short %, date."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";")
    next(reader, None)
    rows = []
    for cells in reader:
        if len(cells) < 5:
            continue
        pct = _pct(cells[3])
        if pct is not None:
            rows.append((cells[0].strip(), cells[1].strip(), cells[2].strip(), pct,
                         _day(cells[4])))
    return _group(rows, "AFM")


def parse_fca(text: str) -> dict[str, NetShort]:
    """FCA's aggregate list: issuer, ISIN, total net short %, latest date.
    No holders — the per-holder file FCA publishes is the historic one."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    next(reader, None)
    out = {}
    for cells in reader:
        if len(cells) < 4:
            continue
        pct = _pct(cells[2])
        if pct is None or pct <= 0:
            continue
        out[cells[1].strip()] = NetShort(
            source="FCA", issuer=cells[0].strip().title(), isin=cells[1].strip(),
            total_pct=round(pct, 2), as_of=_day(cells[3]),
        )
    return out


_ROW = re.compile(
    r'<div class="col-td-1"[^>]*>(?P<holder>.*?)</div>\s*'
    r'<div class="col-td-2">(?P<issuer>.*?)<br\s*/?>.*?</div>\s*'
    r'<div class="col-td-3"[^>]*>(?P<isin>.*?)</div>\s*'
    r'<div class="col-td-4[^"]*"[^>]*>(?P<pct>.*?)</div>\s*'
    r'<div class="col-td-5[^"]*"[^>]*>(?P<day>.*?)</div>',
    re.S,
)


def _text(fragment: str) -> str:
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_bundesanzeiger_page(
    page: str,
) -> list[tuple[str, str, str, float, date | None]]:
    """One result page of the Federal Gazette's net-short list as rows."""
    rows = []
    for m in _ROW.finditer(page):
        pct = _pct(_text(m["pct"]).replace("%", ""))
        if pct is None:
            continue
        rows.append((_text(m["holder"]), _text(m["issuer"]), _text(m["isin"]), pct,
                     _day(_text(m["day"]))))
    return rows


def parse_finra(text: str) -> dict[str, list[int]]:
    """FINRA's daily file as symbol -> [short volume, total volume]."""
    out: dict[str, list[int]] = {}
    for line in text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        try:
            short, total = int(float(parts[2])), int(float(parts[4]))
        except ValueError:
            continue
        if total > 0:
            out[parts[1]] = [short, total]
    return out


def from_info(info: dict | None) -> UsShort | None:
    """The US short-interest figures out of Yahoo's `info`, or None if it has none."""
    info = info or {}
    pct = _pct(info.get("shortPercentOfFloat"))
    shares = _pct(info.get("sharesShort"))
    if pct is None and shares is None:
        return None
    prior = _pct(info.get("sharesShortPriorMonth"))
    stamp = info.get("dateShortInterest")
    as_of = None
    if isinstance(stamp, int | float) and stamp > 0:
        as_of = datetime.fromtimestamp(stamp, tz=UTC).date()
    return UsShort(
        pct_float=None if pct is None else round(pct * 100, 2),
        shares_short=shares,
        days_to_cover=_pct(info.get("shortRatio")),
        prior_shares=prior,
        change_pct=round((shares / prior - 1) * 100, 1) if shares and prior else None,
        as_of=as_of,
    )


# --- stored registers --------------------------------------------------------------

_lock = threading.Lock()
_store: dict | None = None
_index: dict[str, NetShort] | None = None
_volume: dict | None = None
_refreshing = threading.Event()


def _read(path, name: str) -> dict:
    if not path.exists():
        with obs.swallow(f"shorts.restore_{name}"):
            from stocks import storage

            storage.restore(path)
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _encode(entry: NetShort) -> dict:
    return {
        "source": entry.source, "issuer": entry.issuer, "isin": entry.isin,
        "total": entry.total_pct, "as_of": str(entry.as_of or ""),
        "holders": [[h.name, h.pct, str(h.date or "")] for h in entry.holders],
    }


def _decode(raw: dict) -> NetShort:
    return NetShort(
        source=raw["source"], issuer=raw["issuer"], isin=raw.get("isin", ""),
        total_pct=float(raw["total"]), as_of=_day(raw.get("as_of")),
        holders=[
            ShortHolder(h[0], float(h[1]), _day(h[2])) for h in raw.get("holders", [])
        ],
    )


def _registers() -> dict:
    global _store
    with _lock:
        if _store is None:
            loaded = _read(REGISTER_FILE, "register")
            loaded.setdefault("fetched", {})
            loaded.setdefault("registers", {})
            _store = loaded
        return _store


def clear_cache() -> None:
    """Forget every in-process cache — for tests that point the files elsewhere."""
    global _store, _index, _volume
    with _lock:
        _store = _index = _volume = None


def _save(path, payload: dict, name: str) -> None:
    with obs.swallow(f"shorts.save_{name}"):
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(path, payload, separators=(",", ":"))
        from stocks import storage

        storage.persist(path)


def _cookie_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()),
        urllib.request.HTTPSHandler(context=http._context()),
    )


def fetch_bundesanzeiger() -> dict[str, NetShort]:
    """The whole German list: a cookie session, 100 rows a page, then Next."""
    opener = _cookie_opener()

    def call(url: str, data: bytes | None = None) -> str:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        with opener.open(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")

    page = call(BUNDESANZEIGER_URL)
    form = re.search(r'action="([^"]*top~nav-form)"', page)
    if form is None:
        return {}
    page = call(
        form.group(1).replace("&amp;", "&"),
        urllib.parse.urlencode({"hitsperpage-select": "argus-HitsPerPage100"}).encode(),
    )
    rows: list = []
    for _ in range(BUNDESANZEIGER_PAGES):
        got = parse_bundesanzeiger_page(page)
        rows.extend(got)
        nxt = re.search(r'href="([^"]*top~nav-pager-next)"', page)
        if not got or nxt is None:
            break
        page = call(nxt.group(1).replace("&amp;", "&"))
    return _group(rows, "BaFin")


def _download(url: str) -> str:
    return http.get_bytes(url, user_agent=USER_AGENT, timeout=TIMEOUT).decode(
        "utf-8", errors="replace")


_SOURCES: dict[str, Callable[[], dict[str, NetShort]]] = {
    "AFM": lambda: parse_afm(_download(AFM_URL)),
    "FCA": lambda: parse_fca(_download(FCA_URL)),
    "BaFin": fetch_bundesanzeiger,
}


def refresh_registers(*, force: bool = False) -> dict[str, str]:
    """Download every stale register; returns what each one did.

    A register that fails or comes back empty keeps the last good copy.
    """
    global _index
    store = _registers()
    result: dict[str, str] = {}
    changed = False
    for name, fetch in _SOURCES.items():
        stamp = store["fetched"].get(name, 0)
        if not force and time.time() - stamp < REGISTER_TTL_S:
            result[name] = "fresh"
            continue
        try:
            entries = fetch()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            obs.warn("shorts.fetch_failed", source=name, error_type=type(exc).__name__)
            result[name] = "failed"
            continue
        if not entries:
            obs.warn("shorts.fetch_empty", source=name)
            result[name] = "empty"
            continue
        with _lock:
            store["registers"][name] = {k: _encode(v) for k, v in entries.items()}
            store["fetched"][name] = time.time()
            _index = None
        changed = True
        result[name] = f"{len(entries)} issuers"
    if changed:
        _save(REGISTER_FILE, store, "register")
    return result


def _volume_store() -> dict:
    global _volume
    with _lock:
        if _volume is None:
            loaded = _read(VOLUME_FILE, "volume")
            loaded.setdefault("days", {})
            loaded.setdefault("fetched", 0)
            _volume = loaded
        return _volume


def refresh_volume(*, force: bool = False, today: date | None = None) -> str:
    """Add the FINRA files published since the last pass; keep the latest five."""
    store = _volume_store()
    if not force and time.time() - store["fetched"] < VOLUME_TTL_S:
        return "fresh"
    today = today or date.today()
    added = 0
    for back in range(8):
        day = today - timedelta(days=back)
        key = day.strftime("%Y%m%d")
        if day.weekday() >= 5 or key in store["days"]:
            continue
        try:
            body = http.get_bytes(FINRA_URL.format(day=key), user_agent=USER_AGENT,
                                  timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):  # not published yet, or a market holiday
                continue
            obs.warn("shorts.volume_failed", error_type="HTTPError", code=exc.code)
            return "failed"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            obs.warn("shorts.volume_failed", error_type=type(exc).__name__)
            return "failed"
        parsed = parse_finra(body.decode("utf-8", errors="replace"))
        if len(parsed) < MIN_NAMES:
            obs.warn("shorts.volume_empty", day=key, names=len(parsed))
            continue
        with _lock:
            store["days"][key] = parsed
        added += 1
    with _lock:
        for old in sorted(store["days"])[:-VOLUME_DAYS]:
            del store["days"][old]
        store["fetched"] = time.time()
    if added:
        _save(VOLUME_FILE, store, "volume")
    return f"{added} days" if added else "nothing new"


def refresh(*, force: bool = False) -> dict[str, str]:
    """Every register and the FINRA volume, one pass (the cron's whole job)."""
    out = refresh_registers(force=force)
    out["FINRA"] = refresh_volume(force=force)
    return out


def _stale() -> bool:
    store = _registers()
    now = time.time()
    if any(now - store["fetched"].get(n, 0) >= REGISTER_TTL_S for n in _SOURCES):
        return True
    return now - _volume_store()["fetched"] >= VOLUME_TTL_S


def ensure_fresh() -> None:
    """Start a background refresh when something is stale; never waits for it.

    One pass at a time: a page that asks while another is running returns at
    once with whatever is stored.
    """
    if _refreshing.is_set() or not _stale():
        return

    def run() -> None:
        try:
            with obs.swallow("shorts.background"):
                refresh()
        finally:
            _refreshing.clear()

    _refreshing.set()
    threading.Thread(target=run, name="shorts-refresh", daemon=True).start()


# --- lookups -----------------------------------------------------------------------


def _names() -> dict[str, NetShort]:
    """Normalised issuer name -> its entry; a name two issuers share is dropped."""
    global _index
    store = _registers()
    with _lock:
        if _index is not None:
            return _index
        index: dict[str, NetShort | None] = {}
        for name in _SOURCES:
            for raw in store["registers"].get(name, {}).values():
                entry = _decode(raw)
                key = name_key(entry.issuer)
                index[key] = None if key in index else entry
        _index = {k: v for k, v in index.items() if v is not None}
        return _index


def net_short(issuer: str | None) -> NetShort | None:
    """The disclosed net short positions of the company called `issuer`."""
    if not issuer:
        return None
    return _names().get(name_key(issuer))


def short_volume(symbol: str) -> ShortVolume | None:
    """FINRA short volume as a share of volume over the stored days, or None."""
    days = _volume_store()["days"]
    short = total = used = 0
    latest = ""
    for key in sorted(days):
        row = days[key].get(symbol.upper())
        if row:
            short, total, used, latest = short + row[0], total + row[1], used + 1, key
    if not used or not total:
        return None
    return ShortVolume(round(short / total * 100, 1), used,
                       datetime.strptime(latest, "%Y%m%d").date())
