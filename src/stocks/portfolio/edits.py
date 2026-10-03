"""Hand edits to a committed ledger: planned, shown, applied whole, undoable.

An import writes what a statement says. What a person later finds wrong in it
— a transfer one broker printed as a sale, a holding two brokers spell two
ways, a row typed in twice — has to be fixable by asking, from the chat, the
Telegram bot or Claude through the connector. Freedom to rewrite the book is
only safe with three promises, and this module is where all of them live so no
surface can skip one:

* **Seen before it happens.** `plan` applies the edit to a copy of the book
  and replays it, so the person reads what it does to their positions and to
  each year's realized gain ("2 positions become 1", "-4,373 EUR realized in
  2026") before anything is written. An edit that would leave a sale the book
  cannot cover is refused here, not discovered later on the Portfolio page.
* **Applied as planned.** The plan carries a token over the edit *and* the
  book it was planned on. `commit` replans inside one write transaction and
  refuses a token that no longer matches — a second tab, an import landing in
  between, a model that rewrote the arguments after the person said yes.
* **Undoable.** Every commit writes the before and after of each row it
  touched into the `changes` table, in the same transaction. `undo` puts the
  before back, by id, as long as nothing has touched those rows since.

Edits are a list of operations, JSON-shaped so a model, an HTTP body and a
stored chat proposal can all carry them:

``{"op": "add", "row": {date, ticker, action, quantity, price, currency, fee, note}}``
``{"op": "update", "id": 12, "fields": {...}}``
``{"op": "delete", "ids": [12, 13]}``
``{"op": "set_action", "ids": [12], "action": "transfer_out"}``
``{"op": "relabel", "ids": [12, 13], "to": "GRF.MC"}``
``{"op": "split_row", "id": 12, "quantity": 30}``

A row an operation creates (`add`, the new half of `split_row`) has no id
until commit; the n-th one is addressed as ``-n`` by the operations after it,
so "split this sale and turn the split-off part into a transfer" is one edit.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path
from typing import Any, Literal

from stocks import storage
from stocks.portfolio import positions, transfers
from stocks.portfolio.ledger import ACTIONS, DB_PATH, Transaction, connect
from stocks.portfolio.ledger import _row_to_tx as _from_sql

FIELDS = ("date", "ticker", "action", "quantity", "price", "currency", "fee", "note")
OPS = ("add", "update", "delete", "set_action", "relabel", "split_row")
SOURCES = ("chat", "telegram", "mcp", "api", "import")

# Actions whose quantity is shares (or a split ratio), so zero is meaningless.
_SHARES = ("buy", "sell", "transfer_in", "transfer_out", "split")

MAX_OPS = 200  # one edit; a whole-book rewrite is an import, not an edit
_EPS = 1e-9


class EditError(ValueError):
    """An edit that cannot be planned: malformed, or aimed at rows that are
    not there. The message is for the person, in plain English."""


class Stale(EditError):
    """The book or the edit changed since the plan was shown."""


class Conflict(EditError):
    """An undo whose rows were changed again after the edit."""


@dataclass(frozen=True)
class RowChange:
    """One row's fate: `before` is None for a new row, `after` for a deleted one."""

    id: int
    before: dict | None
    after: dict | None

    @property
    def kind(self) -> Literal["added", "updated", "deleted"]:
        if self.before is None:
            return "added"
        if self.after is None:
            return "deleted"
        return "updated"


@dataclass(frozen=True)
class Effect:
    """What the edit does to one security, in the currency it trades in."""

    ticker: str
    currency: str
    held_before: float
    held_after: float
    cost_before: float
    cost_after: float
    # Realized gain per calendar year, FIFO, before and after.
    realized_before: dict[str, float]
    realized_after: dict[str, float]


@dataclass
class Plan:
    ops: list[dict]
    changes: list[RowChange]
    effects: list[Effect]
    positions_before: int
    positions_after: int
    # A replay the edit breaks — a sale left without the shares it sells.
    # Problems the book already had are not counted against the edit.
    problems: list[str] = field(default_factory=list)
    token: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.changes) and not self.problems


@dataclass(frozen=True)
class Changeset:
    id: int
    at: str
    source: str
    summary: str
    changes: list[RowChange]
    undone_at: str | None = None


# ------------------------------------------------------------------ planning


def plan(ops: list[dict], path: Path = DB_PATH) -> Plan:
    """What `ops` would do to the book at `path`. Writes nothing."""
    with closing(connect(path)) as conn:
        return _plan(_rows(conn), ops)


def _plan(rows: list[Transaction], ops: list[dict]) -> Plan:
    ops = _checked(ops)
    after, changes = _apply(rows, ops)
    effects, problems, held_before, held_after = _impact(rows, after)
    return Plan(
        ops=ops,
        changes=changes,
        effects=effects,
        positions_before=held_before,
        positions_after=held_after,
        problems=problems,
        token=_token(ops, rows),
    )


def _checked(ops: Any) -> list[dict]:
    if not isinstance(ops, list) or not ops:
        raise EditError("an edit needs at least one operation")
    if len(ops) > MAX_OPS:
        raise EditError(f"an edit takes at most {MAX_OPS} operations")
    out = []
    for op in ops:
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise EditError(f"unknown operation {op!r}; expected one of {OPS}")
        out.append(json.loads(json.dumps(op)))  # a private copy, JSON-clean
    return out


def _apply(
    rows: list[Transaction], ops: list[dict]
) -> tuple[list[Transaction], list[RowChange]]:
    """The book after `ops`, and each touched row's before and after."""
    book: dict[int, Transaction] = {_key(t): t for t in rows if t.id is not None}
    original = dict(book)
    fresh = 0

    def get(tx_id: Any) -> Transaction:
        try:
            key = int(tx_id)
        except (TypeError, ValueError):
            raise EditError(f"{tx_id!r} is not a transaction id") from None
        if key not in book:
            raise EditError(f"transaction {key} is not in the book")
        return book[key]

    def ids_of(op: dict) -> list[Transaction]:
        ids = op.get("ids")
        if not isinstance(ids, list) or not ids:
            raise EditError(f"{op['op']} needs a non-empty list of ids")
        return [get(i) for i in dict.fromkeys(ids)]

    for op in ops:
        kind = op["op"]
        if kind == "add":
            fresh += 1
            book[-fresh] = _row(op.get("row"), tx_id=-fresh)
        elif kind == "update":
            tx = get(op.get("id"))
            fields = op.get("fields")
            if not isinstance(fields, dict) or not fields:
                raise EditError("update needs the fields to change")
            unknown = set(fields) - set(FIELDS)
            if unknown:
                raise EditError(f"unknown fields {sorted(unknown)}; expected {FIELDS}")
            book[_key(tx)] = _row({**_fields(tx), **fields}, tx_id=_key(tx))
        elif kind == "delete":
            for tx in ids_of(op):
                del book[_key(tx)]
        elif kind == "set_action":
            action = str(op.get("action", "")).lower()
            for tx in ids_of(op):
                book[_key(tx)] = _row({**_fields(tx), "action": action}, tx_id=_key(tx))
        elif kind == "relabel":
            to = str(op.get("to", "")).strip().upper()
            if not to:
                raise EditError("relabel needs the label to change to")
            for tx in ids_of(op):
                book[_key(tx)] = _row({**_fields(tx), "ticker": to}, tx_id=_key(tx))
        elif kind == "split_row":
            tx = get(op.get("id"))
            part = _number(op.get("quantity"), "quantity")
            if not 0 < part < tx.quantity - _EPS:
                raise EditError(
                    f"split_row needs a quantity between 0 and {tx.quantity:g}"
                )
            # The fee follows the shares, so the two halves still add up to
            # the row the broker printed.
            share = part / tx.quantity
            book[_key(tx)] = replace(
                tx, quantity=tx.quantity - part, fee=tx.fee * (1 - share)
            )
            fresh += 1
            book[-fresh] = replace(tx, id=-fresh, quantity=part, fee=tx.fee * share)

    changes: list[RowChange] = []
    for tx_id, tx in original.items():
        now = book.get(tx_id)
        if now is None:
            changes.append(RowChange(tx_id, _fields(tx), None))
        elif _fields(now) != _fields(tx):
            changes.append(RowChange(tx_id, _fields(tx), _fields(now)))
    for tx_id in sorted((k for k in book if k < 0), reverse=True):
        changes.append(RowChange(tx_id, None, _fields(book[tx_id])))
    after = sorted(book.values(), key=lambda t: (t.date, abs(t.id or 0)))
    return after, changes


def _key(tx: Transaction) -> int:
    """A stored row's id; every row in a book being edited has one (a new
    row's is negative until commit)."""
    if tx.id is None:  # pragma: no cover — rows read from sqlite carry their id
        raise EditError("a row without an id cannot be edited")
    return tx.id


def _row(raw: Any, *, tx_id: int | None) -> Transaction:
    """A Transaction from a JSON row, checked the way an import checks one."""
    if not isinstance(raw, dict):
        raise EditError("a row needs date, ticker, action and quantity")
    day = str(raw.get("date", "")).strip()
    try:
        _date.fromisoformat(day)
    except ValueError:
        raise EditError(f"{day!r} is not a date (YYYY-MM-DD)") from None
    ticker = str(raw.get("ticker", "")).strip().upper()
    if not ticker or len(ticker) > 40:
        raise EditError(f"{ticker!r} is not a ticker")
    action = str(raw.get("action", "")).strip().lower()
    if action not in ACTIONS:
        raise EditError(f"unknown action {action!r}; expected one of {sorted(ACTIONS)}")
    quantity = _number(raw.get("quantity", 0), "quantity")
    price = _number(raw.get("price", 0), "price")
    fee = _number(raw.get("fee", 0), "fee")
    if action in _SHARES and quantity <= 0:
        raise EditError(f"a {action} needs a quantity above zero")
    currency = str(raw.get("currency") or "USD").strip().upper()
    if not (len(currency) == 3 and currency.isalpha()):
        raise EditError(f"{currency!r} is not a currency code")
    note = str(raw.get("note") or "").strip()[:1000]
    return Transaction(
        date=day, ticker=ticker, action=action, quantity=quantity, price=price,
        currency=currency, fee=fee, note=note, id=tx_id,
    )


def _number(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise EditError(f"{name} must be a number") from None
    if out != out or out < 0 or out == float("inf"):
        raise EditError(f"{name} must be zero or more")
    return out


def _fields(tx: Transaction) -> dict:
    return {k: getattr(tx, k) for k in FIELDS}


def _token(ops: list[dict], rows: list[Transaction]) -> str:
    """The edit and the exact book it was planned on, in 16 hex characters."""
    digest = hashlib.sha256(json.dumps(ops, sort_keys=True).encode())
    for tx in rows:
        digest.update(json.dumps([tx.id, *_fields(tx).values()]).encode())
    return digest.hexdigest()[:16]


# -------------------------------------------------------------------- impact


def _native(amount: float, currency: str, day: str) -> float:
    """No conversion: each security is replayed in the currency it trades in,
    so a plan needs no rate and no network and answers in a blink."""
    return amount


@dataclass
class _State:
    held: float = 0.0
    cost: float = 0.0
    realized: dict[str, float] = field(default_factory=dict)
    broken: str = ""


def _replay(rows: list[Transaction]) -> dict[tuple[str, str], _State]:
    """(label, currency) -> holding, cost and realized gain per year, FIFO.

    One security at a time, like the import preview's gain: a sale the book
    cannot cover breaks that security's answer and nobody else's.
    """
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for tx in transfers.relabel(rows):
        if tx.action in ("dividend", "fee"):
            continue
        groups[(tx.ticker, tx.currency)].append(tx)
    out: dict[tuple[str, str], _State] = {}
    for key, group in groups.items():
        state = _State()
        try:
            held, sales = positions.build(group, to_base=_native, matching="fifo")
        except ValueError as err:
            state.broken = str(err)
        else:
            state.held = sum(p.quantity for p in held)
            state.cost = sum(p.cost for p in held)
            for sale in sales:
                year = sale.sell_date[:4]
                state.realized[year] = state.realized.get(year, 0.0) + sale.gain
        out[key] = state
    return out


def _impact(
    before: list[Transaction], after: list[Transaction]
) -> tuple[list[Effect], list[str], int, int]:
    was, now = _replay(before), _replay(after)
    effects: list[Effect] = []
    problems: list[str] = []
    for key in sorted(set(was) | set(now)):
        a, b = was.get(key, _State()), now.get(key, _State())
        if b.broken and not a.broken:
            problems.append(b.broken)
            continue
        years = set(a.realized) | set(b.realized)
        same = (
            abs(a.held - b.held) < 1e-6
            and abs(a.cost - b.cost) < 0.005
            and all(
                abs(a.realized.get(y, 0.0) - b.realized.get(y, 0.0)) < 0.005
                for y in years
            )
        )
        if same:
            continue
        effects.append(
            Effect(
                ticker=key[0], currency=key[1],
                held_before=round(a.held, 6), held_after=round(b.held, 6),
                cost_before=round(a.cost, 2), cost_after=round(b.cost, 2),
                realized_before={y: round(v, 2) for y, v in sorted(a.realized.items())},
                realized_after={y: round(v, 2) for y, v in sorted(b.realized.items())},
            )
        )

    def open_positions(states: dict[tuple[str, str], _State]) -> int:
        return len({k[0] for k, s in states.items() if s.held > 1e-6})

    return effects, problems, open_positions(was), open_positions(now)


# ------------------------------------------------------------------- writing


def commit(
    ops: list[dict],
    token: str,
    *,
    source: str,
    summary: str = "",
    path: Path = DB_PATH,
) -> Changeset:
    """Apply a planned edit, journalled, if the book is still the one planned on.

    Replans inside one write transaction (`BEGIN IMMEDIATE`, so no other
    writer can land between the check and the write) and refuses unless the
    token matches and the plan has no problems.
    """
    if source not in SOURCES:
        raise EditError(f"unknown source {source!r}")
    with closing(connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = _rows(conn)
            planned = _plan(rows, ops)
            if planned.token != token:
                raise Stale("the book changed since this edit was shown; plan it again")
            if not planned.changes:
                raise EditError("this edit changes nothing")
            if planned.problems:
                raise EditError("; ".join(planned.problems))
            final = _write(conn, planned.changes)
            at = _now()
            cur = conn.execute(
                "INSERT INTO changes (at, source, summary, rows) VALUES (?,?,?,?)",
                (at, source, summary[:300], _dump(final)),
            )
            change_id = int(cur.lastrowid or 0)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    storage.persist(path)
    return Changeset(change_id, at, source, summary[:300], final)


def _write(conn: sqlite3.Connection, changes: list[RowChange]) -> list[RowChange]:
    """Write each change; new rows come back under the ids sqlite gave them."""
    final: list[RowChange] = []
    for ch in changes:
        if ch.after is None:
            conn.execute("DELETE FROM transactions WHERE id = ?", (ch.id,))
            final.append(ch)
        elif ch.before is None:
            cur = conn.execute(
                "INSERT INTO transactions (date, ticker, action, quantity, price,"
                " currency, fee, note) VALUES (?,?,?,?,?,?,?,?)",
                tuple(ch.after[k] for k in FIELDS),
            )
            final.append(RowChange(int(cur.lastrowid or 0), None, ch.after))
        else:
            conn.execute(
                "UPDATE transactions SET date=?, ticker=?, action=?, quantity=?,"
                " price=?, currency=?, fee=?, note=? WHERE id = ?",
                (*(ch.after[k] for k in FIELDS), ch.id),
            )
            final.append(ch)
    return final


def undo(change_id: int, *, path: Path = DB_PATH) -> Changeset:
    """Put back what a changeset replaced, if nothing has touched it since.

    Deleted rows come back under their old ids (AUTOINCREMENT never hands an
    id out twice, so the slot is still free); new rows go; updated rows get
    their old fields. Any row not as the edit left it — edited again, removed
    by an undo of the last import, wiped — refuses the whole undo with a
    `Conflict`, because half an undo is a book nobody wrote.
    """
    with closing(connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            found = conn.execute(
                "SELECT * FROM changes WHERE id = ?", (change_id,)
            ).fetchone()
            if found is None:
                raise LookupError(f"change {change_id} is not in this book's history")
            change = _changeset(found)
            if change.undone_at:
                raise Conflict("this change was already undone")
            current = {t.id: _fields(t) for t in _rows(conn)}
            for ch in change.changes:
                if current.get(ch.id) != ch.after:
                    raise Conflict(
                        f"transaction {ch.id} changed after this edit; "
                        "it can no longer be undone"
                    )
            for ch in change.changes:
                if ch.after is None and ch.before is not None:
                    conn.execute(
                        "INSERT INTO transactions (id, date, ticker, action,"
                        " quantity, price, currency, fee, note)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (ch.id, *(ch.before[k] for k in FIELDS)),
                    )
                elif ch.before is None:
                    conn.execute("DELETE FROM transactions WHERE id = ?", (ch.id,))
                else:
                    conn.execute(
                        "UPDATE transactions SET date=?, ticker=?, action=?,"
                        " quantity=?, price=?, currency=?, fee=?, note=?"
                        " WHERE id = ?",
                        (*(ch.before[k] for k in FIELDS), ch.id),
                    )
            at = _now()
            conn.execute("UPDATE changes SET undone_at = ? WHERE id = ?", (at, change_id))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    storage.persist(path)
    return replace(change, undone_at=at)


def history(path: Path = DB_PATH, limit: int = 50) -> list[Changeset]:
    """The book's edits, newest first."""
    with closing(connect(path)) as conn:
        found = conn.execute(
            "SELECT * FROM changes ORDER BY id DESC LIMIT ?", (max(1, limit),)
        ).fetchall()
    return [_changeset(r) for r in found]


def last_undoable(path: Path = DB_PATH) -> Changeset | None:
    """The newest edit not undone yet — what "undo that" means."""
    with closing(connect(path)) as conn:
        found = conn.execute(
            "SELECT * FROM changes WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _changeset(found) if found else None


def _rows(conn: sqlite3.Connection) -> list[Transaction]:
    found = conn.execute("SELECT * FROM transactions ORDER BY date, id").fetchall()
    return [_from_sql(r) for r in found]


def _changeset(r: sqlite3.Row) -> Changeset:
    return Changeset(
        id=r["id"], at=r["at"], source=r["source"], summary=r["summary"],
        changes=[
            RowChange(c["id"], c["before"], c["after"]) for c in json.loads(r["rows"])
        ],
        undone_at=r["undone_at"],
    )


def _dump(changes: list[RowChange]) -> str:
    return json.dumps([asdict(c) for c in changes])


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ----------------------------------------------------------------- selecting


@dataclass(frozen=True)
class Selector:
    """Which rows a person means, in their words rather than by id.

    Every field narrows; an empty selector selects nothing (an edit aimed at
    "everything" is a wipe, and that has its own guarded route).
    """

    ticker: str = ""
    broker: str = ""
    action: str = ""
    since: str = ""
    until: str = ""
    quantity: float | None = None
    price: float | None = None
    ids: tuple[int, ...] = ()

    def empty(self) -> bool:
        return not (
            self.ticker or self.broker or self.action or self.since or self.until
            or self.quantity is not None or self.price is not None or self.ids
        )


def select(
    rows: list[Transaction],
    sel: Selector,
    resolve: transfers.Resolver | None = None,
) -> list[Transaction]:
    """The rows `sel` describes, oldest first.

    A ticker matches the row's own label, the label the replay gives it (an
    ISIN row answers to its symbol) and the bare symbol across venues
    (``GRF`` finds ``GRF.MC``): the person names the company the way they
    know it, and the rows say it the way each broker printed it. Being
    generous here is safe because a selection is always shown, row by row,
    before anything is done to it. `resolve` (ISIN -> symbol) lets a row booked
    under an ISIN answer to the symbol another broker used for it.
    """
    if sel.empty():
        return []
    labelled = transfers.relabel(rows)
    want = sel.ticker.strip().upper()
    out = []
    for tx, shown in zip(rows, labelled, strict=True):
        if sel.ids and tx.id not in sel.ids:
            continue
        if want and not _names(want, tx, shown.ticker, resolve):
            continue
        if sel.broker and transfers._broker(tx) != sel.broker.strip().lower():
            continue
        if sel.action and tx.action != sel.action.strip().lower():
            continue
        if sel.since and tx.date < sel.since:
            continue
        if sel.until and tx.date > sel.until:
            continue
        if sel.quantity is not None and abs(tx.quantity - sel.quantity) > 1e-6:
            continue
        if sel.price is not None and abs(tx.price - sel.price) > max(
            0.005, 0.005 * sel.price
        ):
            continue
        out.append(tx)
    return out


def _names(
    want: str, tx: Transaction, label: str, resolve: transfers.Resolver | None
) -> bool:
    sid = transfers.security_id(tx)
    known = {tx.ticker, label, sid}
    if resolve and transfers._ISIN.fullmatch(sid):
        try:
            known.add((resolve(sid) or "").upper())
        except Exception:  # a lookup that cannot answer just matches less
            pass
    if want in known:
        return True
    root = want.split(".")[0]
    return root in {k.split(".")[0] for k in known if k}
