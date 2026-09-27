"""Technical-momentum scoring — the podium next to comp_scores' one.

Mirrors test_fundamentals.py's comp_scores/comp_medals tests: same "best beats
worst" and "too sparse to qualify" shape, over price/volume signals instead of
valuation and quality KPIs.
"""

import pandas as pd

from stocks.analysis.indicators import macd
from stocks.analysis.technicals import (
    technical_medals,
    technical_scores,
    technical_snapshot,
)


def _prices(drift: float, n: int = 260, volume: float = 1_000_000.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = [100.0 * (1 + drift) ** i for i in range(n)]
    return pd.DataFrame({"Close": closes, "Volume": [volume] * n}, index=idx)


def test_macd_histogram_is_positive_in_a_steady_uptrend():
    _, _, hist = macd(_prices(0.01)["Close"])
    assert hist.iloc[-1] > 0


def test_snapshot_reads_an_uptrend_as_strong_on_every_metric():
    snap = technical_snapshot(_prices(0.01))
    assert snap["trend_pct"] > 0  # SMA50 above SMA200
    assert snap["rsi14"] > 50
    assert snap["macd_hist"] > 0
    assert snap["pct_from_high"] == 0.0  # still compounding up, sitting at its high
    assert snap["roc_63"] > 0


def test_snapshot_reads_a_downtrend_as_weak():
    snap = technical_snapshot(_prices(-0.004))
    assert snap["trend_pct"] < 0
    assert snap["roc_63"] < 0
    assert snap["pct_from_high"] < 0  # off its (first-day) high


def test_a_volume_surge_lifts_the_ratio_above_one():
    df = _prices(0.0, volume=1_000_000.0)
    df.loc[df.index[-20:], "Volume"] = 5_000_000.0
    assert technical_snapshot(df)["vol_ratio"] > 1


def test_a_short_history_qualifies_on_fewer_metrics_not_zero():
    """Too short for SMA200/ROC63/the volume window, but RSI/MACD/52w-high
    still compute off whatever is there."""
    snap = technical_snapshot(_prices(0.01, n=50))
    assert "trend_pct" not in snap and "roc_63" not in snap and "vol_ratio" not in snap
    assert "rsi14" in snap and "macd_hist" in snap and "pct_from_high" in snap


def test_empty_history_snapshots_to_nothing():
    assert technical_snapshot(pd.DataFrame()) == {}


def test_scores_rank_the_stronger_uptrend_first():
    rows = [
        {"ticker": "UP", **technical_snapshot(_prices(0.01))},
        {"ticker": "MID", **technical_snapshot(_prices(0.001))},
        {"ticker": "DOWN", **technical_snapshot(_prices(-0.004))},
    ]
    scores = technical_scores(rows)
    assert scores["UP"] > scores["MID"] > scores["DOWN"]


def test_medals_need_three_qualifiers():
    rows = [
        {"ticker": "UP", **technical_snapshot(_prices(0.01))},
        {"ticker": "MID", **technical_snapshot(_prices(0.001))},
        {"ticker": "DOWN", **technical_snapshot(_prices(-0.004))},
    ]
    assert technical_medals(rows) == {"UP": "🥇", "MID": "🥈", "DOWN": "🥉"}
    assert technical_medals(rows[:2]) == {}


def test_a_sparse_row_never_wins_on_the_one_metric_it_has():
    rows = [
        {"ticker": "UP", **technical_snapshot(_prices(0.01))},
        {"ticker": "MID", **technical_snapshot(_prices(0.001))},
        {"ticker": "DOWN", **technical_snapshot(_prices(-0.004))},
        # Only two of the six metrics -> below the qualifying floor.
        {"ticker": "THIN", "rsi14": 90.0, "macd_hist": 5.0},
    ]
    assert "THIN" not in technical_scores(rows)
