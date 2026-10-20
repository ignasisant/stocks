"""The review map's recorded scores: a point a day, thinned to a week."""

from __future__ import annotations

import json
from datetime import date, timedelta

from stocks.data import score_history

TODAY = date(2026, 10, 16)


def test_the_first_read_of_a_day_stands_for_it():
    score_history.record({"amd": (70.0, 40.0)}, TODAY)
    score_history.record({"AMD": (10.0, 10.0), "ESTC": (55.56, 61.04)}, TODAY)
    assert score_history.at("AMD", TODAY, 0) == (70.0, 40.0)
    assert score_history.at("estc", TODAY, 0) == (55.6, 61.0)
    saved = json.loads((score_history.DIR / score_history.NAME).read_text())
    assert saved["AMD"] == {"2026-10-16": [70.0, 40.0]}


def test_a_record_too_far_from_the_day_is_no_record():
    score_history.record({"AMD": (70.0, 40.0)}, TODAY - timedelta(days=5))
    assert score_history.at("AMD", TODAY, 3) is None
    assert score_history.at("AMD", TODAY, 7) == (70.0, 40.0)


def test_the_nearest_record_wins_and_the_earlier_on_a_tie():
    days = {"2026-10-14": [1.0, 1.0], "2026-10-18": [2.0, 2.0], "2026-10-17": [3.0, 3.0]}
    assert score_history.near(days, TODAY, 3) == (3.0, 3.0)
    tie = {"2026-10-14": [1.0, 1.0], "2026-10-18": [2.0, 2.0]}
    assert score_history.near(tie, TODAY, 3) == (1.0, 1.0)


def test_old_days_thin_to_one_a_week_and_go_past_the_keep():
    days = {
        (TODAY - timedelta(days=n)).isoformat(): [float(n), 0.0]
        for n in range(score_history.KEEP_DAYS + 30)
    }
    kept = score_history.thin(days, TODAY)
    since = (TODAY - timedelta(days=score_history.DAILY_DAYS)).isoformat()
    recent = [d for d in kept if d >= since]
    assert len(recent) == score_history.DAILY_DAYS + 1
    old = [date.fromisoformat(d) for d in kept if d not in recent]
    weeks = [d.isocalendar()[:2] for d in old]
    assert len(weeks) == len(set(weeks))
    assert min(old) >= TODAY - timedelta(days=score_history.KEEP_DAYS)
