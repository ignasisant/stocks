"""When the central banks decide — the Fed's and the ECB's meeting calendars.

The daily card warns before a rate decision and reports the one that just
happened, and neither bank publishes its calendar in a feed worth a download:
the Fed posts the year ahead on a web page every summer, the ECB a PDF. Both
are fixed long in advance and change only in an emergency, so they live here
as data, next to where they were read from.

Each date is the *decision* day — the day the statement comes out:

* **Fed** — the second day of the two-day FOMC meeting. The statement lands at
  14:00 New York, after the card for that morning has been written, so on the
  day itself the card says "decides today" and the day after it reports.
  Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  (read 2026-09-29; "each meeting date is tentative until confirmed at the
  meeting immediately preceding it").
* **ECB** — the second day of the Governing Council's monetary-policy meeting,
  the Thursday of the press conference. Source:
  https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
  (read 2026-09-29; it lists October 2026 onward — the earlier 2026 dates are
  from the calendar the ECB published for the year).

`tests/test_daily_memory.py` fails once the calendar runs out of meetings
for the year ahead, which is the reminder to add the next one.
"""

from __future__ import annotations

from datetime import date

FED = "fed"
ECB = "ecb"

_FED = (
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    # 2027
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
)

_ECB = (
    # 2026
    "2026-02-05", "2026-03-19", "2026-04-30", "2026-06-11",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
    # 2027
    "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-10",
    "2027-07-22", "2027-09-09", "2027-10-28", "2027-12-16",
)

DECISIONS: dict[str, tuple[date, ...]] = {
    FED: tuple(date.fromisoformat(d) for d in _FED),
    ECB: tuple(date.fromisoformat(d) for d in _ECB),
}

# The policy-rate series each decision moves, on FRED (keyless CSV —
# stocks.data.macro.fred). The Fed sets a range, so both of its bounds; the
# ECB's deposit rate is the one it steers by.
RATE_SERIES: dict[str, tuple[str, ...]] = {
    FED: ("DFEDTARL", "DFEDTARU"),
    ECB: ("ECBDFR",),
}


def next_decision(bank: str, today: date) -> date | None:
    """The bank's next decision day, today included — None past the calendar."""
    return next((d for d in DECISIONS.get(bank, ()) if d >= today), None)


def last_decision(bank: str, today: date) -> date | None:
    """The bank's most recent decision day strictly before today."""
    past = [d for d in DECISIONS.get(bank, ()) if d < today]
    return past[-1] if past else None
