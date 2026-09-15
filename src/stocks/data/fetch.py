"""Fetch OHLCV price data via yfinance; cache to CSV under data/."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from stocks import obs
from stocks.config import DATA_DIR, ticker_aliases

# ---------------------------------------------------------------- the breaker
# One verdict about Yahoo for the whole process, because there is only one
# thing it can be angry at: this host's egress IP. Without it every caller
# rediscovers the throttle on its own and pays the full `_retry` ladder to do
# it — and yfinance itself charges three or four round trips for a rejected
# request (it re-mints the cookie and crumb, flips its cookie strategy and
# replays the call). A Home render is ~50 symbols; one throttled Yahoo used to
# cost the page all of that, on every rerun.
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


def _retry[T](fn: Callable[[], T], attempts: int = 3, base_delay: float = 1.5) -> T:
    """Run fn, retrying on Yahoo's 429 with exponential backoff (1.5s, 3s).

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


def resolve(ticker: str) -> str:
    """Yahoo Finance symbol for a ticker, mapping broker codes via
    watchlist.yaml `aliases` (identity when unmapped)."""
    return ticker_aliases().get(ticker.upper(), ticker)


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
# several calls *within one render*, not to hold quotes. The web layer's own
# st.cache_data wrappers still bound how often a render happens at all.
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


def fetch_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Download OHLCV history for one ticker."""
    df = _retry(
        lambda: yf.Ticker(resolve(ticker)).history(period=period, interval=interval)
    )
    df.index.name = "Date"
    return df


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
    not the same claim as refused, and the next rerun should try again.
    """
    if not tickers:
        return {}
    symbol_of = {t: resolve(t) for t in tickers}
    symbols = list(dict.fromkeys(symbol_of.values()))
    # The budget is OUTSIDE the retry ladder, not inside it: wrapped the other
    # way each of the three attempts would get its own 60s and a hung Yahoo
    # would cost three minutes plus the backoff — the budget has to bound the
    # whole thing, sleeps included.
    data = _budgeted(
        lambda: _retry(
            lambda: yf.download(
                symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=auto_adjust,
                progress=False,
                threads=True,
            )
        ),
        budget=budget,
        symbols=len(symbols),
    )
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
    return out


def latest_price(ticker: str) -> float:
    """Most recent price — fast_info first, 5d history as fallback."""
    t = yf.Ticker(resolve(ticker))
    with obs.swallow("yahoo.fast_info", ticker=ticker):
        price = t.fast_info["lastPrice"]
        if price:
            return float(price)
    df = _retry(lambda: t.history(period="5d", interval="1d"))
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
