"""OpenFIGI — an ISIN's listings, from Bloomberg's own identifier registry.

A broker statement prints an ISIN (or a bare code and, beside it, an ISIN) and
Yahoo's search is a fuzzy matcher over names: it answers an ISIN with whatever
venue it ranks first ("US7223041028" -> 9PDA.SG, a Stuttgart line). OpenFIGI's
`/v3/mapping` is exact: one ISIN, every line the security trades on, each as
(exchange code, ticker). From those the *home* line is not a ranking but a
fact — the ISIN's country prefix names the primary exchange (ES -> SM, FR ->
FP, NL -> NA ...) — and the lines a trade currency's venues offer are the ones
whose exchange maps to a Yahoo suffix.

Free and keyless at 25 requests a minute and 10 lookups a request; the optional
key (`OPENFIGI_API_KEY` or `[openfigi] api_key` in the secrets file) raises it
to 25 requests per 6 seconds and 100 lookups a request. A statement's ISINs go
in one request (`securities`), the answer is kept on disk — an ISIN's listings
barely move — and a failure of any kind is "no answer", never an exception:
every caller has a Yahoo path to fall back on.

Measured 2026-10-27 (keyless): an answer lists *every* venue (up to ~260 rows
for one ISIN, 1 MB for a batch), so only the rows whose exchange we can spell
the Yahoo way are kept.

Exchange codes verified against live Yahoo charts with real ISINs (see
`EXCHANGES`). Nordic share classes are deliberately absent: OpenFIGI spells
Volvo B "VOLVB" and Novo B "NOVOB" where Yahoo wants VOLV-B and NOVO-B, and
the class separator cannot be recovered from the ticker, so those ISINs stay
with Yahoo's search.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
from collections import deque
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from stocks import atomic, obs
from stocks.config import DATA_DIR
from stocks.data.http import post_json
from stocks.secrets_env import secret

URL = "https://api.openfigi.com/v3/mapping"
CACHE = DATA_DIR / "openfigi_isins.json"

TIMEOUT = 8.0
# Lookups per request and requests per minute, keyless and with a key. A few
# spare on the rate so a second process sharing the egress IP does not tip us.
BATCH = 10
BATCH_KEYED = 100
PER_MINUTE = 22
PER_MINUTE_KEYED = 200

# An ISIN's listings are near-static; a "no identifier found" is as often a
# brand-new instrument as a bad ISIN, so it is asked again sooner.
HIT_TTL_S = 90 * 86400.0
MISS_TTL_S = 24 * 3600.0
# After a 429 (or an outright failure) nothing is asked for this long.
THROTTLED_S = 60.0
FAILED_S = 300.0

# exchCode -> Yahoo suffix. Each row confirmed: the symbol built from the code
# and OpenFIGI's ticker returned the right security from Yahoo's chart API.
# The German floors are listed because Yahoo quotes them; `symbols._FLOORS`
# keeps them last.
EXCHANGES: dict[str, str] = {
    "SM": ".MC",  # Madrid            IBE -> IBE.MC, ITX -> ITX.MC
    "FP": ".PA",  # Paris             MC -> MC.PA, CW8 -> CW8.PA
    "NA": ".AS",  # Amsterdam         ASML -> ASML.AS
    "IM": ".MI",  # Milan             ENEL -> ENEL.MI, VWCE -> VWCE.MI
    "GY": ".DE",  # XETRA             SAP -> SAP.DE, VWCE -> VWCE.DE
    "GR": ".DE",  # German composite, same ticker; some ETFs list only this
    "LN": ".L",  # London             SHEL -> SHEL.L, BT/A -> BT-A.L
    "BB": ".BR",  # Brussels          ABI -> ABI.BR
    "PL": ".LS",  # Lisbon            EDP -> EDP.LS
    "AV": ".VI",  # Vienna            VOE -> VOE.VI
    "FH": ".HE",  # Helsinki          NOKIA -> NOKIA.HE
    "ID": ".IR",  # Dublin            RYA -> RYA.IR
    "NO": ".OL",  # Oslo              EQNR -> EQNR.OL
    "SW": ".SW",  # SIX Swiss         NESN -> NESN.SW
    "PW": ".WA",  # Warsaw            PKO -> PKO.WA
    "CT": ".TO",  # Toronto           SHOP -> SHOP.TO
    "AT": ".AX",  # ASX               BHP -> BHP.AX
    "JT": ".T",  # Tokyo              7203 -> 7203.T
    "HK": ".HK",  # Hong Kong         700 -> 0700.HK (padded)
    "US": "",  # US composite         AAPL -> AAPL, BRK/B -> BRK-B
    "UN": "",  # NYSE
    "UW": "",  # Nasdaq (Global Select)
    "UQ": "",  # Nasdaq (Global Market)
    "UA": "",  # NYSE American
    "UP": "",  # NYSE Arca
    "GF": ".F",  # Frankfurt floor    APC -> APC.F
    "GS": ".SG",  # Stuttgart floor
    "GM": ".MU",  # Munich floor
    "GD": ".DU",  # Dusseldorf floor
    "GH": ".HM",  # Hamburg floor
    "GI": ".HA",  # Hanover floor
}

# ISIN country -> the exchange that is its issuers' primary listing.
# Absent countries (LU, IE ETFs, KY, BM, ...) have no single home line: their
# ISIN says where the fund or the shell company is registered, not where it
# trades.
HOME: dict[str, tuple[str, ...]] = {
    "US": ("US", "UN", "UW", "UQ"),
    "ES": ("SM",),
    "FR": ("FP",),
    "NL": ("NA",),
    "IT": ("IM",),
    "DE": ("GY", "GR"),
    "GB": ("LN",),
    "BE": ("BB",),
    "PT": ("PL",),
    "AT": ("AV",),
    "FI": ("FH",),
    "IE": ("ID",),
    "NO": ("NO",),
    "CH": ("SW",),
    "PL": ("PW",),
    "CA": ("CT",),
    "AU": ("AT",),
    "JP": ("JT",),
}

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,9}$")
# Milan's EuroTLX lines of foreign shares: "1AAPL", "1MSFT". Not the issuer's.
_TLX = re.compile(r"^\d[A-Z]")


def api_key() -> str | None:
    return secret("OPENFIGI_API_KEY", "openfigi", "api_key") or None


@dataclass(frozen=True)
class Listing:
    exch: str
    ticker: str  # OpenFIGI's spelling
    symbol: str  # Yahoo's


@dataclass(frozen=True)
class Security:
    isin: str
    name: str
    kind: str  # OpenFIGI securityType2: "Common Stock", "Mutual Fund" (ETFs) ...
    figi: str  # composite FIGI
    listings: tuple[Listing, ...]


def yahoo_symbol(exch: str, ticker: str) -> str | None:
    """OpenFIGI's (exchange, ticker) as the symbol Yahoo quotes, or None for an
    exchange we cannot spell or a ticker Yahoo would not recognise."""
    suffix = EXCHANGES.get(exch)
    if suffix is None:
        return None
    # Share classes: "BRK/B" -> BRK-B, "BT/A" -> BT-A, and London's trailing
    # slash ("BP/") for a line with no class.
    base = ticker.strip().upper().rstrip("/").replace("/", "-").replace(" ", "-")
    if exch == "HK" and base.isdigit():
        base = base.zfill(4)
    if not _TICKER.match(base):
        return None
    if exch == "IM" and _TLX.match(base):
        return None
    return base + suffix


# ----------------------------------------------------------------- the cache

_lock = threading.Lock()  # memo + rate window
# ISINs a request is out for. A second caller wanting one waits for that answer
# (`_landed`) rather than asking again: the importer's per-code lookups run in
# parallel and would otherwise each spend a request of the minute's allowance.
_inflight: set[str] = set()
_landed = threading.Condition(_lock)
# Batches of one statement asked at once; the rate window bounds the total.
WORKERS = 4
_memo: dict[str, dict] | None = None
_sent: deque[float] = deque()
_blocked_until = 0.0


def _load() -> dict[str, dict]:
    global _memo
    if _memo is None:
        memo: dict[str, dict] = {}
        try:
            data = json.loads(CACHE.read_text())
            if isinstance(data, dict):
                memo = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass
        _memo = memo
    return _memo


_save_lock = threading.Lock()


def _save() -> None:
    """Write the memo as it is *now*, one writer at a time: batches landing
    together must not overwrite each other with older snapshots."""
    with _save_lock:
        with _lock:
            snapshot = dict(_load())
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            atomic.write_json(CACHE, snapshot, sort_keys=True, separators=(",", ":"))
        except OSError:
            pass  # a read-only data dir costs a request per boot, not an import


def clear() -> None:
    """Forget the memo, the rate window and any cooldown (tests, ops)."""
    global _memo, _blocked_until
    with _lock:
        _memo = None
        _sent.clear()
        _inflight.clear()
        _blocked_until = 0.0


def _fresh(entry: dict | None, now: float) -> bool:
    if not entry:
        return False
    ttl = MISS_TTL_S if entry.get("miss") else HIT_TTL_S
    return now - float(entry.get("at", 0)) < ttl


def _security(isin: str, entry: dict) -> Security | None:
    if entry.get("miss"):
        return None
    listings = tuple(
        Listing(str(e), str(t), sym)
        for e, t in entry.get("listings", [])
        if (sym := yahoo_symbol(str(e), str(t)))
    )
    return Security(
        isin,
        str(entry.get("name", "")),
        str(entry.get("kind", "")),
        str(entry.get("figi", "")),
        listings,
    )


def _entry(rows: list[dict], now: float) -> dict:
    """The slim cache form of one answer: identity plus the lines we can use."""
    first = rows[0]
    seen: set[tuple[str, str]] = set()
    keep: list[list[str]] = []
    for row in rows:
        key = (str(row.get("exchCode", "")), str(row.get("ticker", "")))
        if key in seen or yahoo_symbol(*key) is None:
            continue
        seen.add(key)
        keep.append(list(key))
    return {
        "at": now,
        "name": str(first.get("name", "")),
        "kind": str(first.get("securityType2") or first.get("securityType") or ""),
        "figi": str(first.get("compositeFIGI") or ""),
        "listings": keep,
    }


# ------------------------------------------------------------------- asking


def _allowance(now: float, keyed: bool) -> bool:
    """Whether another request fits the rate window; counts it when it does."""
    per_minute = PER_MINUTE_KEYED if keyed else PER_MINUTE
    with _lock:
        while _sent and now - _sent[0] > 60.0:
            _sent.popleft()
        if len(_sent) >= per_minute:
            return False
        _sent.append(now)
        return True


def _post(jobs: list[dict], key: str | None) -> list:
    """One mapping request; the decoded list. Raises on any failure."""
    headers = {"X-OPENFIGI-APIKEY": key} if key else None
    answer, _ = post_json(URL, jobs, timeout=TIMEOUT, headers=headers)
    if not isinstance(answer, list) or len(answer) != len(jobs):
        raise ValueError("unexpected OpenFIGI answer")
    return answer


def _ask(isins: list[str]) -> None:
    """Request `isins` (already deduplicated, within one batch) into the memo."""
    global _blocked_until
    key = api_key()
    now = time.monotonic()
    if now < _blocked_until or not _allowance(now, key is not None):
        return
    jobs = [{"idType": "ID_ISIN", "idValue": isin} for isin in isins]
    try:
        answer = _post(jobs, key)
    except urllib.error.HTTPError as exc:
        wait = THROTTLED_S if exc.code == 429 else FAILED_S
        _blocked_until = time.monotonic() + wait
        obs.warn("openfigi.refused", status=exc.code, n=len(isins))
        return
    except Exception as exc:
        _blocked_until = time.monotonic() + FAILED_S
        obs.warn("openfigi.failed", error_type=type(exc).__name__, n=len(isins))
        return
    stamp = time.time()
    found = 0
    with _lock:
        memo = _load()
        for isin, result in zip(isins, answer, strict=True):
            data = result.get("data") if isinstance(result, dict) else None
            if data and isinstance(data, list):
                memo[isin] = _entry([r for r in data if isinstance(r, dict)], stamp)
                found += 1
            elif isinstance(result, dict) and "warning" in result:
                memo[isin] = {"at": stamp, "miss": True}
            # An "error" (a malformed ISIN) or an empty shape is not a verdict
            # on the security: nothing is kept, so a later ask may try again.
    _save()
    obs.event("openfigi.mapped", asked=len(isins), found=found)


def securities(isins: Iterable[str]) -> dict[str, Security | None]:
    """What OpenFIGI says of each ISIN: the security, or None for no answer.

    Cached answers are served without a request; the rest go out in batches,
    a few at a time (an answer takes seconds, and a statement has many ISINs).
    An ISIN another caller already has a request out for is waited on, not
    asked again. None covers a confirmed miss and a call that could not be made
    (throttled, offline, over the minute's allowance) alike: the caller falls
    back to Yahoo either way. Never raises.
    """
    wanted = list(
        dict.fromkeys(k for i in isins if _ISIN.match(k := (i or "").strip().upper()))
    )
    out: dict[str, Security | None] = {}
    mine: list[str] = []
    try:
        with _lock:
            memo = _load()
            now = time.time()
            for isin in wanted:
                if not _fresh(memo.get(isin), now) and isin not in _inflight:
                    mine.append(isin)
            _inflight.update(mine)
        try:
            size = BATCH_KEYED if api_key() else BATCH
            chunks = [mine[at : at + size] for at in range(0, len(mine), size)]
            if len(chunks) > 1:
                with ThreadPoolExecutor(max_workers=min(WORKERS, len(chunks))) as pool:
                    list(pool.map(_ask, chunks))
            elif chunks:
                _ask(chunks[0])
        finally:
            with _landed:
                _inflight.difference_update(mine)
                _landed.notify_all()
        with _landed:  # ISINs another caller was asking for: wait for it
            _landed.wait_for(
                lambda: not _inflight.intersection(wanted), timeout=TIMEOUT + 2
            )
            memo = _load()
            now = time.time()
            for isin in wanted:
                entry = memo.get(isin)
                if _fresh(entry, now):
                    out[isin] = _security(isin, entry or {})
    except Exception as exc:  # the contract: never into an import
        obs.warn("openfigi.error", error_type=type(exc).__name__)
    return {isin: out.get(isin) for isin in wanted}


def security(isin: str) -> Security | None:
    return securities([isin]).get((isin or "").strip().upper())


# ------------------------------------------------------------------ choosing


def _rank(sec: Security, exchanges: tuple[str, ...]) -> list[Listing]:
    order = {e: i for i, e in enumerate(exchanges)}
    return sorted(
        (item for item in sec.listings if item.exch in order),
        key=lambda item: order[item.exch],
    )


def home(isin: str) -> str | None:
    """The Yahoo symbol of the ISIN's primary listing, or None.

    Only where the country prefix names one (`HOME`); an ETF's or a shell
    company's ISIN does not, and is left to `candidates` and Yahoo.
    """
    key = (isin or "").strip().upper()
    exchanges = HOME.get(key[:2])
    sec = securities([key]).get(key) if exchanges else None
    if not sec or not exchanges:
        return None
    found = _rank(sec, exchanges)
    return found[0].symbol if found else None


def candidates(isin: str, venues: tuple[str, ...]) -> list[str]:
    """Lines of the ISIN on `venues` (Yahoo suffixes, "" for bare US), best
    first: the primary listing, then each venue in the order given.

    The German floors are left out here — `symbols.on_floor` lines are what a
    caller asks home lines to improve on. A US composite line counts for a
    bare venue only on a US ISIN: for any other it is an OTC line.
    """
    key = (isin or "").strip().upper()
    sec = securities([key]).get(key)
    if not sec:
        return []
    primary = home(key)
    out: list[str] = [primary] if primary and _suffix_in(primary, venues) else []
    for suffix in venues:
        for item in sec.listings:
            if EXCHANGES.get(item.exch) != suffix or item.symbol in out:
                continue
            if item.exch in ("GF", "GS", "GM", "GD", "GH", "GI"):
                continue
            if item.exch == "US" and not key.startswith("US"):
                continue
            out.append(item.symbol)
    return out


def _suffix_in(symbol: str, venues: tuple[str, ...]) -> bool:
    dot = symbol.rfind(".")
    return (symbol[dot:] if dot >= 0 else "") in venues
