"""Revolut crypto-statement parsing (stocks.portfolio.revolut_crypto)."""

import pytest

from stocks.portfolio.revolut_crypto import parse_csv

HEADER = "Symbol,Type,Quantity,Price,Value,Fees,Date\n"


def test_buy_normalizes_to_pair_in_statement_currency():
    csv = HEADER + (
        'BTC,Buy,"0.05000000","€60,000.00","€3,000.00",€44.85,2025-03-04T09:12:00.000Z\n'
    )
    result = parse_csv(csv)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.ticker == "BTC-EUR"  # coin + sniffed fiat -> Yahoo pair
    assert tx.action == "buy"
    # The fee came out of the 3,000 € first: 2,955.15 € of coins arrived.
    assert tx.quantity == round(0.05 * (3000 - 44.85) / 3000, 8)
    assert tx.price == 60_000.0
    assert tx.currency == "EUR"
    assert tx.fee == 44.85
    assert tx.date == "2025-03-04"
    assert tx.note == "revolut crypto BTC net"
    # What was paid is the cost: net coins at the price, plus the fee.
    assert tx.quantity * tx.price + tx.fee == pytest.approx(3000.0)


def test_selling_everything_a_buy_brought_leaves_nothing_behind():
    """The CAT-EUR case: 500 € bought 44,471,331 coins by the Quantity
    column, but only the 495.05 € left after the fee were converted — and
    "sell all" sold 44,031,065. Booked gross, 440,266 coins stayed on the
    book as a position nobody held."""
    csv = ES_HEADER + (
        "CAT,Compra,44471331.2889,0.00€,500.00€,4.95€,10 may 2025 10:00:00\n"
        "CAT,Venta,44031065.1091,0.00€,49.87€,0.00€,18 jun 2026 10:00:00\n"
    )
    buy, sell = parse_csv(csv).transactions
    assert buy.quantity == sell.quantity
    assert buy.quantity * buy.price + buy.fee == pytest.approx(500.0)
    assert sell.note == "revolut crypto CAT"  # a sale's quantity is what left


def test_a_rounded_price_column_gives_way_to_the_value():
    # "0.05 €" printed for a coin bought at 500 € / 9,302.55 = 0.0537.
    csv = ES_HEADER + (
        'CHILLGUY,Compra,"9,302.54766102",0.05€,500.00€,4.94€,8 may 2025 22:31:12\n'
    )
    (tx,) = parse_csv(csv).transactions
    assert tx.price == pytest.approx(500.0 / 9302.54766102)
    assert tx.quantity * tx.price + tx.fee == pytest.approx(500.0)


def test_a_fee_cut_to_the_cent_leaves_nothing_after_selling_everything():
    # The owner's export: 4.94 € printed for 0.99 % of 500 €, so the coins the
    # fee took come out a cent's worth short and "sell all" sold 0.19 more
    # CHILLGUY than the fee column says arrived.
    csv = ES_HEADER + (
        'CHILLGUY,Compra,"9,302.54766102",0.05€,500.00€,4.94€,8 may 2025 22:31:12\n'
        'CHILLGUY,Venta,"9,210.45243918",0.07€,620.71€,6.15€,10 may 2025 02:55:17\n'
        'CHILLGUY,Compra,"5,332.18434205",0.09€,500.00€,4.95€,12 may 2025 11:49:15\n'
        'CHILLGUY,Venta,"5,279.39571706",0.01€,40.13€,0.00€,23 mar 2026 14:38:46\n'
    )
    buy, sell, buy2, sell2 = parse_csv(csv).transactions
    assert buy.quantity - sell.quantity == 0
    assert buy2.quantity - sell2.quantity == 0


def test_a_partial_sale_keeps_the_rest():
    csv = ES_HEADER + (
        "METIS,Compra,25.60141493,19.53€,500.00€,4.95€,10 may 2025 02:18:57\n"
        "METIS,Venta,25,20.00€,500.00€,4.95€,11 may 2025 02:18:57\n"
    )
    buy, sell = parse_csv(csv).transactions
    assert buy.quantity - sell.quantity == pytest.approx(25.60141493 * 0.9901 - 25)


def test_usd_statement_and_derived_price():
    # Blank per-coin price: derived from value / quantity.
    csv = HEADER + 'ETH,Sell,"2.00000000",,"$8,000.00",$12.00,2025-06-01T10:00:00.000Z\n'
    result = parse_csv(csv)
    tx = result.transactions[0]
    assert tx.ticker == "ETH-USD"
    assert tx.action == "sell"
    assert tx.price == 4_000.0
    assert tx.currency == "USD"


def test_rewards_transfers_and_exchanges_are_skipped_with_reasons():
    csv = HEADER + (
        "DOT,Staking Reward,0.5,€4.00,€2.00,€0.00,2025-01-10T00:00:00.000Z\n"
        "BTC,Send,0.01,€60000.00,€600.00,€0.00,2025-02-01T00:00:00.000Z\n"
        "ETH,Exchange,1.0,€2000.00,€2000.00,€0.00,2025-02-02T00:00:00.000Z\n"
    )
    result = parse_csv(csv)
    assert not result.transactions
    reasons = {s["ticker"]: s["reason"] for s in result.skipped}
    assert "reward" in reasons["DOT"]
    assert "transfer" in reasons["BTC"]
    assert "exchange" in reasons["ETH"]


def test_inconsistent_row_is_quarantined():
    # 0.05 × 60000 = 3000, but value says 5000 — corrupt, must not import.
    csv = HEADER + "BTC,Buy,0.05,€60000.00,€5000.00,€0.00,2025-03-04T09:12:00.000Z\n"
    result = parse_csv(csv)
    assert not result.transactions
    assert "inconsistent" in result.skipped[0]["reason"]


def test_missing_quantity_or_price_is_skipped():
    csv = HEADER + (
        "BTC,Buy,0,€60000.00,€0.00,€0.00,2025-03-04T09:12:00.000Z\n"
        "ETH,Buy,1.0,,,€0.00,2025-03-05T09:12:00.000Z\n"
    )
    result = parse_csv(csv)
    assert not result.transactions
    assert len(result.skipped) == 2


def test_prose_date_and_explicit_currency_column():
    csv = (
        "Symbol,Type,Quantity,Price,Value,Fees,Currency,Date\n"
        'BTC,Buy,0.10,55000.00,5500.00,10.00,GBP,"Jan 5, 2025, 2:31:41 PM"\n'
    )
    result = parse_csv(csv)
    tx = result.transactions[0]
    assert tx.ticker == "BTC-GBP"
    assert tx.currency == "GBP"
    assert tx.date == "2025-01-05"


def test_unknown_fiat_falls_back_to_usd_pair_but_keeps_currency():
    csv = (
        "Symbol,Type,Quantity,Price,Value,Fees,Currency,Date\n"
        "BTC,Buy,0.10,55000.00,5500.00,0.00,CHF,2025-01-05T00:00:00.000Z\n"
    )
    tx = parse_csv(csv).transactions[0]
    assert tx.ticker == "BTC-USD"  # no reliable Yahoo CHF pair
    assert tx.currency == "CHF"  # cost basis stays in the real currency


# --------------------------------------------------- an export in Spanish
#
# Revolut's crypto export is localised: an account set to Spanish downloads a
# file whose type column says "Compra" and whose dates say "3 abr 2025". Both
# used to be unreadable — the types matched `startswith("BUY")` and the dates
# went through pandas, which knows "apr" — so a 500-row statement imported as
# zero transactions and the app said no parser recognised the file.

ES_HEADER = "Symbol,Type,Quantity,Price,Value,Fees,Date\n"


def test_spanish_types_and_month_names_import():
    csv = ES_HEADER + (
        'SOL,Compra,5.144921,194.37€,"1,000.00€",9.90€,3 feb 2025 09:21:06\n'
        'SOL,Compra,18.989931,105.32€,"2,000.00€",19.79€,3 abr 2025 19:55:12\n'
        'SOL,Venta,15,128.65€,"1,929.70€",19.10€,23 abr 2025 04:22:04\n'
        'BTC,Compra,0.00955534,"73,257.41€",700.00€,6.93€,21 nov 2025 12:11:14\n'
        'ETH,Compra,1.03718945,"1,928.29€","2,000.00€",19.80€,2 feb 2026 09:55:05\n'
    )
    result = parse_csv(csv)
    assert [(tx.date, tx.ticker, tx.action) for tx in result.transactions] == [
        ("2025-02-03", "SOL-EUR", "buy"),
        ("2025-04-03", "SOL-EUR", "buy"),
        ("2025-04-23", "SOL-EUR", "sell"),
        ("2025-11-21", "BTC-EUR", "buy"),
        ("2026-02-02", "ETH-EUR", "buy"),
    ]
    assert not result.skipped


def test_a_buy_books_the_coins_its_staking_move_then_moved():
    # The same export, one line apart: 1,000 € bought 5.144921 SOL by the
    # Quantity column, and the coins staked a minute later were 5.093986 —
    # the 9.90 € fee's worth fewer. The ledger keeps the second figure.
    csv = ES_HEADER + (
        'SOL,Compra,5.144921,194.37€,"1,000.00€",9.90€,3 feb 2025 09:21:06\n'
    )
    (tx,) = parse_csv(csv).transactions
    assert tx.quantity == 5.093986


def test_staking_moves_and_rewards_are_told_apart():
    # "Staking" moves coins the account already owns; "Recompensa de staking"
    # is new coins, taxable income. Both stay out of the ledger, but a move
    # told as a reward sends the reader off to add a buy that never happened.
    csv = ES_HEADER + (
        'SOL,Staking,5.093986,194.80€,992.30€,0.00€,3 feb 2025 09:22:03\n'
        "SOL,Recompensa de staking,0.001771,,,,6 feb 2025 13:38:21\n"
    )
    result = parse_csv(csv)
    assert not result.transactions
    moved, reward = result.skipped
    assert "moved in or out of staking" in moved["reason"]
    assert "reward" in reward["reason"]
