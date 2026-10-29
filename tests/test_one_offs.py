"""The trailing year's one-offs (`analysis/one_offs.py`)."""

import pandas as pd
import pytest

from stocks.analysis import one_offs

B = 1e9


def _income(pretax, operating, tax, net=None):
    """A quarterly statement, newest first, from 2026Q3 back."""
    cols = pd.to_datetime(["2026-09-30", "2026-06-30", "2026-03-31",
                           "2025-12-31", "2025-09-30"][:len(pretax)])
    net = net or [p - t for p, t in zip(pretax, tax, strict=True)]
    return pd.DataFrame(
        [[v * B for v in pretax], [v * B for v in operating],
         [v * B for v in tax], [v * B for v in net]],
        index=["Pretax Income", "Operating Income", "Tax Provision",
               "Net Income Common Stockholders"],
        columns=cols,
    )


def test_a_steady_year_has_nothing_to_flag():
    got = one_offs.read(_income([20, 20, 19, 18, 17], [20, 20, 19, 18, 17],
                                [3, 3, 2.9, 2.7, 2.6]))
    assert got is not None and got.flags == ()
    assert got.usual_tax == pytest.approx(0.15, abs=0.01)


def test_a_tax_benefit_is_named_and_taken_out_of_the_multiple():
    # Meta's 2026Q1: a tax benefit lifts net income above pretax.
    got = one_offs.read(_income([20, 20, 20, 20, 20], [20, 20, 20, 20, 20],
                                [3, 3, -5, 3, 3]))
    (flag,) = got.flags
    assert flag.period == "2026Q1" and flag.kind == "tax"
    assert "benefit of about 8.0B" in flag.text
    # 76 reported over 68 clean: the trailing multiple is the low one.
    assert got.adjust(20.0) == pytest.approx(20.0 * 76 / 68)


def test_gains_on_stakes_are_named_as_outside_operations():
    # Alphabet's 2026Q2: half the pretax income is a mark-up on its stakes.
    got = one_offs.read(_income([40, 140, 77, 39, 44], [40, 41, 40, 36, 31],
                                [7.6, 26.6, 14.6, 7.4, 8.4]))
    (flag,) = got.flags
    assert flag.kind == "non_operating" and "2026Q2" in flag.text
    assert got.adjust(16.0) > 30


def test_a_quarter_well_below_its_year_ago_one_is_a_drop():
    got = one_offs.read(_income([13, 19, 22, 25, 21], [13, 19, 22, 25, 21],
                                [2, 2.9, 3.3, 3.8, 3.2]))
    (flag,) = got.flags
    assert flag.period == "2026Q3" and flag.kind == "drop"
    assert "21.0B a year earlier (-38%)" in flag.text
    assert got.adjust(20.0, "scale_level") < 20.0


def test_growth_and_a_seasonal_quarter_are_not_one_offs():
    # Up 80% on the year-ago quarter, and a December twice the summer.
    got = one_offs.read(_income([36, 20, 18, 40, 20], [36, 20, 18, 40, 20],
                                [5.4, 3, 2.7, 6, 3]))
    assert got.flags == ()


def test_too_few_quarters_reads_nothing():
    assert one_offs.read(_income([20, 20, 20], [20, 20, 20], [3, 3, 3])) is None
    assert one_offs.read(None) is None
    assert one_offs.read(pd.DataFrame()) is None
