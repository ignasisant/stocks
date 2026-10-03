"""Return of capital: a payment that lowers the cost of the shares it was paid
on instead of counting as income — pure, no network.

Spain's devolución de prima de emisión, a US nondividend distribution, a
Canadian ACB reduction. Each test's point is what booking it as a dividend (or
not at all) would have got wrong.
"""

import pytest

from stocks.api.routes.portfolio import _cash_in
from stocks.portfolio import dividends, ibkr, lexicon, revolut, trading212
from stocks.portfolio.custody import by_position
from stocks.portfolio.ledger import RETURN_OF_CAPITAL, Transaction
from stocks.portfolio.positions import MATCH_CAPITAL_RETURN, build
from stocks.portfolio.tax.es import fiscal_period


def flat(amount: float, currency: str, day: str) -> float:
    """No FX: the ledger is already in the reporting currency."""
    return amount


def half_usd(amount: float, currency: str, day: str) -> float:
    return amount * (0.5 if currency == "USD" else 1.0)


def buy(day, qty, price, fee=0.0, ticker="MRL.MC", ccy="EUR", note=""):
    return Transaction(day, ticker, "buy", qty, price, ccy, fee, note)


def sell(day, qty, price, ticker="MRL.MC", ccy="EUR", note=""):
    return Transaction(day, ticker, "sell", qty, price, ccy, 0.0, note)


def roc(day, amount, ticker="MRL.MC", ccy="EUR", fee=0.0, note=""):
    return Transaction(day, ticker, RETURN_OF_CAPITAL, 0, amount, ccy, fee, note)


def replay(txs, matching="fifo", to_base=flat):
    return build(txs, to_base=to_base, base="EUR", matching=matching)


# --- the basis ---

def test_it_lowers_the_cost_the_same_amount_on_every_share():
    positions, sales = replay([
        buy("2024-01-10", 100, 10.0),
        buy("2024-06-10", 100, 20.0),
        roc("2025-05-25", 200.0),
    ])
    assert sales == []  # no income, no disposal
    (pos,) = positions
    assert pos.quantity == 200
    assert pos.cost == pytest.approx(3000 - 200)
    assert pos.cost_native == pytest.approx(3000 - 200)


def test_a_later_sale_realizes_the_lower_basis():
    _, sales = replay([
        buy("2024-01-10", 100, 10.0),
        buy("2024-06-10", 100, 20.0),
        roc("2025-05-25", 200.0),
        sell("2025-09-01", 100, 15.0),
    ])
    (s,) = sales
    # FIFO takes the first lot, which gave up 1 EUR a share.
    assert s.cost == pytest.approx(900)
    assert s.gain == pytest.approx(600)


def test_shares_bought_or_sold_on_the_pay_date_do_not_move_it():
    # The payment was made on the shares held going into the day, wherever
    # the ledger happens to put it among that day's rows.
    positions, _ = replay([
        buy("2024-01-10", 100, 10.0),
        Transaction("2025-05-25", "MRL.MC", "buy", 100, 10.0, "EUR", id=1),
        Transaction("2025-05-25", "MRL.MC", RETURN_OF_CAPITAL, 0, 100.0, "EUR", id=2),
    ])
    (pos,) = positions
    assert pos.cost == pytest.approx(2000 - 100)
    # All of it came off the old lot: selling it now realizes 100 more gain.
    _, sales = replay([
        buy("2024-01-10", 100, 10.0),
        Transaction("2025-05-25", "MRL.MC", "buy", 100, 10.0, "EUR", id=1),
        Transaction("2025-05-25", "MRL.MC", RETURN_OF_CAPITAL, 0, 100.0, "EUR", id=2),
        sell("2025-06-01", 100, 10.0),
    ])
    assert sales[0].cost == pytest.approx(900)


def test_what_it_pays_past_the_basis_is_a_gain_the_day_it_lands():
    positions, sales = replay([
        buy("2024-01-10", 10, 1.0),
        roc("2025-05-25", 15.0),
    ])
    (pos,) = positions
    assert pos.quantity == 10 and pos.cost == 0.0  # never below zero
    (excess,) = sales
    assert excess.matched == MATCH_CAPITAL_RETURN
    assert (excess.quantity, excess.cost, excess.proceeds) == (0.0, 0.0, 5.0)
    assert excess.gain == pytest.approx(5.0)
    # Held since the lot's purchase: a US filer's long-term clock.
    assert (excess.buy_date, excess.sell_date) == ("2024-01-10", "2025-05-25")


def test_a_payment_on_no_shares_is_all_excess():
    _, sales = replay([roc("2025-05-25", 50.0)])
    (excess,) = sales
    assert excess.proceeds == 50.0 and excess.buy_date == "2025-05-25"


def test_a_foreign_payment_cuts_the_native_cost_exactly():
    positions, _ = replay([
        buy("2024-01-10", 10, 100.0, ticker="O", ccy="USD"),  # 1000 USD = 500 EUR
        roc("2025-05-25", 100.0, ticker="O", ccy="USD"),  # 100 USD = 50 EUR
    ], to_base=half_usd)
    (pos,) = positions
    assert pos.cost == pytest.approx(450)
    assert pos.cost_native == pytest.approx(900)


@pytest.mark.parametrize("matching", ["average", "s104", "lifo"])
def test_every_matching_rule_lowers_the_same_total(matching):
    positions, sales = replay([
        buy("2024-01-10", 100, 1.0),
        buy("2024-06-10", 100, 3.0),
        roc("2025-05-25", 100.0),
    ], matching=matching)
    assert sales == []
    assert positions[0].cost == pytest.approx(400 - 100)


def test_the_average_sells_from_the_lowered_holding():
    _, sales = replay([
        buy("2024-01-10", 100, 1.0),
        buy("2024-06-10", 100, 3.0),
        roc("2025-05-25", 100.0),
        sell("2025-09-01", 100, 5.0),
    ], matching="average")
    assert sales[0].cost == pytest.approx(150)


@pytest.mark.parametrize("matching", ["average", "s104"])
def test_a_pooled_holding_books_its_excess_too(matching):
    _, sales = replay([
        buy("2024-01-10", 10, 1.0),
        roc("2025-05-25", 25.0),
    ], matching=matching)
    (excess,) = sales
    assert excess.matched == MATCH_CAPITAL_RETURN
    assert excess.proceeds == pytest.approx(15.0)
    assert excess.buy_date == "2024-01-10"


def test_custody_lowers_every_brokers_slice():
    row = by_position([
        buy("2024-01-01", 10, 10.0, note="revolut"),
        buy("2024-02-01", 30, 10.0, note="clicktrade"),
        roc("2025-05-25", 40.0, note="revolut"),
    ], to_base=flat)["MRL.MC"]
    assert row["revolut"].cost == pytest.approx(90)
    assert row["clicktrade"].cost == pytest.approx(270)


# --- what it is not ---

def test_it_is_not_dividend_income():
    txs = [buy("2024-01-10", 100, 10.0), roc("2025-05-25", 129.40)]
    assert dividends.by_year(txs, to_base=flat) == {}


def test_the_yahoo_reconciliation_counts_it_as_paid():
    # Yahoo's dividend history lists the payment, so leaving it out of the
    # comparison would flag a payment that did import as missing.
    txs = [buy("2024-01-10", 100, 10.0), roc("2025-05-25", 129.40)]
    years = dividends.by_year(txs, to_base=flat, capital=True)
    assert years[2025].gross == pytest.approx(129.40)


def test_the_recent_list_does_not_show_it_as_unbooked():
    owed = dividends.EstimatedPayment("MRL.MC", "2025-05-20", 1.294, 100, "EUR")
    txs = [buy("2024-01-10", 100, 10.0), roc("2025-05-25", 129.40)]
    assert dividends.unbooked([owed], txs) == []


def test_spain_taxes_the_excess_in_the_savings_base():
    _, realized = replay([buy("2024-01-10", 10, 1.0), roc("2025-05-25", 15.0)])
    ty = fiscal_period(realized, "2025", {"MRL.MC": ["2024-01-10"]})
    assert ty.realized_gain == pytest.approx(5.0)
    assert ty.net_taxable == pytest.approx(5.0)


def test_the_transactions_list_shows_its_amount():
    assert _cash_in(roc("2025-05-25", 129.40), "EUR") == pytest.approx(129.40)


# --- importers ---

def test_revolut_books_it():
    res = revolut.parse_csv(
        "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
        "2026-05-25T00:00:00.000Z,MRL.MC,RETURN OF CAPITAL,,,€129.40,EUR,\n"
    )
    (tx,) = res.transactions
    assert (tx.action, tx.price, tx.currency) == (RETURN_OF_CAPITAL, 129.40, "EUR")
    assert res.skipped == []


def test_trading212_books_it():
    res = trading212.parse_csv(
        "Action,Time,ISIN,Ticker,Name,No. of shares,Price / share,"
        "Currency (Price / share),Exchange rate,Total,Currency (Total),"
        "Withholding tax,Currency (Withholding tax),Notes,ID\n"
        "Dividend (Return of capital non us),2024-02-16 12:00:00,"
        "CA0000000000,ENB,Enbridge,10.0000000,0.50,CAD,,3.40,EUR,,,,R1\n"
    )
    (tx,) = res.transactions
    assert (tx.action, tx.price, tx.currency) == (RETURN_OF_CAPITAL, 5.0, "CAD")


def test_ibkr_books_it_from_the_description():
    res = ibkr.parse_csv(
        "Statement,Header,Field Name,Field Value\n"
        "Statement,Data,BrokerName,Interactive Brokers\n"
        "Dividends,Header,Currency,Date,Description,Amount\n"
        "Dividends,Data,USD,2024-02-16,O(US7561091049) Cash Dividend USD 0.25"
        " per Share (Return of Capital),2.50\n"
        "Dividends,Data,Total,,,2.50\n"
    )
    (tx,) = res.transactions
    assert (tx.action, tx.ticker, tx.price) == (RETURN_OF_CAPITAL, "O", 2.50)


@pytest.mark.parametrize("cell", [
    "Devolución de prima de emisión",
    "Dividend (Return of capital)",
    "Kapitalrückzahlung",
])
def test_the_lexicon_reads_it_before_dividend(cell):
    assert lexicon.action_of(cell) == RETURN_OF_CAPITAL
