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
"US81762P1021" into the "NOW" every screen prints.

Same failure contract as the other network-backed sources: any error means an
empty list, never an exception into the render path.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse

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


def _quotes(query: str, count: int) -> list[dict]:
    """Yahoo's raw quote rows for `query`, every venue it lists, in its own
    ranking. Empty for a too-short query and for COOLDOWN seconds after a
    failure: once Yahoo starts rejecting this host, retrying only deepens the
    block. Never raises — see the module docstring's failure contract.
    """
    global _blocked_until
    q = query.strip()
    if len(q) < MIN_QUERY or time.monotonic() < _blocked_until:
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
    out: list[tuple[str, str, str]] = []
    seen: list[str] = []
    for row in _quotes(query, max(limit * 3, 12)):
        symbol = str(row.get("symbol") or "").strip()
        if not symbol or row.get("quoteType") not in QUOTE_TYPES:
            continue
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
        ISIN_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))
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
