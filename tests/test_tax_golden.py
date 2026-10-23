"""Golden cases: a small hand-built ledger through the whole tax pipeline.

The per-country files test each rule from a ready-made `RealizedSale`. These
run what the app runs — `Transaction`s → `positions.build` under the
jurisdiction's own matching rule and currency → `tax.buy_dates` →
`Jurisdiction.fiscal_year` — and assert figures worked out by hand on paper,
to the cent. If one moves, either the engine changed a rule or it broke one.
Pure, no network: the FX "converter" is a dict.
"""

import pytest

from stocks.portfolio import tax
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import build
from stocks.portfolio.tax import Payment, TaxSettings


def buy(day, ticker, qty, price, fee=0.0, cur="EUR"):
    return Transaction(day, ticker, "buy", qty, price, cur, fee)


def sell(day, ticker, qty, price, fee=0.0, cur="EUR"):
    return Transaction(day, ticker, "sell", qty, price, cur, fee)


def flat(amount, currency, day):
    return amount


def report(code, txs, year, to_base=flat, settings=None, dividends=()):
    """(period, sales) exactly as the Tax tab computes them."""
    jur = tax.get(code)
    _, sales = build(txs, to_base, base=jur.currency, matching=jur.matching)
    period = jur.fiscal_year(
        sales, year, tax.buy_dates(txs), settings or TaxSettings(), dividends
    )
    return period, sales


# --- Spain: FIFO, the two-month rule, the savings base ---------------------

ES_LOSS = [
    buy("2024-01-10", "MSFT", 100, 10, fee=5),  # cost 1005
    sell("2025-03-03", "MSFT", 100, 7, fee=3),  # proceeds 697 -> loss 308
    buy("2025-04-15", "MSFT", 50, 8),  # inside the two months: half of it
    buy("2024-02-01", "AAA", 10, 100),
    sell("2025-06-01", "AAA", 10, 130),  # +300
]


def test_es_fifo_loss_is_half_deferred_by_a_half_size_rebuy():
    ty, sales = report("ES", ES_LOSS, 2025)
    msft = next(s for s in sales if s.ticker == "MSFT")
    assert msft.cost == pytest.approx(1005)
    assert msft.proceeds == pytest.approx(697)
    assert ty.realized_gain == pytest.approx(300)
    assert ty.realized_loss == pytest.approx(308)
    assert ty.disallowed_loss == pytest.approx(154)
    assert ty.deductible_loss == pytest.approx(154)
    assert ty.net_taxable == pytest.approx(146)
    assert ty.estimated_tax == pytest.approx(27.74)  # 146 * 19 %


def test_es_deferred_loss_comes_back_when_the_replacement_is_sold():
    txs = [*ES_LOSS, sell("2026-05-01", "MSFT", 50, 9)]  # cost 400, +50
    ty, _ = report("ES", txs, 2026)
    assert ty.realized_gain == pytest.approx(50)
    assert ty.recovered_loss == pytest.approx(154)
    assert ty.net_taxable == pytest.approx(-104)
    assert ty.estimated_tax == pytest.approx(0)


def test_es_a_rebuy_after_two_months_defers_nothing():
    txs = [
        buy("2024-01-10", "MSFT", 100, 10),
        sell("2025-03-03", "MSFT", 100, 7),
        buy("2025-05-04", "MSFT", 100, 8),  # past 2025-05-03
    ]
    ty, _ = report("ES", txs, 2025)
    assert ty.disallowed_loss == pytest.approx(0)
    assert ty.net_taxable == pytest.approx(-300)


def test_es_dividends_join_the_gain_and_climb_the_savings_brackets():
    txs = [buy("2024-01-10", "AAA", 50, 100), sell("2025-06-01", "AAA", 50, 200)]
    ty, _ = report("ES", txs, 2025, dividends=[Payment("2025-05-01", 2000.0)])
    # 5,000 gain + 2,000 dividends = 7,000: 6,000 at 19 % + 1,000 at 21 %.
    assert ty.estimated_tax == pytest.approx(1350.00)


# --- United Kingdom: S104, same day, bed and breakfast ---------------------

def test_uk_same_day_thirty_day_and_pool_in_one_disposal():
    txs = [
        buy("2024-01-10", "LLOY", 10_000, 1, cur="GBP"),
        buy("2024-06-10", "LLOY", 10_000, 3, cur="GBP"),  # pool: 20,000 @ £2
        sell("2025-01-10", "LLOY", 15_000, 5, cur="GBP"),  # £75,000
        buy("2025-01-10", "LLOY", 2_000, 4.5, cur="GBP"),  # same day, £9,000
        buy("2025-01-25", "LLOY", 3_000, 6, cur="GBP"),  # 30-day, £18,000
    ]
    ty, sales = report("UK", txs, 2024, settings=TaxSettings())
    by = {s.matched: s for s in sales}
    assert by["same_day"].gain == pytest.approx(1_000)  # 2,000 * (5 - 4.5)
    assert by["thirty_day"].gain == pytest.approx(-3_000)  # 3,000 * (5 - 6)
    assert by["pool"].cost == pytest.approx(20_000)  # 10,000 from the £2 pool
    assert by["pool"].gain == pytest.approx(30_000)
    assert ty.realized_gain == pytest.approx(31_000)
    assert ty.realized_loss == pytest.approx(3_000)
    # 28,000 net - 3,000 allowance = 25,000, all inside the basic-rate band.
    assert ty.estimated_tax == pytest.approx(4_500)


# --- United States: FIFO, short vs long term -------------------------------

def test_us_fifo_sale_splits_into_long_and_short_with_the_fee_pro_rata():
    txs = [
        buy("2023-01-10", "NVDA", 100, 50, cur="USD"),
        buy("2024-06-01", "NVDA", 100, 80, cur="USD"),
        sell("2025-03-10", "NVDA", 150, 100, fee=10, cur="USD"),
    ]
    ty, sales = report("US", txs, 2025)
    old, new = sorted(sales, key=lambda s: s.buy_date)
    assert old.gain == pytest.approx(4_993.33, abs=0.005)  # 10,000 - 6.67 - 5,000
    assert new.gain == pytest.approx(996.67, abs=0.005)  # 5,000 - 3.33 - 4,000
    assert ty.long_gain == pytest.approx(4_993.33, abs=0.005)
    assert ty.short_gain == pytest.approx(996.67, abs=0.005)
    # Long-term sits in the 0 % band; the short-term 996.67 in the 10 % one.
    assert ty.estimated_tax == pytest.approx(99.67, abs=0.005)


# --- Average cost: France (PFU 30 %) and Canada ----------------------------

def test_fr_average_cost_persists_across_two_sales():
    txs = [
        buy("2024-01-10", "AIR", 100, 10),
        buy("2024-06-10", "AIR", 100, 20, fee=10),  # avg (1,000 + 2,010) / 200 = 15.05
        sell("2025-02-01", "AIR", 50, 30, fee=5),  # 1,495 - 752.50 = +742.50
        sell("2025-09-01", "AIR", 100, 12),  # 1,200 - 1,505 = -305
    ]
    ty, sales = report("FR", txs, 2025)
    assert [round(s.gain, 2) for s in sales] == [742.50, -305.00]
    assert ty.net_taxable == pytest.approx(437.50)
    assert ty.estimated_tax == pytest.approx(131.25)  # 30 %


# --- LIFO: Italy ------------------------------------------------------------

def test_it_lifo_sells_the_newest_lot_and_taxes_the_saldo_at_26_percent():
    txs = [
        buy("2024-01-10", "ENI", 100, 10),
        buy("2024-06-10", "ENI", 100, 20),
        sell("2025-02-01", "ENI", 100, 25),  # newest first: +500
        sell("2025-09-01", "ENI", 50, 8),  # the 10 lot: -100
    ]
    ty, sales = report("IT", txs, 2025)
    assert [round(s.gain, 2) for s in sales] == [500.00, -100.00]
    assert ty.net_taxable == pytest.approx(400)
    assert ty.estimated_tax == pytest.approx(104.00)


# --- Other FIFO countries ---------------------------------------------------

def test_pt_fifo_gain_at_28_percent():
    txs = [buy("2024-01-10", "EDP", 100, 10), sell("2025-03-01", "EDP", 100, 15)]
    ty, _ = report("PT", txs, 2025)
    assert ty.estimated_tax == pytest.approx(140.00)


def test_ie_fifo_gain_after_the_exemption_at_33_percent():
    txs = [buy("2024-01-10", "CRH", 100, 10), sell("2025-03-01", "CRH", 100, 30)]
    ty, _ = report("IE", txs, 2025)  # 2,000 - 1,270 = 730 * 33 %
    assert ty.estimated_tax == pytest.approx(240.90)


# --- Base-currency replay with an FX move ----------------------------------

RATES = {"2024-01-10": 0.90, "2025-03-10": 0.95}  # EUR per USD on each date


def eur_per_usd(amount, currency, day):
    return amount if currency == "EUR" else amount * RATES[day]


def test_es_a_flat_dollar_trade_is_a_euro_gain_through_the_trade_date_rate():
    txs = [
        buy("2024-01-10", "AAPL", 100, 100, fee=10, cur="USD"),
        sell("2025-03-10", "AAPL", 100, 100, fee=10, cur="USD"),
    ]
    ty, sales = report("ES", txs, 2025, to_base=eur_per_usd)
    (s,) = sales
    assert s.cost == pytest.approx(9_009.00)  # (10,000 + 10) * 0.90
    assert s.proceeds == pytest.approx(9_490.50)  # (10,000 - 10) * 0.95
    assert ty.net_taxable == pytest.approx(481.50)
    assert ty.estimated_tax == pytest.approx(91.485)
