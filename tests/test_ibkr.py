"""Tests for the IBKR activity-statement CSV parser (strict-shape import)."""

from __future__ import annotations

from stocks.portfolio import ibkr

IBKR_CSV = (
    "Statement,Header,Field Name,Field Value\n"
    "Statement,Data,BrokerName,Interactive Brokers\n"
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
    "Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,"
    "Realized P/L,MTM P/L,Code\n"
    'Trades,Data,Order,Stocks,USD,AAPL,"2024-01-03, 09:30:00",10,125.00,'
    "125.50,-1250,-1,1251,0,5,O\n"
    'Trades,Data,ClosedLot,Stocks,USD,AAPL,"2024-01-03, 09:30:00",10,120,'
    ",,,,,,\n"
    'Trades,Data,Order,Stocks,USD,AAPL,"2024-03-05, 10:00:00",-4,170.00,'
    "170.10,680,-1.02,-500,178.98,0,C\n"
    "Trades,SubTotal,,Stocks,USD,AAPL,,6,,,-570,-2.02,751,178.98,5,\n"
    'Trades,Data,Order,Forex,USD,EUR.USD,"2024-01-02, 09:00:00",1000,1.0854,'
    ",,-2,,,,\n"
    "Dividends,Header,Currency,Date,Description,Amount\n"
    "Dividends,Data,USD,2024-02-16,AAPL(US0378331005) Cash Dividend USD 0.24"
    " per Share (Ordinary Dividend),2.40\n"
    "Dividends,Data,Total,,,2.40\n"
    "Withholding Tax,Header,Currency,Date,Description,Amount,Code\n"
    "Withholding Tax,Data,USD,2024-02-16,AAPL(US0378331005) Cash Dividend"
    " USD 0.24 per Share - US Tax,-0.36,\n"
)


def test_orders_import_with_commission_as_fee():
    result = ibkr.parse_csv(IBKR_CSV)
    trades = [t for t in result.transactions if t.action in ("buy", "sell")]
    buy, sell = trades
    assert (buy.action, buy.ticker, buy.quantity, buy.price) == ("buy", "AAPL", 10, 125.0)
    assert buy.fee == 1.0 and buy.currency == "USD" and buy.date == "2024-01-03"
    assert (sell.action, sell.quantity, sell.fee) == ("sell", 4, 1.02)


def test_dividend_from_description_and_withholding_listed():
    result = ibkr.parse_csv(IBKR_CSV)
    (div,) = [t for t in result.transactions if t.action == "dividend"]
    assert (div.ticker, div.price, div.currency, div.date) == (
        "AAPL", 2.40, "USD", "2024-02-16",
    )
    # One dividend, one tax line, same day and currency: the tax goes on the
    # dividend as its fee, which is where dividends.by_year reads it from.
    assert div.fee == 0.36
    wht = [s for s in result.skipped if s["type"] == "withholding tax"]
    assert len(wht) == 1 and wht[0]["ticker"] == "AAPL"
    assert "applied as the fee" in wht[0]["reason"]


def test_forex_skipped_closedlot_and_subtotals_dropped():
    result = ibkr.parse_csv(IBKR_CSV)
    forex = [s for s in result.skipped if "Forex" in s.get("type", "")]
    assert len(forex) == 1 and "not auto-imported" in forex[0]["reason"]
    # 2 stock orders + 1 dividend; ClosedLot/SubTotal/Total left no trace
    assert len(result.transactions) == 3
    assert len(result.skipped) == 2  # forex + withholding


def test_refuses_foreign_shape():
    result = ibkr.parse_csv(
        "date,ticker,action,quantity,price\n2024-01-02,AAPL,buy,10,180\n"
    )
    assert result.transactions == []
    assert "not an IBKR activity statement" in result.skipped[0]["reason"]

    result = ibkr.parse_csv("")
    assert result.transactions == []
    assert "not an IBKR activity statement" in result.skipped[0]["reason"]


# A Spanish (es-ES) statement for a single day: IBKR translates the section
# and column names, leaves the row kinds and DataDiscriminator alone, and —
# because nothing traded that day — ships no Trades section at all. The open
# positions block is the only thing in it that names what is held.
IBKR_ES_CSV = (
    "Statement,Header,Nombre del campo,Valor del campo\n"
    "Statement,Data,BrokerName,Interactive Brokers Ireland Limited\n"
    'Statement,Data,Period,"Septiembre 14, 2026"\n'
    'Statement,Data,WhenGenerated,"2026-09-15, 05:54:54 EDT"\n'
    "Valor liquidativo,Header,Clase de activo,Total previo,Cambio\n"
    "Valor liquidativo,Data,Efectivo,3148.001906094,0.0230268\n"
    "Posiciones abiertas,Header,DataDiscriminator,Categoría de activo,Divisa,"
    "Símbolo,Cantidad,Mult.,Precio de coste,Base de coste,Precio de cierre,"
    "Valor,PyG no realizadas,Código\n"
    "Posiciones abiertas,Data,Summary,Acciones,EUR,ASML,1,1,633.9,633.9,"
    "1387.8,1387.8,753.9,\n"
    "Posiciones abiertas,Data,Summary,Acciones,EUR,EMXC,96.9398,1,"
    "26.733268307,2591.517683,40.375,3913.94,1322.422317,\n"
    "Posiciones abiertas,Total,,Acciones,EUR,,,,,24287.116663,,28609.47,"
    "4322.353337,\n"
    "Posiciones abiertas,Data,Summary,Acciones,USD,MSFT,8,1,389.8359405,"
    "3118.687524,505.41,4043.28,924.592476,\n"
    "Posiciones abiertas,Data,Summary,Fórex,USD,EUR.USD,6.19,1,0.861,5.33,"
    "0.865,5.36,0.02,\n"
    "Saldos en fórex,Header,Categoría de activo,Divisa,Descripción,Cantidad,"
    "Precio de coste,Base de coste en EUR,Precio de cierre,Valor en EUR,"
    "PyG no realizadas en EUR,Código\n"
    "Saldos en fórex,Data,Fórex,EUR,USD,6.19,0.861229887,-5.331013,0.86584,"
    "5.35955,0.028536,\n"
    "Modificación en los dividendos devengados,Header,Categoría de activo,"
    "Divisa,Símbolo,Fecha,Fecha exdividendo,Fecha de pago,Cantidad,Impuestos,"
    "Tarifa,Tasa bruta,Cantidad bruta,Cantidad neta,Código\n"
    "Modificación en los dividendos devengados,Data,Dividendos devengados "
    "iniciales enEUR,,,,,,,,,,,5.0347808,\n"
    "Modificación en los dividendos devengados,Data,Acciones,USD,UNH,"
    "2026-09-11,2026-09-14,2026-09-22,10,3.48,0,2.32,23.2,19.72,Po\n"
    "Modificación en los dividendos devengados,Data,Total,,,,,,,3.48,0,,23.2,"
    "19.72,\n"
)


def test_spanish_open_positions_import_as_arriving_shares():
    result = ibkr.parse_csv(IBKR_ES_CSV)
    held = {t.ticker: t for t in result.transactions}
    assert set(held) == {"ASML", "EMXC", "MSFT"}
    # A balance is shares already owned, not a purchase made on the statement
    # date — so they arrive, and a book that already holds them nets them out.
    assert all(t.action == "transfer_in" for t in held.values())
    # The average cost the broker itself reports, in the holding's currency.
    assert (held["EMXC"].quantity, held["EMXC"].currency) == (96.9398, "EUR")
    assert round(held["EMXC"].price, 6) == 26.733268
    assert held["MSFT"].currency == "USD" and held["MSFT"].quantity == 8
    # The period the statement covers, not the day the file was generated.
    assert all(t.date == "2026-09-14" for t in held.values())
    assert all(t.note.startswith("ibkr snapshot") for t in held.values())


def test_an_arriving_balance_with_no_departure_still_opens_the_position():
    """First-ever import: nothing to pair with, so the lots are the book."""
    from stocks.portfolio import positions

    result = ibkr.parse_csv(IBKR_ES_CSV)
    open_lots, realized = positions.build(
        result.transactions, to_base=lambda amount, ccy, day: amount
    )
    assert not realized
    assert {p.ticker: p.quantity for p in open_lots} == {
        "ASML": 1.0, "EMXC": 96.9398, "MSFT": 8.0
    }


def test_instrument_table_puts_each_holdings_isin_in_its_note():
    """The ISIN is how a holding IBKR calls ASML is recognised as the one
    DEGIRO booked under NL0010273215."""
    result = ibkr.parse_csv(IBKR_ES_CSV + _INSTRUMENTS_ES)
    notes = {t.ticker: t.note for t in result.transactions}
    assert notes["ASML.AS"] == "ibkr snapshot NL0010273215"
    assert notes["MSFT"] == "ibkr snapshot US5949181045"
    # A holding the table never names keeps the bare note rather than a blank.
    assert notes["EMXC"] == "ibkr snapshot"


def test_the_listing_venue_qualifies_a_symbol_yahoo_would_read_as_the_adr():
    """`ASML` on Yahoo is the Nasdaq ADR in dollars; the statement is
    reporting the Amsterdam share in euros. Booked bare, that holding prices
    off the ADR and is read as EUR."""
    result = ibkr.parse_csv(IBKR_ES_CSV + _INSTRUMENTS_ES)
    held = {t.ticker: t for t in result.transactions}
    assert held["ASML.AS"].currency == "EUR"  # AEB -> .AS
    assert "MSFT" in held  # NASDAQ: the bare symbol is already the right one
    # A holding the instrument table never names is left exactly as IBKR
    # wrote it — guessing a venue is how a position starts pricing off the
    # wrong listing, which is the failure this map exists to stop.
    assert "EMXC" in held


def test_an_unknown_listing_venue_leaves_the_symbol_alone():
    table = _INSTRUMENTS_ES.replace("NL0010273215,ASML,AEB", "NL0010273215,ASML,XXX")
    held = {t.ticker for t in ibkr.parse_csv(IBKR_ES_CSV + table).transactions}
    assert "ASML" in held and "ASML.AS" not in held


_INSTRUMENTS_ES = (
    "Información de instrumento financiero,Header,Categoría de activo,Símbolo,"
    "Descripción,Conid,Id. de seguridad,Underlying,Merc. de cotización,"
    "Multiplicador,Tipo,Código\n"
    "Información de instrumento financiero,Data,Acciones,ASML,ASML HOLDING NV,"
    "117589399,NL0010273215,ASML,AEB,1,COMMON,\n"
    "Información de instrumento financiero,Data,Acciones,MSFT,MICROSOFT CORP,"
    "272093,US5949181045,MSFT,NASDAQ,1,COMMON,\n"
)


def test_spanish_forex_holding_and_total_rows_left_out():
    result = ibkr.parse_csv(IBKR_ES_CSV)
    assert "EUR.USD" not in {t.ticker for t in result.transactions}
    forex = [s for s in result.skipped if "rex" in s.get("type", "")]
    assert len(forex) == 1 and "not auto-imported" in forex[0]["reason"]


def test_accrued_dividend_is_listed_not_imported():
    result = ibkr.parse_csv(IBKR_ES_CSV)
    assert "dividend" not in {t.action for t in result.transactions}
    (accrual,) = [s for s in result.skipped if s["type"] == "accrued dividend"]
    assert (accrual["ticker"], accrual["amount"]) == ("UNH", 23.2)
    assert accrual["date"] == "2026-09-22" and accrual["currency"] == "USD"


def test_positions_are_ignored_when_the_file_carries_trades():
    """The closing balance of trades just imported is not a second purchase."""
    both = IBKR_CSV + (
        "Open Positions,Header,DataDiscriminator,Asset Category,Currency,"
        "Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,"
        "Unrealized P/L,Code\n"
        "Open Positions,Data,Summary,Stocks,USD,AAPL,6,1,125,750,170,1020,"
        "270,\n"
    )
    result = ibkr.parse_csv(both)
    assert [t.quantity for t in result.transactions if t.ticker == "AAPL"
            and t.action == "buy"] == [10]
    (note,) = [s for s in result.skipped if s["type"] == "open positions"]
    assert "closing balance" in note["reason"]


def test_spanish_trades_section_wins_over_the_snapshot():
    """A Spanish statement with movements imports them, not the holdings."""
    with_trades = IBKR_ES_CSV + (
        "Operaciones,Header,DataDiscriminator,Categoría de activo,Divisa,"
        "Símbolo,Fecha/Hora,Cantidad,T. Precio,C. Precio,Productos,"
        "Tarifa/com.,Base,Realizado P/G,MTM P/G,Código\n"
        'Operaciones,Data,Order,Acciones,EUR,ASML,"2026-09-14, 09:30:00",1,'
        "633.9,640,-633.9,-1.25,635.15,0,6.1,O\n"
    )
    result = ibkr.parse_csv(with_trades)
    (trade,) = result.transactions
    assert (trade.ticker, trade.action, trade.quantity) == ("ASML", "buy", 1)
    assert (trade.price, trade.currency, trade.fee) == (633.9, "EUR", 1.25)
    assert trade.date == "2026-09-14" and trade.note == "ibkr"
