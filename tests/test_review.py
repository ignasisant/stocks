"""The Review engine: verdicts off a dict of KPIs, no network."""

from __future__ import annotations

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
    v = review.judge_held(CHEAP_QUALITY, weight=0.20)
    assert v.verdict == review.TRIM
    assert v.target == review.CONCENTRATED_TO
    assert v.reasons[0] == review.R_CONCENTRATED


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


def test_a_concentrated_name_is_cut_even_when_it_cannot_be_scored():
    broken = {**CHEAP_QUALITY, "fcf_yield": 0.95, "ev": -3.4e11}
    v = review.judge_held(broken, weight=0.22)
    assert v.verdict == review.TRIM
    assert v.target == review.CONCENTRATED_TO
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
