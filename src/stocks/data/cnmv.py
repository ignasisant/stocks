"""CNMV directors' dealings — Art. 19 MAR managers' transactions (Spain).

The Spanish half of what `bafin.py` does for Germany. The CNMV publishes every
notification of "operaciones de directivos y personas vinculadas" and, unlike
BaFin, offers no export: the register is a list page per issuer, and the
transaction itself lives in a PDF form behind each item.

How it is read (probed against the live site):

* The issuer is found by name: POSTing the search form's "Denominación social"
  answers with a 302 to `...Directivos-Resultado.aspx?nif=<NIF>` when exactly
  one company matches. The NIF is permanent, so it is memoised for good.
* `directivos-resultado?nif=<NIF>&page=N` is a plain GET, ten notifications a
  page, newest first. Each item links to `webservices/verdocumento/ver?e=...`,
  a PDF the standard MAR form is rendered into (ISIN, instrument, buy or sell,
  date, venue, volume, unit price, currency).
* The form's volume is a number of shares (BaFin's is money), so no derivation.

A page load must never fan out: list pages are cached for an hour, every
parsed PDF is memoised by its token (on disk and in the bucket, like Form 4),
and one request fetches at most `MAX_PDFS` PDFs it has not seen. Older items
fill in over later requests as the memo grows.

Coverage: Spanish issuers, notifications of the last twelve months. Rows are in
the form's own currency (EUR for Spanish shares), `source` is "CNMV".
"""

from __future__ import annotations

import gzip
import html
import io
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar

from stocks import atomic, obs
from stocks.config import DATA_DIR
from stocks.data import http
from stocks.data.insiders import (
    BUY_CODE,
    SELL_CODE,
    InsiderTx,
    _decode,
    _encode,
)

BASE = "https://www.cnmv.es"
FORM_URL = f"{BASE}/portal/Consultas/Directivos-Consulta"
LIST_URL = f"{BASE}/portal/consultas/directivos-resultado"
USER_AGENT = "Mozilla/5.0 (compatible; stocks-toolkit)"

LOOKBACK_DAYS = 365
MAX_PDFS = 30  # uncached PDFs fetched by one request
MAX_PAGES = 8  # list pages read by one request (ten notifications each)
PDF_WORKERS = 8
BUDGET_S = 15.0  # wall clock one request waits on the network (the PDFs are slow)
PAGE_TTL_S = 3600.0
PAGE_CACHE_MAX = 64

MEMO_FILE = DATA_DIR / "cnmv.json"
MEMO_PDF_MAX = 4000
_memo: dict | None = None
_lock = threading.Lock()
_pages: dict[tuple[str, int], tuple[float, list[dict]]] = {}

SPANISH_VENUES = (".MC",)
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_REG = re.compile(r"\b(20\d{8})\b")

TRANSACTION_CODES = {"compra": BUY_CODE, "venta": SELL_CODE}
OTHER_CODE = "O"

# Longest keyword first: "vicepresidente" must not read as "presidente".
ROLE_WORDS = (
    ("consejero delegado", "Chief Executive Officer"),
    ("chief executive", "Chief Executive Officer"),
    ("ceo", "Chief Executive Officer"),
    ("vicepresidente", "Vice-Chairman"),
    ("presidente", "Chairman"),
    ("director financiero", "Chief Financial Officer"),
    ("cfo", "Chief Financial Officer"),
    ("consejero", "Director"),
    ("administrador", "Director"),
)


def spanish_listing(ticker: str) -> bool:
    return ticker.upper().endswith(SPANISH_VENUES)


# --- memo (parsed PDFs by token, NIFs by name) ---------------------------------


def _memory() -> dict:
    """The on-disk memo, read once per process (bucket first on a fresh host)."""
    global _memo
    with _lock:
        if _memo is None:
            if not MEMO_FILE.exists():
                with obs.swallow("cnmv.restore"):
                    from stocks import storage

                    storage.restore(MEMO_FILE)
            try:
                loaded = json.loads(MEMO_FILE.read_text())
            except (OSError, ValueError):
                loaded = {}
            loaded = loaded if isinstance(loaded, dict) else {}
            loaded.setdefault("nif", {})
            loaded.setdefault("pdf", {})
            _memo = loaded
        return _memo


def clear_cache() -> None:
    """Forget every cache — for tests that point `MEMO_FILE` somewhere else."""
    global _memo
    with _lock:
        _memo = None
        _pages.clear()


def _persist() -> None:
    memo = _memory()
    with _lock:
        pdfs = memo["pdf"]
        while len(pdfs) > MEMO_PDF_MAX:
            pdfs.pop(next(iter(pdfs)))
        with obs.swallow("cnmv.remember"):
            MEMO_FILE.parent.mkdir(parents=True, exist_ok=True)
            atomic.write_json(MEMO_FILE, memo, separators=(",", ":"))
            from stocks import storage

            storage.persist(MEMO_FILE)


# --- pure parsers ----------------------------------------------------------------


def _number(raw: str | None) -> float | None:
    """Spanish number: "72101,00", "1.234,5" or "12.75" (a lone dot is decimal
    unless three digits follow it)."""
    if not raw:
        return None
    text = raw.strip().replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _day(raw: str | None) -> date | None:
    try:
        return datetime.strptime((raw or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_list(page_html: str) -> list[dict]:
    """The notifications on one list page: date, token, registration number.

    Newest first, as the register serves them. Items without a PDF link are
    skipped; the token is the `e=` query value, kept URL-encoded as served.
    """
    items = []
    for block in re.split(r'<li id="[^"]*elementoPrimerNivel"', page_html)[1:]:
        when = re.search(r'fecha-no-icon">\s*(\d{2}/\d{2}/\d{4})', block)
        link = re.search(r'href="[^"]*verdocumento/ver\?e=([^"]+)"', block)
        if not link:
            continue
        reg = re.search(r"mero de registro:\s*(\d+)", block)
        items.append(
            {
                "date": _day(when.group(1)) if when else None,
                "token": html.unescape(link.group(1)),
                "reg": reg.group(1) if reg else "",
            }
        )
    return items


def _role(raw: str, closely: bool) -> str:
    if closely:
        return "Closely associated"
    low = raw.lower()
    for word, english in ROLE_WORDS:
        if word in low:
            return english
    return raw.title() if raw else "Insider"


def _after(tokens: list[str], marker: str) -> str:
    for i, tok in enumerate(tokens):
        if marker in tok and i + 1 < len(tokens):
            return tokens[i + 1]
    return ""


_NOISE = re.compile(r"^(\d+ / \d+|Formulario|Standard form)$")


def _table_rows(tokens: list[str]) -> list[tuple]:
    """The transaction cells of a form as (isin, kind, op, date, ccy, volume,
    price) tuples.

    A table of one row reads across (eight cells in order). A table of several
    rows with the same shape reads down: pdfminer emits it column by column,
    the ISIN of every row first, then every instrument, and so on. Both are
    told apart by how many ISINs lead the block. A page break in the middle
    (page counter, running headers) is noise and is dropped.
    """
    rows: list[tuple] = []
    i = 0
    while i < len(tokens):
        if tokens[i] != "4.h)":
            i += 1
            continue
        j = i + 1
        body: list[str] = []
        while j < len(tokens) and not tokens[j].startswith(
            ("Total Agregado", "Código de", "Otra informaci", "5)")
        ):
            if not _NOISE.match(tokens[j]):
                body.append(tokens[j])
            j += 1
        n = 0
        while n < len(body) and _ISIN.match(body[n]):
            n += 1
        if n and len(body) >= 8 * n:
            cols = [body[k * n : (k + 1) * n] for k in range(8)]
            for isin, kind, op, when, _mic, vol, price, ccy in zip(*cols, strict=True):
                day, volume = _day(when), _number(vol)
                if day and volume:
                    price_n = _number(price)
                    rows.append((isin, kind, op, day, ccy.upper(), volume, price_n))
        i = j
    return rows


def parse_form(text: str, ticker: str = "") -> tuple[list[InsiderTx], str]:
    """One MAR form's text (pdfminer output) into transactions plus the
    registration number it amends ("" for an initial notification). Pure.

    Layout-independent: every transaction table ends in the same eight cells
    (ISIN, instrument, operation, date, venue, volume, price, currency), so a
    row is found by its date and read relative to it. Rows of one date, side
    and instrument split over several venues are merged into one, the price
    volume-weighted, the way BaFin reports an aggregate.
    """
    # pdfminer keeps the PDF's "fi" ligature glyph, which breaks every match.
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    tokens = [ln.strip() for ln in text.splitlines() if ln.strip()]
    insider = _after(tokens, "Nombre y apellidos") or "Unknown"
    closely = any(
        re.match(r"^\[\s*[√xX✓]\s*\]\s*Persona estrechamente", t) for t in tokens
    )
    title = _after(tokens, "Cargo - posici")
    if title.startswith(("b)", "3.", "Notif")):
        title = ""
    relationship = _role(title, closely)
    note = text[text.find("Otra informaci") :] if "Otra informaci" in text else ""
    amends = ""
    if any(t.lower().startswith("modif") for t in tokens[:80]) or "rectif" in note:
        reg = _REG.search(note)
        amends = reg.group(1) if reg else ""

    merged: dict[tuple, list[float]] = {}
    for _isin, kind, op, when, ccy, volume, price in _table_rows(tokens):
        key = (when, op.lower(), kind.lower(), ccy)
        acc = merged.setdefault(key, [0.0, 0.0, 0.0])  # shares, shares*price, priced
        acc[0] += volume
        if price:
            acc[1] += volume * price
            acc[2] += volume

    out: list[InsiderTx] = []
    for (when, op, kind, ccy), (shares, notional, priced) in merged.items():
        # Only shares are the signal; options, rights and bonds are "other".
        code = OTHER_CODE
        if kind.startswith("acci"):
            code = TRANSACTION_CODES.get(op, OTHER_CODE)
        out.append(
            InsiderTx(
                date=when,
                insider=insider,
                relationship=relationship,
                code=code,
                acquired=(code == BUY_CODE),
                shares=shares,
                price=notional / priced if priced else None,
                ticker=ticker.upper(),
                currency=ccy if ccy.isalpha() and len(ccy) == 3 else "EUR",
                source="CNMV",
            )
        )
    return out, amends


def pdf_text(data: bytes) -> str:
    from pdfminer.high_level import extract_text

    return extract_text(io.BytesIO(data))


# --- network ---------------------------------------------------------------------


def _get(url: str, timeout: float = 20) -> bytes:
    # The list pages are 250 KB of markup: ask for gzip, which the portal
    # answers, and unpack it ourselves (urllib does not).
    data = http.get_bytes(
        url,
        user_agent=USER_AGENT,
        timeout=timeout,
        headers={"Accept-Encoding": "gzip"},
    )
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def _name_key(name: str) -> str:
    """The search text for a company: legal-form suffixes dropped, since the
    register stores "BANCO SANTANDER, S.A." and a feed says "Banco Santander"."""
    text = re.sub(r"[,.]", " ", name)
    text = re.sub(
        r"\b(s\s?a\s?u?|s\s?l|se|plc|sociedad an[oó]nima|holdings?)\b\s*$",
        "",
        text.strip(),
        flags=re.I,
    )
    return re.sub(r"\s+", " ", text).strip()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_NoRedirect = _NoRedirectHandler()


def _resolve_nif(name: str) -> str | None:
    """The issuer's NIF from the search form, None when zero or several match."""
    key = _name_key(name)
    if len(key) < 3:
        return None
    memo = _memory()["nif"]
    if key.lower() in memo:
        return memo[key.lower()] or None
    jar = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=http._context()),
    )
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept-Encoding", "gzip")]
    raw = opener.open(FORM_URL, timeout=20).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    page = raw.decode("utf-8", "replace")

    def hidden(field: str) -> str:
        m = re.search(rf'name="{field}"[^>]*value="([^"]*)"', page)
        return html.unescape(m.group(1)) if m else ""

    form = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": hidden("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": hidden("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": hidden("__EVENTVALIDATION"),
        "ctl00$ContentPrincipal$txtNombre": key,
        "ctl00$ContentPrincipal$txtLEI": "",
        "ctl00$ContentPrincipal$txtDeclarante": "",
        "ctl00$ContentPrincipal$txtFechaD": "",
        "ctl00$ContentPrincipal$txtFechaH": "",
        "ctl00$ContentPrincipal$btnBuscar": "Buscar",
    }
    # The 302's Location carries the NIF; following it would download the
    # issuer's whole list page for nothing.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=http._context()),
        _NoRedirect,
    )
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept-Encoding", "gzip")]
    req = urllib.request.Request(
        FORM_URL, data=urllib.parse.urlencode(form).encode(), method="POST"
    )
    try:
        resp = opener.open(req, timeout=20)
        where = resp.geturl() if resp.status != 200 else ""
    except urllib.error.HTTPError as err:
        where = err.headers.get("Location", "") if err.code in (301, 302, 303) else ""
        if not where:
            raise
    found = re.search(r"[?&]nif=([^&#]+)", where)
    nif = urllib.parse.unquote(found.group(1)) if found else ""
    # A definitive answer (one match, or none/ambiguous) is remembered; only a
    # network failure, which raised above, is retried next time.
    with _lock:
        memo[key.lower()] = nif
    _persist()
    return nif or None


def _list_page(nif: str, page: int) -> list[dict]:
    hit = _pages.get((nif, page))
    if hit and time.time() - hit[0] < PAGE_TTL_S:
        return hit[1]
    url = f"{LIST_URL}?{urllib.parse.urlencode({'nif': nif, 'page': page})}"
    items = parse_list(_get(url).decode("utf-8", "replace"))
    with _lock:
        if len(_pages) >= PAGE_CACHE_MAX:
            _pages.pop(next(iter(_pages)))
        _pages[(nif, page)] = (time.time(), items)
    return items


def _read_pdf(item: dict) -> None:
    """Fetch and parse one PDF into the memo. A worker stores its own result, so
    one that finishes after the request stopped waiting still serves the next."""
    token = item["token"]
    try:
        data = _get(f"{BASE}/webservices/verdocumento/ver?e={token}", timeout=60)
        txs, amends = parse_form(pdf_text(data))
    except Exception as exc:  # noqa: BLE001 — one bad PDF must not cost the card
        obs.warn("cnmv.pdf_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return
    entry = {"reg": item["reg"], "amends": amends, "txs": [_encode(t) for t in txs]}
    pdfs = _memory()["pdf"]
    with _lock:
        pdfs.pop(token, None)
        pdfs[token] = entry


def insider_transactions(
    ticker: str = "", *, issuer: str | None = None, nif: str | None = None
) -> list[InsiderTx]:
    """Art. 19 MAR notifications for one Spanish issuer, newest first.

    Best-effort like BaFin's: an unknown or ambiguous name, a network failure
    or a portal redesign yields an empty list rather than raising. Bounded: at
    most `MAX_PAGES` list pages and `MAX_PDFS` unseen PDFs per call, inside
    `BUDGET_S`; whatever was read is memoised, so the next call goes further.
    """
    if not (issuer or nif):
        return []
    started = time.monotonic()
    try:
        nif = nif or _resolve_nif(issuer or "")
        if not nif:
            return []
        cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
        pdfs = _memory()["pdf"]
        items: list[dict] = []
        budget = MAX_PDFS
        for page in range(MAX_PAGES):
            if time.monotonic() - started > BUDGET_S:
                break
            batch = _list_page(nif, page)
            if not batch:
                break
            stop = False
            for item in batch:
                if item["date"] and item["date"] < cutoff:
                    stop = True
                    break
                if item["token"] not in pdfs:
                    if budget <= 0:
                        stop = True
                        break
                    budget -= 1
                items.append(item)
            if stop:
                break

        todo = [i for i in items if i["token"] not in pdfs]
        if todo:
            pool = ThreadPoolExecutor(PDF_WORKERS)
            futures = [pool.submit(_read_pdf, i) for i in todo]
            left = max(BUDGET_S - (time.monotonic() - started), 1.0)
            wait(futures, timeout=left)
            # Whatever is still running finishes into the memo on its own.
            pool.shutdown(wait=False, cancel_futures=True)
            _persist()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        obs.warn("cnmv.failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return []

    entries = [pdfs[i["token"]] for i in items if i["token"] in pdfs]
    # An amendment replaces the notification it corrects.
    replaced = {e["amends"] for e in entries if e.get("amends")}
    out = [
        t
        for e in entries
        if e.get("reg") not in replaced
        for t in (_decode(row) for row in e["txs"])
        if t.date is None or t.date >= cutoff
    ]
    out = [replace(t, ticker=ticker.upper()) for t in out]
    out.sort(key=lambda t: (t.date is not None, t.date or date.min), reverse=True)
    return out
