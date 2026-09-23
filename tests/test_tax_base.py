"""The jurisdiction-neutral scaffolding every country module opens with.

`open_period` and `sales_in` were ten copies of the same eleven lines before
they moved to base.py; these cover them once, so a change to the stamp or the
period filter fails here rather than in ten country suites at once.
"""

import pytest

from stocks.portfolio.positions import RealizedSale
from stocks.portfolio.tax import TaxSettings
from stocks.portfolio.tax.base import (
    Kpi,
    TaxPeriod,
    open_period,
    sales_in,
    total_of,
)
from stocks.portfolio.tax.us import UsTaxPeriod


def sale(sell_date, ticker="AAPL"):
    return RealizedSale(ticker, "2020-01-02", sell_date, 1, 100.0, 150.0, "USD")


# --- open_period ---

def test_the_period_carries_its_jurisdiction_currency_and_year():
    out = open_period(TaxPeriod, "ES", "EUR", "2025")
    assert (out.jurisdiction, out.currency, out.year) == ("ES", "EUR", 2025)


def test_a_month_slice_keeps_the_month_and_still_reads_the_year_off_it():
    out = open_period(TaxPeriod, "ES", "EUR", "2025-03")
    assert out.period == "2025-03" and out.year == 2025


def test_it_returns_the_subclass_it_was_handed_not_the_base():
    out = open_period(UsTaxPeriod, "US", "USD", "2025", settings=TaxSettings())
    assert isinstance(out, UsTaxPeriod)


def test_extra_fields_reach_the_subclass():
    cfg = TaxSettings()
    out = open_period(UsTaxPeriod, "US", "USD", "2025", settings=cfg)
    assert out.settings is cfg


def test_a_field_the_subclass_does_not_declare_is_an_error():
    # The base TaxPeriod has no `settings`; passing one is a programming
    # mistake in the country module, not something to swallow.
    with pytest.raises(TypeError):
        open_period(TaxPeriod, "ES", "EUR", "2025", settings=TaxSettings())


def test_it_opens_empty():
    out = open_period(TaxPeriod, "ES", "EUR", "2025")
    assert out.sales == [] and out.realized_gain == 0.0


# --- sales_in ---

def test_only_the_period_s_disposals_come_through():
    rows = [sale("2024-12-31"), sale("2025-06-01"), sale("2026-01-01")]
    assert [s.sell_date for s in sales_in("2025", rows)] == ["2025-06-01"]


def test_a_month_slice_narrows_to_that_month():
    rows = [sale("2025-03-01"), sale("2025-04-01")]
    assert [s.sell_date for s in sales_in("2025-03", rows)] == ["2025-03-01"]


def test_ledger_order_is_kept():
    rows = [sale("2025-06-01", "MSFT"), sale("2025-01-02", "AAPL")]
    assert [s.ticker for s in sales_in("2025", rows)] == ["MSFT", "AAPL"]


def test_a_tax_year_that_opens_in_april_spans_the_boundary():
    rows = [sale("2025-04-05"), sale("2025-04-06"), sale("2026-04-05")]
    got = [s.sell_date for s in sales_in("2025", rows, (4, 6))]
    assert got == ["2025-04-06", "2026-04-05"]


def test_nothing_in_the_period_yields_nothing():
    assert list(sales_in("2025", [sale("2024-06-01")])) == []


# --- total_of ---

def year(y, gain=0.0, loss=0.0, disallowed=0.0, recovered=0.0, sales=()):
    return TaxPeriod(
        jurisdiction="ES", currency="EUR", year=y,
        realized_gain=gain, realized_loss=loss,
        disallowed_loss=disallowed, recovered_loss=recovered,
        sales=list(sales),
    )


def test_the_total_carries_the_jurisdiction_and_the_years_it_summed():
    out = total_of([year(2024), year(2025)])
    assert (out.jurisdiction, out.currency) == ("ES", "EUR")
    assert out.years == (2024, 2025)


def test_the_components_add_up_and_so_does_the_deductible_loss():
    out = total_of([
        year(2024, gain=1_000.0, loss=400.0, disallowed=100.0),
        year(2025, gain=500.0, loss=200.0, recovered=50.0),
    ])
    assert out.realized_gain == 1_500.0
    assert out.realized_loss == 600.0
    assert out.disallowed_loss == 100.0
    assert out.recovered_loss == 50.0
    assert out.deductible_loss == 500.0


def test_every_year_s_disposals_are_there_in_the_order_handed_over():
    out = total_of([
        year(2024, sales=[sale("2024-06-01", "MSFT")]),
        year(2025, sales=[sale("2025-06-01", "AAPL")]),
    ])
    assert [s.ticker for s in out.sales] == ["MSFT", "AAPL"]


def test_the_kpis_are_each_year_s_own_figures_summed_by_key():
    # The point of the whole helper: the tiles add up what the engine already
    # decided per year. Summing the *bases* and re-running the brackets would
    # run two years of gains up one progressive scale.
    out = total_of([
        year(2024, gain=1_000.0),
        year(2025, gain=3_000.0),
    ])
    tiles = {k.key: k.value for k in out.kpis()}
    assert tiles["net_taxable"] == 4_000.0
    assert tiles["carryforward_loss"] == 0.0


def test_a_kpi_only_some_years_carry_still_lands_once_in_first_seen_order():
    a, b = year(2024), year(2025)
    a.kpis = lambda: [Kpi("net_taxable", 10.0, "h")]
    b.kpis = lambda: [Kpi("net_taxable", 5.0, "h"), Kpi("allowance", 3_000.0, "h")]
    out = total_of([a, b])
    assert [(k.key, k.value) for k in out.kpis()] == [
        ("net_taxable", 15.0), ("allowance", 3_000.0),
    ]


def test_notes_are_per_year_so_a_total_writes_none():
    assert total_of([year(2024), year(2025)]).notes() == []


def test_nothing_to_add_is_a_programming_error_not_an_empty_total():
    with pytest.raises(ValueError):
        total_of([])
