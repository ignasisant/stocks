"""Fetch OHLCV price data via yfinance; cache to CSV under data/."""

from __future__ import annotations

import ast
import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from urllib.error import HTTPError

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from stocks import obs
from stocks.analysis import naive_dates
from stocks.config import DATA_DIR, ticker_aliases
from stocks.data import profiles
from stocks.data.crypto import COINGECKO_IDS, split_pair
from stocks.data.fx import rates_range
from stocks.data.http import get_json
from stocks.data.symbols import code_symbol

# ---------------------------------------------------------------- the breaker
# One verdict about Yahoo for the whole process, because there is only one
# thing it can be angry at: this host's egress IP. Without it every caller
# rediscovers the throttle on its own and pays the full `retry` ladder to do
# it — and yfinance itself charges three or four round trips for a rejected
# request (it re-mints the cookie and crumb, flips its cookie strategy and
# replays the call). A Home render is ~50 symbols; one throttled Yahoo used to
# cost the page all of that, on every render.
#
# 300s is `data.symbols.COOLDOWN`, for the same reason it picked it: long
# enough that the host stops making the throttle worse, short enough that a
# transient one clears without anybody noticing.
COOLDOWN_S = 300.0
_blocked_until = 0.0
_throttle_lock = threading.Lock()


def throttle_remaining() -> float:
    """Seconds left on the cooldown, 0.0 when Yahoo may be asked again."""
    with _throttle_lock:
        return max(0.0, _blocked_until - time.monotonic())


def trip_throttle(cooldown: float = COOLDOWN_S) -> None:
    """Declare this host throttled for `cooldown` seconds."""
    global _blocked_until
    with _throttle_lock:
        _blocked_until = max(_blocked_until, time.monotonic() + cooldown)


def clear_throttle() -> None:
    """Forget the cooldown — for tests, and for anything that wants the next
    read to actually go to Yahoo."""
    global _blocked_until
    with _throttle_lock:
        _blocked_until = 0.0


def retry[T](fn: Callable[[], T], attempts: int = 3, base_delay: float = 1.5) -> T:
    """Run fn, retrying on Yahoo's 429 with exponential backoff (1.5s, 3s).

    Public because it is the whole discipline: any module that talks to Yahoo
    goes through here, or it rediscovers the throttle on this host's behalf and
    deepens it (`data.fundamentals` used to, and a sector scan is two hundred
    companies' worth of that mistake).

    Hosted deploys hit Yahoo from datacenter IPs, so transient rate limits
    are routine; a short backoff usually clears them. The final attempt re-raises so
    callers (the app-level guard) can degrade gracefully.

    Once that ladder has been climbed and lost, the cooldown opens and the next
    call raises `YFRateLimitError` without touching the network at all. Callers
    already handle that exception — it is what the "prices unavailable" cards
    are made of — so a throttled window now costs a page one instant
    degradation instead of one slow one per block.
    """
    if throttle_remaining() > 0:
        obs.event("yahoo.cooling_off", remaining_s=round(throttle_remaining(), 1))
        raise YFRateLimitError()
    for i in range(attempts - 1):
        try:
            return fn()
        except YFRateLimitError:
            # How often the host is throttled — and whether the backoff clears
            # it — is the difference between "Yahoo is flaky today" and "this
            # deploy's egress IP is burnt". Neither is visible from the UI.
            obs.warn("yahoo.rate_limited", attempt=i + 1, attempts=attempts)
            time.sleep(base_delay * 2**i)
    try:
        return fn()
    except YFRateLimitError:
        trip_throttle()
        obs.warn(
            "yahoo.rate_limit_exhausted", attempts=attempts, cooldown_s=COOLDOWN_S
        )
        raise


# Wall clock for one bulk download. Fifty symbols over two years measures ~6s
# warm, so this is ten times the honest cost: it is here to catch a hang, not
# to hurry a slow day.
BULK_BUDGET_S = 60.0

# Concurrent requests inside one bulk download. yfinance's default is
# `cpu_count() * 2`, which on the 1-vCPU Cloud Run service is two: a 34-name
# watchlist became seventeen sequential round-trips, and with Yahoo timing
# out at 10s each that alone overran the budget above. The work is network
# wait, not CPU, so the host's core count is the wrong dial — fix it here.
DOWNLOAD_THREADS = 8


def _budgeted[T](fn: Callable[[], T], *, budget: float, **fields) -> T:
    """Run `fn` on a worker and give up on it after `budget` seconds.

    No `with` on the pool: `shutdown(wait=True)` would block on exactly the
    hung call the timeout just escaped, which is how the budget gets defeated.
    The abandoned thread finishes into nothing (yfinance bounds each request,
    so it does terminate) — the same trade `chat.market.quotes` makes.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=budget)
    except FuturesTimeout:
        obs.warn("yahoo.bulk_budget_spent", budget_s=budget, **fields)
        raise YFRateLimitError() from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# --------------------------------------------- what a bulk download said
# `yf.download` never raises for one symbol. It files each reason away and,
# once the batch is done, logs a summary on the thread that called it — one
# line per reason, "['SIE', 'OZTA']: No data found, symbol may be delisted" or
# "['AAPL']: YFRateLimitError('Too Many Requests. Rate limited. …')". That
# summary is the only place the two part ways, and they must: a symbol Yahoo
# says it has never heard of is a fact about the book, a refused one is
# weather. Read as a filter, not a handler, so it hears the line whatever the
# logging setup does with it afterwards, and changes nothing about where it
# goes.
_SUMMARY_RE = re.compile(r"^(\[[^\]]*\]): (.*)$", re.S)
_download_log = threading.local()

# Yahoo's own words for a chart it has no symbol for — its 404 reason, which
# yfinance passes through verbatim. Not the generic "no price data found" nor
# "no timezone found": yfinance says those on its own, and a throttled Yahoo
# has been seen to produce the second.
UNLISTED_REASON = "no data found"
_REFUSED_RE = re.compile(r"YFRateLimitError|Too Many Requests", re.I)


class _DownloadFailures(logging.Filter):
    """File each summary line into the calling thread's sink, if it set one."""

    def filter(self, record: logging.LogRecord) -> bool:
        sink = getattr(_download_log, "sink", None)
        if sink is None:
            return True
        m = _SUMMARY_RE.match(record.getMessage())
        if m is None:
            return True
        try:
            symbols = ast.literal_eval(m.group(1))
        except (ValueError, SyntaxError):
            return True
        for symbol in symbols:
            if isinstance(symbol, str):
                sink[symbol.upper()] = m.group(2).strip()
        return True


logging.getLogger("yfinance").addFilter(_DownloadFailures())

# Tickers (as requested) that the last bulk download asking for them was told
# Yahoo has no such symbol. One verdict per process, like the breaker: the
# answer is about the symbol, not about who asked. Rewritten by every download
# that includes the name, so one that starts pricing leaves on its own.
_unlisted: set[str] = set()
_unlisted_lock = threading.Lock()


def unlisted(tickers) -> set[str]:
    """Those of `tickers` Yahoo last said it has no symbol for."""
    with _unlisted_lock:
        return _unlisted & set(tickers)


def relisted(ticker: str) -> None:
    """Drop the verdict on `ticker`: it has just been mapped to a line Yahoo
    does list, and the next download asks that one."""
    with _unlisted_lock:
        _unlisted.discard(ticker)


def clear_unlisted() -> None:
    """Forget every verdict — for tests."""
    with _unlisted_lock:
        _unlisted.clear()


def _note_failures(
    tickers: list[str],
    symbol_of: dict[str, str],
    priced: dict[str, pd.DataFrame],
    failures: dict[str, str],
) -> None:
    """Record which unpriced names Yahoo disowned, and say when it refused."""
    refused = sorted(s for s, why in failures.items() if _REFUSED_RE.search(why))
    if refused:
        # Not the breaker: yfinance already spent its own retries on these,
        # and a partial refusal is `complete_download`'s call, not ours.
        obs.warn(
            "yahoo.bulk_refused",
            refused=len(refused),
            symbols=len(set(symbol_of.values())),
        )
    newly: list[str] = []
    with _unlisted_lock:
        for t in tickers:
            why = failures.get(symbol_of[t].upper(), "")
            if t not in priced and why.lower().startswith(UNLISTED_REASON):
                if t not in _unlisted:
                    newly.append(t)
                _unlisted.add(t)
            else:
                _unlisted.discard(t)
    if newly:
        obs.warn("yahoo.unlisted", tickers=sorted(newly))


def resolve(ticker: str) -> str:
    """Yahoo Finance symbol for a ticker (identity when unmapped).

    Broker codes map through watchlist.yaml `aliases` first — the hand-written
    answer wins — then through the codes an import resolved with Yahoo's
    search (`symbols.code_symbol`: SIE -> SIE.DE). Both are local reads.
    """
    key = ticker.upper()
    return ticker_aliases().get(key) or code_symbol(key) or ticker


# `.info` is the heaviest call yfinance makes — a full quoteSummary — and it
# used to be fetched independently by everything that wanted one field of it:
# the allocation profile (sector/country/currency), the session quote
# (pre/post prices), the fund classifier (quoteType), the logo resolver
# (website) and the earnings currency. One ticker on one page render could
# pay for it three to five times over, and that pile of requests is what
# trips Yahoo's rate limiter from a datacenter IP.
#
# The TTL is deliberately short. The same blob carries both facts that never
# move (sector, country) and facts that move by the second (premarket price),
# so it is pinned to the faster of the two — the point is to collapse the
# several calls *within one render*, not to hold quotes. The API's own
# `ttl_cache` wrappers (api/cache.py) still bound how often a render happens.
_INFO_TTL_S = 120.0
_info_memo: dict[str, tuple[float, dict]] = {}
_info_lock = threading.Lock()


def clear_info_cache() -> None:
    """Forget every memoized `.info` blob.

    For tests that swap yfinance out between assertions, and for anything that
    wants the next read to go to the network — a memo hit doesn't see a
    patched `yfinance.Ticker`, and within the TTL it doesn't see a new quote.
    """
    with _info_lock:
        _info_memo.clear()


def info(ticker: str) -> dict:
    """Yahoo's quote/profile blob for `ticker` (yfinance `.info`), memoized.

    Returns {} when Yahoo has nothing (or hands back a non-dict). Errors are
    not memoized and propagate — callers decide whether a missing profile is
    fatal (`data.earnings` re-raises a rate limit) or cosmetic (`data.logo`
    swallows everything). Safe to call from a thread pool: entries are shared
    under a lock, so a `load_meta` fan-out over one ticker fetches once.
    """
    key = resolve(ticker)
    now = time.monotonic()
    with _info_lock:
        hit = _info_memo.get(key)
        if hit is not None and now - hit[0] < _INFO_TTL_S:
            return hit[1]
    fetched = yf.Ticker(key).info
    blob = fetched if isinstance(fetched, dict) else {}
    # The facts in it that never move (sector, country, currency, quoteType)
    # go to the on-disk profile memo, so the allocation splits stop paying a
    # quoteSummary per holding on every cold process (stocks.data.profiles).
    profiles.remember(key, blob)
    with _info_lock:
        _info_memo[key] = (time.monotonic(), blob)
        # Bounded: a long-lived server would otherwise accumulate an entry per
        # symbol anyone ever looked at. Evicting the expired ones is enough —
        # the live set is one page's worth of tickers.
        if len(_info_memo) > 512:
            cutoff = time.monotonic() - _INFO_TTL_S
            for stale in [k for k, (at, _) in _info_memo.items() if at < cutoff]:
                del _info_memo[stale]
    return blob


# Corporate splits, memoized for the life of the process: a split that
# happened is a fact that never changes, and the one caller (import
# validation, when a sell overshoots its position) asks about one symbol at a
# time. A throttled or unreachable Yahoo answers "no splits" rather than
# raising — the caller's fallback is the plain oversell error it would have
# shown anyway.
_splits_memo: dict[str, list[tuple[str, float]]] = {}
_splits_lock = threading.Lock()


def splits(ticker: str) -> list[tuple[str, float]]:
    """[(YYYY-MM-DD, ratio), …] for `ticker`, oldest first; [] when unknown.

    Ratios are Yahoo's: 20.0 for a 20-for-1 forward split, 0.1 for a 1-for-10
    reverse one.
    """
    key = resolve(ticker)
    with _splits_lock:
        hit = _splits_memo.get(key)
    if hit is not None:
        return hit
    if throttle_remaining():
        return []
    try:
        series = yf.Ticker(key).splits
    except YFRateLimitError:
        trip_throttle()
        obs.warn("yahoo.splits_rate_limited", ticker=key)
        return []
    except Exception as exc:
        obs.warn("yahoo.splits_failed", ticker=key, error=str(exc))
        return []
    events = [
        (str(pd.Timestamp(when).date()), float(ratio))
        for when, ratio in getattr(series, "items", lambda: [])()
        if ratio and float(ratio) > 0
    ]
    events.sort()
    with _splits_lock:
        _splits_memo[key] = events
    return events


# Split-adjusted closes on single past days, memoized like `splits` and for the
# same caller: the missing-split detector (stocks.portfolio.corporate) asks for
# one day per candidate, and only for a ticker that already has a candidate.
_close_memo: dict[tuple[str, str], float | None] = {}
_close_lock = threading.Lock()


def close_on(ticker: str, day: str) -> float | None:
    """Close on `day`, or the last session before it; None when Yahoo can't say.

    Split-adjusted and dividend-UNadjusted (auto_adjust=False), which is the
    scale ledger prices are compared against everywhere in this codebase
    (see portfolio.fees): a pre-split execution divided by this close gives
    the split factor the ledger is missing, and a dividend adjustment would
    blur that ratio by years of yield.
    """
    key = (resolve(ticker), day)
    with _close_lock:
        if key in _close_memo:
            return _close_memo[key]
    if throttle_remaining():
        return None  # not cached: a throttle is temporary, an answer is forever
    start = (pd.Timestamp(day) - pd.Timedelta(days=10)).date().isoformat()
    end = (pd.Timestamp(day) + pd.Timedelta(days=1)).date().isoformat()
    try:
        df = retry(
            lambda: yf.Ticker(key[0]).history(
                start=start, end=end, interval="1d", auto_adjust=False
            )
        )
    except YFRateLimitError:
        trip_throttle()
        obs.warn("yahoo.close_on_rate_limited", ticker=key[0])
        return None
    except Exception as exc:
        obs.warn("yahoo.close_on_failed", ticker=key[0], error=str(exc))
        return None
    close = None
    if df is not None and not df.empty and "Close" in df:
        series = df["Close"].dropna()
        series = series[series.index.map(lambda ts: str(pd.Timestamp(ts).date()) <= day)]
        if not series.empty:
            close = float(series.iloc[-1])
    with _close_lock:
        _close_memo[key] = close
    return close


def fetch_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Download OHLCV history for one ticker.

    The listing's first trading day rides along as `attrs["first_trade"]`
    (exchange-local ``YYYY-MM-DD``): Yahoo sends it in the same response as the
    bars, and it is what tells the price chart that a 2y range of a stock listed
    last spring would draw the same bars as "max".
    """
    handle = yf.Ticker(resolve(ticker))
    df = retry(lambda: handle.history(period=period, interval=interval))
    df.index.name = "Date"
    first = _first_trade(handle) if not df.empty else None
    if first:
        df.attrs["first_trade"] = first
    return df


def _first_trade(handle) -> str | None:
    """`firstTradeDate` from the metadata `history()` just stored, or None.

    Read only after a history call that returned rows: yfinance fills the
    metadata from that response, and asking before it fires a request of its
    own.
    """
    try:
        first = (handle.history_metadata or {}).get("firstTradeDate")
        return str(pd.Timestamp(first).date()) if first is not None else None
    except Exception:
        return None


def fetch_many(
    tickers: list[str],
    period: str = "1y",
    interval: str = "1d",
    auto_adjust: bool = True,
    budget: float = BULK_BUDGET_S,
) -> dict[str, pd.DataFrame]:
    """OHLCV history for many tickers in ONE bulk request (yf.download).

    Tickers with no data are absent from the result. Results are keyed by the
    ticker as requested (broker code), not the resolved Yahoo symbol. This is
    the shared bulk path for the updater, portfolio analytics and the
    dashboard picker. auto_adjust=False keeps dividend-unadjusted bars —
    needed when comparing against as-traded ledger prices (portfolio.fees).

    `budget` is the wall clock the whole download gets. yfinance bounds each
    *request* (10s) but not the set, and a page asks for ~50 symbols: a Yahoo
    that times out every one of them turned a Home render into a nineteen-
    minute one. Over budget raises `YFRateLimitError`, which every caller
    already degrades on — but it does NOT open the cooldown, because slow is
    not the same claim as refused, and the next request should try again.

    A name Yahoo answers "No data found" for is remembered as `unlisted`, so a
    caller judging whether the download was gutted can tell a book holding
    codes Yahoo does not know from a Yahoo that refused.
    """
    if not tickers:
        return {}
    # Hand-mapped coins skip Yahoo entirely: for some its symbol is another
    # coin, and an answer from the wrong asset never reaches the fallbacks.
    gecko = [t for t in tickers if (p := split_pair(t)) and p[0] in COINGECKO_IDS]
    tickers = [t for t in tickers if t not in gecko]
    if not tickers:
        return _coingecko_fallback(gecko, period, interval)
    symbol_of = {t: resolve(t) for t in tickers}
    symbols = list(dict.fromkeys(symbol_of.values()))
    failures: dict[str, str] = {}

    def download() -> pd.DataFrame:
        # On the thread yfinance logs its summary from — `_budgeted`'s worker,
        # not the caller. Cleared per attempt: only the one that returned counts.
        failures.clear()
        _download_log.sink = failures
        try:
            return yf.download(
                symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=auto_adjust,
                progress=False,
                threads=min(DOWNLOAD_THREADS, len(symbols)),
            )
        finally:
            _download_log.sink = None

    # The budget is OUTSIDE the retry ladder, not inside it: wrapped the other
    # way each of the three attempts would get its own 60s and a hung Yahoo
    # would cost three minutes plus the backoff — the budget has to bound the
    # whole thing, sleeps included.
    data = _budgeted(lambda: retry(download), budget=budget, symbols=len(symbols))
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            # Strip the ticker column level when there is one. Older yfinance
            # only added it for multi-symbol downloads, so this used to key off
            # the symbol count; 1.5.x adds it for a single symbol too, and the
            # count test then handed the caller a frame whose columns were
            # ('AAPL', 'Close') — every `df["Close"]` downstream silently found
            # nothing, so a one-name watchlist or a single-position book read as
            # unpriced. Ask the frame what shape it is instead.
            df = (
                data[symbol_of[t]]
                if isinstance(data.columns, pd.MultiIndex)
                else data
            )
        except KeyError:
            continue
        df = df.dropna(how="all")
        if not df.empty:
            df.index.name = "Date"
            out[t] = df
    missing = [t for t in tickers if t not in out]
    if missing:
        out.update(_crypto_usd_fallback(missing, period, interval, auto_adjust, budget))
    _note_failures(tickers, symbol_of, out, failures)
    if gecko:
        out.update(_coingecko_fallback(gecko, period, interval))
    return out


def _crypto_usd_fallback(
    tickers: list[str],
    period: str,
    interval: str,
    auto_adjust: bool,
    budget: float,
) -> dict[str, pd.DataFrame]:
    """Retry an unpriced EUR/GBP crypto pair on its USD one, FX-converted back.

    Yahoo's EUR/GBP crypto pairs only exist for major coins — a meme token a
    Revolut statement paired to EUR (`stocks.data.crypto.to_pair`) 404s there
    even though the USD pair, the one Yahoo actually maintains depth for,
    prices fine. Converting through the ECB daily rate keeps the series in the
    ledger's own quote currency, so nothing downstream has to know the coin
    was fetched at a different pair than the one it is held in.
    """
    pairs = {t: p for t in tickers if (p := split_pair(t)) and p[1] != "USD"}
    if not pairs:
        return {}
    usd_symbols = sorted({f"{coin}-USD" for coin, _ in pairs.values()})
    usd_frames = fetch_many(
        usd_symbols,
        period=period,
        interval=interval,
        auto_adjust=auto_adjust,
        budget=budget,
    )
    out: dict[str, pd.DataFrame] = {}
    for t, (coin, quote) in pairs.items():
        usd_df = usd_frames.get(f"{coin}-USD")
        if usd_df is None or usd_df.empty:
            continue
        converted = usd_df.copy()
        converted.index = naive_dates(converted.index)
        converted.index.name = "Date"
        start = converted.index.min().date().isoformat()
        end = converted.index.max().date().isoformat()
        fx = rates_range(start, end, "USD", quote)
        if not fx:
            continue
        rate = pd.Series(fx)
        rate.index = naive_dates(rate.index)
        rate = rate.reindex(converted.index).ffill().bfill()
        for col in ("Open", "High", "Low", "Close"):
            if col in converted:
                converted[col] = converted[col] * rate.to_numpy()
        out[t] = converted
        obs.event("yahoo.crypto_usd_fallback", ticker=t, via=f"{coin}-USD")
    return out


# CoinGecko's public API, no key: the last resort for a coin Yahoo has no
# pair for at all, not even -USD (MOODENG, at last check). Free-tier history
# is capped to the past year regardless of `days` asked for — a book older
# than that still carries its earliest stretch at cost.
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
    "?vs_currency={quote}&days={days}&interval=daily"
)
COINGECKO_MAX_DAYS = 365
_PERIOD_RE = re.compile(r"^(\d+)(d|mo|y)$")
_PERIOD_DAYS = {"d": 1, "mo": 30, "y": 365}

# The keyless tier allows a few dozen calls a minute per IP, and a Cloud Run
# egress IP is shared with everyone else's keyless calls: 429s arrive in
# bursts. Daily bars change once a day, so a quarter-hour memo costs nothing,
# and after a 429 the coins wait out what CoinGecko asked for (bounded — the
# header is advisory, and an hour-long pause would blank the coin for no gain).
GECKO_TTL_S = 900.0
GECKO_COOLDOWN_S = 60.0
_GECKO_WAIT_BOUNDS = (30.0, 600.0)
_gecko_memo: dict[str, tuple[float, pd.DataFrame]] = {}
_gecko_blocked_until = 0.0
_gecko_lock = threading.Lock()


def _gecko_hit(url: str) -> pd.DataFrame | None:
    with _gecko_lock:
        hit = _gecko_memo.get(url)
    if hit is None or time.monotonic() - hit[0] > GECKO_TTL_S:
        return None
    return hit[1].copy()


def _gecko_wait() -> float:
    with _gecko_lock:
        return max(0.0, _gecko_blocked_until - time.monotonic())


def _gecko_trip(retry_after: str | None) -> float:
    """Open CoinGecko's cooldown for its `Retry-After`, clamped; the seconds."""
    global _gecko_blocked_until
    try:
        wait = float(retry_after) if retry_after is not None else GECKO_COOLDOWN_S
    except ValueError:  # an HTTP date: not worth parsing for a hint
        wait = GECKO_COOLDOWN_S
    low, high = _GECKO_WAIT_BOUNDS
    wait = min(max(wait, low), high)
    with _gecko_lock:
        _gecko_blocked_until = max(_gecko_blocked_until, time.monotonic() + wait)
    return wait


def clear_coingecko() -> None:
    """Forget CoinGecko's memo and cooldown — for tests."""
    global _gecko_blocked_until
    with _gecko_lock:
        _gecko_memo.clear()
        _gecko_blocked_until = 0.0


def _period_days(period: str) -> int:
    """`period` ("1y", "37mo", "5d") as a day count, capped at the free
    tier's lookback — same d/mo/y shapes `stocks.analysis.portfolio` builds."""
    m = _PERIOD_RE.match(period)
    days = int(m.group(1)) * _PERIOD_DAYS[m.group(2)] if m else COINGECKO_MAX_DAYS
    return min(days, COINGECKO_MAX_DAYS)


def _coingecko_fallback(
    tickers: list[str], period: str, interval: str
) -> dict[str, pd.DataFrame]:
    """CoinGecko history for a pair whose coin is hand-mapped in
    `crypto.COINGECKO_IDS` — the coins Yahoo does not quote under any pair.

    Daily only: `market_chart`'s finer intervals only go back a few days,
    nowhere near a book's history. `vs_currency` asks CoinGecko for the
    pair's own quote currency directly, so no FX conversion is needed here —
    unlike the Yahoo USD fallback above, which has no such option.
    """
    if interval != "1d":
        return {}
    pairs = {t: p for t in tickers if (p := split_pair(t)) and p[0] in COINGECKO_IDS}
    if not pairs:
        return {}
    days = _period_days(period)
    out: dict[str, pd.DataFrame] = {}
    waiting: list[str] = []
    for t, (coin, quote) in pairs.items():
        url = COINGECKO_URL.format(id=COINGECKO_IDS[coin], quote=quote.lower(), days=days)
        if (hit := _gecko_hit(url)) is not None:
            out[t] = hit
            continue
        if _gecko_wait() > 0:
            waiting.append(t)
            continue
        with obs.swallow("coingecko.market_chart", ticker=t):
            try:
                prices = get_json(url, timeout=15).get("prices") or []
            except HTTPError as exc:
                if exc.code != 429:
                    raise
                headers = exc.headers
                wait = _gecko_trip(headers.get("Retry-After") if headers else None)
                obs.warn("coingecko.rate_limited", ticker=t, cooldown_s=wait)
                waiting.append(t)
                continue
            if not prices:
                continue
            idx = naive_dates(pd.to_datetime([p[0] for p in prices], unit="ms"))
            close = pd.Series([p[1] for p in prices], index=idx.normalize())  # ty: ignore[unresolved-attribute]
            close = close[~close.index.duplicated(keep="last")].sort_index()
            df = pd.DataFrame(
                {"Open": close, "High": close, "Low": close, "Close": close}
            )
            df.index.name = "Date"
            with _gecko_lock:
                _gecko_memo[url] = (time.monotonic(), df)
            out[t] = df.copy()
            obs.event("coingecko.fallback", ticker=t, coin=coin)
    if waiting:
        obs.event(
            "coingecko.cooling_off",
            remaining_s=round(_gecko_wait(), 1),
            tickers=sorted(waiting),
        )
    return out


def latest_price(ticker: str) -> float:
    """Most recent price — fast_info first, 5d history as fallback."""
    t = yf.Ticker(resolve(ticker))
    with obs.swallow("yahoo.fast_info", ticker=ticker):
        price = t.fast_info["lastPrice"]
        if price:
            return float(price)
    df = retry(lambda: t.history(period="5d", interval="1d"))
    if df.empty:
        raise ValueError(f"no data for {ticker}")
    return float(df["Close"].iloc[-1])


def cache_path(ticker: str) -> Path:
    return DATA_DIR / f"{ticker.upper()}.csv"


def save_history(ticker: str, df: pd.DataFrame) -> Path:
    path = cache_path(ticker)
    df.to_csv(path)
    return path


def load_cached(ticker: str) -> pd.DataFrame | None:
    path = cache_path(ticker)
    if not path.exists():
        return None
    return pd.read_csv(path, index_col="Date", parse_dates=True)
