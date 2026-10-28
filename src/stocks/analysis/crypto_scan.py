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
* `dvol` — Deribit's options-implied volatility index for BTC and ETH: today,
  its percentile over the past year, the range, a week ago.
* `stablecoins` — DefiLlama's total stablecoin supply and its 30/90-day change.
* `onchain` — `map`: coin code to the DefiLlama chain or protocol its token
  stands for (persisted, rebuilt nightly from `/protocols` and `/v2/chains`);
  `coins`: that entry's TVL, 30-day TVL change and 30-day fees and revenue.

Failure policy, the sector scan's: a part that did not answer tonight keeps
last night's figures, and the file is never published half-empty.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from urllib.error import HTTPError

from stocks import atomic, obs, storage
from stocks.analysis import crypto_market as cm
from stocks.config import DATA_DIR
from stocks.data import crypto_market as source
from stocks.data.crypto import (
    CRYPTO_NAMES,
    GECKO_MARKET_IDS,
    QUOTE_CURRENCIES,
    STABLECOINS,
)

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


# ------------------------------------------------- options vol and on-chain

# Deribit lists DVOL for these two only.
DVOL_COINS = ("BTC", "ETH")
# DefiLlama tracks no TVL worth a line under this (dollars).
MIN_TVL = 1_000_000.0
# Pause between DefiLlama calls: ~4 per mapped coin, spread out.
LLAMA_PAUSE_S = 0.5
# Protocol categories whose symbol is a bridge, a foundation's wallet or an
# exchange's reserve, not the coin's own protocol.
_NOT_A_PROTOCOL = {
    "Canonical Bridge", "Bridge", "Cross Chain Bridge", "Foundation", "Chain",
    "CEX", "Bridge Aggregator", "Bridge Aggregators",
}
# Coins DefiLlama lists under another name (MKR became Sky), and the parent
# ids whose API slug is not the id (`parent#maker` answers at `/sky`).
_PROTOCOL_ALIASES = {"MKR": "maker"}
_SLUG_FIX = {"maker": "sky"}


def _protocol_key(row: dict) -> str:
    parent = row.get("parentProtocol")
    return str(parent).removeprefix("parent#") if parent else str(row.get("slug") or "")


def map_coins(protocols: list[dict], chains: list[dict]) -> dict[str, dict]:
    """Coin code -> the DefiLlama chain or protocol its token stands for.

    A chain wins (the gas token IS the chain: ETH, SOL, AVAX), matched on the
    CoinGecko id the curated map already carries. Otherwise a protocol whose
    CoinGecko id or token symbol is the coin's, children of one parent
    summed so Uniswap is one protocol rather than four versions. Anything
    under `MIN_TVL` is left out: no line beats a line about nothing.
    Bitcoin is skipped — its "chain TVL" is wrapped coins, not the network.
    """
    by_chain = {str(c["gecko_id"]): c for c in chains if c.get("gecko_id")}
    groups: dict[str, list[dict]] = {}
    for row in protocols:
        if row.get("category") in _NOT_A_PROTOCOL:
            continue
        groups.setdefault(_protocol_key(row), []).append(row)
    out: dict[str, dict] = {}
    for code, gid in GECKO_MARKET_IDS.items():
        if code == "BTC" or code in STABLECOINS:
            continue
        chain = by_chain.get(gid)
        if chain is not None and (_num(chain.get("tvl")) or 0) >= MIN_TVL:
            out[code] = {"kind": "chain", "slug": str(chain["name"]),
                         "name": str(chain["name"])}
            continue
        alias = _PROTOCOL_ALIASES.get(code)
        own = (CRYPTO_NAMES.get(code) or "").lower().replace(" ", "-")
        best, best_tvl = None, 0.0
        for key, rows in groups.items():
            # Never on the symbol alone: "DOT" and "EOS" are also the tickers
            # of unrelated small protocols.
            hit = key in (alias, own) or any(r.get("gecko_id") == gid for r in rows)
            tvl = sum(_num(r.get("tvl")) or 0 for r in rows)
            if hit and tvl > best_tvl:
                best, best_tvl = key, tvl
        if best is not None and best_tvl >= MIN_TVL:
            first = max(groups[best], key=lambda r: _num(r.get("tvl")) or 0)
            name = re.sub(r"\s+v\d+(\.\d+)?$", "", str(first.get("name") or best),
                          flags=re.IGNORECASE)
            out[code] = {"kind": "protocol", "slug": _SLUG_FIX.get(best, best),
                         "name": name}
    return out


def dvol_from(series: list[tuple[str, float]]) -> dict | None:
    """Today's DVOL with its place in the series (percentile, range, week ago)."""
    if len(series) < 30:
        return None
    closes = [v for _, v in series]
    now = closes[-1]
    return {
        "value": now,
        "percentile": cm.percentile_rank(closes, now),
        "low": min(closes),
        "high": max(closes),
        "week_ago": closes[-8] if len(closes) >= 8 else None,
        "as_of": series[-1][0],
    }


def stablecoins_from(series: list[tuple[str, float]]) -> dict | None:
    if len(series) < 31:
        return None
    return {
        "usd": series[-1][1],
        "change_30d": cm.change_over(series, 30),
        "change_90d": cm.change_over(series, 90),
        "as_of": series[-1][0],
    }


def _fees_30d(slug: str, kind: str) -> float | None:
    try:
        return _num(source.llama_fees(slug, kind).get("total30d"))
    except Exception as exc:  # noqa: BLE001 — most slugs have no fee adapter
        if not isinstance(exc, HTTPError):
            obs.warn("crypto.scan_failed", part=f"fees_{slug}", error=repr(exc)[:200])
        return None


def onchain_for(entry: dict) -> dict | None:
    """TVL, its 30-day change and 30-day fees/revenue for one mapped coin."""
    series = source.llama_tvl_series(entry["kind"], entry["slug"])
    if not series:
        return None
    slug = entry["slug"]
    if entry["kind"] == "chain":
        slug = slug.lower().replace(" ", "-")
    time.sleep(LLAMA_PAUSE_S)
    fees = _fees_30d(slug, "dailyFees")
    time.sleep(LLAMA_PAUSE_S)
    revenue = _fees_30d(slug, "dailyRevenue") if fees is not None else None
    return {
        **entry,
        "tvl": series[-1][1],
        "tvl_change_30d": cm.change_over(series, 30),
        "fees_30d": fees,
        "revenue_30d": revenue,
        "as_of": series[-1][0],
    }


def run_scan(*, dry_run: bool = False) -> dict[str, str]:
    """Fetch tonight's figures, merge over last night's, write. Status per part."""
    stored = load_scan()
    payload = {
        "global": stored.get("global") or {},
        "fear_greed": stored.get("fear_greed") or [],
        "coins": stored.get("coins") or {},
        "dvol": stored.get("dvol") or {},
        "stablecoins": stored.get("stablecoins") or {},
        "onchain": stored.get("onchain") or {"map": {}, "coins": {}},
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

    for code in DVOL_COINS:
        try:
            fresh_vol = dvol_from(source.dvol(code))
            if fresh_vol is not None:
                payload["dvol"][code] = fresh_vol
                status[f"dvol_{code.lower()}"] = f"ok ({fresh_vol['value']:.1f})"
            else:
                status[f"dvol_{code.lower()}"] = "kept (short)"
        except Exception as exc:  # noqa: BLE001
            obs.warn("crypto.scan_failed", part=f"dvol_{code}", error=repr(exc)[:200])
            status[f"dvol_{code.lower()}"] = f"kept ({type(exc).__name__})"

    try:
        fresh_stables = stablecoins_from(source.stablecoin_supply())
        if fresh_stables is not None:
            payload["stablecoins"] = fresh_stables
            status["stablecoins"] = "ok"
        else:
            status["stablecoins"] = "kept (short)"
    except Exception as exc:  # noqa: BLE001
        obs.warn("crypto.scan_failed", part="stablecoins", error=repr(exc)[:200])
        status["stablecoins"] = f"kept ({type(exc).__name__})"

    try:
        mapping = map_coins(source.llama_protocols(), source.llama_chains())
        if mapping:
            payload["onchain"]["map"] = mapping
        status["onchain_map"] = f"ok ({len(mapping)} coins)"
    except Exception as exc:  # noqa: BLE001 — the stored map still serves
        obs.warn("crypto.scan_failed", part="onchain_map", error=repr(exc)[:200])
        status["onchain_map"] = f"kept ({type(exc).__name__})"
    done = 0
    for code, entry in sorted((payload["onchain"].get("map") or {}).items()):
        time.sleep(LLAMA_PAUSE_S)
        try:
            row = onchain_for(entry)
        except Exception as exc:  # noqa: BLE001 — this coin keeps last night's
            obs.warn("crypto.scan_failed", part=f"onchain_{code}", error=repr(exc)[:200])
            continue
        if row is not None:
            payload["onchain"].setdefault("coins", {})[code] = row
            done += 1
    status["onchain"] = f"ok ({done}/{len(payload['onchain'].get('map') or {})} coins)"

    payload["saved"] = date.today().isoformat()
    if dry_run:
        sample = {
            **payload,
            "fear_greed": payload["fear_greed"][-3:],
            "coins": {k: payload["coins"][k] for k in list(payload["coins"])[:2]},
            "onchain": {
                "map": payload["onchain"].get("map"),
                "coins": {k: v for k, v in list(
                    (payload["onchain"].get("coins") or {}).items())[:3]},
            },
        }
        print(json.dumps(sample, indent=1, default=str))
    elif payload["coins"] or payload["global"] or payload["fear_greed"]:
        save_scan(payload)
    obs.event("crypto.scan", parts=status)
    return status
