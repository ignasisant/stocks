"""Shares moving between brokers: the ledger's two non-trade legs.

Moving your own shares from one custodian to another is not a disposal
anywhere: no jurisdiction taxes it, the acquisition date does not restart and
the cost basis carries over untouched. Brokers do not print it that way.
DEGIRO books a transfer-out as an ordinary sale at the day's market price;
IBKR's first statement after the shares land simply lists them as a holding.
Imported literally that pair reads as "sold the lot, bought it back weeks
later at a different price" — a realized gain the account never made, a tax
bill nobody owes, and two cash flows that never happened.

So the ledger gets two actions that say what really occurred:

* ``transfer_out`` — `quantity` shares left this broker. Carries no proceeds;
  `price` is only ever the market print the statement happened to show.
* ``transfer_in``  — `quantity` shares arrived. `price` is the **cost basis
  per share** the receiving broker reports, which is the basis the shares
  carry when the book has never seen them before.

`normalize` turns those legs back into the shape the replay engines already
understand, and it is the single place that decides what a transfer *means*:

* A leg that pairs with its counterpart — the same security left one broker
  and arrived at another — is dropped from both sides. Nothing happened to
  the position: the lots keep their original dates and their original basis,
  no sale is realized, and no cash moved. This is the whole point.
* An unmatched ``transfer_in`` is an opening balance: shares that entered the
  book from a broker whose history was never imported. They have to become a
  lot or the position does not exist, so it reads as a `buy` at the reported
  basis, dated the day they arrived. The holding period is wrong (the real
  one starts at the original purchase) and that is the best a statement
  listing only a balance can support.
* An unmatched ``transfer_out`` is dropped, leaving the lot open. The shares
  still belong to the account; they are simply at a broker whose statements
  are not in the book yet. Importing that broker later pairs the legs and the
  replay is unchanged, which is what makes the two cases consistent.

Pairing is per ticker and by quantity, not by date order: the destination
broker's statement is often imported before the source broker's, and the
ledger has no column linking one row to another. `stocks.portfolio.custody`
does not use any of this — it replays the legs directly, because *which
broker holds the shares* is exactly the question a netted-out pair erases.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date as _date
from datetime import timedelta as _timedelta

from stocks.portfolio.ledger import Transaction

TRANSFER_IN = "transfer_in"
TRANSFER_OUT = "transfer_out"
TRANSFERS = (TRANSFER_IN, TRANSFER_OUT)

# Below this, a leftover quantity is float noise from the netting, not shares.
_EPS = 1e-9

# Two-letter country code, nine alphanumerics, check digit.
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")

# resolve(ISIN) -> the symbol another broker would use, "" when unknowable.
# stocks.web.logos.yahoo_symbol is the one the app passes (cached on disk, so
# a given ISIN is looked up once ever).
Resolver = Callable[[str], str]


def has_transfers(transactions: list[Transaction]) -> bool:
    """Whether any row is a transfer leg — lets callers skip the pre-pass."""
    return any(t.action in TRANSFERS for t in transactions)


def unmatched_arrivals(transactions: list[Transaction]) -> dict[str, float]:
    """ticker -> incoming shares no outgoing leg accounts for.

    The rule every consumer shares: a `transfer_in` covered by a `transfer_out`
    of the same security is one move of the same shares and changes no share
    count, so only the excess is an opening balance. Matching is on totals per
    ticker rather than date order — the destination broker's statement is
    routinely imported before the source broker's, and a rule that depended on
    which arrived first would answer differently on a re-import.
    """
    incoming: dict[str, float] = defaultdict(float)
    outgoing: dict[str, float] = defaultdict(float)
    for tx in transactions:
        if tx.action == TRANSFER_IN:
            incoming[tx.ticker] += tx.quantity
        elif tx.action == TRANSFER_OUT:
            outgoing[tx.ticker] += tx.quantity
    return {
        ticker: max(0.0, qty - outgoing.get(ticker, 0.0))
        for ticker, qty in incoming.items()
    }


def normalize(transactions: list[Transaction]) -> list[Transaction]:
    """`transactions` with transfer legs resolved into ordinary rows.

    Matched legs disappear, an unmatched `transfer_in` becomes the `buy` that
    opens its position, an unmatched `transfer_out` disappears too (see the
    module docstring). Every other row passes through untouched, the result in
    the (date, id) order every replay sorts into anyway; nothing is mutated,
    and a book with no transfer legs is handed straight back.
    """
    if not has_transfers(transactions):
        return transactions

    # Whatever the outgoing legs cannot cover is an opening balance, spread
    # over the incoming legs oldest-first so a partially covered position
    # opens its lot on the earliest day it could have.
    unmatched = unmatched_arrivals(transactions)

    out: list[Transaction] = []
    for tx in sorted(transactions, key=lambda t: (t.date, t.id or 0)):
        if tx.action == TRANSFER_OUT:
            continue
        if tx.action != TRANSFER_IN:
            out.append(tx)
            continue
        opens = min(tx.quantity, unmatched.get(tx.ticker, 0.0))
        if opens <= _EPS:
            continue  # fully covered by a transfer out: a non-event
        unmatched[tx.ticker] -= opens
        out.append(replace(tx, action="buy", quantity=opens))
    return out


# ------------------------------------------------------ pairing a real move
# Everything above assumes the ledger already says "transfer". Two situations
# leave it saying something else, and both are the normal case rather than an
# edge:
#
#   * the book was imported before the parsers knew the difference, so the
#     departure sits there as an ordinary sale, and
#   * the two brokers spell the same security differently — DEGIRO exports
#     carry no ticker column and book under the ISIN, IBKR uses its symbol —
#     so even two rows that both say "transfer" never meet.
#
# `propose` finds those pairs and says what it would take to join them. It
# proves nothing by itself: the evidence is that the receiving broker reports
# the *cost basis the shares already had*, which a genuine sale-and-repurchase
# would not (there, the new basis is the repurchase price). The caller shows
# the numbers and the account decides — nothing here writes.

# Cost bases this close are the same money, rounded by two brokers.
_BASIS_TOLERANCE = 0.02
# Shares rarely take longer than this to land; beyond it, two unrelated events.
_MAX_DAYS_IN_TRANSIT = 180


@dataclass(frozen=True)
class Move:
    """One departure and one arrival that look like the same shares."""

    quantity: float
    ticker_out: str
    ticker_in: str
    broker_out: str
    broker_in: str
    date_out: str
    date_in: str
    out_ids: tuple[int, ...]
    in_id: int | None
    booked_at: float  # per-share price the departure was recorded at
    basis_out: float  # per-share basis of the lots that left
    basis_in: float  # per-share basis the receiving broker reports
    currency: str

    @property
    def rekey(self) -> bool:
        """Whether accepting this also has to unify the two ticker labels."""
        return self.ticker_out != self.ticker_in

    @property
    def phantom_gain(self) -> float:
        """The gain the book currently reports for shares nobody sold."""
        return (self.booked_at - self.basis_out) * self.quantity


def security_id(tx: Transaction) -> str:
    """What this row is about, across brokers that label it differently.

    The ISIN when one is knowable — the ticker itself in a DEGIRO-style book
    keyed by ISIN, or the one an importer stamped into the note — and the
    ticker otherwise. Two rows sharing this are the same security even when
    one says ``ASML`` and the other ``NL0010273215``.
    """
    if _ISIN.fullmatch(tx.ticker):
        return tx.ticker
    for word in tx.note.upper().split():
        if _ISIN.fullmatch(word):
            return word
    return tx.ticker


def propose(
    transactions: list[Transaction], resolve: Resolver | None = None
) -> list[Move]:
    """Departures and arrivals in `transactions` that are one move of shares.

    A candidate needs all of: the same security, the same share count, an
    arrival that is not earlier than the departure and not half a year later,
    two different brokers, and — the part that makes it evidence rather than a
    guess — an arrival whose reported basis is the basis the departing lots
    carried, not the price the departure was booked at. Ordered by what
    accepting one would correct, largest first.

    "The same security" is the hard half, because the whole situation starts
    with two brokers that name it differently. Rows that already agree (an
    ISIN on both sides, a symbol on both sides, an importer that stamped the
    ISIN into the note) pair on `security_id` alone. Rows imported before any
    of that was recorded — an IBKR balance under its symbol, a DEGIRO history
    under the ISIN, nothing linking them — need the ISIN looked up, and
    `resolve` is that lookup. It is called only for a departure that already
    matches an arrival on every other count, so a book with nothing to repair
    asks nobody anything.
    """
    by_security: dict[str, list[Transaction]] = defaultdict(list)
    for tx in sorted(transactions, key=lambda t: (t.date, t.id or 0)):
        by_security[security_id(tx)].append(tx)

    moves: list[Move] = []
    spare_departures: list[tuple[Transaction, float]] = []
    spare_arrivals: list[Transaction] = []
    for rows in by_security.values():
        found, departures, arrivals = _pair(rows)
        moves += found
        spare_departures += departures
        spare_arrivals += arrivals
    moves += _pair_across_labels(spare_departures, spare_arrivals, resolve)
    moves.sort(key=lambda m: -abs(m.phantom_gain))
    return moves


def _pair(
    rows: list[Transaction],
) -> tuple[list[Move], list[tuple[Transaction, float]], list[Transaction]]:
    """Moves within one security's rows, plus the legs that found no partner.

    The leftovers carry the basis this replay worked out, so the second pass
    across differently-labelled rows does not have to replay anything again.
    """
    arrivals = [t for t in rows if _is_arrival(t)]
    lots = _Basis()
    departures: list[tuple[Transaction, float]] = []  # row, basis/share when it left
    for tx in rows:
        if tx.action == "buy" and not _is_arrival(tx):
            lots.add(tx.quantity, tx.quantity * tx.price + tx.fee)
        elif tx.action in ("sell", TRANSFER_OUT):
            departures.append((tx, lots.take(tx.quantity)))
        elif tx.action == "split" and tx.quantity > 0:
            lots.split(tx.quantity)
    if not arrivals:
        return [], departures, []

    moves: list[Move] = []
    claimed: set[int] = set()
    matched: set[int] = set()
    for a, arrival in enumerate(arrivals):
        for i, (tx, basis) in enumerate(departures):
            if i in claimed or not _same_move(tx, basis, arrival):
                continue
            claimed.add(i)
            matched.add(a)
            moves.append(_move(tx, basis, arrival))
            break
    return (
        moves,
        [d for i, d in enumerate(departures) if i not in claimed],
        [a for i, a in enumerate(arrivals) if i not in matched],
    )


def _pair_across_labels(
    departures: list[tuple[Transaction, float]],
    arrivals: list[Transaction],
    resolve: Resolver | None,
) -> list[Move]:
    """Legs whose brokers spell the security differently.

    Every other test has to pass first — this only settles whether two names
    are one company, and it asks `resolve` about the ISIN rather than trusting
    a quantity that happens to line up.
    """
    if not resolve or not departures or not arrivals:
        return []
    moves: list[Move] = []
    taken: set[int] = set()
    for arrival in arrivals:
        for i, (tx, basis) in enumerate(departures):
            if i in taken or not _same_move(tx, basis, arrival, same_security=False):
                continue
            if not _same_security(tx.ticker, arrival.ticker, resolve):
                continue
            taken.add(i)
            moves.append(_move(tx, basis, arrival))
            break
    return moves


def _same_security(left: str, right: str, resolve: Resolver) -> bool:
    """Whether two ledger labels for a holding name one company.

    Only an ISIN is worth asking about: it is the label a broker export falls
    back on when it has no symbol column, and the one thing that can be turned
    into the symbol another broker used.
    """
    for isin, other in ((left, right), (right, left)):
        if not _ISIN.fullmatch(isin) or _ISIN.fullmatch(other):
            continue
        try:
            symbol = resolve(isin)
        except Exception:  # a lookup that cannot answer proposes nothing
            return False
        if symbol and symbol.upper() == other.upper():
            return True
    return False


def _move(departure: Transaction, basis: float, arrival: Transaction) -> Move:
    return Move(
        quantity=arrival.quantity,
        ticker_out=departure.ticker,
        ticker_in=arrival.ticker,
        broker_out=_broker(departure),
        broker_in=_broker(arrival),
        date_out=departure.date,
        date_in=arrival.date,
        out_ids=(departure.id,) if departure.id is not None else (),
        in_id=arrival.id,
        booked_at=departure.price,
        basis_out=basis,
        basis_in=arrival.price,
        currency=departure.currency,
    )


def _same_move(
    departure: Transaction,
    basis: float,
    arrival: Transaction,
    same_security: bool = True,
) -> bool:
    """Whether these two rows are one parcel of shares changing custodian.

    `same_security` is False when the caller has not established that yet and
    is using this to decide whether the question is even worth asking.
    """
    if abs(departure.quantity - arrival.quantity) > 1e-6:
        return False
    if _broker(departure) == _broker(arrival):
        return False
    if not departure.date <= arrival.date <= _horizon(departure.date):
        return False
    if departure.currency != arrival.currency or basis <= 0 or arrival.price <= 0:
        return False
    # The decisive test: the receiving broker reports the basis the shares
    # already had, where a real sale followed by a real repurchase reports the
    # repurchase price. Both readings have to be on the table for the answer
    # to mean anything — someone who sold at what the shares cost leaves no
    # evidence either way, and a guess there is worse than silence.
    gap = abs(departure.price - basis)
    if gap <= 2 * _BASIS_TOLERANCE * basis:
        return False
    carried = abs(arrival.price - basis)
    return carried <= _BASIS_TOLERANCE * basis and carried < abs(
        arrival.price - departure.price
    )


def _horizon(day: str) -> str:
    return (_date.fromisoformat(day) + _timedelta(days=_MAX_DAYS_IN_TRANSIT)).isoformat()


def _is_arrival(tx: Transaction) -> bool:
    """A row that says shares turned up already owned: an explicit transfer
    in, or the opening balance an importer wrote before the ledger had one."""
    return tx.action == TRANSFER_IN or (
        tx.action == "buy" and "snapshot" in tx.note.lower()
    )


def _broker(tx: Transaction) -> str:
    """First word of the note, the label every importer stamps (fees.broker_of
    reads the same one; imported here would be a cycle)."""
    words = tx.note.split()
    return words[0].lower() if words else "manual"


class _Basis:
    """A ticker's open lots, FIFO, for evidence only.

    Specifically FIFO and not an average: that is what the receiving broker's
    reported cost is computed with, so an averaged number here would miss the
    very match it is looking for — a position whose oldest lots were sold off
    carries a remaining basis nothing like its lifetime average. The real
    replay is `positions.build` under the account's own matching rule; this
    only has to answer "what did the shares that left cost", closely enough to
    tell a carried-over basis from a repurchase price.
    """

    def __init__(self) -> None:
        self.lots: deque[list[float]] = deque()  # [quantity, cost per share]

    def add(self, quantity: float, cost: float) -> None:
        if quantity > 0:
            self.lots.append([quantity, cost / quantity])

    def split(self, ratio: float) -> None:
        for lot in self.lots:
            lot[0] *= ratio
            lot[1] /= ratio

    def take(self, quantity: float) -> float:
        """Cost per share of the oldest `quantity` shares, which then leave."""
        remaining, spent, taken = quantity, 0.0, 0.0
        while remaining > _EPS and self.lots:
            lot = self.lots[0]
            take = min(lot[0], remaining)
            spent += take * lot[1]
            taken += take
            lot[0] -= take
            remaining -= take
            if lot[0] <= _EPS:
                self.lots.popleft()
        return spent / taken if taken > _EPS else 0.0
