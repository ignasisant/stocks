"""Crypto cycle figures — the arithmetic a coin's page reads instead of accounts.

Pure functions only: the scan that feeds them is `test_crypto_scan.py`'s
subject, the routes that serve them `test_api_crypto.py`'s.
"""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from stocks.analysis import crypto_market as cm


def _daily(values, end="2026-10-04") -> pd.Series:
    index = pd.date_range(end=end, periods=len(values), freq="D")
    return pd.Series(values, index=index, dtype=float)


def test_from_peak_is_never_positive():
    assert cm.from_peak(40.0, 100.0) == pytest.approx(-0.6)
    # A new high since last night's scan: at the peak, not above it.
    assert cm.from_peak(120.0, 100.0) == 0.0
    assert cm.from_peak(None, 100.0) is None
    assert cm.from_peak(50.0, 0.0) is None
    assert cm.from_peak(float("nan"), 100.0) is None


def test_realized_vol_annualises_over_365_days():
    # Alternating +1% / -1% log moves: daily std is 0.01 (sample std of ±0.01
    # over an even count is a hair above it).
    logs = np.cumsum([0.01 if i % 2 else -0.01 for i in range(31)])
    close = _daily(np.exp(logs) * 100)
    vol = cm.realized_vol(close, 30)
    assert vol == pytest.approx(0.01 * math.sqrt(365), rel=0.05)
    assert cm.realized_vol(close.tail(10), 30) is None


def test_flat_price_has_no_volatility():
    assert cm.realized_vol(_daily([50.0] * 40), 30) == 0.0


def test_mayer_needs_two_hundred_closes():
    assert cm.mayer_multiple(_daily([10.0] * 199)) is None
    close = _daily([10.0] * 199 + [20.0])
    # Mean of the last 200 is (199*10 + 20) / 200 = 10.05.
    assert cm.mayer_multiple(close) == pytest.approx(20 / 10.05)


def test_ratio_200w_reads_weekly_closes():
    days = 7 * 210
    close = _daily([100.0] * (days - 1) + [150.0])
    assert cm.ratio_200w(close) == pytest.approx(1.5, rel=0.01)
    assert cm.ratio_200w(_daily([100.0] * 7 * 150)) is None


def test_relative_return_is_a_ratio_of_growths():
    a = _daily(np.linspace(100, 140, 91))
    b = _daily(np.linspace(100, 120, 91))
    assert cm.relative_return(a, b, 90) == pytest.approx(1.4 / 1.2 - 1)


def test_relative_return_refuses_a_short_history():
    a = _daily(np.linspace(100, 140, 30))
    b = _daily(np.linspace(100, 120, 30))
    assert cm.relative_return(a, b, 90) is None


def test_relative_return_aligns_mismatched_calendars():
    # Coin trades daily, the index fund on weekdays only: the shared days rule.
    coin = _daily(np.linspace(100, 200, 120))
    fund = coin[coin.index.dayofweek < 5] * 0 + 50.0
    out = cm.relative_return(coin, fund, 90)
    assert out is not None and out > 0


def test_halving_phase_counts_from_the_last_halving():
    phase = cm.halving_phase(date(2026, 10, 4))
    assert phase.last == "2024-04-20"
    assert phase.days_since == (date(2026, 10, 4) - date(2024, 4, 20)).days
    assert phase.next_est == "2028-04-15"
    assert 0 < phase.progress < 1
    assert cm.halving_phase(date(2010, 1, 1)) is None


@pytest.mark.parametrize(
    "value,key,tone",
    [
        (0.7, "deep", "green"),
        (0.95, "below", "gray"),
        (1.6, "normal", "gray"),
        (2.4, "stretched", "red"),
    ],
)
def test_mayer_bands(value, key, tone):
    assert cm.mayer_band(value) == cm.Band(key, tone)


@pytest.mark.parametrize(
    "value,key",
    [(10, "extreme_fear"), (30, "fear"), (50, "neutral"), (70, "greed"),
     (90, "extreme_greed")],
)
def test_fear_greed_bands_follow_the_index_own_labels(value, key):
    assert cm.fear_greed_band(value).key == key


def test_funding_is_restated_per_eight_hours():
    # 0.005% every four hours is 0.01% per eight: the resting rate, not half.
    assert cm.per_8h(0.00005, 4) == pytest.approx(0.0001)
    assert cm.per_8h(0.0001, None) == pytest.approx(0.0001)
    assert cm.annualized_funding(0.0001) == pytest.approx(0.1095)


@pytest.mark.parametrize(
    "rate,key",
    [(-0.0001, "negative"), (0.0001, "neutral"), (0.0003, "hot"),
     (0.001, "extreme")],
)
def test_funding_bands(rate, key):
    assert cm.funding_band(rate).key == key


def test_supply_figures():
    assert cm.issued_share(19.8e6, 21e6) == pytest.approx(19.8 / 21)
    assert cm.issued_share(120e6, None) is None
    assert cm.fdv_ratio(300.0, 100.0) == pytest.approx(3.0)
    assert cm.dilution_band(3.0) == cm.Band("heavy", "orange")
    assert cm.dilution_band(1.0).key == "none"
    assert cm.fdv_ratio(None, 100.0) is None
