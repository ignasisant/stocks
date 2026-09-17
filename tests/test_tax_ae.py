"""United Arab Emirates — the 0% jurisdiction. Pure, no network.

The interesting cases here are the ones where a zero must *stay* zero: a
losing year that would carry forward anywhere else, and a reporting flag that
no book is large enough to trip.
"""

import pytest

from stocks.portfolio import tax
from stocks.portfolio.positions import RealizedSale
from stocks.portfolio.tax import TaxSettings
from stocks.portfolio.tax.ae import (
    CORPORATE_RATE,
    CORPORATE_THRESHOLD_AED,
    RATE,
    fiscal_period,
    reporting_flags,
)


def sale(sell_date, cost, proceeds, ticker="AAPL", buy_date="2020-01-02"):
    return RealizedSale(ticker, buy_date, sell_date, 1, cost, proceeds, "AED")


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


def test_a_gain_held_one_day_is_taxed_the_same_as_one_held_a_decade():
    quick = year([sale("2025-03-10", 1_000, 5_000, buy_date="2025-03-09")])
    slow = year([sale("2025-03-10", 1_000, 5_000, buy_date="2015-03-09")])
    assert quick.estimated_tax == slow.estimated_tax == 0.0
    assert not tax.get("AE").splits_holding_period


def test_gains_and_losses_still_net_because_the_number_is_worth_seeing():
    ty = year([
        sale("2025-03-10", 10_000, 18_000),  # +8,000
        sale("2025-06-10", 10_000, 9_000, ticker="MSFT"),  # -1,000
    ])
    assert (ty.realized_gain, ty.realized_loss) == (8_000, 1_000)
    assert ty.net_taxable == pytest.approx(7_000)


# --- the zeros that have to stay zero ---

def test_a_losing_year_carries_nothing_forward():
    # Everywhere else this is a 6,000 deduction against a later gain. Here
    # there is no future tax to offset, so promising one would be a lie.
    ty = year([sale("2025-03-10", 10_000, 4_000)])
    assert ty.net_taxable == pytest.approx(-6_000)
    assert ty.carryforward_loss == 0.0
    assert tax.get("AE").carryforward_years == 0


def test_no_repurchase_rule_can_block_a_loss():
    # A buy the day after the sale would be a wash sale in the US and a
    # two-month-rule deferral in Spain. Nothing is disallowed without a tax.
    realized = [sale("2025-03-10", 10_000, 4_000)]
    ty = fiscal_period(realized, "2025", {"AAPL": ["2025-03-11"]}, None)
    assert ty.disallowed_loss == 0.0
    assert ty.deductible_loss == pytest.approx(6_000)
    assert tax.get("AE").repurchase_window == ""


def test_the_carryforward_tile_is_not_shown_at_all():
    ty = year([sale("2025-03-10", 10_000, 4_000)])
    assert [k.key for k in ty.kpis()] == ["net_taxable", "estimated_tax"]


# --- notes ---

def test_the_zero_and_the_corporate_boundary_are_always_said():
    ty = year([sale("2025-03-10", 1_000, 2_000)])
    assert {"no_tax_note", "corporate_note"} <= keys(ty)


def test_a_losing_year_says_the_loss_goes_nowhere():
    assert "no_carryforward_note" in keys(year([sale("2025-03-10", 10_000, 4_000)]))
    assert "no_carryforward_note" not in keys(year([sale("2025-03-10", 1_000, 2_000)]))


def test_the_corporate_figures_are_the_real_ones_for_the_note():
    assert (CORPORATE_RATE, CORPORATE_THRESHOLD_AED) == (0.09, 375_000.0)


# --- reporting ---

def test_no_book_is_large_enough_to_need_a_local_declaration():
    (flag,) = reporting_flags(50_000_000.0)
    assert flag.name == "no_local_reporting"
    assert not flag.reportable
    assert flag.threshold == float("inf")
    assert "CRS" in flag.message


def test_an_empty_book_reports_nothing_either():
    (flag,) = reporting_flags(0.0)
    assert not flag.reportable


# --- registry ---

def test_the_uae_is_registered_in_dirhams_on_the_calendar_year():
    j = tax.get("AE")
    assert (j.currency, j.matching, j.year_start) == ("AED", "fifo", (1, 1))
    assert not j.pools_shares
    # No brackets, so the Profile page offers this filer no tax inputs at all.
    assert j.settings_fields == () and j.filing_statuses == ()


def test_the_code_normalizes_from_either_case_or_a_subdivision():
    assert tax.normalize("ae") == "AE"
    assert tax.normalize("AE-DU") == "AE"  # Dubai; there is no emirate-level tax
