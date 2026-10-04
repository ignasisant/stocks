"""What looks wrong in a book, and the edit that would put it right.

A statement only ever describes one broker, so the mistakes that matter are
the ones two statements make together: shares that changed custodian read as
a sale at one broker and a purchase at the other, one company kept under two
labels because each broker spells it its own way, the same trade imported from
two exports. Each one is invisible row by row and visible in every number
downstream — a gain nobody made, a position held twice, a tax bill nobody owes.
One more is a single statement read the way it was printed: crypto buys whose
quantity still holds the coins the fee took, left over as a position nobody
has once everything is sold.

`scan` reads the ledger and nothing else (plus the label lookup it is given)
and returns `Finding`s, largest first. A finding carries the edit that would
fix it as `stocks.portfolio.edits` operations, so applying one is planning
and committing it like any hand edit: its impact is shown first, it is
journalled, and it can be undone. A finding with no fix is one only the
account can explain — a sale of shares the book never saw arrive.

Nothing here writes, and nothing here decides: every finding is a proposal
the reader accepts or ignores.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from stocks.portfolio import edits, revolut_crypto, transfers
from stocks.portfolio.ledger import Transaction

Kind = Literal["transfer", "two_labels", "oversold", "duplicate", "fee_in_coins"]
KINDS: tuple[Kind, ...] = (
    "transfer", "two_labels", "oversold", "duplicate", "fee_in_coins"
)

# Two fills this close in price on the same day are one trade printed twice.
_SAME_PRICE = 0.005


@dataclass(frozen=True)
class Finding:
    kind: Kind
    ticker: str  # the label the reader knows it by — the one a fix keeps
    ids: tuple[int, ...]  # the rows it is about
    fix: list[dict] = field(default_factory=list)  # edits ops; [] = ask the reader
    detail: dict[str, Any] = field(default_factory=dict)  # the facts, for the copy
    weight: float = 0.0  # what it is worth fixing, in the security's currency

    @property
    def key(self) -> str:
        """Names this finding on this book: the kind and the rows. Rescanning
        a book nobody changed gives the same keys, so a key handed to a reader
        can be applied later by asking again."""
        return f"{self.kind}:{'-'.join(str(i) for i in sorted(self.ids))}"


def scan(
    rows: list[Transaction], resolve: transfers.Resolver | None = None
) -> list[Finding]:
    """Everything that looks wrong in `rows`, the costliest first.

    `resolve` turns a stored label into the symbol it stands for (the app
    passes its cached ISIN and broker-code lookup); without it only labels
    that already agree can be compared.
    """
    rows = [t for t in rows if t.id is not None]
    if not rows:
        return []
    found = _transfers(rows, resolve)
    joined = {(f.detail["ticker_out"], f.detail["currency"]) for f in found}
    found += _two_labels(rows, resolve, joined)
    for f in found:
        if f.kind == "two_labels":
            joined.update((label, f.detail["currency"]) for label in f.detail["labels"])
    found += _oversold(rows, joined)
    found += _duplicates(rows)
    found += _fee_in_coins(rows)
    order = {k: i for i, k in enumerate(KINDS)}
    found.sort(key=lambda f: (-f.weight, order[f.kind]))
    return found


def by_key(rows: list[Transaction], key: str, resolve=None) -> Finding | None:
    """The finding `key` names on this book now, or None once it is gone."""
    return next((f for f in scan(rows, resolve) if f.key == key), None)


# ----------------------------------------------------------------- the kinds


def _transfers(
    rows: list[Transaction], resolve: transfers.Resolver | None
) -> list[Finding]:
    out = []
    for m in transfers.propose(rows, resolve=resolve):
        ids = (*m.out_ids, *((m.in_id,) if m.in_id is not None else ()))
        out.append(
            Finding(
                kind="transfer",
                ticker=m.ticker_in,
                ids=ids,
                fix=transfers.ops(m, rows),
                detail={
                    "ticker_out": m.ticker_out,
                    "ticker_in": m.ticker_in,
                    "quantity": m.quantity,
                    "broker_out": m.broker_out,
                    "broker_in": m.broker_in,
                    "date_out": m.date_out,
                    "date_in": m.date_in,
                    "booked_at": round(m.booked_at, 4),
                    "basis_out": round(m.basis_out, 4),
                    "basis_in": round(m.basis_in, 4),
                    "phantom_gain": round(m.phantom_gain, 2),
                    "currency": m.currency,
                },
                weight=abs(m.phantom_gain),
            )
        )
    return out


def _two_labels(
    rows: list[Transaction],
    resolve: transfers.Resolver | None,
    joined: set[tuple[str, str]],
) -> list[Finding]:
    """One security under two labels: two positions to every replay.

    Only labels a lookup puts on exactly one symbol are joined — never on a
    shared root alone, which is how Santander (``SAN.MC``) and Sanofi
    (``SAN.PA``) would end up one holding. A transfer finding that already
    joins a label leaves it alone here.
    """
    if resolve is None:
        return []
    shown = transfers.relabel(rows)
    ids: dict[tuple[str, str], list[int]] = defaultdict(list)
    cost: dict[tuple[str, str], float] = defaultdict(float)
    for tx, label in zip(rows, shown, strict=True):
        key = (label.ticker, tx.currency)
        ids[key].append(tx.id or 0)
        if tx.action in ("buy", "transfer_in"):
            cost[key] += tx.quantity * tx.price
    by_symbol: dict[tuple[str, str], list[str]] = defaultdict(list)
    for label, currency in ids:
        if (label, currency) in joined:
            continue
        try:
            symbol = (resolve(label) or "").upper()
        except Exception:  # a lookup that cannot answer joins nothing
            continue
        if symbol and not transfers._ISIN.fullmatch(symbol):
            by_symbol[(symbol, currency)].append(label)
    out = []
    for (symbol, currency), labels in by_symbol.items():
        if len(labels) < 2:
            continue
        keep = (
            symbol
            if symbol in labels
            else max(labels, key=lambda lb: (not transfers._ISIN.fullmatch(lb),
                                             len(ids[(lb, currency)])))
        )
        others = sorted(lb for lb in labels if lb != keep)
        moved = [i for lb in others for i in ids[(lb, currency)]]
        out.append(
            Finding(
                kind="two_labels",
                ticker=keep,
                ids=tuple(moved),
                fix=[{"op": "relabel", "ids": moved, "to": keep}],
                detail={"labels": [keep, *others], "symbol": symbol,
                        "currency": currency},
                weight=sum(cost[(lb, currency)] for lb in others),
            )
        )
    return out


def _oversold(rows: list[Transaction], joined: set[tuple[str, str]]) -> list[Finding]:
    """Sales of shares the book never saw arrive. No fix: only the reader
    knows whether a buy is missing, a broker's history was never imported, or
    the sale belongs to another security."""
    shown = transfers.relabel(rows)
    ids: dict[tuple[str, str], list[int]] = defaultdict(list)
    for tx, label in zip(rows, shown, strict=True):
        ids[(label.ticker, tx.currency)].append(tx.id or 0)
    out = []
    for (label, currency), state in edits._replay(rows).items():
        if not state.broken or (label, currency) in joined:
            continue
        out.append(
            Finding(
                kind="oversold",
                ticker=label,
                ids=tuple(ids[(label, currency)]),
                detail={"message": state.broken, "currency": currency},
            )
        )
    return out


def _duplicates(rows: list[Transaction]) -> list[Finding]:
    """The same trade imported from two brokers' exports.

    Same security, day, side, share count and price, at two different brokers
    — two real fills would almost never agree on all of it. The fix deletes
    the copy imported later, which is the one with the higher id.
    """
    shown = transfers.relabel(rows)
    groups: dict[tuple[str, str, str, str], list[Transaction]] = defaultdict(list)
    for tx, label in zip(rows, shown, strict=True):
        if tx.action in ("buy", "sell"):
            groups[(label.ticker, tx.date, tx.action, tx.currency)].append(tx)
    out = []
    for (label, day, action, currency), group in groups.items():
        dropped: set[int] = set()
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if (a.id in dropped or b.id in dropped
                        or transfers._broker(a) == transfers._broker(b)
                        or abs(a.quantity - b.quantity) > 1e-6
                        or abs(a.price - b.price)
                        > _SAME_PRICE * max(a.price, b.price)):
                    continue
                keep, drop = sorted((a, b), key=lambda t: t.id or 0)
                dropped.add(drop.id or 0)
                out.append(
                    Finding(
                        kind="duplicate",
                        ticker=label,
                        ids=(keep.id or 0, drop.id or 0),
                        fix=[{"op": "delete", "ids": [drop.id]}],
                        detail={
                            "date": day,
                            "action": action,
                            "quantity": keep.quantity,
                            "price": keep.price,
                            "currency": currency,
                            "broker_kept": transfers._broker(keep),
                            "broker_dropped": transfers._broker(drop),
                        },
                        weight=keep.quantity * keep.price,
                    )
                )
    return out


# A sale that leaves about the fees' worth of coins behind emptied the
# position: what is left is those coins. Wider than the fee's own spread
# (a price column rounded to two decimals is up to ~10% off on a cheap coin),
# narrow enough that a real partial sale never reads as one.
_FEES_LEFT = (0.6, 1.6)


def _fee_in_coins(rows: list[Transaction]) -> list[Finding]:
    """Revolut crypto buys booked with the fee still in their quantity — one
    finding for them all, since they are one mistake made once per buy.

    The export prints a buy's Quantity as the whole amount paid over the
    price, but the fee comes out of that amount first, so fewer coins arrive
    (`stocks.portfolio.revolut_crypto`, which now books what arrived and marks
    the row ``net``). Imported before that, every buy holds the fee's worth of
    coins nobody received, and "sell all" leaves them on the book.

    Per coin, walking its Revolut rows in order: when a sale leaves about the
    fees' worth of coins behind, the leftover is exactly the coins the fees
    took. They come off the buys that carried them, and each buy's price
    becomes its fee over those coins — which also undoes a Price column
    printed rounded (0.05 € for 0.0536 €). A position still open loses each
    fee's worth at the price booked, the best the book alone can say.
    """
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for tx in rows:
        if tx.note.lower().startswith(_REVOLUT_CRYPTO):
            groups[(tx.ticker, tx.currency)].append(tx)
    fix: list[dict] = []
    removed: dict[str, float] = {}
    closed: list[str] = []
    fees = 0.0
    for (ticker, _currency), txs in sorted(groups.items()):
        txs.sort(key=lambda t: (t.date, t.id or 0))
        net: dict[int, tuple[Transaction, float, float]] = {}  # id: row, qty, price
        held = 0.0
        episode: list[Transaction] = []
        emptied = False
        for i, tx in enumerate(txs):
            if tx.action in ("buy", "transfer_in"):
                held += tx.quantity
                if revolut_crypto.gross_buy(tx):
                    episode.append(tx)
            elif tx.action in ("sell", "transfer_out"):
                held -= tx.quantity
                if not episode:
                    continue
                owed = sum(_fee_coins(t) for t in episode)
                if _FEES_LEFT[0] * owed <= held <= _FEES_LEFT[1] * owed:
                    for t in episode:
                        coins = held * _fee_coins(t) / owed
                        net[t.id or 0] = (t, _less(t, coins), t.fee / coins)
                    _settle(txs[: i + 1], net, episode[-1])
                    held, episode, emptied = 0.0, [], True
                elif held < _FEES_LEFT[0] * owed:
                    episode = []  # emptied some other way; nothing to say
        if episode and held >= sum(_fee_coins(t) for t in episode):
            for t in episode:
                net[t.id or 0] = (t, _less(t, _fee_coins(t)), t.price)
        ops = [
            {"op": "update", "id": t.id, "fields": {
                "quantity": qty, "price": price,
                "note": f"{t.note} {revolut_crypto.NET}"}}
            for t, qty, price in net.values()
        ]
        if not ops or len(fix) + len(ops) > edits.MAX_OPS:
            continue
        if edits._plan(rows, ops).problems:
            continue
        fix += ops
        removed[ticker] = sum(t.quantity - q for t, q, _p in net.values())
        fees += sum(t.fee for t, _q, _p in net.values())
        if emptied:
            closed.append(ticker)
    if not fix:
        return []
    return [
        Finding(
            kind="fee_in_coins",
            # The coin a reader is likeliest to be looking at: one that shows
            # a holding nobody has.
            ticker=(closed or list(removed))[0],
            ids=tuple(sorted(op["id"] for op in fix)),
            fix=fix,
            detail={"coins": removed, "closed": closed, "buys": len(fix),
                    "fees": round(fees, 2)},
            weight=fees,
        )
    ]


_REVOLUT_CRYPTO = "revolut crypto"


def _fee_coins(tx: Transaction) -> float:
    """The coins a buy's fee took, at the price it was booked at."""
    return tx.fee / tx.price


def _less(tx: Transaction, coins: float) -> float:
    """`tx`'s quantity without `coins`, to the decimals the broker printed."""
    digits = repr(tx.quantity).partition(".")[2]
    places = len(digits) if "e" not in digits else 10
    return round(tx.quantity - coins, max(places, 4))


def _settle(
    upto: list[Transaction],
    net: dict[int, tuple[Transaction, float, float]],
    last: Transaction,
) -> None:
    """Leave exactly nothing after the sale that emptied the position.

    Rounding each buy to its printed decimals, then subtracting sales in
    float, can leave a few billionths — one ulp of a 44-million-coin holding
    is 7e-9, and every replay counts more than 1e-9 as still held. Whatever
    is left comes off the last buy."""
    held = 0.0
    for tx in upto:
        qty = net[tx.id][1] if tx.id in net else tx.quantity
        if tx.action in ("buy", "transfer_in"):
            held += qty
        elif tx.action in ("sell", "transfer_out"):
            held -= qty
    if held > 0:
        t, qty, price = net[last.id or 0]
        net[last.id or 0] = (t, qty - held, price)
