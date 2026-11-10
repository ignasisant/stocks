"""The entry checklist (`stocks.portfolio.entry`): what a buy or an add is held
to, read on one company's Review metrics. It only ever tells, so the cases
that matter are the ones that would mislead: a missing figure read as a pass
or a fail, a percent read against a fraction, a forward loss under a P/E line.
"""

from __future__ import annotations

from stocks.portfolio import entry

METRICS = {
    "revenue_growth": 0.22,
    "revenue_cagr": 0.10,
    "op_margin": 0.31,
    "fcf_yield": 0.025,
    "roic": 0.18,
    "roic_ex_goodwill": 0.41,
    "pe_fwd": 34.0,
    "net_debt_ebitda": -0.8,
    "share_dilution": 0.004,
    "dividend_yield": None,
}


def _checklist(**levels) -> entry.Checklist:
    return entry.parse({"rules": [{"rule": r, "level": v} for r, v in levels.items()]})


def test_clean_keeps_the_last_line_per_measure_in_catalog_order():
    kept = entry.clean([
        {"rule": "pe_fwd_max", "level": 40},
        {"rule": "REVENUE_GROWTH_MIN", "level": "15 %"},
        {"rule": "pe_fwd_max", "level": "30"},
        {"rule": "beta_max", "level": 1},
        {"rule": "roic_min", "level": float("nan")},
        "junk",
    ])
    assert kept == (entry.Rule("revenue_growth_min", 15.0),
                    entry.Rule("pe_fwd_max", 30.0))


def test_clean_drops_levels_no_company_could_be_read_against():
    assert entry.clean([{"rule": "pe_fwd_max", "level": 0}]) == ()
    assert entry.clean([{"rule": "pe_fwd_max", "level": 900}]) == ()
    assert entry.clean([{"rule": "weight_max", "level": 120}]) == ()
    assert entry.clean([{"rule": "op_margin_min", "level": 5000}]) == ()
    # A buyback line is a negative percent and stays.
    assert entry.clean([{"rule": "dilution_max", "level": -1}]) == (
        entry.Rule("dilution_max", -1.0),)


def test_parse_is_none_for_nothing_and_keeps_a_note_alone():
    assert entry.parse(None) is None
    assert entry.parse({"rules": [], "note": "  "}) is None
    alone = entry.parse({"note": "no biotech"})
    assert alone is not None and alone.rules == () and alone.note == "no biotech"
    assert len(entry.parse({"note": "x" * 2000}).note) == entry.MAX_NOTE


def test_stored_round_trips():
    checklist = _checklist(roic_min=12, pe_fwd_max=30)
    assert entry.parse(entry.stored(checklist)) == checklist
    assert entry.stored(None) is None


def test_percent_lines_read_fractions_as_percents():
    readings = {r.rule: r for r in entry.check(
        _checklist(revenue_growth_min=15, op_margin_min=35, fcf_yield_min=2),
        METRICS)}
    assert readings["revenue_growth_min"] == entry.Reading(
        "revenue_growth_min", 15, 22.0, entry.PASS)
    margin = readings["op_margin_min"]
    assert margin.state == entry.FAIL and margin.value == 31.0
    assert readings["fcf_yield_min"].state == entry.PASS


def test_growth_falls_back_to_the_long_run_and_roic_reads_the_higher():
    no_recent = {**METRICS, "revenue_growth": None}
    (growth,) = entry.check(_checklist(revenue_growth_min=15), no_recent)
    assert growth.value == 10.0 and growth.state == entry.FAIL
    (roic,) = entry.check(_checklist(roic_min=30), METRICS)
    assert roic.value == 41.0 and roic.state == entry.PASS


def test_a_missing_figure_is_unknown_never_a_verdict():
    (pe,) = entry.check(_checklist(pe_fwd_max=30), {"pe_fwd": None, "roic": 0.1})
    assert pe.state == entry.UNKNOWN and pe.value is None
    assert entry.check(_checklist(pe_fwd_max=30), {})[0].state == entry.UNKNOWN


def test_a_forward_loss_fails_a_pe_line():
    (pe,) = entry.check(_checklist(pe_fwd_max=30), {"pe_fwd": -12.0})
    assert pe.state == entry.FAIL


def test_net_cash_passes_a_leverage_line():
    (debt,) = entry.check(_checklist(net_debt_ebitda_max=2), METRICS)
    assert debt.state == entry.PASS


def test_no_dividend_on_file_is_zero_once_the_feed_answered():
    (div,) = entry.check(_checklist(dividend_yield_min=2), METRICS)
    assert div.value == 0.0 and div.state == entry.FAIL
    assert entry.check(_checklist(dividend_yield_min=2), {})[0].state == entry.UNKNOWN


def test_weight_holds_an_add_and_passes_a_name_not_held():
    checklist = _checklist(weight_max=8)
    assert entry.check(checklist, METRICS, weight=0.12)[0].state == entry.FAIL
    assert entry.check(checklist, METRICS, weight=0.05)[0].state == entry.PASS
    assert entry.check(checklist, METRICS, weight=None)[0].state == entry.PASS


def test_summary_counts_what_a_chip_prints():
    readings = entry.check(_checklist(pe_fwd_max=30, roic_min=12, fcf_yield_min=2),
                           {**METRICS, "fcf_yield": None})
    assert entry.summary(readings) == {"met": 1, "failed": 1, "unknown": 1, "total": 3}


def test_describe_tells_the_assistant_to_say_never_to_drop():
    said = entry.describe(entry.parse({
        "rules": [{"rule": "pe_fwd_max", "level": 30},
                  {"rule": "weight_max", "level": 8}],
        "note": "no pre-revenue biotech",
    }))
    assert "forward P/E at most 30x" in said and "past 8% of the book" in said
    assert '"no pre-revenue biotech"' in said and "never drop" in said
    assert entry.describe(None) == ""
