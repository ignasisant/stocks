"""The percentile-ranking core shared by fundamentals.comp_scores and
technicals.technical_scores — see test_fundamentals.py and test_technicals.py
for the domain-specific behavior built on top of this."""

from stocks.analysis.ranking import percentile_rank_scores, podium_from_scores


def test_higher_better_and_lower_better_both_reward_the_right_direction():
    rows = [
        {"ticker": "A", "cheap": 10, "profitable": 0.9},
        {"ticker": "B", "cheap": 20, "profitable": 0.5},
        {"ticker": "C", "cheap": 30, "profitable": 0.1},
    ]
    scores = percentile_rank_scores(rows, {"cheap"}, {"profitable"}, min_metrics=1)
    assert scores["A"] > scores["B"] > scores["C"]
    assert scores["A"] == 1.0 and scores["C"] == 0.0


def test_below_the_metric_floor_is_dropped():
    rows = [{"ticker": "SPARSE", "cheap": 10}]
    assert percentile_rank_scores(rows, {"cheap"}, set(), min_metrics=2) == {}


def test_podium_needs_three_qualifiers():
    assert podium_from_scores({"A": 1.0, "B": 0.5, "C": 0.0}) == {
        "A": "🥇", "B": "🥈", "C": "🥉",
    }
    assert podium_from_scores({"A": 1.0, "B": 0.5}) == {}
