"""Trade Republic transaction export → ledger rows (stocks.portfolio.trade_republic)."""

from __future__ import annotations

from stocks.portfolio import autodetect, platforms, trade_republic

HEADER = (
    "datetime,date,account_type,category,type,asset_class,name,symbol,shares,"
    "price,amount,fee,tax,currency,original_amount,original_currency,fx_rate,"
    "description,transaction_id,counterparty_name,counterparty_iban,"
    "payment_reference,mcc_code"
)


def _row(category, rtype, *, asset="", name="", symbol="", shares="", price="",
         amount="", fee="", tax="", currency="EUR", day="2026-03-02", tid="t1",
         description=""):
    cells = [f"{day}T10:15:00.000Z", day, "DEFAULT", category, rtype, asset,
             name, symbol, shares, price, amount, fee, tax, currency, "", "",
             "", description, tid, "", "", "", ""]
    return ",".join(f'"{c}"' for c in cells)


def _csv(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


APPLE = dict(asset="STOCK", name="Apple Inc.", symbol="US0378331005")


def test_buys_and_sells_import_under_the_isin_with_the_fee():
    result = trade_republic.parse_csv(_csv(
        _row("TRADING", "BUY", **APPLE, shares="2", price="150.00",
             amount="-300.00", fee="-1.00", tid="a"),
        _row("TRADING", "SELL", **APPLE, shares="-1", price="170.00",
             amount="170.00", fee="-1.00", day="2026-04-01", tid="b"),
    ))

    assert result.skipped == []
    buy, sell = result.transactions
    assert (buy.date, buy.ticker, buy.action, buy.quantity, buy.price, buy.fee) == (
        "2026-03-02", "US0378331005", "buy", 2.0, 150.0, 1.0)
    assert (sell.action, sell.quantity, sell.price) == ("sell", 1.0, 170.0)
    assert buy.note.startswith("trade_republic ")
    assert platforms.detected_broker(result.transactions) == "trade_republic"


def test_a_savings_plan_execution_is_a_buy_and_price_falls_back_to_the_amount():
    result = trade_republic.parse_csv(_csv(_row(
        "TRADING", "BUY", asset="FUND", name="iShares Core MSCI World",
        symbol="IE00B4L5Y983", shares="0.5", amount="-50.00",
        description="Savings plan execution", tid="sp")))

    tx, = result.transactions
    assert (tx.action, tx.quantity, tx.price) == ("buy", 0.5, 100.0)


def test_crypto_imports_as_the_yahoo_pair():
    result = trade_republic.parse_csv(_csv(_row(
        "TRADING", "BUY", asset="CRYPTO", name="Bitcoin", symbol="BTC",
        shares="0.01", price="60000", amount="-600.00", fee="-1.00")))

    assert result.transactions[0].ticker == "BTC-EUR"


def test_a_dividend_books_gross_with_the_withholding_as_fee():
    result = trade_republic.parse_csv(_csv(_row(
        "CASH", "DIVIDEND", **APPLE, shares="2", amount="1.20", tax="-0.18")))

    tx, = result.transactions
    assert (tx.action, tx.ticker, tx.price, tx.fee) == (
        "dividend", "US0378331005", 1.2, 0.18)


def test_a_reversed_dividend_cancels_and_the_rebooking_imports():
    result = trade_republic.parse_csv(_csv(
        _row("CASH", "DIVIDEND", **APPLE, amount="1.20", tax="-0.18", tid="d1"),
        _row("CASH", "DIVIDEND", **APPLE, amount="-1.20", tax="0.18", tid="d2"),
        _row("CASH", "DIVIDEND", **APPLE, amount="1.25", tax="-0.19", tid="d3"),
    ))

    tx, = result.transactions
    assert tx.price == 1.25
    reasons = [s["reason"] for s in result.skipped]
    assert reasons == [trade_republic.REVERSED, trade_republic.REVERSED]


def test_bond_coupon_and_maturity_book_cash_interest_does_not():
    bond = dict(asset="BOND", name="Bund 2026", symbol="DE0001102333")
    result = trade_republic.parse_csv(_csv(
        _row("CASH", "INTEREST_PAYMENT", **bond, amount="25.00", tid="c"),
        _row("CASH", "INTEREST_PAYMENT", amount="3.10", tid="i"),
        _row("CORPORATE_ACTION", "REDEMPTION", **bond, shares="-1000", tid="r"),
        _row("CASH", "FINAL_MATURITY", **bond, shares="1000", amount="1000.00",
             tid="m"),
    ))

    coupon, sale = result.transactions
    assert (coupon.action, coupon.ticker, coupon.price) == (
        "dividend", "DE0001102333", 25.0)
    assert (sale.action, sale.quantity, sale.price) == ("sell", 1000.0, 1.0)
    assert [s["reason"] for s in result.skipped] == [
        trade_republic.INTEREST, trade_republic.REDEMPTION]


def test_cash_tax_and_unknown_rows_are_skipped_with_a_reason():
    result = trade_republic.parse_csv(_csv(
        _row("CASH", "CUSTOMER_INBOUND", amount="1000.00", tid="1"),
        _row("CASH", "CARD_TRANSACTION", amount="-12.50", tid="2"),
        _row("CASH", "EARNINGS", tax="-3.00", tid="3"),
        _row("CASH", "BENEFITS_SAVEBACK", amount="2.00", tid="4"),
        _row("CORPORATE_ACTION", "SPLIT", **APPLE, shares="8", tid="5"),
        _row("CASH", "SOMETHING_NEW", amount="1.00", tid="6"),
    ))

    assert result.transactions == []
    assert [s["reason"] for s in result.skipped] == [
        trade_republic.CASH, trade_republic.CASH, trade_republic.TAX,
        trade_republic.CASH, trade_republic.SPLIT, trade_republic.UNKNOWN]
    split = result.skipped[4]
    assert (split["ticker"], split["quantity"]) == ("US0378331005", 8.0)


def test_a_repeated_transaction_id_is_one_booking():
    row = _row("TRADING", "BUY", **APPLE, shares="1", price="150",
               amount="-150.00", tid="same")
    assert len(trade_republic.parse_csv(_csv(row, row)).transactions) == 1


def test_the_semicolon_variant_with_decimal_commas_reads_the_same():
    text = _csv(_row("TRADING", "BUY", **APPLE, shares="2", price="1.500,00",
                     amount="-3.000,00", fee="-1,00"))
    semi = text.replace('","', '";"').replace(HEADER, HEADER.replace(",", ";"))

    tx, = trade_republic.parse_csv(semi).transactions
    assert (tx.quantity, tx.price, tx.fee) == (2.0, 1500.0, 1.0)


def test_another_brokers_file_is_refused_whole():
    result = trade_republic.parse_csv(
        "Date,Ticker,Type,Quantity\n2026-01-01,AAPL,BUY,1\n")

    assert result.transactions == []
    assert result.skipped[0]["reason"].startswith(trade_republic.REFUSAL)


def test_autodetect_picks_trade_republic_without_the_model():
    text = _csv(
        _row("TRADING", "BUY", **APPLE, shares="1", price="150",
             amount="-150.00", tid="a"),
        _row("CASH", "CARD_TRANSACTION", amount="-9.99", tid="b"),
    )

    class Provider:
        classifier_model = default_model = "stub"
        calls: list = []

        def complete(self, *args):
            self.calls.append(args)
            return "{}"

    provider = Provider()
    found = autodetect.detect("export.csv", text.encode("utf-8-sig"), provider)

    assert found.platform == "trade_republic" and found.label == "Trade Republic"
    assert len(found.result.transactions) == 1
    assert provider.calls == []
