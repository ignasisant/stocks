"""Finnhub client — the US line that stays up when Yahoo throttles us.

Yahoo throttles Cloud Run's shared egress IPs, and while `data.fetch`'s
cooldown is open `data.quotes` has nothing to say: the day-change column goes
blank for the whole book. Finnhub's free plan answers `/quote` in real time for
US listings at 60 requests a minute, which covers a book in one pass. It covers
nothing else — a European or Asian listing is a paid-plan feature — so this is
a fallback for US symbols only, never a second source for everything.

Three more reads ride on the same key and the same allowance, each a single
request where Yahoo or EDGAR cost one per name:

* the **earnings calendar** (`earnings_window`): every US print in a span of
  days, with the EPS estimate and, once reported, the actual. A book's worth
  of dates in a handful of requests instead of two Yahoo calls per name;
* the **market status** (`us_session`): whether New York is open, in its
  pre- or post-market, or shut for a holiday — from the exchange's own
  clock rather than a weekday-and-hours table;
* the **insider feed** (`insider_transactions`): the Form 4 lines of a US
  filer in one answer, where EDGAR is a document per filing.

Optional, like FMP: the key is `FINNHUB_API_KEY` or `[finnhub] api_key` in the
secrets file. Without one every call returns nothing and callers carry on with
what Yahoo gave them.

The quote is shaped as a Yahoo v7 quote row so `analysis.portfolio._snapshot`
reads it without knowing who fetched it. Finnhub's free quote has no extended
hours, so the row carries no `marketState`: it reads as the regular session —
live while the market trades, the last completed session once it closes.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.parse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, timedelta

from stocks import obs
from stocks.data.http import get_json
from stocks.secrets_env import secret

API_ROOT = "https://finnhub.io/api/v1"
QUOTE_URL = API_ROOT + "/quote?symbol={symbol}"

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

# The calendar answers at most this many rows and silently cuts the span
# short past them (measured 2026-10-22: a fortnight in reporting season came
# back 1500 rows that ended days early). A span answering that many is split
# in two and asked again, down to a single day — the busiest day measured
# was 352 rows, so a day never hits the page.
CALENDAR_PAGE = 1500
# Days per calendar request before any split: a quiet fortnight is one
# request, and a reporting-season one lands under the page.
CALENDAR_CHUNK_DAYS = 10

# The one whole-market read every earnings caller shares: back far enough for
# the last print of every name (a quarter, with slack), forward past the next
# one. Six hours, like the API's memo of the answer; a failed read is tried
# again after ten minutes rather than on every caller.
WINDOW_BACK_DAYS = 90
WINDOW_AHEAD_DAYS = 100
WINDOW_TTL_S = 6 * 3600.0
WINDOW_RETRY_S = 600.0

# The market clock: a minute, like the exchange's own transitions, and a read
# that failed keeps the last answer for a few minutes before saying nothing.
STATUS_TTL_S = 60.0
STATUS_KEEP_S = 300.0

# What a US listing looks like as a Yahoo symbol: bare letters, optionally a
# share class (BRK-B). A suffix (.MC, .L), an index (^GSPC), a currency (EUR=X)
# or a crypto pair (BTC-EUR) is somewhere Finnhub's free plan does not go.
_US_SYMBOL = re.compile(r"[A-Z]{1,5}(-[A-Z]{1,2})?")

_lock = threading.Lock()
_sent: deque[float] = deque()
_blocked_until = 0.0

# (monotonic when read, the day it was read for, the answer or None).
_window: tuple[float, date | None, dict[str, list[dict]] | None] = (0.0, None, None)
_window_lock = threading.Lock()

# (monotonic when last asked, monotonic when the answer landed, the answer).
# Never asked is -inf, not 0.0: the monotonic clock counts from boot, and a
# runner a minute old would read 0.0 as "asked just now".
_NEVER = float("-inf")
_status: tuple[float, float, dict | None] = (_NEVER, _NEVER, None)
_status_lock = threading.Lock()
_status_flight = False


def api_key() -> str | None:
    return secret("FINNHUB_API_KEY", "finnhub", "api_key") or None


def has_key() -> bool:
    return api_key() is not None


def covers(symbol: str) -> bool:
    """Whether `symbol` (a Yahoo symbol) is a US listing Finnhub's free plan quotes."""
    return bool(_US_SYMBOL.fullmatch(symbol))


def spelling(symbol: str) -> str:
    """Finnhub's spelling of a Yahoo symbol: the share class after a dot (BRK.B)."""
    return symbol.replace("-", ".")


def clear() -> None:
    """Forget the rate window, any cooldown and the memos (tests, a rotated key)."""
    global _blocked_until, _window, _status, _status_flight
    with _lock:
        _sent.clear()
        _blocked_until = 0.0
    with _window_lock:
        _window = (0.0, None, None)
    with _status_lock:
        _status = (_NEVER, _NEVER, None)
        _status_flight = False


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


def _refused(code: int) -> None:
    """Open the cooldown a refusal calls for. Any other status is one
    request's loss and nothing to remember."""
    if code == 429:
        _block(THROTTLED_S)
        obs.warn("finnhub.throttled")
    elif code in (401, 403):
        _block(REJECTED_S)
        obs.warn("finnhub.rejected", status=code)


def _fetch(symbol: str, key: str, timeout: float) -> dict:
    """Finnhub's raw `/quote` body for one symbol (its spelling: BRK.B)."""
    return get_json(
        QUOTE_URL.format(symbol=symbol),
        timeout=timeout,
        # In a header rather than `?token=`, so the key never lands in a URL
        # that an error message or a proxy log repeats.
        headers={"X-Finnhub-Token": key},
    )


def _get(path: str, params: dict[str, object], key: str, timeout: float) -> dict:
    """Finnhub's raw body for `path` (under the v1 root) asked with `params`."""
    return get_json(
        f"{API_ROOT}/{path}?{urllib.parse.urlencode(params)}",
        timeout=timeout,
        headers={"X-Finnhub-Token": key},  # see `_fetch`
    )


def _ask(
    path: str, params: dict[str, object], *, timeout: float, what: str
) -> dict | None:
    """One request from the allowance; None without a key, past the minute's
    allowance or a cooldown, or when Finnhub did not answer (a refusal opens
    the cooldown the way a quote's does)."""
    key = api_key()
    if key is None or not _take():
        return None
    try:
        body = _get(path, params, key, timeout)
    except urllib.error.HTTPError as exc:
        _refused(exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 — a side read is never fatal
        obs.event(f"finnhub.{what}_failed", error=type(exc).__name__)
        return None
    return body if isinstance(body, dict) else None


# ------------------------------------------------------------------- quotes
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
        body = _fetch(spelling(symbol), key, timeout)
    except urllib.error.HTTPError as exc:
        _refused(exc.code)
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


# ---------------------------------------------------------- earnings calendar
def _calendar_rows(start: date, end: date, timeout: float) -> list[dict] | None:
    """The calendar's rows from `start` to `end` inclusive; None unanswered."""
    body = _ask(
        "calendar/earnings",
        {"from": start.isoformat(), "to": end.isoformat()},
        timeout=timeout,
        what="earnings",
    )
    if body is None:
        return None
    rows = body.get("earningsCalendar")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict)]


def _chunks(start: date, end: date, days: int) -> list[tuple[date, date]]:
    spans: list[tuple[date, date]] = []
    while start <= end:
        stop = min(start + timedelta(days=days - 1), end)
        spans.append((start, stop))
        start = stop + timedelta(days=1)
    return spans


def earnings_calendar(
    start: date, end: date, *, timeout: float = 10.0
) -> dict[str, list[dict]] | None:
    """Every print Finnhub lists from `start` to `end` inclusive, as
    `{symbol: [rows]}` in its spelling (BRK.B), each row as the API gives it:
    `date`, `hour` (bmo/amc), `epsEstimate`, `epsActual`, `revenueEstimate`,
    `revenueActual`, `quarter`, `year`.

    Whole-market windows only: asked for one symbol, the free plan answers
    its future dates alone, while a span carries the past prints' actuals.
    The span goes out in `CALENDAR_CHUNK_DAYS` slices at once, and any slice
    the page cut short is halved and asked again. None when a slice went
    unanswered — a window with a hole would read as "no print" for every
    name in it, which a caller must not take for an answer.
    """
    if api_key() is None or end < start:
        return None
    out: dict[str, list[dict]] = {}
    failed = False
    requests = 0
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    with obs.timed("finnhub.earnings", days=(end - start).days + 1) as rec:
        try:
            pending = {
                pool.submit(_calendar_rows, a, b, timeout): (a, b)
                for a, b in _chunks(start, end, CALENDAR_CHUNK_DAYS)
            }
            while pending and not failed:
                done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                for future in done:
                    a, b = pending.pop(future)
                    requests += 1
                    rows = future.result()
                    if rows is None:
                        failed = True
                        break
                    if len(rows) >= CALENDAR_PAGE and a < b:
                        mid = a + (b - a) // 2
                        for span in ((a, mid), (mid + timedelta(days=1), b)):
                            pending[pool.submit(_calendar_rows, *span, timeout)] = span
                        continue
                    if len(rows) >= CALENDAR_PAGE:
                        obs.warn("finnhub.earnings_page", day=a.isoformat())
                    for row in rows:
                        symbol = str(row.get("symbol") or "")
                        if symbol:
                            out.setdefault(symbol, []).append(row)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        rec["requests"] = requests
        rec["symbols"] = len(out)
        if failed:
            rec["failed"] = True
    return None if failed else out


def earnings_window(ref: date | None = None) -> dict[str, list[dict]] | None:
    """The calendar around `ref` (today) — `WINDOW_BACK_DAYS` back,
    `WINDOW_AHEAD_DAYS` ahead — read once per process per day and kept
    `WINDOW_TTL_S`; None without a key or while the read keeps failing.

    One lock around the read: callers landing together wait for the one
    answer rather than each spending the allowance on their own.
    """
    global _window
    if api_key() is None:
        return None
    ref = ref or date.today()
    with _window_lock:
        read_at, read_for, rows = _window
        ttl = WINDOW_TTL_S if rows is not None else WINDOW_RETRY_S
        if read_for == ref and time.monotonic() - read_at < ttl:
            return rows
        rows = earnings_calendar(
            ref - timedelta(days=WINDOW_BACK_DAYS),
            ref + timedelta(days=WINDOW_AHEAD_DAYS),
        )
        _window = (time.monotonic(), ref, rows)
        return rows


# -------------------------------------------------------------- market clock
_SESSIONS = {"pre-market": "pre", "regular": "regular", "post-market": "post"}


def _session_of(body: dict) -> dict | None:
    """Finnhub's `/stock/market-status` body as `{open, session, holiday}`.

    `session` is "pre", "regular" or "post" while one is on and None when the
    exchange is shut; `holiday` names the day when that is why.
    """
    if "isOpen" not in body:
        return None
    raw = str(body.get("session") or "").lower()
    holiday = body.get("holiday")
    return {
        "open": bool(body.get("isOpen")),
        "session": _SESSIONS.get(raw),
        "holiday": str(holiday) if holiday else None,
    }


def _refresh_status(timeout: float) -> None:
    global _status, _status_flight
    body = _ask("stock/market-status", {"exchange": "US"}, timeout=timeout, what="status")
    answer = _session_of(body) if body else None
    now = time.monotonic()
    with _status_lock:
        _, landed_at, last = _status
        if answer is not None:
            _status = (now, now, answer)
        else:
            kept = last if now - landed_at < STATUS_KEEP_S else None
            _status = (now, landed_at, kept)
        _status_flight = False


def us_session(*, timeout: float = 4.0, sync: bool = False) -> dict | None:
    """What Finnhub says of the US session right now, or None.

    `{"open": bool, "session": "pre" | "regular" | "post" | None,
    "holiday": str | None}`, a minute old at most. Refreshed off the caller's
    thread: a call past the minute hands back the last answer and asks again
    in the background, so a page is never held on Finnhub's clock. None
    without a key, before the first answer lands, or once a failed read is
    `STATUS_KEEP_S` old — and then the time-table clock decides. `sync` waits
    for the answer instead (a test, the CLI).
    """
    global _status_flight
    if api_key() is None:
        return None
    with _status_lock:
        asked_at, _, answer = _status
        if time.monotonic() - asked_at < STATUS_TTL_S or _status_flight:
            return answer
        _status_flight = True
    if sync:
        _refresh_status(timeout)
        with _status_lock:
            return _status[2]
    threading.Thread(
        target=_refresh_status, args=(timeout,), name="finnhub-status", daemon=True
    ).start()
    return answer


# ---------------------------------------------------------------- insiders
def insider_transactions(
    symbol: str, start: date, end: date, *, timeout: float = 6.0
) -> list[dict] | None:
    """Finnhub's Form 4 lines for `symbol` (its spelling) with a transaction
    date from `start` to `end`, each row as the API gives it: `name`,
    `transactionDate`, `filingDate`, `transactionCode`, `change` (signed
    shares), `transactionPrice`, `isDerivative`. None when it was not asked
    or not answered — the caller then reads EDGAR as before.
    """
    body = _ask(
        "stock/insider-transactions",
        {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()},
        timeout=timeout,
        what="insiders",
    )
    if body is None:
        return None
    rows = body.get("data")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict)]
