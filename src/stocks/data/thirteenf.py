"""Who holds a US stock, straight from the SEC's 13F filings.

Every manager with over $100M in US equities files a 13F-HR within 45 days of
a quarter's end: each position as a CUSIP and a share count. The SEC bundles a
filing window into one zip (the "Form 13F data sets", ~100 MB, ~4M positions).
Yahoo (`data.holders`) aggregates the same filings, but one name at a time and
behind a rate limit; this reads the source once a quarter.

What was weighed (the options, cheapest first):

* per-filer information tables for a curated top-50 — a submissions call, an
  index page and a 5-50 MB XML per manager per quarter, ~300 requests, and
  only ever "the funds on our list", which is not "the top holders";
* the quarterly data sets — two downloads, streamed from disk row by row (the
  zip is never unpacked), a few hundred MB of memory at peak, ~1.5 min of one
  vCPU. Complete, so "top holders" is true. This is what runs.

Pipeline (`build`, run from `stocks holdings-13f`, never on a page route):

1. the newest window and the one before it come off the SEC's index page;
2. window now: top `KEEP` holders per CUSIP (a bounded heap, so memory is
   CUSIPs x KEEP, not positions);
3. window before: what the current top holders held a quarter earlier, and
   the previous top holders (to spot a position sold out entirely);
4. the result is one SQLite file under data/ (a few MB) mirrored to the
   bucket; the server only ever does indexed SELECTs against it;
5. CUSIP -> ticker comes from OpenFIGI (free, keyless: 250 CUSIPs a minute),
   resolved most-held first within a time budget and remembered for good —
   a CUSIP never changes ticker meaningfully, so a re-run only maps new ones.

Figures are a quarter old by construction and every answer carries the
report date. Shares are the filer's whole position (sole + shared voting,
every sub-account summed); options and notes are left out. Where a filer
amended a quarter, the latest full restatement wins; an amendment that only
adds holdings is ignored. Values are dollars at the quarter's end.
"""

from __future__ import annotations

import contextlib
import csv
import heapq
import io
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from stocks import obs, storage
from stocks.config import DATA_DIR
from stocks.data import http

DB = DATA_DIR / "thirteenf.sqlite"
INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
SEC_ROOT = "https://www.sec.gov"
FIGI_URL = "https://api.openfigi.com/v3/mapping"

# Holders kept per CUSIP, and shown by default.
KEEP = 12
# A CUSIP held by fewer filers than this is not a name anyone looks up.
MIN_HOLDERS = 10
# A stake that moved less than this over the quarter is "held" (percent).
MOVE_PCT = 2.0
# Keyless OpenFIGI: 25 requests a minute, 10 CUSIPs each. With a key, 100.
FIGI_BATCH_KEYLESS, FIGI_BATCH_KEYED = 10, 100
FIGI_PAUSE_KEYLESS, FIGI_PAUSE_KEYED = 2.5, 0.3

_ZIP_RE = re.compile(r'href="(/files/[^"]+_form13f\.zip)"')
_DAY_FORMAT = "%d-%b-%Y"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS holding (
    cusip TEXT, rank INTEGER, cik INTEGER, shares INTEGER, value REAL,
    prev_shares INTEGER);
CREATE INDEX IF NOT EXISTS holding_cusip ON holding (cusip);
CREATE TABLE IF NOT EXISTS sold (
    cusip TEXT, cik INTEGER, prev_shares INTEGER, prev_value REAL);
CREATE INDEX IF NOT EXISTS sold_cusip ON sold (cusip);
CREATE TABLE IF NOT EXISTS manager (cik INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS cusip (
    cusip TEXT PRIMARY KEY, total REAL, holders INTEGER,
    ticker TEXT, name TEXT, resolved INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS cusip_ticker ON cusip (ticker);
"""


# ----------------------------------------------------------------- results


@dataclass(frozen=True)
class Position:
    """One manager's stake in a company, against a quarter before."""

    manager: str
    shares: int
    value: float
    prev_shares: int | None  # None: no position a quarter earlier (new)

    @property
    def change_pct(self) -> float | None:
        if not self.prev_shares:
            return None
        return round((self.shares - self.prev_shares) / self.prev_shares * 100, 2)

    @property
    def status(self) -> str:
        if self.shares == 0:
            return "sold_out"
        if not self.prev_shares:
            return "new"
        change = self.change_pct or 0.0
        if change >= MOVE_PCT:
            return "added"
        if change <= -MOVE_PCT:
            return "cut"
        return "held"


@dataclass(frozen=True)
class Holdings:
    as_of: date
    top: list[Position]
    sold_out: list[Position] = field(default_factory=list)


# --------------------------------------------------------------- the scan


@dataclass
class Scan:
    period: date | None = None
    top: dict[str, list[tuple[int, int, float]]] = field(default_factory=dict)
    total: dict[str, float] = field(default_factory=dict)
    count: dict[str, int] = field(default_factory=dict)
    got: dict[tuple[str, int], int] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)
    filers: set[int] = field(default_factory=set)


def _day(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip().title(), _DAY_FORMAT).date()
    except ValueError:
        return None


def _rows(zf: zipfile.ZipFile, name: str) -> Iterator[list[str]]:
    with zf.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        yield from csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


def _table(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    rows = _rows(zf, name)
    header = next(rows, None) or []
    for row in rows:
        yield dict(zip(header, row, strict=False))


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    return (name.title() if name.isupper() else name)[:80]


def _chosen(zf: zipfile.ZipFile) -> tuple[date | None, dict[str, int], set[int]]:
    """The window's reporting quarter; per accession, the filer's CIK for the
    one filing of that quarter each manager's figures come from; and the
    filers whose filing withholds positions under confidential treatment (an
    absent position there is not a sale)."""
    submissions: list[tuple[str, str, int, date | None, date | None]] = []
    periods: dict[date, int] = {}
    for row in _table(zf, "SUBMISSION.tsv"):
        kind = row.get("SUBMISSIONTYPE", "")
        if kind not in ("13F-HR", "13F-HR/A"):
            continue
        period = _day(row.get("PERIODOFREPORT", ""))
        try:
            cik = int(row.get("CIK", ""))
        except ValueError:
            continue
        if period is None:
            continue
        if kind == "13F-HR":
            periods[period] = periods.get(period, 0) + 1
        submissions.append(
            (row["ACCESSION_NUMBER"], kind, cik, period, _day(row.get("FILING_DATE", "")))
        )
    if not periods:
        return None, {}, set()
    target = max(periods, key=lambda p: periods[p])
    restated: set[str] = set()
    confidential: set[str] = set()
    for row in _table(zf, "COVERPAGE.tsv"):
        accession = row.get("ACCESSION_NUMBER", "")
        if row.get("AMENDMENTTYPE", "").upper() == "RESTATEMENT":
            restated.add(accession)
        if "confidential" in row.get("ADDITIONALINFORMATION", "").lower():
            confidential.add(accession)
    best: dict[int, tuple[int, date, str]] = {}
    for accession, kind, cik, period, filed in submissions:
        if period != target:
            continue
        if kind == "13F-HR/A" and accession not in restated:
            continue
        # A restatement beats the original; among equals the later filing.
        rank = (1 if kind == "13F-HR/A" else 0, filed or date.min, accession)
        if cik not in best or rank > best[cik]:
            best[cik] = rank
    chosen = {acc: cik for cik, (_, _, acc) in best.items()}
    withheld = {cik for acc, cik in chosen.items() if acc in confidential}
    return target, chosen, withheld


def scan(path: Path, *, keep: int = KEEP, want: set[tuple[str, int]] | None = None,
         names: bool = False) -> Scan:
    """One pass over a data-set zip.

    `keep` > 0 builds the top-`keep` holders of every CUSIP; `want` records
    the shares of just those (cusip, filer) pairs. Rows of one filing are
    contiguous in INFOTABLE, so a filing is summed per CUSIP and flushed when
    the next one begins: memory is one filing plus the heaps.
    """
    out = Scan()
    with zipfile.ZipFile(path) as zf:
        out.period, chosen, withheld = _chosen(zf)
        out.filers = set(chosen.values()) - withheld
        if names:
            for row in _table(zf, "COVERPAGE.tsv"):
                cik = chosen.get(row.get("ACCESSION_NUMBER", ""))
                if cik is not None and row.get("FILINGMANAGER_NAME"):
                    out.names[cik] = _clean_name(row["FILINGMANAGER_NAME"])
        rows = _rows(zf, "INFOTABLE.tsv")
        header = next(rows, None) or []
        try:
            at = {k: header.index(k) for k in (
                "ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMT",
                "SSHPRNAMTTYPE", "PUTCALL")}
        except ValueError as exc:
            raise ValueError(f"13F INFOTABLE columns changed: {exc}") from exc
        i_acc, i_cus, i_val, i_amt, i_typ, i_put = (
            at[k] for k in ("ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMT",
                            "SSHPRNAMTTYPE", "PUTCALL"))
        last = ""
        cik = None
        agg: dict[str, list[float]] = {}

        def flush() -> None:
            if cik is None:
                return
            for cus, (shares, value) in agg.items():
                if shares <= 0:
                    continue
                if keep:
                    out.total[cus] = out.total.get(cus, 0.0) + value
                    out.count[cus] = out.count.get(cus, 0) + 1
                    heap = out.top.setdefault(cus, [])
                    item = (int(shares), cik, value)
                    if len(heap) < keep:
                        heapq.heappush(heap, item)
                    elif item > heap[0]:
                        heapq.heappushpop(heap, item)
                if want is not None and (cus, cik) in want:
                    out.got[(cus, cik)] = int(shares)
            agg.clear()

        for row in rows:
            if len(row) <= i_put:
                continue
            accession = row[i_acc]
            if accession != last:
                flush()
                last = accession
                cik = chosen.get(accession)
            if cik is None or row[i_typ] != "SH" or row[i_put]:
                continue
            cus = row[i_cus].strip().upper()
            if len(cus) != 9:
                continue
            try:
                shares, value = float(row[i_amt]), float(row[i_val])
            except ValueError:
                continue
            cell = agg.setdefault(cus, [0.0, 0.0])
            cell[0] += shares
            cell[1] += value
        flush()
    return out


# -------------------------------------------------------------- the build


def window_zips(html: str) -> list[str]:
    """The data-set zip paths on the SEC's index page, newest first."""
    return list(dict.fromkeys(_ZIP_RE.findall(html)))


def _user_agent() -> str:
    from stocks.data import edgar

    return edgar._user_agent()


def _page() -> str:
    return http.get_bytes(
        INDEX_URL, user_agent=_user_agent(), timeout=30).decode("utf-8", "replace")


def _fetch_zip(path: str, dest: Path) -> Path:
    http.download(SEC_ROOT + path, dest, user_agent=_user_agent(), timeout=120)
    return dest


def _post(url: str, jobs: list, **kwargs):
    return http.post_json(url, jobs, **kwargs)[0]


def _write(path: Path, cur: Scan, prev: Scan,
           sold: dict[tuple[str, int], tuple[int, float]],
           zips: tuple[str, str], keep_map: dict[str, tuple] | None) -> None:
    """The new index in a file beside `path`, renamed over it when whole."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        cusips = [c for c, n in cur.count.items() if n >= MIN_HOLDERS]
        ciks: set[int] = set()
        for cus in cusips:
            ranked = sorted(cur.top[cus], reverse=True)
            for rank, (shares, cik, value) in enumerate(ranked):
                prior = prev.got.get((cus, cik), 0)
                db.execute("INSERT INTO holding VALUES (?,?,?,?,?,?)",
                           (cus, rank, cik, shares, value, prior or None))
                ciks.add(cik)
        for (cus, cik), (shares, value) in sold.items():
            if cus in cur.count and cur.count[cus] >= MIN_HOLDERS:
                db.execute("INSERT INTO sold VALUES (?,?,?,?)",
                           (cus, cik, shares, value))
                ciks.add(cik)
        db.executemany("INSERT INTO manager VALUES (?,?)",
                       [(c, cur.names.get(c) or prev.names.get(c) or f"CIK {c}")
                        for c in ciks])
        for cus in cusips:
            kept = (keep_map or {}).get(cus)
            db.execute("INSERT INTO cusip VALUES (?,?,?,?,?,?)",
                       (cus, cur.total[cus], cur.count[cus],
                        kept[0] if kept else None, kept[1] if kept else None,
                        1 if kept else 0))
        meta = {"period": (cur.period or date.min).isoformat(),
                "prev_period": (prev.period or date.min).isoformat(),
                "zip": zips[0], "prev_zip": zips[1],
                "built": date.today().isoformat()}
        db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
        db.commit()
    finally:
        db.close()
    os.replace(tmp, path)


def _old_map(path: Path) -> dict[str, tuple]:
    """Tickers already resolved in the index being replaced."""
    if not path.exists():
        return {}
    try:
        db = sqlite3.connect(path)
        try:
            return {c: (t, n) for c, t, n in db.execute(
                "SELECT cusip, ticker, name FROM cusip WHERE resolved = 1")}
        finally:
            db.close()
    except sqlite3.Error:
        return {}


def meta(path: Path = DB) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return dict(db.execute("SELECT key, value FROM meta"))
        finally:
            db.close()
    except sqlite3.Error:
        return {}


def build(*, force: bool = False, path: Path = DB, html: str | None = None,
          fetch_zip=None) -> str:
    """Make the index current: "built <period>" after a scan, "current" when
    the newest window is already in. Raises on a failed download — the
    previous file stays in place."""
    page = html if html is not None else _page()
    zips = window_zips(page)
    if len(zips) < 2:
        raise RuntimeError("13F data sets page lists no windows")
    if storage.enabled() and not path.exists():
        with obs.swallow("thirteenf.restore"):
            storage.restore(path)
    newest, before = zips[0], zips[1]
    if not force and meta(path).get("zip") == newest:
        return "current"
    fetch_zip = fetch_zip or _fetch_zip
    with tempfile.TemporaryDirectory(prefix="13f-") as tmp:
        # Each zip is dropped as soon as it has been read: ~100 MB of disk at
        # a time on an instance that has little.
        cur_zip = fetch_zip(newest, Path(tmp) / "cur.zip")
        started = time.monotonic()
        cur = scan(cur_zip, names=True)
        cur_s = time.monotonic() - started
        wanted = {(c, cik) for c, rows in cur.top.items()
                  if cur.count[c] >= MIN_HOLDERS for _, cik, _ in rows}
        prev_zip = fetch_zip(before, Path(tmp) / "prev.zip")
        prev = scan(prev_zip, want=wanted)
        prev_s = time.monotonic() - started - cur_s
        # Last quarter's top holders no longer among the current ones, among
        # managers that did file this quarter (a missing filing is not a sale).
        gone = {
            (c, cik): (shares, value)
            for c, rows in prev.top.items() if cur.count.get(c, 0) >= MIN_HOLDERS
            for shares, cik, value in rows
            if (c, cik) not in wanted and cik in cur.filers
        }
        # Who among last quarter's top holders holds nothing now: one light
        # pass of the current zip over just those pairs.
        still = scan(cur_zip, keep=0, want=set(gone)) if gone else Scan()
        sold = {k: v for k, v in gone.items() if not still.got.get(k)}
    if cur.period is None or not cur.top:
        raise RuntimeError("13F window held no 13F-HR positions")
    if prev.period and cur.period and prev.period >= cur.period:
        raise RuntimeError("13F windows out of order")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, cur, prev, sold, (newest, before), _old_map(path))
    if storage.enabled():
        with obs.swallow("thirteenf.persist"):
            storage.persist(path)
    obs.event("thirteenf.built", period=str(cur.period), cusips=len(cur.top),
              holders=sum(len(v) for v in cur.top.values()),
              cur_s=round(cur_s, 1), prev_s=round(prev_s, 1))
    return f"built {cur.period}"


# ------------------------------------------------------- CUSIP -> ticker

_FIGI_TYPES = {"Common Stock", "ADR", "REIT", "Depositary Receipt", "ETP",
               "Closed-End Fund", "Preference", "Unit", "MLP", "GDR"}


def _figi_key() -> str | None:
    from stocks.data import openfigi

    return openfigi.api_key()


def _ticker_of(answer: dict) -> tuple[str, str] | None:
    """(Yahoo-style ticker, name) of the US line in one OpenFIGI answer."""
    for item in answer.get("data") or []:
        if item.get("exchCode") != "US" or item.get("marketSector") != "Equity":
            continue
        if item.get("securityType") not in _FIGI_TYPES:
            continue
        ticker = str(item.get("ticker") or "").upper().replace("/", "-")
        if ticker:
            return ticker, str(item.get("name") or "")[:80]
    return None


def figi_lookup(batch: list[str], post=None) -> list[tuple[str, str] | None]:
    """OpenFIGI's reading of each CUSIP: (ticker, name) or None."""
    post = post or _post
    key = _figi_key()
    headers = {"X-OPENFIGI-APIKEY": key} if key else None
    jobs = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
    answers = post(FIGI_URL, jobs, user_agent=_user_agent(), headers=headers)
    if not isinstance(answers, list) or len(answers) != len(batch):
        raise ValueError("OpenFIGI answered a different number of jobs")
    return [_ticker_of(a) if isinstance(a, dict) else None for a in answers]


def resolve(*, budget_s: float = 600.0, path: Path = DB, post=None,
            sleep=time.sleep) -> tuple[int, int]:
    """Map unresolved CUSIPs to tickers, most-held first, until the budget
    runs out. (resolved now, still open). A CUSIP OpenFIGI does not know is
    recorded as resolved with no ticker, so it is not asked again."""
    if not path.exists():
        return 0, 0
    keyed = _figi_key() is not None
    size = FIGI_BATCH_KEYED if keyed else FIGI_BATCH_KEYLESS
    pause = FIGI_PAUSE_KEYED if keyed else FIGI_PAUSE_KEYLESS
    deadline = time.monotonic() + budget_s
    done = 0
    db = sqlite3.connect(path)
    try:
        todo = [c for (c,) in db.execute(
            "SELECT cusip FROM cusip WHERE resolved = 0 ORDER BY total DESC")]
        for i in range(0, len(todo), size):
            if time.monotonic() + pause > deadline:
                break
            batch = todo[i:i + size]
            try:
                found = figi_lookup(batch, post)
            except Exception as exc:  # noqa: BLE001 — resume on the next run
                obs.warn("thirteenf.figi_failed", error_type=type(exc).__name__,
                         error=str(exc)[:200])
                break
            for cus, hit in zip(batch, found, strict=True):
                db.execute(
                    "UPDATE cusip SET ticker = ?, name = ?, resolved = 1 "
                    "WHERE cusip = ?", (hit[0] if hit else None,
                                        hit[1] if hit else None, cus))
            db.commit()
            done += len(batch)
            sleep(pause)
        left = db.execute("SELECT COUNT(*) FROM cusip WHERE resolved = 0").fetchone()[0]
    finally:
        db.close()
    if done and storage.enabled():
        with obs.swallow("thirteenf.persist"):
            storage.persist(path)
    return done, int(left)


# ------------------------------------------------------------- the reader

_restored = False


def _open(path: Path) -> sqlite3.Connection | None:
    global _restored
    if not path.exists() and not _restored and storage.enabled():
        _restored = True
        with obs.swallow("thirteenf.restore"):
            storage.restore(path)
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def holdings(ticker: str, *, path: Path = DB, limit: int = KEEP) -> Holdings | None:
    """`ticker`'s biggest 13F holders for the newest indexed quarter, or None
    — no index yet, a ticker the index does not know (non-US, crypto)."""
    db = _open(path)
    if db is None:
        return None
    try:
        row = db.execute(
            "SELECT cusip FROM cusip WHERE ticker = ? ORDER BY total DESC LIMIT 1",
            (ticker.upper(),)).fetchone()
        period = dict(db.execute("SELECT key, value FROM meta")).get("period")
        if row is None or not period:
            return None
        top = [
            Position(name, shares, value, prior)
            for name, shares, value, prior in db.execute(
                "SELECT m.name, h.shares, h.value, h.prev_shares FROM holding h "
                "JOIN manager m ON m.cik = h.cik WHERE h.cusip = ? "
                "ORDER BY h.rank LIMIT ?", (row[0], limit))
        ]
        sold = [
            Position(name, 0, value, prior)
            for name, prior, value in db.execute(
                "SELECT m.name, s.prev_shares, s.prev_value FROM sold s "
                "JOIN manager m ON m.cik = s.cik WHERE s.cusip = ? "
                "ORDER BY s.prev_shares DESC LIMIT ?", (row[0], limit))
        ]
    except sqlite3.Error:
        return None
    finally:
        with contextlib.suppress(Exception):
            db.close()
    if not top:
        return None
    return Holdings(as_of=date.fromisoformat(period), top=top, sold_out=sold)
