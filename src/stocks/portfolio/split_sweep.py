"""Write the splits a book is missing, for every name, without a visit.

The Ticker page repairs a missing split when its reader opens that name
(`api.routes.ticker`), so a book whose AMZN was bought before the 2022
20-for-1 stayed wrong on Home, Portfolio and Review for as long as nobody
opened AMZN — the 2026-10-20 triage found one that had for weeks. This runs
the same evidence rule (`corporate.missing_splits`) over the whole book from
the warm cron and writes what it finds through the edit journal, so the
reader's Undo takes it back, and a split taken back is never written again.

A scan asks Yahoo once per name, so it runs only when the book changed since
the last one (row count and highest id), or a week after it. The stamp lives
next to the ledger and in the bucket, because the warm wakes a cold instance.
A scan Yahoo throttled is not stamped: the names it skipped proposed nothing
and must be asked again.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from stocks import atomic, obs, storage
from stocks.data import crypto
from stocks.portfolio import corporate, demo, edits, transfers
from stocks.portfolio.ledger import all_transactions

STAMP = "splits_checked.json"
RECHECK_DAYS = 7


def declined(db: Path | str, ticker: str | None = None) -> set[tuple[str, str]]:
    """(ticker, day) of every split the reader wrote and then undid."""
    want = ticker.upper() if ticker else None
    days: set[tuple[str, str]] = set()
    for change in edits.history(Path(db), limit=500):
        if not change.undone_at:
            continue
        for row in change.changes:
            after = row.after or {}
            name = str(after.get("ticker", "")).upper()
            if (
                row.before is None
                and after.get("action") == "split"
                and (want is None or name == want)
            ):
                days.add((name, str(after.get("date", ""))))
    return days


def _fingerprint(rows: list) -> str:
    return f"{len(rows)}:{max((t.id or 0) for t in rows)}"


def _stamp_path(db: Path) -> Path:
    return db.parent / STAMP


def _checked(db: Path, fingerprint: str, today: date) -> bool:
    path = _stamp_path(db)
    if not path.exists():
        storage.restore(path)
    try:
        stamp = json.loads(path.read_text())
        when = date.fromisoformat(stamp["on"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return stamp.get("fingerprint") == fingerprint and today - when < timedelta(
        days=RECHECK_DAYS
    )


def _stamp(db: Path, fingerprint: str, today: date) -> None:
    path = _stamp_path(db)
    atomic.write_json(path, {"fingerprint": fingerprint, "on": today.isoformat()})
    storage.persist(path)


def repair(
    db: Path | str,
    *,
    splits: corporate.SplitLookup,
    close_on: corporate.CloseLookup,
    throttled=lambda: False,
    today: date | None = None,
) -> int:
    """Write the book's missing, never-declined splits as one undoable edit.

    Returns how many it wrote. A book unchanged since its last scan asks
    nobody. `throttled()` true after the scan leaves it unstamped.
    """
    db = Path(db)
    if not db.exists():
        return 0
    today = today or date.today()
    raw = all_transactions(db)
    if not raw:
        return 0
    fingerprint = _fingerprint(raw)
    if _checked(db, fingerprint, today):
        return 0
    # A coin never splits; asking Yahoo about one is a wasted round trip.
    rows = [
        t
        for t in transfers.relabel(demo.without(raw))
        if not crypto.is_crypto(t.ticker)
    ]
    gaps = []
    if any(t.action == "buy" for t in rows):
        gaps = corporate.missing_splits(
            rows, splits=splits, close_on=close_on, source="sweep"
        )
        refused = declined(db) if gaps else set()
        gaps = [g for g in gaps if (g.ticker.upper(), g.tx.date) not in refused]
    wrote = 0
    if gaps:
        ops = [
            {"op": "add", "row": {k: getattr(g.tx, k) for k in edits.FIELDS}}
            for g in gaps
        ]
        summary = ", ".join(f"{g.ticker} {g.ratio:g}:1 split {g.tx.date}" for g in gaps)
        planned = edits.plan(ops, db)
        edits.commit(ops, planned.token, source="api", summary=summary, path=db)
        wrote = len(gaps)
        for ticker in sorted({g.ticker for g in gaps}):
            obs.event(
                "ledger.splits_repaired",
                n=sum(g.ticker == ticker for g in gaps),
                ticker=ticker,
                via="sweep",
            )
        fingerprint = _fingerprint(all_transactions(db))
    if not throttled():
        _stamp(db, fingerprint, today)
    return wrote
