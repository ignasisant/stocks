"""Nightly crypto scan — the market-wide figures a coin's page reads.

CoinGecko and alternative.me rate-limit per IP, and the app's egress IP shares
that budget with every other keyless caller (`stocks.data.crypto_market`). So
they are read once a night, from a GitHub Actions runner, into one file every
account shares (`data/crypto_scan.json`, mirrored to the bucket like the
sector scan). A page request never calls either.

What the file holds:

* `global` — the whole market's capitalisation in each quote currency and
  bitcoin's and ether's share of it.
* `fear_greed` — the past year of the Crypto Fear & Greed Index, by day.
* `coins` — per coin code in `crypto.GECKO_MARKET_IDS`: rank, all-time high
  and its date, market cap and fully diluted value, each in USD, EUR and GBP
  (the pair's own currency, so no FX hop sits between a EUR pair and its
  peak); circulating, total and maximum supply.

Failure policy, the sector scan's: a part that did not answer tonight keeps
last night's figures, and the file is never published half-empty.
"""

from __future__ import annotations

import json
import time
from datetime import date
from urllib.error import HTTPError

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR
from stocks.data import crypto_market as source
from stocks.data.crypto import GECKO_MARKET_IDS, QUOTE_CURRENCIES

SCAN_FILE = DATA_DIR / "crypto_scan.json"

# Between CoinGecko calls: five of them, well under the keyless tier's
# per-minute budget even from a runner IP someone else hammered first.
PAUSE_S = 4.0
# One retry after a 429, waiting what CoinGecko asked for, within reason.
_RETRY_BOUNDS = (10.0, 90.0)

_PER_QUOTE = ("ath", "ath_date", "market_cap", "fdv")


def load_scan(*, restore: bool = True) -> dict:
    """The stored scan, or {} when there is none (or it will not parse)."""
    if restore and storage.enabled():
        with obs.swallow("crypto.scan_restore"):
            storage.restore(SCAN_FILE)
    try:
        raw = json.loads(SCAN_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_scan(payload: dict) -> None:
    SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(SCAN_FILE, payload, indent=0, sort_keys=True)
    if storage.enabled():
        with obs.swallow("crypto.scan_persist"):
            storage.persist(SCAN_FILE)


def _patient(call, *args):
    """`call(*args)`, once more after a 429 once CoinGecko's wait is over."""
    try:
        return call(*args)
    except HTTPError as exc:
        if exc.code != 429:
            raise
        header = exc.headers.get("Retry-After") if exc.headers else None
        try:
            wait = float(header) if header is not None else _RETRY_BOUNDS[1]
        except ValueError:
            wait = _RETRY_BOUNDS[1]
        wait = min(max(wait, _RETRY_BOUNDS[0]), _RETRY_BOUNDS[1])
        obs.warn("crypto.scan_rate_limited", wait_s=wait)
        time.sleep(wait)
        return call(*args)


def _num(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def coins_from(markets: dict[str, list[dict]]) -> dict[str, dict]:
    """Per coin code, the rows of each quote's `/coins/markets` folded together.

    Supply and rank are the same in every currency; they are read from
    whichever quote answered first.
    """
    by_id = {gid: code for code, gid in GECKO_MARKET_IDS.items()}
    out: dict[str, dict] = {}
    for quote, rows in markets.items():
        for row in rows:
            code = by_id.get(str(row.get("id")))
            if code is None:
                continue
            coin = out.setdefault(code, {"id": row["id"], **{k: {} for k in _PER_QUOTE}})
            coin["ath"][quote] = _num(row.get("ath"))
            coin["ath_date"][quote] = (row.get("ath_date") or "")[:10] or None
            coin["market_cap"][quote] = _num(row.get("market_cap"))
            coin["fdv"][quote] = _num(row.get("fully_diluted_valuation"))
            for key, field in (
                ("rank", "market_cap_rank"),
                ("circulating", "circulating_supply"),
                ("total_supply", "total_supply"),
                ("max_supply", "max_supply"),
            ):
                if coin.get(key) is None:
                    coin[key] = _num(row.get(field))
    for coin in out.values():
        if coin.get("rank") is not None:
            coin["rank"] = int(coin["rank"])
    return out


def _merge_coins(old: dict, new: dict) -> dict:
    """Tonight's coins over last night's, one currency at a time: a quote that
    did not answer keeps yesterday's peak instead of dropping it."""
    out = {
        code: dict(coin) for code, coin in (old or {}).items() if isinstance(coin, dict)
    }
    for code, coin in new.items():
        merged = out.setdefault(code, {})
        for key, value in coin.items():
            if key in _PER_QUOTE:
                merged[key] = {**(merged.get(key) or {}), **{
                    q: v for q, v in value.items() if v is not None}}
            elif value is not None:
                merged[key] = value
    return out


def global_from(data: dict) -> dict:
    caps = data.get("total_market_cap") or {}
    shares = data.get("market_cap_percentage") or {}
    return {
        "total_mcap": {
            q.lower(): v for q in QUOTE_CURRENCIES
            if (v := _num(caps.get(q.lower()))) is not None
        },
        "btc_dominance": _num(shares.get("btc")),
        "eth_dominance": _num(shares.get("eth")),
    }


def run_scan(*, dry_run: bool = False) -> dict[str, str]:
    """Fetch tonight's figures, merge over last night's, write. Status per part."""
    stored = load_scan()
    payload = {
        "global": stored.get("global") or {},
        "fear_greed": stored.get("fear_greed") or [],
        "coins": stored.get("coins") or {},
    }
    status: dict[str, str] = {}

    markets: dict[str, list[dict]] = {}
    ids = sorted(set(GECKO_MARKET_IDS.values()))
    for i, quote in enumerate(q.lower() for q in QUOTE_CURRENCIES):
        if i:
            time.sleep(PAUSE_S)
        try:
            markets[quote] = _patient(source.gecko_markets, ids, quote)
            status[f"markets_{quote}"] = f"ok ({len(markets[quote])} coins)"
        except Exception as exc:  # noqa: BLE001 — keep last night's
            obs.warn("crypto.scan_failed", part=f"markets_{quote}", error=repr(exc)[:200])
            status[f"markets_{quote}"] = f"kept ({type(exc).__name__})"
    if markets:
        payload["coins"] = _merge_coins(payload["coins"], coins_from(markets))

    time.sleep(PAUSE_S)
    try:
        fresh = global_from(_patient(source.gecko_global))
        if fresh["btc_dominance"] is not None:
            payload["global"] = fresh
            status["global"] = "ok"
        else:
            status["global"] = "kept (empty)"
    except Exception as exc:  # noqa: BLE001
        obs.warn("crypto.scan_failed", part="global", error=repr(exc)[:200])
        status["global"] = f"kept ({type(exc).__name__})"

    try:
        series = source.fear_greed(365)
        if series:
            payload["fear_greed"] = [[day, value] for day, value in series]
            status["fear_greed"] = f"ok ({len(series)} days)"
        else:
            status["fear_greed"] = "kept (empty)"
    except Exception as exc:  # noqa: BLE001
        obs.warn("crypto.scan_failed", part="fear_greed", error=repr(exc)[:200])
        status["fear_greed"] = f"kept ({type(exc).__name__})"

    payload["saved"] = date.today().isoformat()
    if dry_run:
        sample = {
            **payload,
            "fear_greed": payload["fear_greed"][-3:],
            "coins": {k: payload["coins"][k] for k in list(payload["coins"])[:2]},
        }
        print(json.dumps(sample, indent=1, default=str))
    elif payload["coins"] or payload["global"] or payload["fear_greed"]:
        save_scan(payload)
    obs.event("crypto.scan", **status)
    return status
