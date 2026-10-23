"""The exchange calendars the earnings calendar marks closed days from.

They are hand-copied from each exchange's published calendar, so what can be
checked is their shape: weekdays only, a venue per listing, and enough days
ahead that the calendar never silently stops marking closures.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stocks.data import market_holidays as mh


def test_every_venue_covers_the_year_ahead():
    """Fails once a calendar runs out — add the next year from the sources in
    stocks/data/market_holidays.py."""
    horizon = date.today() + timedelta(days=60)
    for venue in mh.DAYS:
        last = mh.last_day(venue)
        assert last is not None and last >= horizon, venue


def test_no_closure_falls_on_a_weekend():
    for venue, days in mh.DAYS.items():
        for day in days:
            assert day.weekday() < 5, (venue, day)


@pytest.mark.parametrize(
    ("ticker", "venue"),
    [
        ("AAPL", mh.US),
        ("BRK-B", mh.US),
        ("SAP.DE", mh.XETRA),
        ("NVD.F", mh.XETRA),
        ("ITX.MC", mh.BME),
        ("VOD.L", mh.LSE),
        ("ASML.AS", None),
        ("IE00B4L5Y983", None),
    ],
)
def test_a_listing_reads_its_venue_off_the_suffix(ticker, venue):
    assert mh.venue(ticker) == venue


def test_every_venue_with_a_half_day_has_an_early_close():
    for venue, days in mh.DAYS.items():
        if mh.EARLY in days.values():
            assert venue in mh.EARLY_CLOSE, venue
