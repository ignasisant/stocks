"""Moat scoring tests — synthetic data, no network."""

import pandas as pd

from stocks.analysis.fundamentals import compute_metrics, format_value, verdict
from stocks.analysis.moat import (
    PILLAR_WEIGHTS,
    MoatScore,
    moat_rating,
    moat_score,
)
from stocks.data.fundamentals import RawFundamentals

YEARS = ["2025", "2024", "2023", "2022", "2021"]  # newest-first like yfinance


def wide_moat_raw() -> RawFundamentals:
    """Compounder: high stable ROIC, fat steady margins, buybacks."""
    income = pd.DataFrame(
        {
            "Total Revenue": [400e9, 380e9, 365e9, 350e9, 300e9],
            "Gross Profit": [190e9, 180e9, 172e9, 165e9, 140e9],
            "Net Income": [100e9, 95e9, 90e9, 85e9, 70e9],
            "EBIT": [120e9, 115e9, 110e9, 105e9, 90e9],
            "Tax Rate For Calcs": [0.15, 0.15, 0.16, 0.16, 0.14],
            "Diluted Average Shares": [15e9, 15.3e9, 15.6e9, 16e9, 16.5e9],
        },
        index=YEARS,
    ).T
    balance = pd.DataFrame({"Invested Capital": [200e9] * 5}, index=YEARS).T
    cashflow = pd.DataFrame(
        {"Free Cash Flow": [95e9, 90e9, 88e9, 82e9, 70e9]}, index=YEARS
    ).T
    return RawFundamentals("WIDE", {}, income, balance, cashflow)


def no_moat_raw() -> RawFundamentals:
    """Value trap: thin volatile returns, shrinking revenue, dilution."""
    income = pd.DataFrame(
        {
            "Total Revenue": [80e9, 90e9, 100e9, 110e9, 120e9],
            "Gross Profit": [12e9, 14e9, 15e9, 17e9, 18e9],
            "Net Income": [1e9, -2e9, 2e9, -1e9, 3e9],
            "EBIT": [2e9, -1e9, 3e9, 1e9, 4e9],
            "Tax Rate For Calcs": [0.25] * 5,
            "Diluted Average Shares": [12e9, 11.5e9, 11e9, 10.5e9, 10e9],
        },
        index=YEARS,
    ).T
    balance = pd.DataFrame({"Invested Capital": [150e9] * 5}, index=YEARS).T
    cashflow = pd.DataFrame(
        {"Free Cash Flow": [-2e9, 1e9, -3e9, 0.5e9, -1e9]}, index=YEARS
    ).T
    return RawFundamentals("TRAP", {}, income, balance, cashflow)


def test_weights_sum_to_one():
    assert abs(sum(PILLAR_WEIGHTS.values()) - 1.0) < 1e-9


def test_wide_moat_scores_wide():
    ms = moat_score(wide_moat_raw())
    assert isinstance(ms, MoatScore)
    assert ms.rating == "wide"
    assert ms.score >= 70
    assert ms.years == 5
    # every pillar scored on this fixture
    assert all(p.score is not None for p in ms.pillars)
    # ROIC ~51% every year -> level and persistence both max out
    roic = next(p for p in ms.pillars if p.key == "roic")
    assert roic.score == 100
    # buybacks (shares shrink) -> dilution pillar maxes out
    dilution = next(p for p in ms.pillars if p.key == "dilution")
    assert dilution.score == 100


def test_no_moat_scores_low():
    ms = moat_score(no_moat_raw())
    assert ms.rating == "no moat"
    assert ms.score < 45
    # ROIC ~1-2% -> far below the 10% hurdle every year
    roic = next(p for p in ms.pillars if p.key == "roic")
    assert roic.score < 10
    # revenue shrinks every year
    growth = next(p for p in ms.pillars if p.key == "growth")
    assert growth.score == 0
    # +4.7%/y share growth -> heavy dilution
    dilution = next(p for p in ms.pillars if p.key == "dilution")
    assert dilution.score == 0


def test_missing_statements_yield_none():
    ms = moat_score(RawFundamentals("EMPTY"))
    assert ms.score is None
    assert ms.rating is None
    assert ms.years == 0
    assert all(p.score is None for p in ms.pillars)


def _margin_raw(revenue: list[float], operating: list[float]) -> RawFundamentals:
    """Income rows only, newest first like yfinance."""
    income = pd.DataFrame(
        {"Total Revenue": revenue, "Operating Income": operating},
        index=YEARS[: len(revenue)],
    ).T
    return RawFundamentals("M", {}, income)


def _margin(raw: RawFundamentals):
    return next(p for p in moat_score(raw).pillars if p.key == "op_margin")


def test_a_thin_steady_margin_is_moat_evidence():
    """Costco's case: 3% that never moves. A level scale scored it 0; the
    stability scale reads it for what it is."""
    pillar = _margin(_margin_raw([250, 240, 230, 220], [8.0, 7.6, 7.2, 6.8]))
    assert pillar.score is not None and pillar.score > 90
    assert pillar.kind == "op_margin"
    assert abs(pillar.facts["margin"] - 0.0318) < 1e-3


def test_a_swinging_margin_scores_low_whatever_its_level():
    """A 30% median that swings ±15pp is cyclical, not pricing power."""
    pillar = _margin(_margin_raw([100, 100, 100, 100], [15, 45, 15, 45]))
    assert pillar.score is not None and pillar.score < 30


def test_a_falling_margin_costs_points_a_rising_one_does_not():
    """Same swing, opposite direction: erosion is the moat failing."""
    falling = _margin(_margin_raw([100, 100, 100, 100], [20, 22, 24, 26]))
    rising = _margin(_margin_raw([100, 100, 100, 100], [26, 24, 22, 20]))
    assert falling.facts["change"] < 0 < rising.facts["change"]
    assert falling.score < rising.score


def test_a_steady_loss_is_not_pricing_power():
    pillar = _margin(_margin_raw([100, 100, 100], [-5, -5, -5]))
    assert pillar.score == 0.0
    assert pillar.kind == "op_margin_loss"


def test_a_margin_needs_three_years_and_never_a_snapshot():
    """Two points make no σ, and today's margin has no history at all — the
    pillar stays unscored rather than guessing its stability."""
    assert _margin(_margin_raw([100, 90], [30, 27])).score is None
    snap = moat_score(RawFundamentals("SNAP", info={"operatingMargins": 0.4}))
    assert next(p for p in snap.pillars if p.key == "op_margin").score is None
    assert snap.score is None


def test_buybacks_earn_nothing_past_a_flat_share_count():
    """Shrinking the count with borrowed money is capital allocation, not an
    advantage: flat and -5%/y both score 100, dilution costs points."""

    def dilution(shares: list[float]) -> float | None:
        income = pd.DataFrame(
            {"Diluted Average Shares": shares}, index=YEARS[: len(shares)]
        ).T
        ms = moat_score(RawFundamentals("D", {}, income))
        return next(p for p in ms.pillars if p.key == "dilution").score

    assert dilution([10, 10, 10]) == 100
    assert dilution([9.0, 9.5, 10]) == 100
    assert dilution([10.7, 10.3, 10]) == 0  # +3.4%/y


def test_a_good_roic_is_not_the_ceiling():
    """The level scales top out where exceptional starts: a steady 25% ROIC
    is good, and no longer scores like a 50% one."""

    def roic(level: float) -> float | None:
        income = pd.DataFrame(
            {"EBIT": [level * 100] * 4, "Tax Rate For Calcs": [0.0] * 4},
            index=YEARS[:4],
        ).T
        balance = pd.DataFrame({"Invested Capital": [100.0] * 4}, index=YEARS[:4]).T
        ms = moat_score(RawFundamentals("R", {}, income, balance))
        return next(p for p in ms.pillars if p.key == "roic").score

    assert 70 < roic(0.25) < 100
    assert roic(0.50) == 100


def test_every_pillar_carries_its_facts():
    """The client words each detail from these; a pillar without them would
    fall back to English."""
    ms = moat_score(wide_moat_raw())
    kinds = {p.key: p.kind for p in ms.pillars}
    assert kinds == {
        "roic": "roic",
        "op_margin": "op_margin",
        "growth": "growth",
        "fcf": "fcf",
        "dilution": "dilution",
    }
    assert all(p.facts for p in ms.pillars)
    dilution = next(p for p in ms.pillars if p.key == "dilution")
    assert dilution.facts["shares"] < 0


def test_moat_rating_bands():
    assert moat_rating(None) is None
    assert moat_rating(85) == "wide"
    assert moat_rating(70) == "wide"
    assert moat_rating(69.9) == "narrow"
    assert moat_rating(45) == "narrow"
    assert moat_rating(44.9) == "no moat"


def test_moat_flows_into_metrics_and_formatting():
    m = compute_metrics(wide_moat_raw())
    assert m["moat"] is not None and m["moat"] >= 70
    assert format_value("moat", m["moat"]).endswith("/100")
    label, color = verdict("moat", m["moat"])
    assert (label, color) == ("wide", "green")
    assert verdict("moat", 30) == ("no moat", "red")
    assert verdict("moat", 55) == ("narrow", "orange")


def test_invested_capital_nonpositive_years_dropped():
    income = pd.DataFrame(
        {
            "Total Revenue": [100e9, 90e9],
            "EBIT": [20e9, 18e9],
            "Tax Rate For Calcs": [0.2, 0.2],
        },
        index=YEARS[:2],
    ).T
    balance = pd.DataFrame({"Invested Capital": [80e9, -5e9]}, index=YEARS[:2]).T
    ms = moat_score(RawFundamentals("NEG", {}, income, balance))
    roic = next(p for p in ms.pillars if p.key == "roic")
    # only the positive-capital year counts: 20*0.8/80 = 20%
    assert roic.score is not None
    assert "1/1 years" in roic.detail
