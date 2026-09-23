"""Column mapping for exports no dedicated parser owns (portfolio/llm_map).

The contract under test is the split that makes this safe: the model names
columns, Python converts rows. So the interesting cases are the conversion
(European decimals, accountancy negatives, date formats, unmapped actions),
the defensive validation of whatever JSON comes back, and the fact that one
call maps a file of any length.
"""

from __future__ import annotations

import io
import json

import pytest

from stocks.portfolio import instruments, llm_map

# A hand-kept Spanish spreadsheet: two preamble rows, semicolons, comma
# decimals, dotted thousands, an action column in Spanish and a trailing
# totals line — none of which any dedicated parser accepts.
ES_CSV = (
    "Extracto de operaciones;;;;;;\n"
    "Cuenta 1234;;;;;;\n"
    "Fecha;Valor;Operación;Títulos;Precio;Divisa;Comisión\n"
    "02/01/2024;AAPL;Compra;10;180,50;USD;1,20\n"
    "05/03/2024;AAPL;Venta;-4;190,00;USD;1,20\n"
    "16/02/2024;MSFT;Dividendo;0;1.234,56;USD;0\n"
    "03/04/2024;SAN;Traspaso;5;4,10;EUR;0\n"
)

# A holdings report: a table, but no date and nothing that says what
# happened. Neither the model nor the guess can make transactions of it, and
# that is the case where an outage is still an outage.
POSITIONS_CSV = (
    "Resumen de cartera;;\n"
    "Posicion;Cantidad;Valor\n"
    "AAPL;10;1.805,00\n"
    "MSFT;5;2.000,00\n"
)

MAPPING = {
    "header_row": 2,
    "columns": {"date": 0, "ticker": 1, "action": 2, "quantity": 3,
                "price": 4, "currency": 5, "fee": 6, "note": None},
    "date_format": "%d/%m/%Y",
    "decimal": ",",
    "thousands": ".",
    "action_map": {"compra": "buy", "venta": "sell", "dividendo": "dividend"},
}


@pytest.fixture(autouse=True)
def clear_symbol_memo():
    """Resolution is memoised process-wide; each test starts with none."""
    instruments._memo.clear()
    yield
    instruments._memo.clear()


class _StubProvider:
    classifier_model = "stub-mini"
    default_model = "stub"

    def __init__(self, reply="", boom=False):
        self.reply, self.boom = reply, boom
        self.calls = []

    def complete(self, api_key, model, system, messages):
        self.calls.append((api_key, model, system, messages))
        if self.boom:
            raise RuntimeError("network down")
        return self.reply


# -------------------------------------------------------------- file to grid


def test_read_grid_sniffs_semicolons_and_keeps_preamble():
    grid = llm_map.read_grid("extracto.csv", ES_CSV.encode("utf-8"))
    assert grid[2][:3] == ["Fecha", "Valor", "Operación"]
    assert grid[3][0] == "02/01/2024"


def test_read_grid_drops_blank_lines():
    grid = llm_map.read_grid("x.csv", b"a,b\n\n,\n1,2\n")
    assert grid == [["a", "b"], ["1", "2"]]


def test_read_grid_survives_latin1():
    grid = llm_map.read_grid("x.csv", "Fecha,Valor\n02/01/2024,Telefónica\n"
                             .encode("latin-1"))
    assert grid[1][0] == "02/01/2024"


def test_read_grid_returns_empty_for_an_unreadable_file():
    assert llm_map.read_grid("x.xlsx", b"not really a spreadsheet") == []


def test_sample_is_indexed_and_truncated():
    grid = [["a" * 100, "b"], ["1", "2"]]
    out = llm_map.sample(grid)
    assert out.startswith("row 0: ")
    assert "a" * llm_map.MAX_CELL in out
    assert "a" * (llm_map.MAX_CELL + 1) not in out


# ------------------------------------------------------------ mapping checks


def _grid():
    return llm_map.read_grid("extracto.csv", ES_CSV.encode("utf-8"))


def test_parse_mapping_accepts_a_good_reply():
    raw = '{"header_row": 2, "columns": {"date": 0, "ticker": 1, "action": 2}}'
    out = llm_map.parse_mapping(raw, _grid())
    assert out["header_row"] == 2
    assert out["columns"]["date"] == 0
    assert out["columns"]["quantity"] is None  # absent stays absent


def test_parse_mapping_rejects_a_missing_required_column():
    raw = '{"header_row": 2, "columns": {"date": 0, "ticker": 1}}'
    assert llm_map.parse_mapping(raw, _grid()) is None


def test_parse_mapping_rejects_an_out_of_range_index():
    raw = '{"header_row": 2, "columns": {"date": 0, "ticker": 1, "action": 99}}'
    assert llm_map.parse_mapping(raw, _grid()) is None


def test_parse_mapping_rejects_an_explicit_refusal():
    assert llm_map.parse_mapping('{"columns": null}', _grid()) is None


def test_parse_mapping_rejects_garbage():
    assert llm_map.parse_mapping("sorry, I can't help", _grid()) is None
    assert llm_map.parse_mapping("{not json", _grid()) is None


def test_parse_mapping_drops_unknown_actions():
    raw = ('{"header_row": 2, "columns": {"date": 0, "ticker": 1, "action": 2},'
           ' "action_map": {"Compra": "buy", "Traspaso": "transfer"}}')
    out = llm_map.parse_mapping(raw, _grid())
    assert out["action_map"] == {"compra": "buy"}


def test_parse_mapping_refuses_a_thousands_separator_equal_to_the_decimal():
    """Stripping it would silently eat the decimals off every number."""
    raw = ('{"header_row": 2, "columns": {"date": 0, "ticker": 1, "action": 2},'
           ' "decimal": ",", "thousands": ","}')
    assert llm_map.parse_mapping(raw, _grid())["thousands"] == ""


# ------------------------------------------------------------------ numbers


@pytest.mark.parametrize("text,expected", [
    ("1.234,56", 1234.56),
    ("€ 1.234,56", 1234.56),
    ("-12,50", -12.5),
    ("(12,50)", -12.5),  # accountancy negative
    (" 1 234,00 EUR", 1234.0),  # non-breaking spaces
    ("", None),
    ("n/a", None),
])
def test_number_european(text, expected):
    assert llm_map._number(text, ",", ".") == expected


@pytest.mark.parametrize("text,expected", [
    ("1,234.56", 1234.56),
    ("$1,234.56", 1234.56),
    ("180.50", 180.5),
])
def test_number_us(text, expected):
    assert llm_map._number(text, ".", ",") == expected


def test_number_recovers_undeclared_thousands():
    """'1.234.567' can only be a grouped integer — two separators, no decimals."""
    assert llm_map._number("1.234.567", ".", "") == 1234567.0


# -------------------------------------------------------------------- dates


def test_date_uses_the_mapped_format_first():
    assert llm_map._date("02/01/2024", "%d/%m/%Y") == "2024-01-02"
    assert llm_map._date("02/01/2024", "%m/%d/%Y") == "2024-02-01"


def test_date_falls_back_when_the_mapped_format_is_wrong():
    assert llm_map._date("2024-01-02", "%d/%m/%Y") == "2024-01-02"


def test_date_strips_a_time_part():
    assert llm_map._date("2024-01-02 14:30:15", "%Y-%m-%d") == "2024-01-02"


def test_date_gives_up_rather_than_guessing():
    assert llm_map._date("last tuesday", "%Y-%m-%d") is None
    assert llm_map._date("", "%Y-%m-%d") is None


# ------------------------------------------------------------------ applying


def test_apply_mapping_converts_every_row():
    result = llm_map.apply_mapping(_grid(), MAPPING)
    buy, sell, div = result.transactions

    assert (buy.date, buy.ticker, buy.action) == ("2024-01-02", "AAPL", "buy")
    assert (buy.quantity, buy.price, buy.fee, buy.currency) == (
        10.0, 180.5, 1.2, "USD")
    # exported as a negative quantity; the action already carries the direction
    assert sell.action == "sell" and sell.quantity == 4.0
    assert div.action == "dividend" and div.price == 1234.56


def test_apply_mapping_skips_unmapped_actions_with_a_reason():
    result = llm_map.apply_mapping(_grid(), MAPPING)
    assert [s["type"] for s in result.skipped] == ["Traspaso"]
    assert result.skipped[0]["reason"] == "action not recognised"
    assert result.skipped[0]["row"] == 7  # 1-based, header included


def test_apply_mapping_skips_an_unreadable_date():
    grid = [["Fecha", "Valor", "Operación"], ["mañana", "AAPL", "Compra"]]
    mapping = {**MAPPING, "header_row": 0,
               "columns": {**MAPPING["columns"], "quantity": None,
                           "price": None, "currency": None, "fee": None}}
    result = llm_map.apply_mapping(grid, mapping)
    assert not result.transactions
    assert "unreadable date" in result.skipped[0]["reason"]


def test_apply_mapping_skips_a_row_with_no_symbol():
    grid = [["Fecha", "Valor", "Operación"], ["02/01/2024", "", "Compra"]]
    mapping = {**MAPPING, "header_row": 0,
               "columns": {**MAPPING["columns"], "quantity": None,
                           "price": None, "currency": None, "fee": None}}
    result = llm_map.apply_mapping(grid, mapping)
    assert result.skipped[0]["reason"] == "no symbol"


def test_apply_mapping_skips_a_row_whose_symbol_is_its_currency():
    """The currency column mapped as the symbol — a well-formed misread."""
    grid = [["date", "ticker", "action", "currency"],
            ["2024-01-02", "EUR", "dividend", "EUR"]]
    mapping = {**MAPPING, "header_row": 0,
               "columns": {"date": 0, "ticker": 1, "action": 2, "currency": 3,
                           "quantity": None, "price": None, "fee": None}}
    result = llm_map.apply_mapping(grid, mapping)
    assert not result.transactions
    assert result.skipped[0]["reason"] == "ticker is the currency EUR"


def test_extracted_row_whose_symbol_is_its_currency_is_dropped():
    tx, why = llm_map._transaction_from({
        "date": "2024-12-27", "ticker": "USD", "action": "dividend",
        "price": 1.08, "currency": "USD"})
    assert tx is None and why == "ticker is the currency USD"


def test_the_extracted_label_is_kept_verbatim_for_resolution():
    """_transaction_from copies what the page said; symbols come later."""
    tx, why = llm_map._transaction_from({
        "date": "2024-08-29", "ticker": "PDD Holdings Inc - ADR",
        "action": "buy", "quantity": 22, "price": 94.41, "currency": "USD"})
    assert tx is not None and tx.ticker == "PDD HOLDINGS INC - ADR"


# Fidelity writes the action as a sentence that is unique to every row, so an
# exact-match vocabulary matches nothing below the sampled rows.
SENTENCE_CSV = (
    "Run Date,Action,Symbol,Quantity,Price ($),Fees ($),Amount ($)\n"
    "01/16/2025,YOU BOUGHT PROSHARES ULTRAPRO QQQ (TQQQ) (Cash),TQQQ,"
    "50,78.4200,0.02,-3921.02\n"
    "04/22/2025,DIVIDEND RECEIVED VANGUARD TOTAL STOCK MKT (VTI),VTI,"
    "0,0.0000,0.00,22.15\n"
    "08/07/2025,YOU SOLD PROSHARES ULTRAPRO QQQ (TQQQ) (Cash),TQQQ,"
    "-20,96.3300,0.03,1926.57\n"
    "09/01/2025,ELECTRONIC FUNDS TRANSFER RECEIVED,,0,0.0000,0.00,500.00\n"
)

SENTENCE_MAPPING = {
    "header_row": 0,
    "columns": {"date": 0, "action": 1, "ticker": 2, "quantity": 3,
                "price": 4, "fee": 5, "amount": 6, "currency": None,
                "note": None},
    "date_format": "%m/%d/%Y",
    "decimal": ".",
    "thousands": "",
    "action_map": {"you bought": "buy", "you sold": "sell",
                   "dividend received": "dividend"},
}


def test_an_action_written_as_a_sentence_is_read_by_its_phrase():
    grid = llm_map.read_grid("x.csv", SENTENCE_CSV.encode())
    result = llm_map.apply_mapping(grid, SENTENCE_MAPPING)

    assert [t.action for t in result.transactions] == [
        "buy", "dividend", "sell"]
    buy, div, sell = result.transactions
    assert (buy.quantity, buy.price) == (50.0, 78.42)
    assert div.price == 22.15  # the total column, the per-share cell is 0
    assert sell.quantity == 20.0  # exported negative
    # The cash line names no action of ours and is still reported, not dropped.
    assert result.skipped[0]["reason"] == "action not recognised"


def test_a_phrase_only_counts_as_a_whole_word():
    """"buy" inside "buyback" is not a buy."""
    grid = [["date", "action", "ticker"], ["2025-01-02", "Buyback offer", "X"]]
    mapping = {**SENTENCE_MAPPING, "action_map": {"buy": "buy"},
               "columns": {"date": 0, "action": 1, "ticker": 2,
                           "quantity": None, "price": None, "amount": None,
                           "fee": None, "currency": None, "note": None},
               "date_format": "%Y-%m-%d"}
    result = llm_map.apply_mapping(grid, mapping)
    assert not result.transactions
    assert result.skipped[0]["reason"] == "action not recognised"


def test_the_longest_phrase_wins():
    """A broker that spells out both keeps its own distinction."""
    grid = [["date", "action", "ticker"],
            ["2025-01-02", "Sell to close position", "X"]]
    mapping = {**SENTENCE_MAPPING,
               "action_map": {"sell": "sell", "sell to close": "fee"},
               "columns": {"date": 0, "action": 1, "ticker": 2,
                           "quantity": None, "price": None, "amount": None,
                           "fee": None, "currency": None, "note": None},
               "date_format": "%Y-%m-%d"}
    assert llm_map.apply_mapping(grid, mapping).transactions[0].action == "fee"


def test_a_canonical_verb_inside_a_sentence_is_the_last_resort():
    """A row type the sample never showed the model still reads."""
    grid = [["date", "action", "ticker"],
            ["2025-01-02", "Stock split 10:1 applied", "X"]]
    mapping = {**SENTENCE_MAPPING, "action_map": {"you bought": "buy"},
               "columns": {"date": 0, "action": 1, "ticker": 2,
                           "quantity": None, "price": None, "amount": None,
                           "fee": None, "currency": None, "note": None},
               "date_format": "%Y-%m-%d"}
    assert llm_map.apply_mapping(grid, mapping).transactions[0].action == "split"


# A file that prints both a per-share price and a row total — the shape that
# makes one "price" column index unable to serve every row: the dividend's
# value is in the total column and its per-share cell is zero.
TOTALS_CSV = (
    "Date,Type,Symbol,Units,Unit Price,Fees,Amount\n"
    "12/03/2025,Open Position,NVDA,30,151.00,1.50,-4530.00\n"
    "01/03/2026,Dividend,MSFT,0,0.00,0.00,6.64\n"
    "01/09/2026,Fee,MSFT,0,0.00,0.00,-2.50\n"
)

TOTALS_MAPPING = {
    "header_row": 0,
    "columns": {"date": 0, "action": 1, "ticker": 2, "quantity": 3,
                "price": 4, "amount": 6, "fee": 5, "currency": None,
                "note": None},
    "date_format": "%m/%d/%Y",
    "decimal": ".",
    "thousands": "",
    "action_map": {"open position": "buy", "dividend": "dividend",
                   "fee": "fee"},
}


def test_a_dividend_takes_its_value_from_the_total_column():
    """The per-share cell is 0 on a dividend row; the total is the amount."""
    grid = llm_map.read_grid("x.csv", TOTALS_CSV.encode())
    buy, div, fee = llm_map.apply_mapping(grid, TOTALS_MAPPING).transactions

    assert div.price == 6.64
    assert fee.price == 2.50  # a fee row prints its value in the same column
    # The trade keeps its own per-share price; the total is not divided in.
    assert buy.price == 151.00


def test_a_trade_with_no_unit_price_divides_the_total():
    """Some exports carry only a total — better a derived price than zero."""
    csv = ("Date,Type,Symbol,Units,Amount\n"
           "12/03/2025,Buy,NVDA,30,-4530.00\n")
    grid = llm_map.read_grid("x.csv", csv.encode())
    mapping = {**TOTALS_MAPPING, "action_map": {"buy": "buy"},
               "columns": {"date": 0, "action": 1, "ticker": 2, "quantity": 3,
                           "amount": 4, "price": None, "fee": None,
                           "currency": None, "note": None}}
    assert llm_map.apply_mapping(grid, mapping).transactions[0].price == 151.0


def test_a_total_never_overrides_a_price_the_file_stated():
    grid = llm_map.read_grid("x.csv", TOTALS_CSV.encode())
    mapping = {**TOTALS_MAPPING,
               "columns": {**TOTALS_MAPPING["columns"], "amount": 6}}
    buy = llm_map.apply_mapping(grid, mapping).transactions[0]
    assert buy.price == 151.00 and buy.quantity == 30.0


def test_a_mapping_without_an_amount_column_still_applies():
    """Every stored mapping predates the amount column; none may break."""
    legacy = {**MAPPING}
    legacy["columns"] = {k: v for k, v in MAPPING["columns"].items()
                         if k != "amount"}
    assert len(llm_map.apply_mapping(_grid(), legacy).transactions) == 3


def test_apply_mapping_accepts_an_already_canonical_action():
    """A file that already says "buy" needs no action_map entry."""
    grid = [["date", "ticker", "action"], ["2024-01-02", "AAPL", "BUY"]]
    mapping = {**MAPPING, "header_row": 0, "action_map": {},
               "columns": {**MAPPING["columns"], "quantity": None,
                           "price": None, "currency": None, "fee": None}}
    assert llm_map.apply_mapping(grid, mapping).transactions[0].action == "buy"


# ------------------------------------------------------------ pdf extraction
# A PDF has no regular grid to map, so the model extracts the values itself.
# _pdf_batches is monkeypatched throughout: pdfplumber's text extraction is
# not what these tests are about (same approach as test_revolut_pdf).


POSITIONS_PAGE = """Posiciones, EUR
Instrumento | Cantidad | PreciodeApertura | PrecioActual | Valordemercado
InModeLtd(ISIN:
USD | 112 | 18,15890 | 14,85000 | 1.428,82
IL0011595993)
"""

TRADES_PAGE = """Operaciones ejecutadas
Fecha | Valor | Tipo | Titulos | Precio
02/01/2024 | AAPL | Compra | 10 | 180,50
"""


def _extraction(kind, transactions=()):
    return json.dumps({"kind": kind, "transactions": list(transactions)})


def _batches(monkeypatch, pages):
    monkeypatch.setattr(llm_map, "_pdf_batches", lambda data: list(pages))


def test_a_portfolio_report_is_reported_as_positions(monkeypatch):
    """The user's real case: holdings with no dated movements. Nothing to
    import is the right answer — but it must not read as 'unreadable'."""
    _batches(monkeypatch, [POSITIONS_PAGE])
    found = llm_map.extract("Portfolio.pdf", b"%PDF",
                            _StubProvider(_extraction("positions")), "k")

    assert found.kind == llm_map.KIND_POSITIONS
    assert not found.result.transactions


def test_extracted_trades_become_transactions(monkeypatch):
    _batches(monkeypatch, [TRADES_PAGE])
    provider = _StubProvider(_extraction("trades", [{
        "date": "2024-01-02", "ticker": "aapl", "action": "Buy",
        "quantity": 10, "price": 180.5, "currency": "usd", "fee": 1.2,
        "note": "primera compra",
    }]))
    found = llm_map.extract("statement.pdf", b"%PDF", provider, "k")

    tx, = found.result.transactions
    assert found.kind == llm_map.KIND_TRADES
    assert (tx.date, tx.ticker, tx.action) == ("2024-01-02", "AAPL", "buy")
    assert (tx.quantity, tx.price, tx.fee, tx.currency) == (10.0, 180.5, 1.2, "USD")


def test_the_resolution_call_is_retried_once(monkeypatch):
    """It lands right behind the extraction calls, into a per-minute limit."""
    _batches(monkeypatch, [TRADES_PAGE])
    monkeypatch.setattr(llm_map, "RESOLVE_RETRY_SECONDS", 0)
    replies = iter([
        _extraction("trades", [{"date": "2024-01-02", "ticker": "Tesla Inc.",
                                "action": "buy", "quantity": 1, "price": 10}]),
        RuntimeError("429 rate limited"),
        '{"TESLA INC.": "TSLA"}',
    ])

    class _RateLimitedOnce(_StubProvider):
        def complete(self, api_key, model, system, messages):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

    found = llm_map.extract("statement.pdf", b"%PDF", _RateLimitedOnce(), "k")
    assert found.result.transactions[0].ticker == "TSLA"


def test_labels_become_tickers_in_one_extra_call(monkeypatch):
    """Names and ISINs are resolved by the model, once, after the read."""
    _batches(monkeypatch, [TRADES_PAGE])
    replies = iter([
        _extraction("trades", [
            {"date": "2024-11-13", "ticker": "LVMH Moet Hennessy Louis Vuitton",
             "action": "buy", "quantity": 5, "price": 575, "currency": "EUR"},
            {"date": "2024-12-05", "ticker": "IL0011595993",
             "action": "buy", "quantity": 112, "price": 18.16},
            {"date": "2024-12-05", "ticker": "LVMH Moet Hennessy Louis Vuitton",
             "action": "sell", "quantity": 5, "price": 629.9, "currency": "EUR"},
        ]),
        '{"LVMH MOET HENNESSY LOUIS VUITTON": "MC.PA", "IL0011595993": "INMD"}',
    ])

    class _Sequence(_StubProvider):
        def complete(self, api_key, model, system, messages):
            self.calls.append(messages)
            return next(replies)

    provider = _Sequence()
    found = llm_map.extract("statement.pdf", b"%PDF", provider, "k")

    assert [tx.ticker for tx in found.result.transactions] == [
        "MC.PA", "INMD", "MC.PA"]
    assert len(provider.calls) == 2  # one read, one resolution for three rows


def test_an_unresolved_label_keeps_its_name_for_the_preview(monkeypatch):
    """Nothing is guessed: the row reaches validation named as printed."""
    _batches(monkeypatch, [TRADES_PAGE])
    replies = iter([
        _extraction("trades", [{"date": "2024-01-02", "ticker": "Banco Fictício SA",
                                "action": "buy", "quantity": 1, "price": 10}]),
        '{"BANCO FICTÍCIO SA": null}',
    ])

    class _Sequence(_StubProvider):
        def complete(self, api_key, model, system, messages):
            return next(replies)

    found = llm_map.extract("statement.pdf", b"%PDF", _Sequence(), "k")
    assert found.result.transactions[0].ticker == "BANCO FICTÍCIO SA"


def test_a_dead_provider_leaves_the_labels_alone(monkeypatch):
    """The read succeeded; only resolution failed. Keep what was read."""
    _batches(monkeypatch, [TRADES_PAGE])
    monkeypatch.setattr(llm_map, "RESOLVE_RETRY_SECONDS", 0)
    replies = iter([_extraction("trades", [{"date": "2024-01-02",
                                            "ticker": "Tesla Inc.",
                                            "action": "buy", "quantity": 1,
                                            "price": 10}])])

    class _DiesOnResolution(_StubProvider):
        def complete(self, api_key, model, system, messages):
            try:
                return next(replies)
            except StopIteration:
                raise RuntimeError("network down") from None

    provider = _DiesOnResolution()
    found = llm_map.extract("statement.pdf", b"%PDF", provider, "k")
    assert found.result.transactions[0].ticker == "TESLA INC."
    # and the preview says why, instead of blaming the statement
    assert "symbols could not be looked up" in found.result.skipped[0]["reason"]


def test_one_page_of_trades_outweighs_pages_of_holdings(monkeypatch):
    """A statement that opens with a valuation summary is still a statement."""
    _batches(monkeypatch, [POSITIONS_PAGE, TRADES_PAGE])
    replies = iter([_extraction("positions"),
                    _extraction("trades", [{"date": "2024-01-02",
                                            "ticker": "AAPL", "action": "buy",
                                            "quantity": 1, "price": 10}])])

    class _Sequence(_StubProvider):
        def complete(self, api_key, model, system, messages):
            self.calls.append(messages)
            return next(replies)

    found = llm_map.extract("mixed.pdf", b"%PDF", _Sequence(), "k")
    assert found.kind == llm_map.KIND_TRADES
    assert len(found.result.transactions) == 1


def test_each_page_block_is_its_own_call(monkeypatch):
    _batches(monkeypatch, [TRADES_PAGE] * 3)
    provider = _StubProvider(_extraction("trades"))
    llm_map.extract("long.pdf", b"%PDF", provider, "k")
    assert len(provider.calls) == 3


def test_a_block_the_model_chokes_on_costs_only_that_block(monkeypatch):
    _batches(monkeypatch, [TRADES_PAGE, TRADES_PAGE])
    replies = iter([RuntimeError("rate limited"),
                    _extraction("trades", [{"date": "2024-01-02",
                                            "ticker": "AAPL", "action": "buy",
                                            "quantity": 1, "price": 10}])])

    class _Flaky(_StubProvider):
        def complete(self, api_key, model, system, messages):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

    found = llm_map.extract("flaky.pdf", b"%PDF", _Flaky(), "k")
    assert len(found.result.transactions) == 1
    assert any(s["type"] == "batch" for s in found.result.skipped)


def test_a_document_past_the_call_limit_says_so(monkeypatch):
    """Bounded coverage must be reported, never silently truncated."""
    _batches(monkeypatch, [TRADES_PAGE] * (llm_map.MAX_PDF_CALLS + 2))
    provider = _StubProvider(_extraction("trades"))
    found = llm_map.extract("huge.pdf", b"%PDF", provider, "k")

    assert len(provider.calls) == llm_map.MAX_PDF_CALLS
    assert "2 more page block(s) not read" in found.result.skipped[-1]["reason"]


@pytest.mark.parametrize("record,why", [
    ({"date": "2024-01-02", "ticker": "AAPL", "action": "transfer"},
     "unknown action"),
    ({"date": "whenever", "ticker": "AAPL", "action": "buy"}, "unreadable date"),
    ({"date": "2024-01-02", "ticker": "", "action": "buy"}, "no symbol"),
    ("not even a dict", "not a record"),
])
def test_a_bad_extracted_record_is_dropped_with_a_reason(record, why, monkeypatch):
    """Whatever the model returns is re-checked before it can reach a ledger."""
    _batches(monkeypatch, [TRADES_PAGE])
    found = llm_map.extract("x.pdf", b"%PDF",
                            _StubProvider(_extraction("trades", [record])), "k")
    assert not found.result.transactions
    assert why in found.result.skipped[0]["reason"]


def test_extracted_numbers_are_coerced_not_trusted(monkeypatch):
    """A sell exported negative, and a price the model returned as a string."""
    _batches(monkeypatch, [TRADES_PAGE])
    found = llm_map.extract("x.pdf", b"%PDF", _StubProvider(_extraction(
        "trades", [{"date": "2024-01-02", "ticker": "AAPL", "action": "sell",
                    "quantity": -4, "price": "190.0", "fee": None}])), "k")
    tx, = found.result.transactions
    assert (tx.quantity, tx.price, tx.fee) == (4.0, 190.0, 0.0)


def test_a_dead_provider_is_not_reported_as_an_unreadable_file(monkeypatch):
    """"The assistant is down" and "your export makes no sense" need different
    answers — the second sends the user off to fix a file that is fine."""
    _batches(monkeypatch, [TRADES_PAGE, TRADES_PAGE])
    found = llm_map.extract("x.pdf", b"%PDF", _StubProvider(boom=True), "k")
    assert found.unavailable is True
    assert not found.result.transactions


def test_one_block_failing_is_not_an_outage(monkeypatch):
    _batches(monkeypatch, [TRADES_PAGE, TRADES_PAGE])
    replies = iter([RuntimeError("rate limited"), _extraction("trades")])

    class _Flaky(_StubProvider):
        def complete(self, api_key, model, system, messages):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

    assert llm_map.extract("x.pdf", b"%PDF", _Flaky(), "k").unavailable is False


def test_a_dead_provider_on_the_spreadsheet_path_too():
    """Only when the file defeats the model *and* the header/content guess."""
    found = llm_map.extract("posiciones.csv", POSITIONS_CSV.encode(),
                            _StubProvider(boom=True), "k")
    assert found.unavailable is True
    assert "assistant is down" in found.result.skipped[0]["reason"]


def test_a_dead_provider_still_imports_a_readable_file():
    # The columns are named in the file; nothing about reading them needs a
    # model, so an outage must not be the end of the import.
    found = llm_map.extract("extracto.csv", ES_CSV.encode(),
                            _StubProvider(boom=True), "k")
    assert found.unavailable is False
    assert [tx.ticker for tx in found.result.transactions] == ["AAPL", "AAPL",
                                                               "MSFT"]


def test_a_refused_mapping_is_not_an_outage():
    found = llm_map.extract("posiciones.csv", POSITIONS_CSV.encode(),
                            _StubProvider('{"columns": null}'), "k")
    assert found.unavailable is False


def test_parse_extraction_survives_junk():
    assert llm_map.parse_extraction("sorry!") == ([], llm_map.KIND_NONE)
    assert llm_map.parse_extraction("{bad json") == ([], llm_map.KIND_NONE)
    assert llm_map.parse_extraction('{"kind": "wat"}') == ([], llm_map.KIND_NONE)


def test_a_pdf_with_no_text_is_reported(monkeypatch):
    _batches(monkeypatch, [])
    found = llm_map.extract("scan.pdf", b"%PDF", _StubProvider(""), "k")
    assert "no text could be read" in found.result.skipped[0]["reason"]


# --------------------------------------------------------------- end to end


def _reply(mapping: dict) -> str:
    return f"Here you go:\n```json\n{json.dumps(mapping)}\n```"


def test_parse_maps_once_however_long_the_file_is():
    rows = "".join(
        f"0{d % 9 + 1}/01/2024;AAPL;Compra;1;100,00;USD;0\n" for d in range(500)
    )
    data = (ES_CSV.rsplit("\n", 5)[0] + "\n" + rows).encode("utf-8")
    provider = _StubProvider(_reply(MAPPING))

    result = llm_map.parse("big.csv", data, provider, "key")

    assert len(result.transactions) == 500
    # Two calls whatever the length: one maps the columns from a sample, one
    # resolves the file's distinct labels. Neither grows with the row count.
    assert len(provider.calls) == 2
    _, model, _, messages = provider.calls[0]
    assert model == "stub-mini"
    assert messages[0]["content"].count("row ") <= llm_map.SAMPLE_ROWS


def test_parse_reports_an_unreadable_file_instead_of_raising():
    result = llm_map.parse("notes.pdf", b"", _StubProvider(_reply(MAPPING)))
    assert not result.transactions
    assert "no text could be read" in result.skipped[0]["reason"]


def test_parse_reports_an_unreadable_spreadsheet():
    result = llm_map.parse("book.xlsx", b"nonsense", _StubProvider(_reply(MAPPING)))
    assert not result.transactions
    assert "no table" in result.skipped[0]["reason"]


def test_parse_reports_a_refused_mapping():
    result = llm_map.parse("posiciones.csv", POSITIONS_CSV.encode(),
                           _StubProvider('{"columns": null}'))
    assert not result.transactions
    assert "columns could not be matched" in result.skipped[0]["reason"]


def test_parse_survives_a_dead_provider():
    result = llm_map.parse("posiciones.csv", POSITIONS_CSV.encode(),
                           _StubProvider(boom=True))
    assert not result.transactions and result.skipped


def test_parse_reads_a_real_xlsx(tmp_path):
    """openpyxl is already a dependency (ClickTrade); the Excel path must use it."""
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    for row in [["Extracto"], ["Fecha", "Valor", "Operación", "Títulos",
                               "Precio", "Divisa", "Comisión"],
                ["02/01/2024", "AAPL", "Compra", "10", "180,50", "USD", "1,20"]]:
        sheet.append(row)
    buf = io.BytesIO()
    book.save(buf)

    mapping = {**MAPPING, "header_row": 1}
    result = llm_map.parse("libro.xlsx", buf.getvalue(),
                           _StubProvider(_reply(mapping)))
    assert len(result.transactions) == 1
    assert result.transactions[0].price == 180.5


# ------------------------------------------- mapping the file with no model
#
# The model call is an optimisation, not a dependency: the columns of a CSV
# are named in the CSV. These cover the path that reads them without asking
# anyone, which is what runs when the free chain is rate-limited.

CRYPTO_CSV = (
    "Symbol,Type,Quantity,Price,Value,Fees,Date\n"
    'SOL,Compra,5.144921,194.37€,"1,000.00€",9.90€,3 feb 2025 09:21:06\n'
    'BTC,Compra,0.00955534,"73,257.41€",700.00€,6.93€,21 nov 2025 12:11:14\n'
    'ETH,Venta,1.03718945,"1,928.29€","2,000.00€",19.80€,2 feb 2026 09:55:05\n'
    "SOL,Recompensa de staking,0.001771,,,,6 feb 2025 13:38:21\n"
)

# The same rows with the headers replaced by nothing anyone could look up.
OPAQUE_CSV = (
    "c1,c2,c3,c4,c5\n"
    "0001,3 feb 2025 09:21:06,AAPL,Compra,10\n"
    "0002,17 feb 2025 09:08:18,AAPL,Compra,4\n"
    "0003,23 abr 2025 04:22:04,MSFT,Venta,2\n"
)


def test_the_columns_are_mapped_without_asking_anyone():
    mapping = llm_map.guess_mapping(llm_map.read_grid("x.csv", ES_CSV.encode()))
    assert mapping["header_row"] == 2
    assert mapping["columns"]["date"] == 0
    assert mapping["columns"]["ticker"] == 1
    assert mapping["columns"]["action"] == 2
    assert (mapping["decimal"], mapping["thousands"]) == (",", ".")


def test_unnamed_columns_are_found_by_what_is_in_them():
    mapping = llm_map.guess_mapping(llm_map.read_grid("x.csv", OPAQUE_CSV.encode()))
    # Nothing in the header row says anything; the cells do.
    assert mapping["columns"]["date"] == 1
    assert mapping["columns"]["action"] == 3
    assert mapping["columns"]["ticker"] == 2
    result = llm_map.apply_mapping(
        llm_map.read_grid("x.csv", OPAQUE_CSV.encode()), mapping)
    assert [(tx.date, tx.ticker, tx.action) for tx in result.transactions] == [
        ("2025-02-03", "AAPL", "buy"),
        ("2025-02-17", "AAPL", "buy"),
        ("2025-04-23", "MSFT", "sell"),
    ]


def test_a_file_of_coins_imports_as_pairs_not_as_shares():
    """SOL is Emeren Group on NYSE; a coin left bare prices as that company."""
    grid = llm_map.read_grid("wallet.csv", CRYPTO_CSV.encode())
    result = llm_map.apply_mapping(grid, llm_map.guess_mapping(grid))
    assert [tx.ticker for tx in result.transactions] == [
        "SOL-EUR", "BTC-EUR", "ETH-EUR"]
    assert result.skipped[0]["type"] == "Recompensa de staking"


def test_a_share_statement_is_never_read_as_coins():
    shares = (
        "Fecha;Valor;Operación;Títulos;Precio;Divisa\n"
        "02/01/2024;SOL;Compra;10;3,20;USD\n"
        "05/03/2024;AAPL;Venta;4;190,00;USD\n"
    )
    grid = llm_map.read_grid("x.csv", shares.encode())
    result = llm_map.apply_mapping(grid, llm_map.guess_mapping(grid))
    assert [tx.ticker for tx in result.transactions] == ["SOL", "AAPL"]


def test_the_model_saying_crypto_is_enough_on_its_own():
    # Coins nobody curated a name for, so the symbols cannot vote: the
    # mapping's own asset_class is what pairs them.
    csv = ("Symbol,Type,Quantity,Price,Value,Fees,Date\n"
           'CHILLGUY,Compra,"9,302.54766102",0.05€,500.00€,4.94€,8 may 2025 22:31:12\n'
           'MOODENG,Compra,"2,079.44607002",0.24€,500.00€,4.94€,12 may 2025 11:48:56\n')
    grid = llm_map.read_grid("wallet.csv", csv.encode())
    mapping = llm_map.guess_mapping(grid)
    assert [tx.ticker for tx in llm_map.apply_mapping(grid, mapping).transactions] \
        == ["CHILLGUY", "MOODENG"]
    mapping["asset_class"] = "crypto"
    assert [tx.ticker for tx in llm_map.apply_mapping(grid, mapping).transactions] \
        == ["CHILLGUY-EUR", "MOODENG-EUR"]


def test_a_dated_cell_with_a_time_in_it_is_still_a_date():
    """The old reader split on the first space and kept "3"."""
    assert llm_map._date("3 feb 2025 09:21:06", "") == "2025-02-03"
    assert llm_map._date("2025-03-04T09:12:00.000Z", "%Y-%m-%d") == "2025-03-04"


def test_an_action_the_sample_never_showed_the_model_still_maps():
    # The model only ever sees the first rows; "Venta" first appears deep in
    # the file, so its absence from action_map must not drop the row.
    grid = llm_map.read_grid("x.csv", ES_CSV.encode())
    mapping = dict(MAPPING, action_map={"compra": "buy"})
    result = llm_map.apply_mapping(grid, mapping)
    assert [tx.action for tx in result.transactions] == ["buy", "sell", "dividend"]
