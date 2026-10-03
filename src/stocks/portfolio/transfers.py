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

from stocks.portfolio import ledger
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


def relabel(transactions: list[Transaction]) -> list[Transaction]:
    """One label per security, so the same shares cannot be two positions.

    Two brokers spell one holding differently — a DEGIRO export has no ticker
    column and books under the ISIN, IBKR uses the symbol and stamps the ISIN
    into the note — and a replay keyed on the ticker then holds those shares
    twice: the departure leaves its lot open under one name while the arrival
    opens a second under the other. The cost basis is counted twice, the
    weights are computed over a book that does not exist, and nothing in the
    numbers says so. `security_id` already knows the two rows are one
    security; this is where that reaches the replay.

    The label that survives is a tradeable symbol whenever any row carries
    one — it is what prices, what the ticker page links to and what the user
    reads. A book whose every row says ISIN keeps the ISIN, and rows that
    share no security id are never merged.
    """
    labels: dict[str, str] = {}
    for tx in transactions:
        sid = security_id(tx)
        current = labels.get(sid)
        if current is None or (
            _ISIN.fullmatch(current) and not _ISIN.fullmatch(tx.ticker)
        ):
            labels[sid] = tx.ticker
    if all(labels[security_id(t)] == t.ticker for t in transactions):
        return transactions  # nothing to rename; hand back the same rows
    return [
        t if labels[security_id(t)] == t.ticker
        else replace(t, ticker=labels[security_id(t)])
        for t in transactions
    ]


def normalize(transactions: list[Transaction]) -> list[Transaction]:
    """`transactions` with one label per security and transfer legs resolved.

    Matched legs disappear, an unmatched `transfer_in` becomes the `buy` that
    opens its position, an unmatched `transfer_out` disappears too (see the
    module docstring). Every other row passes through untouched, the result in
    the (date, id) order every replay sorts into anyway; nothing is mutated,
    and a book with no transfer legs is handed straight back.
    """
    transactions = relabel(transactions)
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
    spare_departures: list[_Leg] = []
    spare_arrivals: list[Transaction] = []
    for rows in by_security.values():
        found, departures, arrivals = _pair(rows)
        moves += found
        spare_departures += departures
        spare_arrivals += arrivals
    moves += _pair_across_labels(spare_departures, spare_arrivals, resolve)
    # Two legs the brokers already printed as a transfer, under one label, are
    # a move the book already reads correctly; offering it would offer nothing.
    by_id = {t.id: t for t in transactions if t.id is not None}
    moves = [m for m in moves if _changes_something(m, by_id)]
    moves.sort(key=lambda m: -abs(m.phantom_gain))
    return moves


def _changes_something(move: Move, by_id: dict[int, Transaction]) -> bool:
    if move.rekey:
        return True
    if move.in_id is not None and by_id.get(move.in_id, None) is not None:
        if by_id[move.in_id].action != TRANSFER_IN:
            return True
    return any(
        (t := by_id.get(i)) is not None and t.action != TRANSFER_OUT
        for i in move.out_ids
    )


def ops(move: Move, transactions: list[Transaction]) -> list[dict]:
    """The edit (`stocks.portfolio.edits`) that books `move` as what it was.

    The departure rows become `transfer_out`, the arrival `transfer_in`, and
    when the brokers spelled the security differently every row under the
    departing label — in the move's currency, plus its splits — takes the
    arriving one, so the lots the shares left with meet the shares that came.
    A label two securities share in different currencies (Revolut's euro
    "ALV" is Allianz, a dollar one Autoliv) only moves its own currency's rows.
    """
    out: list[dict] = [
        {"op": "set_action", "ids": list(move.out_ids), "action": TRANSFER_OUT}
    ]
    if move.in_id is not None:
        out.append({"op": "set_action", "ids": [move.in_id], "action": TRANSFER_IN})
    if move.rekey:
        ids = [
            t.id
            for t in transactions
            if t.id is not None
            and t.ticker == move.ticker_out
            and (t.currency == move.currency or t.action == "split")
        ]
        if ids:
            out.append({"op": "relabel", "ids": ids, "to": move.ticker_in})
    return out


def accept(moves: list[Move], path) -> int:
    """Book each proposed move as what it was, and return how many were.

    The departure stops being a disposal and the arrival stops being a
    purchase; when the two brokers spelled the security differently, both
    labels become one so the replay can see that the shares never left. Every
    surface that offers this repair goes through here — the Import page and
    the assistant both do, and two surfaces offering one repair must not come
    to mean two slightly different things by it.
    """
    if not moves:
        return 0
    # Journalled like any hand edit, so a repair accepted by mistake has an
    # undo. Imported here: `edits` reads this module's labels at import time.
    from stocks.portfolio import edits

    rows = ledger.all_transactions(path)
    planned_ops = [op for m in moves for op in ops(m, rows)]
    planned = edits.plan(planned_ops, path)
    if planned.changes:
        names = sorted({m.ticker_in for m in moves})
        edits.commit(
            planned.ops,
            planned.token,
            source="import",
            summary="transfer: " + ", ".join(names),
            path=path,
        )
    return len(moves)


@dataclass(frozen=True)
class _Leg:
    """Shares leaving: one row, or the same day's rows at one broker summed.

    A broker moving a position of several lots may print one departure per
    lot while the receiving broker prints one arrival for the total, so the
    day's departures are offered as a whole too. `tx` is then a stand-in row
    carrying the summed quantity and the quantity-weighted price.
    """

    tx: Transaction
    basis: float  # per-share basis of the lots that left, FIFO
    ids: tuple[int, ...]


def _pair(
    rows: list[Transaction],
) -> tuple[list[Move], list[_Leg], list[Transaction]]:
    """Moves within one security's rows, plus the legs that found no partner.

    The leftovers carry the basis this replay worked out, so the second pass
    across differently-labelled rows does not have to replay anything again.
    """
    arrivals = [t for t in rows if _may_be_arrival(t)]
    lots = _Basis()
    departures: list[_Leg] = []
    for tx in rows:
        if tx.action == "buy" and not _is_arrival(tx):
            lots.add(tx.quantity, tx.quantity * tx.price + tx.fee)
        elif tx.action in ("sell", TRANSFER_OUT):
            ids = (tx.id,) if tx.id is not None else ()
            departures.append(_Leg(tx, lots.take(tx.quantity), ids))
        elif tx.action == "split" and tx.quantity > 0:
            lots.split(tx.quantity)
    if not arrivals:
        return [], departures, []
    moves, departures, arrivals = _match(departures, arrivals, lambda a, b: True)
    return moves, departures, arrivals


def _match(
    departures: list[_Leg],
    arrivals: list[Transaction],
    same: Callable[[Transaction, Transaction], bool],
    *,
    same_security: bool = True,
) -> tuple[list[Move], list[_Leg], list[Transaction]]:
    """Pair arrivals with single departures first, then with a day's worth.

    `same` settles identity once every other test has passed — it is the one
    that may cost a lookup.
    """
    moves: list[Move] = []
    claimed: set[int] = set()  # departure positions
    matched: set[int] = set()  # arrival positions
    for a, arrival in enumerate(arrivals):
        for i, leg in enumerate(departures):
            if i in claimed or not _same_move(
                leg.tx, leg.basis, arrival, same_security=same_security
            ):
                continue
            if not same(leg.tx, arrival):
                continue
            claimed.add(i)
            matched.add(a)
            moves.append(_move(leg, arrival))
            break
    for a, arrival in enumerate(arrivals):
        if a in matched:
            continue
        for group, leg in _day_groups(departures, claimed):
            if not _same_move(leg.tx, leg.basis, arrival, same_security=same_security):
                continue
            if not same(leg.tx, arrival):
                continue
            claimed.update(group)
            matched.add(a)
            moves.append(_move(leg, arrival))
            break
    return (
        moves,
        [d for i, d in enumerate(departures) if i not in claimed],
        [x for i, x in enumerate(arrivals) if i not in matched],
    )


def _day_groups(
    departures: list[_Leg], claimed: set[int]
) -> list[tuple[list[int], _Leg]]:
    """Unclaimed departures of one label, broker, day and currency, summed —
    only where there are at least two of them."""
    groups: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for i, leg in enumerate(departures):
        if i not in claimed:
            tx = leg.tx
            groups[(tx.ticker, _broker(tx), tx.date, tx.currency)].append(i)
    out: list[tuple[list[int], _Leg]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        legs = [departures[i] for i in members]
        quantity = sum(leg.tx.quantity for leg in legs)
        if quantity <= _EPS:
            continue
        first = legs[0].tx
        stand_in = replace(
            first,
            id=None,
            quantity=quantity,
            price=sum(leg.tx.quantity * leg.tx.price for leg in legs) / quantity,
            # Still a transfer only if every row already said so.
            action=(
                TRANSFER_OUT
                if all(leg.tx.action == TRANSFER_OUT for leg in legs)
                else "sell"
            ),
        )
        basis = sum(leg.tx.quantity * leg.basis for leg in legs) / quantity
        ids = tuple(i for leg in legs for i in leg.ids)
        out.append((members, _Leg(stand_in, basis, ids)))
    return out


def _pair_across_labels(
    departures: list[_Leg],
    arrivals: list[Transaction],
    resolve: Resolver | None,
) -> list[Move]:
    """Legs whose brokers spell the security differently.

    Every other test has to pass first — this only settles whether two names
    are one company, and it asks `resolve` rather than trusting a quantity
    that happens to line up.
    """
    if not departures or not arrivals:
        return []
    return _match(
        departures,
        arrivals,
        lambda out, arrival: _same_security(out.ticker, arrival.ticker, resolve),
        same_security=False,
    )[0]


def _same_security(left: str, right: str, resolve: Resolver | None) -> bool:
    """Whether two ledger labels for a holding name one company.

    Each broker names it its own way: DEGIRO by ISIN, IBKR by its bare symbol
    (``GRF``), Revolut and Yahoo with a venue suffix (``GRF.MC``). Both labels
    go through `resolve` — the ISIN lookup, and the code map for a broker's
    own codes — and two that land on one symbol, or on one root where one side
    names no venue (``GRF`` and ``GRF.MC``), are one company. The root rule is
    only safe because every other test of a move has already passed: the same
    share count, the same currency, two brokers, and the basis carried over.
    A lookup that cannot answer joins nothing.
    """
    try:
        a = _symbol(left, resolve)
        b = _symbol(right, resolve)
    except Exception:  # a lookup that cannot answer proposes nothing
        return False
    if not a or not b or _ISIN.fullmatch(a) or _ISIN.fullmatch(b):
        return False
    if a == b:
        return True
    root_a, _, venue_a = a.partition(".")
    root_b, _, venue_b = b.partition(".")
    return root_a == root_b and not (venue_a and venue_b)


def _symbol(label: str, resolve: Resolver | None) -> str:
    """`label` as a symbol: resolved when there is a lookup, an ISIN only
    through one."""
    label = label.upper()
    if resolve is None:
        return "" if _ISIN.fullmatch(label) else label
    return (resolve(label) or ("" if _ISIN.fullmatch(label) else label)).upper()


def _move(leg: _Leg, arrival: Transaction) -> Move:
    departure = leg.tx
    return Move(
        quantity=arrival.quantity,
        ticker_out=departure.ticker,
        ticker_in=arrival.ticker,
        broker_out=_broker(departure),
        broker_in=_broker(arrival),
        date_out=departure.date,
        date_in=arrival.date,
        out_ids=leg.ids,
        in_id=arrival.id,
        booked_at=departure.price,
        basis_out=leg.basis,
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
    if departure.currency != arrival.currency:
        return False
    if departure.action == TRANSFER_OUT and arrival.action == TRANSFER_IN:
        # Both brokers already said "transfer": there is no sale to tell apart
        # from a move, only two labels that never met.
        return True
    if not _is_arrival(arrival) and arrival.fee > _EPS:
        # An ordinary buy stands in for an arrival only when it cost nothing
        # to make: a custodian change carries no commission, a purchase does.
        return False
    if basis <= 0 or arrival.price <= 0:
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


def _may_be_arrival(tx: Transaction) -> bool:
    """A row the shares might have turned up as: an arrival proper, or an
    ordinary buy a statement printed for shares that only changed broker —
    which `_same_move` then has to prove from the basis it carries."""
    return tx.action in (TRANSFER_IN, "buy")


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
