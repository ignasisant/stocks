"""Finnhub client — the US quote line that stays up when Yahoo throttles us.

Yahoo throttles Cloud Run's shared egress IPs, and while `data.fetch`'s
cooldown is open `data.quotes` has nothing to say: the day-change column goes
blank for the whole book. Finnhub's free plan answers `/quote` in real time for
US listings at 60 requests a minute, which covers a book in one pass. It covers
nothing else — a European or Asian listing is a paid-plan feature — so this is
a fallback for US symbols only, never a second source for everything.

Optional, like FMP: the key is `FINNHUB_API_KEY` or `[finnhub] api_key` in the
secrets file. Without one every call returns nothing and callers carry on with
what Yahoo gave them.

The answer is shaped as a Yahoo v7 quote row so `analysis.portfolio._snapshot`
reads it without knowing who fetched it. Finnhub's free quote has no extended
hours, so the row carries no `marketState`: it reads as the regular session —
live while the market trades, the last completed session once it closes.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.error
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait

from stocks import obs
from stocks.data.http import get_json
from stocks.secrets_env import secret

QUOTE_URL = "https://finnhub.io/api/v1/quote?symbol={symbol}"

# The free plan allows 60 a minute; a few spare so a second process (the cron
# job, a staging candidate) sharing the key does not tip us into 429.
PER_MINUTE = 55

# Parallel requests. Finnhub's burst ceiling is 30/s; eight keeps a 40-name
# book well under a second without coming near it.
WORKERS = 8

# Cooldowns after Finnhub refuses us: a 429 clears within the minute; a 401/403
# means the key is wrong, and asking again every render will not fix it.
THROTTLED_S = 60.0
REJECTED_S = 3600.0

# What a US listing looks like as a Yahoo symbol: bare letters, optionally a
# share class (BRK-B). A suffix (.MC, .L), an index (^GSPC), a currency (EUR=X)
# or a crypto pair (BTC-EUR) is somewhere Finnhub's free plan does not go.
_US_SYMBOL = re.compile(r"[A-Z]{1,5}(-[A-Z]{1,2})?")

_lock = threading.Lock()
_sent: deque[float] = deque()
_blocked_until = 0.0


def api_key() -> str | None:
    return secret("FINNHUB_API_KEY", "finnhub", "api_key") or None


def has_key() -> bool:
    return api_key() is not None


def covers(symbol: str) -> bool:
    """Whether `symbol` (a Yahoo symbol) is a US listing Finnhub's free plan quotes."""
    return bool(_US_SYMBOL.fullmatch(symbol))


def clear() -> None:
    """Forget the rate window and any cooldown (tests, a rotated key)."""
    global _blocked_until
    with _lock:
        _sent.clear()
        _blocked_until = 0.0


def _block(seconds: float) -> None:
    global _blocked_until
    with _lock:
        _blocked_until = max(_blocked_until, time.monotonic() + seconds)


def _take() -> bool:
    """Claim one request from the per-minute allowance; False when it is spent."""
    now = time.monotonic()
    with _lock:
        if now < _blocked_until:
            return False
        while _sent and now - _sent[0] >= 60:
            _sent.popleft()
        if len(_sent) >= PER_MINUTE:
            return False
        _sent.append(now)
        return True


def _fetch(symbol: str, key: str, timeout: float) -> dict:
    """Finnhub's raw `/quote` body for one symbol (its spelling: BRK.B)."""
    return get_json(
        QUOTE_URL.format(symbol=symbol),
        timeout=timeout,
        # In a header rather than `?token=`, so the key never lands in a URL
        # that an error message or a proxy log repeats.
        headers={"X-Finnhub-Token": key},
    )


def _row(symbol: str, body: dict) -> dict | None:
    """`body` as a Yahoo v7 quote row under `symbol`, None when it is empty.

    An unknown symbol is not an error at Finnhub: it answers 200 with every
    field zero.
    """
    try:
        price, prev = float(body.get("c") or 0), float(body.get("pc") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0 or prev <= 0:
        return None
    return {
        "symbol": symbol,
        "regularMarketPrice": price,
        "regularMarketPreviousClose": prev,
        "regularMarketTime": body.get("t") or None,
        "exchangeTimezoneName": "America/New_York",
        "currency": "USD",
        "quoteSource": "finnhub",
    }


def _one(symbol: str, key: str, timeout: float) -> dict | None:
    if not _take():
        return None
    try:
        body = _fetch(symbol.replace("-", "."), key, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _block(THROTTLED_S)
            obs.warn("finnhub.throttled")
        elif exc.code in (401, 403):
            _block(REJECTED_S)
            obs.warn("finnhub.rejected", status=exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 — a fallback quote is never fatal
        obs.event("finnhub.quote_failed", symbol=symbol, error=type(exc).__name__)
        return None
    return _row(symbol, body) if isinstance(body, dict) else None


def quotes(symbols: list[str], *, timeout: float) -> dict[str, dict]:
    """`{symbol: Yahoo-shaped row}` for the US `symbols` Finnhub could quote.

    Takes Yahoo symbols and keys the answer by them. Anything `covers` rejects
    is skipped unasked; so is everything once the minute's allowance or a
    cooldown runs out. Never raises, and never waits past `timeout`: a request
    still in flight then is abandoned, not joined.
    """
    key = api_key()
    wanted = [s for s in dict.fromkeys(symbols) if covers(s)]
    if key is None or not wanted:
        return {}
    out: dict[str, dict] = {}
    pool = ThreadPoolExecutor(max_workers=min(WORKERS, len(wanted)))
    with obs.timed("finnhub.quotes", symbols=len(wanted)) as rec:
        try:
            futures = {pool.submit(_one, s, key, timeout): s for s in wanted}
            done, _ = wait(futures, timeout=timeout)
            for future in done:
                row = future.result()
                if row is not None:
                    out[futures[future]] = row
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        rec["quotes"] = len(out)
    return out
