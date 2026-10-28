"""The Review engine: verdicts off a dict of KPIs, no network."""

from __future__ import annotations

import pytest

from stocks.analysis import review

# Shapes lifted from real books (2026-10): a quality compounder on sale, a
# chip maker priced for perfection, a heavy cheap-but-weak ADR.
CHEAP_QUALITY = {
    "pe_fwd": 9.0, "fcf_yield": 0.10, "ev_ebitda": 9.0, "ev": 1e11,
    "roic": 0.41, "op_margin": 0.36, "moat": 80.0, "share_dilution": -0.03,
}
DEAR_WEAK = {
    "pe_fwd": 40.0, "fcf_yield": 0.007, "ev_ebitda": 105.0, "ev": 1e12,
    "roic": 0.05, "op_margin": 0.17, "moat": 33.0,
}
CHEAP_WEAK = {
    "pe_fwd": 11.0, "fcf_yield": -0.01, "ev_ebitda": 10.0, "ev": 3e11,
    "roic": 0.08, "op_margin": 0.12, "moat": 31.0,
}
# A great business the market already prices as one.
DEAR_QUALITY = {
    "pe_fwd": 32.0, "fcf_yield": 0.03, "ev_ebitda": 26.0, "ev": 3e12,
    "roic": 0.45, "op_margin": 0.31, "moat": 85.0,
}


def _rows(*rows) -> list[review.BookRow]:
    return [review.BookRow(*row) for row in rows]


def test_a_dear_weak_business_is_sold():
    v = review.judge_held(DEAR_WEAK, weight=0.03, risk_share=0.06)
    assert v.verdict == review.SELL
    assert v.target == 0.0
    assert review.R_EXPENSIVE in v.reasons and review.R_LOW_ROIC in v.reasons


def test_a_quality_name_on_sale_and_underweight_is_added_to():
    v = review.judge_held(CHEAP_QUALITY, weight=0.02, risk_share=0.02)
    assert v.verdict == review.ADD
    assert v.target == review.ADD_TO
    assert review.R_UNDERWEIGHT in v.reasons


def test_already_a_full_position_is_held_not_added_to():
    v = review.judge_held(CHEAP_QUALITY, weight=0.08, risk_share=0.08)
    assert v.verdict == review.HOLD


def test_a_heavy_weak_name_is_halved_and_says_why_first():
    v = review.judge_held(CHEAP_WEAK, weight=0.072, risk_share=0.12)
    assert v.verdict == review.TRIM
    assert v.target == 0.072 * review.TRIM_KEEPS
    assert v.reasons[:2] == (review.R_HEAVY, review.R_RISKY)


def test_one_company_this_big_is_cut_whatever_its_quality():
    v = review.judge_held(DEAR_QUALITY, weight=0.20)
    assert v.verdict == review.TRIM
    assert v.target == review.CONCENTRATED_TO
    assert v.reasons[0] == review.R_CONCENTRATED


def test_a_good_business_at_a_good_price_is_cut_only_halfway_back():
    # The excess goes, the conviction stays, and the target sits under the
    # line so the next rally does not trip it again.
    v = review.judge_held(CHEAP_QUALITY, weight=0.20)
    assert v.verdict == review.TRIM
    assert review.CONCENTRATED_TO < v.target < review.CONCENTRATED


def test_a_crumb_that_is_not_good_enough_to_grow_is_sold():
    v = review.judge_held(CHEAP_WEAK, weight=0.002)
    assert v.verdict == review.SELL
    assert review.R_SMALL in v.reasons


def test_broken_source_data_is_named_not_ranked():
    """A Chinese ADR's FCF yield of 95% and a negative EV are a currency mix,
    not a bargain: those inputs drop out and the row says so."""
    broken = {**CHEAP_QUALITY, "fcf_yield": 0.95, "ev": -3.4e11}
    s = review.score(broken)
    assert s.suspect
    # Forward P/E alone is one input: not enough to call a price.
    assert s.cheapness is None
    v = review.judge_held(broken, weight=0.02)
    assert v.verdict == review.UNRATED
    assert v.reasons == (review.R_SUSPECT,)


def test_a_high_yield_the_forward_pe_backs_is_a_price_not_a_fault():
    """Teleperformance at five times earnings yields 30% in cash: real, and
    scored. The same yield at fifteen times earnings is a feed fault."""
    distressed = {
        **CHEAP_WEAK, "pe_fwd": 5.08, "fcf_yield": 0.32, "owner_fcf_yield": 0.31,
        "ev_ebitda": 5.1,
    }
    s = review.score(distressed)
    assert not s.suspect
    assert s.cheapness == 100.0
    assert review.score({**distressed, "pe_fwd": 15.0}).suspect
    assert review.score({**distressed, "owner_fcf_yield": 0.6, "pe_fwd": 3.0}).suspect


def test_a_concentrated_name_is_cut_halfway_even_when_it_cannot_be_scored():
    broken = {**CHEAP_QUALITY, "fcf_yield": 0.95, "ev": -3.4e11}
    v = review.judge_held(broken, weight=0.22)
    assert v.verdict == review.TRIM
    # Unread is not weak: the size goes, halfway, as for a good name.
    assert v.target == pytest.approx((review.CONCENTRATED + review.CONCENTRATED_TO) / 2)
    assert v.reasons == (review.R_CONCENTRATED, review.R_SUSPECT)


def test_no_fundamentals_is_unrated_not_held_by_default():
    assert review.judge_held(None, weight=0.05).verdict == review.UNRATED
    assert review.judge_held({"roic": 0.3}, weight=0.05).reasons == (review.R_NO_DATA,)


def test_a_forward_loss_is_the_dear_end_not_missing():
    s = review.score({"pe_fwd": -12.0, "ev_ebitda": 30.0, "ev": 1e9})
    # Zero on the P/E leg: averaged with a middling EV/EBITDA, still "dear".
    assert s.cheapness is not None and s.cheapness < 30


def test_funds_and_cash_are_judged_by_kind():
    assert review.judge_held(None, weight=0.1, kind="equity_fund").verdict == review.CORE
    assert review.judge_held(None, weight=0.1, kind="money_market").verdict == review.CASH
    assert review.judge_held(None, weight=0.1, kind="crypto").verdict == review.UNRATED
    assert review.judge_candidate(None, kind="equity_fund").verdict == review.UNRATED


def test_outside_names_are_bought_watched_or_passed():
    assert review.judge_candidate(CHEAP_QUALITY).verdict == review.BUY
    dear_quality = {
        **CHEAP_QUALITY, "pe_fwd": 45.0, "fcf_yield": 0.015, "ev_ebitda": 60.0
    }
    assert review.judge_candidate(dear_quality).verdict == review.WATCH
    assert review.judge_candidate(DEAR_WEAK).verdict == review.PASS


def test_actions_sort_before_the_quiet_rows_and_unknowns_sink():
    rows = [
        ("hold", 70.0, 0.05),
        ("sell", 20.0, 0.02),
        ("add", 80.0, 0.02),
        ("trim", 30.0, 0.07),
        ("unrated", None, 0.01),
        ("sell", 10.0, 0.01),
    ]
    ordered = sorted(rows, key=lambda r: review.sort_key(r[0], r[1], r[2], held=True))
    assert [r[0] for r in ordered] == ["sell", "sell", "trim", "add", "hold", "unrated"]
    # The weakest sale first.
    assert ordered[0][1] == 10.0


# A drug developer before its first sale (Revolution Medicines, 2026-10): no
# revenue, a billion a year out the door, four years of cash.
PRE_REVENUE_BIOTECH = {
    "industry": "Biotechnology", "revenue": 0.0, "market_cap": 2e10,
    "fcf": -1e9, "fcf_yield": -0.05, "runway_years": 4.3,
    "share_dilution": 0.12, "op_margin": None, "roic": -0.3,
}
# A design-software grower: 40% sales growth, still at break-even.
FAST_GROWER = {
    "revenue": 1e9, "market_cap": 1.5e10, "fcf": 3e8, "fcf_yield": 0.02,
    "fcf_margin": 0.30, "revenue_growth": 0.40, "op_margin": -0.05,
    "gross_margin": 0.88, "moat": 60.0, "ev_sales": 14.0, "ev": 1.4e10,
    "roic": -0.02,
}


def test_a_business_still_proving_its_product_is_a_bet_not_a_score():
    s = review.score(PRE_REVENUE_BIOTECH)
    assert s.stage == review.EARLY
    assert s.quality is None and s.cheapness is None
    v = review.judge_candidate(PRE_REVENUE_BIOTECH)
    assert v.verdict == review.BET
    assert v.reasons[:2] == (review.R_PRE_REVENUE, review.R_TRIAL_RISK)
    assert review.R_LONG_RUNWAY in v.reasons and review.R_DILUTION in v.reasons
    # Losses are the stage, not a finding.
    assert review.R_LOSS not in v.reasons and review.R_LOW_ROIC not in v.reasons


def test_a_bet_is_kept_small():
    assert review.judge_held(PRE_REVENUE_BIOTECH, weight=0.02).verdict == review.BET
    v = review.judge_held(PRE_REVENUE_BIOTECH, weight=0.08)
    assert v.verdict == review.TRIM
    assert v.target == review.SPEC_MAX
    assert v.reasons[0] == review.R_BET_HEAVY


def test_running_out_of_cash_is_said():
    short = {**PRE_REVENUE_BIOTECH, "runway_years": 0.8}
    assert review.R_SHORT_RUNWAY in review.judge_candidate(short).reasons


def test_a_fast_grower_is_judged_on_its_growth_not_todays_profit():
    s = review.score(FAST_GROWER)
    assert s.stage == review.GROWTH
    assert s.quality is not None and s.quality >= review.GOOD
    v = review.judge_held(FAST_GROWER, weight=0.01)
    assert v.reasons[0] == review.R_GROWTH_STAGE
    assert review.R_RULE_40 in v.reasons
    assert review.R_LOSS not in v.reasons and review.R_LOW_ROIC not in v.reasons
    # Added to a starter size, not a mature name's full one.
    assert v.verdict == review.ADD
    assert v.target == review.SPEC_MAX


def test_a_profitable_grower_stays_on_the_mature_lens():
    mature = {**FAST_GROWER, "op_margin": 0.30, "roic": 0.25, "pe_fwd": 30.0}
    assert review.stage(mature) == review.MATURE


def test_a_drug_maker_on_sale_carries_its_patent_risk():
    pharma = {**CHEAP_QUALITY, "industry": "Drug Manufacturers - General"}
    assert review.R_PATENT_RISK in review.judge_held(pharma, weight=0.02).reasons
    other = review.judge_held(CHEAP_QUALITY, weight=0.02)
    assert review.R_PATENT_RISK not in other.reasons


def test_cash_that_is_not_the_business_is_not_a_yield():
    """A lender's loan book runs through FCF: a 39% "yield" is not a price."""
    lender = {**CHEAP_QUALITY, "fcf_yield": 0.39, "fcf_ebitda": 6.0, "pb": 1.2}
    s = review.score(lender)
    assert s.fcf_float
    plain = review.score({**CHEAP_QUALITY, "pb": 1.2})
    # Without the float the price leans on P/E, EV/EBITDA and book instead.
    assert s.cheapness is not None and s.cheapness != plain.cheapness
    assert review.R_FCF_FLOAT in review.judge_held(lender, weight=0.02).reasons


def test_a_long_runway_is_no_news_for_a_mature_business():
    burner = {**CHEAP_WEAK, "runway_years": 5.0}
    assert review.R_LONG_RUNWAY not in review.judge_held(burner, weight=0.02).reasons
    short = {**CHEAP_WEAK, "runway_years": 0.5}
    assert review.R_SHORT_RUNWAY in review.judge_held(short, weight=0.02).reasons


def test_pay_in_shares_is_taken_off_the_cash_flow():
    """HubSpot 2026: 577M of FCF, 528M of it share-based pay."""
    saas = {**CHEAP_QUALITY, "fcf_yield": 0.05, "owner_fcf_yield": 0.004,
            "sbc_fcf": 0.92}
    assert review.score(saas).cheapness < review.score(
        {**CHEAP_QUALITY, "fcf_yield": 0.05}
    ).cheapness
    assert review.R_SHARE_PAY in review.judge_held(saas, weight=0.02).reasons


# Shopify, 2026-10: 34% sales growth last quarter (27% a year over four), a
# 17.6% operating margin that puts it on the mature lens, priced at 67x
# forward earnings. Before the rule of 40 counted it read "quality 39.9, sell".
PROFITABLE_GROWER = {
    "revenue": 1.16e10, "market_cap": 2.1e11, "ev": 2.07e11, "fcf": 2.0e9,
    "revenue_growth": 0.337, "revenue_cagr": 0.273, "op_margin": 0.176,
    "gross_margin": 0.48, "roic": 0.114, "moat": 41.4, "fcf_margin": 0.135,
    "fcf_yield": 0.0095, "owner_fcf_yield": 0.0074, "sbc_fcf": 0.22,
    "pe_fwd": 67.0, "ev_ebitda": 86.0, "ev_sales": 15.6, "fcf_ebitda": 0.81,
}


def test_a_profitable_grower_keeps_the_credit_for_its_growth():
    s = review.score(PROFITABLE_GROWER)
    assert s.stage == review.MATURE
    slow = review.score(
        {**PROFITABLE_GROWER, "revenue_growth": 0.05, "revenue_cagr": 0.05}
    )
    assert s.quality > slow.quality
    v = review.judge_held(PROFITABLE_GROWER, weight=0.05)
    # Dear, and said so — but not sold for being a grower that turned a profit.
    assert v.verdict == review.HOLD
    assert review.R_EXPENSIVE in v.reasons
    assert review.R_RULE_40 in v.reasons and review.R_GROWTH in v.reasons


# Elastic, 2026-10: 15% growth (18% a year over four), break-even only after
# 298M of share-based pay; before it, an 18.5% cash margin. Under the mature
# lens it read "quality 17, cheapness 22, sell".
SCALING_GROWER = {
    "revenue": 1.74e9, "market_cap": 1.11e10, "ev": 1.02e10, "fcf": 3.22e8,
    "revenue_growth": 0.151, "revenue_cagr": 0.176, "op_margin": -0.006,
    "gross_margin": 0.756, "roic": 0.007, "roic_ex_goodwill": 0.009,
    "moat": 27.9, "fcf_margin": 0.013, "fcf_yield": 0.029,
    "owner_fcf_yield": 0.002, "sbc_fcf": 0.93, "pe_fwd": 26.7,
    "ev_ebitda": -458.0, "ev_sales": 5.67, "share_dilution": 0.028,
}


def test_a_grower_spending_its_margin_on_growth_is_judged_as_one():
    s = review.score(SCALING_GROWER)
    assert s.stage == review.GROWTH
    v = review.judge_held(SCALING_GROWER, weight=0.02)
    assert v.verdict == review.HOLD
    assert v.reasons[0] == review.R_GROWTH_STAGE
    assert review.R_LOW_ROIC not in v.reasons
    # The shares it pays its staff in still count against it.
    assert review.R_SHARE_PAY in v.reasons


def test_a_thin_margin_without_the_cash_stays_mature():
    """The same pace with a grocer's cash margin is a thin business, not one
    spending on growth; nor does a slower pace earn the lens."""
    thin = {**SCALING_GROWER, "fcf": 0.03 * SCALING_GROWER["revenue"]}
    assert review.stage(thin) == review.MATURE
    slow = {**SCALING_GROWER, "revenue_growth": 0.12}
    assert review.stage(slow) == review.MATURE


def test_one_spiky_quarter_is_not_growth():
    """Exxon, 2026-10: +44% on the year-ago quarter, -7% a year over four."""
    oil = {**CHEAP_WEAK, "revenue_growth": 0.44, "revenue_cagr": -0.067,
           "fcf_margin": 0.07}
    assert review.sustained_growth(oil) == -0.067
    assert review.score(oil).quality == review.score(CHEAP_WEAK).quality
    assert review.R_GROWTH not in review.judge_held(oil, weight=0.02).reasons
    # Nor does one quarter put a loss-maker on the growth lens.
    spiky = {**FAST_GROWER, "revenue_cagr": 0.05}
    assert review.stage(spiky) == review.MATURE


def test_the_growth_lens_scores_the_pace_it_sees_now():
    """Sustained growth picks the lens; inside it, the last quarter is the
    pace (Axon fell from hold to sell when the lower rate was scored too)."""
    steady = {**FAST_GROWER, "revenue_cagr": 0.30}
    assert review.stage(steady) == review.GROWTH
    assert review.score(steady).quality == review.score(FAST_GROWER).quality


def test_losing_more_than_it_sells_is_a_bet_even_with_sales():
    """Recursion, 2026-10: 60M of collaboration revenue, an operating loss 17
    times that, priced at 28x sales — under the pre-revenue bar, still a bet."""
    burner = {
        "industry": "Biotechnology", "revenue": 6.0e7, "market_cap": 1.7e9,
        "ev": 1.6e9, "fcf": -3.8e8, "fcf_yield": -0.18, "op_margin": -17.6,
        "roic": -0.56, "moat": 15.0, "pe_fwd": -4.0, "revenue_growth": -0.6,
        "revenue_cagr": 0.23, "runway_years": 1.2,
    }
    v = review.judge_held(burner, weight=0.01)
    assert v.verdict == review.BET
    assert v.reasons[:2] == (review.R_DEEP_BURN, review.R_TRIAL_RISK)
    assert review.R_SHORT_RUNWAY in v.reasons
    # A loss smaller than the sales is still scored, on whichever lens fits.
    assert review.stage({**burner, "op_margin": -0.5}) != review.EARLY


# A mature compounder at thirty times earnings: dear on the plain multiple,
# fair or cheap once its growth is counted.
COMPOUNDER = {
    "pe_fwd": 30.0, "fcf_yield": 0.03, "ev_ebitda": 25.0, "ev": 1e12,
    "roic": 0.30, "op_margin": 0.40, "moat": 75.0,
}


def test_a_fast_mature_grower_is_cheaper_for_its_growth():
    grower = {**COMPOUNDER, "revenue_growth": 0.35, "revenue_cagr": 0.35}
    slow = review.score({**COMPOUNDER, "revenue_growth": 0.04, "revenue_cagr": 0.04})
    fast = review.score(grower)
    assert fast.stage == slow.stage == review.MATURE
    assert fast.cheapness > slow.cheapness
    v = review.judge_held(grower, weight=0.02)
    assert review.R_CHEAP_FOR_GROWTH in v.reasons


def test_a_slow_grower_is_not_marked_down_for_being_slow():
    plain = review.score(COMPOUNDER)
    slow = review.score({**COMPOUNDER, "revenue_growth": 0.02, "revenue_cagr": 0.02})
    assert slow.cheapness == plain.cheapness
    assert review.R_CHEAP_FOR_GROWTH not in review.judge_held(
        {**COMPOUNDER, "revenue_growth": 0.02, "revenue_cagr": 0.02}, weight=0.02
    ).reasons


def test_growth_credit_reads_the_sustained_pace_and_caps_it():
    # One spiky quarter is not the pace the P/E is divided by.
    spike = {**COMPOUNDER, "revenue_growth": 0.60, "revenue_cagr": 0.06}
    assert review.growth_pe(spike) == 30.0 / 6.0
    boom = {**COMPOUNDER, "revenue_growth": 0.90, "revenue_cagr": 0.90}
    assert review.growth_pe(boom) == 30.0 / (review.PEG_GROWTH_CAP * 100)
    assert review.growth_pe({**COMPOUNDER, "pe_fwd": -5.0, "revenue_growth": 0.3}) is None


def test_growth_credit_is_per_share_so_dilution_eats_it():
    grower = {**COMPOUNDER, "revenue_growth": 0.21, "revenue_cagr": 0.21}
    diluting = {**grower, "share_dilution": 0.10}
    buying_back = {**grower, "share_dilution": -0.05}
    assert review.growth_pe(diluting) > review.growth_pe(grower) > review.growth_pe(
        buying_back
    )
    assert abs(review.per_share_growth(diluting) - 0.10) < 1e-9


def test_the_row_carries_the_growth_adjusted_pe():
    grower = {**COMPOUNDER, "revenue_growth": 0.30, "revenue_cagr": 0.30}
    v = review.judge_held(grower, weight=0.02)
    assert v.metrics["growth_pe"] == review.growth_pe(grower)
    assert review.judge_held(COMPOUNDER, weight=0.02).metrics["growth_pe"] is None


# The cautions: good scores the numbers behind them may not hold. They stop
# an add or a buy, never make one.
def _blocked(metrics: dict, reason: str) -> None:
    held = review.judge_held(metrics, weight=0.02, risk_share=0.02)
    assert held.verdict == review.HOLD
    assert reason in held.reasons
    outside = review.judge_candidate(metrics)
    assert outside.verdict == review.WATCH
    assert reason in outside.reasons


def test_a_cyclical_at_its_peak_margin_is_not_added_to():
    peak = {**CHEAP_QUALITY, "op_margin_median": 0.20, "revenue_down_years": 1}
    _blocked(peak, review.R_PEAK_MARGIN)


def test_a_cyclical_at_its_peak_is_priced_on_a_normal_year():
    # The P/E it shows is on the peak margin; a normal year's earnings are
    # its median margin on today's sales, a dearer multiple.
    peak = {**CHEAP_QUALITY, "op_margin_median": 0.20, "revenue_down_years": 1}
    at_top, plain = review.score(peak), review.score(CHEAP_QUALITY)
    assert at_top.normal_pe and not plain.normal_pe
    assert at_top.cheapness < plain.cheapness
    pe, _ = review._pe(peak)
    assert review._normal_pe(peak, pe) == pytest.approx(
        pe * peak["op_margin"] / peak["op_margin_median"]
    )
    # A median at a loss: a normal year has no multiple, the dear end.
    assert review._normal_pe({**peak, "op_margin_median": -0.02}, pe) == 0.0


def test_a_compounder_widening_its_margin_is_no_peak():
    no_down_year = {**CHEAP_QUALITY, "op_margin_median": 0.20, "revenue_down_years": 0}
    fast = {
        **CHEAP_QUALITY, "op_margin_median": 0.20, "revenue_down_years": 1,
        "revenue_growth": 0.25, "revenue_cagr": 0.25,
    }
    for metrics in (no_down_year, fast):
        reasons = review.judge_held(metrics, weight=0.02).reasons
        assert review.R_PEAK_MARGIN not in reasons
    v = review.judge_held(no_down_year, weight=0.02, risk_share=0.02)
    assert v.verdict == review.ADD


def test_heavy_dilution_blocks_and_mild_is_only_named():
    _blocked({**CHEAP_QUALITY, "share_dilution": 0.06}, review.R_HEAVY_DILUTION)
    mild = review.judge_held({**CHEAP_QUALITY, "share_dilution": 0.035}, weight=0.02)
    assert review.R_DILUTION in mild.reasons
    assert review.R_HEAVY_DILUTION not in mild.reasons
    reit = {**CHEAP_QUALITY, "industry": "REIT - Retail", "share_dilution": 0.14}
    assert review.R_HEAVY_DILUTION not in review.judge_held(reit, weight=0.02).reasons


def test_earnings_the_cash_does_not_back_block():
    _blocked({**CHEAP_QUALITY, "accruals": 0.14}, review.R_EARNINGS_NOT_CASH)
    _blocked({**CHEAP_QUALITY, "cfo_ni": 0.55}, review.R_EARNINGS_NOT_CASH)
    backed = {**CHEAP_QUALITY, "accruals": 0.03, "cfo_ni": 1.1}
    v = review.judge_held(backed, weight=0.02, risk_share=0.02)
    assert v.verdict == review.ADD
    # A bank's operating cash is deposits moving: not read.
    bank = {**CHEAP_QUALITY, "industry": "Banks - Regional", "cfo_ni": 0.2}
    assert review.R_EARNINGS_NOT_CASH not in review.judge_held(bank, weight=0.02).reasons


def test_goodwill_blocks_only_when_the_deals_do_not_earn_it():
    # Heavy goodwill and a thin return on all the capital: the premium paid
    # is not coming back. The business's own return stays high (ex goodwill).
    heavy = {**CHEAP_QUALITY, "goodwill_assets": 0.6, "roic": 0.06,
             "roic_ex_goodwill": 0.41}
    _blocked(heavy, review.R_GOODWILL_HEAVY)
    _blocked({**heavy, "goodwill_assets": None, "goodwill_equity": 1.4},
             review.R_GOODWILL_HEAVY)
    earning = {**heavy, "roic": 0.15}
    assert review.R_GOODWILL_HEAVY not in review.judge_held(earning, weight=0.02).reasons


def test_share_pay_is_named_on_a_tenth_of_sales_too():
    paid = review.judge_held({**CHEAP_QUALITY, "sbc_revenue": 0.12}, weight=0.02)
    assert review.R_SHARE_PAY in paid.reasons
    light = review.judge_held({**CHEAP_QUALITY, "sbc_revenue": 0.04}, weight=0.02)
    assert review.R_SHARE_PAY not in light.reasons


def test_cheap_and_shrinking_is_a_value_trap():
    _blocked(
        {**CHEAP_QUALITY, "revenue_growth": -0.05, "revenue_cagr": -0.02},
        review.R_SALES_FALLING,
    )
    one_bad_year = {**CHEAP_QUALITY, "revenue_growth": -0.05, "revenue_cagr": 0.06}
    reasons = review.judge_held(one_bad_year, weight=0.02).reasons
    assert review.R_SALES_FALLING not in reasons


def test_a_sliding_margin_is_fading_pricing_power():
    _blocked(
        {**CHEAP_QUALITY, "op_margin_median": 0.40, "op_margin_change": -0.12},
        review.R_MARGIN_FALLING,
    )
    small_slip = {**CHEAP_QUALITY, "op_margin_median": 0.40, "op_margin_change": -0.03}
    reasons = review.judge_held(small_slip, weight=0.02).reasons
    assert review.R_MARGIN_FALLING not in reasons


def test_earnings_expected_to_shrink_make_a_low_pe_no_bargain():
    # Novo Nordisk, October 2026: 9.4x trailing, 11.6x forward.
    _blocked({**CHEAP_QUALITY, "pe_ttm": 9.4, "pe_fwd": 11.6}, review.R_EARNINGS_FALLING)
    for trailing in (12.0, 9.0, -5.0):
        steady = {**CHEAP_QUALITY, "pe_ttm": trailing}
        reasons = review.judge_held(steady, weight=0.02).reasons
        assert review.R_EARNINGS_FALLING not in reasons


def test_heavy_debt_stops_an_add_or_a_buy():
    _blocked({**CHEAP_QUALITY, "net_debt_ebitda": 3.5}, review.R_DEBT)
    light = {**CHEAP_QUALITY, "net_debt_ebitda": 2.0}
    assert review.judge_held(light, weight=0.02, risk_share=0.02).verdict == review.ADD


def test_cheap_on_its_kindest_reading_alone_is_no_margin_of_safety():
    one_reading = {**CHEAP_QUALITY, "pe_fwd": 8.0, "fcf_yield": 0.02, "ev_ebitda": 30.0}
    s = review.score(one_reading)
    assert s.cheapness >= review.CHEAP and s.cheap_reads == 1
    _blocked(one_reading, review.R_ONE_READING)


def test_two_cheap_readings_are_a_margin_of_safety_even_beside_a_dear_one():
    # HSBC's shape: cheap on earnings and on its book, dear on its ROE-fair
    # book; the mean without the cheapest reading fell under 50 and blocked it.
    two = {**CHEAP_QUALITY, "pe_fwd": 9.0, "fcf_yield": 0.03, "ev_ebitda": 14.0}
    s = review.score(two)
    assert s.cheap_reads == 2
    v = review.judge_held(two, weight=0.02, risk_share=0.02)
    assert review.R_ONE_READING not in v.reasons
    assert v.verdict == review.ADD


def test_cautions_never_make_an_add():
    weak = {
        **DEAR_WEAK, "op_margin_median": 0.05, "revenue_down_years": 2,
        "net_debt_ebitda": 4.0, "revenue_growth": -0.1, "revenue_cagr": -0.1,
    }
    assert review.judge_held(weak, weight=0.02).verdict not in (review.ADD, review.BUY)
    assert review.judge_candidate(weak).verdict == review.PASS


# --- Sizing over the whole book ---------------------------------------------
# The route counts the companies, judges each name against that count and
# spreads what the sales free (`_plan` does the same over plain rows).

FAIR_QUALITY = {
    "pe_fwd": 20.0, "fcf_yield": 0.05, "ev_ebitda": 16.0, "ev": 2e12,
    "roic": 0.30, "op_margin": 0.40, "moat": 80.0,
}
MIDDLING = {
    "pe_fwd": 20.0, "fcf_yield": 0.03, "ev_ebitda": 15.0, "ev": 1e11,
    "roic": 0.15, "op_margin": 0.18, "moat": 55.0,
}


def _plan(*book):
    rows = [(row + ("stock",))[:3] for row in book]
    names = sum(review.company(kind) for _, _, kind in rows)
    judged = [
        (w, review.judge_held(m, weight=w, kind=kind, names=names))
        for m, w, kind in rows
    ]
    return review.redeploy(judged)


def _moves(book, plan):
    pairs = [
        (w, v.target)
        for (_, w, *_), v in zip(book, plan, strict=True)
        if v.target is not None
    ]
    sells = sum(w - to for w, to in pairs if to < w)
    buys = sum(to - w for w, to in pairs if to > w)
    return sells, buys


def test_the_concentration_line_widens_as_the_book_narrows():
    assert review.concentration_line(None) == review.CONCENTRATED
    assert review.concentration_line(2) is None
    assert review.concentration_line(4) == review.CONCENTRATED_MAX
    assert review.concentration_line(7) == pytest.approx(1.5 / 7)
    assert review.concentration_line(10) == review.CONCENTRATED
    assert review.concentration_line(40) == review.CONCENTRATED


def test_a_one_company_book_is_told_it_is_narrow_not_to_sell_most_of_itself():
    [v] = _plan((DEAR_QUALITY, 1.0))
    assert v.verdict == review.HOLD and v.target is None
    assert review.R_FEW_NAMES in v.reasons
    assert review.book_notes(_rows(("stock", "Technology", 1.0))) == [
        review.Note(review.N_FEW_NAMES, count=1)
    ]


def test_two_good_companies_half_and_half_are_both_kept():
    plan = _plan((CHEAP_QUALITY, 0.5), (DEAR_QUALITY, 0.5))
    assert [v.verdict for v in plan] == [review.HOLD, review.HOLD]
    assert [
        n.key
        for n in review.book_notes(_rows(("stock", None, 0.5), ("stock", None, 0.5)))
    ] == [review.N_FEW_NAMES]


def test_a_narrow_book_still_sells_what_is_weak_on_both_scores():
    plan = _plan((DEAR_WEAK, 0.5), (CHEAP_QUALITY, 0.5))
    assert plan[0].verdict == review.SELL
    # With too few companies the money goes to new names, not to the one
    # already carrying the book.
    assert plan[1].verdict == review.HOLD


def test_a_fund_based_book_with_one_stock_on_the_side_says_the_stock_is_a_satellite():
    plan = _plan((None, 0.85, "equity_fund"), (DEAR_QUALITY, 0.15))
    assert [v.verdict for v in plan] == [review.CORE, review.HOLD]
    notes = review.book_notes(_rows(("equity_fund", None, 0.85), ("stock", None, 0.15)))
    assert notes == [review.Note(review.N_FUND_CORE, count=1, weight=0.85)]


@pytest.mark.parametrize("metrics", [CHEAP_QUALITY, DEAR_QUALITY, {}])
def test_four_even_positions_are_not_cut_to_cash(metrics):
    book = [(metrics, 0.25)] * 4
    plan = _plan(*book)
    assert all(v.verdict != review.TRIM for v in plan)
    assert _moves(book, plan) == (0, 0)


def test_twenty_even_positions_move_nothing():
    book = [(CHEAP_QUALITY, 0.05)] * 20
    assert {v.verdict for v in _plan(*book)} == {review.HOLD}


# Shaped on a real seven-name book (2026-10): a cheap chip maker at a third
# of it, a dear compounder at a fifth, a weak car maker, four fair names.
SEVEN = (
    (CHEAP_QUALITY, 0.33),
    (DEAR_QUALITY, 0.229),
    (DEAR_WEAK, 0.068),
    (FAIR_QUALITY, 0.12),
    (FAIR_QUALITY, 0.10),
    (FAIR_QUALITY, 0.09),
    (MIDDLING, 0.063),
)


def test_a_seven_name_book_cuts_to_an_even_share_and_spends_what_it_frees():
    plan = _plan(*SEVEN)
    line, even = 1.5 / 7, 1 / 7
    cheap, dear, weak, *fair, middling = plan
    # The good business on sale keeps more than the dear one.
    assert cheap.verdict == review.TRIM and even < cheap.target < line
    assert dear.verdict == review.TRIM and dear.target == pytest.approx(even)
    assert weak.verdict == review.SELL
    # The freed money tops the fair names up to an even share, no further.
    for v in fair:
        assert v.verdict == review.ADD and v.target == pytest.approx(even)
        assert v.reasons[0] == review.R_REDEPLOY
    assert middling.verdict == review.HOLD
    sells, buys = _moves(SEVEN, plan)
    assert buys == pytest.approx(sum(even - w for _, w in SEVEN[3:6]))
    assert 0 < buys < sells


def test_adds_are_never_funded_with_money_the_plan_does_not_raise():
    # Nothing sold: the underweight names wait for new money, nothing moves.
    book = [(CHEAP_QUALITY, 0.02)] * 5 + [(FAIR_QUALITY, 0.10)] * 9
    plan = _plan(*book)
    for v in plan[:5]:
        assert v.verdict == review.HOLD and v.target is None
        assert v.reasons[0] == review.R_NEW_MONEY and v.want == review.ADD_TO
    assert {v.verdict for v in plan[5:]} == {review.HOLD}
    assert _moves(book, plan) == (0, 0)


def test_the_sales_pay_for_the_best_adds_first_and_the_rest_wait():
    book = (
        [(DEAR_WEAK, 0.04)]
        + [(CHEAP_QUALITY, 0.02)] * 2
        + [(FAIR_QUALITY, 0.02)]
        + [(FAIR_QUALITY, 0.10)] * 9
    )
    plan = _plan(*book)
    sold, first, second, fair, *_ = plan
    assert sold.verdict == review.SELL
    # 4% freed: the first cheap name gets its whole 3%, the second the 1%
    # left and keeps the rest of its mark as a wish.
    assert first.verdict == review.ADD and first.target == pytest.approx(review.ADD_TO)
    assert first.want is None
    assert second.verdict == review.ADD and second.target == pytest.approx(0.03)
    assert second.want == review.ADD_TO
    assert fair.verdict == review.HOLD and fair.reasons[0] == review.R_NEW_MONEY
    sells, buys = _moves(book, plan)
    assert buys == pytest.approx(sells)


def test_an_add_the_sales_reach_by_a_crumb_waits_whole():
    book = [(DEAR_WEAK, 0.004), (CHEAP_QUALITY, 0.02)] + [(FAIR_QUALITY, 0.122)] * 8
    plan = _plan(*book)
    assert plan[0].verdict == review.SELL
    assert plan[1].verdict == review.HOLD and plan[1].want == review.ADD_TO


def _scored(monkeypatch, quality, cheapness):
    monkeypatch.setattr(
        review, "score", lambda metrics: review.Scores(quality, cheapness, cheap_reads=2)
    )


@pytest.mark.parametrize("quality, cheapness", [(38.0, 30.0), (30.0, 38.0)])
def test_a_name_between_the_sell_lines_is_a_close_call_held(
    monkeypatch, quality, cheapness
):
    _scored(monkeypatch, quality, cheapness)
    v = review.judge_held({}, weight=0.05, names=20)
    assert v.verdict == review.HOLD and v.reasons[0] == review.R_CLOSE_CALL
    # Proposed before and still under the plain line: the sale stands.
    kept = review.judge_held({}, weight=0.05, names=20, was=review.SELL)
    assert kept.verdict == review.SELL


def test_a_name_under_both_new_lines_is_sold_whatever_was_proposed(monkeypatch):
    _scored(monkeypatch, 30.0, 30.0)
    for was in (None, review.SELL, review.ADD):
        verdict = review.judge_held({}, weight=0.05, names=20, was=was)
        assert verdict.verdict == review.SELL


def test_a_new_add_clears_the_lines_by_a_margin_and_an_old_one_holds_to_them(
    monkeypatch,
):
    _scored(monkeypatch, review.GOOD + 2, review.CHEAP + 2)
    v = review.judge_held({}, weight=0.02, names=20)
    assert v.verdict == review.HOLD and v.reasons[0] == review.R_CLOSE_CALL
    kept = review.judge_held({}, weight=0.02, names=20, was=review.ADD)
    assert kept.verdict == review.ADD
    _scored(monkeypatch, review.GOOD + 6, review.CHEAP + 6)
    assert review.judge_held({}, weight=0.02, names=20).verdict == review.ADD


def test_a_full_position_between_the_add_lines_is_no_close_call(monkeypatch):
    _scored(monkeypatch, review.GOOD + 2, review.CHEAP + 2)
    v = review.judge_held({}, weight=0.05, names=20)
    assert v.verdict == review.HOLD and review.R_CLOSE_CALL not in v.reasons


def test_an_outside_buy_clears_the_margin_unless_it_was_proposed(monkeypatch):
    _scored(monkeypatch, review.GOOD + 2, review.CHEAP + 2)
    v = review.judge_candidate({})
    assert v.verdict == review.WATCH and review.R_CLOSE_CALL in v.reasons
    assert review.judge_candidate({}, was=review.BUY).verdict == review.BUY


def test_a_sale_that_costs_more_in_tax_than_its_case_is_worth_waits():
    sell = review.judge_held(DEAR_WEAK, weight=0.05, names=20)
    assert sell.verdict == review.SELL
    held = review.hold_for_cost(sell, 0.08)
    assert held.verdict == review.HOLD and held.target is None
    assert held.reasons[0] == review.R_SALE_COSTLY
    # Cheap in tax, or no replay to say: the sale stands.
    assert review.hold_for_cost(sell, 0.03) is sell
    assert review.hold_for_cost(sell, None) is sell


def test_a_business_too_weak_to_keep_is_sold_whatever_the_tax(monkeypatch):
    _scored(monkeypatch, review.COSTLY_FLOOR - 5, 10.0)
    sell = review.judge_held({}, weight=0.05, names=20)
    assert review.hold_for_cost(sell, 0.20) is sell


def test_a_crumb_is_sold_whatever_its_tax():
    crumb = review.judge_held(MIDDLING, weight=0.002, names=20)
    assert review.R_SMALL in crumb.reasons
    assert review.hold_for_cost(crumb, 0.20) is crumb


def test_acquired_goodwill_does_not_sink_the_return_on_capital():
    bought = DEAR_WEAK | {"roic_ex_goodwill": 0.12}
    assert review.score(bought).quality > review.score(DEAR_WEAK).quality
    assert review.R_LOW_ROIC not in review.judge_held(bought, weight=0.05).reasons
    # The lower of the two never drags a high plain ROIC down.
    plain = CHEAP_QUALITY | {"roic_ex_goodwill": 0.05}
    assert review.score(plain).quality == review.score(CHEAP_QUALITY).quality


def test_new_money_wishes_count_toward_idle_cash():
    rows = _rows(("money_market", None, 0.25), ("stock", None, 0.75))
    assert review.cash_note(rows, [review.HOLD]) is None
    assert review.cash_note(rows, [review.HOLD], waiting=1) is not None


def test_a_top_up_too_small_to_trade_is_left_alone():
    book = [(DEAR_WEAK, 0.003)] + [(FAIR_QUALITY, 0.20)] * 4 + [(FAIR_QUALITY, 0.16)]
    plan = _plan(*book)
    assert plan[0].verdict == review.SELL
    assert {v.verdict for v in plan[1:]} == {review.HOLD}


def test_a_grower_is_only_topped_up_to_a_bet_size():
    plan = _plan(*SEVEN[:3], (FAST_GROWER, 0.02), *SEVEN[3:])
    grower = plan[3]
    assert grower.verdict == review.ADD and grower.target == review.SPEC_MAX


def test_a_name_a_hair_under_its_mark_is_not_told_to_buy():
    assert review.judge_held(CHEAP_QUALITY, weight=0.048).verdict == review.HOLD
    v = review.judge_held(CHEAP_QUALITY, weight=0.04)
    assert v.verdict == review.ADD and v.target == review.ADD_TO


def _trim(weight=0.30, metrics=DEAR_QUALITY, names=7):
    return review.judge_held(metrics, weight=weight, names=names)


def test_a_concentration_cut_dear_in_tax_is_taken_in_two_steps():
    v = _trim()
    assert v.verdict == review.TRIM
    staged = review.stage_for_tax(0.30, v, 0.12)
    assert staged.target == pytest.approx(0.30 - (0.30 - v.target) / 2)
    assert staged.reasons[:2] == (review.R_CONCENTRATED, review.R_TAX_STAGED)
    # Cheap in tax, or no replay to say: the whole cut stands.
    assert review.stage_for_tax(0.30, v, 0.05) is v
    assert review.stage_for_tax(0.30, v, None) is v


def test_a_sale_for_quality_is_not_deferred_for_tax():
    sell = review.judge_held(DEAR_WEAK, weight=0.10, names=12)
    poor = MIDDLING | {"roic": 0.02, "moat": 20.0}
    weak = review.judge_held(poor, weight=0.08, names=12)
    for v in (sell, weak):
        assert v.verdict in (review.SELL, review.TRIM)
        assert review.R_CONCENTRATED not in v.reasons
        assert review.stage_for_tax(0.10, v, 0.5) is v


def test_one_sector_carrying_the_book_is_named_and_gets_none_of_the_sales():
    tech = ["Technology"] * len(SEVEN)
    judged = [
        (w, review.judge_held(m, weight=w, names=len(SEVEN))) for m, w in SEVEN
    ]
    plan = review.redeploy(judged, tech)
    assert not any(review.R_REDEPLOY in v.reasons for v in plan)
    assert _moves(SEVEN, plan)[1] == 0
    [note] = review.book_notes(_rows(*[("stock", "Technology", w) for _, w in SEVEN]))
    assert note.key == review.N_SECTOR_HEAVY and note.count == 7
    assert note.weight == pytest.approx(sum(w for _, w in SEVEN))


def test_the_sales_spread_only_up_to_a_sectors_line():
    # The cut names are tech; the fair names fill a sector of their own up
    # to the line and no further.
    sectors = ["Technology"] * 3 + ["Health"] * 3 + ["Energy"]
    judged = [
        (w, review.judge_held(m, weight=w, names=len(SEVEN))) for m, w in SEVEN
    ]
    plan = review.redeploy(judged, sectors)
    health = sum(
        v.target if v.target is not None else w
        for (_, w), v in zip(SEVEN[3:6], plan[3:6], strict=True)
    )
    assert health <= review.SECTOR_LINE + 1e-9
    assert any(review.R_REDEPLOY in v.reasons for v in plan[3:6])


def test_an_underweight_add_into_a_full_sector_is_held():
    judged = [
        (0.04, review.judge_held(CHEAP_QUALITY, weight=0.04, names=12)),
        (0.40, review.Verdict(review.HOLD)),
    ]
    assert judged[0][1].verdict == review.ADD
    add, _ = review.redeploy(judged, ["Technology", "Technology"])
    assert add.verdict == review.HOLD and add.target is None
    assert add.reasons[0] == review.R_SECTOR_FULL
    assert review.R_UNDERWEIGHT not in add.reasons


def test_one_company_alone_is_a_concentration_not_a_sector():
    rows = _rows(("stock", "Technology", 0.45), *[("stock", s, 0.11) for s in "ABCDE"])
    assert review.book_notes(rows) == []


def test_heavy_crypto_is_named_never_cut():
    rows = _rows(("crypto", None, 0.40), *[("stock", None, 0.15)] * 4)
    assert review.book_notes(rows) == [review.Note(review.N_CRYPTO_HEAVY, weight=0.40)]
    assert review.judge_held(None, weight=0.40, kind="crypto").verdict == review.UNRATED


def test_one_country_carrying_the_book_is_named_whichever_it_is():
    rows = _rows(
        *[("stock", s, 0.24, "Spain", "EUR") for s in "ABC"],
        ("stock", "D", 0.28, "United States", "USD"),
    )
    [note] = review.book_notes(rows, "EUR")
    assert note.key == review.N_COUNTRY_HEAVY and note.country == "Spain"
    assert note.count == 3 and note.weight == pytest.approx(0.72)


def test_two_companies_from_one_country_are_not_a_home_bias():
    rows = _rows(("stock", "A", 0.40, "Spain"), ("stock", "B", 0.40, "Spain"))
    assert review.N_COUNTRY_HEAVY not in [n.key for n in review.book_notes(rows)]


def test_a_book_quoted_in_another_currency_is_named_against_the_readers():
    rows = _rows(
        *[("stock", s, 0.2, "United States", "USD") for s in "ABCD"],
        ("equity_fund", None, 0.1, None, "USD"),
        ("money_market", None, 0.1, None, "EUR"),
    )
    notes = review.book_notes(rows, "EUR")
    [note] = [n for n in notes if n.key == review.N_CURRENCY_HEAVY]
    assert note.currency == "USD" and note.weight == pytest.approx(0.9)
    # Read in dollars, the same book is at home.
    assert review.N_CURRENCY_HEAVY not in [n.key for n in review.book_notes(rows, "USD")]


def test_idle_cash_is_named_only_beside_something_to_buy():
    rows = _rows(("money_market", None, 0.30), *[("stock", s, 0.14) for s in "ABCDE"])
    assert review.cash_note(rows, [review.HOLD, review.SELL]) is None
    note = review.cash_note(rows, [review.ADD, review.HOLD, review.BUY])
    assert note == review.Note(review.N_CASH_HEAVY, count=2, weight=0.30)
    assert review.cash_note(_rows(("money_market", None, 0.10)), [review.BUY]) is None


# -- Data the feed lacks, and businesses judged on their own ruler ----------

MATURE_NO_ESTIMATES = {
    "pe_ttm": 9.0,
    "ev_ebitda": 9.0,
    "fcf_yield": 0.06,
    "ev": 1e9,
    "roic": 0.30,
    "op_margin": 0.30,
    "moat": 70.0,
}


def test_a_trailing_pe_stands_in_when_analysts_do_not_cover_the_name():
    s = review.score(MATURE_NO_ESTIMATES)
    assert s.trailing_pe
    with_forward = review.score({**MATURE_NO_ESTIMATES, "pe_fwd": 9.0})
    assert s.cheapness == with_forward.cheapness
    held = review.judge_held(MATURE_NO_ESTIMATES, weight=0.02)
    assert review.R_TRAILING_PE in held.reasons
    losing = review.judge_held({**MATURE_NO_ESTIMATES, "pe_ttm": -5.0}, weight=0.02)
    assert review.R_LOSS in losing.reasons


def test_book_value_prices_a_name_the_feed_gives_one_multiple_for():
    thin = {"pe_fwd": 10.0, "pb": 1.0, "roic": 0.30, "op_margin": 0.30, "moat": 70.0}
    s = review.score(thin)
    assert s.cheapness is not None and s.book_priced
    assert review.R_BOOK_PRICED in review.judge_held(thin, weight=0.02).reasons
    # With two prices of its own, book stays out.
    assert not review.score({**thin, "ev_ebitda": 9.0}).book_priced


BANK = {
    "industry": "Banks - Diversified",
    "roe": 0.13,
    "net_income_cagr": 0.10,
    "share_dilution": -0.03,
    "pe_fwd": 7.0,
    "pb": 0.9,
    "fcf_yield": -0.5,
    "fcf": -5e10,
    "net_debt_ebitda": 10.0,
    "ev": -1e10,
    "roic": 0.02,
    "op_margin": 0.35,
    "moat": 30.0,
}


def test_a_bank_is_priced_on_its_book_not_its_cash_flow():
    v = review.judge_held(BANK, weight=0.02)
    assert v.verdict == review.ADD
    assert v.reasons[0] == review.R_FINANCIAL_LENS
    for wrong in (
        review.R_NEGATIVE_FCF,
        review.R_DEBT,
        review.R_SUSPECT,
        review.R_LOW_ROIC,
        review.R_NO_MOAT,
    ):
        assert wrong not in v.reasons
    assert v.metrics["pb"] == 0.9 and v.metrics["roe"] == 0.13


def test_an_insurer_with_a_negative_enterprise_value_is_still_rated():
    insurer = {
        "industry": "Insurance - Diversified",
        "ev": -2e10,
        "roe": 0.12,
        "net_income_cagr": 0.08,
        "pb": 1.5,
        "pe_fwd": 20.0,
    }
    s = review.score(insurer)
    assert not s.suspect and s.quality is not None and s.cheapness is not None
    assert review.judge_candidate(insurer).verdict != review.UNRATED


def test_a_bank_paying_more_for_its_book_than_its_return_earns_reads_dear():
    dear = {**BANK, "roe": 0.05, "net_income_cagr": 0.0, "pb": 2.0, "pe_fwd": 18.0}
    v = review.judge_candidate(dear)
    assert v.verdict == review.PASS
    assert review.R_EXPENSIVE in v.reasons and review.R_LOW_ROE in v.reasons


def test_a_bank_is_priced_on_its_tangible_book():
    # Same book on paper, but most of it goodwill: on tangible book it costs
    # far more, for a thinner return on the capital that is left.
    tangible = {**BANK, "ptbv": 1.0, "rotce": 0.17}
    padded = {**BANK, "ptbv": 2.4, "rotce": 0.08}
    assert review.score(tangible).cheapness > review.score(padded).cheapness
    # (17% - 3%) / (10% - 3%) = 2x justified: 1x paid is half of it.
    assert review._pb_for_roe(tangible) == pytest.approx(0.5)
    # Earning under the growth rate: no price is cheap.
    assert review._pb_for_roe({**BANK, "ptbv": 0.5, "rotce": 0.02}) == float("inf")
    shown = review.judge_held(tangible, weight=0.02).metrics
    assert shown["ptbv"] == 1.0 and shown["rotce"] == 0.17
    firm = review.judge_held({**CHEAP_QUALITY, "ptbv": 30.0}, weight=0.02).metrics
    assert firm["ptbv"] is None
    # Without a tangible book, the whole book.
    assert review._pb_for_roe(BANK) == pytest.approx(0.9 / ((0.13 - 0.03) / 0.07))


def test_a_name_nobody_trades_is_not_added_to():
    _blocked({**CHEAP_QUALITY, "turnover_usd": 4e5}, review.R_THIN_TRADING)
    liquid = review.judge_held({**CHEAP_QUALITY, "turnover_usd": 5e7}, weight=0.02)
    assert review.R_THIN_TRADING not in liquid.reasons


def test_insiders_holding_a_tenth_are_named_not_scored():
    owned = {**CHEAP_QUALITY, "insider_share": 0.14}
    assert review.R_INSIDERS_OWN in review.judge_held(owned, weight=0.02).reasons
    assert review.score(owned) == review.score(CHEAP_QUALITY)
    few = {**CHEAP_QUALITY, "insider_share": 0.02}
    assert review.R_INSIDERS_OWN not in review.judge_held(few, weight=0.02).reasons


def test_a_bank_never_reads_as_a_growth_or_early_stage():
    racing = {
        **BANK,
        "industry": "Banks - Regional",
        "revenue_growth": 0.40,
        "revenue_cagr": 0.40,
        "op_margin": 0.05,
        "revenue": 1.0,
        "market_cap": 100.0,
    }
    assert review.stage(racing) == review.MATURE
    assert review.judge_held(racing, weight=0.02).verdict != review.BET


REIT = {
    "industry": "REIT - Industrial",
    "roe": 0.06,
    "revenue_cagr": 0.07,
    "share_dilution": 0.02,
    "op_margin": 0.45,
    "pb": 1.0,
    "pe_fwd": 20.0,
    "ev_ebitda": 15.0,
    "dividend_yield": 0.05,
    "payout_ratio": 1.4,
    "fcf_yield": -0.03,
    "roic": 0.03,
    "moat": 30.0,
}


def test_a_reit_is_not_a_heavy_debtor_at_six_times_ebitda():
    v = review.judge_held({**REIT, "net_debt_ebitda": 6.0}, weight=0.02)
    assert review.R_DEBT not in v.reasons
    assert v.reasons[0] == review.R_REIT_LENS
    heavy = review.judge_held({**REIT, "net_debt_ebitda": 9.0}, weight=0.02)
    assert review.R_DEBT in heavy.reasons


def test_a_reit_is_priced_on_book_ffo_and_yield():
    s = review.score(REIT)
    assert s.lens == review.REAL_ESTATE
    assert s.quality is not None and s.cheapness is not None
    pricier = review.score({**REIT, "pb": 1.8, "dividend_yield": 0.02})
    assert pricier.cheapness < s.cheapness


def test_a_reit_paying_out_its_earnings_is_not_stretched():
    v = review.judge_held(REIT, weight=0.02)
    assert review.R_PAYOUT_STRETCHED not in v.reasons
    for wrong in (review.R_NEGATIVE_FCF, review.R_LOW_ROIC, review.R_NO_MOAT):
        assert wrong not in v.reasons


# A regulated network as the feed reads it: low ROIC, capex past its cash
# flow and no moat on a company's ruler.
UTILITY = {
    "industry": "Utilities - Regulated Electric",
    "roe": 0.11, "net_income_cagr": 0.05, "share_dilution": 0.0,
    "pe_fwd": 14.0, "ev_ebitda": 9.0, "dividend_yield": 0.045,
    "roic": 0.05, "op_margin": 0.30, "fcf_yield": -0.03, "moat": 30.0,
    "runway_years": 0.5, "ev": 1e11,
}


def test_a_utility_carries_four_times_ebitda_without_blocking_an_add():
    assert (
        review.judge_held({**UTILITY, "net_debt_ebitda": 4.0}, weight=0.02).verdict
        == review.ADD
    )
    _blocked({**UTILITY, "net_debt_ebitda": 5.5}, review.R_DEBT)


def test_a_regulated_utility_is_judged_on_its_allowed_return_not_its_roic():
    s = review.score({**UTILITY, "net_debt_ebitda": 4.0})
    assert s.lens == review.UTILITY
    assert s.quality >= review.GOOD and s.cheapness >= review.CHEAP
    v = review.judge_held({**UTILITY, "net_debt_ebitda": 4.0}, weight=0.02)
    assert v.reasons[0] == review.R_UTILITY_LENS
    for company_ruler in (
        review.R_LOW_ROIC, review.R_NEGATIVE_FCF, review.R_NO_MOAT,
        review.R_SHORT_RUNWAY,
    ):
        assert company_ruler not in v.reasons
    weak = review.score({**UTILITY, "roe": 0.05, "net_income_cagr": -0.04})
    assert weak.quality < s.quality


def test_a_utility_paying_past_its_free_cash_flow_is_funding_capex_not_stretched():
    funded = {**UTILITY, "net_debt_ebitda": 4.0, "dividend_fcf": 1.5}
    v = review.judge_held(funded, weight=0.02)
    assert review.R_PAYOUT_STRETCHED not in v.reasons
    _blocked({**funded, "payout_ratio": 1.15}, review.R_PAYOUT_STRETCHED)


def test_a_renewables_developer_keeps_the_standard_lens():
    assert review.lens({"industry": "Utilities - Renewable"}) == review.STANDARD
    assert (
        review.lens({"industry": "Utilities - Independent Power Producers"})
        == review.STANDARD
    )


def test_a_lender_outside_the_financial_industries_still_falls_back_on_the_float():
    card = {
        **CHEAP_QUALITY,
        "industry": "Credit Services",
        "fcf_yield": 0.39,
        "fcf_ebitda": 6.0,
        "pb": 1.2,
    }
    s = review.score(card)
    assert s.lens == review.STANDARD and s.fcf_float


# -- Dividends --------------------------------------------------------------

PAYER = {"pe_fwd": 25.0, "ev_ebitda": 20.0, "roic": 0.30, "op_margin": 0.30, "moat": 70.0}


def test_a_high_yield_counts_toward_a_mature_names_price():
    plain = review.score(PAYER).cheapness
    assert review.score({**PAYER, "dividend_yield": 0.05}).cheapness > plain
    # A token payout is not held against a name that reinvests.
    assert review.score({**PAYER, "dividend_yield": 0.015}).cheapness == plain


def test_a_dividend_earnings_cover_is_not_stretched_by_a_short_cash_flow_alone():
    # Coca-Cola: 62% of earnings, 116% of four years' free cash flow.
    ko = {**CHEAP_QUALITY, "payout_ratio": 0.62, "dividend_fcf": 1.16}
    assert review.R_PAYOUT_STRETCHED not in review.judge_held(ko, weight=0.02).reasons
    _blocked({**ko, "payout_ratio": 0.80}, review.R_PAYOUT_STRETCHED)
    _blocked({**ko, "dividend_fcf": 1.6}, review.R_PAYOUT_STRETCHED)


def test_a_two_percent_payer_is_not_dearer_than_a_name_that_pays_nothing():
    # Inditex: a 2.2% yield scored 24 and pulled a cheap name under the line.
    plain = review.score(PAYER).cheapness
    assert review.score({**PAYER, "dividend_yield": 0.022}).cheapness == plain
    assert review.score({**PAYER, "dividend_yield": 0.034}).cheapness == plain


def test_a_stretched_payout_stops_an_add():
    _blocked({**CHEAP_QUALITY, "payout_ratio": 1.2}, review.R_PAYOUT_STRETCHED)
    _blocked({**CHEAP_QUALITY, "dividend_fcf": 1.5}, review.R_PAYOUT_STRETCHED)


def test_a_four_percent_yield_is_named_never_a_verdict():
    v = review.judge_held({**DEAR_WEAK, "dividend_yield": 0.06}, weight=0.03)
    assert v.verdict == review.SELL
    assert review.R_DIVIDEND in v.reasons


# --- Sizes that follow the book's shape --------------------------------------


def test_the_small_line_shrinks_with_a_wide_book():
    assert review.small_line(None) == review.SMALL
    assert review.small_line(50) == review.SMALL
    assert review.small_line(200) == pytest.approx(0.0025)


def test_a_two_hundred_name_book_does_not_sell_every_crumb():
    # 0.4% is an even share of 200 names, not a crumb.
    assert review.judge_held(CHEAP_WEAK, weight=0.004).verdict == review.SELL
    assert review.judge_held(CHEAP_WEAK, weight=0.004, names=200).verdict == review.HOLD


def test_only_the_weakest_crumbs_are_sold_in_one_pass():
    crumbs = [
        review.Verdict(review.SELL, (review.R_SMALL,), 45.0 + i, 50.0, 0.0)
        for i in range(8)
    ]
    poor = review.Verdict(review.SELL, (review.R_SMALL,), 20.0, 20.0, 0.0)
    out = review.cap_small_sells([*crumbs, poor])
    sold = [v for v in out if v.verdict == review.SELL]
    assert len(sold) == review.SMALL_SELLS_MAX + 1
    assert out[-1].verdict == review.SELL
    # The best three wait, still named small and moving nothing.
    for v in out[5:8]:
        assert v.verdict == review.HOLD and v.target is None
        assert review.R_SMALL in v.reasons
    assert review.cap_small_sells(crumbs[:5]) == crumbs[:5]


def test_an_add_in_a_wide_book_is_twice_an_even_share_not_five_percent():
    assert review.add_line(10) == review.ADD_TO
    assert review.add_line(40) == review.ADD_TO
    assert review.add_line(50) == pytest.approx(0.04)
    assert review.add_line(200) == pytest.approx(0.01)
    assert review.add_line(500) == review.ADD_MIN
    v = review.judge_held(CHEAP_QUALITY, weight=0.005, names=100)
    assert v.verdict == review.ADD
    assert v.target == pytest.approx(0.02)


def test_a_satellite_is_not_filled_past_its_slice():
    # Five companies beside an index fund at 80%: an even share of their
    # fifth of the book is 4%, so a freed sale fills one to the add line.
    alone = review.judge_held(CHEAP_QUALITY, weight=0.03, names=5)
    beside = review.judge_held(CHEAP_QUALITY, weight=0.03, names=5, company_share=0.2)
    assert alone.fill == pytest.approx(0.2)
    assert beside.fill == review.ADD_TO


# --- Outside buys sized with what the sales leave -----------------------------


def _buy(q: float = 80.0, fill: float = review.ADD_TO) -> review.Verdict:
    return review.Verdict(review.BUY, (), q, 70.0, None, {}, fill)


def test_what_the_sales_leave_goes_to_the_best_outside_buys_first():
    sold = review.Verdict(review.SELL, (), 20.0, 20.0, 0.0)
    targets, left = review.place_outside(
        [(0.08, sold)], [None], [(_buy(70.0), None), (_buy(90.0), None)]
    )
    # 8% freed: the better buy opens at 5%, the other takes the 3% left.
    assert targets == [pytest.approx(0.03), pytest.approx(0.05)]
    assert left == pytest.approx(0.0)


def test_an_outside_buy_never_fills_a_sector_past_its_line():
    sold = review.Verdict(review.SELL, (), 20.0, 20.0, 0.0)
    kept = review.Verdict(review.HOLD, (), 70.0, 60.0)
    targets, left = review.place_outside(
        [(0.10, sold), (0.38, kept)],
        ["Energy", "Technology"],
        [(_buy(), "Technology"), (_buy(), "Energy")],
    )
    # Technology sits at 38%: the buy there takes only the two points to
    # its line; Energy, emptied by the sale, takes its 5%.
    assert targets[0] == pytest.approx(0.02)
    assert targets[1] == pytest.approx(0.05)
    assert left == pytest.approx(0.03)


def test_no_buy_is_opened_under_a_crumb_and_a_watch_is_never_sized():
    sold = review.Verdict(review.SELL, (), 20.0, 20.0, 0.0)
    watch = review.Verdict(review.WATCH, (), 80.0, 40.0)
    targets, left = review.place_outside([(0.004, sold)], [None], [(_buy(), None)])
    assert targets == [None] and left == pytest.approx(0.004)
    targets, _ = review.place_outside([(0.05, sold)], [None], [(watch, None)])
    assert targets == [None]


def test_a_buy_is_sized_to_the_add_line_of_the_book_it_joins():
    assert review.judge_candidate(CHEAP_QUALITY).fill == review.ADD_TO
    assert review.judge_candidate(CHEAP_QUALITY, names=100).fill == pytest.approx(0.02)
    assert review.judge_candidate(DEAR_WEAK).fill is None


@pytest.mark.parametrize(
    ("industry", "unmapped"),
    [
        ("Banks - Savings", True),
        ("REIT - Data Centers", True),
        ("Utilities - Regulated Electric", False),
        ("Insurance Brokers", False),
        ("Utilities - Renewable", False),
        ("Semiconductors", False),
        (None, False),
    ],
)
def test_an_industry_that_sounds_like_a_lens_but_has_none_is_flagged(
    industry, unmapped
):
    assert review.unmapped_industry(industry) is unmapped


# ------------------------------------------------------------- at_price


def test_at_a_lower_price_the_same_business_reads_cheaper():
    """The map's trail: half the price is half every multiple and twice
    every yield; the business behind them does not move."""
    metrics = {**DEAR_QUALITY, "market_cap": 2.8e12, "pb": 12.0, "dividend_yield": 0.01}
    then = review.at_price(metrics, 0.5)
    assert then["pe_fwd"] == pytest.approx(16.0)
    assert then["pb"] == pytest.approx(6.0)
    assert then["fcf_yield"] == pytest.approx(0.06)
    assert then["dividend_yield"] == pytest.approx(0.02)
    # EV falls by the cap's change only: 3e12 - 1.4e12.
    assert then["ev"] == pytest.approx(1.6e12)
    assert then["ev_ebitda"] == pytest.approx(26.0 * 1.6 / 3.0)
    assert then["roic"] == metrics["roic"] and then["moat"] == metrics["moat"]
    now, past = review.score(metrics), review.score(then)
    # Quality reads the cash yield too, so it moves, but far less.
    assert past.cheapness - now.cheapness > 3 * abs(past.quality - now.quality)


def test_at_its_own_price_nothing_moves():
    metrics = {**CHEAP_QUALITY, "market_cap": 9e10}
    assert review.at_price(metrics, 1.0) == pytest.approx(metrics)
    assert review.at_price(metrics, 0.0) == metrics  # no price, no replay


def test_the_ticker_page_reads_the_same_cautions_and_peak_pe(monkeypatch):
    """The company page names what the review would hold against it, minus the
    one warning that is about the review's own cheap call."""
    peak = {
        **CHEAP_QUALITY,
        "pe_ttm": 10.0,
        "op_margin_median": 0.20,
        "revenue_down_years": 1,
    }
    assert review.R_PEAK_MARGIN in review.cautions(peak)
    assert review.peak_pe(peak) == pytest.approx(
        10.0 * peak["op_margin"] / peak["op_margin_median"]
    )
    assert review.peak_pe({**CHEAP_QUALITY, "pe_ttm": 10.0}) is None, "no peak"
    assert review.cautions({**peak, "quote_type": "ETF"}) == []
    monkeypatch.setattr(
        review, "_cautions", lambda m, s: [review.R_ONE_READING, review.R_DEBT]
    )
    assert review.cautions(CHEAP_QUALITY) == [review.R_DEBT]
