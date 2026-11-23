"""On-disk memo of the facts in a Yahoo `.info` blob that never change.

`.info` is a full quoteSummary — the heaviest request yfinance makes, two
round-trips per ticker — and the allocation splits (sector / country /
currency donuts on the Pulse and Portfolio pages) asked for one per holding on
every cold process, to read four fields that are as fixed as the company's
address. A 38-name book cost 76 requests to learn what it learnt last time.

This is the same shape as `stocks.data.funds`' quoteType cache, for the same
reason: `data.fetch.info` records every blob it fetches here, and
`analysis.portfolio._profile` answers from here first. Writing is best-effort —
a read-only filesystem costs a repeated lookup, never a failed render.
"""

from __future__ import annotations

import json
import re
import threading

from stocks import atomic
from stocks.config import DATA_DIR

PROFILE_CACHE = DATA_DIR / "profiles.json"

# What is kept. Anything that moves (prices, market cap, margins) is
# deliberately not on the list — this memo has no TTL.
FIELDS = ("sector", "industry", "country", "currency", "quoteType", "name")
# The ones a throttled Yahoo leaves out: it answers the quote alone, without
# the company's profile, and the blob still looks whole (a price, a P/E, a
# market cap). They decide how a company is valued (`analysis.review` picks
# a bank's lens, or prices what AI can copy, by the industry), so a blob that
# lacks them is given what an earlier, whole answer said (`fill`).
CLASSIFIED = ("sector", "industry", "country")

_lock = threading.Lock()
_memo: dict[str, dict[str, str]] | None = None


def _read() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(PROFILE_CACHE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): {f: str(v[f]) for f in FIELDS if v.get(f)}
        for k, v in data.items()
        if isinstance(v, dict)
    }


def _all() -> dict[str, dict[str, str]]:
    global _memo
    if _memo is None:
        _memo = _read()
    return _memo


def known(symbol: str) -> dict[str, str] | None:
    """The stored profile for a Yahoo symbol, or None when never seen.

    A hit always carries `quoteType`: a blob that lacked it (Yahoo returned a
    stub) is not remembered, so a caller can trust the answer to say whether
    the name is a fund — the one case where the memo is not enough on its own
    (a fund's sector split is a look-through, see `analysis.portfolio._profile`).
    """
    with _lock:
        hit = _all().get(symbol.upper())
    return dict(hit) if hit else None


# The kinds whose name names one security across its lines: a company's
# share (SAP and SAP.DE, an ADR and its home line: TM and 7203.T) or one
# fund's class (CSPX.L and SXR8.DE). Yahoo spells the name the same on each.
_ONE_ISSUER = frozenset({"EQUITY", "ETF"})


def company(symbol: str) -> str | None:
    """The issuer's name as one key across the lines it trades on: lower case,
    punctuation and spacing folded ("sap se"). None for a symbol never seen
    or of another kind (a coin, an index), whose name says nothing of whose
    it is. Disk only, never the network."""
    hit = known(symbol)
    if not hit or hit.get("quoteType") not in _ONE_ISSUER:
        return None
    name = str(hit.get("name") or "").casefold()
    key = " ".join(re.sub(r"[^0-9a-z]+", " ", name).split())
    return key or None


def fill(symbol: str, info: dict) -> dict:
    """`info` with the `CLASSIFIED` facts it lacks taken from the memo.

    The same dict when nothing is missing or nothing is known; a copy
    otherwise, so the caller's blob is never edited under it."""
    if not symbol or not info.get("quoteType"):
        return info
    stored = known(symbol) or {}
    missing = {f: stored[f] for f in CLASSIFIED if not info.get(f) and stored.get(f)}
    return {**info, **missing} if missing else info


def remember(symbol: str, info: dict | None) -> None:
    """Record the fixed fields of `info` for `symbol`; a no-op on a stub.

    A field the blob lacks keeps what was known: Yahoo's quote-only answer
    carries a quoteType and no sector, and replacing the entry with it forgot
    the industry until the next whole answer."""
    if not symbol or not isinstance(info, dict) or not info.get("quoteType"):
        return
    # Yahoo's own name for the listing: the one source that covers a non-US
    # symbol the SEC map and the fund catalog do not.
    named = {**info, "name": info.get("longName") or info.get("shortName")}
    entry = {f: str(named[f]) for f in FIELDS if named.get(f)}
    key = symbol.upper()
    with _lock:
        cache = _all()
        entry = {**cache.get(key, {}), **entry}
        if cache.get(key) == entry:
            return
        cache[key] = entry
        stored = _read() | {key: entry}
        try:
            atomic.write_json(PROFILE_CACHE, stored, indent=0, sort_keys=True)
        except OSError:
            pass


def clear() -> None:
    """Forget the in-process copy (tests swapping the data dir)."""
    global _memo
    with _lock:
        _memo = None
