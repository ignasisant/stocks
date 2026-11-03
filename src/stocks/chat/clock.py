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
            "are when those pages were written, never today's. Never head an "
            "answer with a date")


def session(as_of: str | None) -> str:
    """` <date>` for the session a day move belongs to, said outright when
    that session is not today's.

    A bare date left the model to compare it with today, and before Monday's
    open it called Friday's ServiceNow move "−3 % hoy"."""
    if not isinstance(as_of, str) or not as_of:
        return ""
    if as_of < today().isoformat():
        return f" {as_of} (last completed session, not today)"
    return f" {as_of}"
