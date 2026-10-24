"""Daily closes for many symbols from Yahoo's spark endpoint — twenty a request.

A book's refresh used to ask `yf.download(period="1mo")` for its last month:
one chart request per symbol, eight at a time, about fifty for a book. That
burst is what Yahoo answers with 429 from a datacenter IP, and what spent a
refresh's whole budget on the throttled vCPU. Spark carries the same daily
closes for up to twenty symbols in one request (more is a 400), so the same
book is three requests and well under a second each.

What it does not carry: Open, High, Low, Volume, or the dividend-adjusted
close — its `close` is chart's printed close. So it extends a book's frames
(`fetch.fetch_tail`), and the chart download that does carry those runs once a
day (`loaders._held_frames`' rebase), not on every refresh.

The v7 shape is the one used: unlike v8 it names each symbol's exchange time
zone, and a daily bar's timestamp is its session's open — 23:00 UTC the day
before, for Sydney — so the date is only right read in the exchange's zone.

Like `data.quotes`, this borrows yfinance's authenticated session (`YfData`)
and shares the host's one throttle verdict (`fetch.trip_throttle`).
"""

from __future__ import annotations

import time

import pandas as pd
from yfinance.exceptions import YFRateLimitError

from stocks import obs, progress
from stocks.analysis import naive_dates
from stocks.data.fetch import (
    failure_kind,
    reset_crumb,
    throttle_remaining,
    trip_throttle,
)
from stocks.frames import midnights

SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"

# Symbols per request: Yahoo answers twenty and refuses twenty-five with a
# bare 400 (measured 2026-10-13).
CHUNK = 20

# Per-request and whole-call wall clock. A refresh runs behind a served
# answer, but a hung request still holds the book's refresh open.
TIMEOUT = 10.0
BUDGET_S = 30.0


def _fetch(symbols: list[str], range_: str, timeout: float) -> list[dict]:
    """Raw spark entries for `symbols`. Symbols Yahoo does not know are
    simply absent."""
    from yfinance.data import YfData

    raw = YfData().get_raw_json(
        SPARK_URL,
        params={"symbols": ",".join(symbols), "range": range_, "interval": "1d"},
        timeout=timeout,
    )
    rows = ((raw or {}).get("spark") or {}).get("result") or []
    return [r for r in rows if isinstance(r, dict)]


def _series(entry: dict) -> pd.Series | None:
    """One entry's daily closes on naive exchange dates, or None when the
    entry carries none."""
    responses = entry.get("response") or []
    if not responses or not isinstance(responses[0], dict):
        return None
    resp = responses[0]
    stamps = resp.get("timestamp") or []
    quote = ((resp.get("indicators") or {}).get("quote") or [{}])[0] or {}
    closes = quote.get("close") or []
    if not stamps or len(stamps) != len(closes):
        return None
    when = pd.to_datetime(stamps, unit="s", utc=True)
    zone = (resp.get("meta") or {}).get("exchangeTimezoneName")
    if zone:
        try:
            when = when.tz_convert(zone)
        except Exception:  # noqa: BLE001 — an unknown zone reads in UTC
            pass
    index = naive_dates(midnights(when)).rename("Date")
    series = pd.Series(pd.to_numeric(closes, errors="coerce"), index=index, dtype=float)
    series = series.dropna()
    # A session still trading can repeat its day.
    series = series[~series.index.duplicated(keep="last")]
    return series if not series.empty else None


def _ask(chunk: list[str], range_: str, deadline: float) -> list[dict]:
    """One chunk's entries. A stale crumb gets one fresh one and one more
    try; anything else Yahoo does is a refusal (`YFRateLimitError`), and only
    a throttle opens the cooldown."""
    for again in (True, False):
        left = deadline - time.monotonic()
        if left <= 0:
            obs.warn("yahoo.spark.budget_spent", symbols=len(chunk))
            raise YFRateLimitError()
        try:
            return _fetch(chunk, range_, min(TIMEOUT, left))
        except Exception as exc:  # noqa: BLE001 — classified below
            kind = failure_kind(exc)
            obs.warn(
                "yahoo.spark.failed", symbols=len(chunk), kind=kind, error=repr(exc)[:300]
            )
            if kind == "throttle":
                trip_throttle()
                raise YFRateLimitError() from exc
            if kind == "crumb" and again:
                reset_crumb()
                continue
            raise YFRateLimitError() from exc
    raise YFRateLimitError()


def closes(
    symbols: list[str],
    range_: str = "1mo",
    *,
    chunk: int = CHUNK,
    budget: float = BUDGET_S,
) -> dict[str, pd.Series]:
    """`{symbol: daily close}` for Yahoo `symbols` (resolved, not broker codes).

    Symbols Yahoo has nothing for are absent. All or nothing: a chunk Yahoo
    would not answer raises `YFRateLimitError`, which is what every price
    caller already degrades on — a half-refreshed book would read as a book
    whose missing names stopped trading.
    """
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return {}
    if (cooling := throttle_remaining()) > 0:
        obs.event("yahoo.cooling_off", remaining_s=round(cooling, 1), via="spark")
        raise YFRateLimitError()
    deadline = time.monotonic() + budget
    out: dict[str, pd.Series] = {}
    with obs.timed("yahoo.spark", symbols=len(symbols)) as rec:
        for i in range(0, len(symbols), chunk):
            batch = symbols[i : i + chunk]
            for entry in _ask(batch, range_, deadline):
                symbol = str(entry.get("symbol") or "")
                series = _series(entry)
                if symbol and series is not None:
                    out[symbol] = series.rename(symbol)
            # The corner banner counts these: a book's refresh is a few
            # chunks, and each one landing is the bar moving.
            progress.tick(len(batch))
        rec["series"] = len(out)
    return out


def names(symbols: list[str], *, budget: float = TIMEOUT) -> dict[str, str]:
    """`{symbol: company name}`, from the meta of the same spark request.

    Twenty listings named in one request, where `.info` is one each — the
    difference between a peer list that reads "Nintendo Co., Ltd." and one
    that reads "7974.T". Symbols Yahoo does not know, or names it gives
    none for, are absent.

    Never raises, unlike `closes`: a name is a label beside a symbol, and
    no label is a page that still works. Empty while the host is cooling off.
    """
    symbols = list(dict.fromkeys(symbols))
    if not symbols or throttle_remaining() > 0:
        return {}
    deadline = time.monotonic() + budget
    out: dict[str, str] = {}
    try:
        for i in range(0, len(symbols), CHUNK):
            for entry in _ask(symbols[i : i + CHUNK], "1d", deadline):
                responses = entry.get("response") or [{}]
                first = responses[0] if isinstance(responses[0], dict) else {}
                meta = first.get("meta")
                meta = meta if isinstance(meta, dict) else {}
                name = str(meta.get("longName") or meta.get("shortName") or "").strip()
                symbol = str(entry.get("symbol") or "")
                if symbol and name:
                    out[symbol] = name
    except YFRateLimitError:
        pass
    return out
