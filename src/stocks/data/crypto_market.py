"""Market-wide crypto data: CoinGecko metadata, Fear & Greed, perpetual swaps.

Two sources, two places they may be called from:

* **CoinGecko and alternative.me** — keyless, rate-limited per IP, and a Cloud
  Run egress IP shares its budget with everyone else's keyless calls. They are
  read ONLY by the nightly scan (`stocks.analysis.crypto_scan`, a GitHub
  Actions job), never on a page request.
* **Derivatives venues** (Bybit, Binance, OKX) — the opposite constraint: all
  three refuse US IPs, and GitHub's runners are in the US. Funding and open
  interest are read live, from the app's own European egress, behind a cache.
  The venues are tried in order and the first that lists the coin's USDT
  perpetual answers; a coin none of them lists has no positioning card.

Every function raises on a transport failure; the callers decide what a
failure costs (the scan keeps last night's figures, the page hides the card).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlencode

from stocks import obs
from stocks.data.http import get_json

GECKO_API = "https://api.coingecko.com/api/v3"
FNG_URL = "https://api.alternative.me/fng/?limit={days}"

# /coins/markets answers up to 250 ids a page; the curated map is a fifth of it.
GECKO_PAGE = 250


def gecko_markets(ids: list[str], quote: str) -> list[dict]:
    """One `/coins/markets` row per id, priced in `quote` (usd, eur, gbp)."""
    out: list[dict] = []
    for start in range(0, len(ids), GECKO_PAGE):
        chunk = ids[start : start + GECKO_PAGE]
        query = urlencode(
            {
                "vs_currency": quote.lower(),
                "ids": ",".join(chunk),
                "per_page": GECKO_PAGE,
                "page": 1,
            }
        )
        rows = get_json(f"{GECKO_API}/coins/markets?{query}", timeout=20)
        if isinstance(rows, list):
            out.extend(r for r in rows if isinstance(r, dict))
    return out


def gecko_global() -> dict:
    """`/global`'s `data`: total market cap by currency, dominance by coin."""
    raw = get_json(f"{GECKO_API}/global", timeout=20)
    data = raw.get("data") if isinstance(raw, dict) else None
    return data if isinstance(data, dict) else {}


def fear_greed(days: int = 365) -> list[tuple[str, int]]:
    """alternative.me's Crypto Fear & Greed Index, oldest first, as (day, 0..100)."""
    raw = get_json(FNG_URL.format(days=days), timeout=20)
    out: dict[str, int] = {}
    for row in (raw or {}).get("data") or []:
        try:
            day = datetime.fromtimestamp(int(row["timestamp"]), UTC).date()
            out[day.isoformat()] = int(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out.items())


# --------------------------------------------------------------- derivatives


@dataclass(frozen=True)
class Positioning:
    """A coin's USDT perpetual on one venue: what longs pay, and how much is open.

    `funding` is the current (or last settled) rate per `interval_h` hours;
    `funding_7d` the mean of the past week's settlements, same unit. Open
    interest is in US dollars; `oi_change_7d` is a fraction, None when the
    venue gives no history.
    """

    venue: str
    symbol: str
    funding: float | None
    funding_7d: float | None
    interval_h: float
    oi_usd: float | None
    oi_change_7d: float | None


def _float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _mean(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _change(first: float | None, last: float | None) -> float | None:
    if first is None or last is None or first <= 0:
        return None
    return last / first - 1.0


def _contracts(coin: str) -> tuple[str, ...]:
    """The perpetual symbols a coin may trade under: PEPE lists as 1000PEPE."""
    return (f"{coin}USDT", f"1000{coin}USDT")


BYBIT = "https://api.bybit.com/v5/market"


def _bybit(coin: str) -> Positioning | None:
    for symbol in _contracts(coin):
        q = {"category": "linear", "symbol": symbol}
        rows = (get_json(f"{BYBIT}/tickers?{urlencode(q)}", timeout=10).get("result")
                or {}).get("list") or []
        if not rows:
            continue
        row = rows[0]
        hours = _float(row.get("fundingIntervalHour")) or 8.0
        history = (get_json(
            f"{BYBIT}/funding/history?{urlencode({**q, 'limit': int(7 * 24 / hours)})}",
            timeout=10,
        ).get("result") or {}).get("list") or []
        oi = (get_json(
            f"{BYBIT}/open-interest?{urlencode({**q, 'intervalTime': '1d', 'limit': 8})}",
            timeout=10,
        ).get("result") or {}).get("list") or []
        # Bybit lists newest first, in contracts (= coins for a linear swap).
        oi_coins = [_float(r.get("openInterest")) for r in oi]
        return Positioning(
            venue="bybit",
            symbol=symbol,
            funding=_float(row.get("fundingRate")),
            funding_7d=_mean([_float(r.get("fundingRate")) for r in history]),
            interval_h=hours,
            oi_usd=_float(row.get("openInterestValue")),
            # Contracts, not dollars: a week's price move would read as
            # positions opened or closed.
            oi_change_7d=(
                _change(oi_coins[-1], oi_coins[0]) if len(oi_coins) >= 2 else None
            ),
        )
    return None


BINANCE = "https://fapi.binance.com"


def _binance(coin: str) -> Positioning | None:
    for symbol in _contracts(coin):
        try:
            premium = get_json(
                f"{BINANCE}/fapi/v1/premiumIndex?{urlencode({'symbol': symbol})}",
                timeout=10,
            )
        except Exception as exc:
            # An unlisted symbol is a 400, not an empty list.
            if getattr(exc, "code", None) == 400:
                continue
            raise
        # A list, though `get_json` is typed for the usual object.
        history = cast(list[dict], get_json(
            f"{BINANCE}/fapi/v1/fundingRate?{urlencode({'symbol': symbol, 'limit': 21})}",
            timeout=10,
        ))
        oi = get_json(
            f"{BINANCE}/futures/data/openInterestHist?"
            f"{urlencode({'symbol': symbol, 'period': '1d', 'limit': 8})}",
            timeout=10,
        )
        rates = [_float(r.get("fundingRate")) for r in history or []]
        # Binance lists oldest first.
        oi_coins = [_float(r.get("sumOpenInterest")) for r in oi or []]
        oi_usd = [_float(r.get("sumOpenInterestValue")) for r in oi or []]
        return Positioning(
            venue="binance",
            symbol=symbol,
            funding=_float(premium.get("lastFundingRate")),
            funding_7d=_mean(rates),
            interval_h=8.0 if len(history or []) < 2 else _interval(history),
            oi_usd=oi_usd[-1] if oi_usd else None,
            oi_change_7d=(
                _change(oi_coins[0], oi_coins[-1]) if len(oi_coins) >= 2 else None
            ),
        )
    return None


def _interval(history: list[dict]) -> float:
    """Hours between Binance's last two settlements — 8, or 4 for some coins."""
    try:
        times = sorted(int(r["fundingTime"]) for r in history[-2:])
        hours = round((times[1] - times[0]) / 3_600_000, 1)
    except (KeyError, TypeError, ValueError, IndexError):
        return 8.0
    return hours if hours > 0 else 8.0


OKX = "https://www.okx.com/api/v5/public"


def _okx(coin: str) -> Positioning | None:
    inst = f"{coin}-USDT-SWAP"
    rate = (get_json(f"{OKX}/funding-rate?{urlencode({'instId': inst})}", timeout=10)
            .get("data") or [])
    if not rate:
        return None
    history = (get_json(
        f"{OKX}/funding-rate-history?{urlencode({'instId': inst, 'limit': 21})}",
        timeout=10,
    ).get("data") or [])
    oi = (get_json(
        f"{OKX}/open-interest?{urlencode({'instType': 'SWAP', 'instId': inst})}",
        timeout=10,
    ).get("data") or [])
    row = rate[0]
    try:
        hours = (int(row["nextFundingTime"]) - int(row["fundingTime"])) / 3_600_000
    except (KeyError, TypeError, ValueError):
        hours = 8.0
    return Positioning(
        venue="okx",
        symbol=inst,
        funding=_float(row.get("fundingRate")),
        funding_7d=_mean([_float(r.get("realizedRate") or r.get("fundingRate"))
                          for r in history]),
        interval_h=hours if hours > 0 else 8.0,
        oi_usd=_float(oi[0].get("oiUsd")) if oi else None,
        # OKX's public API has no daily open-interest history.
        oi_change_7d=None,
    )


VENUES = (("bybit", _bybit), ("binance", _binance), ("okx", _okx))


def positioning(coin: str) -> Positioning | None:
    """The first venue listing `coin`'s USDT perpetual; None when none does.

    A venue that errors is skipped, not fatal: Binance refuses some regions
    outright, Bybit has had whole-API outages. Only when every venue failed
    does the error surface — "nobody lists it" and "nobody answered" are
    different facts, and the second must not be cached as the first.
    """
    errors = 0
    for name, read in VENUES:
        try:
            got = read(coin.upper())
        except Exception as exc:  # noqa: BLE001 — one venue down is routine
            errors += 1
            obs.warn("crypto.venue_failed", venue=name, coin=coin, error=repr(exc)[:200])
            continue
        if got is not None:
            return got
    if errors == len(VENUES):
        raise RuntimeError(f"every derivatives venue failed for {coin}")
    return None
