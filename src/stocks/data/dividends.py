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

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime

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
