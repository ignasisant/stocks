"""Corporate actions the ledger never heard about — missing splits.

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

    recorded_price / close_on(D)  ~=  every split after D

A reverse split works the same way with a quotient under one: a 1:30 leaves a
raw pre-split buy at 1/30 of the adjusted close, and the row it needs shrinks
the position to the shares that survived. A broker that already restated the
row prices it on today's scale, and nothing is proposed.

When the quotient matches the *full* product of Yahoo's post-D splits, the
row is raw and the ledger needs all of them. When it matches the product
with one split left out, the broker already adjusted for that one and adding
it would multiply a real position by twenty. Anything in between, or a close
Yahoo won't hand over, is not evidence — and this module proposes nothing it
cannot price. Nothing here writes; the caller decides.

Sells are priced the same way as buys, and the latest trade before each
split speaks for it; with several splits those trades are read together
(`_fit`), because one alone cannot tell a 2:1 then 1:2 from neither.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from stocks import obs
from stocks.portfolio import consistency
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import replay_order

# splits(ticker) -> [(YYYY-MM-DD, ratio), …]; see data.fetch.splits.
SplitLookup = Callable[[str], list[tuple[str, float]]]
# close_on(ticker, YYYY-MM-DD) -> split-adjusted close, or None; see fetch.close_on.
CloseLookup = Callable[[str, str], float | None]

# How far the price quotient may sit from the factor it is claimed to be.
# Generous on purpose: the gap being tested is 20x (or, at the tightest ratio
# this module accepts, 1.5x), while the noise is one fill against that day's
# close. Wide enough to absorb the fill, far too narrow to confuse 1.5 with 1.
_PRICE_TOLERANCE = 0.12

# The tightest split this module believes, either way: 1.5 forward, 1/1.5
# reverse. Anything closer to 1 hides inside the tolerance above.
_MIN_RATIO = 1.5

# How many trades before a split are asked for a close: the latest one Yahoo
# can price, without a round trip for every fill in the book.
_EVIDENCE_TRIES = 3


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
    source: consistency.Source = "import",
) -> list[MissingSplit]:
    """Splits, forward or reverse, the ledger is missing, oldest first.

    A candidate has to clear all of: no `split` row already covers that
    day, and the pre-split price evidence above. A name sold out before it
    is proposed too (nothing held, nothing to say when unproven): its
    history is priced off the split-adjusted close all the same. Tickers
    whose lookups fail are skipped, never guessed. Each one found is a
    `data.inconsistency` line, `source` saying which screen asked.
    """
    by_ticker: dict[str, list[Transaction]] = {}
    for t in transactions:
        if t.action in ("buy", "sell", "split"):
            by_ticker.setdefault(t.ticker.upper(), []).append(t)

    found: list[MissingSplit] = []
    for ticker, rows in sorted(by_ticker.items()):
        found += _ticker_gaps(ticker, rows, splits, close_on, source=source)
    found.sort(key=lambda m: (m.tx.date, m.ticker))
    for gap in found:
        consistency.report(
            "split_missing",
            source=source,
            ticker=gap.ticker,
            key=gap.tx.date,
            split=gap.tx.date,
            ratio=gap.tx.quantity,
            off=consistency.ratio(gap.priced_at, gap.market_close),
        )
    return found


def _ticker_gaps(
    ticker: str,
    rows: list[Transaction],
    splits: SplitLookup,
    close_on: CloseLookup,
    *,
    source: consistency.Source = "import",
) -> list[MissingSplit]:
    try:
        events = [
            (str(day), float(ratio))
            for day, ratio in (splits(ticker) or [])
            if _believable(float(ratio))
        ]
    except Exception:  # a lookup that can't answer proposes nothing
        return []
    if not events:
        return []
    events.sort()

    rows = sorted(rows, key=replay_order)
    have = {t.date: t.quantity for t in rows if t.action == "split" and t.quantity > 0}
    currency = next((t.currency for t in rows if t.currency), "USD")
    trades = [t for t in rows if t.action in ("buy", "sell") and t.price > 0]

    evidence = _evidence(
        ticker, trades, [d for d, _ in events if d not in have], close_on
    )
    fills = list({id(e[0]): e for e in evidence.values() if e}.values())
    chosen, off = _fit(fills, events, have)
    for t, close in off:
        quotient = t.price / close
        # No reading of the splits explains the row's scale. A split's worth
        # away from its day's close — pence booked as pounds, another name
        # under the symbol, a typo — is a contradiction worth a line; closer
        # than that is a volatile day, which is not. About a hundred off is
        # the minor-unit slip, counted apart since a scale fixes it.
        if quotient >= _MIN_RATIO or quotient <= 1 / _MIN_RATIO:
            consistency.report(
                "currency_off" if consistency.unit_slip(quotient) else "price_off_market",
                source=source,
                ticker=ticker,
                key=t.date,
                traded=t.date,
                off=consistency.ratio(t.price, close),
            )
    unexplained = {id(t) for t, _ in off}

    # Only the candidates accepted below: the ledger's own split rows are in
    # `rows` already, and counting them twice would square the share count.
    applied: list[tuple[str, float]] = []
    out: list[MissingSplit] = []
    for day, ratio in events:
        if day in have:
            continue
        # A name sold out before the split still needs it: the closes are
        # split-adjusted, and the replay restates the earlier fills by the
        # ledger's split rows only, so without one every fill read the close
        # 20x off and the whole series was rejected — the book's history held
        # at cost (AMZN, GOOGL, NVDA closed in 2022, prod 2026-11-10). Nothing
        # held is nothing to say, though: a flat name proposes only on proof.
        held = _held_at(rows, day, applied)
        if held < -1e-9:
            continue
        flat = held <= 1e-9
        found = evidence.get(day)
        if found is None:
            if not flat:
                before = any(t.date < day for t in trades)
                _unproven(ticker, day, "no_close" if before else "no_buy", source)
            continue
        trade, close = found
        if day not in chosen:
            # The rows already carry this split, or two readings fit them.
            if not flat and id(trade) not in unexplained:
                _unproven(ticker, day, "restated", source)
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
                held_before=max(0.0, held),
                priced_at=trade.price,
                priced_on=trade.date,
                market_close=close,
            )
        )
    return out


def _evidence(
    ticker: str, trades: list[Transaction], days: list[str], close_on: CloseLookup
) -> dict[str, tuple[Transaction, float] | None]:
    """Split day -> the latest trade before it Yahoo can price, and that close.

    A few trades back at most, each asked once: the scan runs over a whole
    book from the warm cron, and a close per fill would be a round trip per
    row.
    """
    asked: dict[int, float | None] = {}
    out: dict[str, tuple[Transaction, float] | None] = {}
    for day in days:
        out[day] = None
        before = [t for t in trades if t.date < day]
        for t in reversed(before[-_EVIDENCE_TRIES:]):
            if id(t) not in asked:
                asked[id(t)] = _close(close_on, ticker, t.date)
            close = asked[id(t)]
            if close is not None and close > 0:
                out[day] = (t, close)
                break
    return out


def _fit(
    fills: list[tuple[Transaction, float]],
    events: list[tuple[str, float]],
    have: dict[str, float],
) -> tuple[set[str], list[tuple[Transaction, float]]]:
    """The missing splits the ledger needs, and the fills no reading explains.

    A fill's price over the adjusted close is every split after it that the
    row was not restated for. A statement restates the splits that had
    happened when it printed, so what a book lacks is a *suffix* of them:
    the most recent ones. Read one fill at a time, a forward and a reverse
    split that cancel (2:1 then 1:2) fit both or neither, and a later fill
    proved the second alone: the book got half the pair and the shares
    before it were halved (tests/test_split_scenarios.py). So every suffix
    is scored by how many fills it puts on their close, then by how close
    (3:1, 3:1, 1:10 multiply to 0.9, inside the tolerance of no split at
    all), and the best one wins; between equals, the shortest, which writes
    the fewest rows and, for a pair that cancels, none — the price path is
    right without it.
    """
    first = min((t.date for t, _ in fills), default=None)
    missing = [
        (d, r) for d, r in events if d not in have and first is not None and d > first
    ]
    restated = []
    for t, close in fills:
        on_ledger = math.prod(r for d, r in have.items() if d > t.date)
        restated.append((t, t.price / close / on_ledger))
    best: tuple[int, float, list[tuple[str, float]]] = (-1, 0.0, [])
    explained: set[int] = set()
    for cut in range(len(missing), -1, -1):
        suffix = missing[cut:]
        hits, error = set(), 0.0
        for t, quotient in restated:
            product = math.prod(r for d, r in suffix if d > t.date)
            if abs(quotient - product) <= _PRICE_TOLERANCE * product:
                hits.add(id(t))
                error += abs(math.log(quotient / product))
        explained |= hits
        if len(hits) > best[0] or (len(hits) == best[0] and error < best[1] - 1e-9):
            best = (len(hits), error, suffix)
    return {d for d, _ in best[2]}, [f for f in fills if id(f[0]) not in explained]


def _unproven(ticker: str, day: str, why: str, source: consistency.Source) -> None:
    """Say why a split on shares the ledger held proposed nothing.

    Silence here hid a book's BYND 1:30 for days (triage 2026-10-24, ERR-05):
    the scan ran, wrote nothing, and nothing said which rule stopped it.
    """
    obs.event(
        "portfolio.split_unproven", ticker=ticker, split=day, why=why, source=source
    )


def _believable(ratio: float) -> bool:
    return ratio >= _MIN_RATIO or 0 < ratio <= 1 / _MIN_RATIO


def _close(close_on: CloseLookup, ticker: str, day: str) -> float | None:
    try:
        return close_on(ticker, day)
    except Exception:
        return None


def _held_at(
    rows: list[Transaction], day: str, applied: list[tuple[str, float]]
) -> float:
    """Shares held the instant before `day`, with `applied` splits replayed.

    A sell recorded in post-split shares against a ledger still counting
    pre-split ones drives this negative, and the caller proposes nothing on
    a position it cannot even price.
    """
    qty = 0.0
    # Replayed in date order with the rows, not after them: a sell between
    # two splits is in the first one's shares (tests/test_split_scenarios.py).
    pending = sorted(applied)
    for t in rows:
        if t.date >= day:
            break
        while pending and pending[0][0] <= t.date:
            qty *= pending.pop(0)[1]
        if t.action == "buy":
            qty += t.quantity
        elif t.action == "sell":
            qty -= t.quantity
        elif t.action == "split" and t.quantity > 0:
            qty *= t.quantity
    for split_day, ratio in pending:
        if split_day < day:
            qty *= ratio
    return qty


# --------------------------------------------------- putting trades on one scale
# Yahoo's bars are split-adjusted; a ledger row keeps the price and the share
# count the trade ticket carried. Anything that draws the two together — a buy
# marker on the price chart, an execution against that day's midpoint — has to
# restate the trade first, or a pre-split buy plots twenty times above a chart
# it belongs on and its return to today reads as a 90% loss.


def split_factors(
    transactions: list[Transaction],
) -> dict[str, list[tuple[str, float]]]:
    """ticker -> [(date, ratio), …] from the ledger's own split rows (a reverse
    split's ratio is under one)."""
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


# ------------------------------------------------------------- fills on a chart
# Drawing somebody's own trades against a price series needs two corrections,
# and forgetting either one is silent. They live here together so that a caller
# cannot remember the split and forget the label.


@dataclass(frozen=True)
class Fill:
    """One buy or sell, ready to plot: today's shares, today's price scale."""

    date: str
    action: str
    price: float
    quantity: float


def own_fills(transactions: list[Transaction], ticker: str) -> list[Fill]:
    """This account's buys and sells of `ticker`, oldest first, chart-ready.

    Two corrections, both invisible when they are missing:

    **The label.** A book fed by two brokers spells one holding two ways —
    DEGIRO exports have no ticker column and book under the ISIN, IBKR uses the
    symbol — and `positions.build` unifies them before replaying. So the open
    position, the custody split and the URL of the page all speak the unified
    label, while the raw ledger rows do not. Filtering the raw rows by that
    label matches nothing at all, and a holding the reader can see on screen
    draws no trades whatsoever.

    **The scale.** Ledger prices are as-traded and Yahoo's bars are
    split-adjusted, so a pre-split buy plotted raw sits twenty times above the
    candles it belongs to. Price and quantity move inversely, so the money each
    row represents is unchanged.

    `relabel` rather than `normalize`: the labels are what a lookup needs, and
    an unmatched transfer leg turned into a synthetic `buy` would draw a
    purchase marker at a price nobody paid.
    """
    from stocks.portfolio import transfers

    unified = transfers.relabel(transactions)
    factors = split_factors(unified)
    fills = [
        tx for tx in unified if tx.ticker == ticker and tx.action in ("buy", "sell")
    ]
    scaled = []
    for fill in sorted(fills, key=lambda tx: (tx.date, tx.id or 0)):
        price, quantity = on_market_scale(fill, factors)
        scaled.append(Fill(fill.date, fill.action, price, quantity))
    return scaled
