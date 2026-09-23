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
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from stocks import obs
from stocks.data import crypto
from stocks.portfolio import instruments, lexicon
from stocks.portfolio.ledger import ACTIONS, Transaction
from stocks.portfolio.statement import ParseResult

if TYPE_CHECKING:
    from stocks.web.llm import Provider

# What the model is shown. Enough rows to see the shape of the data (and any
# preamble above the header), few enough to stay a cheap classifier call.
SAMPLE_ROWS = 18
MAX_COLS = 30
MAX_CELL = 40

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


def _ask(provider: Provider, api_key: str, system: str, content: str) -> str:
    try:
        return provider.complete(
            api_key,
            provider.classifier_model or provider.default_model,
            system,
            [{"role": "user", "content": content}],
        )
    except Exception as exc:
        raise ProviderUnavailable(str(exc)) from exc


@dataclass(frozen=True)
class Extraction:
    """What came out of a file, and what the file turned out to be."""

    result: ParseResult = field(default_factory=ParseResult)
    kind: str = KIND_NONE
    unavailable: bool = False  # the model never answered; the file is unjudged


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


def _read_csv(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")
    # European exports are semicolon-delimited as often as comma-delimited;
    # sniffing beats guessing, and a failed sniff falls back to comma.
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [_cells(r) for r in csv.reader(io.StringIO(text), dialect)]


def _read_excel(data: bytes) -> list[list[str]]:
    import pandas as pd

    frame = pd.read_excel(io.BytesIO(data), header=None, dtype=str)
    return [_cells(r) for r in frame.itertuples(index=False, name=None)]


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
        for page in pdf.pages:
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
        if name.endswith(".pdf"):
            grid = _read_pdf(data)
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


_SYSTEM = """You map a broker's transaction export onto a fixed ledger schema.
You are shown the first rows of the file, each cell separated by " | " and
numbered by row and (implicitly) by column, starting at 0.

Reply with ONLY a JSON object, no prose, no code fences:
{"header_row": <index of the row holding the column headers>,
 "columns": {"date": <column index>, "ticker": <index>, "action": <index>,
             "quantity": <index or null>, "price": <index or null>,
             "amount": <index or null>, "currency": <index or null>,
             "fee": <index or null>, "note": <index or null>},
 "date_format": "<strftime format of the date cells, e.g. %d/%m/%Y>",
 "decimal": "<the decimal separator, '.' or ','>",
 "thousands": "<the thousands separator, or an empty string>",
 "asset_class": "crypto" | "securities",
 "action_map": {"<the exact text in the action column>":
                "<buy|sell|dividend|fee|split>"}}

Rules:
- Column indexes are 0-based positions in the " | " list, NOT header names.
- Required: date, ticker, action. If the file has no column that identifies
  the security, or no column that says what happened, reply {"columns": null}.
- "ticker": the symbol column. Failing that, the ISIN column, failing that
  the instrument-name column — a name is resolved to its symbol later. Never
  an id column (position id, transaction id, order reference).
- "price" is the per-share price column, "amount" the row's total cash column
  — the one that is negative for a purchase and positive for a sale or a
  dividend. Many exports carry both: map both. Never map one column to the
  other's name, and leave "amount" null when the file has no total column.
- For a split, "quantity" is the ratio.
- "action_map" needs one entry per distinct value you can see in the action
  column, including the ones you would ignore — map those to the closest of
  buy/sell/dividend/fee/split, and leave out only values that are clearly not
  transactions (cash top-ups, transfers, balance lines).
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
    out-of-range index, unparseable JSON. The caller reports that rather than
    importing a half-understood file.
    """
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("columns"), dict):
        return None

    width = max((len(r) for r in grid), default=0)
    header_row = _index(data.get("header_row"), len(grid))
    columns = {
        f: _index(data["columns"].get(f), width) for f in FIELDS
    }
    if any(columns[f] is None for f in _REQUIRED):
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
             "dia", "day"),
    "ticker": ("symbol", "simbolo", "ticker", "asset", "activo", "isin",
               "instrument", "instrumento", "valor", "producto", "product",
               "security", "criptomoneda", "coin", "titulo"),
    "action": ("type", "tipo", "action", "accion", "operacion", "operation",
               "transaction type", "movimiento", "side", "sentido",
               "concepto", "transaccion"),
    "quantity": ("quantity", "cantidad", "qty", "shares", "titulos",
                 "participaciones", "unidades", "volumen", "volume", "units",
                 "num titulos", "numero de titulos"),
    "price": ("price", "precio", "price per share", "price per coin",
              "precio unitario", "cotizacion", "kurs", "prezzo", "cours",
              "unit price"),
    "amount": ("value", "total", "importe", "total amount", "gross amount",
               "valor total", "importe total", "efectivo", "contravalor",
               "montant", "betrag", "amount"),
    "fee": ("fee", "fees", "comision", "comisiones", "commission",
            "corretaje", "gastos", "costes", "gebuhr", "frais", "tarifa"),
    "currency": ("currency", "divisa", "moneda", "ccy", "currency code"),
    "note": ("note", "notes", "nota", "descripcion", "description",
             "detalle", "comentario"),
}

# European and US number shapes, told apart by which separator comes last.
_EU_NUMBER = re.compile(r"^\d{1,3}(\.\d{3})*,\d+$")
_US_NUMBER = re.compile(r"^\d{1,3}(,\d{3})*\.\d+$")

# A symbol column's cells: short, no spaces, not a number. Loose on purpose —
# it only has to beat the other columns of the same file.
_SYMBOLISH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-:_]{0,11}$")

# Rows of the file read when guessing by content rather than by header.
_SNIFF_ROWS = 40


def _header_field(cell: str) -> str | None:
    """The field a header cell names, or None."""
    text = " ".join(lexicon.plain(cell).replace(".", " ").split())
    if not text:
        return None
    for name, words in _HEADER_WORDS.items():
        if text in words:
            return name
    for name, words in _HEADER_WORDS.items():
        if any(word in text for word in words):
            return name
    return None


def _guess_header_row(grid: list[list[str]]) -> int:
    """The row that names the columns: the one most of whose cells are names.

    A preamble line ("Extracto de operaciones") names nothing, and a data row
    names at most a column or two by accident, so the real header wins on
    count. Ties go to the earliest row, and a file whose header this cannot
    see is read as starting at row 0 — the same assumption the model's
    mapping falls back on.
    """
    best, best_score = 0, 0
    for index, row in enumerate(grid[:10]):
        score = sum(1 for cell in row if _header_field(cell))
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


def guess_mapping(grid: list[list[str]]) -> dict | None:
    """A mapping worked out from the file alone, or None.

    Headers first, then the cells themselves: a column whose values parse as
    dates is the date column whatever it is called, and one whose values are
    words lexicon.py knows is the action column. That content check is what
    carries a file whose headers are in a language, or an abbreviation, the
    table above never listed.
    """
    if len(grid) < 2:
        return None
    header_row = _guess_header_row(grid)
    width = max((len(row) for row in grid), default=0)
    rows = [r for r in grid[header_row + 1:header_row + 1 + _SNIFF_ROWS] if any(r)]
    if not rows or not width:
        return None

    columns: dict[str, int | None] = {name: None for name in FIELDS}
    for index, cell in enumerate(grid[header_row][:width]):
        name = _header_field(cell)
        if name and columns[name] is None:
            columns[name] = index

    taken = {i for i in columns.values() if i is not None}

    def adopt(name: str, test) -> None:
        index = columns[name]
        if index is not None:
            hits = _column_scores(rows, width, test)[index]
            if hits >= max(1, len(rows) // 2):
                return  # the header was right about it
            taken.discard(index)
        found = _best_column(rows, width, test, taken)
        if found is not None:
            columns[name] = found
            taken.add(found)

    adopt("date", lambda cell: lexicon.readable_date(cell) is not None)
    adopt("action", lambda cell: lexicon.action_of(cell) is not None)
    if columns["ticker"] is None:
        columns["ticker"] = _best_column(
            rows, width,
            lambda cell: bool(_SYMBOLISH.match(cell.strip()))
            and lexicon.readable_date(cell) is None
            and _number(cell, ".", ",") is None,
            taken,
        )
    if any(columns[name] is None for name in _REQUIRED):
        return None

    decimal, thousands = _sniff_separators(
        rows, [columns[f] for f in ("price", "amount", "quantity", "fee")])
    return {
        "header_row": header_row,
        "columns": columns,
        "date_format": "",  # lexicon reads the cells; no one format to declare
        "decimal": decimal,
        "thousands": thousands,
        "action_map": {},  # lexicon's vocabulary covers it
        "asset_class": "",  # decided from the symbols themselves
    }


def map_columns(provider: Provider, api_key: str,
                grid: list[list[str]]) -> dict | None:
    """Ask the provider's cheapest model how this file is laid out.

    None means the model looked and could not match the columns. A model that
    could not be reached raises ProviderUnavailable instead — the two need
    different answers.
    """
    return parse_mapping(_ask(provider, api_key, _SYSTEM, sample(grid)), grid)


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


def _date(text: str, fmt: str) -> str | None:
    """An ISO date out of a cell: the mapped format, the usual ones, then prose.

    The cell is tried whole and again without its time half. Splitting on the
    first space, as this used to, turns "3 feb 2025 09:21:06" into "3" and
    rejects every row of a file that a human reads at a glance — the date is
    not always the first word-with-no-spaces in the cell.
    """
    text = (text or "").strip()
    if not text:
        return None
    candidates = [text]
    head = text.split("T")[0].strip()
    if head != text:
        candidates.append(head)
    for candidate in candidates:
        for pattern in ([fmt] if fmt else []) + list(_DATE_FALLBACKS):
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
    return "USD"


def apply_mapping(grid: list[list[str]], mapping: dict) -> ParseResult:
    """Turn every data row into a Transaction using the mapping. No LLM here."""
    result = ParseResult()
    cols = mapping["columns"]
    coins = _is_crypto_file(_symbol_column(grid, mapping),
                            mapping.get("asset_class", ""))
    default_currency = _sniff_currency(grid, mapping)
    actions = mapping["action_map"]
    phrases = _action_phrases(actions)
    decimal, thousands = mapping["decimal"], mapping["thousands"]

    def cell(row: list[str], field: str) -> str:
        i = cols.get(field)
        return row[i] if i is not None and i < len(row) else ""

    for lineno, row in enumerate(grid[mapping["header_row"] + 1:],
                                 start=mapping["header_row"] + 2):
        raw_action = cell(row, "action").strip()
        if not any(cell(row, f) for f in _REQUIRED):
            continue  # separator / totals line
        action = actions.get(raw_action.lower()) or (
            raw_action.lower() if raw_action.lower() in ACTIONS else ""
        ) or _phrase_action(raw_action, phrases)
        if not action:
            result.skipped.append({
                "row": lineno, "type": raw_action or "?",
                "reason": "action not recognised",
            })
            continue

        day = _date(cell(row, "date"), mapping["date_format"])
        if day is None:
            result.skipped.append({
                "row": lineno, "type": raw_action,
                "reason": f"unreadable date {cell(row, 'date')!r}",
            })
            continue

        # Whatever the sheet used to name the instrument, verbatim: a company
        # name, an ISIN, a broker code. _resolve_symbols turns it into a
        # ticker once the whole file has been read.
        ticker = " ".join(cell(row, "ticker").split())
        if not ticker:
            result.skipped.append({
                "row": lineno, "type": raw_action, "reason": "no symbol",
            })
            continue

        currency = (cell(row, "currency").strip().upper() or default_currency)[:3]
        if coins and _COIN_RE.match(ticker.upper()):
            # Coin plus the row's own fiat, the pair Yahoo prices and the form
            # the rest of the app stores crypto in (stocks.data.crypto).
            ticker = crypto.to_pair(ticker, currency)
        if ticker == currency:  # the currency column got mapped as the symbol
            result.skipped.append({
                "row": lineno, "type": raw_action,
                "reason": f"ticker is the currency {currency}",
            })
            continue

        quantity = _number(cell(row, "quantity"), decimal, thousands) or 0.0
        price = _number(cell(row, "price"), decimal, thousands) or 0.0
        amount = _number(cell(row, "amount"), decimal, thousands) or 0.0
        fee = _number(cell(row, "fee"), decimal, thousands) or 0.0
        if not price and amount:
            # One column index has to serve every row, so a file with both a
            # per-share price and a row total cannot have "price" mean the
            # right thing for a buy *and* for a dividend: the dividend prints
            # its value in the total column and leaves the per-share one at
            # zero. The halves are reconciled here rather than by asking the
            # model for a row-dependent mapping it cannot express.
            #
            # For a trade this divides the total, which carries the fee with
            # it — a cent or two per share, and only ever when the export
            # gave no unit price at all.
            price = amount if action in ("dividend", "fee") else (
                amount / quantity if quantity else 0.0)
        try:
            result.transactions.append(Transaction(
                date=day, ticker=ticker, action=action,
                # The action carries the direction; a sell exported as a
                # negative quantity must not import as a negative position.
                quantity=abs(quantity), price=abs(price), currency=currency,
                fee=abs(fee), note=cell(row, "note").strip()[:120],
            ))
        except ValueError as exc:
            result.skipped.append({
                "row": lineno, "type": raw_action, "reason": str(exc)})
    return result


# ------------------------------------------------------------ pdf extraction


_PDF_SYSTEM = """You read a broker document and pull out its transactions.
You are shown some pages of it as text; each line is one row of the page and
" | " separates what sat in separate columns.

Reply with ONLY a JSON object, no prose, no code fences:
{"kind": "trades" | "positions" | "none",
 "transactions": [{"date": "YYYY-MM-DD", "ticker": "<symbol or ISIN>",
                   "action": "buy|sell|dividend|fee|split",
                   "quantity": <number>, "price": <number>,
                   "currency": "<3-letter code>", "fee": <number>,
                   "note": "<short label, optional>"}]}

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
        for page in pdf.pages:
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
    if not isinstance(raw, dict):
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
            fee=number("fee"), note=str(raw.get("note") or "").strip()[:120],
        ), ""
    except ValueError as exc:
        return None, str(exc)


def parse_extraction(raw: str) -> tuple[list[dict], str]:
    """(records, kind) out of one extraction reply; ([], KIND_NONE) on junk."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return [], KIND_NONE
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return [], KIND_NONE
    if not isinstance(data, dict):
        return [], KIND_NONE
    kind = str(data.get("kind") or KIND_NONE).strip().lower()
    if kind not in (KIND_TRADES, KIND_POSITIONS, KIND_NONE):
        kind = KIND_NONE
    records = data.get("transactions")
    return (records if isinstance(records, list) else []), kind


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
            reply = _ask(provider, api_key, _PDF_SYSTEM, batch)
        except ProviderUnavailable:
            unreachable += 1
            result.skipped.append({
                "row": index, "type": "batch",
                "reason": f"pages in block {index} could not be read",
            })
            continue
        records, batch_kind = parse_extraction(reply)
        if batch_kind == KIND_TRADES or (
            batch_kind == KIND_POSITIONS and kind != KIND_TRADES
        ):
            kind = batch_kind
        for record in records:
            tx, why = _transaction_from(record)
            if tx is None:
                result.skipped.append({"row": index, "type": "row", "reason": why})
            else:
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
            return _ask(provider, api_key, system, content)
        except ProviderUnavailable:
            time.sleep(RESOLVE_RETRY_SECONDS)
            return _ask(provider, api_key, system, content)

    # A pair is already the ticker the app prices with; asking the model to
    # "resolve" BTC-EUR invites it to answer with a company.
    labels = [tx.ticker for tx in result.transactions
              if not crypto.is_crypto(tx.ticker)]
    if not labels:
        return
    try:
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


def extract(filename: str, data: bytes, provider: Provider,
            api_key: str = "") -> Extraction:
    """Read one unrecognised export, by whichever route its format needs."""
    if filename.lower().endswith(".pdf"):
        found = extract_pdf(data, provider, api_key)
        _resolve_symbols(found.result, provider, api_key)
        return found

    grid = read_grid(filename, data)
    if len(grid) < 2:
        return Extraction(ParseResult(skipped=[{
            "row": 0, "type": "file",
            "reason": "no table could be read from this file",
        }]))

    # Worked out from the file itself, before anything is asked of anyone.
    # It is the answer when the model is unreachable, when it declines the
    # file, and when its mapping turns out to convert nothing — three
    # failures that used to be the end of the import and are now a fallback.
    guess = guess_mapping(grid)

    down = ""
    try:
        mapping = map_columns(provider, api_key, grid)
    except ProviderUnavailable as exc:
        mapping, down = None, str(exc)

    result = apply_mapping(grid, mapping) if mapping else ParseResult()
    if not result.transactions and guess and guess != mapping:
        rescued = apply_mapping(grid, guess)
        if rescued.transactions:
            obs.event("import.llm_map.rescued", rows=len(rescued.transactions),
                      reason="model_down" if down else
                      ("no_mapping" if mapping is None else "no_rows"))
            result = rescued

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
    return Extraction(result, KIND_TRADES if result.transactions else KIND_NONE)


def parse(filename: str, data: bytes, provider: Provider,
          api_key: str = "") -> ParseResult:
    """extract() without the document kind, for callers that don't need it."""
    return extract(filename, data, provider, api_key).result
