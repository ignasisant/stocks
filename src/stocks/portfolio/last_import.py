"""Record of the most recent statement import (data/last_import.json).

Stores which ledger rows the last commit inserted, so the web Import page can
survive a reload (show what was imported without a re-upload) and undo exactly
that batch — "clear last import" — without touching the rest of the ledger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from stocks import userstore
from stocks.config import DATA_DIR

RECORD_PATH = DATA_DIR / "last_import.json"


@dataclass
class ImportRecord:
    filename: str
    imported_at: str  # ISO-8601 UTC
    tx_ids: list[int]
    wiped: bool = False  # ledger was wiped right before this import
    platform: str = "revolut"  # platforms.py key; default covers pre-field records


def imported_on(record: ImportRecord | None) -> str | None:
    """The calendar day (UTC, YYYY-MM-DD) of the last import, or None.

    The one reading of "last import" every page shows: the Import rail and the
    Profile summary both take this date rather than each slicing the stamp.
    """
    stamp = record.imported_at if record else ""
    return stamp[:10] if len(stamp) >= 10 and stamp[4] == "-" else None


def save(record: ImportRecord, path: Path = RECORD_PATH) -> None:
    userstore.write(path, asdict(record))


def load(path: Path = RECORD_PATH) -> ImportRecord | None:
    """The last import record, or None if absent/corrupt."""
    stored = userstore.read(path)
    try:
        return ImportRecord(**stored) if stored else None
    except TypeError:
        return None


def forget(path: Path = RECORD_PATH) -> None:
    userstore.remove(path)
