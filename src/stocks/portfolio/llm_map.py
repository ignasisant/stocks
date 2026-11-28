"""Import a broker export nobody wrote a parser for, by mapping its columns.

The dedicated parsers (revolut, degiro, ibkr, …) all key off exact headers, so
an export from a broker we don't cover — or a spreadsheet the user keeps by
hand — has nowhere to go. This module fills that gap: the file is read into a
raw grid of text cells, a *sample* of it goes to the model, and what comes
back is a **mapping**, not data:

    {"header_row": 3,
     "columns": {"date": 0, "ticker": 2, "action": 4, "quantity": 5,
                 "price": 6, "amount": 9, "currency": 7, "fee": 8,
                 "note": null},
     "date_format": "%d/%m/%Y", "decimal": ",", "thousands": ".",
     "action_map": {"Compra": "buy", "Venta": "sell", "Dividendo": "dividend"}}

The mapping is then applied to every row **in Python**. That split is the
whole point: the model never transcribes a price or a date, so it cannot
hallucinate one into the ledger, and a 10-row file costs exactly as much to
map as a 2000-row one. Columns are addressed by index rather than by header
text — no fuzzy matching, and duplicate or blank headers stay unambiguous.

PDFs get the other treatment. A PDF has no regular grid to map: instrument
names wrap over two lines, the table breaks across pages, and hundreds of
cover-page and footer lines sit around it. So for PDFs the model *extracts*
the transactions themselves, a few pages per call. That is a deliberate
exception to the rule above, and the guard against a hallucinated price is the
mandatory preview: nothing an extraction produces reaches the ledger until the
user has looked at the table and pressed the button.

Either way, rows that can't be turned into a Transaction land in
``ParseResult.skipped`` with a reason, never silently dropped — the same
contract generic.py has. Semantic checks (future dates, oversells, unknown
tickers) stay in validate.py, so an LLM-read import is quarantined exactly
like a Revolut one. Nothing here writes to the ledger.
"""

from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from stocks import obs
from stocks.data import crypto
from stocks.llm import structured
from stocks.portfolio import instruments, lexicon, platforms, upload_guard
from stocks.portfolio.ledger import ACTIONS, RETURN_OF_CAPITAL, Transaction
from stocks.portfolio.statement import ParseResult

if TYPE_CHECKING:
    from stocks.llm import Provider

# What the model is shown. Enough rows to see the shape of the data (and any
# preamble above the header), few enough to stay a cheap classifier call.
SAMPLE_ROWS = 18
MAX_COLS = 30
MAX_CELL = 40
# Columns a mapping editor offers. More than the model is shown: a reader
# fixing a mapping is looking at the whole file, not at a sample of it.
MAX_EDIT_COLS = 60

# Pause before the single retry of the symbol-resolution call (see
# _resolve_symbols): long enough to clear a per-minute rate limit, short
# enough that a real outage does not hold the preview open.
RESOLVE_RETRY_SECONDS = 8

FIELDS = ("date", "ticker", "action", "quantity", "price", "amount",
          "currency", "fee", "note")
_REQUIRED = ("date", "ticker", "action")

# Tried in order when the model's date_format doesn't parse a cell — brokers
# mix these freely and one bad guess must not reject the whole file. Anything
# these miss goes to lexicon.iso_date, which also reads the month names the
# file's own language spells ("3 abr 2025").
_DATE_FALLBACKS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y/%m/%d", "%d %b %Y", "%d-%b-%Y",
)

# Everything that is decoration around a number: currency symbols and codes,
# spaces (including the non-breaking kind Excel exports love), quotes.
_MONEY_JUNK = re.compile(r"[^\d,.\-+()]")

# What a document turned out to be. "positions" matters on its own: a
# portfolio report lists what you hold right now with no dated buys or sells,
# so there is genuinely nothing to import, and saying so beats "unreadable".
KIND_TRADES = "trades"
KIND_POSITIONS = "positions"
KIND_NONE = "none"

# PDF extraction budget. Pages are batched up to this many characters per
# call (~3k tokens of statement text), and no document costs more than
# MAX_PDF_CALLS calls however long it is — the tail is reported, not dropped.
PDF_CHARS_PER_CALL = 12_000
MAX_PDF_CALLS = 8


class ProviderUnavailable(Exception):
    """The model could not be reached.

    Kept apart from every other failure on purpose: "the assistant is down"
    and "this file makes no sense" look identical in a ParseResult, and
    telling the user to fix their export when the real problem is a dead API
    key sends them off to do the wrong work.
    """


def _ask(provider: Provider, api_key: str, fn: str, system: str,
         content: str) -> str:
    """The raw reply to BAML function `fn` (llm/structured.py renders it)."""
    system, messages = structured.render(fn, system, content)
    return _send(provider, api_key, system, messages[0]["content"])


def _send(provider: Provider, api_key: str, system: str, content: str) -> str:
    """One call with a prompt that is already complete."""
    try:
        return provider.complete(
            api_key, _model(provider), system,
            [{"role": "user", "content": content}],
        )
    except Exception as exc:
        raise ProviderUnavailable(str(exc)) from exc


def _model(provider: Provider) -> str:
    return provider.classifier_model or provider.default_model


def _replying(provider: Provider):
    """Binds the provider for the off-contract log of the reply parsed inside."""
    return obs.context(provider=getattr(provider, "id", ""), model=_model(provider))


@dataclass(frozen=True)
class Extraction:
    """What came out of a file, and what the file turned out to be."""

    result: ParseResult = field(default_factory=ParseResult)
    kind: str = KIND_NONE
    unavailable: bool = False  # the model never answered; the file is unjudged
    # The mapping the rows were read with, and the file's columns as a reader
    # would name them (`columns`) — what a mapping editor shows and sends back.
    # Absent for a PDF, which is extracted rather than mapped.
    mapping: dict | None = None
    columns: tuple[str, ...] = ()
    # Who the file turned out to be from ("Binance"), when it was read as a
    # crypto export (crypto_map); empty otherwise.
    label: str = ""
    # A holdings snapshot's lines (`holdings_rows`): what is held, undated.
    holdings: tuple[dict, ...] = ()


# --------------------------------------------------------------- file to grid


def _cells(row) -> list[str]:
    out = []
    for c in row:
        if c is None:
            out.append("")
        else:
            text = str(c).strip()
            out.append("" if text.lower() in ("nan", "nat", "none") else text)
    return out


# Bytes that open a file in a format other than text. A bank's "Excel" export
# is as often an HTML table or a tab-separated text file named .xls as it is
# a workbook, so the format is read off the bytes, never off the name alone.
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .xls (BIFF)
_HTML = re.compile(
    rb"^\s*(<!doctype html|<html|<\?xml[^>]*>\s*<html|<table|<meta|<head|<body)",
    re.I)


def _decode(data: bytes) -> str:
    """The text of a CSV, whatever its encoding.

    Excel's "Unicode text" is UTF-16 with tabs; Spanish banks still write
    Windows-1252, where latin-1 would turn "€" into a control character.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    head = data[:400]
    if head and head.count(b"\x00") > len(head) // 4:
        # UTF-16 that lost its byte-order mark: every other byte is a zero.
        odd = head[1::2].count(b"\x00") >= head[0::2].count(b"\x00")
        return data.decode("utf-16-le" if odd else "utf-16-be", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _delimiter(lines: list[str]) -> str:
    """The separator that cuts the most lines into the same number of cells.

    `csv.Sniffer` picks the most frequent character, which in a semicolon file
    of European numbers is the comma inside "1.234,56", and a preamble above
    the table throws it off altogether. A table is the run of lines that agree
    on a width, so the delimiter is the one that makes the most of them agree.
    """
    best, best_score = ",", (0, 0)
    for delimiter in ",;\t|":
        widths: dict[int, int] = {}
        for row in csv.reader(lines, delimiter=delimiter):
            if len(row) > 1:
                widths[len(row)] = widths.get(len(row), 0) + 1
        if not widths:
            continue
        width = max(widths, key=lambda w: (widths[w], w))
        score = (widths[width], width)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _read_csv(data: bytes) -> list[list[str]]:
    text = _decode(data).replace("\x00", "")
    lines = text.splitlines()
    # Excel's own hint on the first line ("sep=;") names the delimiter.
    hint = re.match(r"^\ufeff?\"?sep=(.)\"?\s*$", lines[0], re.I) if lines else None
    if hint:
        text = "\n".join(lines[1:])
        delimiter = hint.group(1)
    else:
        delimiter = _delimiter([line for line in lines[:200] if line.strip()])
    return [_cells(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _read_html(data: bytes) -> list[list[str]]:
    """Every table row of an HTML page — the "Excel" many banks export."""
    from lxml import html

    head = data[:4096].lower()
    if b"charset" not in head and b"encoding=" not in head:
        # Undeclared, lxml reads bytes as latin-1 and "Títulos" stops naming
        # the quantity; decode it as a CSV would be.
        doc = html.fromstring(_decode(data))
    else:
        doc = html.fromstring(data)
    return [_cells(" ".join(cell.text_content().split())
                   for cell in row.xpath("./td|./th"))
            for row in doc.iter("tr")]


def _table_score(grid: list[list[str]]) -> tuple[int, int]:
    """How much a sheet looks like the table to import: the most column names
    one row carries, then how many rows it has."""
    named = max((sum(1 for c in row if _header_field(c)) for row in grid[:_HEADER_SCAN]),
                default=0)
    return named, len(grid)


def _read_excel(data: bytes) -> list[list[str]]:
    """The workbook sheet that holds the table.

    A broker's workbook often opens on a summary ("Resumen", "Overview") and
    keeps the movements on the next sheet; reading only the first one found
    nothing to import in a file that holds everything.
    """
    import pandas as pd

    upload_guard.check(data)
    # openpyxl for .xlsx (pandas' default); calamine for what it cannot open:
    # legacy BIFF .xls and OpenDocument .ods.
    calamine = (data.startswith(_OLE2)
                or b"application/vnd.oasis.opendocument" in data[:200])
    engine = "calamine" if calamine else "openpyxl"
    sheets = pd.read_excel(io.BytesIO(data), header=None, dtype=str,
                           sheet_name=None, engine=engine)
    grids = [[_cells(r) for r in frame.itertuples(index=False, name=None)]
             for frame in sheets.values()]
    grids = [[r for r in g if any(r)] for g in grids]
    return max(grids, key=_table_score, default=[])


def _words_grid(page, ytol: float = 3.0, xgap: float = 6.0) -> list[list[str]]:
    """Rows rebuilt from where the words sit on the page.

    Words sharing a baseline (within ytol points) form a row; a horizontal gap
    wider than xgap starts a new cell. This is the only way to read the many
    statement PDFs that *position* their text instead of drawing a table grid
    — pdfplumber's table finder needs ruling lines and returns nothing at all
    for those, so without this they extract as an empty file.

    Text wrapped over two lines inside one visual row (a long instrument name)
    lands on its own row here; the mapping downstream skips such rows with a
    reason rather than mangling them.
    """
    lines: dict[int, list] = {}
    for word in page.extract_words():
        lines.setdefault(round(word["top"] / ytol), []).append(word)

    grid = []
    for key in sorted(lines):
        cells: list[str] = []
        current: list[str] = []
        prev_right = None
        for word in sorted(lines[key], key=lambda w: w["x0"]):
            if prev_right is not None and word["x0"] - prev_right > xgap:
                cells.append(" ".join(current))
                current = []
            current.append(word["text"])
            prev_right = word["x1"]
        if current:
            cells.append(" ".join(current))
        grid.append(cells)
    return grid


def _read_pdf(data: bytes) -> list[list[str]]:
    """The PDF's transaction table, however it is drawn.

    Ruled tables are preferred: the widest one is kept and stacked across
    pages (a statement's table breaks over pages, while tables of a different
    column count are page furniture — headers, summary boxes). A PDF with no
    ruling lines at all falls back to reading word positions.
    """
    import pdfplumber

    tables: list[list[list[str]]] = []
    positioned: list[list[str]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in upload_guard.pages(pdf):
            found = page.extract_tables() or []
            # pdfplumber leaves an empty cell as None; downstream reads strings.
            tables.extend([[c or "" for c in row] for row in t] for t in found)
            if not found:
                positioned.extend(_words_grid(page))
    if not tables:
        return [_cells(r) for r in positioned]
    widths: dict[int, int] = {}
    for t in tables:
        for row in t:
            widths[len(row)] = widths.get(len(row), 0) + 1
    best = max(widths, key=lambda w: (widths[w] * w, w))
    return [_cells(r) for t in tables for r in t if len(r) == best]


def read_grid(filename: str, data: bytes) -> list[list[str]]:
    """The file as raw text cells, header row not yet assumed.

    Empty when the format isn't readable here or the file has no table at all;
    the caller turns that into a skip reason rather than an exception.
    """
    name = filename.lower()
    try:
        if data.startswith(b"%PDF") or (name.endswith(".pdf")
                                         and not data.startswith(b"PK")):
            grid = _read_pdf(data)
        elif data.startswith((b"PK\x03\x04", _OLE2)):
            grid = _read_excel(data)
        elif _HTML.match(data[:2048]):
            grid = _read_html(data)
        elif name.endswith((".xlsx", ".xlsm")):
            grid = _read_excel(data)
        else:
            grid = _read_csv(data)
    except Exception:
        return []
    return [r for r in grid if any(c for c in r)]  # drop blank lines


# ------------------------------------------------------------------- mapping


def sample(grid: list[list[str]]) -> str:
    """The first rows, indexed, as the model sees them."""
    lines = []
    for i, row in enumerate(grid[:SAMPLE_ROWS]):
        cells = [c[:MAX_CELL] for c in row[:MAX_COLS]]
        lines.append(f"row {i}: " + " | ".join(cells))
    return "\n".join(lines)


# The reply's shape is BAML's (MapColumns in baml_src/import.baml), appended
# after this by structured.render.
_SYSTEM = """You map a broker's transaction export onto a fixed ledger schema.
You are shown the first rows of the file, each cell separated by " | " and
numbered by row and (implicitly) by column, starting at 0.

Rules:
- Column indexes are 0-based positions in the " | " list, NOT header names.
- Required: date, ticker, action. If the file has no column that identifies
  the security, or no column that says what happened, set "columns" to null.
- "ticker": the symbol column. Failing that, the ISIN column, failing that
  the instrument-name column — a name is resolved to its symbol later. Never
  an id column (position id, transaction id, order reference).
- "price" is the per-share price column, "amount" the row's total cash column
  — the one that is negative for a purchase and positive for a sale or a
  dividend. Many exports carry both: map both. Never map one column to the
  other's name, and leave "amount" null when the file has no total column.
- For a split, "quantity" is the ratio.
- "capital" is a return of capital: a payment the issuer makes out of
  capital rather than profit (devolución de prima de emisión), never an
  ordinary dividend.
- "action_map" needs one entry per distinct value you can see in the action
  column, including the ones you would ignore — map those to the closest of
  buy/sell/dividend/fee/split/capital, and leave out only values
  that are clearly not transactions (cash top-ups, transfers, balance
  lines).
- When that column is a sentence that differs in every row ("YOU BOUGHT
  PROSHARES ULTRAPRO QQQ (TQQQ) (Cash)"), key the map on the phrase that
  names the action ("you bought"), never on the whole sentence.
- "asset_class" is "crypto" when the symbol column holds coin codes (BTC,
  ETH, SOL) from an exchange or wallet export, "securities" for shares,
  ETFs, funds and bonds. Coin codes collide with real tickers — SOL is a
  US-listed company — so this is what stops a coin importing as a share.
- Never invent values from the sample rows; you are only naming columns.
"""


def _index(value, width: int) -> int | None:
    """A column index from the model, or None when it isn't usable."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None
    return i if 0 <= i < width else None


def parse_mapping(raw: str, grid: list[list[str]]) -> dict | None:
    """A validated mapping out of the model's reply, or None.

    None means "this file can't be mapped" — a missing required column, an
    out-of-range index, a reply that is not the mapping at all. The caller
    reports that rather than importing a half-understood file.
    """
    try:
        data = structured.parse(raw, "MapColumns")
    except structured.OffContract:
        return None
    return _mapping_from(data, grid)


def _mapping_from(data: dict, grid: list[list[str]]) -> dict | None:
    """`parse_mapping` for a mapping that is already data — the model's
    parsed reply, or the one a reader edited and sent back."""
    if not isinstance(data, dict) or not isinstance(data.get("columns"), dict):
        return None

    width = max((len(r) for r in grid), default=0)
    header_row = _index(data.get("header_row"), len(grid))
    columns = {
        f: _index(data["columns"].get(f), width) for f in FIELDS
    }
    debit = _index(data.get("debit"), width)
    credit = _index(data.get("credit"), width)
    sentence = bool(data.get("sentence"))
    if columns["date"] is None or (columns["ticker"] is None and not sentence):
        return None
    # A file with no type column still says which way each row went — by the
    # sign of its quantity or its money, or by which of a bank's debit and
    # credit columns is filled — so the action column is required only when
    # nothing else could stand in for it.
    if columns["action"] is None and not (
            columns["quantity"] is not None or columns["amount"] is not None
            or debit is not None or credit is not None):
        return None

    actions = {}
    for key, value in (data.get("action_map") or {}).items():
        value = str(value).strip().lower()
        if value in ACTIONS:
            actions[str(key).strip().lower()] = value

    decimal = str(data.get("decimal") or ".")[:1] or "."
    thousands = str(data.get("thousands") or "")[:1]
    asset_class = str(data.get("asset_class") or "").strip().lower()
    return {
        "header_row": 0 if header_row is None else header_row,
        "columns": columns,
        "date_format": str(data.get("date_format") or "").strip(),
        "decimal": decimal,
        # A separator that is also the decimal point would eat the decimals.
        "thousands": "" if thousands == decimal else thousands,
        "action_map": actions,
        "asset_class": asset_class if asset_class in ("crypto", "securities") else "",
        "debit": debit,
        "credit": credit,
        "dayfirst": (data.get("dayfirst")
                     if isinstance(data.get("dayfirst"), bool) else None),
        "pence": bool(data.get("pence")),
        "sentence": sentence,
        "isin": _index(data.get("isin"), width),
    }


# ------------------------------------------------- mapping without a model

# Header name -> field, in the languages brokers export in. Matched against
# the header cell with its accents stripped, exactly first and then as a
# substring, so "Fecha de operación" and "Precio unitario" both land.
#
# This is not a better version of the model call: it is the version that
# still works when the model is rate-limited, out of credit or simply wrong,
# and it is deliberately dumb enough to be predictable.
_HEADER_WORDS: dict[str, tuple[str, ...]] = {
    "date": ("date", "fecha", "data", "datum", "fecha valor", "trade date",
             "completed date", "settlement date", "timestamp", "fecha hora",
             "dia", "day", "run date", "date d", "data do negocio",
             "buchungstag", "handelstag", "schlusstag", "valuta", "time",
             "transaction date", "execution date", "booking date",
             "value date", "operation date", "trade time", "order date"),
    "ticker": ("symbol", "simbolo", "ticker", "asset", "activo", "isin",
               "instrument", "instrumento", "valor", "producto", "product",
               "security", "criptomoneda", "coin", "titulo", "titolo",
               "wertpapier", "libelle", "epic", "codigo", "code", "pair",
               "stock", "fondo", "fund", "emisora", "nome", "nom du titre",
               "denominacion", "descripcion del valor", "wkn", "share"),
    "action": ("type", "tipo", "action", "accion", "operacion", "operation",
               "transaction type", "movimiento", "side", "sentido",
               "concepto", "transaccion", "transaktion", "sens", "segno",
               "activity", "buy/sell", "buy sell", "b/s", "direction",
               "operazione", "richtung", "art", "tipo de movimentacao",
               "transaction"),
    "quantity": ("quantity", "cantidad", "qty", "shares", "titulos",
                 "participaciones", "unidades", "volumen", "volume", "units",
                 "num titulos", "numero de titulos", "stuck", "stueck",
                 "anzahl", "quantite", "quantita", "quantidade", "nominal",
                 "nominale", "aantal", "titres", "acciones", "executed",
                 "filled", "menge", "pezzi"),
    "price": ("price", "precio", "price per share", "price per coin",
              "precio unitario", "cotizacion", "kurs", "prezzo", "cours",
              "unit price", "valor liquidativo", "nav", "net asset value",
              "preco", "ausfuhrungskurs", "cambio", "prix", "koers", "each",
              "per unit", "per share", "unit"),
    "amount": ("value", "total", "importe", "total amount", "gross amount",
               "valor total", "importe total", "efectivo", "contravalor",
               "montant", "betrag", "amount", "controvalore", "consideration",
               "net amount", "proceeds", "valor da operacao", "importo",
               "bedrag", "kurswert"),
    "fee": ("fee", "fees", "comision", "comisiones", "commission",
            "corretaje", "gastos", "costes", "gebuhr", "frais", "tarifa",
            "charges", "commissioni", "spese", "provision", "entgelt",
            "kosten", "taxa", "corretagem"),
    "currency": ("currency", "divisa", "moneda", "ccy", "currency code",
                 "wahrung", "devise", "valuta", "moeda", "waehrung"),
    # Columns that look like one of the above but are not: "Asset type" is
    # not the asset, "Order type" not the side. Naming them keeps them out.
    "_skip": ("asset type", "asset class", "security type", "tipo de activo",
              "tipo de producto", "product type", "order type",
              "tipo de orden", "account type", "mercado", "market", "bolsa",
              "exchange", "venue", "order id", "reference", "referencia",
              "status", "estado", "account", "cuenta"),
    "note": ("note", "notes", "nota", "descripcion", "description",
             "detalle", "comentario", "bemerkung", "commento", "remarque"),
}

# Debit and credit columns: a bank's way of saying which way the money went,
# and with it the direction of a row that has no type column at all.
_DEBIT_WORDS = ("cargo", "cargos", "debe", "debit", "debito", "soll",
                "addebito", "uscite", "salida", "withdrawal", "paid out",
                "money out")
_CREDIT_WORDS = ("abono", "abonos", "haber", "credit", "credito", "haben",
                 "accredito", "entrate", "entrada", "deposit", "paid in",
                 "money in")

# Rows of the file searched for the header row: a bank's statement can open
# with a page of account details and legal text before its table starts.
_HEADER_SCAN = 60


# European and US number shapes, told apart by which separator comes last.
_EU_NUMBER = re.compile(r"^\d{1,3}(\.\d{3})*,\d+$")
_US_NUMBER = re.compile(r"^\d{1,3}(,\d{3})*\.\d+$")

# A symbol column's cells: short, no spaces, not a number. Loose on purpose —
# it only has to beat the other columns of the same file.
_SYMBOLISH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-:_]{0,11}$")

# Rows of the file read when guessing by content rather than by header.
_SNIFF_ROWS = 40


def _header_text(cell: str) -> str:
    return " ".join(lexicon.plain(cell).replace(".", " ").replace("_", " ").split())


def _word_at(text: str, word: str) -> int:
    """Where `word` starts a word inside `text`, or -1."""
    found = re.search(rf"(?<![a-z0-9]){re.escape(word)}", text)
    return found.start() if found else -1


def _header_field(cell: str) -> str | None:
    """The field a header cell names, or None.

    An exact name wins. Otherwise the word the header *opens* with does —
    "Date d'opération" is a date, not an operation; "Valor liquidativo" a
    price, not a security — and of words starting at the same place, the
    longest. Words match at the start of a word only, so "data" never fires
    inside "validated".
    """
    text = _header_text(cell)
    if not text or len(text) > 60:
        return None
    for name, words in _HEADER_WORDS.items():
        if text in words:
            return name
    best: tuple[int, int, str] | None = None
    for name, words in _HEADER_WORDS.items():
        for word in words:
            at = _word_at(text, word)
            if at >= 0 and (best is None or (at, -len(word)) < best[:2]):
                best = (at, -len(word), name)
    return best[2] if best else None


def _guess_header_row(grid: list[list[str]]) -> int:
    """The row that names the columns: the one most of whose cells are names.

    A preamble line ("Extracto de operaciones") names nothing, and a data row
    names at most a column or two by accident, so the real header wins on
    count. Ties go to the earliest row, and a file whose header this cannot
    see is read as starting at row 0 — the same assumption the model's
    mapping falls back on.
    """
    best, best_score = 0, 0
    for index, row in enumerate(grid[:_HEADER_SCAN]):
        if sum(1 for cell in row if cell.strip()) < 2:
            continue  # a title line ("Mis operaciones") names no columns
        score = len({_header_field(cell) for cell in row} - {None})
        if score > best_score:
            best, best_score = index, score
    return best


def _column_scores(rows: list[list[str]], width: int, test) -> list[int]:
    return [sum(1 for row in rows if i < len(row) and test(row[i]))
            for i in range(width)]


def _best_column(rows: list[list[str]], width: int, test,
                 taken: set[int]) -> int | None:
    """The column whose cells pass `test` most often, if any does at all."""
    scores = _column_scores(rows, width, test)
    ranked = sorted(
        (i for i in range(width) if i not in taken and scores[i]),
        key=lambda i: -scores[i],
    )
    if not ranked:
        return None
    # Half the sampled rows, so a stray date inside a note column never wins.
    return ranked[0] if scores[ranked[0]] >= max(1, len(rows) // 2) else None


def _sniff_separators(
    rows: list[list[str]], indexes: list[int | None]
) -> tuple[str, str]:
    """(decimal, thousands) as this file writes its numbers.

    `None` is an ordinary entry, not an accident: the caller passes the four
    numeric columns it mapped, and a file with no fee column maps that one to
    nothing. Skipped below rather than filtered by the caller, so the set of
    columns sniffed stays the set the mapping named.
    """
    european = american = 0
    for row in rows:
        for i in indexes:
            if i is None or i >= len(row):
                continue
            cell = _MONEY_JUNK.sub("", row[i]).strip("()+-")
            if _EU_NUMBER.match(cell):
                european += 1
            elif _US_NUMBER.match(cell):
                american += 1
    if european > american:
        return ",", "."
    if american > european:
        return ".", ","
    return ".", ""


# Headers that name a code rather than a name: a symbol column under one of
# these is the ticker even when the file also prints the ISIN.
_CODE_HEADERS = ("symbol", "simbolo", "ticker", "epic", "codigo", "code",
                 "pair", "coin", "criptomoneda", "trading symbol")


def _data_rows(grid: list[list[str]], header_row: int, limit: int | None = None
               ) -> list[list[str]]:
    """The rows under the header that can be a transaction: a title, a page
    number or a repeat of the header itself (a PDF prints it on every page)
    is not one."""
    header = [c.strip().lower() for c in grid[header_row]] if grid else []
    out = []
    for row in grid[header_row + 1:]:
        if sum(1 for c in row if c.strip()) < 2:
            continue
        if [c.strip().lower() for c in row] == header:
            continue
        out.append(row)
        if limit and len(out) >= limit:
            break
    return out


# A type column that writes one letter: A/V (acquisto/vendita), C/V (compra/
# venta), K/V (Kauf/Verkauf), B/S. Read only when the whole column is letters,
# so a stray "A" in some other column means nothing.
_LETTER_ACTIONS = {"a": "buy", "b": "buy", "c": "buy", "k": "buy",
                   "s": "sell", "v": "sell"}

# What a spreadsheet stores a date as when the cell lost its date format:
# days since 1899-12-30. The range is 1954–2119, so a share count or a price
# is never mistaken for one — and serials are read only in a column whose
# header already said "date".
_SERIAL = re.compile(r"^\d{5}(\.0+)?$")


def _excel_serial(text: str) -> str | None:
    text = (text or "").strip()
    if not _SERIAL.match(text):
        return None
    days = int(float(text))
    if not 20_000 <= days <= 80_000:
        return None
    return (date(1899, 12, 30) + timedelta(days=days)).isoformat()


_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")


def _day_order(cells: list[str]) -> bool | None:
    """True when the file writes day/month, False for month/day, None when
    none of its dates says.

    Decided once for the whole column: "01/02/2024" is ambiguous on its own,
    but the same file's "12/20/2024" is not, and every row has to be read the
    same way.
    """
    dayfirst = monthfirst = 0
    for cell in cells:
        m = _NUMERIC_DATE.match(cell or "")
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            dayfirst += 1
        elif b > 12 >= a:
            monthfirst += 1
    if dayfirst == monthfirst:
        return None
    return dayfirst > monthfirst


def _is_isin(text: str) -> bool:
    return bool(_ISIN_CELL.match(text.strip().upper()))


def _is_symbol(text: str) -> bool:
    """A cell that reads as a ticker: one short word, not a number, a date,
    an ISIN, a currency code or a verb."""
    text = text.strip()
    return (bool(_SYMBOLISH.match(text)) and not _is_isin(text)
            and _number(text, ".", ",") is None
            and lexicon.readable_date(text) is None
            and lexicon.action_of(text) is None
            and not (len(text) == 3 and lexicon.currency_of(text) == text.upper()))


def _symbol_tier(rows: list[list[str]], index: int) -> int:
    """How good a column is as the instrument: 3 tickers, 2 ISINs, 1 names,
    0 not an instrument at all (numbers, dates, nothing)."""
    values = [row[index].strip() for row in rows
              if index < len(row) and row[index].strip()]
    if not values:
        return 0
    need = 0.8 * len(values)
    if sum(1 for v in values if _is_symbol(v)) >= need:
        return 3
    if sum(1 for v in values if _is_isin(v)) >= need:
        return 2
    if sum(1 for v in values if _number(v, ".", ",") is None
           and lexicon.readable_date(v) is None) >= need:
        return 1
    return 0


def _money_word_at(cell: str, words: tuple[str, ...]) -> bool:
    text = _header_text(cell)
    return any(text == w or _word_at(text, w) == 0 for w in words)


# One sentence per row, as someone keeping their own list writes it: "Compré
# 10 AAPL a 125,07 USD", "sold 5 MSFT @ 410". Verb, count, symbol, price.
_SENTENCE = re.compile(
    r"^\s*(?P<verb>[^\d]+?)\s+(?P<qty>\d[\d.,]*)\s+(?:(?:acciones|shares|titulos|"
    r"participaciones|units|x)\s+(?:de\s+|of\s+)?)?(?P<symbol>[A-Za-z][A-Za-z0-9.\-]{0,11})"
    r"\s+(?:a|at|@|à|zu|por|for|à)\s+(?P<price>\d[\d.,]*)\s*(?P<ccy>[A-Za-z]{3}|[$€£])?",
    re.IGNORECASE,
)


def _has_sell_sign(rows: list[list[str]], indexes: list[int | None],
                   decimal: str, thousands: str) -> bool:
    """Whether any money or quantity cell is negative: the only way a file
    with no type column tells a sale from a purchase."""
    for row in rows:
        for i in indexes:
            if i is None or i >= len(row):
                continue
            cell = row[i].strip()
            value = _number(cell, decimal, thousands)
            if value is not None and (value < 0 or cell.startswith("(")):
                return True
    return False


def guess_mapping(grid: list[list[str]]) -> dict | None:
    """A mapping worked out from the file alone, or None.

    Headers first, then the cells themselves: a column whose values parse as
    dates is the date column whatever it is called, and one whose values are
    words lexicon.py knows is the action column. That content check is what
    carries a file whose headers are in a language, or an abbreviation, the
    table above never listed.

    A file with no type column at all is still read when something else says
    which way each row went: a bank's debit and credit columns, or the sign
    of its quantity or money. A file that writes each operation as one
    sentence ("Compré 10 AAPL a 125 USD") is read from the sentence.
    """
    if len(grid) < 2:
        return None
    header_row = _guess_header_row(grid)
    width = max((len(row) for row in grid), default=0)
    rows = _data_rows(grid, header_row, _SNIFF_ROWS)
    if not rows or not width:
        return None

    header = grid[header_row][:width]
    fields = [_header_field(cell) for cell in header]
    if sum(1 for cell in header if cell.strip()) < 2:
        fields = [None] * len(header)  # a title, not a header: cells decide
    columns: dict[str, int | None] = {name: None for name in FIELDS}
    named_tickers: list[int] = []
    for index, name in enumerate(fields):
        if name == "ticker":
            named_tickers.append(index)
        elif name in columns and columns[name] is None:
            columns[name] = index

    # Of every column the header calls the instrument, the one that holds
    # tickers beats ISINs beats names; one that holds money ("Valor") is the
    # amount, if the file named no other.
    tiers = {i: _symbol_tier(rows, i) for i in named_tickers}
    if any(t == 2 for t in tiers.values()):
        # Beside an ISIN, a column headed "Valor" or "Libellé" holds names,
        # some of which happen to be one short word (LVMH, ENEL). The ISIN is
        # the one that names the line exactly; only a column the header
        # calls a code ("Symbol", "Ticker", "EPIC") outranks it.
        for i in named_tickers:
            if tiers[i] == 3 and not any(
                    _word_at(_header_text(header[i]), w) == 0 for w in _CODE_HEADERS):
                tiers[i] = 1
    best = max(named_tickers, key=lambda i: (tiers[i], -i), default=None)
    isin = next((i for i in named_tickers if tiers[i] == 2 and i != best), None)
    if best is not None and tiers[best]:
        columns["ticker"] = best
    for i in named_tickers:
        if i != best and columns["amount"] is None and sum(
                1 for r in rows if i < len(r) and _number(r[i], ",", ".") is not None
        ) >= max(1, len(rows) // 2):
            columns["amount"] = i

    debit = next((i for i, c in enumerate(header)
                  if _money_word_at(c, _DEBIT_WORDS)), None)
    credit = next((i for i, c in enumerate(header)
                   if _money_word_at(c, _CREDIT_WORDS) and i != debit), None)

    taken = {i for i in columns.values() if i is not None}
    taken |= {i for i, f in enumerate(fields) if f is not None}
    taken |= {i for i in (debit, credit) if i is not None}

    def adopt(name: str, test, among: set[int] | None = None) -> None:
        index = columns[name]
        if index is not None:
            hits = _column_scores(rows, width, test)[index]
            if hits >= max(1, len(rows) // 2):
                return  # the header was right about it
            taken.discard(index)
        found = _best_column(rows, width, test, taken - (among or set()))
        if found is not None:
            columns[name] = found
            taken.add(found)
        elif index is not None and not _column_scores(rows, width, test)[index]:
            columns[name] = None  # the header named it; not one cell agreed

    date_format = ""
    named_date = columns["date"]
    if named_date is not None and sum(
            1 for r in rows if named_date < len(r) and _excel_serial(r[named_date])
    ) >= max(1, len(rows) // 2):
        date_format = "excel"
    else:
        adopt("date", lambda cell: lexicon.readable_date(cell) is not None)

    letters: dict[str, str] = {}
    named_action = columns["action"]
    if named_action is not None:
        cells = {r[named_action].strip().lower() for r in rows
                 if named_action < len(r) and r[named_action].strip()}
        if cells and cells <= set(_LETTER_ACTIONS):
            letters = {c: _LETTER_ACTIONS[c] for c in cells}
    if not letters:
        # A description column can carry the verb ("YOU BOUGHT …"), so it is
        # searched even though its header called it a note.
        note = {columns["note"]} if columns["note"] is not None else set()
        adopt("action", lambda cell: lexicon.action_of(cell) is not None, note)
        if columns["action"] is not None and columns["action"] == columns["note"]:
            columns["note"] = None

    sentence = False
    if columns["ticker"] is None:
        columns["ticker"] = _best_column(rows, width, _is_symbol, taken)
    if columns["ticker"] is None and columns["action"] is not None:
        i = columns["action"]
        said = sum(1 for r in rows if i < len(r) and _SENTENCE.match(r[i]))
        if said >= max(1, len(rows) // 2):
            sentence = True
    if columns["ticker"] is None and named_tickers and not sentence:
        columns["ticker"] = best
    if columns["date"] is None or (columns["ticker"] is None and not sentence):
        return None
    if columns["action"] is None and not (
            columns["quantity"] is not None or columns["amount"] is not None
            or debit is not None or credit is not None):
        return None

    decimal, thousands = _sniff_separators(
        rows, [columns[f] for f in ("price", "amount", "quantity", "fee")]
        + [debit, credit])
    if (columns["action"] is None and not sentence and debit is None
            and credit is None and _symbol_tier(rows, columns["ticker"]) != 2
            and not _has_sell_sign(
                rows, [columns["quantity"], columns["amount"]], decimal, thousands)):
        # No column says what happened and no sign says which way: every row
        # would be booked a buy, unless an ISIN names each line outright. A shipping or order list has a date, a name,
        # a count and a price too; a statement says what each row was.
        return None
    date_cells = [r[columns["date"]] for r in _data_rows(grid, header_row)
                  if columns["date"] < len(r)]
    price_head = header[columns["price"]] if columns["price"] is not None else ""
    return {
        "header_row": header_row,
        "columns": columns,
        "date_format": date_format,  # lexicon reads the cells otherwise
        "decimal": decimal,
        "thousands": thousands,
        "action_map": letters,  # lexicon's vocabulary covers words
        "asset_class": "",  # decided from the symbols themselves
        "debit": debit,
        "credit": credit,
        "dayfirst": _day_order(date_cells),
        "pence": bool(re.search(r"\((p|pence|gbx|gbp?ence)\)|\bpence\b|\bgbx\b",
                                price_head, re.IGNORECASE)),
        "sentence": sentence,
        "isin": isin if isin != columns["ticker"] else None,
    }


def holdings_only(grid: list[list[str]]) -> bool:
    """Whether the file is a holdings snapshot: what is held, never when or how.

    A column of symbols and one of quantities, and nothing that dates a row or
    names a buy or a sell — not in the header and not in the cells, which is
    what `guess_mapping` would have found them by. Such a file has nothing to
    import, and saying "this is a portfolio report" beats handing it to a
    parser that lists every line as an unrecognised type (prod 10-31, a
    hand-made holdings CSV read under a preselected Revolut).
    """
    if len(grid) < 2:
        return False
    header_row = _guess_header_row(grid)
    named = {_header_field(cell) for cell in grid[header_row]}
    if not {"ticker", "quantity"} <= named or named & {"date", "action"}:
        return False
    width = max((len(row) for row in grid), default=0)
    rows = [r for r in grid[header_row + 1:header_row + 1 + _SNIFF_ROWS] if any(r)]
    if not rows:
        return False
    return all(
        _best_column(rows, width, test, set()) is None
        for test in (lambda cell: lexicon.readable_date(cell) is not None,
                     lambda cell: lexicon.action_of(cell) is not None)
    )


# A holdings report prints today's price beside what was paid, so only a header
# that says "average" or "cost" is the reader's own price: per share, or the
# position's total.
_UNIT_COST = ("average", "avg", "medio", "media", "pmc", "pmp", "unit cost",
              "coste unitario", "cost per share")
_TOTAL_COST = ("cost basis", "coste total", "costo total", "total cost",
               "invested", "invertido", "coste de adquisicion", "book cost")
_ISIN_CELL = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_CODE_CELL = re.compile(r"^[A-Za-z]{3}$")


def holdings_rows(grid: list[list[str]]) -> list[dict]:
    """A holdings snapshot's lines: {row, ticker, quantity, currency, cost}.

    `ticker` is the symbol when the file prints one beside the ISIN — the
    symbol is what prices. `cost` is the average price paid per share when a
    column says so, else None: a bare "Price" in a holdings report is today's
    quote, and offering it as what was paid would date every buy to this week.
    """
    if len(grid) < 2:
        return []
    header_row = _guess_header_row(grid)
    header = grid[header_row]
    fields = [_header_field(cell) for cell in header]
    rows = [r for r in grid[header_row + 1:] if any(r)]

    def cell(row: list[str], index: int | None) -> str:
        return row[index].strip() if index is not None and index < len(row) else ""

    sample = rows[:_SNIFF_ROWS]

    def is_isin(text: str) -> bool:
        return bool(_ISIN_CELL.match(text.upper()))

    def is_symbol(text: str) -> bool:
        return (bool(_SYMBOLISH.match(text)) and not is_isin(text)
                and _number(text, ".", ",") is None
                and lexicon.readable_date(text) is None)

    def share(index: int, test) -> int:
        return sum(1 for r in sample if test(cell(r, index)))

    quantity = next((i for i, f in enumerate(fields) if f == "quantity"), None)
    currency = next((i for i, f in enumerate(fields) if f == "currency"), None)
    # "Valor" names a security and a value alike, so a named column still has
    # to hold codes; the cells decide when none of them does.
    named = [i for i, f in enumerate(fields) if f == "ticker"]
    ticker = max(named, key=lambda i: share(i, is_symbol), default=None)
    if ticker is None or not share(ticker, is_symbol):
        width = max((len(row) for row in sample), default=0)
        ticker = _best_column(sample, width, is_symbol,
                              {i for i in (quantity, currency) if i is not None})
    isin = max((i for i in named if i != ticker), key=lambda i: share(i, is_isin),
               default=None)
    if isin is not None and not share(isin, is_isin):
        isin = None
    if ticker is None and isin is not None:
        ticker, isin = isin, None
    if ticker is None or quantity is None:
        return []
    plain = [" ".join(lexicon.plain(c).replace("_", " ").split()) for c in header]
    unit = next((i for i, h in enumerate(plain)
                 if any(w in h for w in _UNIT_COST)), None)
    total = next((i for i, h in enumerate(plain)
                  if any(w in h for w in _TOTAL_COST)), None)
    decimal, thousands = _sniff_separators(sample, [quantity, unit, total])
    out = []
    for offset, row in enumerate(rows):
        # A name in the symbol column ("Apple") prices nothing; the ISIN does.
        code = cell(row, ticker)
        if not code or (code != code.upper() and cell(row, isin)):
            code = cell(row, isin)
        held = _number(cell(row, quantity), decimal, thousands)
        if not code or held is None or held <= 0:
            continue
        cost = _number(cell(row, unit), decimal, thousands) if unit is not None else None
        if cost is None and total is not None:
            paid = _number(cell(row, total), decimal, thousands)
            cost = paid / held if paid else None
        named_ccy = cell(row, currency)
        ccy = (named_ccy.upper() if _CODE_CELL.match(named_ccy)
               else lexicon.currency_of(named_ccy))
        out.append({
            "row": header_row + 2 + offset,
            "ticker": code.upper(),
            "isin": cell(row, isin).upper() if isin is not None else "",
            "quantity": held,
            "currency": ccy or "",
            "cost": cost if cost and cost > 0 else None,
        })
    return out


def map_columns(provider: Provider, api_key: str,
                grid: list[list[str]]) -> dict | None:
    """Ask the provider's cheapest model how this file is laid out.

    None means the model looked and could not match the columns. A model that
    could not be reached raises ProviderUnavailable instead — the two need
    different answers.
    """
    raw = _ask(provider, api_key, "MapColumns", _SYSTEM, sample(grid))
    with _replying(provider):
        return parse_mapping(raw, grid)


# ------------------------------------------------------------------ applying


def _number(text: str, decimal: str, thousands: str) -> float | None:
    """A float out of a broker's formatting, or None.

    Handles currency symbols and codes, thin/non-breaking spaces, and the
    accountancy convention of wrapping negatives in parentheses.
    """
    raw = _MONEY_JUNK.sub("", text or "")
    if not raw:
        return None
    negative = raw.startswith("-") or ("(" in raw and ")" in raw)
    raw = raw.strip("()+-")
    if thousands:
        raw = raw.replace(thousands, "")
    if decimal != ".":
        raw = raw.replace(decimal, ".")
    if raw.count(".") > 1:
        # More than one separator survived, so the thousands one was never
        # declared. A trailing group of exactly three digits is a thousands
        # group ("1.234.567"); anything else is the decimal part ("1.234.56").
        head, _, tail = raw.rpartition(".")
        raw = head.replace(".", "") + ("" if len(tail) == 3 else ".") + tail
    try:
        value = float(raw)
    except ValueError:
        return None
    return -value if negative else value


def _date(text: str, fmt: str, dayfirst: bool | None = None) -> str | None:
    """An ISO date out of a cell: the mapped format, the usual ones, then prose.

    The cell is tried whole and again without its time half. Splitting on the
    first space, as this used to, turns "3 feb 2025 09:21:06" into "3" and
    rejects every row of a file that a human reads at a glance — the date is
    not always the first word-with-no-spaces in the cell.
    """
    text = (text or "").strip()
    if not text:
        return None
    if fmt == "excel" and (serial := _excel_serial(text)):
        return serial
    if dayfirst is not None:
        # The file's own dates settled which way round it writes them; that
        # beats a declared format and the day-first fallbacks below alike.
        if found := lexicon.readable_date(text, dayfirst):
            return found
    candidates = [text]
    head = text.split("T")[0].strip()
    if head != text:
        candidates.append(head)
    for candidate in candidates:
        for pattern in ([fmt] if fmt and fmt != "excel" else []) + list(_DATE_FALLBACKS):
            try:
                return datetime.strptime(candidate, pattern).date().isoformat()
            except (ValueError, TypeError):
                continue
    # Whatever no strftime pattern caught: a timestamp with a time part, a
    # month spelled out, a locale's own month name.
    return lexicon.readable_date(text)


def _action_phrases(actions: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    """The action vocabulary as whole-word patterns, longest phrase first.

    Some brokers write the action as a sentence that is different in every
    row — Fidelity's column reads "YOU BOUGHT PROSHARES ULTRAPRO QQQ (TQQQ)
    (Cash)" — so an exact lookup matches nothing and the whole file imports as
    zero rows. The model's vocabulary is not wrong there, it is simply a
    phrase inside the sentence, so its keys are searched for as phrases too.

    Longest key first, so a broker that spells out "sell to close" alongside
    "sell" keeps the distinction. The canonical verbs come last, as the
    fallback for a row type the sample never showed the model.
    """
    ordered = sorted(actions.items(), key=lambda kv: -len(kv[0]))
    # Then every verb lexicon.py knows, in every language it knows them in:
    # the model's vocabulary comes from a sample of the file, so a type that
    # appears only on row 400 ("Venta") is not in it, and without this the
    # row is dropped as "action not recognised".
    ordered += sorted(
        ((word, action)
         for action, words in lexicon.ACTION_WORDS.items()
         for word in words),
        key=lambda kv: -len(kv[0]),
    )
    ordered += [(a, a) for a in sorted(ACTIONS)]
    return [(re.compile(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])"), value)
            for key, value in ordered if key]


def _phrase_action(text: str, phrases: list[tuple[re.Pattern, str]]) -> str:
    """The action named inside a free-text cell, or "" when none is."""
    low = lexicon.plain(text)  # accents stripped: "Comisión" matches "comision"
    for pattern, action in phrases:
        if pattern.search(low):
            return action
    return ""


# A bare coin code as an exchange writes it: BTC, SOL, CHILLGUY. Deliberately
# the same shape a stock ticker has — which is the whole problem, and why the
# decision below is taken per *file*, never per symbol.
_COIN_RE = re.compile(r"^[A-Z0-9]{2,10}$")

# How much of a file's symbol column has to be coins we recognise before the
# file is read as a crypto export. Two is the floor because a single "ETH"
# in a share portfolio is more likely Ethan Allen; the share is low because a
# real wallet export is mostly coins nobody curated a name for (MOODENG,
# CHILLGUY) sitting next to the two or three majors that anchor it.
_CRYPTO_SHARE = 0.3


_QUOTES = ("USDT", "USDC", "BUSD", "EUR", "USD", "GBP", "BTC", "ETH")


def _coin_of(label: str) -> str:
    """The coin a label names: BTC for "BTC", "BTC-EUR", "BTC/USDT" or an
    exchange's glued "BTCEUR"."""
    text = (label or "").upper().strip()
    for sep in ("-", "/", "_", " "):
        if sep in text:
            return text.split(sep)[0]
    for quote in _QUOTES:
        head = text[: -len(quote)]
        if text.endswith(quote) and head in crypto.CRYPTO_NAMES:
            return head
    return text


def _is_crypto_file(labels: list[str], declared: str) -> bool:
    """Whether this export's symbols are coins, decided once for the file.

    The model's own reading wins when it gave one — it saw the headers and
    the surrounding text. Otherwise the symbols vote: pairing SOL with EUR
    when the file is a share statement would book Solana for Emeren Group,
    and leaving a coin bare prices it as that company forever.
    """
    if declared:
        return declared == "crypto"
    distinct = {label.upper() for label in labels if label}
    if not distinct:
        return False
    known = [c for c in distinct if c in crypto.CRYPTO_NAMES]
    return len(known) >= 2 and len(known) >= _CRYPTO_SHARE * len(distinct)


def _symbol_column(grid: list[list[str]], mapping: dict) -> list[str]:
    """Every value the mapped symbol column holds, for the file-level checks."""
    index = mapping["columns"].get("ticker")
    if index is None:
        return []
    return [row[index].strip() for row in grid[mapping["header_row"] + 1:]
            if index < len(row) and row[index].strip()]


def _sniff_currency(grid: list[list[str]], mapping: dict) -> str:
    """The currency the money columns are written in, for files without one.

    Outside the US a currency column is the exception, and the only thing
    saying "1.000,00 €" is not dollars is the € itself. Defaulting to USD
    without looking books a euro statement as dollars, which every later
    conversion then compounds.
    """
    cols = mapping["columns"]
    indexes = [cols.get(f) for f in ("price", "amount", "fee")]
    for row in grid[mapping["header_row"] + 1:][:_SNIFF_ROWS]:
        for index in indexes:
            if index is None or index >= len(row):
                continue
            if found := lexicon.currency_of(row[index]):
                return found
    header = grid[mapping["header_row"]] if grid else []
    for index in indexes:
        if index is not None and index < len(header):
            marks = re.findall(r"\(([^)]*)\)", header[index])
            for mark in marks:
                if found := lexicon.currency_of(mark):
                    return found
    return ""


# ISIN country -> the currency its shares trade in at home. Fund domiciles
# (IE, LU) are left out: their share classes come in every currency.
_ISIN_CURRENCY = {
    **dict.fromkeys(("ES", "DE", "FR", "IT", "NL", "BE", "PT", "AT", "FI",
                     "GR", "SK", "SI", "EE", "LV", "LT"), "EUR"),
    "US": "USD", "GB": "GBP", "CH": "CHF", "CA": "CAD", "JP": "JPY",
    "SE": "SEK", "DK": "DKK", "NO": "NOK", "AU": "AUD", "HK": "HKD",
    "BR": "BRL", "MX": "MXN",
}

# Minor units a price can be quoted in, and the currency they are cents of.
_MINOR = {"GBX": "GBP", "GBP_PENCE": "GBP", "ZAC": "ZAR", "ILA": "ILS"}


def _row_currency(text: str, default: str) -> tuple[str, bool]:
    """(ISO currency, whether the row's money is in its minor unit)."""
    raw = (text or "").strip()
    if raw in ("GBp", "GBX", "gbx", "Gbx"):
        return "GBP", True
    code = raw.upper()
    if code in _MINOR:
        return _MINOR[code], True
    if re.fullmatch(r"[A-Za-z]{3}", raw):
        return code, False
    return (lexicon.currency_of(raw) or default)[:3], False


# A fee charged in the coin itself ("0.00005BTC"): the exchange kept part of
# what was bought, so the holding is that much smaller and no cash was paid.
_COIN_FEE = re.compile(r"^\s*[\d.,]+\s*([A-Za-z]{2,10})\s*$")


def _sentence_parts(text: str, decimal: str, thousands: str
                    ) -> tuple[str, float, float, str] | None:
    """(symbol, quantity, price, currency) out of "Compré 10 AAPL a 125 USD"."""
    m = _SENTENCE.match(text or "")
    if not m:
        return None
    qty = _number(m.group("qty"), decimal, thousands)
    price = _number(m.group("price"), decimal, thousands)
    if qty is None or price is None:
        return None
    ccy = m.group("ccy") or ""
    return (m.group("symbol").upper(), qty, price,
            lexicon.currency_of(ccy) or (ccy.upper() if len(ccy) == 3 else ""))


def apply_mapping(grid: list[list[str]], mapping: dict) -> ParseResult:
    """Turn every data row into a Transaction using the mapping. No LLM here."""
    result = ParseResult()
    cols = mapping["columns"]
    sentence = bool(mapping.get("sentence"))
    coins = (not sentence) and _is_crypto_file(
        [_coin_of(label) for label in _symbol_column(grid, mapping)],
        mapping.get("asset_class", ""))
    sniffed = _sniff_currency(grid, mapping)
    default_currency = sniffed or "USD"
    actions = mapping["action_map"]
    phrases = _action_phrases(actions)
    decimal, thousands = mapping["decimal"], mapping["thousands"]
    debit, credit = mapping.get("debit"), mapping.get("credit")
    header = [c.strip().lower() for c in grid[mapping["header_row"]]] \
        if mapping["header_row"] < len(grid) else []
    dayfirst = mapping.get("dayfirst")
    if dayfirst is None and cols.get("date") is not None:
        i = cols["date"]
        dayfirst = _day_order([r[i] for r in grid[mapping["header_row"] + 1:]
                               if i < len(r)])

    def cell(row: list[str], field: str | int | None) -> str:
        i = cols.get(field) if isinstance(field, str) else field
        return row[i] if i is not None and i < len(row) else ""

    def money(row: list[str], field: str | int | None) -> float:
        return _number(cell(row, field), decimal, thousands) or 0.0

    for lineno, row in enumerate(grid[mapping["header_row"] + 1:],
                                 start=mapping["header_row"] + 2):
        # A title, a page footer, a blank line, the header printed again on
        # the next page: nothing to import and nothing worth reporting.
        if sum(1 for c in row if c.strip()) < 2:
            continue
        if [c.strip().lower() for c in row] == header:
            continue
        raw_action = cell(row, "action").strip()
        if not any(cell(row, f) for f in _REQUIRED if cols.get(f) is not None):
            continue  # separator / totals line

        quantity = money(row, "quantity")
        price = money(row, "price")
        amount = money(row, "amount")
        fee = money(row, "fee")
        paid, received = abs(money(row, debit)), abs(money(row, credit))
        ticker = " ".join(cell(row, "ticker").split())
        currency, minor = _row_currency(cell(row, "currency"), default_currency)
        if not sniffed and not cell(row, "currency").strip():
            # Nothing in the file names a currency. An ISIN at least says
            # where the line is listed, which beats assuming dollars for a
            # Spanish bank's Telefónica. Any cell will do: a model may leave
            # the ISIN column unmapped when it took the name as the symbol.
            for code in (cell(row, mapping.get("isin")), ticker, *row):
                found = (_ISIN_CURRENCY.get(code.strip().upper()[:2])
                         if _is_isin(code) else None)
                if found:
                    currency = found
                    break
        if sentence:
            parts = _sentence_parts(raw_action, decimal, thousands)
            if parts is None:
                result.skipped.append({"row": lineno, "type": raw_action[:40] or "?",
                                       "reason": "action not recognised"})
                continue
            ticker, quantity, price, said = parts
            currency = said or currency

        if cols.get("action") is not None:
            action = actions.get(raw_action.lower()) or (
                raw_action.lower() if raw_action.lower() in ACTIONS else ""
            ) or _phrase_action(raw_action, phrases)
        elif paid or received:
            # A bank's statement: which column the money sits in is the side.
            action = "buy" if paid else "sell"
        elif quantity:
            action = "sell" if quantity < 0 else "buy"
        elif amount:
            action = "buy" if amount < 0 else "sell"
        else:
            action = "buy"
        if not action:
            result.skipped.append({
                "row": lineno, "type": raw_action or "?",
                "reason": "action not recognised",
            })
            continue

        day = _date(cell(row, "date"), mapping["date_format"], dayfirst)
        if day is None:
            result.skipped.append({
                "row": lineno, "type": raw_action,
                "reason": f"unreadable date {cell(row, 'date')!r}",
            })
            continue

        # Whatever the sheet used to name the instrument, verbatim: a company
        # name, an ISIN, a broker code. _resolve_symbols turns it into a
        # ticker once the whole file has been read.
        if not ticker:
            result.skipped.append({
                "row": lineno, "type": raw_action, "reason": "no symbol",
            })
            continue

        if coins:
            coin = _coin_of(ticker)
            if _COIN_RE.match(coin):
                # Coin plus the row's own fiat, the pair Yahoo prices and the
                # form the rest of the app stores crypto in.
                pair_fiat = ticker.upper()[len(coin):].strip("-/ ")
                if (pair_fiat and currency == default_currency
                        and cols.get("currency") is None):
                    currency = pair_fiat[:3]
                ticker = crypto.to_pair(coin, currency)
                fee_cell = _COIN_FEE.match(cell(row, "fee"))
                if fee_cell and fee_cell.group(1).upper() == coin:
                    if action == "buy":
                        quantity = abs(quantity) - abs(fee)
                    fee = 0.0
        if ticker == currency:  # the currency column got mapped as the symbol
            result.skipped.append({
                "row": lineno, "type": raw_action,
                "reason": f"ticker is the currency {currency}",
            })
            continue

        if not amount and (paid or received):
            amount = paid or received
        if minor or (mapping.get("pence") and not sentence):
            # Quoted in pence: 45.12 GBp is £0.4512 a share, and booking it
            # as pounds makes the position a hundred times its size.
            price /= 100
            if minor:
                amount /= 100
                fee /= 100
        if action in ("dividend", "fee", RETURN_OF_CAPITAL) and amount:
            # A payout's value is the money that arrived. One column index
            # has to serve every row, so the per-share column of a dividend
            # row says the rate and only the total says what was paid.
            price = amount
        elif not price and amount:
            # For a trade this divides the total, which carries the fee with
            # it — a cent or two per share, and only ever when the export
            # gave no unit price at all.
            price = amount / quantity if quantity else 0.0
        try:
            result.transactions.append(Transaction(
                date=day, ticker=ticker, action=action,
                # The action carries the direction; a sell exported as a
                # negative quantity must not import as a negative position.
                quantity=abs(quantity), price=abs(price), currency=currency,
                fee=abs(fee), note=platforms.clean_note(cell(row, "note")),
            ))
        except ValueError as exc:
            result.skipped.append({
                "row": lineno, "type": raw_action, "reason": str(exc)})
    return result


# ------------------------------------------------------------ pdf extraction


# The reply's shape is BAML's (ExtractStatement in baml_src/import.baml),
# appended after this by structured.render.
_PDF_SYSTEM = """You read a broker document and pull out its transactions.
You are shown some pages of it as text; each line is one row of the page and
" | " separates what sat in separate columns.

"kind" describes these pages:
- "trades": they contain dated buys, sells, dividends or fees.
- "positions": they only state what is held right now (a portfolio report,
  a holdings summary, a valuation) with no dated movements. Return an empty
  "transactions" list — a holding is not a transaction.
- "none": no financial records here (cover page, cost glossary, disclaimer).

Rules:
- Copy values from the page. Never infer, average or complete a number, and
  never carry one row's value into another. Omit a row you cannot read in
  full rather than guessing at it.
- "date" is when the trade happened, as YYYY-MM-DD. A row with no date is not
  a transaction — leave it out.
- "ticker": the symbol if the document shows one (keep the exchange code:
  "ZBRA:xnas"), otherwise the ISIN, otherwise the instrument's full name as
  printed. Never an account, position or transaction id — those are long
  digit strings and identify the row, not the instrument.
- "quantity" and "price" are per share, unsigned; the action carries the
  direction. For a dividend, "price" is the total amount received.
- "capital" is a return of capital: a payment out of capital rather than
  profit (devolución de prima de emisión), never an ordinary dividend; its
  "price" is the total amount received, as for a dividend.
- "currency" is the instrument's currency, not the account's, when they differ.
  It is never the answer for "ticker": a dividend row names its instrument in
  one column and its currency in another, so read the instrument column.
- An empty "transactions" list is a fine answer.
"""


def _page_text(grid: list[list[str]]) -> str:
    return "\n".join(" | ".join(c for c in row if c) for row in grid if any(row))


def _pdf_batches(data: bytes) -> list[str]:
    """The PDF's pages as text, grouped into per-call batches.

    Batched by character budget rather than page count because statement
    pages vary hugely in density, and a page is never split across calls — a
    transaction cut in half would be read wrong by both calls.
    """
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in upload_guard.pages(pdf):
            rows = page.extract_tables() or []
            text = (_page_text([_cells(r) for t in rows for r in t]) if rows
                    else _page_text(_words_grid(page)))
            if text.strip():
                pages.append(text)

    batches: list[str] = []
    current: list[str] = []
    size = 0
    for text in pages:
        if current and size + len(text) > PDF_CHARS_PER_CALL:
            batches.append("\n".join(current))
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        batches.append("\n".join(current))
    return batches


def _transaction_from(raw: dict) -> tuple[Transaction | None, str]:
    """One extracted record as a Transaction, or None plus why not.

    Everything the model returns is re-checked here: an out-of-schema action,
    an unparseable date or a non-numeric amount drops the row instead of
    reaching the ledger.
    """
    if not isinstance(raw, dict) or not raw:
        return None, "not a record"
    action = str(raw.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return None, f"unknown action {action or '?'}"
    day = _date(str(raw.get("date") or ""), "%Y-%m-%d")
    if day is None:
        return None, f"unreadable date {raw.get('date')!r}"
    ticker = " ".join(str(raw.get("ticker") or "").split())
    if not ticker:
        return None, "no symbol"
    currency = (str(raw.get("currency") or "USD").strip().upper() or "USD")[:3]
    # A dividend line often prints the instrument in one column and the
    # currency in the next, and a model that grabs the wrong one produces a
    # perfectly well-formed "EUR dividend" that validation cannot fault. No
    # holding is its own settlement currency, so this pair is always a misread.
    if ticker == currency:
        return None, f"ticker is the currency {currency}"

    def number(key: str) -> float:
        try:
            return abs(float(raw.get(key) or 0))
        except (TypeError, ValueError):
            return 0.0

    try:
        return Transaction(
            date=day, ticker=ticker, action=action,
            quantity=number("quantity"), price=number("price"),
            currency=currency,
            fee=number("fee"), note=platforms.clean_note(str(raw.get("note") or "")),
        ), ""
    except ValueError as exc:
        return None, str(exc)


def parse_extraction(raw: str) -> tuple[list[dict], str]:
    """(records, kind) out of one extraction reply; ([], KIND_NONE) on junk."""
    try:
        data = structured.parse(raw, "ExtractStatement")
    except structured.OffContract:
        return [], KIND_NONE
    # The enum's third member is spelled "neither" in Python ("None" is
    # reserved), so anything but the two real kinds is KIND_NONE.
    kind = data.get("kind")
    if kind not in (KIND_TRADES, KIND_POSITIONS):
        kind = KIND_NONE
    return data.get("transactions") or [], kind


_ISIN_ANY = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")


_CURRENCY_SIGNS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _printed(currency: str, text: str) -> bool:
    """Whether the page itself states `currency`, by code or by sign."""
    code = currency.strip().upper()[:3]
    if not code:
        return False
    if re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", text, re.IGNORECASE):
        return True
    sign = _CURRENCY_SIGNS.get(code, "")
    return bool(sign) and sign in text


def _listed_currency(ticker: str, text: str) -> str:
    """The currency an ISIN names for `ticker` on a page: the ISIN itself, or
    the ones printed on the lines that name it. Empty when none does or when
    those lines disagree."""
    if not ticker.strip():
        return ""
    if _is_isin(ticker):
        return _ISIN_CURRENCY.get(ticker.strip().upper()[:2], "")
    named = re.compile(rf"(?<![\w.]){re.escape(ticker.strip())}(?!\w)", re.IGNORECASE)
    found = {_ISIN_CURRENCY.get(code[:2], "")
             for line in text.splitlines() if named.search(line)
             for code in _ISIN_ANY.findall(line.upper())}
    return next(iter(found)) if len(found) == 1 else ""


def extract_pdf(data: bytes, provider: Provider, api_key: str = "") -> Extraction:
    """Have the model read a PDF's transactions out of it, batch by batch.

    Batches are independent calls, so one page the model chokes on costs that
    page and not the document. The document's kind is the strongest thing any
    batch reported: one page of real trades makes it a statement, and failing
    that, one page of holdings makes it a portfolio report.
    """
    try:
        batches = _pdf_batches(data)
    except Exception:
        batches = []
    if not batches:
        return Extraction(ParseResult(skipped=[{
            "row": 0, "type": "file",
            "reason": "no text could be read from this PDF",
        }]))

    result = ParseResult()
    kind = KIND_NONE
    dropped = len(batches) - MAX_PDF_CALLS
    attempted = min(len(batches), MAX_PDF_CALLS)
    unreachable = 0
    for index, batch in enumerate(batches[:MAX_PDF_CALLS], start=1):
        try:
            reply = _ask(provider, api_key, "ExtractStatement", _PDF_SYSTEM, batch)
        except ProviderUnavailable:
            unreachable += 1
            result.skipped.append({
                "row": index, "type": "batch",
                "reason": f"pages in block {index} could not be read",
            })
            continue
        with _replying(provider):
            records, batch_kind = parse_extraction(reply)
        if batch_kind == KIND_TRADES or (
            batch_kind == KIND_POSITIONS and kind != KIND_TRADES
        ):
            kind = batch_kind
        for record in records:
            tx, why = _transaction_from(record)
            if tx is None:
                result.skipped.append({"row": index, "type": "row", "reason": why})
                continue
            if not _printed(str(record.get("currency") or ""), batch):
                # The model named no currency, or one the page never prints
                # (dollars is only a default): an ISIN on the row's own line
                # says where it is listed.
                tx.currency = _listed_currency(tx.ticker, batch) or tx.currency
            result.transactions.append(tx)

    if dropped > 0:  # never a silent truncation
        result.skipped.append({
            "row": 0, "type": "file",
            "reason": f"{dropped} more page block(s) not read — the document is "
                      f"longer than the {MAX_PDF_CALLS}-block limit",
        })
    # Every block failing means the model was never reached, so nothing has
    # been learned about the document — that is not "an unreadable PDF".
    return Extraction(result, KIND_TRADES if result.transactions else kind,
                      unavailable=unreachable == attempted)


# ------------------------------------------------------------ symbol resolution


def _resolve_symbols(result: ParseResult, provider: Provider,
                     api_key: str) -> None:
    """Rewrite every row's label into its ticker, in one extra call.

    Runs on the finished ParseResult rather than per row so a nine-page
    statement asks about its five holdings once. A label the model won't name
    is left as the document wrote it: validate.py then rejects that row by
    name, which is what puts it in front of the user.
    """
    if not result.transactions:
        return

    def ask(system: str, content: str) -> str:
        # One retry, because this call arrives right behind the extraction
        # calls and the free chain's limits are per-minute: losing it costs
        # every row in the file, which is far worse than a few seconds' wait.
        try:
            return _send(provider, api_key, system, content)
        except ProviderUnavailable:
            time.sleep(RESOLVE_RETRY_SECONDS)
            return _send(provider, api_key, system, content)

    # A pair is already the ticker the app prices with; asking the model to
    # "resolve" BTC-EUR invites it to answer with a company.
    labels = [tx.ticker for tx in result.transactions
              if not crypto.is_crypto(tx.ticker)]
    if not labels:
        return
    try:
        with _replying(provider):
            mapping = instruments.resolve(labels, provider, api_key, ask=ask)
    except ProviderUnavailable as exc:
        # Nothing is guessed at — but every unresolved row is about to be
        # rejected as a "malformed ticker", which reads as a broken statement
        # rather than a dead API. Say which it was.
        result.skipped.append({
            "row": 0, "type": "file",
            "reason": f"symbols could not be looked up: {exc}",
        })
        return
    for tx in result.transactions:
        if ticker := mapping.get(tx.ticker):
            tx.ticker = ticker


# ------------------------------------------------------------------ entry


def columns(grid: list[list[str]], header_row: int) -> tuple[str, ...]:
    """Each column as a reader would recognise it: its header and a sample.

    "Precio · 12,50" rather than "column 6": the mapping is by index, and an
    index means nothing to someone looking at their own spreadsheet. A column
    with no header is numbered from one, the way a spreadsheet letters them.
    """
    width = min(max((len(r) for r in grid), default=0), MAX_EDIT_COLS)
    head = grid[header_row] if 0 <= header_row < len(grid) else []
    body = next((r for r in grid[header_row + 1:] if any(c.strip() for c in r)), [])
    out = []
    for i in range(width):
        name = (head[i].strip() if i < len(head) else "") or f"#{i + 1}"
        cell = body[i].strip() if i < len(body) else ""
        label = f"{name} · {cell}" if cell and cell != name else name
        out.append(label[:MAX_CELL + 20])
    return tuple(out)


def _is_pdf(filename: str, data: bytes) -> bool:
    return data[:5] == b"%PDF-" or (filename.lower().endswith(".pdf")
                                    and not data.startswith(b"PK\x03\x04"))


# Why a file that read as nothing could not be read at all: a closed set, so
# the chat can say what to do about it instead of "export a CSV".
UNREADABLE = ("locked", "scanned", "odf", "numbers")
_UNREADABLE_REASON = {
    "locked": "the file is password-protected",
    "scanned": "no text could be read from this PDF (a scan or a picture)",
    "odf": "this OpenDocument file could not be opened: save it again as .xlsx or .csv",
    "numbers": "Numbers files are not read: export it as .xlsx or .csv",
}


def unreadable(filename: str, data: bytes) -> str:
    """One of UNREADABLE when the bytes say why nothing could be read, else ""."""
    if data.startswith(_OLE2) and "EncryptedPackage".encode("utf-16-le") in data:
        return "locked"  # an Office file saved with a password
    if data.startswith(b"PK\x03\x04"):
        if b"application/vnd.oasis.opendocument" in data[:200]:
            return "odf"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
        except (zipfile.BadZipFile, ValueError, OSError):
            return ""
        return "numbers" if "Index/Document.iwa" in names else ""
    if _is_pdf(filename, data):
        try:
            batches = _pdf_batches(data)
        except Exception:  # noqa: BLE001 - an unreadable PDF has no text either
            batches = []
        if batches:
            return ""  # bank statements often carry an owner password and read fine
        return "locked" if b"/Encrypt" in data else "scanned"
    return ""


def unreadable_in(skipped: list[dict]) -> str:
    """The UNREADABLE code a read already gave as its reason, else "".

    Read off the result rather than the bytes again: a good .ods whose rows
    were all rejected is not one that "could not be opened"."""
    reasons = {reason: code for code, reason in _UNREADABLE_REASON.items()}
    return next((reasons[entry.get("reason", "")] for entry in skipped
                 if entry.get("type") == "file" and entry.get("reason") in reasons), "")


def _safe_grid(filename: str, data: bytes) -> list[list[str]]:
    """read_grid, or no rows when the bytes are not the table they claim."""
    try:
        return read_grid(filename, data)
    except Exception as exc:  # noqa: BLE001 — a broken file is "no table", not a 500
        obs.event("import.llm_map.unreadable", error=type(exc).__name__)
        return []


def _guessed(grid: list[list[str]]) -> tuple[ParseResult, dict | None]:
    guess = guess_mapping(grid)
    return (apply_mapping(grid, guess) if guess else ParseResult()), guess


def _directed(mapping: dict) -> bool:
    """Whether a mapping reads each row's direction from the cells."""
    return (mapping["columns"].get("action") is not None
            or mapping.get("debit") is not None or mapping.get("credit") is not None)


def _with_guess(mapping: dict, guess: dict) -> dict:
    """The model's mapping, with what only the cells can tell filled in.

    The model names the columns; it is never asked whether the price is in
    pence, whether 03/04 is the 3rd of April, which column is the ISIN, or
    whether the totals sit in a debit and a credit column. Where the guess
    read the same table those come from it, so a model that maps the file
    cannot read it worse than no model would.
    """
    if mapping.get("header_row") != guess.get("header_row"):
        return mapping
    mine, theirs = mapping["columns"], guess["columns"]
    merged = dict(mapping)
    if mapping.get("dayfirst") is None and guess.get("dayfirst") is not None \
            and mine.get("date") == theirs.get("date"):
        merged["dayfirst"] = guess["dayfirst"]
    if guess.get("date_format") == "excel" and mine.get("date") == theirs.get("date"):
        merged["date_format"] = "excel"
    if guess.get("pence") and mine.get("price") == theirs.get("price"):
        merged["pence"] = True
    taken = {i for i in mine.values() if i is not None}
    for key in ("debit", "credit", "isin"):
        if mapping.get(key) is None and guess.get(key) is not None \
                and (guess[key] not in taken or guess[key] == mine.get("amount")):
            merged[key] = guess[key]
    if merged.get("debit") is not None and mine.get("amount") in (
            merged.get("debit"), merged.get("credit")):
        merged["columns"] = {**mine, "amount": None}
    if mine.get("action") is None and theirs.get("action") is not None \
            and (theirs["action"] not in taken or theirs["action"] == mine.get("note")):
        merged["columns"] = {**merged["columns"], "action": theirs["action"]}
        merged["action_map"] = {**guess.get("action_map", {}),
                                **mapping.get("action_map", {})}
    return merged


def extract(filename: str, data: bytes, provider: Provider | None,
            api_key: str = "", mapping: dict | None = None,
            fiat: str = "") -> Extraction:
    """Read one unrecognised export, by whichever route its format needs.

    `mapping` is one the reader corrected (`Extraction.mapping`, edited): it
    is checked exactly as a model's reply would be and applied with no model
    call at all, so a second read can only differ where the reader changed it.
    A crypto export is read as one first (`_crypto`); `fiat` is the account's
    currency, which a file traded only against stablecoins is booked in.

    With no provider at all the file is still read, from its headers and
    cells (`guess_mapping`) — a PDF's table included. The model is what reads
    the files the guess cannot, never what the guess has to wait for.
    """
    pdf = _is_pdf(filename, data)
    if mapping is not None and not pdf:
        return _remap(filename, data, provider, api_key, mapping)
    grid = _safe_grid(filename, data)
    if len(grid) >= 2:
        found = _crypto(grid, provider, api_key, fiat) or _holdings(grid)
        if found is not None:
            return found

    model_pdf: Extraction | None = None
    if pdf and provider is not None:
        model_pdf = extract_pdf(data, provider, api_key)
        if model_pdf.result.transactions or model_pdf.kind == KIND_POSITIONS:
            _resolve_symbols(model_pdf.result, provider, api_key)
            return model_pdf

    if len(grid) < 2:
        why = unreadable(filename, data)
        if model_pdf is not None and not why:
            return model_pdf
        return Extraction(ParseResult(skipped=[{
            "row": 0, "type": "file",
            "reason": _UNREADABLE_REASON.get(
                why, "no table could be read from this file"),
        }]))

    if provider is None or pdf:
        # No model to ask, or the model already read this PDF and found
        # nothing: the table on its pages is the last word.
        result, guess = _guessed(grid)
        if result.transactions:
            obs.event("import.llm_map.guessed", rows=len(result.transactions),
                      pdf=pdf, model=provider is not None)
            if provider is not None:
                _resolve_symbols(result, provider, api_key)
            return Extraction(result, KIND_TRADES, mapping=None if pdf else guess,
                              columns=columns(grid, guess["header_row"]) if guess else ())
        if model_pdf is not None:
            return model_pdf
        reason = ("no rows could be read: the columns could not be matched to "
                  "date/symbol/action" if guess is None else
                  "no rows could be read from this file")
        return Extraction(
            ParseResult(skipped=[{"row": 0, "type": "file", "reason": reason}]
                        + result.skipped[:20]),
            mapping=guess, columns=columns(grid, guess["header_row"]) if guess else (),
        )

    # Worked out from the file itself, before anything is asked of anyone.
    # It is the answer when the model is unreachable, when it declines the
    # file, and when its mapping turns out to convert nothing — three
    # failures that would otherwise end the import.
    guess = guess_mapping(grid)

    down = ""
    try:
        mapping = map_columns(provider, api_key, grid)
    except ProviderUnavailable as exc:
        mapping, down = None, str(exc)

    if mapping and guess:
        mapping = _with_guess(mapping, guess)
        if mapping["columns"].get("action") is None and _directed(guess):
            # The model left the direction to the signs while the cells name
            # it: one that filed "Kauf"/"Verkauf" under another column would
            # book every sale as a buy. With no guess to take over, a mapping
            # with no action column stands (a buys-only or signed file).
            mapping = guess
    result = apply_mapping(grid, mapping) if mapping else ParseResult()
    used = mapping
    if not result.transactions and guess and guess != mapping:
        rescued = apply_mapping(grid, guess)
        if rescued.transactions:
            obs.event("import.llm_map.rescued", rows=len(rescued.transactions),
                      reason="model_down" if down else
                      ("no_mapping" if mapping is None else "no_rows"))
            result, used = rescued, guess

    if not result.transactions:
        if down:
            return Extraction(ParseResult(skipped=[{
                "row": 0, "type": "file",
                "reason": f"the assistant is down: {down}",
            }]), unavailable=True)
        if mapping is None:
            return Extraction(ParseResult(skipped=[{
                "row": 0, "type": "file",
                "reason": "the columns could not be matched to date/symbol/action",
            }]))

    _resolve_symbols(result, provider, api_key)
    return Extraction(
        result, KIND_TRADES if result.transactions else KIND_NONE,
        mapping=used,
        columns=columns(grid, used["header_row"]) if used else (),
    )


def _crypto(grid: list[list[str]], provider: Provider | None, api_key: str,
            fiat: str) -> Extraction | None:
    """The file read as a crypto export (crypto_map), or None to read it as shares.

    A header we know is read with no model at all. Otherwise the model is
    asked only when the file shows coins, and its reading is kept only when
    it books something: a mapping that books nothing, a model that declines
    or one that is down all leave the file to the share mapping, as before.
    """
    from stocks.portfolio import crypto_map

    if len(grid) < 2:
        return None
    spec, via = crypto_map.preset_spec(grid), "preset"
    if spec is None:
        if provider is None or not crypto_map.looks_crypto(grid):
            return None
        try:
            spec, via = crypto_map.map_crypto(provider, api_key, grid), "model"
        except ProviderUnavailable:
            return None
        if spec is None:
            return None
    result = crypto_map.apply(grid, spec, fiat_hint=fiat)
    obs.event("import.crypto.read", via=via, layout=spec.layout,
              exchange=spec.exchange or "unknown",
              rows=len(result.transactions), skipped=len(result.skipped))
    if not result.transactions and via == "model":
        return None
    return Extraction(result, KIND_TRADES if result.transactions else KIND_NONE,
                      label=crypto_map.label(spec.exchange))


def preset_read(filename: str, data: bytes, fiat: str = "") -> Extraction | None:
    """A crypto export whose header we know, or a holdings snapshot, read
    with no model; else None."""
    grid = _safe_grid(filename, data)
    if len(grid) < 2:
        return None
    return _crypto(grid, None, "", fiat) or _holdings(grid)


def _holdings(grid: list[list[str]]) -> Extraction | None:
    """A holdings snapshot read as one, with no model asked; else None."""
    if not holdings_only(grid):
        return None
    held = tuple(holdings_rows(grid))
    obs.event("import.llm_map.holdings_only", rows=len(grid) - 1, held=len(held))
    return Extraction(ParseResult(), KIND_POSITIONS,
                      columns=columns(grid, _guess_header_row(grid)), holdings=held)


def _remap(filename: str, data: bytes, provider: Provider | None,
           api_key: str, mapping: dict) -> Extraction:
    """`extract` with the reader's own mapping in place of the model's."""
    grid = read_grid(filename, data)
    chosen = _mapping_from(mapping, grid) if len(grid) >= 2 else None
    if chosen is None:
        return Extraction(ParseResult(skipped=[{
            "row": 0, "type": "file",
            "reason": "the columns could not be matched to date/symbol/action",
        }]), mapping=None, columns=columns(grid, 0))
    result = apply_mapping(grid, chosen)
    if provider is not None:
        _resolve_symbols(result, provider, api_key)
    obs.event("import.llm_map.remapped", rows=len(result.transactions))
    return Extraction(result, KIND_TRADES if result.transactions else KIND_NONE,
                      mapping=chosen, columns=columns(grid, chosen["header_row"]))


def parse(filename: str, data: bytes, provider: Provider,
          api_key: str = "") -> ParseResult:
    """extract() without the document kind, for callers that don't need it."""
    return extract(filename, data, provider, api_key).result
