"""Return of capital: cash back out of what the shares cost.

A share-premium repayment (Merlin, Inmobiliaria Colonial…) or a US nondividend
distribution is not income: it gives back part of the purchase price, so the
basis of the shares held that day falls by it — and the gain on their eventual
sale grows by exactly as much. Every matching rule takes it the same way.
"""

import pytest

from stocks.portfolio import revolut
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import build


def flat(amount: float, currency: str, day: str) -> float:
    return amount


def replay(txs, matching="fifo"):
    return build(txs, to_base=flat, base="EUR", matching=matching)


def buy(day, qty, price, ticker="MRL.MC"):
    return Transaction(day, ticker, "buy", qty, price, "EUR")


def sell(day, qty, price, ticker="MRL.MC"):
    return Transaction(day, ticker, "sell", qty, price, "EUR")


def capital(day, total, ticker="MRL.MC"):
    return Transaction(day, ticker, "capital", price=total, currency="EUR")


TWO_LOTS = [
    buy("2025-01-02", 100, 10),
    buy("2025-06-02", 100, 20),
    capital("2026-05-25", 100),
]


@pytest.mark.parametrize("matching", ["fifo", "lifo", "average", "s104"])
def test_the_basis_falls_by_the_whole_payment_under_every_rule(matching):
    positions, _ = replay(TWO_LOTS, matching)
    (pos,) = positions
    assert pos.quantity == 200
    assert pos.cost == pytest.approx(2900)
    assert pos.cost_native == pytest.approx(2900)


def test_each_lot_gives_up_its_shares_part_not_its_costs_part():
    """0.50 a share: the cheap lot and the dear one lose the same 50."""
    _, sales = replay([*TWO_LOTS, sell("2026-06-01", 100, 15)], "fifo")
    (sale,) = sales
    assert sale.cost == pytest.approx(950)
    assert sale.gain == pytest.approx(550)

    _, sales = replay([*TWO_LOTS, sell("2026-06-01", 100, 15)], "lifo")
    (sale,) = sales
    assert sale.cost == pytest.approx(1950)


def test_only_the_shares_held_that_day_are_repaid():
    positions, _ = replay(
        [buy("2025-01-02", 100, 10), capital("2025-03-03", 100), buy("2025-06-02", 100, 20)]
    )
    (pos,) = positions
    assert pos.cost == pytest.approx(900 + 2000)


def test_a_same_day_uk_acquisition_is_not_in_the_pool_it_repays():
    positions, _ = replay(
        [buy("2025-01-02", 100, 10), buy("2025-03-03", 100, 20), capital("2025-03-03", 100)],
        "s104",
    )
    (pos,) = positions
    assert pos.cost == pytest.approx(900 + 2000)


def test_a_basis_never_goes_below_zero():
    positions, _ = replay([buy("2025-01-02", 10, 1), capital("2025-03-03", 50)])
    (pos,) = positions
    assert pos.cost == 0
    assert pos.quantity == 10


def test_a_repayment_on_nothing_held_changes_nothing():
    positions, sales = replay([buy("2025-01-02", 10, 1), capital("2025-03-03", 5, "COL.MC")])
    assert [p.ticker for p in positions] == ["MRL.MC"]
    assert positions[0].cost == pytest.approx(10)
    assert sales == []


def test_the_native_basis_falls_in_step_when_the_payment_is_in_another_currency():
    """A USD lot repaid in EUR: the reporting cut is converted, the native one
    is the same fraction of the native basis."""

    def eur(amount, currency, day):
        return amount * 0.5 if currency == "USD" else amount

    txs = [
        Transaction("2025-01-02", "O", "buy", 10, 40, "USD"),
        Transaction("2025-03-03", "O", "capital", price=50, currency="EUR"),
    ]
    (pos,), _ = build(txs, to_base=eur, base="EUR")
    assert pos.cost == pytest.approx(200 - 50)
    assert pos.cost_native == pytest.approx(400 * 0.75)


def test_revolut_imports_a_return_of_capital_as_a_ledger_row():
    res = revolut.parse_csv(
        "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
        "2026-05-25T00:00:00.000Z,MRL,RETURN OF CAPITAL,,,€129.40,EUR,\n"
    )
    assert res.skipped == []
    (tx,) = res.transactions
    assert (tx.date, tx.ticker, tx.action) == ("2026-05-25", "MRL", "capital")
    assert tx.price == pytest.approx(129.40)
    assert tx.quantity == 0 and tx.currency == "EUR"
