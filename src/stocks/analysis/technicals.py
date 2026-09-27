"""Technical-momentum scoring for a sector cohort — the podium next to comps.

Deliberately separate from `fundamentals.comp_scores`: valuation/quality and
price momentum answer different questions, and blending them into one score
would make neither legible. Shares its ranking machinery with `fundamentals`
through `ranking.py` rather than duplicating it.
"""

from __future__ import annotations

import pandas as pd

from stocks.analysis import ranking
from stocks.analysis.indicators import macd, rsi, sma

# Every key `technical_snapshot` can produce, in the order an API/table wants
# them.
TECH_METRIC_ORDER = ("trend_pct", "rsi14", "macd_hist", "pct_from_high", "roc_63",
                     "vol_ratio")

# All higher-is-better: there is no metric here where a smaller number is the
# more attractive one. "Crossed the SMA50/200 upward" is read as a continuous
# spread (trend_pct) rather than a boolean recent-cross flag — ranking a
# cohort on a mostly-0/1 signal is degenerate, the spread still rewards a
# fresh, strong golden cross over a stale or marginal one.
_TECH_HIGHER_BETTER = frozenset(TECH_METRIC_ORDER)
# A ticker missing most of the six can't win on the one or two it has.
_TECH_MIN_METRICS = 4

_ROC_WINDOW = 63
_VOL_SHORT = 20
_VOL_LONG = 90


def technical_snapshot(df: pd.DataFrame) -> dict:
    """The six technical metrics off one ticker's OHLCV frame.

    A metric is absent (not zero, not a crash) when the frame is too short for
    it — a recently-listed name simply scores on whichever ones it has.
    """
    if df.empty or "Close" not in df:
        return {}
    close = df["Close"].dropna()
    if close.empty:
        return {}
    out: dict[str, float] = {}

    sma50, sma200 = sma(close, 50), sma(close, 200)
    if pd.notna(sma50.iloc[-1]) and pd.notna(sma200.iloc[-1]) and sma200.iloc[-1]:
        out["trend_pct"] = float(sma50.iloc[-1] / sma200.iloc[-1] - 1)

    rsi14 = rsi(close, 14)
    if pd.notna(rsi14.iloc[-1]):
        out["rsi14"] = float(rsi14.iloc[-1])

    _, _, hist = macd(close)
    if pd.notna(hist.iloc[-1]):
        out["macd_hist"] = float(hist.iloc[-1])

    high = close.max()
    if high:
        out["pct_from_high"] = float(close.iloc[-1] / high - 1)

    if len(close) > _ROC_WINDOW and close.iloc[-_ROC_WINDOW - 1]:
        out["roc_63"] = float(close.iloc[-1] / close.iloc[-_ROC_WINDOW - 1] - 1)

    if "Volume" in df and len(df) >= _VOL_LONG:
        vol = df["Volume"].dropna()
        long_avg = vol.tail(_VOL_LONG).mean()
        if len(vol) >= _VOL_LONG and long_avg:
            out["vol_ratio"] = float(vol.tail(_VOL_SHORT).mean() / long_avg)

    return out


def technical_scores(rows: list[dict]) -> dict[str, float]:
    """Composite technical score per ticker in [0, 1], same shape as comp_scores."""
    return ranking.percentile_rank_scores(
        rows, frozenset(), _TECH_HIGHER_BETTER, _TECH_MIN_METRICS
    )


def technical_medals(rows: list[dict]) -> dict[str, str]:
    """Medal emoji for the 3 best technical scores (empty below 3 qualifiers)."""
    return ranking.podium_from_scores(technical_scores(rows))
