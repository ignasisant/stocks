"""Tests for the DEGIRO Transactions.csv parser (strict-shape import)."""

from __future__ import annotations

from stocks.portfolio import degiro

# English export: unnamed currency columns follow each money column.
EN_CSV = (
    "Date,Time,Product,ISIN,Exchange,Venue,Quantity,Price,,Local value,,"
    "Value,,Exchange rate,Transaction costs,,Total,,Order ID\n"
    "03-01-2024,14:30,APPLE INC. - COMMON ST,US0378331005,NDQ,XNAS,"
    "10,125.00,USD,-1250.00,USD,-1151.65,EUR,1.0854,-2.50,EUR,-1154.15,EUR,a1\n"
    "05-03-2024,10:00,APPLE INC. - COMMON ST,US0378331005,NDQ,XNAS,"
    "-4,170.00,USD,680.00,USD,630.21,EUR,1.0790,-2.50,EUR,627.71,EUR,a2\n"
)

# Spanish export: same positions, localised headers and comma decimals.
ES_CSV = (
    "Fecha,Hora,Producto,ISIN,Bolsa de,Centro de ejecución,Número,Precio,,"
    "Valor local,,Valor,,Tipo de cambio,Costes de transacción,,Total,,ID Orden\n"
    "03-01-2024,14:30,APPLE INC. - COMMON ST,US0378331005,NDQ,XNAS,"
    '10,"125,00",USD,"-1250,00",USD,"-1151,65",EUR,"1,0854","-2,50",EUR,'
    '"-1154,15",EUR,a1\n'
)


def test_english_export_buy_and_sell():
    result = degiro.parse_csv(EN_CSV)
    assert result.skipped == []
    buy, sell = result.transactions
    assert (buy.action, buy.ticker, buy.quantity, buy.price) == (
        "buy", "US0378331005", 10, 125.0,
    )
    assert buy.currency == "USD" and buy.date == "2024-01-03"
    # Costs are billed in EUR on a USD trade: converted at the row's own rate.
    assert buy.fee == round(2.50 * 1.0854, 4)
    assert "APPLE" in buy.note
    assert (sell.action, sell.quantity) == ("sell", 4)


def test_spanish_export_with_comma_decimals():
    result = degiro.parse_csv(ES_CSV)
    assert result.skipped == []
    (buy,) = result.transactions
    assert (buy.quantity, buy.price, buy.currency) == (10, 125.0, "USD")
    assert buy.date == "2024-01-03"


def test_fee_kept_when_charged_in_trade_currency():
    text = (
        "Date,Time,Product,ISIN,Exchange,Venue,Quantity,Price,,Local value,,"
        "Value,,Exchange rate,Transaction costs,,Total,,Order ID\n"
        "03-01-2024,14:30,AIRBUS SE,NL0000235190,EPA,XPAR,"
        "5,140.00,EUR,-700.00,EUR,-700.00,EUR,,-2.50,EUR,-702.50,EUR,b1\n"
    )
    (buy,) = degiro.parse_csv(text).transactions
    assert buy.fee == 2.50


def test_inconsistent_row_quarantined():
    text = (
        "Date,Time,Product,ISIN,Exchange,Venue,Quantity,Price,,Local value,,"
        "Value,,Exchange rate,Transaction costs,,Total,,Order ID\n"
        "03-01-2024,14:30,APPLE,US0378331005,NDQ,XNAS,"
        "10,125.00,USD,-500.00,USD,-460.00,EUR,1.0854,,,-462.50,EUR,c1\n"
    )
    result = degiro.parse_csv(text)
    assert result.transactions == []
    assert "inconsistent" in result.skipped[0]["reason"]


def test_refuses_foreign_shape():
    result = degiro.parse_csv(
        "date,ticker,action,quantity,price\n2024-01-02,AAPL,buy,10,180\n"
    )
    assert result.transactions == []
    assert "not a DEGIRO" in result.skipped[0]["reason"]

    # A Ticker column is an explicit tell that this is another broker's file.
    t212ish = (
        "Action,Time,ISIN,Ticker,Name,No. of shares,Price / share\n"
        "Market buy,2024-01-03,US0378331005,AAPL,Apple,10,125.00\n"
    )
    result = degiro.parse_csv(t212ish)
    assert result.transactions == []
    assert "Ticker column" in result.skipped[0]["reason"]


def test_number_locale_heuristics():
    assert degiro._num("1.234,56") == 1234.56
    assert degiro._num("1,234.56") == 1234.56
    assert degiro._num("-2,5") == -2.5
    assert degiro._num("0,123") == 0.123
    assert degiro._num("10") == 10.0
    assert degiro._num("1,234,567") == 1234567.0


def test_empty_input():
    assert degiro.parse_csv("").transactions == []


# The shape DEGIRO exports today: no unnamed currency column after the money
# columns — the currency is a suffix on the header instead ("Total EUR") — and
# the charge is split over two columns.
ES_CURRENT_CSV = (
    "Fecha,Hora,Producto,ISIN,Bolsa de referencia,Centro de ejecución,Número,"
    "Precio,,Valor local,,Valor EUR,Tipo de cambio,Comisión AutoFX,"
    "Costes de transacción y/o externos EUR,Total EUR,ID Orden\n"
    "10-08-2026,21:13,ADR ON PDD HOLDINGS INC.,US7223041028,NDQ,CDED,"
    '-15,"92,8550",USD,"1392,82",USD,"1206,86","1,1541","-3,02","-2,00",'
    '"1201,84",71c6a81b\n'
    "14-05-2026,16:36,TELEPERFORMANCE SE,FR0000051807,EPA,XPAR,"
    '-18,"66,0000",EUR,"1188,00",EUR,"1188,00",,"0,00","-4,90","1183,10",e6a4\n'
)


def test_current_export_splits_the_charge_and_converts_it():
    """Both cost columns count, and an EUR charge lands on a USD trade."""
    pdd, tlp = degiro.parse_csv(ES_CURRENT_CSV).transactions
    assert (pdd.action, pdd.quantity, pdd.currency) == ("sell", 15, "USD")
    assert pdd.fee == round((3.02 + 2.00) * 1.1541, 4)
    # An EUR trade needs no conversion: the charge is already in its currency.
    assert (tlp.currency, tlp.fee) == ("EUR", 4.90)


def test_total_column_wins_over_the_parts():
    """An unrecognised cost column still reaches the cost basis via Total."""
    text = (
        "Fecha,Hora,Producto,ISIN,Bolsa,Centro,Número,Precio,,Valor local,,"
        "Valor EUR,Tipo de cambio,Recargo raro,Total EUR,ID Orden\n"
        "14-05-2026,16:36,TELEPERFORMANCE SE,FR0000051807,EPA,XPAR,"
        '-18,"66,0000",EUR,"1188,00",EUR,"1188,00",,"-4,90","1183,10",e6a4\n'
    )
    (sell,) = degiro.parse_csv(text).transactions
    assert sell.fee == 4.90


def test_zero_value_bookkeeping_pair_is_not_a_skip():
    """Tradeable/NON TRADEABLE transfers net to nothing — dropped silently."""
    text = (
        "Fecha,Hora,Producto,ISIN,Bolsa,Centro,Número,Precio,,Valor local,,"
        "Valor EUR,Tipo de cambio,Comisión AutoFX,Costes EUR,Total EUR,ID\n"
        "06-08-2026,09:48,ASML HOLDING - NON TRADEABLE,NL0010273215,DEG,,"
        '-1,"0,0000",EUR,"0,00",EUR,"0,00",,"0,00",,"0,00",-1\n'
        "06-08-2026,09:48,ASML HOLDING N.V.,NL0010273215,EAM,,"
        '1,"0,0000",EUR,"0,00",EUR,"0,00",,"0,00",,"0,00",-1\n'
    )
    result = degiro.parse_csv(text)
    assert (result.transactions, result.skipped) == ([], [])


def test_wrapped_product_name_is_not_a_broken_row():
    """DEGIRO wraps a long product name onto a line with no date and no ISIN."""
    text = (
        "Fecha,Hora,Producto,ISIN,Bolsa,Centro,Número,Precio,,Valor local,,"
        "Valor EUR,Tipo de cambio,Comisión AutoFX,Costes EUR,Total EUR,ID\n"
        '20-08-2024,21:40,"CHARTER COMMUNICATIONS, INC.",US16119P1084,NDQ,SOHO,'
        '-2,"349,2500",USD,"698,50",USD,"627,81","1,1126","-1,57","-2,00",'
        '"624,24",038d\n'
        ",,CLASS A,,,,,,,,,,,,,,\n"
    )
    result = degiro.parse_csv(text)
    assert result.skipped == []
    assert len(result.transactions) == 1
