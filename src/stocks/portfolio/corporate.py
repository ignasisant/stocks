"""Corporate actions the ledger never heard about — missing forward splits.

A broker statement prints trades. Most print nothing else, so a position
bought before a split and still held after it keeps the share count and the
per-share price the trade ticket carried: one AMZN share at $2050, not the
twenty at $102.50 the account actually holds since 2022-06-06. Everything
downstream then reads a pre-split cost basis against a post-split market
price, and a position that doubled shows as a 35% loss.

`validate._market_splits` already repairs this at import time, but only for
the ticker whose *sells* overshoot — a shortfall is the evidence it needs.
A position that was never sold produces no shortfall and no evidence, and
the wrong basis sits in the ledger indefinitely. This module supplies the
other evidence: what the buy was *priced* at.

Yahoo's daily closes are split-adjusted, ledger prices are as-traded (the
same asymmetry portfolio.fees replays by hand). So for a buy on day D:

    recorded_price / close_on(D)  ~=  every forward split after D

When the quotient matches the *full* product of Yahoo's post-D splits, the
row is raw and the ledger needs all of them. When it matches the product
with one split left out, the broker already adjusted for that one and adding
it would multiply a real position by twenty. Anything in between, or a close
Yahoo won't hand over, is not evidence — and this module proposes nothing it
cannot price. Nothing here writes; the caller decides.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from stocks.portfolio.ledger import Transaction

# splits(ticker) -> [(YYYY-MM-DD, ratio), …]; see data.fetch.splits.
SplitLookup = Callable[[str], list[tuple[str, float]]]
# close_on(ticker, YYYY-MM-DD) -> split-adjusted close, or None; see fetch.close_on.
CloseLookup = Callable[[str, str], float | None]

# How far the price quotient may sit from the factor it is claimed to be.
# Generous on purpose: the gap being tested is 20x (or, at the tightest ratio
# this module accepts, 1.5x), while the noise is one fill against that day's
# close. Wide enough to absorb the fill, far too narrow to confuse 1.5 with 1.
_PRICE_TOLERANCE = 0.12

# Reverse splits (ratio < 1) are left alone: they shrink a position, the
# broker reports the share count that survives, and a wrongly applied one
# would delete shares rather than leave a visible pre-split price behind.
_MIN_RATIO = 1.5


@dataclass
class MissingSplit:
    """One split the ledger lacks, with what applying it would do."""

    tx: Transaction  # the split row, ready for ledger.add_many
    held_before: float  # shares the ledger holds the day before the split
    priced_at: float  # the pre-split buy price the evidence came from
    priced_on: str  # …and its date
    market_close: float  # Yahoo's split-adjusted close that day

    @property
    def ticker(self) -> str:
        return self.tx.ticker

    @property
    def ratio(self) -> float:
        return self.tx.quantity

    @property
    def held_after(self) -> float:
        return self.held_before * self.ratio


def missing_splits(
    transactions: list[Transaction],
    *,
    splits: SplitLookup,
    close_on: CloseLookup,
) -> list[MissingSplit]:
    """Forward splits the ledger is missing, oldest first.

    A candidate has to clear all of: the ledger holds shares the day before
    it, no `split` row already covers that day, and the pre-split price
    evidence above. Tickers whose lookups fail are skipped, never guessed.
    """
    by_ticker: dict[str, list[Transaction]] = {}
    for t in transactions:
        if t.action in ("buy", "sell", "split"):
            by_ticker.setdefault(t.ticker.upper(), []).append(t)

    found: list[MissingSplit] = []
    for ticker, rows in sorted(by_ticker.items()):
        found += _ticker_gaps(ticker, rows, splits, close_on)
    found.sort(key=lambda m: (m.tx.date, m.ticker))
    return found


def _ticker_gaps(
    ticker: str,
    rows: list[Transaction],
    splits: SplitLookup,
    close_on: CloseLookup,
) -> list[MissingSplit]:
    try:
        events = [
            (str(day), float(ratio))
            for day, ratio in (splits(ticker) or [])
            if float(ratio) >= _MIN_RATIO
        ]
    except Exception:  # a lookup that can't answer proposes nothing
        return []
    if not events:
        return []
    events.sort()

    rows = sorted(rows, key=lambda t: (t.date, t.id or 0))
    have = {t.date for t in rows if t.action == "split" and t.quantity > 0}
    currency = next((t.currency for t in rows if t.currency), "USD")

    # Only the candidates accepted below: the ledger's own split rows are in
    # `rows` already, and counting them twice would square the share count.
    applied: list[tuple[str, float]] = []
    out: list[MissingSplit] = []
    for day, ratio in events:
        if day in have:
            continue
        held = _held_at(rows, day, applied)
        if held <= 1e-9:
            continue
        buy = _last_buy_before(rows, day)
        if buy is None:
            continue
        close = _close(close_on, ticker, buy.date)
        if close is None or close <= 0 or buy.price <= 0:
            continue
        unadjusted = _unadjusted_splits(buy.price / close, events, buy.date)
        if not any(d == day for d, _ in unadjusted):
            continue
        applied.append((day, ratio))
        out.append(
            MissingSplit(
                tx=Transaction(
                    date=day,
                    ticker=ticker,
                    action="split",
                    quantity=ratio,
                    currency=currency,
                    note=f"{ratio:g}:1 split (Yahoo corporate action)",
                ),
                held_before=held,
                priced_at=buy.price,
                priced_on=buy.date,
                market_close=close,
            )
        )
    return out


def _unadjusted_splits(
    quotient: float, events: list[tuple[str, float]], bought: str
) -> list[tuple[str, float]]:
    """Which splits after `bought` a price of `quotient` x the adjusted close
    has NOT been restated for.

    A broker restates the splits that had already happened when it printed the
    statement, so the ones a row still carries at face value are a *suffix* of
    the event list: the most recent ones. Each suffix has a distinct product
    (every ratio is at least 1.5, far outside the tolerance), so the quotient
    names exactly one of them — including the empty suffix, which is a row
    already on today's scale and needs no split at all. A quotient that fits
    none of them is not evidence of anything and returns none.
    """
    after = [(d, r) for d, r in events if d > bought]
    for cut in range(len(after) + 1):
        suffix = after[cut:]
        product = math.prod(r for _, r in suffix)
        if abs(quotient - product) <= _PRICE_TOLERANCE * product:
            return suffix
    return []


def _close(close_on: CloseLookup, ticker: str, day: str) -> float | None:
    try:
        return close_on(ticker, day)
    except Exception:
        return None


def _last_buy_before(rows: list[Transaction], day: str) -> Transaction | None:
    """The most recent buy strictly before `day` — the row whose price says
    which scale this ticker's ledger is on."""
    buys = [t for t in rows if t.action == "buy" and t.date < day and t.price > 0]
    return buys[-1] if buys else None


def _held_at(
    rows: list[Transaction], day: str, applied: list[tuple[str, float]]
) -> float:
    """Shares held the instant before `day`, with `applied` splits replayed.

    A sell recorded in post-split shares against a ledger still counting
    pre-split ones drives this negative; clamping at zero keeps such a book
    from proposing a split on a position it cannot even price.
    """
    qty = 0.0
    for t in rows:
        if t.date >= day:
            break
        if t.action == "buy":
            qty += t.quantity
        elif t.action == "sell":
            qty -= t.quantity
        elif t.action == "split" and t.quantity > 0:
            qty *= t.quantity
    for split_day, ratio in applied:
        if split_day < day:
            qty *= ratio
    return max(0.0, qty)


# --------------------------------------------------- putting trades on one scale
# Yahoo's bars are split-adjusted; a ledger row keeps the price and the share
# count the trade ticket carried. Anything that draws the two together — a buy
# marker on the price chart, an execution against that day's midpoint — has to
# restate the trade first, or a pre-split buy plots twenty times above a chart
# it belongs on and its return to today reads as a 90% loss.


def split_factors(
    transactions: list[Transaction],
) -> dict[str, list[tuple[str, float]]]:
    """ticker -> [(date, ratio), …] from the ledger's own forward-split rows."""
    out: dict[str, list[tuple[str, float]]] = {}
    for t in transactions:
        if t.action == "split" and t.quantity > 0:
            out.setdefault(t.ticker, []).append((t.date, t.quantity))
    return out


def on_market_scale(
    tx: Transaction, factors: dict[str, list[tuple[str, float]]]
) -> tuple[float, float]:
    """`tx`'s (price, quantity) in today's shares — the scale Yahoo quotes in.

    Splits strictly after the trade date apply; one sharing the trade's date
    does not, matching how positions.py replays the ledger. Price and quantity
    move inversely, so the money the row represents is unchanged.
    """
    ratio = math.prod(
        r for day, r in factors.get(tx.ticker, ()) if day > tx.date
    )
    return (tx.price / ratio, tx.quantity * ratio) if ratio else (tx.price, tx.quantity)
