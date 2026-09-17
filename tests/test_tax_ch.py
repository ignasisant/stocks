"""Switzerland — exempt for private investors. Pure, no network.

The zeros have to stay zero, and the reporting duty has to stay *on* even
though nothing is taxed: a Swiss return lists every security whatever its
gain did.
"""

import pytest

from stocks.portfolio import tax
from stocks.portfolio.positions import RealizedSale
from stocks.portfolio.tax import TaxSettings
from stocks.portfolio.tax.ch import (
    DEALER_MAX_GAIN_SHARE_OF_INCOME,
    DEALER_MAX_TURNOVER_RATIO,
    DEALER_MIN_HOLD_MONTHS,
    RATE,
    fiscal_period,
    reporting_flags,
)


def sale(sell_date, cost, proceeds, ticker="NESN.SW", buy_date="2020-01-02"):
    return RealizedSale(ticker, buy_date, sell_date, 1, cost, proceeds, "CHF")


def year(realized, y=2025, **settings):
    return fiscal_period(realized, str(y), {}, TaxSettings(**settings))


def keys(period):
    return {n.key for n in period.notes()}


# --- nothing is taxed ---

def test_the_rate_is_zero():
    assert RATE == 0.0


def test_a_large_gain_owes_nothing():
    ty = year([sale("2025-03-10", 100_000, 900_000)])
    assert ty.net_taxable == pytest.approx(800_000)
    assert ty.estimated_tax == 0.0


def test_the_holding_period_changes_nothing_in_the_figures():
    # KS 36's six months decide whether you are a dealer at all; they are not
    # a rate split, so the engine must not model them as one.
    quick = year([sale("2025-03-10", 1_000, 5_000, buy_date="2025-03-09")])
    slow = year([sale("2025-03-10", 1_000, 5_000, buy_date="2015-03-09")])
    assert quick.estimated_tax == slow.estimated_tax == 0.0
    assert not tax.get("CH").splits_holding_period


# --- the zeros that have to stay zero ---

def test_an_exempt_gain_means_a_non_deductible_loss():
    ty = year([sale("2025-03-10", 10_000, 4_000)])
    assert ty.net_taxable == pytest.approx(-6_000)
    assert ty.carryforward_loss == 0.0
    assert tax.get("CH").carryforward_years == 0


def test_no_repurchase_rule_can_block_a_loss():
    realized = [sale("2025-03-10", 10_000, 4_000)]
    ty = fiscal_period(realized, "2025", {"NESN.SW": ["2025-03-11"]}, None)
    assert ty.disallowed_loss == 0.0
    assert tax.get("CH").repurchase_window == ""


def test_the_carryforward_tile_is_not_shown_at_all():
    ty = year([sale("2025-03-10", 10_000, 4_000)])
    assert [k.key for k in ty.kpis()] == ["net_taxable", "estimated_tax"]


# --- notes ---

def test_the_exemption_and_the_dealer_test_are_always_said():
    # The dealer test is the whole risk: never let the 0% render without it.
    ty = year([sale("2025-03-10", 1_000, 2_000)])
    assert {"exempt_note", "dealer_note", "wealth_note"} <= keys(ty)


def test_a_losing_year_says_the_loss_relieves_nothing():
    assert "no_relief_note" in keys(year([sale("2025-03-10", 10_000, 4_000)]))
    assert "no_relief_note" not in keys(year([sale("2025-03-10", 1_000, 2_000)]))


def test_the_safe_harbour_numbers_are_the_ks36_ones():
    assert DEALER_MIN_HOLD_MONTHS == 6
    assert DEALER_MAX_TURNOVER_RATIO == 5.0
    assert DEALER_MAX_GAIN_SHARE_OF_INCOME == 0.50


# --- reporting ---

def test_every_holding_is_declared_however_small():
    (flag,) = reporting_flags(1_000.0)
    assert flag.name == "wertschriftenverzeichnis"
    assert flag.reportable and flag.threshold == 0.0


def test_the_duty_is_not_a_foreign_asset_threshold():
    # Unlike AE (no declaration at all, threshold inf), Switzerland does ask —
    # it just asks at any amount.
    assert reporting_flags(0.0)[0].reportable
    assert tax.get("AE").reporting_flags(1e9)[0].reportable is False


# --- registry ---

def test_switzerland_is_registered_in_francs_on_the_calendar_year():
    j = tax.get("CH")
    assert (j.currency, j.matching, j.year_start) == ("CHF", "fifo", (1, 1))
    assert not j.pools_shares
    # No brackets, so the Profile page offers this filer no tax inputs at all.
    assert j.settings_fields == () and j.filing_statuses == ()
