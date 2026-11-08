"""The edits a person asks for in words, turned into `edits` operations.

The chat and the Claude connector both let someone say "book these under that
label", "that was a transfer between brokers", "apply the fix you found". They
used to build the operations each its own way and so answered differently: the
connector renamed only rows stored under exactly the label it was given, the
chat also found the company under another broker's spelling and left alone the
rows already under the target. This is the one place the request becomes
operations; what is then planned, committed or refused is `stocks.portfolio.edits`.

Nothing here writes. A request that finds nothing returns nothing (an empty
`Rename.rows`, a missing finding) and the caller says so in its own words;
a request the book cannot honour raises `edits.EditError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from stocks.portfolio import demo, doctor, edits, held, transfers
from stocks.portfolio.fees import broker_of
from stocks.portfolio.ledger import Transaction

# ------------------------------------------------------------------- renaming


@dataclass(frozen=True)
class Rename:
    """The rows a relabel moves, and the operation that moves them."""

    rows: list[Transaction]
    ops: list[dict] = field(default_factory=list)


def rename(
    rows: list[Transaction],
    to: str,
    *,
    label: str = "",
    broker: str = "",
    ids: Sequence[int] = (),
    resolve: transfers.Resolver | None = None,
) -> Rename:
    """Book rows under the label `to`.

    Named by `ids`, the rows are exactly those. Named by `label`, the rows
    stored under exactly that label come first, so renaming "SAN" never sweeps
    up "SAN.PA" because the two share a root; only when none is stored under it
    does the label name a company, found however each broker spelled it
    (`edits.select`). `broker` narrows either. Rows already under `to` are left
    out: relabelling them is no change, and would make a plan of nothing.
    """
    to = to.strip().upper()
    if ids:
        by_id = {t.id: t for t in rows}
        chosen = [i for i in dict.fromkeys(ids)
                  if i not in by_id or by_id[i].ticker != to]
        found = [by_id[i] for i in chosen if i in by_id]
    else:
        want = label.strip().upper()
        if not want:
            return Rename([])
        who = broker.strip().lower()
        found = [t for t in rows if t.ticker == want
                 and (not who or broker_of(t) == who)]
        if not found:
            found = edits.select(rows, edits.Selector(ticker=want, broker=who), resolve)
        found = [t for t in found if t.ticker != to]
        chosen = [t.id for t in found]
    if not chosen:
        return Rename([])
    return Rename(found, [{"op": "relabel", "ids": chosen, "to": to}])


# ------------------------------------------------------------------ transfers


def transfer_ops(
    out_ids: Sequence[int], in_ids: Sequence[int] = (), to: str = ""
) -> list[dict]:
    """Rows booked as sales and purchases, read as shares that changed broker.

    `to` books both legs under one label, for brokers that spelled the
    company differently.
    """
    ops: list[dict] = [{"op": "set_action", "ids": list(out_ids),
                        "action": "transfer_out"}]
    if in_ids:
        ops.append({"op": "set_action", "ids": list(in_ids),
                    "action": "transfer_in"})
    if to.strip():
        ops.append({"op": "relabel", "ids": [*out_ids, *in_ids],
                    "to": to.strip().upper()})
    return ops


def find_transfer(
    rows: list[Transaction],
    ticker: str,
    *,
    broker: str = "",
    to_broker: str = "",
    resolve: transfers.Resolver | None = None,
) -> doctor.Finding | None:
    """The transfer the doctor sees for `ticker` (either leg's label, or the
    bare symbol across venues), optionally between two named brokers."""
    root = ticker.split(".")[0]
    for f in doctor.scan(rows, resolve):
        if f.kind != "transfer":
            continue
        d = f.detail
        named = {d["ticker_out"], d["ticker_in"]}
        if ticker not in named and root not in {n.split(".")[0] for n in named}:
            continue
        if broker and d["broker_out"] != broker:
            continue
        if to_broker and d["broker_in"] != to_broker:
            continue
        return f
    return None


# ---------------------------------------------------------------------- fixes


@dataclass(frozen=True)
class Fix:
    """An edit the book proposes for itself: the doctor's `finding` with its
    fix, or the `sales` an import held back and the ledger can carry now."""

    ops: list[dict]
    finding: doctor.Finding | None = None
    sales: list[Transaction] = field(default_factory=list)


def first_fix(
    findings: Sequence[doctor.Finding], sales: Sequence[held.Held]
) -> Fix | None:
    """The first finding that has a fix; else the held sales; else nothing."""
    fixable = next((f for f in findings if f.fix), None)
    if fixable is not None:
        return Fix(fixable.fix, finding=fixable)
    if sales:
        rows = [h.tx for h in sales]
        return Fix(held.ops(rows), sales=rows)
    return None


def fix_by_key(
    rows: list[Transaction],
    key: str,
    db: Path,
    resolve: transfers.Resolver | None = None,
) -> Fix:
    """The fix a `check_book` finding's key names on the book as it is now.

    Raises `edits.EditError` when the finding is gone, or has no fix because
    only the person can say which rows are right.
    """
    ids = held.ids_in(key)
    if ids is not None:
        sales = held.take(ids, db)
        if sales is None:
            raise edits.EditError(
                "Those sales are not ready any more; run check_book again.")
        return Fix(held.ops(sales), sales=sales)
    found = doctor.by_key(demo.without(rows), key, resolve)
    if found is None:
        raise edits.EditError("No such finding any more; run check_book again.")
    if not found.fix:
        raise edits.EditError(
            "That finding has no fix to apply; it needs the person to say "
            "which rows are right.")
    return Fix(found.fix, finding=found)
