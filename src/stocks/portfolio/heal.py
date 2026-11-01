"""Repairs the app makes by itself, once per book.

The doctor (`stocks.portfolio.doctor`) finds mistakes and proposes the edit
that fixes each, but a proposal only helps the reader who opens it. Some
mistakes are the app's own and have one right answer: a Revolut crypto buy
imported before the importer learned that the fee comes out of the coins
(`fee_in_coins`) holds coins nobody received, on every such book alike. Those
are written here from the warm cron, through the edit journal (source
``doctor``) so Import can say what changed and the reader's Undo takes it
back. Each runs once: a repair the reader undid is never written again.

Revolut's stock dividends (`net_dividends`) are booked net with nothing
withheld, and a statement keeps bringing new ones, so that repair is marked
per row rather than per book: a row written, or undone, is never touched
again, and next month's dividend still is.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from stocks import obs, storage
from stocks.data.dividends import DividendHistory
from stocks.portfolio import demo, dividends, doctor, edits, revolut, transfers
from stocks.portfolio.ledger import all_transactions, connect

FEE_IN_COINS = "fee_in_coins"
NET_DIVIDENDS = "net_dividends"


def _done(db: Path, name: str) -> bool:
    with closing(connect(db)) as conn:
        return bool(
            conn.execute("SELECT 1 FROM heals WHERE name = ?", (name,)).fetchone()
        )


def _mark(db: Path, name: str, change: int | None) -> None:
    _mark_all(db, [name], change)


def _mark_all(db: Path, names: list[str], change: int | None) -> None:
    at = datetime.now(UTC).isoformat(timespec="seconds")
    with closing(connect(db)) as conn, conn:
        conn.executemany(
            "INSERT OR REPLACE INTO heals (name, at, change) VALUES (?, ?, ?)",
            [(name, at, change) for name in names],
        )
    storage.persist(db)


def _marked(db: Path, prefix: str) -> set[str]:
    with closing(connect(db)) as conn:
        return {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM heals WHERE name LIKE ?", (f"{prefix}:%",)
            )
        }


def fee_in_coins(db: Path | str) -> edits.Changeset | None:
    """Take the Revolut fee out of the coins it was left in, once.

    Nothing is marked while the book has no such buys, so one imported later
    from an old export is still repaired; once written, never again.
    """
    db = Path(db)
    if not db.exists() or _done(db, FEE_IN_COINS):
        return None
    rows = demo.without(all_transactions(db))
    found = doctor._fee_in_coins([t for t in rows if t.id is not None])
    if not found:
        return None
    f = found[0]
    coins = ", ".join(sorted(f.detail["coins"]))
    summary = f"Revolut fee taken out of {f.detail['buys']} crypto buys ({coins})"
    planned = edits.plan(f.fix, db)
    done = edits.commit(f.fix, planned.token, source="doctor", summary=summary, path=db)
    _mark(db, FEE_IN_COINS, done.id)
    obs.event("ledger.healed", kind=FEE_IN_COINS, rows=len(f.ids))
    return done


def net_dividends(
    db: Path | str,
    histories: Callable[[list[str]], dict[str, DividendHistory]],
) -> edits.Changeset | None:
    """Put back the tax Revolut kept from the dividends it booked net.

    `histories` fetches per-share payment histories for the labels it is
    given (the warm passes the app's cached loader). Only rows the history
    explains are written (`dividends.withheld_at_source`); the rest stay as
    they are and are asked about again next time, when Yahoo may answer.
    """
    db = Path(db)
    if not db.exists():
        return None
    rows = [t for t in demo.without(all_transactions(db)) if t.id is not None]
    seen = _marked(db, NET_DIVIDENDS)
    if not any(
        revolut.net_dividend(t) and f"{NET_DIVIDENDS}:{t.id}" not in seen for t in rows
    ):
        return None
    # Under the labels the histories know: a Revolut code and the symbol
    # another broker spells it with count as one holding.
    shown = transfers.relabel(rows)
    paid = [
        label for t, label in zip(rows, shown, strict=True)
        if revolut.net_dividend(t) and f"{NET_DIVIDENDS}:{t.id}" not in seen
    ]
    found = dividends.withheld_at_source(
        shown, histories(sorted({t.ticker for t in paid})), paid
    )[: edits.MAX_OPS]
    if not found:
        return None
    ops = [
        {"op": "update", "id": w.tx.id,
         "fields": {"price": w.gross, "fee": w.withheld}}
        for w in found
    ]
    names = sorted({w.tx.ticker for w in found})
    summary = (
        f"Withholding put back on {len(ops)} Revolut dividends ({', '.join(names)})"
    )
    planned = edits.plan(ops, db)
    done = edits.commit(ops, planned.token, source="doctor", summary=summary, path=db)
    _mark_all(db, [f"{NET_DIVIDENDS}:{w.tx.id}" for w in found], done.id)
    obs.event("ledger.healed", kind=NET_DIVIDENDS, rows=len(ops))
    return done


def recent(db: Path | str) -> list[tuple[str, edits.Changeset]]:
    """The repairs written here and still standing, newest first, each with
    the name of the repair that wrote it (a per-row mark, `name:id`, counts
    as its repair)."""
    db = Path(db)
    with closing(connect(db)) as conn:
        wrote = {
            r["change"]: r["name"].partition(":")[0]
            for r in conn.execute(
                "SELECT name, change FROM heals WHERE change IS NOT NULL"
            )
        }
    if not wrote:
        return []
    return [
        (wrote[c.id], c)
        for c in edits.history(db, limit=200)
        if c.id in wrote and not c.undone_at
    ]
