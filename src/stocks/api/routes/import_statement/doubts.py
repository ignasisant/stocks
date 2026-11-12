"""Whether the model named the right security, asked of its prices.

A parser copies the symbol its broker printed. The model reads a statement no
parser knows and *names* each holding (`portfolio.instruments`), and a name it
half remembers comes back as a real ticker all the same: listed, priced, and
somebody else's company. Validation cannot fault that row. Its price can: a
fill sits near the close of the security it was a fill of.

So each name the model gave is priced on the latest days it traded, and one
whose fills are nowhere near its closes is doubted: a warning on its rows, a
`data.inconsistency` line (`ticker_doubt`), and a question to the reader, who
confirms the name or picks the line it really was (`/import/ticker`).

Only what can be compared is: a line of the trade currency's venues against
the fill as it is, a bare (dollar) line against a fill in another currency at
the day's rate. A split after the trade explains a gap as well as a wrong name
does and has its own repair (`portfolio.corporate`), so a gap that is a split's
size is not a doubt, nor is the minor-unit hundredfold.

Bounded like every lookup the preview makes: nothing asked of a throttled
host, one budget for the statement, and a name still unpriced when it runs
out is not doubted. A doubt is a verdict, and "could not ask" is not one.
"""

from __future__ import annotations

import itertools
import math
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass

from stocks import obs
from stocks.api.routes.import_statement.lookups import LOOKUP_BUDGET_S, _within
from stocks.data import crypto, fetch, fx, symbols
from stocks.portfolio import consistency, venue
from stocks.portfolio.validate import Checked, Issue

DOUBT_BUDGET_S = 6.0  # every name's closes, together
_DOUBT_WORKERS = 4
# The most names one statement is priced for; the rest are not doubted.
DOUBT_MAX = 24

# How far a fill may sit from its day's close before the name is in doubt.
# Far wider than the band a venue is picked on (`venue.TOLERANCE`): that one
# chooses between lines of one company, this one accuses a row of being
# another company, and a fill a fifth off its close is still an ugly session.
DOUBT_TOLERANCE = 0.2

# Splits after the trade whose products are tried as the gap's explanation.
_SPLITS_TRIED = 6

ISSUE = "validate.ticker_doubt"


@dataclass(frozen=True)
class Doubt:
    """A name whose fills its closes do not back."""

    day: str  # the latest trade day that could be priced
    off: float  # the fill over that day's close


def _split_sized(quotient: float, events: list[tuple[str, float]], day: str) -> bool:
    """Whether some of the splits after `day` multiply to `quotient`: the row
    is raw (all of them) or its broker restated part (the rest)."""
    later = [ratio for when, ratio in events if when > day and ratio > 0]
    later = later[-_SPLITS_TRIED:]
    for size in range(1, len(later) + 1):
        for chosen in itertools.combinations(later, size):
            if abs(quotient / math.prod(chosen) - 1) <= DOUBT_TOLERANCE:
                return True
    return False


def verdict(ticker: str, currency: str, sampled, *, close, usd_rate, splits):
    """The `Doubt` on `ticker` for fills `sampled` in `currency`, or None.

    None is "no doubt", for either reason: a sampled day closed near its fill,
    or nothing here could compare the two.
    """
    symbol = fetch.resolve(ticker)
    if "." in symbol:
        if not symbols.on_venues(symbol, currency):
            return None  # a line quoted in a currency this cannot name
        priced = close
    else:
        priced = venue.in_currency(close, usd_rate, currency)
    closes: dict[str, float] = {}

    def remembered(name: str, day: str) -> float | None:
        last = priced(name, day)
        if last:
            closes[day] = last
        return last

    off: tuple[str, float] | None = None
    for day, price in sampled:
        said = venue.agrees(ticker, [(day, price)], currency, remembered, DOUBT_TOLERANCE)
        if said:
            return None
        if said is False and off is None:
            off = (day, price / closes[day])
    if off is None:
        return None
    day, quotient = off
    if consistency.unit_slip(quotient) or _split_sized(quotient, splits(ticker), day):
        return None
    return Doubt(day=day, off=round(quotient, 3))


def find(rows: list[Checked]) -> dict[venue.Key, Doubt]:
    """(ticker, currency) -> `Doubt`, for the names of `rows` the prices do
    not back. Empty when Yahoo is throttled: nothing is asked into it."""
    txs = [c.tx for c in rows]
    keys = sorted(
        {
            (tx.ticker, tx.currency)
            for tx in txs
            if tx.action in ("buy", "sell")
            and tx.price > 0
            and not crypto.is_crypto(tx.ticker)
            and not symbols.is_isin(tx.ticker)
        }
    )[:DOUBT_MAX]
    if not keys or fetch.throttle_remaining() > 0:
        return {}
    deadline = time.monotonic() + DOUBT_BUDGET_S

    def left() -> float:
        return min(LOOKUP_BUDGET_S, deadline - time.monotonic())

    def close(symbol: str, day: str) -> float | None:
        if left() <= 0 or fetch.throttle_remaining() > 0:
            return None
        return _within(lambda: fetch.close_on(symbol, day), left(), None, ticker=symbol)

    def usd_rate(currency: str, day: str) -> float | None:
        if left() <= 0:
            return None
        return _within(
            lambda: fx.rate_on(day, "USD", currency), left(), None, currency=currency
        )

    def splits(ticker: str) -> list[tuple[str, float]]:
        if left() <= 0:
            return []
        return _within(lambda: fetch.splits(ticker), left(), [], ticker=ticker)

    def ask(key: venue.Key) -> Doubt | None:
        return verdict(
            *key, venue.samples(key, txs), close=close, usd_rate=usd_rate, splits=splits
        )

    pool = ThreadPoolExecutor(max_workers=min(len(keys), _DOUBT_WORKERS))
    try:
        asked = {pool.submit(ask, key): key for key in keys}
        done, _ = wait(asked, timeout=DOUBT_BUDGET_S)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    found: dict[venue.Key, Doubt] = {}
    for future in done:
        if future.exception() is not None:
            obs.warn(
                "api.import_doubt_failed",
                error_type=type(future.exception()).__name__,
                ticker=asked[future][0],
            )
        elif doubt := future.result():
            found[asked[future]] = doubt
    return found


def flag(rows: list[Checked]) -> list[str]:
    """Warn on the rows of each doubted name, log it, and name the tickers."""
    found = find(rows)
    for (ticker, _), doubt in sorted(found.items()):
        consistency.report(
            "ticker_doubt",
            source="import",
            ticker=ticker,
            key=doubt.day,
            traded=doubt.day,
            off=doubt.off,
        )
    for checked in rows:
        tx = checked.tx
        doubt = found.get((tx.ticker, tx.currency))
        if doubt and tx.action in ("buy", "sell"):
            params = {"ticker": tx.ticker, "date": doubt.day}
            checked.issues.append(Issue("warning", "ticker", ISSUE, params))
    return sorted({ticker for ticker, _ in found})
