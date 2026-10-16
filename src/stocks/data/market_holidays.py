"""When the exchanges the book trades on are shut, or shut early.

The calendar marks the days an order placed at the open would wait: a full
closure, or a half session that ends hours before the usual close. Like
`macro_calendar`, the exchanges publish these a year or more ahead in a page
or a PDF, never in a feed worth a download, so they live here as data next to
where they were read from:

* **US** (NYSE and Nasdaq share the calendar) — NYSE Group's "2026, 2027 and
  2028 Holiday and Early Closings Calendar" (ICE investor relations, read
  2026-10-16). Early closes are at 13:00 New York.
* **Xetra** — Deutsche Börse's trading calendar (xetra.com, read 2026-10-16).
  Xetra has no half sessions: Christmas Eve and New Year's Eve are closed.
  The German floors (Frankfurt, Stuttgart, Tradegate's quoting) follow it.
* **BME** — Sociedad de Bolsas, "Instrucción Operativa 65/2025, calendario de
  sesiones 2026" (read 2026-10-16). 2027 is not published yet: its rows are
  the standing rule (1 Jan, Good Friday, Easter Monday, 1 May, 25 and 26 Dec,
  half sessions on 24 and 31 Dec) applied to 2027's weekdays.
* **London** — LSE trading calendar for 2026 (read 2026-10-16); 2027 is the
  UK's published bank holidays, with the same 12:30 half sessions on 24 and
  31 December.

`tests/test_market_holidays.py` fails once a venue runs out of days for the
year ahead, which is the reminder to add the next one.
"""

from __future__ import annotations

import re
from datetime import date

US = "us"
XETRA = "xetra"
BME = "bme"
LSE = "lse"

CLOSED = "closed"
EARLY = "early"

_CALENDAR: dict[str, dict[str, str]] = {
    US: {
        # 2026
        "2026-01-01": CLOSED, "2026-01-19": CLOSED, "2026-02-16": CLOSED,
        "2026-04-03": CLOSED, "2026-05-25": CLOSED, "2026-06-19": CLOSED,
        "2026-07-03": CLOSED, "2026-09-07": CLOSED, "2026-11-26": CLOSED,
        "2026-11-27": EARLY, "2026-12-24": EARLY, "2026-12-25": CLOSED,
        # 2027
        "2027-01-01": CLOSED, "2027-01-18": CLOSED, "2027-02-15": CLOSED,
        "2027-03-26": CLOSED, "2027-05-31": CLOSED, "2027-06-18": CLOSED,
        "2027-07-05": CLOSED, "2027-09-06": CLOSED, "2027-11-25": CLOSED,
        "2027-11-26": EARLY, "2027-12-24": CLOSED,
    },
    XETRA: {
        # 2026
        "2026-01-01": CLOSED, "2026-04-03": CLOSED, "2026-04-06": CLOSED,
        "2026-05-01": CLOSED, "2026-12-24": CLOSED, "2026-12-25": CLOSED,
        "2026-12-31": CLOSED,
        # 2027 — 1 May and 25-26 December fall on a weekend.
        "2027-01-01": CLOSED, "2027-03-26": CLOSED, "2027-03-29": CLOSED,
        "2027-12-24": CLOSED, "2027-12-31": CLOSED,
    },
    BME: {
        # 2026 — 26 December is a Saturday.
        "2026-01-01": CLOSED, "2026-04-03": CLOSED, "2026-04-06": CLOSED,
        "2026-05-01": CLOSED, "2026-12-24": EARLY, "2026-12-25": CLOSED,
        "2026-12-31": EARLY,
        # 2027 — the rule, not yet the instruction (see the docstring).
        "2027-01-01": CLOSED, "2027-03-26": CLOSED, "2027-03-29": CLOSED,
        "2027-12-24": EARLY, "2027-12-31": EARLY,
    },
    LSE: {
        # 2026
        "2026-01-01": CLOSED, "2026-04-03": CLOSED, "2026-04-06": CLOSED,
        "2026-05-04": CLOSED, "2026-05-25": CLOSED, "2026-08-31": CLOSED,
        "2026-12-24": EARLY, "2026-12-25": CLOSED, "2026-12-28": CLOSED,
        "2026-12-31": EARLY,
        # 2027
        "2027-01-01": CLOSED, "2027-03-26": CLOSED, "2027-03-29": CLOSED,
        "2027-05-03": CLOSED, "2027-05-31": CLOSED, "2027-08-30": CLOSED,
        "2027-12-24": EARLY, "2027-12-27": CLOSED, "2027-12-28": CLOSED,
        "2027-12-31": EARLY,
    },
}

DAYS: dict[str, dict[date, str]] = {
    venue: {date.fromisoformat(day): kind for day, kind in days.items()}
    for venue, days in _CALENDAR.items()
}

# Yahoo suffix -> the venue whose calendar it trades on. A bare symbol is a
# US listing; a suffix not here (Euronext, Milan, Zurich…) has no calendar yet
# and draws nothing rather than a wrong day.
_SUFFIX: dict[str, str] = {
    "DE": XETRA, "F": XETRA, "SG": XETRA, "MU": XETRA, "BE": XETRA,
    "DU": XETRA, "HM": XETRA, "HA": XETRA,
    "MC": BME,
    "L": LSE, "IL": LSE,
}

# An unlisted broker code held at cost is an ISIN, not a US symbol.
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def venue(ticker: str) -> str | None:
    """The calendar a Yahoo symbol trades on, or None when there is none here.

    Coins never close and are the caller's to drop; an ISIN has no venue.
    """
    symbol = ticker.upper()
    if "." in symbol:
        return _SUFFIX.get(symbol.rsplit(".", 1)[1])
    if _ISIN.match(symbol):
        return None
    return US


def last_day(venue_: str) -> date | None:
    """The latest day the venue's calendar covers — the test's horizon."""
    days = DAYS.get(venue_)
    return max(days) if days else None
