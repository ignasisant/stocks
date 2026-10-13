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
    assert s.cheapness >= review.CHEAP > s.price_floor
    _blocked(one_reading, review.R_ONE_READING)


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
    assert review.book_notes([("stock", "Technology", 1.0)]) == [
        review.Note(review.N_FEW_NAMES, count=1)
    ]


def test_two_good_companies_half_and_half_are_both_kept():
    plan = _plan((CHEAP_QUALITY, 0.5), (DEAR_QUALITY, 0.5))
    assert [v.verdict for v in plan] == [review.HOLD, review.HOLD]
    assert [n.key for n in review.book_notes([("stock", None, 0.5)] * 2)] == [
        review.N_FEW_NAMES
    ]


def test_a_narrow_book_still_sells_what_is_weak_on_both_scores():
    plan = _plan((DEAR_WEAK, 0.5), (CHEAP_QUALITY, 0.5))
    assert plan[0].verdict == review.SELL
    # With too few companies the money goes to new names, not to the one
    # already carrying the book.
    assert plan[1].verdict == review.HOLD


def test_a_fund_based_book_with_one_stock_on_the_side_says_nothing():
    plan = _plan((None, 0.85, "equity_fund"), (DEAR_QUALITY, 0.15))
    assert [v.verdict for v in plan] == [review.CORE, review.HOLD]
    assert review.book_notes([("equity_fund", None, 0.85), ("stock", None, 0.15)]) == []


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
    # Nothing sold: the underweight adds stand, nothing else is topped up.
    book = [(CHEAP_QUALITY, 0.02)] * 5 + [(FAIR_QUALITY, 0.10)] * 9
    plan = _plan(*book)
    assert [v.verdict for v in plan[:5]] == [review.ADD] * 5
    assert all(v.target == review.ADD_TO for v in plan[:5])
    assert {v.verdict for v in plan[5:]} == {review.HOLD}


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
    [note] = review.book_notes([("stock", "Technology", w) for _, w in SEVEN])
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
    rows = [("stock", "Technology", 0.45)] + [("stock", s, 0.11) for s in "ABCDE"]
    assert review.book_notes(rows) == []


def test_heavy_crypto_is_named_never_cut():
    rows = [("crypto", None, 0.40)] + [("stock", None, 0.15)] * 4
    assert review.book_notes(rows) == [review.Note(review.N_CRYPTO_HEAVY, weight=0.40)]
    assert review.judge_held(None, weight=0.40, kind="crypto").verdict == review.UNRATED
