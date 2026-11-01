"""Sales an import held back, and the statements worth reading again.

An import quarantines a sale larger than the position it sells from
(`validate.oversell`): the shares were never seen arriving, so writing the
sale would take the position below zero. Most of the time the missing piece
turns up later — a split written by the sweep (`split_sweep`), a transfer the
reader paired, the other broker's statement — and until 2026-10 the sale was
gone by then: the reader had to know to upload the same file again. Now the
commit keeps it here, and Import offers it back the moment the book can carry
it, through the same replay that refused it.

Books imported before that lost theirs for good, and the shape they were left
in is recognisable: a split written after a broker's last import, on a name
that broker still shows open. Re-uploading that statement is safe (rows the
book has are dropped as duplicates) and is the only way to recover the sale,
so Import says so until the reader does it or waves it off.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from stocks import storage
from stocks.portfolio import validate
from stocks.portfolio.fees import broker_of
from stocks.portfolio.ledger import Transaction, all_transactions, connect

OVERSELL = "validate.oversell"


@dataclass(frozen=True)
class Held:
    id: int
    at: str
    tx: Transaction


@dataclass(frozen=True)
class Reupload:
    broker: str
    ticker: str
    split_date: str

    @property
    def key(self) -> str:
        return f"{self.broker}:{self.ticker}:{self.split_date}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def keep(checked: list[validate.Checked], broker: str, path: Path) -> int:
    """Store the rows an import refused only for overselling, stamped with the
    broker they came from. A row already held is not held twice. Returns how
    many it stored."""
    rows = [
        c.tx for c in checked if c.errors and all(i.key == OVERSELL for i in c.errors)
    ]
    if not rows:
        return 0
    from stocks.portfolio import platforms

    rows = platforms.stamp_broker(rows, broker)
    have = {validate._dupe_key(h.tx) for h in held(path)}
    fresh = [t for t in rows if validate._dupe_key(t) not in have]
    if not fresh:
        return 0
    at = _now()
    with closing(connect(path)) as conn, conn:
        conn.executemany(
            "INSERT INTO held_back "
            "(at, date, ticker, action, quantity, price, currency, fee, note) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    at,
                    t.date,
                    t.ticker,
                    t.action,
                    t.quantity,
                    t.price,
                    t.currency,
                    t.fee,
                    t.note,
                )
                for t in fresh
            ],
        )
    storage.persist(path)
    return len(fresh)


def held(path: Path) -> list[Held]:
    with closing(connect(path)) as conn:
        rows = conn.execute("SELECT * FROM held_back ORDER BY date, id").fetchall()
    return [
        Held(
            id=r["id"],
            at=r["at"],
            tx=Transaction(
                date=r["date"],
                ticker=r["ticker"],
                action=r["action"],
                quantity=r["quantity"],
                price=r["price"],
                currency=r["currency"],
                fee=r["fee"],
                note=r["note"],
            ),
        )
        for r in rows
    ]


def drop(ids: list[int], path: Path) -> int:
    if not ids:
        return 0
    with closing(connect(path)) as conn, conn:
        cur = conn.execute(
            f"DELETE FROM held_back WHERE id IN ({','.join('?' * len(ids))})", ids
        )
        removed = cur.rowcount
    storage.persist(path)
    return removed


def ready(path: Path) -> list[Held]:
    """The held rows the book can carry now, in date order.

    Rows the ledger holds by now (the reader typed the sale, or re-uploaded the
    statement) are dropped from the shelf on the way: they are done. Each sale
    is replayed with the other held ones, so two sales of one position are
    offered only as far as it reaches.
    """
    shelf = held(path)
    if not shelf:
        return []
    ledger = all_transactions(path)
    seen = {validate._loose_key(t) for t in ledger}
    done = [h.id for h in shelf if validate._loose_key(h.tx) in seen]
    if done:
        drop(done, path)
    shelf = [h for h in shelf if h.id not in done]
    return [h for h, ok in zip(shelf, _carried(ledger, shelf), strict=True) if ok]


def _carried(ledger: list[Transaction], shelf: list[Held]) -> list[bool]:
    checked = [validate.Checked(tx=h.tx) for h in shelf]
    short = {id(c) for c, _q in validate._replay(checked, ledger)}
    return [id(c) not in short for c in checked]


def take(ids: list[int], path: Path) -> list[Transaction] | None:
    """The rows `ids` names, if the book can carry every one of them together;
    None when one is gone or would oversell again."""
    shelf = {h.id: h for h in held(path)}
    if not ids or any(i not in shelf for i in ids):
        return None
    picked = [shelf[i] for i in sorted(ids, key=lambda i: (shelf[i].tx.date, i))]
    if not all(_carried(all_transactions(path), picked)):
        return None
    return [replace(h.tx) for h in picked]


# The chat and the connector name a set of ready sales as one finding, so the
# reader's yes is to the rows they were shown.
KEY = "held:"


def key_of(sales: list[Held]) -> str:
    return KEY + ",".join(str(h.id) for h in sales)


def ids_in(key: str) -> list[int] | None:
    """The held ids a `key_of` key names, or None when it is not one."""
    if not key.startswith(KEY):
        return None
    try:
        return [int(i) for i in key.removeprefix(KEY).split(",") if i]
    except ValueError:
        return None


def ops(rows: list[Transaction]) -> list[dict]:
    """The edit that writes held rows as they were read (`edits.plan` ops).
    Once in the ledger, `ready` takes them off the shelf."""
    from stocks.portfolio import edits

    return [{"op": "add", "row": edits._fields(t)} for t in rows]


# ------------------------------------------------------------ broker records
def seen_broker(broker: str, path: Path) -> None:
    """Record that `broker` was imported just now, and how far the ledger
    reached after it."""
    if not broker:
        return
    with closing(connect(path)) as conn, conn:
        top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM transactions").fetchone()[0]
        conn.execute(
            "INSERT INTO imported_brokers (broker, at, top_id) VALUES (?,?,?) "
            "ON CONFLICT(broker) DO UPDATE SET at = excluded.at, "
            "top_id = excluded.top_id",
            (broker.lower(), _now(), top),
        )
    storage.persist(path)


def _tops(path: Path) -> dict[str, int]:
    with closing(connect(path)) as conn:
        return {
            r["broker"]: r["top_id"]
            for r in conn.execute("SELECT broker, top_id FROM imported_brokers")
        }


def dismissed(path: Path) -> set[str]:
    with closing(connect(path)) as conn:
        return {
            r["name"].removeprefix("reupload:")
            for r in conn.execute("SELECT name FROM heals WHERE name LIKE 'reupload:%'")
        }


def dismiss(key: str, path: Path) -> None:
    with closing(connect(path)) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO heals (name, at) VALUES (?, ?)",
            (f"reupload:{key}", _now()),
        )
    storage.persist(path)


def reuploads(rows: list[Transaction], path: Path) -> list[Reupload]:
    """Statements that may hold a sale the book lost: per broker and name, a
    split written after that broker's last import, on shares it bought before
    the split and still shows open. One per broker and name, latest split."""
    tops = _tops(path)
    gone = dismissed(path)
    splits = [t for t in rows if t.action == "split" and t.quantity > 0 and t.id]
    if not splits:
        return []
    out: dict[tuple[str, str], Reupload] = {}
    by: dict[tuple[str, str], list[Transaction]] = {}
    for t in rows:
        if t.action in ("buy", "sell", "transfer_in", "transfer_out"):
            by.setdefault((broker_of(t), t.ticker), []).append(t)
    for (broker, ticker), trades in by.items():
        if broker in ("manual", "demo"):
            continue
        top = tops.get(broker, max(t.id or 0 for t in trades))
        for s in sorted((s for s in splits if s.ticker == ticker), key=lambda s: s.date):
            if (s.id or 0) <= top:
                continue
            if not any(t.action == "buy" and t.date < s.date for t in trades):
                continue
            if _open(trades, splits, ticker) <= 1e-6:
                continue
            hint = Reupload(broker=broker, ticker=ticker, split_date=s.date)
            if hint.key not in gone:
                out[(broker, ticker)] = hint
    return sorted(out.values(), key=lambda r: (r.broker, r.ticker))


def _open(trades: list[Transaction], splits: list[Transaction], ticker: str) -> float:
    events = sorted(
        [*trades, *(s for s in splits if s.ticker == ticker)],
        key=lambda t: (t.date, t.id or 0),
    )
    q = 0.0
    for t in events:
        if t.action in ("buy", "transfer_in"):
            q += t.quantity
        elif t.action in ("sell", "transfer_out"):
            q -= t.quantity
        elif t.action == "split":
            q *= t.quantity
    return q
