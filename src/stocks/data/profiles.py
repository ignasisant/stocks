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
import threading

from stocks.config import DATA_DIR

PROFILE_CACHE = DATA_DIR / "profiles.json"

# What is kept. Anything that moves (prices, market cap, margins) is
# deliberately not on the list — this memo has no TTL.
FIELDS = ("sector", "country", "currency", "quoteType")

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


def remember(symbol: str, info: dict | None) -> None:
    """Record the fixed fields of `info` for `symbol`; a no-op on a stub."""
    if not symbol or not isinstance(info, dict) or not info.get("quoteType"):
        return
    entry = {f: str(info[f]) for f in FIELDS if info.get(f)}
    key = symbol.upper()
    with _lock:
        cache = _all()
        if cache.get(key) == entry:
            return
        cache[key] = entry
        stored = _read() | {key: entry}
        try:
            PROFILE_CACHE.write_text(json.dumps(stored, indent=0, sort_keys=True))
        except OSError:
            pass


def clear() -> None:
    """Forget the in-process copy (tests swapping the data dir)."""
    global _memo
    with _lock:
        _memo = None
