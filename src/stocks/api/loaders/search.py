"""Search tiers: the held names, SEC titles, the world list, coins, funds
and peers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from stocks.api.cache import ttl_cache
from stocks.api.loaders.keys import _LEDGER_TTL
from stocks.api.loaders.market import sector_scans
from stocks.config import DATA_DIR
from stocks.data.shared_memo import SharedMemo
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.positions import build

# The tiers themselves live in `stocks.search`; these are the cached lookups it
# is handed. Every one swallows its exceptions: search degrading to the tiers
# that answered is the app's behaviour, and a dead Yahoo must not 500 a
# keystroke.

_SEARCH_TTL = 86400.0
# Short and strict: the answers themselves live in WORLD_MEMO, and an empty
# list from a throttled Yahoo must not stand in for a minute longer than this.
_WORLD_TTL = 60.0


@ttl_cache(_LEDGER_TTL, max_entries=32)
def held(db: str, mtime: float) -> tuple[str, ...]:
    """Tickers with an open position, so imported activity is searchable.

    Quantities need no FX, so the replay runs with an identity converter and
    stays offline — this is on the path of every keystroke.
    """
    try:
        positions, _ = build(all_transactions(Path(db)), to_base=lambda a, c, d: a)
        return tuple(p.ticker for p in positions)
    except Exception:
        return ()  # an empty or inconsistent ledger must never break search


@ttl_cache(_SEARCH_TTL, max_entries=256)
def sec_title(ticker: str) -> str | None:
    """Company name for a held-but-unlisted ticker, from the SEC map."""
    from stocks.data.edgar import title_for

    try:
        return title_for(ticker)
    except Exception:
        return None


@ttl_cache(_SEARCH_TTL, max_entries=128)
def sec_matches(query: str) -> list[tuple[str, str]]:
    """SEC ticker-map search. In-memory, but memoised so typing doesn't rescan."""
    from stocks.data.edgar import search_companies

    try:
        return search_companies(query, limit=6)
    except Exception:
        return []


# What Yahoo lists for a query, shared by every account and kept across boots:
# a symbol, once listed, stays listed, and the same few hundred queries ("nvda",
# "asml") are what everybody types. A month an answer — new listings do appear.
# A few MB of JSON at the cap.
#
# The bucket must not become a log of what people type, so the key is a hash
# of the query, an empty answer (a typo, a name, whatever was in the field)
# is never kept, and an ISIN is never asked through it: an ISIN somebody types
# is one they hold, which is the fingerprint `isin_symbols.json` stays local
# to avoid.
WORLD_MEMO = SharedMemo(DATA_DIR / "symbol_search.json", ttl=30 * 86400.0, cap=5000)


def _world_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]


@ttl_cache(_WORLD_TTL, max_entries=128, stale_s=0.0)
def world_matches(query: str) -> list[tuple[str, str, str]]:
    """Worldwide symbol search (Yahoo) — the only search tier that is a network
    round-trip, so its answers live in `WORLD_MEMO` for every account; this
    process-wide memo in front is what makes a burst of keystrokes one call.

    Only a listing is kept: an empty list from a throttled host is "could not
    ask", and a real "nothing" is a typed string nobody else needs to read.
    """
    from stocks.data import funds, symbols
    from stocks.fuzzy import MIN_QUERY

    key = query.strip().upper()
    if len(key) < MIN_QUERY:
        return []
    shared = not symbols.is_isin(key)
    if shared and (hit := WORLD_MEMO.get(_world_key(key))) is not None:
        for symbol, _, _, quote_type in hit:
            funds.remember(symbol, quote_type)  # the row's label, as on a miss
        return [(s, n, x) for s, n, x, _ in hit]
    try:
        rows = symbols.search_rows(key, limit=6)
    except Exception:
        return []
    if shared and rows:
        WORLD_MEMO.put(_world_key(key), rows)
    return [(s, n, x) for s, n, x, _ in rows]


@ttl_cache(_SEARCH_TTL, max_entries=128)
def coin_matches(query: str) -> list[tuple[str, str]]:
    """Coin pairs for a query — a local table, cached only to skip the rescan."""
    from stocks.data.crypto import search_crypto

    try:
        return search_crypto(query)
    except Exception:
        return []


@ttl_cache(_SEARCH_TTL, max_entries=128)
def fund_matches(query: str) -> list[tuple[str, str]]:
    """Fund catalog matches — the tier that still answers while Yahoo throttles."""
    from stocks.data.funds import search_funds

    try:
        return search_funds(query)
    except Exception:
        return []


def related(ticker: str) -> tuple[str, ...]:
    """Rivals for Compare and the evidence pack: both `peer_groups`, rivals
    first, as one list."""
    rivals, watched = peer_groups(ticker)
    return (*rivals, *watched)


@ttl_cache(86400.0, max_entries=128)
def peer_groups(ticker: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(rivals, also watched) for the comps picker.

    Rivals are the sector screen's cohort in the same industry, double-checked
    (`analysis.sectors`). Also watched is Yahoo's "people also watch" list,
    which is what readers co-view: next to Adobe it had PayPal, Visa and
    Broadcom. Only the names filed under the subject's own industry are kept —
    a name whose industry cannot be told is dropped, never vouched for. A
    subject with no industry (a fund) keeps the list as Yahoo sent it.

    A day's ttl and empty on any failure: a suggestion nobody asked for must
    never be the thing that fails the page.
    """
    from stocks.analysis.sectors import industry_rivals
    from stocks.data.related import related_tickers

    try:
        yahoo = related_tickers(ticker)
    except Exception:
        yahoo = []
    try:
        scans = sector_scans()
    except Exception:
        scans = {}
    industry = _industry(ticker, scans)
    try:
        rivals = industry_rivals(scans, ticker) or (
            industry_rivals(scans, ticker, industry) if industry else []
        )
    except Exception:
        rivals = []
    # Another class of the same company (GOOG beside GOOGL) is no rival.
    own = sec_title(ticker)
    rivals = [r for r in rivals if not own or sec_title(r) != own]
    watched = [s for s in dict.fromkeys(yahoo) if s not in rivals]
    if industry and watched:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(len(watched), 4)) as pool:
            filed = list(pool.map(lambda s: _industry(s, scans), watched))
        watched = [s for s, i in zip(watched, filed, strict=True) if i == industry]
    return tuple(rivals), tuple(watched)


def _industry(ticker: str, scans: dict) -> str | None:
    """Yahoo's industry for `ticker`: the nightly scan, the profile memo, then
    `info` — None when none of them can say."""
    from stocks.data import profiles
    from stocks.data.fetch import info, resolve

    subject = ticker.upper()
    for scan in scans.values():
        for m in scan.metrics:
            if str(m.get("ticker", "")).upper() == subject and m.get("industry"):
                return str(m["industry"])
    stored = profiles.known(resolve(ticker)) or {}
    if stored.get("industry"):
        return stored["industry"]
    # A fund files under no industry. An equity without one is a memo written
    # before the field was kept, so `info` is asked (and fills it in).
    if stored.get("quoteType", "EQUITY") != "EQUITY":
        return None
    try:
        return info(ticker).get("industry") or None
    except Exception:
        return None
