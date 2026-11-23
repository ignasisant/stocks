"""Trade Republic account-statement PDF — the line parser, no PDF needed.

The lines are written for these tests in the shapes the statement takes once
pdfplumber flattens it: the English one-line rows, and the Spanish/German
rows whose date, type word and amounts wrap over two or three lines.
"""

# ruff: noqa: E501 — statement lines are kept whole, as pdfplumber gives them.

from stocks.portfolio import revolut_pdf, trade_republic_pdf
from stocks.portfolio.trade_republic_pdf import (
    CONTRADICTS,
    NO_QUANTITY,
    OLD_LAYOUT,
    REFUSAL,
    _isin_ok,
    parse_lines,
)

EN = [
    "TRADE REPUBLIC BANK GMBH",
    "ACCOUNT STATEMENT SUMMARY",
    "PRODUCT OPENING BALANCE MONEY IN MONEY OUT ENDING BALANCE",
    "Cash account €0.00 €1,300.00 €1,180.50 €119.50",
    "ACCOUNT TRANSACTIONS",
    "DATE TYPE DESCRIPTION MONEY IN MONEY OUT BALANCE",
    "02 Mar 2025 Transfer Deposit accepted: DE00000000000000000000 to DE00000000000000000000 €1,300.00 €1,300.00",
    "03 Mar 2025 Trade Buy trade IE00B4L5Y983 iShares Core MSCI World UCITS ETF USD (Acc), quantity: 10 €1,001.00 €299.00",
    "04 Mar 2025 Card Transaction SOME SHOP €20.50 €278.50",
    "05 Mar 2025 Trade Sell trade IE00B4L5Y983 iShares Core MSCI World UCITS ETF USD (Acc), quantity: 2.5 €249.00 €527.50",
    "06 Mar 2025 Earnings Cash Dividend for ISIN US0378331005 €3.00 €530.50",
    "07 Mar 2025 Interest Your interest payment €1.00 €531.50",
    "10 Mar 2025 Trade Buy trade XF000BTC0017 Bitcoin, quantity: 0.005 €412.00 €119.50",
    "Trade Republic Bank GmbH, Page 1 of 1",
]

ES = [
    "RESUMEN DE ESTADO DE CUENTA",
    "PRODUCTO SALDO INICIAL ENTRADA DE DINERO SALIDA DE DINERO SALDO FINAL",
    "Cuenta de efectivo 500,00 € 10,12 € 187,04 € 323,08 €",
    "TRANSACCIONES DE CUENTA",
    "FECHA TIPO DESCRIPCIÓN ENTRADA DE SALIDA DE BALANCE",
    "03 nov ",
    "Recompensa Your Saveback payment 10,12 € 510,12 €",
    "2025",
    "03 nov Savings plan execution IE000716YHJ7 Invesco Markets II plc - ",
    "Comercio 175,00 € 335,12 €",
    "2025 Invesco FTSE All-World UCITS ETF Acc, quantity: 24.305555",
    "04 nov ",
    "Transacción con tarjeta UNA TIENDA 12,04 € 323,08 €",
    "2025",
    "DISCLAIMER",
    "FONDOS DEL MERCADO MONETARIO ISIN UNIDADES PRECIO VALOR",
    "Deutsche Managed Euro Fund IE0008643037 0,00 1,00 € 0,00 €",
]

DE = [
    "KONTOÜBERSICHT",
    "PRODUKT ANFANGSSALDO ZAHLUNGSEINGANG ZAHLUNGSAUSGANG ENDSALDO",
    "Cashkonto 2.000,00 € 0,00 € 1.181,75 € 818,25 €",
    "UMSATZÜBERSICHT",
    "DATUM TYP BESCHREIBUNG ZAHLUNGSEINGANG ZAHLUNGSAUSGANG SALDO",
    "11 Juni Handel Buy trade US5801351017 MCDONALDS CORP., quantity: 2024 5 1.181,75 € 818,25 €",
    "12 Juni Ausführung Handel Direktkauf Kauf US0378331005 APPLE INC. 2024 10,00 € 808,25 €",
    "27 Juni ",
    "2024 Steuern Tax Optimisation 10,00 € 818,25 €",
]


def test_english_statement_books_trades_and_dividends():
    res = parse_lines(EN)
    got = [(t.date, t.ticker, t.action, t.quantity) for t in res.transactions]
    assert got == [
        ("2025-03-03", "IE00B4L5Y983", "buy", 10.0),
        ("2025-03-05", "IE00B4L5Y983", "sell", 2.5),
        ("2025-03-06", "US0378331005", "dividend", 0.0),
        ("2025-03-10", "BTC-EUR", "buy", 0.005),
    ]
    buy, sell, div, coin = res.transactions
    # No fee column: the price is the cash over the quantity, fee inside.
    assert buy.price == 100.1 and buy.fee == 0 and buy.currency == "EUR"
    assert sell.price == 249.0 / 2.5
    assert div.price == 3.0
    assert coin.price == 412.0 / 0.005
    assert buy.note == "trade_republic iShares Core MSCI World UCITS ETF USD (Acc)"
    reasons = [s["reason"] for s in res.skipped]
    assert len(reasons) == 3  # deposit, card payment, interest
    assert all("not position-affecting" in r for r in reasons)


def test_spanish_wrapped_rows_read_across_lines():
    res = parse_lines(ES)
    [buy] = res.transactions
    assert (buy.date, buy.ticker, buy.action) == ("2025-11-03", "IE000716YHJ7", "buy")
    assert buy.quantity == 24.305555  # a decimal point even in Spanish
    assert buy.price == 175.0 / 24.305555
    # The type word that wrapped into the name is not part of it.
    assert buy.note == ("trade_republic Invesco Markets II plc - Invesco FTSE "
                        "All-World UCITS ETF Acc")
    # The fund table after the bookings never joins the last one.
    assert [s["amount"] for s in res.skipped] == [10.12, 12.04]


def test_german_year_inside_the_description():
    res = parse_lines(DE)
    [buy] = res.transactions
    assert (buy.date, buy.quantity, buy.price) == ("2024-06-11", 5.0, 1181.75 / 5)
    skipped = {s["reason"] for s in res.skipped}
    # The old wording without a quantity, and a tax booking: listed, not booked.
    assert NO_QUANTITY in skipped
    assert any("tax" in r for r in skipped)


def test_balance_overrules_contradicting_wording():
    lines = [
        "ACCOUNT TRANSACTIONS",
        "01 Mar 2025 Transfer Deposit accepted €100.00 €100.00",
        # Says buy, but the balance went up by exactly the amount.
        "02 Mar 2025 Trade Buy trade IE00B4L5Y983 iShares Core MSCI World, quantity: 1 €90.00 €190.00",
        # No wording; the balance says the cash went out — a buy.
        "03 Mar 2025 Trade IE00B4L5Y983 iShares Core MSCI World, quantity: 1 €90.00 €100.00",
    ]
    res = parse_lines(lines)
    assert [t.action for t in res.transactions] == ["buy"]
    assert res.transactions[0].date == "2025-03-03"
    assert CONTRADICTS in {s["reason"] for s in res.skipped}


def test_year_carries_over_when_a_row_lost_it():
    lines = [
        "ACCOUNT TRANSACTIONS",
        "01 Mar 2025 Transfer Deposit accepted €100.00 €100.00",
        "02 Mar Trade Buy trade IE00B4L5Y983 iShares Core MSCI World, quantity: 1 €90.00 €10.00",
    ]
    assert parse_lines(lines).transactions[0].date == "2025-03-02"


def test_other_documents_are_refused():
    assert parse_lines(["Account Statement", "Date Ticker Type"]).skipped[0][
        "reason"] == REFUSAL
    old = ["KONTOAUSZUG", "BUCHUNGSTAG / BUCHUNGSTEXT BETRAG IN EUR",
           "16.04.2020 Ausführung Handel Direktkauf Kauf DE0008232125 LUFTHANSA -41,88"]
    res = parse_lines(old)
    assert not res.transactions and res.skipped[0]["reason"] == OLD_LAYOUT


def test_revolut_and_trade_republic_ignore_each_other():
    revolut = [
        "Account Statement",
        "2024-12-24 NVO BUY - MARKET 34.2896331 US$87.49 US$3,000.00 USD 1.0427",
    ]
    assert not parse_lines(revolut).transactions
    assert not revolut_pdf.parse_lines(EN).transactions
    assert not revolut_pdf.parse_lines(ES).transactions


def test_isin_check_digit():
    assert _isin_ok("IE00B4L5Y983") and _isin_ok("US0378331005")
    assert _isin_ok("XF000BTC0017")
    assert not _isin_ok("IE00B4L5Y984")


def test_platform_routes_pdf_to_the_statement_parser(monkeypatch):
    from stocks.portfolio import platforms, trade_republic_pdf

    seen = []
    monkeypatch.setattr(trade_republic_pdf, "parse_pdf",
                        lambda data: seen.append(data) or parse_lines(EN))
    tr = next(p for p in platforms.PLATFORMS if p.key == "trade_republic")
    assert "pdf" in tr.file_types
    assert len(tr.parse("Account statement.PDF", b"%PDF").transactions) == 4
    assert seen == [b"%PDF"]


def test_autodetect_finds_the_statement_without_a_platform(monkeypatch):
    from stocks.portfolio import autodetect, trade_republic_pdf

    monkeypatch.setattr(trade_republic_pdf, "parse_pdf", lambda data: parse_lines(EN))
    found, _, _ = autodetect._parsers("Account statement.pdf", b"%PDF-1.7")
    assert found and found.platform == "trade_republic"


def test_parse_pdf_reads_a_real_file():
    from stocks.portfolio.trade_republic_pdf import parse_pdf
    from tests.minipdf import pdf

    res = parse_pdf(pdf(["\n".join(EN[:8]), "\n".join(EN[8:])]))
    assert [t.action for t in res.transactions] == ["buy", "sell", "dividend", "buy"]
    assert res.transactions[0].price == 100.1


def test_parse_pdf_stops_after_a_foreign_first_page(monkeypatch):
    from stocks.portfolio import trade_republic_pdf
    from tests.minipdf import pdf

    seen = []
    real = trade_republic_pdf.parse_lines
    monkeypatch.setattr(trade_republic_pdf, "parse_lines",
                        lambda lines: seen.append(list(lines)) or real(lines))
    res = trade_republic_pdf.parse_pdf(pdf(["Revolut Securities Europe UAB",
                                            "\n".join(EN)]))
    assert seen == [["Revolut Securities Europe UAB"]]
    assert res.skipped[0]["reason"] == REFUSAL


# The shape pdfplumber gives a statement the app makes today (checked against
# a real page, figures changed): the date cell stacked — day, then month with
# the type word and amounts, then year — a description line or the quantity
# falling between them, the quantity run into the amount, the page footer
# under the last row and no section title on a page after the first.
STACKED = [
    "TRADE REPUBLIC BANK GMBH, BRANCH AUSTRIA KÄRNTNER RING 5-7 1010 WIEN, ÖSTERREICH",
    "DATUM TYP BESCHREIBUNG ZAHLUNGSEINGANGZAHLUNGSAUSGANG SALDO",
    "22",
    "Sept. Handel Buy trade US0378331005 APPLE INC., quantity: 10 1.801,00 € 8.199,00 €",
    "2025",
    "23",
    "Buy trade IE00B4L5Y983 iShares Core MSCI World UCITS ETF USD",
    "Sept. Handel 1.001,00 € 7.198,00 €",
    "(Acc), quantity: 10",
    "2025",
    "24",
    "Sept. Handel Sell trade US0378331005 APPLE INC., quantity: 302.324,47 € 9.522,47 €",
    "2025",
    "25",
    "Buy trade US0231351067 AMAZON.COM INC. DL-,01, quantity:",
    "Sept. Handel 5.611,00 € 3.911,47 €",
    "30",
    "2025",
    "Trade Republic Bank GmbH, Branch Austria www.traderepublic.at Sitz der Gesellschaft:",
    "1010 Wien, Österreich Brunnenstrasse 19-21",
    "Erstellt am 2026 Feb 9 16:50:15 Seite 2 von 22",
]


def test_stacked_date_cells_as_the_app_prints_them_today():
    res = parse_lines(STACKED)
    got = [(t.date, t.ticker, t.action, t.quantity, round(t.price, 4))
           for t in res.transactions]
    assert got == [
        ("2025-09-22", "US0378331005", "buy", 10.0, 180.1),
        ("2025-09-23", "IE00B4L5Y983", "buy", 10.0, 100.1),
        # 30 shares for 2.324,47 €, split by the balance.
        ("2025-09-24", "US0378331005", "sell", 30.0, round(2324.47 / 30, 4)),
        # The quantity wrapped past the amounts, the footer kept out.
        ("2025-09-25", "US0231351067", "buy", 30.0, round(5611.0 / 30, 4)),
    ]
    assert res.transactions[1].note == (
        "trade_republic iShares Core MSCI World UCITS ETF USD (Acc)")
    assert res.transactions[3].note == "trade_republic AMAZON.COM INC. DL-,01"
    assert not res.skipped


def test_a_glued_quantity_without_the_balance_before_is_not_guessed():
    lines = STACKED[:2] + STACKED[10:13]  # the glued sale, first on its page
    res = parse_lines(lines)
    assert not res.transactions
    assert res.skipped[0]["reason"] == trade_republic_pdf.GLUED
