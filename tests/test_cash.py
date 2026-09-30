"""A money-market fund's yield off its own price, and the rate it tracks.

Synthetic closes only: an accumulating fund compounding at a known rate has a
known answer, which is the whole test.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stocks.analysis.cash import annualised, is_flat, policy_level
from stocks.api import loaders


def drift(days: int, rate: float, start: float = 100.0) -> pd.Series:
    """Business-day closes compounding at `rate` a year, ending 2026-09-29."""
    index = pd.bdate_range(end="2026-09-29", periods=days)
    elapsed = (index - index[0]).days.to_numpy()
    return pd.Series(start * (1 + rate) ** (elapsed / 365), index=index)


# ------------------------------------------------------------------ annualised


@pytest.mark.parametrize("days", [91, 365])
def test_a_steady_three_percent_reads_as_three_percent(days):
    assert annualised(drift(300, 0.03), days) == pytest.approx(0.03, abs=1e-6)


def test_the_window_is_the_last_one_not_the_whole_series():
    """A rate cut shows in the three-month figure before the yearly one."""
    old, new = drift(200, 0.04), drift(80, 0.02)
    start = old.index[-1] + pd.offsets.BDay()
    new = new.set_axis(pd.bdate_range(start=start, periods=80))
    series = pd.concat([old, new * old.iloc[-1] / new.iloc[0]])
    assert annualised(series, 91) == pytest.approx(0.02, abs=0.002)
    assert annualised(series, 365) > annualised(series, 91)


def test_a_window_the_closes_do_not_cover_has_no_yield():
    """Six weeks of a new listing are not a three-month yield."""
    assert annualised(drift(30, 0.03), 91) is None
    assert annualised(drift(300, 0.03), 365) is not None
    assert annualised(drift(200, 0.03), 365) is None


def test_junk_and_zones_are_ignored():
    series = drift(100, 0.03)
    series.iloc[5] = float("nan")
    series.iloc[6] = 0.0
    series.index = series.index.tz_localize("Europe/Berlin")
    assert annualised(series, 91) == pytest.approx(0.03, abs=1e-6)


def test_too_few_closes_have_no_yield():
    assert annualised(pd.Series(dtype=float), 91) is None
    assert annualised(drift(1, 0.03), 91) is None


# --------------------------------------------------------------------- is_flat


def test_a_pinned_nav_is_flat_and_an_accumulating_one_is_not():
    assert is_flat(drift(260, 0.0, start=1.0))
    assert not is_flat(drift(260, 0.02))
    assert not is_flat(pd.Series(dtype=float))


# ---------------------------------------------------------------- policy rate


def _series(values: list[float], end: str) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)))


def test_the_fed_rate_is_the_middle_of_its_range():
    rates = {
        "DFEDTARL": _series([4.25, 4.0], "2026-09-18"),
        "DFEDTARU": _series([4.5, 4.25], "2026-09-18"),
    }
    level, stamp = policy_level(("DFEDTARL", "DFEDTARU"), rates)
    assert level == pytest.approx(0.04125)
    assert stamp == date(2026, 9, 18)


def test_the_older_print_dates_the_pair():
    rates = {
        "DFEDTARL": _series([4.0], "2026-09-17"),
        "DFEDTARU": _series([4.25], "2026-09-18"),
    }
    assert policy_level(("DFEDTARL", "DFEDTARU"), rates)[1] == date(2026, 9, 17)


def test_a_missing_bound_is_no_rate_rather_than_half_of_one():
    lower_only = {"DFEDTARL": _series([4.0], "2026-09-18")}
    assert policy_level(("DFEDTARL", "DFEDTARU"), lower_only) is None


def test_a_currency_reads_its_own_banks_series(monkeypatch):
    asked = []

    def fred(sids, years):
        asked.append(tuple(sids))
        return {"ECBDFR": _series([2.25, 2.0], "2026-09-17")}

    monkeypatch.setattr("stocks.data.macro.fred_many", fred)
    loaders.policy_rate.cache_clear()
    try:
        expected = ("ecb", pytest.approx(0.02), date(2026, 9, 17))
        assert loaders.policy_rate("eur") == expected
        # No bank mapped: no rate, and nothing asked.
        assert loaders.policy_rate("GBP") is None
    finally:
        loaders.policy_rate.cache_clear()
    assert asked == [("ECBDFR",)]


def test_fred_down_is_no_rate_not_a_failure(monkeypatch):
    def boom(sids, years):
        raise OSError("FRED unreachable")

    monkeypatch.setattr("stocks.data.macro.fred_many", boom)
    loaders.policy_rate.cache_clear()
    try:
        assert loaders.policy_rate("USD") is None
    finally:
        loaders.policy_rate.cache_clear()
