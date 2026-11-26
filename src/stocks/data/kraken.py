"""Crypto quotes from Kraken's public ticker, outside Yahoo's allowance.

A coin trades around the clock, so its row on Home is the one most likely to
read stale, and every refresh of it used to be one more Yahoo request from an
IP Yahoo already throttles. Kraken's public `Ticker` answers any number of
pairs in one keyless request, from a datacenter IP, without a quota worth
the name (about one call a second). So crypto pairs ask here first and only
fall back to Yahoo when Kraken has nothing usable.

The two numbers a day move needs line up with Yahoo's: `c` is the last trade
and `o` is the price at 00:00 UTC, which is the close a Yahoo crypto bar ends
on. The row is shaped as a Yahoo v7 quote (`regularMarketPrice`,
`regularMarketPreviousClose`, an always-open `marketState`) so
`analysis.portfolio.quote_snapshot` reads it without knowing who fetched it.

A thin pair's last trade can be hours old (Simon's Cat in euros printed once
on 2026-11-26), and reads as "no move" when the coin moved. A pair with fewer
than `MIN_TRADES` in the last 24 hours is left to the next source.

The pair map comes from `AssetPairs` (once a day): Kraken spells Bitcoin XBT
and Dogecoin XDG, and its oldest pairs answer under a legacy key (XXBTZEUR)
rather than the name asked for (XBTEUR).
"""

from __future__ import annotations

import threading
import time
import urllib.parse

from stocks import obs
from stocks.data.crypto import CRYPTO_NAMES, QUOTE_CURRENCIES, split_pair
from stocks.data.http import get_json

API_ROOT = "https://api.kraken.com/0/public"

# A page render waits on this, and it comes out of Yahoo's budget: past it,
# the coins go to Yahoo instead. Kraken answers in well under a second.
TIMEOUT = 2.0

# Trades over the last 24 hours below which a pair's last price is not a
# quote. BTC, ETH and SOL print thousands; the meme coins a Revolut book
# holds print hundreds; the pairs this keeps out print one or two.
MIN_TRADES = 50

# The pair map changes when Kraken lists a coin: once a day is plenty. A map
# that would not load is asked for again after `RETRY_S`, not on every call.
PAIRS_TTL_S = 24 * 3600.0
RETRY_S = 600.0

# After a failed ticker request: long enough not to hammer a host that is
# down, short enough that the coins come back within a couple of refreshes.
COOLDOWN_S = 120.0

# Kraken's own codes for coins the rest of the world spells otherwise.
_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}

_NEVER = float("-inf")
_lock = threading.Lock()
# (monotonic when loaded or tried, {pair symbol: (response key, altname)}).
_pairs: tuple[float, dict[str, tuple[str, str]] | None] = (_NEVER, None)
_blocked_until = _NEVER


def _get(url: str, timeout: float) -> dict:
    """Kraken's raw JSON body for `url` (stubbed in tests and the load test)."""
    return get_json(url, timeout=timeout)


def covers(symbol: str) -> bool:
    """Whether `symbol` is a crypto pair Kraken could quote (no network)."""
    return split_pair(symbol) is not None


def clear() -> None:
    """Forget the pair map and any cooldown (tests)."""
    global _pairs, _blocked_until
    with _lock:
        _pairs = (_NEVER, None)
        _blocked_until = _NEVER


def _pair_map(timeout: float) -> dict[str, tuple[str, str]]:
    """{"BTC-EUR": ("XXBTZEUR", "XBTEUR"), …} for the online fiat pairs."""
    global _pairs
    now = time.monotonic()
    with _lock:
        at, known = _pairs
        if known is not None and now - at < PAIRS_TTL_S:
            return known
        if known is None and now - at < RETRY_S:
            return {}
    found: dict[str, tuple[str, str]] = {}
    try:
        body = _get(f"{API_ROOT}/AssetPairs", timeout)
        for key, pair in (body.get("result") or {}).items():
            if not isinstance(pair, dict) or pair.get("status", "online") != "online":
                continue
            coin, _, fiat = str(pair.get("wsname") or "").partition("/")
            if fiat not in QUOTE_CURRENCIES or not coin:
                continue
            found[f"{_ALIASES.get(coin, coin)}-{fiat}"] = (
                str(key),
                str(pair.get("altname") or key),
            )
    except Exception as exc:  # noqa: BLE001 — a coin quote is never fatal
        obs.warn("kraken.pairs.failed", error=repr(exc)[:300])
    with _lock:
        if found:
            _pairs = (now, found)
        else:
            _pairs = (now, _pairs[1]) if _pairs[1] is not None else (now, None)
        return _pairs[1] or {}


def _row(symbol: str, tick: dict, fetched: float) -> dict | None:
    """A Yahoo-v7-shaped row from Kraken's ticker entry, None when thin."""
    try:
        trades = int((tick.get("t") or [0, 0])[1])
        last = float((tick.get("c") or [0])[0])
        opened = float(tick.get("o") or 0)
    except (TypeError, ValueError, IndexError):
        return None
    if trades < MIN_TRADES or last <= 0 or opened <= 0:
        return None
    coin, _, fiat = symbol.partition("-")
    return {
        "symbol": symbol,
        # The chat's quote card prints a name; Yahoo's row would carry one.
        "shortName": f"{CRYPTO_NAMES.get(coin, coin)} {fiat}",
        "marketState": "REGULAR",
        "regularMarketPrice": last,
        "regularMarketPreviousClose": opened,
        "regularMarketTime": int(fetched),
        "exchangeTimezoneName": "UTC",
        "currency": fiat,
        "quoteSource": "kraken",
    }


def quotes(symbols: list[str], *, timeout: float = TIMEOUT) -> dict[str, dict]:
    """`{symbol: v7-shaped row}` for the liquid pairs among `symbols`.

    One request for all of them. Never raises: a pair Kraken does not list, a
    thin one, a failed request or an open cooldown are simply absent, and the
    caller asks the next source.
    """
    global _blocked_until
    wanted = [s for s in dict.fromkeys(symbols) if covers(s)]
    if not wanted:
        return {}
    with _lock:
        if time.monotonic() < _blocked_until:
            return {}
    deadline = time.monotonic() + timeout
    known = _pair_map(timeout)
    asked = {s: known[s] for s in wanted if s in known}
    if not asked:
        return {}
    left = deadline - time.monotonic()
    if left <= 0:
        return {}
    by_key = {}
    for symbol, (key, alt) in asked.items():
        by_key[key] = by_key[alt] = symbol
    names = urllib.parse.quote(",".join(alt for _, alt in asked.values()), safe=",")
    out: dict[str, dict] = {}
    with obs.timed("kraken.quotes", symbols=len(asked)) as rec:
        try:
            body = _get(f"{API_ROOT}/Ticker?pair={names}", left)
            if body.get("error"):
                raise RuntimeError(str(body["error"])[:200])
            fetched = time.time()
            for key, tick in (body.get("result") or {}).items():
                symbol = by_key.get(str(key))
                if symbol and isinstance(tick, dict):
                    if (row := _row(symbol, tick, fetched)) is not None:
                        out[symbol] = row
        except Exception as exc:  # noqa: BLE001 — a coin quote is never fatal
            obs.warn("kraken.quotes.failed", symbols=len(asked), error=repr(exc)[:300])
            with _lock:
                _blocked_until = time.monotonic() + COOLDOWN_S
        rec["quotes"] = len(out)
    return out
