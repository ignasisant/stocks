"""Cross-sectional percentile ranking, shared by fundamentals and technicals.

Extracted out of `fundamentals.comp_scores`/`comp_medals` so a second scored
podium (technical indicators, `technicals.py`) doesn't need its own copy of
the same rank-and-average logic.
"""

from __future__ import annotations

import pandas as pd


def percentile_rank_scores(
    rows: list[dict],
    lower_better: frozenset[str],
    higher_better: frozenset[str],
    min_metrics: int,
) -> dict[str, float]:
    """Composite score per ticker in [0, 1] — cross-sectional, not banded.

    Each rankable metric contributes a normalized average rank across the
    tickers that report it (best = 1, worst = 0, ties share); a ticker's score
    is the mean over its ranked metrics. Tickers ranked on fewer than
    `min_metrics` of them are dropped — too sparse to compare fairly.
    """
    per_ticker: dict[str, list[float]] = {str(r["ticker"]): [] for r in rows}
    for key in lower_better | higher_better:
        vals = {
            str(r["ticker"]): float(r[key])
            for r in rows
            if isinstance(r.get(key), (int, float))
            and not isinstance(r.get(key), bool)
            and pd.notna(r[key])
        }
        if len(vals) < 2:
            continue
        n = len(vals)
        for t, v in vals.items():
            beaten = sum(1 for o in vals.values() if o > v) if (
                key in lower_better
            ) else sum(1 for o in vals.values() if o < v)
            tied = sum(1 for o in vals.values() if o == v) - 1
            per_ticker[t].append((beaten + tied / 2) / (n - 1))
    return {
        t: sum(s) / len(s)
        for t, s in per_ticker.items()
        if len(s) >= min_metrics
    }


def podium_from_scores(scores: dict[str, float]) -> dict[str, str]:
    """Medal emoji for the 3 best scores (empty when fewer than 3 qualify —
    a 2-horse race has no podium)."""
    if len(scores) < 3:
        return {}
    ranked = sorted(scores, key=lambda t: scores[t], reverse=True)
    return dict(zip(ranked, ("🥇", "🥈", "🥉"), strict=False))
