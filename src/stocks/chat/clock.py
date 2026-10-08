"""The chat's "today": the reader's calendar day, not the server's.

The app is Spanish-first and runs on a host whose clock is UTC, so
`date.today()` is a day behind for the first hours of every morning in Madrid.
Every prompt that names a date, and every default a ledger draft books under,
reads it from here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Madrid")


def today() -> date:
    """Today's date in Europe/Madrid."""
    return datetime.now(UTC).astimezone(ZONE).date()


def line() -> str:
    """The sentence that pins the date in a system prompt.

    Stated as authoritative because fetched web pages carry their own dates
    (an article's, a cached copy's, a different timezone's), and a model left
    to choose between them has headed an answer with the wrong day."""
    return (f"Today is {today().isoformat()} (Europe/Madrid). This is the only "
            "current date: dates inside fetched web pages or search results "
            "are when those pages were written, never today's — head an "
            "answer with today's date or none, never with one read off a page")
