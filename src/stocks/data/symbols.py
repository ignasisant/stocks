"""Worldwide symbol search — Yahoo's own lookup, behind the ticker pickers.

The local search tiers only know part of the universe: the watchlist, the coin
table, and the SEC ticker map (US filers only). A foreign listing therefore
matched nothing — typing "mips" or "hermes" fell straight through to the raw
"Analyze <SYMBOL>" button, which then handed yfinance a symbol Yahoo does not
quote (bare MIPS is a dead stub; the real line is MIPS.ST). This tier asks
Yahoo's search endpoint, which is name-aware, typo-tolerant and covers every
venue it quotes, so the picker offers a symbol that actually resolves.

The same endpoint answers an ISIN with the line Yahoo quotes it under, so
`symbol_for_isin` sits here too: it is what turns a DEGIRO row stored as
"US81762P1021" into the "NOW" every screen prints — and `symbol_for_code`,
which turns the bare "SIE" a Revolut statement prints into the SIE.DE Yahoo
quotes.

Same failure contract as the other network-backed sources: any error means an
empty list, never an exception into the render path.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse

from stocks import atomic
from stocks.config import DATA_DIR
from stocks.data.http import get_json
from stocks.fuzzy import MIN_QUERY

SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"

# Tradable instruments only — Yahoo also returns mutual funds, futures and
# currencies for a plain word query, none of which the app can chart.
QUOTE_TYPES = {"EQUITY", "ETF"}

# This runs per keystroke behind a cache, so it must fail FAST and then stay
# quiet: Yahoo throttles datacenter egress IPs, and a search field
# that blocks for 30s on every letter is worse than one that finds nothing.
TIMEOUT = 6.0
COOLDOWN = 300.0

# Shortest normalized name that may swallow a longer one as a duplicate. Below
# this, a shared prefix is coincidence ("MP" vs "MPLX"), not the same issuer.
_DEDUP_MIN = 5

_blocked_until = 0.0


def _clean(name: str) -> str:
    """Collapse Yahoo's column-padded names ("Mips AB           N")."""
    return " ".join(name.split())


def _norm(name: str) -> str:
    """Alphanumeric-only uppercase form, for cross-venue issuer matching."""
    return "".join(c for c in name.upper() if c.isalnum())


def _is_dup(keys: set[str], seen: list[str]) -> bool:
    """Whether these names belong to an issuer already listed.

    Yahoo returns every venue it quotes, and each one spells the issuer its own
    way — Mips AB comes back as "Mips AB" (Stockholm), "Mips AB N" (Frankfurt),
    "MIPS AB O.N." (Stuttgart) and "MIPS AB MIPS ORD SHS" (London). Exact-name
    dedup keeps all four and burns the whole dropdown on one company, so both
    of a row's names (short and long) are matched against both of every kept
    row's, and a prefix relation counts as the same issuer. Yahoo's first row
    wins — its ranking puts the primary listing on top, which is the line with
    the deepest history and the native currency.

    The `_DEDUP_MIN` floor keeps a coincidental short prefix from swallowing an
    unrelated company ("ASML" must not absorb "ASML Group").
    """
    for norm in keys:
        for other in seen:
            short, long = sorted((norm, other), key=len)
            if len(short) >= _DEDUP_MIN and long.startswith(short):
                return True
    return False


def _quotes(query: str, count: int, min_len: int = MIN_QUERY) -> list[dict]:
    """Yahoo's raw quote rows for `query`, every venue it lists, in its own
    ranking. Empty for a query shorter than `min_len` and for COOLDOWN seconds
    after a failure: once Yahoo starts rejecting this host, retrying only
    deepens the block. Never raises — see the module docstring's failure
    contract.
    """
    global _blocked_until
    q = query.strip()
    if len(q) < min_len or time.monotonic() < _blocked_until:
        return []
    url = (
        f"{SEARCH_URL}?q={urllib.parse.quote(q)}"
        f"&quotesCount={count}&newsCount=0"
        "&enableFuzzyQuery=true&enableNavLinks=false"
    )
    try:
        payload = get_json(url, timeout=TIMEOUT)
    except Exception:
        _blocked_until = time.monotonic() + COOLDOWN
        return []
    rows = payload.get("quotes", [])
    return [r for r in rows if isinstance(r, dict)]


def search_symbols(query: str, limit: int = 6) -> list[tuple[str, str, str]]:
    """(symbol, name, exchange) matches for `query`, best first.

    Fuzzy by construction — Yahoo's own matcher takes "sandisc" to SNDK and
    "nvidai" to NVDA — so callers get typo tolerance over the whole quotable
    universe, not just the local tables. One row per issuer (see `_is_dup`).

    Empty for a query shorter than MIN_QUERY, and empty for COOLDOWN seconds
    after a failure: once Yahoo starts rejecting this host, retrying on every
    keystroke only deepens the throttle.
    """
    from stocks.data import funds

    out: list[tuple[str, str, str]] = []
    seen: list[str] = []
    for row in _quotes(query, max(limit * 3, 12)):
        symbol = str(row.get("symbol") or "").strip()
        if not symbol or row.get("quoteType") not in QUOTE_TYPES:
            continue
        # The quoteType came free with the match; keeping it is what lets the
        # search box label the row (asset_kind.cached) without a lookup.
        funds.remember(symbol, row.get("quoteType"))
        # longname first: it is the full legal name, spelled the same on every
        # venue ("Mips AB (publ)"), while shortname is a 30-char truncation of
        # whatever the local exchange prints ("ASML Holding N.V. - New York Re").
        short = _clean(str(row.get("shortname") or ""))
        long = _clean(str(row.get("longname") or ""))
        name = long or short or symbol
        keys = {k for k in (_norm(long), _norm(short)) if k} or {_norm(symbol)}
        if _is_dup(keys, seen):
            continue
        seen.extend(keys)
        out.append((symbol, name, str(row.get("exchDisp") or "")))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ ISINs
#
# Brokers that print no symbol (DEGIRO, and Saxo for a venue we can't map)
# import under the ISIN, which is the ledger's audit trail but unreadable on
# screen: "US81762P1021" tells nobody it is ServiceNow. watchlist.yaml
# `aliases` is the hand-written answer; this is the automatic one — Yahoo's
# own search resolves an ISIN to the line it quotes, so a freshly imported
# DEGIRO statement reads as NOW and META before anyone edits a mapping file.
#
# Display only. The ledger keeps the ISIN it was given (stocks.web.logos
# .display_symbol), so nothing here can move a position onto another symbol.

ISIN_CACHE = DATA_DIR / "isin_symbols.json"

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# isin -> symbol, mirrored to disk: an ISIN's listing is a fact that doesn't
# move, and the map is public reference data, never anything about an account.
# Misses stay in memory only — a "no match" is as often a throttled host as a
# security Yahoo really doesn't quote, and the next boot should ask again.
_isin_memo: dict[str, str] | None = None
_isin_misses: set[str] = set()


def is_isin(text: str) -> bool:
    """Whether `text` is ISIN-shaped (2-letter country + 9 + check digit)."""
    return bool(_ISIN_RE.match((text or "").strip().upper()))


def _load_isin_cache() -> dict[str, str]:
    global _isin_memo
    if _isin_memo is None:
        _isin_memo = {}
        try:
            data = json.loads(ISIN_CACHE.read_text())
            if isinstance(data, dict):
                _isin_memo = {
                    str(k).upper(): str(v)
                    for k, v in data.items()
                    if isinstance(v, str) and v
                }
        except (OSError, ValueError):
            pass
    return _isin_memo


def _save_isin_cache(cache: dict[str, str]) -> None:
    try:
        ISIN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(ISIN_CACHE, cache, indent=2, sort_keys=True)
    except OSError:
        pass  # a read-only data dir costs a lookup per boot, not a render


def symbol_for_isin(isin: str) -> str | None:
    """Yahoo symbol for an ISIN, or None when nothing resolves it.

    One search per ISIN, ever: the answer is cached to disk and the misses
    for the process. A US ISIN prefers the bare US listing when Yahoo offers
    several — the security's home line is the one whose price history the
    rest of the app can read (Yahoo answers a foreign ISIN with its local
    venue, "NL0010273215" -> "ASML.AS", which is equally right).

    Never raises: search_symbols already turns a throttled Yahoo into an
    empty list, and every caller here is a label being drawn on screen.
    """
    key = (isin or "").strip().upper()
    if not is_isin(key):
        return None
    cache = _load_isin_cache()
    if hit := cache.get(key):
        return hit
    if key in _isin_misses:
        return None

    # The raw rows, not `search_symbols`: that one collapses an issuer's
    # venues into its best-ranked line, and the line worth having here is
    # sometimes further down the list.
    found = [
        str(row.get("symbol") or "").strip()
        for row in _quotes(key, 12)
        if row.get("quoteType") in QUOTE_TYPES and row.get("symbol")
    ]
    if not found:
        _isin_misses.add(key)
        return None
    symbol = found[0]
    if key.startswith("US"):
        # A US security's ISIN is regularly answered with a European line
        # first ("US7223041028" -> "9PDA.SG", Stuttgart). The home listing is
        # the one with the deep history, and it takes no Yahoo suffix.
        symbol = next((s for s in found if "." not in s), symbol)
    cache[key] = symbol
    _save_isin_cache(cache)
    return symbol


# ------------------------------------------------------------ broker codes
#
# Revolut prints a European stock under its bare German code — SIE, BSD2, BOY
# (BBVA), OZTA (Grifols) — which Yahoo quotes only with a venue suffix
# (SIE.DE, OZTA.F). watchlist.yaml `aliases` is the hand-written answer and
# still wins; this is the automatic one, so a statement full of them imports
# priced instead of warned. The trade's currency picks the venues: a code
# bought in EUR is looked for on the German exchanges first, because that is
# the code family Revolut uses, then on the other euro venues Yahoo ranks.
#
# Asked only for a code Yahoo has just said it does not quote bare
# (stocks.api.routes.import_statement._Lookup), and only a row whose symbol is
# the code plus a suffix counts: "SIE" never lands on Siemens Energy (ENR.DE),
# which the same search ranks first.
#
# Unlike the ISIN map this one feeds the price download (fetch.resolve), and
# the price path has no currency to search with, so the map is mirrored to the
# bucket: a container that boots without it would hold every such position at
# cost until the next import.

CODE_CACHE = DATA_DIR / "code_symbols.json"

# Yahoo suffixes per trade currency, best first. EUR puts XETRA first because
# Revolut's euro codes are German ones, then each market's home exchange, and
# the German regional floors last: those quote nearly everything, thinly, so
# Philips found on both is PHIA.AS, not PHIA.F.
_VENUES = {
    "EUR": (".DE", ".PA", ".AS", ".MI", ".MC", ".BR", ".LS", ".VI", ".HE",
            ".IR", ".AT", ".F", ".SG", ".MU", ".DU", ".BE", ".HM", ".HA"),
    "GBP": (".L", ".IL"),
    "GBX": (".L", ".IL"),  # London prices in pence; some brokers say so
    "CHF": (".SW",),
    "SEK": (".ST",),
    "DKK": (".CO",),
    "NOK": (".OL",),
    "PLN": (".WA",),
    "CZK": (".PR",),
    "HUF": (".BD",),
    "TRY": (".IS",),
    "ILS": (".TA",),
    "CAD": (".TO", ".V", ".NE", ".CN"),
    "AUD": (".AX",),
    "NZD": (".NZ",),
    "HKD": (".HK",),
    "JPY": (".T",),
    "CNY": (".SS", ".SZ"),
    "TWD": (".TW", ".TWO"),
    "KRW": (".KS", ".KQ"),
    "SGD": (".SI",),
    "INR": (".NS", ".BO"),
    "IDR": (".JK",),
    "THB": (".BK",),
    "MYR": (".KL",),
    "BRL": (".SA",),
    "MXN": (".MX",),
    "ZAR": (".JO",),
}

# The venues also asked by name when the bare search misses: Yahoo's matcher
# ranks "BOY" to Boyd Gaming and La-Z-Boy and never lists BOY.DE, but answers
# "BOY.DE" exactly. Every other currency asks its first two.
_PROBES = {"EUR": (".DE", ".PA", ".F")}

# After `_normalized`: a code, optionally with a share class (VOLV-B, BT-A).
_CODE_RE = re.compile(r"^[A-Z0-9]{1,10}(-[A-Z0-9]{1,3})?$")


def _normalized(code: str, currency: str) -> str:
    """The code as Yahoo spells it: a share class after a hyphen (BT.A,
    "VOLV B" -> BT-A, VOLV-B), and a Hong Kong number as four digits
    (700 -> 0700), the form Yahoo lists it under."""
    key = re.sub(r"[.\s/]+", "-", code.strip().upper())
    if currency == "HKD" and key.isdigit():
        key = str(int(key)).zfill(4)
    return key


# code -> symbol, like the ISIN map: hits on disk (and in the bucket), misses
# for the process only, and a miss while the search is cooling down is not
# one — that was the host being throttled, not the code being unknown.
_code_memo: dict[str, str] | None = None
_code_misses: set[str] = set()
_code_lock = threading.Lock()


def _load_code_cache() -> dict[str, str]:
    global _code_memo
    if _code_memo is None:
        from stocks import obs, storage

        if storage.enabled():
            with obs.swallow("symbols.code_restore"):
                storage.restore(CODE_CACHE)
        memo: dict[str, str] = {}
        try:
            data = json.loads(CODE_CACHE.read_text())
            if isinstance(data, dict):
                memo = {
                    str(k).upper(): str(v)
                    for k, v in data.items()
                    if isinstance(v, str) and v
                }
        except (OSError, ValueError):
            pass
        _code_memo = memo
    return _code_memo


def _save_code_cache(cache: dict[str, str]) -> None:
    from stocks import obs, storage

    try:
        CODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(CODE_CACHE, cache, indent=2, sort_keys=True)
    except OSError:
        return  # a read-only data dir costs a search per boot, not an import
    if storage.enabled():
        with obs.swallow("symbols.code_persist"):
            storage.persist(CODE_CACHE)


def code_symbol(code: str) -> str | None:
    """The Yahoo line a broker code was resolved to, from the map only.

    No network, ever: this sits in `fetch.resolve`, under every price lookup.
    """
    return _load_code_cache().get((code or "").strip().upper())


def resolved_codes() -> dict[str, str]:
    """Every broker code the search has resolved so far, code -> symbol."""
    return dict(_load_code_cache())


def symbol_for_code(code: str, currency: str) -> str | None:
    """The Yahoo line a bare broker code stands for, or None.

    `currency` is the trade's: it says which venues to look on (`_VENUES`).
    Of the rows whose symbol is the code plus one of those suffixes, the
    earliest venue wins, so "SIE" in EUR is SIE.DE (XETRA), not SIE.F. A USD
    code is its own listing and is only searched when Yahoo spells it
    differently (BRK.B -> BRK-B).

    One to four searches per code, ever: the answer is cached (see
    `CODE_CACHE`) under the code as the ledger holds it. Never raises.
    """
    key = (code or "").strip().upper()
    cur = (currency or "").strip().upper()
    wanted = _normalized(key, cur)
    venues = _VENUES.get(cur) or (("",) if cur == "USD" and wanted != key else ())
    if not venues or not _CODE_RE.match(wanted):
        return None
    if hit := code_symbol(key):
        return hit
    if key in _code_misses:
        return None

    rank = {f"{wanted}{suffix}": i for i, suffix in enumerate(venues)}

    def best(rows: list[dict]) -> str | None:
        found = [
            symbol
            for row in rows
            if row.get("quoteType") in QUOTE_TYPES
            and (symbol := str(row.get("symbol") or "").strip().upper()) in rank
        ]
        return min(found, key=rank.__getitem__) if found else None

    # Short codes too (BP, 5): this is a lookup, not a keystroke to debounce.
    symbol = best(_quotes(wanted, 12, min_len=1))
    for suffix in _PROBES.get(cur, venues[:2]):
        if symbol:
            break
        if suffix:
            symbol = best(_quotes(f"{wanted}{suffix}", 6, min_len=1))
    if not symbol:
        if time.monotonic() >= _blocked_until:
            _code_misses.add(key)
        return None
    with _code_lock:
        cache = _load_code_cache()
        cache[key] = symbol
        _save_code_cache(dict(cache))
    return symbol


# (code, currency) -> candidates, for the process only: a statement's preview
# and its commit ask the same thing seconds apart.
_listings_memo: dict[tuple[str, str], list[str]] = {}


def venue_symbols(code: str, currency: str) -> list[str]:
    """The code on each of `currency`'s venues, best first (ALV, EUR ->
    ALV.DE, ALV.PA, …). Names only, no network; [] for a currency without
    venues and for a code that is not one."""
    cur = (currency or "").strip().upper()
    wanted = _normalized((code or "").strip().upper(), cur)
    if not _CODE_RE.match(wanted):
        return []
    return [f"{wanted}{suffix}" for suffix in _VENUES.get(cur, ())]


def listings_for_code(code: str, currency: str, limit: int = 6) -> list[str]:
    """The lines a code could be on in its trade currency, most likely first.

    For a code Yahoo DOES quote bare, but in dollars: Revolut's euro "ALV" is
    Allianz (ALV.DE), not the Autoliv that bare "ALV" is. Unlike
    `symbol_for_code` nothing here is an answer — the caller picks one by
    price — so nothing is written to `CODE_CACHE`, whose single global answer
    per code is the price download's: the dollar rows still mean Autoliv.

    The search's own hits on `currency`'s venues come first, by venue, then
    the venues it did not list, by name and unasked: Yahoo's matcher ranks
    "SAN" to Sanofi (SAN.PA) and never shows Santander's SAN.MC. Never
    raises; [] for a currency without venues.
    """
    key = (code or "").strip().upper()
    cur = (currency or "").strip().upper()
    names = venue_symbols(key, cur)
    if not names:
        return []
    if (key, cur) in _listings_memo:
        return list(_listings_memo[(key, cur)])
    wanted = _normalized(key, cur)
    rank = {symbol: i for i, symbol in enumerate(names)}
    hits = sorted(
        {
            symbol
            for row in _quotes(wanted, 12, min_len=1)
            if row.get("quoteType") in QUOTE_TYPES
            and (symbol := str(row.get("symbol") or "").strip().upper()) in rank
        },
        key=rank.__getitem__,
    )
    rest = [s for s in rank if s not in hits]
    found = (hits + rest)[: max(limit, len(hits))]
    if time.monotonic() >= _blocked_until:
        _listings_memo[(key, cur)] = found
    return list(found)
