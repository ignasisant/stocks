"""The watchlist row's second read: month, usual swing and the buy zone.

All of it comes off the year of closes the row already has and the reader's
own buy rules, so these are pure functions and tested as such.
"""

from __future__ import annotations

import pytest

from stocks.views import home


def test_the_month_is_21_sessions_back():
    closes = [100.0] * 5 + [80.0] + [90.0] * 20 + [96.0]
    assert home.month_move(closes) == pytest.approx(96.0 / 80.0 - 1)
    assert home.month_move([1.0] * 21) is None, "too short to have a month"


def test_a_move_is_measured_in_the_names_usual_swings():
    calm = [100.0 + (i % 2) for i in range(120)]  # about 1 % a day, up and down
    size = home.move_size(calm, 0.10)
    assert size is not None and size > home.ODD_MOVE_Z
    assert home.move_size(calm, 0.005) < 1
    assert home.move_size(calm[:20], 0.10) is None, "too little history to call usual"
    assert home.move_size(calm, None) is None


def rule(name: str, level: float, state: str = "open", since: str = "2026-11-11"):
    return {"rule": name, "level": level, "state": state, "since": since}


def test_no_rules_no_zone():
    assert home.buy_zone([], [10.0, 11.0]) is None


def test_a_price_rule_the_close_meets_is_in_the_zone_even_before_the_night_check():
    zone = home.buy_zone([rule("buy_below", 11.5)], [12.0, 11.2])
    assert zone["state"] == "met"
    assert zone["rule"] == "buy_below"
    assert zone["gap"] < 0


def test_a_fundamental_rule_met_names_itself_and_counts():
    rules = [rule("buy_below", 650), rule("buy_pe_fwd_below", 15, state="hit")]
    zone = home.buy_zone(rules, [700.0, 702.0])
    assert zone["state"] == "met"
    assert zone["rule"] == "buy_pe_fwd_below"
    assert (zone["met"], zone["rules"]) == (1, 2)


def test_the_closest_price_rule_says_how_near():
    near = home.buy_zone([rule("buy_below", 29)], [31.4])
    assert near["state"] == "near"
    assert near["gap"] == pytest.approx(8.28, abs=0.01)
    far = home.buy_zone([rule("buy_below", 20)], [31.4])
    assert far["state"] == "far"


def test_a_drawdown_rule_reads_in_points_from_the_high():
    closes = [100.0, 90.0, 83.0]  # 17 % off the high, rule at 20
    zone = home.buy_zone([rule("buy_drawdown_high", 20)], closes)
    assert zone["state"] == "near"
    assert zone["gap"] == pytest.approx(3.0)


def test_a_rule_only_the_night_check_reads_is_far_without_a_gap():
    zone = home.buy_zone([rule("buy_pe_fwd_below", 10)], [11.0])
    assert zone["state"] == "far" and zone["gap"] is None
