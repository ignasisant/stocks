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
from collections.abc import Callable

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
# Display only. The ledger keeps the ISIN it was given (stocks.identity
# .yahoo_symbol), so nothing here can move a position onto another symbol.

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

# The German regional floors. They quote nearly every European share under its
# German code, thinly, and that is where a code lands when its home exchange
# spells it differently: Revolut's MEQA is MEQA.F in Frankfurt and MRL.MC in
# Madrid, and no search for "MEQA" ever lists the Madrid line. An answer here
# is the very security, but the best the code could do rather than the
# issuer's own line, so `symbol_for_code` asks again for that one whenever its
# caller can tell which it is.
_FLOORS = frozenset({".F", ".SG", ".MU", ".DU", ".BE", ".HM", ".HA"})

# Words in a listing's name where the issuer's own name has ended: legal forms,
# share classes, the floors' padding ("Merlin Properties SOCIMI S.A. A",
# "GRIFOLS SA A EO 0,25"). Yahoo answers the floor's full name with the floors
# again, and "Merlin Properties" with MRL.MC first.
_LEGAL = frozenset(
    "A B N ON AG SE SA NV PLC SPA AB ASA OYJ AS KGAA SOCIMI INC CORP LTD ORD"
    " SHS REG SAB SCA".split()
)

# Home lines a floor answer's name search may offer for a price check: two
# covers the issuer's line and its other class, and each check is a download.
_HOME_TRIES = 2


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
# Codes whose floor answer has been asked for a home line this process, and
# got a verdict: the next statement trading them does not ask again.
_code_settled: set[str] = set()


def _suffix(symbol: str) -> str:
    return symbol[symbol.rfind(".") :] if "." in symbol else ""


def on_floor(symbol: str) -> bool:
    """Whether `symbol` is a German regional floor's line (MEQA.F, OZTA.SG)."""
    return _suffix((symbol or "").strip().upper()) in _FLOORS


def _issuer(name: str) -> str:
    """The issuer part of a listing's name ("Merlin Properties SOCIMI S.A. A"
    -> "Merlin Properties"), or "" when too little of it is left to search."""
    words = _clean(name.replace(",", " ").replace("/", " ")).split()
    end = next(
        (at for at, word in enumerate(words) if at and _norm(word) in _LEGAL),
        len(words),
    )
    base = " ".join(words[:end])
    return base if len(_norm(base)) >= _DEDUP_MIN else ""


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


def _symbol(row: dict) -> str:
    return str(row.get("symbol") or "").strip().upper()


def _home_by_isin(isin: str, venues: tuple[str, ...]) -> str | None:
    """The line Yahoo quotes `isin` under, if it trades on one of `venues`
    and is not a floor. An ISIN names the security, class included, so the
    line needs no price to prove it: ES0105025003 is MRL.MC."""
    found = symbol_for_isin(isin)
    if found and _suffix(found) in venues and not on_floor(found):
        return found
    return None


def _home_by_name(
    row: dict, venues: tuple[str, ...], vet: Callable[[str], bool | None]
) -> tuple[str | None, bool]:
    """The issuer's own line for a floor answer, by the floor line's name.

    A line counts when it trades on one of `venues` off the floors, its name
    starts with the issuer's, and `vet` says it closed where the statement's
    trades were filled — a name is not an identity: Grifols' class B shares
    are "Grifols" too, at two thirds of the price. Yahoo's ranking decides
    which `_HOME_TRIES` are vetted.

    Returns the line, or None, and whether that is a verdict: a vet that could
    not say, or a throttled search, leaves the question open.
    """
    sure = True
    tried: list[str] = []
    asked: set[str] = set()
    for field in ("longname", "shortname"):
        base = _issuer(str(row.get(field) or ""))
        stem = _norm(base)
        if not base or stem in asked or len(tried) >= _HOME_TRIES:
            continue
        asked.add(stem)
        for found in _quotes(base, 12):
            symbol = _symbol(found)
            name = _norm(str(found.get("longname") or found.get("shortname") or ""))
            if (
                found.get("quoteType") not in QUOTE_TYPES
                or symbol in tried
                or symbol == _symbol(row)
                or _suffix(symbol) not in venues
                or on_floor(symbol)
                or not name.startswith(stem)
            ):
                continue
            if len(tried) >= _HOME_TRIES:
                break
            tried.append(symbol)
            verdict = vet(symbol)
            if verdict:
                return symbol, True
            if verdict is None:
                sure = False
    return None, sure and time.monotonic() >= _blocked_until


def symbol_for_code(
    code: str,
    currency: str,
    *,
    isin: str = "",
    vet: Callable[[str], bool | None] | None = None,
) -> str | None:
    """The Yahoo line a bare broker code stands for, or None.

    `currency` is the trade's: it says which venues to look on (`_VENUES`).
    Of the rows whose symbol is the code plus one of those suffixes, the
    earliest venue wins, so "SIE" in EUR is SIE.DE (XETRA), not SIE.F. A USD
    code is its own listing and is only searched when Yahoo spells it
    differently (BRK.B -> BRK-B).

    An answer on a German regional floor (`_FLOORS`) is then asked for the
    issuer's home line, when the caller can tell which that is. `isin` is the
    statement's own for the code, and Yahoo's line for it is taken as it
    comes (`_home_by_isin`); without one, the floor line's name is searched,
    and a line found there counts only once `vet` — the caller's check of a
    symbol against the trades' fills — proves it (`_home_by_name`). Asked
    once per process, cached floor answer or not, so a map written before
    this existed is mended by the next import; the floor answer stays when
    neither finds better, since it is the security itself, thinly quoted.

    One to four searches per code, ever, and a few more for a floor answer:
    the answer is cached (see `CODE_CACHE`) under the code as the ledger holds
    it. Never raises.
    """
    key = (code or "").strip().upper()
    cur = (currency or "").strip().upper()
    wanted = _normalized(key, cur)
    venues = _VENUES.get(cur) or (("",) if cur == "USD" and wanted != key else ())
    if not venues or not _CODE_RE.match(wanted):
        return None
    hit = code_symbol(key)
    homing = bool(isin or vet) and key not in _code_settled
    if hit and not (homing and on_floor(hit)):
        return hit
    if not hit and key in _code_misses:
        return None

    home = _home_by_isin(isin, venues) if homing and is_isin(isin) else None
    sure = True
    symbol = home
    if home is None and hit and vet is None:
        symbol = hit  # the ISIN was the only way up, and it led nowhere
    elif home is None:
        rank = {f"{wanted}{suffix}": i for i, suffix in enumerate(venues)}

        def best(rows: list[dict]) -> dict | None:
            found = [
                row
                for row in rows
                if row.get("quoteType") in QUOTE_TYPES and _symbol(row) in rank
            ]
            return min(found, key=lambda row: rank[_symbol(row)]) if found else None

        # Short codes too (BP, 5): this is a lookup, not a keystroke to debounce.
        row = best(_quotes(wanted, 12, min_len=1))
        for suffix in _PROBES.get(cur, venues[:2]):
            if row:
                break
            if suffix:
                row = best(_quotes(f"{wanted}{suffix}", 6, min_len=1))
        if row is None and hit:
            row = {"symbol": hit}
        if row is not None and homing and vet is not None and on_floor(_symbol(row)):
            home, sure = _home_by_name(row, venues, vet)
        symbol = home or (_symbol(row) if row else None)
    if homing and sure and time.monotonic() >= _blocked_until:
        _code_settled.add(key)
    if not symbol:
        if time.monotonic() >= _blocked_until:
            _code_misses.add(key)
        return None
    if symbol != hit:
        with _code_lock:
            cache = _load_code_cache()
            cache[key] = symbol
            _save_code_cache(dict(cache))
    return symbol


# (code, currency) -> candidates, for the process only: a statement's preview
# and its commit ask the same thing seconds apart.
_listings_memo: dict[tuple[str, str], list[str]] = {}


def remember_code(code: str, symbol: str) -> None:
    """Map `code` to `symbol` for good, as a search answer would be.

    For the reader's own pick (the Import page's venue picker), which the
    caller has checked against the reader's fills first: no search here.
    """
    key = (code or "").strip().upper()
    with _code_lock:
        cache = _load_code_cache()
        cache[key] = (symbol or "").strip().upper()
        _save_code_cache(dict(cache))
    _code_misses.discard(key)
    _code_settled.add(key)


def on_venues(symbol: str, currency: str) -> bool:
    """Whether `symbol` is a line of `currency`'s venues: bare for dollars,
    one of its suffixes otherwise (MRL.MC is a euro line, MRL is not)."""
    sym = (symbol or "").strip().upper()
    cur = (currency or "").strip().upper()
    if not sym:
        return False
    if cur == "USD":
        return "." not in sym
    return _suffix(sym) in _VENUES.get(cur, ())


def lines_for(query: str, currency: str, limit: int = 6) -> list[tuple[str, str, str]]:
    """(symbol, name, exchange) of the lines `query` finds on `currency`'s
    venues, in Yahoo's order with the German floors last.

    What a reader is shown when the search could not place a code at all and
    they name its security themselves ("Merlin"): a dollar code's lines are
    the bare ones, any other's carry a suffix of its currency's venues.
    Candidates only — nothing is cached. Never raises.
    """
    cur = (currency or "").strip().upper()
    if cur != "USD" and cur not in _VENUES:
        return []
    found: list[tuple[str, str, str]] = []
    for row in _quotes(query, 12, min_len=1):
        symbol = _symbol(row)
        if (
            row.get("quoteType") not in QUOTE_TYPES
            or not on_venues(symbol, cur)
            or any(symbol == seen for seen, _, _ in found)
        ):
            continue
        name = _clean(str(row.get("longname") or row.get("shortname") or ""))
        found.append((symbol, name, str(row.get("exchDisp") or "")))
    found.sort(key=lambda line: on_floor(line[0]))
    return found[:limit]


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
