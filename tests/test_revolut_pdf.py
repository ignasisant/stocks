"""PDF extraction tests — exercise the line parser, no actual PDF needed.

parse_lines is the whole PDF path minus pdfplumber text extraction, so these
tests feed it statement-shaped text lines in the renderings Revolut uses
(ISO dates, en/es month names, US and European number formats).
"""

from stocks.portfolio.revolut_pdf import _normalize_number, _to_iso, parse_lines


def test_iso_styled_lines_parse_like_csv():
    lines = [
        "Account Statement",  # noise: ignored, no type keyword
        "Date Ticker Type Quantity Price per share Total Amount Currency FX Rate",
        "2024-12-24 NVO BUY - MARKET 34.2896331 US$87.49 US$3,000.00 USD 1.0427",
        "2025-03-07 SEZL SELL - MARKET 5.84960108 US$220.99 US$1,292.68 USD 1.0893",
        "2025-03-18 GOOG DIVIDEND US$2.46 USD 1.0964",
        "2024-12-24 CASH TOP-UP US$3,000.00 USD 1.0427",
    ]
    res = parse_lines(lines)
    actions = [t.action for t in res.transactions]
    assert actions == ["buy", "sell", "dividend"]

    buy = res.transactions[0]
    assert buy.ticker == "NVO" and buy.quantity == 34.2896331
    assert buy.price == 87.49 and buy.currency == "USD"
    assert buy.date == "2024-12-24"

    # Dividend total must be the money column, never the trailing FX rate.
    div = res.transactions[2]
    assert div.price == 2.46

    assert any("cash movement" in s["reason"] for s in res.skipped)


def test_spanish_dates_and_decimal_commas():
    lines = [
        "13 feb. 2025 DHER BUY - MARKET 69,71070059 28,69 € 2.000,00 € EUR 1,0000",
    ]
    res = parse_lines(lines)
    assert len(res.transactions) == 1
    tx = res.transactions[0]
    assert tx.date == "2025-02-13"
    assert tx.ticker == "DHER"
    assert abs(tx.quantity - 69.71070059) < 1e-9
    assert tx.price == 28.69
    assert tx.currency == "EUR"


def test_split_row_keeps_added_shares_in_skipped():
    lines = ["2025-03-31 SEZL STOCK SPLIT 31.00046115 US$0.00 USD 1.0853"]
    res = parse_lines(lines)
    assert res.transactions == []
    skip = res.skipped[0]
    assert skip["ticker"] == "SEZL" and skip["quantity"] == 31.00046115


def test_dividend_tax_correction_not_imported_from_pdf():
    lines = ["2025-07-02 GOOG DIVIDEND TAX (CORRECTION) -US$0.75 USD 1.1815"]
    res = parse_lines(lines)
    assert res.transactions == []
    assert "tax correction" in res.skipped[0]["reason"]


def test_slash_dates_day_first():
    assert _to_iso("13/02/2025") == "2025-02-13"
    assert _to_iso("02/24/2025") == "2025-02-24"  # month-first fallback when b>12
    assert _to_iso("2025-02-13") == "2025-02-13"
    assert _to_iso("24 February 2025") == "2025-02-24"
    assert _to_iso("garbage") == "garbage"  # passes through; parser rejects later


def test_normalize_number_both_locales():
    assert _normalize_number("1,723.00") == "1723.00"
    assert _normalize_number("1.723,00") == "1723.00"
    assert _normalize_number("28,69") == "28.69"
    assert _normalize_number("1,723") == "1723"
    assert _normalize_number("5.84960108") == "5.84960108"
    assert _normalize_number("-0.75") == "-0.75"


def test_unparseable_trade_line_lands_in_skipped_not_lost():
    lines = ["?? ??? BUY - MARKET garbage row with no numbers"]
    res = parse_lines(lines)
    assert res.transactions == []
    assert len(res.skipped) == 1


# The 2026 layout: time + zone after the date, "Trade - Market" plus a Side
# column, and Fees + Commission where the FX columns used to be.
_2026_LINES = [
    "Date Symbol Type Quantity Price Side Value Fees Commission",
    "01 Dec 2025 14:31:21 GMT NVDA Trade - Market 12.5 US$180.00 Buy US$2,250 US$0 US$0",
    "30 Jan 2026 18:40:21 GMT NVDA Trade - Market 12.5 US$200.00 Sell US$2,494.78"
    " US$0.02 US$5.20",
    "03 Feb 2026 09:05:12 GMT SIE Trade - Limit 10 €250.00 Buy €2,506.25 €6.25 €0",
    "02 Jan 2026 03:32:09 GMT NVDA Dividend US$0.13 US$0 US$0",
    "01 Dec 2025 13:09:01 GMT Cash top-up US$5,000 US$0 US$0",
]


def test_2026_layout_trades_take_side_from_their_own_column():
    res = parse_lines(_2026_LINES)
    trades = [t for t in res.transactions if t.action in ("buy", "sell")]
    assert [(t.ticker, t.action) for t in trades] == [
        ("NVDA", "buy"), ("NVDA", "sell"), ("SIE", "buy"),
    ]
    buy = trades[0]
    assert buy.date == "2025-12-01"
    assert buy.quantity == 12.5 and buy.price == 180.0 and buy.currency == "USD"
    assert trades[2].currency == "EUR"


def test_2026_layout_fee_is_fees_plus_commission():
    res = parse_lines(_2026_LINES)
    buy, sell, eur_buy = (t for t in res.transactions if t.action in ("buy", "sell"))
    assert buy.fee == 0.0
    assert sell.fee == 5.22  # 0.02 fees + 5.20 commission, as printed
    assert eur_buy.fee == 6.25


def test_2026_layout_time_never_reads_as_date_or_ticker():
    res = parse_lines(_2026_LINES)
    div = next(t for t in res.transactions if t.action == "dividend")
    assert div.date == "2026-01-02" and div.ticker == "NVDA" and div.price == 0.13
    cash = next(s for s in res.skipped if "cash movement" in s["reason"])
    assert cash["ticker"] == ""  # not "GMT"


def test_2026_trade_without_a_side_is_skipped_not_guessed():
    lines = ["01 Dec 2025 14:31:21 GMT NVDA Trade - Market 12.5 US$180.00 US$2,250"]
    res = parse_lines(lines)
    assert res.transactions == []
    assert res.skipped[0]["reason"] == "unrecognised type — not imported"


def test_the_holdings_table_names_each_codes_isin():
    lines = [
        "Symbol Company ISIN Quantity Price Value % of Portfolio",
        "MEQA Merlin Properties SOCIMI S.A. ES0105025003 631.438159 €12.24"
        " €7,728.80 17.05%",
        "GOOGL Alphabet (Class A) US02079K3059 24 US$340.92 US$8,182.08 14.83%",
        "2024-01-03 MEQA BUY - MARKET 10 €12.00 €120.00 EUR 1.0",
        "This statement lists US02079K3059 for reference only.",
    ]
    res = parse_lines(lines)
    assert res.isins == {"MEQA": "ES0105025003", "GOOGL": "US02079K3059"}
    assert [t.ticker for t in res.transactions] == ["MEQA"]


def test_a_code_printed_with_two_isins_is_neithers():
    res = parse_lines([
        "ABC Some Co ES0105025003 1 €1 €1 1%",
        "ABC Other Co ES0171996087 2 €1 €2 1%",
    ])
    assert res.isins == {}
