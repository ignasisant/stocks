"""What the book is owed and was paid: estimates, unbooked payouts,
ex-dates and histories.
"""

from __future__ import annotations

from stocks.analysis.portfolio import HELD_ACTIONS
from stocks.cache import ttl_cache
from stocks.loaders.keys import _HELD_STALE, ledger_state
from stocks.portfolio import transfers


@ttl_cache(21600.0, max_entries=8)
def dividend_estimates(db: str, mtime: float, base: str = "EUR") -> tuple:
    """(estimated years, forward income, forward totals in `base`, unrecorded).

    What the book was entitled to, from Yahoo's per-share history and the
    ledger's own share timeline — the half no statement can be asked for, since
    a dividend is owed to whoever held the share the day before it went ex
    whether or not the import carried a row for it. Six-hour ttl: a payment goes
    ex once a quarter and this is one request per name ever held.

    Raises `YFRateLimitError` when Yahoo is in cooldown and nothing came back,
    so a throttled minute is never cached as "this book pays nothing" — the
    route turns it into a 503 with a `Retry-After` like every other fetch here.
    """
    from stocks.portfolio import dividends as div

    txs, history, payments = _entitled(db, mtime, base)
    estimated = div.estimate_by_year(payments, base=base)
    forward = div.forward_income(txs, history)
    totals = div.forward_totals(forward, base=base)
    unrecorded = div.unrecorded_by_year(
        div.by_year(txs, base=base, capital=True), estimated
    )
    return estimated, forward, totals, unrecorded


@ttl_cache(21600.0, max_entries=8)
def unbooked_dividends(db: str, mtime: float, base: str = "EUR") -> list[tuple]:
    """[(EstimatedPayment, gross in `base` or None), …], newest first.

    The payments `dividend_estimates` counts as unrecorded, one by one: what the
    shares were entitled to with no ledger dividend row to answer for it. Most
    of them are the tail a statement never reached — it was exported in July,
    the book kept paying in August. Valued at the ex-date's rate, as the yearly
    estimate is; a date with no rate is None, never today's standing in.

    Raises `YFRateLimitError` under the same rule as `dividend_estimates`.
    """
    from stocks.data.fx import converter, prefetch
    from stocks.portfolio import dividends as div

    txs, _history, payments = _entitled(db, mtime, base)
    missing = div.unbooked(payments, transfers.relabel(txs))
    prefetch((p.ex_date, p.currency) for p in missing)
    to_base = converter(base)
    out: list[tuple] = []
    for p in reversed(missing):
        try:
            amount = to_base(p.gross, p.currency, p.ex_date)
        except Exception:  # noqa: BLE001 — an unpriced row is n/a, not a 500
            amount = None
        out.append((p, amount))
    return out


@ttl_cache(21600.0, max_entries=8)
def dividend_payments(db: str, mtime: float, base: str = "EUR") -> list:
    """Every ex-date the ledger's shares were entitled to, oldest first.

    `EstimatedPayment`s straight off `_entitled`: the calendar's past dividend
    chips, drawn whether or not a statement ever booked the cash.

    Raises `YFRateLimitError` under the same rule as `dividend_estimates`.
    """
    return _entitled(db, mtime, base)[2]


@ttl_cache(
    21600.0,
    max_entries=16,
    stale_s=_HELD_STALE,
    quiet_s=21600.0,
    persist="ex_dividends",
)
def ex_dividends(tickers: tuple[str, ...]) -> list:
    """The next declared ex-date per name, inside a year — `DividendEvent`s.

    Keyed on the ticker tuple like `earnings_calendar`, and six hours like it:
    a company declares once a quarter. Yahoo's `exDividendDate` stays on the
    LAST ex-date until the next is declared, so most names come back with
    nothing ahead — which is the answer, not a gap.

    Raises `YFRateLimitError` when Yahoo is in cooldown and nothing came back,
    so a throttled minute is never cached as "nothing declared".
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import upcoming_ex_dividends
    from stocks.data.fetch import throttle_remaining

    if not tickers:
        return []
    if throttle_remaining():
        raise YFRateLimitError
    events = upcoming_ex_dividends(list(tickers), within_days=366)
    if not events and throttle_remaining():
        raise YFRateLimitError
    return events


@ttl_cache(
    21600.0,
    max_entries=16,
    stale_s=_HELD_STALE,
    persist="dividend_histories",
    disk_max=16,
)
def dividend_histories(tickers: tuple[str, ...]) -> dict:
    """Per-share payment history per name — what the projected ex-dates repeat
    and what the Dividendos tab's estimates start from (`_entitled`).

    `DividendHistory`s keyed by the caller's label, names that pay nothing
    left out. One request per name — eighty for a book that has held eighty —
    and the process memo under it (`stocks.data.dividends`) died with every
    restart, so it is persisted, and served stale for a while: a series only
    changes when a payment goes ex.

    Raises `YFRateLimitError` when Yahoo throttled any of them: a name that
    came back empty then may well pay, and a persisted "pays nothing" would
    outlive the cooldown by days.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import histories
    from stocks.data.fetch import throttle_remaining

    if not tickers:
        return {}
    found = histories(list(tickers))
    if throttle_remaining():
        raise YFRateLimitError
    return found


def _entitled(db: str, mtime: float, base: str) -> tuple:
    """(ledger, per-share histories, every payment the shares were owed).

    The half both dividend estimates start from. The histories are memoized
    (`dividend_histories`), so the second loader to ask pays no request.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import histories
    from stocks.data.fetch import throttle_remaining
    from stocks.portfolio import dividends as div

    txs = ledger_state(db, mtime, base).txs
    tickers = sorted(
        {t.ticker for t in transfers.relabel(txs) if t.action in HELD_ACTIONS}
    )
    try:
        history = dividend_histories(tuple(tickers))
    except YFRateLimitError:
        # What the process memo has: the names that did come back.
        history = histories(tickers)
    if not history and (tickers and throttle_remaining()):
        raise YFRateLimitError
    return txs, history, div.estimate_payments(txs, history)
