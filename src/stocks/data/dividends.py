"""Ex-dividend calendar: which holdings go ex in the next N days, and for how much.

The rear-view (what the ledger already received) lives in
stocks.portfolio.dividends; this is the forward-looking half. Yahoo's quote
blob carries `exDividendDate` and `lastDividendValue`, so one memoized `.info`
per ticker answers both "when" and "roughly how much per share" — the amount is
the *last* payment, which is what a declared-but-unpublished next payment is
worth guessing at. Date selection (build_events) is pure and tests offline;
only fetch_ex_dividend touches the network.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

# yfinance reports the ex-date as an epoch. A stale blob can carry a date months
# in the past (the last one that went ex); build_events drops those with the
# same `days_until >= 0` rule the earnings calendar uses.


@dataclass(frozen=True)
class DividendEvent:
    """One upcoming ex-dividend date for a ticker held or watched."""

    ticker: str
    ex_date: date
    days_until: int
    per_share: float | None = None  # last paid, in `currency`
    currency: str | None = None

    def cash(self, quantity: float) -> float | None:
        """Estimated gross payment on `quantity` shares, in `currency`."""
        if self.per_share is None:
            return None
        return self.per_share * quantity


def _epoch_date(value) -> date | None:
    """Epoch seconds to a UTC date; None for anything unparseable."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def _positive_float(value) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def build_events(
    raw: dict[str, tuple[date | None, float | None, str | None]],
    ref: date,
    within_days: int = 7,
) -> list[DividendEvent]:
    """Turn {ticker: (ex_date, per_share, ccy)} into upcoming events, soonest first.

    Pure: no network, no clock. A ticker whose ex-date is unknown or already
    past is dropped — a payment that has gone ex is the ledger's business now.
    """
    events: list[DividendEvent] = []
    for ticker, (ex_date, per_share, currency) in raw.items():
        if ex_date is None:
            continue
        days = (ex_date - ref).days
        if days < 0 or days > within_days:
            continue
        events.append(DividendEvent(ticker, ex_date, days, per_share, currency))
    return sorted(events, key=lambda e: (e.days_until, e.ticker))


def fetch_ex_dividend(ticker: str) -> tuple[date | None, float | None, str | None]:
    """(ex-date, last per-share amount, currency) for one ticker, via yfinance.

    All-None on any failure: a dead symbol inside a pool.map must not abort the
    whole calendar, and a digest without the dividend section is still a digest.
    Non-payers simply have no `exDividendDate`.
    """
    from stocks.data.crypto import is_crypto
    from stocks.data.fetch import info as quote_info

    if is_crypto(ticker):
        return None, None, None
    try:
        blob = quote_info(ticker)
    except Exception:
        return None, None, None
    currency = blob.get("currency")
    return (
        _epoch_date(blob.get("exDividendDate")),
        _positive_float(blob.get("lastDividendValue")),
        str(currency).upper() if currency else None,
    )


def upcoming_ex_dividends(
    tickers: list[str],
    within_days: int = 7,
    ref: date | None = None,
    max_workers: int = 8,
) -> list[DividendEvent]:
    """Fetch ex-dates for `tickers` and return the ones inside the window."""
    if not tickers:
        return []
    ref = ref or date.today()
    unique = sorted(set(tickers))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fetched = dict(zip(unique, pool.map(fetch_ex_dividend, unique), strict=True))
    return build_events(fetched, ref, within_days)


# ------------------------------------------------------------------- history
# The other half of "what will this book pay": every past per-share payment,
# which is what turns a holding into an income estimate even when the broker's
# statement never mentioned the dividend. Yahoo's series is SPLIT-ADJUSTED
# (AAPL's 2016 payments read 0.13, not 0.52), which is the same footing
# analysis.portfolio.shares_frame puts quantities on — so per_share * shares
# is the cash, with no split arithmetic in between.


@dataclass(frozen=True)
class DividendHistory:
    """Every past per-share payment for one ticker, oldest first.

    `payments` is [(ex-date ISO, per share in `currency`), …]. Empty when the
    ticker pays nothing, is unknown, or Yahoo refused — a caller can't tell
    those apart and shouldn't: all three mean "no history to estimate from".
    """

    ticker: str
    payments: tuple[tuple[str, float], ...] = ()
    currency: str | None = None

    def trailing(self, ref: date, days: int = 365) -> float:
        """Per-share total paid in the `days` before `ref` — the TTM rate."""
        start = (ref - timedelta(days=days)).isoformat()
        end = ref.isoformat()
        return sum(amt for day, amt in self.payments if start < day <= end)

    def trailing_count(self, ref: date, days: int = 365) -> int:
        """How many payments went ex in that window (4 = quarterly payer)."""
        start = (ref - timedelta(days=days)).isoformat()
        end = ref.isoformat()
        return sum(1 for day, _ in self.payments if start < day <= end)


_history_memo: dict[str, DividendHistory] = {}
_history_lock = threading.Lock()


def clear_history_cache() -> None:
    """Forget memoized histories — for tests and for a forced refresh."""
    with _history_lock:
        _history_memo.clear()


def fetch_history(ticker: str) -> DividendHistory:
    """Full dividend history for one ticker via yfinance; empty on any failure.

    Memoized for the process: a book of 30 names re-reads this on every rerun
    and the series only changes when a payment goes ex. The currency comes
    from the history metadata the same call already downloaded, so knowing
    what the amounts are denominated in costs no extra request.
    """
    import pandas as pd
    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError

    from stocks import obs
    from stocks.data.crypto import is_crypto
    from stocks.data.fetch import resolve, throttle_remaining, trip_throttle

    if is_crypto(ticker):
        return DividendHistory(ticker)
    key = resolve(ticker)
    with _history_lock:
        hit = _history_memo.get(key)
    if hit is not None:
        return DividendHistory(ticker, hit.payments, hit.currency)
    if throttle_remaining():
        return DividendHistory(ticker)
    try:
        handle = yf.Ticker(key)
        series = handle.dividends
        meta = handle.history_metadata or {}
    except YFRateLimitError:
        trip_throttle()
        obs.warn("yahoo.dividends_rate_limited", ticker=key)
        return DividendHistory(ticker)
    except Exception as exc:
        obs.warn("yahoo.dividends_failed", ticker=key, error=str(exc))
        return DividendHistory(ticker)
    payments = tuple(sorted(
        (str(pd.Timestamp(when).date()), float(amount))
        for when, amount in getattr(series, "items", lambda: [])()
        if amount and float(amount) > 0
    ))
    ccy = meta.get("currency")
    history = DividendHistory(key, payments, str(ccy).upper() if ccy else None)
    with _history_lock:
        _history_memo[key] = history
    return DividendHistory(ticker, history.payments, history.currency)


def histories(tickers: list[str], max_workers: int = 8) -> dict[str, DividendHistory]:
    """Dividend history for many tickers, fetched in parallel. Never raises."""
    if not tickers:
        return {}
    unique = sorted(set(tickers))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fetched = pool.map(fetch_history, unique)
    return {t: h for t, h in zip(unique, fetched, strict=True) if h.payments}
