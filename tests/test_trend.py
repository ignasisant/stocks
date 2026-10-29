"""The trend read: 200-session average, 12-1 momentum, 52w high, home index."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stocks.analysis import trend
from stocks.analysis.indicators import atr


def _closes(values, start="2024-01-02", freq="B") -> pd.Series:
    return pd.Series(
        np.asarray(values, dtype=float),
        index=pd.date_range(start, periods=len(values), freq=freq),
    )


def _frame(close: pd.Series, swing: float = 0.01) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * (1 + swing),
            "Low": close * (1 - swing),
            "Close": close,
            "Volume": 1_000.0,
        }
    )


def _geometric(n: int, daily: float, start: float = 100.0) -> np.ndarray:
    return start * (1 + daily) ** np.arange(n)


# ---------------------------------------------------------------- benchmark


@pytest.mark.parametrize(
    ("symbol", "index"),
    [
        ("SAN.MC", "^IBEX"),
        ("SAP.DE", "^GDAXI"),
        ("SIE.F", "^GDAXI"),
        ("MC.PA", "^FCHI"),
        ("SHEL.L", "^FTSE"),
        ("7203.T", "^N225"),
        ("0700.HK", "^HSI"),
        ("ASML.AS", "^STOXX50E"),
        ("ENI.MI", "^STOXX50E"),
        ("AAPL", "^GSPC"),
        ("BRK-B", "^GSPC"),
        ("aapl", "^GSPC"),
    ],
)
def test_benchmark_by_listing_suffix(symbol, index):
    bench = trend.benchmark_for(symbol)
    assert bench is not None and bench.ticker == index


@pytest.mark.parametrize("symbol", ["BTC-EUR", "ETH-USD", "^GSPC", "NESN.SW", ""])
def test_no_benchmark_for_coins_indices_and_unmapped_markets(symbol):
    assert trend.benchmark_for(symbol) is None


def test_foreign_company_on_a_german_floor_reads_against_its_own_market():
    bench = trend.benchmark_for("APC.DE", country="United States")
    assert bench is not None and bench.ticker == "^GSPC"
    # A German company stays on the DAX, and an unknown country falls back to it.
    assert trend.benchmark_for("SAP.DE", country="Germany").ticker == "^GDAXI"
    assert trend.benchmark_for("XYZ.DE", country="Atlantis").ticker == "^GDAXI"
    # The override is for German floors only: a Paris line stays on the CAC.
    assert trend.benchmark_for("MC.PA", country="United States").ticker == "^FCHI"


# ---------------------------------------------------------------- pieces


def test_momentum_skips_the_last_month():
    # Flat for a year, then up 10 % over the last month: 12-1 ignores that month.
    flat = _closes([100.0] * 260 + list(np.linspace(100, 110, 21)))
    assert trend.momentum_12_1(flat) == pytest.approx(0.0, abs=1e-9)
    rising = _closes(_geometric(300, 0.001))
    mom = trend.momentum_12_1(rising)
    assert mom is not None and mom > 0.2


def test_momentum_needs_a_year_of_history():
    assert trend.momentum_12_1(_closes(_geometric(200, 0.001))) is None
    assert trend.momentum_12_1(pd.Series(dtype=float)) is None


def test_momentum_reads_calendar_months_for_a_coin():
    # A coin trades every day: 365 bars make a year, as 252 sessions do for a share.
    coin = _closes(_geometric(400, 0.001), freq="D")
    share = _closes(_geometric(280, 0.001 * 365 / 252), freq="B")
    assert trend.momentum_12_1(coin) == pytest.approx(
        trend.momentum_12_1(share), rel=0.05
    )


def test_from_high_reads_only_the_last_year():
    # A peak 18 months back no longer counts as the high.
    values = [200.0] + [100.0] * 400 + [90.0]
    s = _closes(values)
    assert trend.from_high_52w(s) == pytest.approx(-0.1)


def test_excess_return_aligns_dates_across_calendars():
    stock = _closes(_geometric(300, 0.002))
    # The index trades on a different calendar (every day) and rose less.
    bench = _closes(_geometric(450, 0.0005), freq="D")
    rs = trend.excess_return(stock, bench, 6)
    end = stock.index[-1]
    start = end - pd.DateOffset(months=6)
    own = stock.iloc[-1] / stock.asof(start) - 1
    market = bench.asof(end) / bench.asof(start) - 1
    assert rs == pytest.approx(own - market)
    assert rs > 0


def test_excess_return_none_when_the_index_is_too_short():
    stock = _closes(_geometric(300, 0.002))
    bench = _closes(_geometric(20, 0.001), start="2025-01-01")
    assert trend.excess_return(stock, bench, 12) is None


def test_atr_counts_overnight_gaps():
    close = _closes([100.0] * 20 + [120.0] * 20)
    df = _frame(close, swing=0.0)
    # No intraday range at all, one 20-point gap: ATR is above zero after it.
    values = atr(df, 14)
    assert values.iloc[19] == pytest.approx(0.0)
    assert values.iloc[20] > 0


# ---------------------------------------------------------------- the read


def test_uptrend():
    read = trend.trend_read(_frame(_closes(_geometric(400, 0.001))))
    assert read.state == "up"
    assert read.sma200_rising is True
    assert read.pct_vs_sma200 > 0
    assert read.mom_12_1 > 0
    assert read.pct_from_high == pytest.approx(0.0)
    assert read.sessions == 400
    assert 0 < read.atr_pct < 0.05
    assert read.rs_6m is None and read.bench is None


def test_downtrend():
    read = trend.trend_read(_frame(_closes(_geometric(400, -0.001))))
    assert read.state == "down"
    assert read.sma200_rising is False
    assert read.pct_vs_sma200 < 0
    assert read.mom_12_1 < 0
    assert read.pct_from_high < -0.2


def test_mixed_when_price_breaks_under_a_rising_average():
    values = list(_geometric(380, 0.001)) + list(_geometric(20, -0.01, start=146.0))
    read = trend.trend_read(_frame(_closes(values)))
    assert read.price < read.sma200
    assert read.sma200_rising is True
    assert read.state == "mixed"


def test_short_history_is_none_not_zero():
    read = trend.trend_read(_frame(_closes(_geometric(120, 0.001))))
    assert read.price is not None
    assert read.sma200 is None
    assert read.state is None
    assert read.mom_12_1 is None
    assert read.pct_vs_sma200 is None
    assert read.sessions == 120


def test_empty_frame():
    assert trend.trend_read(pd.DataFrame()) == trend.TrendRead()
    blank = pd.DataFrame({"Close": [np.nan, np.nan]})
    assert trend.trend_read(blank) == trend.TrendRead()


def test_relative_strength_against_the_home_index():
    stock = _closes(_geometric(400, 0.002))
    index = _closes(_geometric(400, 0.0005))
    bench = trend.benchmark_for("SAN.MC")
    read = trend.trend_read(_frame(stock), index, bench)
    assert read.bench == "^IBEX" and read.bench_name == "IBEX 35"
    assert read.rs_6m > 0 and read.rs_12m > read.rs_6m


def test_timezone_aware_index_is_flattened():
    close = _closes(_geometric(300, 0.001))
    close.index = close.index.tz_localize("Europe/Madrid")
    read = trend.trend_read(_frame(close))
    assert read.mom_12_1 is not None and read.state == "up"


# ---------------------------------------------------------------- breadth


def test_below_sma_share_counts_only_measurable_names():
    up = list(_geometric(250, 0.001))
    down = list(_geometric(250, -0.001))
    young = list(_geometric(50, -0.01))
    assert trend.below_sma_share({"A": up, "B": down, "C": down, "D": young}) == (2, 3)
    assert trend.below_sma_share({}) == (0, 0)
    assert trend.below_sma(young) is None
