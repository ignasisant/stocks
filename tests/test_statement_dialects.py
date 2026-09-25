"""The two dialect defects the import diagnostics were built to catch.

Both broke the same way and neither raised: a European export read with the
wrong separator collapses to one column, and one saved in a Windows codepage
raised UnicodeDecodeError out of the parser. Each has a regression test for
the happy path it must not disturb.
"""

from __future__ import annotations

import pytest

from stocks.portfolio import platforms, statement

# The same statement in three dialects: the one that always worked, the
# semicolon one Excel writes in Europe, and the accented one saved as cp1252.
_HEADER = "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency"
_ROWS = (
    "2023-01-03T14:30:00.000Z,AAPL,BUY - MARKET,5,130.15,650.75,USD",
    "2023-07-01T09:00:00.000Z,AAPL,SELL - MARKET,2,150.00,300.00,USD",
)
COMMA = "\n".join((_HEADER, *_ROWS)) + "\n"
SEMICOLON = COMMA.replace(",", ";")


def _revolut(data: bytes):
    return platforms.by_key("revolut").parse("statement.csv", data)


# ------------------------------------------------------------- the delimiter


def test_a_semicolon_export_imports_like_any_other():
    """It used to yield one giant column, so every row was skipped."""
    result = _revolut(SEMICOLON.encode())
    assert len(result.transactions) == 2
    assert [t.ticker for t in result.transactions] == ["AAPL", "AAPL"]


def test_the_two_dialects_produce_the_same_ledger():
    comma = _revolut(COMMA.encode()).transactions
    semicolon = _revolut(SEMICOLON.encode()).transactions
    assert [t.__dict__ for t in comma] == [t.__dict__ for t in semicolon]


def test_a_comma_file_full_of_semicolons_is_still_comma_delimited():
    """The regression a naive separator count would have shipped.

    Scoring by resolved columns rather than by character frequency: the
    semicolons live in a description, so `;` resolves nothing and loses.
    """
    text = (
        _HEADER + ",Notes\n"
        '2023-01-03T14:30:00.000Z,AAPL,BUY - MARKET,5,130.15,650.75,USD,"a;b;c;d;e;f"\n'
    )
    result = _revolut(text.encode())
    assert len(result.transactions) == 1
    assert result.transactions[0].ticker == "AAPL"


def test_an_unrecognisable_header_falls_back_to_comma():
    assert statement.sniff_delimiter("no columns here", {"date": ("date",)}) == ","


def test_sniff_delimiter_picks_the_separator_that_resolves_most_columns():
    aliases = {"date": ("date",), "ticker": ("ticker",)}
    assert statement.sniff_delimiter("Date;Ticker;Type", aliases) == ";"
    assert statement.sniff_delimiter("Date\tTicker\tType", aliases) == "\t"
    assert statement.sniff_delimiter("Date,Ticker,Type", aliases) == ","


# What a Spanish Excel actually writes: semicolon separators, and the decimal
# commas left unquoted because the separator no longer collides with them.
DEGIRO_ES_SEMICOLON = (
    "Fecha;Hora;Producto;ISIN;Bolsa de;Centro de ejecución;Número;Precio;;"
    "Valor local;;Valor;;Tipo de cambio;Costes de transacción;;Total;;ID Orden\n"
    "03-01-2024;14:30;APPLE INC. - COMMON ST;US0378331005;NDQ;XNAS;"
    "10;125,00;USD;-1250,00;USD;-1151,65;EUR;1,0854;-2,50;EUR;-1154,15;EUR;a1\n"
)


def test_degiro_reads_its_semicolon_export_too():
    """DEGIRO drives its own row loop, so it needed the same fix."""
    result = platforms.by_key("degiro").parse(
        "Transactions.csv", DEGIRO_ES_SEMICOLON.encode()
    )
    assert result.skipped == []
    (buy,) = result.transactions
    assert (buy.action, buy.ticker, buy.quantity, buy.price) == (
        "buy", "US0378331005", 10, 125.0,
    )


# -------------------------------------------------------------- the encoding


def test_a_windows_codepage_export_no_longer_raises():
    """`platforms` decoded utf-8-sig with no fallback; this used to crash."""
    text = (
        COMMA.replace(_HEADER, _HEADER + ",Descripción")
        .replace("USD\n", "USD,Comisión de gestión\n")
    )
    result = _revolut(text.encode("cp1252"))
    assert len(result.transactions) == 2


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252"])
def test_decode_reads_every_encoding_a_broker_exports(encoding):
    assert statement.decode("Comisión".encode(encoding)).endswith("Comisión")


def test_decode_never_raises_on_bytes_that_are_no_text_at_all():
    assert isinstance(statement.decode(b"\xff\xfe\x00\x81\x8d"), str)


def test_utf8_still_wins_over_the_fallback():
    """cp1252 would decode these bytes too, but as mojibake."""
    assert statement.decode("Comisión".encode()) == "Comisión"
