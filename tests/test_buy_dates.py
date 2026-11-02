"""Dating a holdings snapshot: the stretches of sessions whose range held a
price, newest first, each offered once at the session whose close sat nearest.
The route is tested with the rest of the import in test_api_import."""

from __future__ import annotations

import pandas as pd

from stocks.portfolio import buy_dates


def bars(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    days, low, high, close = zip(*rows, strict=True)
    return pd.DataFrame(
        {"Low": low, "High": high, "Close": close},
        index=pd.DatetimeIndex(days, name="Date"),
    )


BARS = bars([
    ("2024-01-02", 90, 99, 95),
    ("2024-01-03", 98, 104, 103),  # holds 100
    ("2024-01-04", 99, 102, 100.2),  # holds 100, closest close
    ("2024-01-05", 103, 110, 108),
    ("2024-03-01", 95, 101, 97),  # holds 100 again: a second stretch
    ("2024-03-04", 120, 130, 125),
])


def test_each_stretch_is_offered_once_at_its_nearest_close_newest_first():
    assert buy_dates.runs(BARS, 100) == [
        {"start": "2024-03-01", "end": "2024-03-01", "day": "2024-03-01",
         "close": 97.0, "sessions": 1},
        {"start": "2024-01-03", "end": "2024-01-04", "day": "2024-01-04",
         "close": 100.2, "sessions": 2},
    ]


def test_a_price_the_listing_never_traded_at_offers_no_day():
    assert buy_dates.runs(BARS, 500) == []
    assert buy_dates.runs(BARS, 0) == []
    assert buy_dates.runs(pd.DataFrame(), 100) == []


def test_the_newest_stretches_are_kept_when_there_are_many():
    many = bars([(f"2024-01-{d:02d}", 99 if d % 2 else 200, 101 if d % 2 else 210, 100)
                 for d in range(1, 21)])
    found = buy_dates.runs(many, 100, limit=3)
    assert [run["day"] for run in found] == ["2024-01-19", "2024-01-17", "2024-01-15"]


def test_a_timezone_on_the_bars_does_not_move_the_day():
    local = BARS.copy()
    local.index = local.index.tz_localize("America/New_York")
    assert buy_dates.runs(local, 100)[0]["day"] == "2024-03-01"
