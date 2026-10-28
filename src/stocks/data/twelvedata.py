"""Twelve Data client — daily closes for the US names Yahoo left unanswered.

Yahoo throttles Cloud Run's shared egress IPs and sometimes answers a blank
frame without saying why. Stooq, the keyless daily CSV this fallback was first
meant to be, now puts a JavaScript proof-of-work check in front of every
scripted request (probed 2026-10-27), so it is not a source for a server. Of
the keyed free tiers, Twelve Data's is the one whose daily bars are
split-adjusted by default, which is the scale `fetch.close_on` and the
`auto_adjust=False` download promise their callers: 8 requests a minute and
800 a day, one request (one credit) per symbol.

It covers US symbols only (`covers`): the free plan answers a European or
Asian listing with a plan error, and a bare code of another country that
happens to look like a ticker is refused by the response itself — the answer
must say USD on a New York exchange.

Optional, like Finnhub: `TWELVEDATA_API_KEY` or `[twelvedata] api_key` in the
secrets file. Without one every call returns nothing and callers carry on with
what Yahoo gave them.

A frame is marked `attrs["source"] == "twelvedata"` and is never a replacement
for Yahoo's: callers ask only for names Yahoo did not answer, and a split-only
`Close` stands in for `Adj Close` (a dividend does not restate the past).
"""

from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.parse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from stocks import obs
from stocks.data.http import get_json
from stocks.secrets_env import secret

API_ROOT = "https://api.twelvedata.com/time_series"
SOURCE = "twelvedata"

# The free plan is 8 credits a minute (800 a day); one spare for a second
# process sharing the key.
PER_MINUTE = 7
WORKERS = 4
TIMEOUT_S = 8.0
# Daily bars change once a day: an hour's memo, and a name the plan refuses is
# not asked again for as long.
TTL_S = 3600.0
THROTTLED_S = 60.0
REJECTED_S = 3600.0
# `outputsize` ceiling; ~20 years of sessions.
MAX_ROWS = 5000

_US_SYMBOL = re.compile(r"[A-Z]{1,5}(-[A-Z]{1,2})?")
_COLUMNS = {"open": "Open", "high": "High", "low": "Low", "close": "Close"}

_lock = threading.Lock()
_sent: deque[float] = deque()
_blocked_until = 0.0
# (symbol, start, adjust) -> (monotonic when read, frame or None for refused).
_memo: dict[tuple[str, str, str], tuple[float, pd.DataFrame | None]] = {}


def api_key() -> str | None:
    return secret("TWELVEDATA_API_KEY", "twelvedata", "api_key") or None


def has_key() -> bool:
    return api_key() is not None


def covers(symbol: str) -> bool:
    """Whether `symbol` (a Yahoo symbol) is a US listing the free plan serves."""
    return bool(_US_SYMBOL.fullmatch(symbol))


def spelling(symbol: str) -> str:
    """Twelve Data's spelling of a Yahoo symbol: the share class after a dot."""
    return symbol.replace("-", ".")


def clear() -> None:
    """Forget the rate window, the cooldown and the memo (tests, a rotated key)."""
    global _blocked_until
    with _lock:
        _sent.clear()
        _blocked_until = 0.0
        _memo.clear()


def room() -> int:
    """Requests the minute's allowance still has (0 in a cooldown or keyless)."""
    if not has_key():
        return 0
    now = time.monotonic()
    with _lock:
        if now < _blocked_until:
            return 0
        return max(0, PER_MINUTE - sum(1 for t in _sent if now - t < 60))


def _take() -> bool:
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


def _block(seconds: float, why: str, status: int) -> None:
    global _blocked_until
    with _lock:
        _blocked_until = max(_blocked_until, time.monotonic() + seconds)
    obs.warn(f"twelvedata.{why}", status=status)


def _refusal(code: int) -> None:
    """Open the cooldown a refusal calls for; other codes are one name's loss."""
    if code == 429:
        _block(THROTTLED_S, "throttled", code)
    elif code in (401, 403):
        _block(REJECTED_S, "rejected", code)


def _frame(body: dict) -> pd.DataFrame | None:
    """`body` as a Yahoo-shaped daily frame, None when it is not a US answer."""
    meta = body.get("meta") or {}
    if (meta.get("currency"), meta.get("exchange_timezone")) != (
        "USD",
        "America/New_York",
    ):
        return None
    rows = body.get("values")
    if not isinstance(rows, list) or not rows:
        return None
    df = pd.DataFrame(rows)
    if "datetime" not in df or "close" not in df:
        return None
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("datetime")), name="Date")
    cols = {k: v for k, v in _COLUMNS.items() if k in df}
    out = df[list(cols)].apply(pd.to_numeric, errors="coerce").rename(columns=cols)
    out["Adj Close"] = out["Close"]
    out["Volume"] = (
        pd.to_numeric(df["volume"], errors="coerce") if "volume" in df else float("nan")
    )
    out = out.sort_index().dropna(subset=["Close"])
    out = out[out["Close"] > 0]
    if out.empty:
        return None
    out.attrs["source"] = SOURCE
    return out


def _one(symbol: str, start: str, adjust: str, key: str) -> pd.DataFrame | None:
    memo_key = (symbol, start, adjust)
    with _lock:
        hit = _memo.get(memo_key)
    if hit is not None and time.monotonic() - hit[0] < TTL_S:
        return None if hit[1] is None else hit[1].copy()
    if not _take():
        return None
    params: dict[str, object] = {
        "symbol": spelling(symbol),
        "interval": "1day",
        "outputsize": MAX_ROWS,
        "adjust": adjust,
        "apikey": key,
    }
    if start:
        params["start_date"] = start
    try:
        body = get_json(
            f"{API_ROOT}?{urllib.parse.urlencode(params)}", timeout=TIMEOUT_S
        )
    except urllib.error.HTTPError as exc:
        _refusal(exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 — a fallback is never fatal
        obs.event("twelvedata.failed", symbol=symbol, error=type(exc).__name__)
        return None
    # Errors can also arrive as a 200 with a body of {"code": …, "status": "error"}.
    if body.get("status") == "error":
        code = int(body.get("code") or 0)
        _refusal(code)
        if code in (400, 404):  # not on the free plan / no such symbol
            with _lock:
                _memo[memo_key] = (time.monotonic(), None)
        return None
    df = _frame(body)
    if df is None:
        obs.event("twelvedata.unusable", symbol=symbol)
        with _lock:  # a wrong-venue answer is a verdict on the code, not a blip
            _memo[memo_key] = (time.monotonic(), None)
        return None
    with _lock:
        _memo[memo_key] = (time.monotonic(), df)
    return df.copy()


def daily(
    symbols: list[str], days: int | None = None, *, auto_adjust: bool = False
) -> dict[str, pd.DataFrame]:
    """Daily bars for the US `symbols` Twelve Data can answer, keyed as given.

    `days` is the lookback (None: as far back as a request goes). Names the
    plan does not cover, a missing key, a spent allowance or a cooldown simply
    leave a name out. `auto_adjust` asks for dividend-adjusted closes too;
    otherwise only splits are folded in.
    """
    key = api_key()
    asked = [s for s in dict.fromkeys(symbols) if covers(s)]
    if key is None or not asked:
        return {}
    start = (date.today() - timedelta(days=days + 5)).isoformat() if days else ""
    adjust = "all" if auto_adjust else "splits"
    with ThreadPoolExecutor(min(WORKERS, len(asked))) as pool:
        frames = list(pool.map(lambda s: _one(s, start, adjust, key), asked))
    out = {s: f for s, f in zip(asked, frames, strict=True) if f is not None}
    if out:
        obs.event("twelvedata.daily", asked=len(asked), answered=len(out))
    return out


def close_on(symbol: str, day: str) -> float | None:
    """Split-adjusted close on `day` or the last session before it, or None."""
    frames = daily([symbol], days=(date.today() - date.fromisoformat(day)).days + 15)
    df = frames.get(symbol)
    if df is None:
        return None
    series = df["Close"][df.index <= pd.Timestamp(day)]
    return float(series.iloc[-1]) if not series.empty else None
