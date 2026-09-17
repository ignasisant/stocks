"""Parse an Interactive Brokers activity-statement CSV into Transactions.

IBKR's activity statement (Performance & Reports → Statements → Activity →
CSV) is not one table: it concatenates many sections, each row prefixed with
its section name and a row kind (``Trades,Header,…`` / ``Trades,Data,…``).
Every section carries its own header row, so the columns only mean anything
relative to the most recent ``Header`` line for that section.

The statement is emitted in the account's own language. IBKR translates both
the section names and the column names ("Trades" → "Operaciones", "Symbol" →
"Símbolo") but not the row kinds (``Header``/``Data``/``Total``) nor
``DataDiscriminator``, so the skeleton is stable and only the vocabulary
moves. Sections and columns are therefore matched through alias tables,
accent- and case-insensitively (see `_SECTIONS` and the per-section column
aliases). The Spanish names for the sections this parser reads are taken from
a real es-ES statement; other locales fall through to the English names.

This parser stays strict about shape: it refuses the whole file unless some
section it understands turns up with the columns IBKR emits, so a statement
from another broker can never be half-imported by accident.

What imports, and how:

* ``Trades``/``Operaciones``, ``DataDiscriminator == Order``, asset category
  Stocks — buys (positive quantity) and sells (negative). Per-share price is
  ``T. Price`` in the row's currency; ``Comm/Fee`` (always negative in the
  statement) becomes the fee — IBKR charges commission in the trade currency.
  ``SubTotal``/``Total``/``ClosedLot`` rows are derived lines, not events,
  and are dropped without comment.
* Other asset categories (Forex, Options, CFDs…) are skipped with a reason —
  the ledger models stock/ETF positions only.
* ``Dividends``/``Dividendos`` — the ticker is parsed from the description
  prefix ("AAPL(US03…) Cash Dividend…"); amount is the gross payment.
  Per-currency ``Total`` summary rows are dropped.
* ``Withholding Tax``/``Retención de impuestos`` — the tax withheld at source
  belongs on its dividend as the fee (the Spanish double-tax credit
  convention), so a row that can only mean one payment is put there: exactly
  one dividend and exactly one withholding row for the same ticker, day and
  currency. Anything else — a restatement, two payments on one day, a
  correction that reverses an earlier line — is left for the reader with the
  pointer it always had, because guessing which payment a second tax line
  belongs to is how a year's withholding silently doubles. Either way the row
  stays in the skipped list, so the statement can be reconciled line by line.
* ``Open Positions``/``Posiciones abiertas`` — **only when the file holds no
  movements at all**. A one-day statement, or any statement covering a period
  with no activity, has no Trades section whatsoever; what it does carry is
  the holding: ticker, quantity, average cost price, currency. Each holding
  becomes one ``transfer_in`` at that average cost, dated the statement's end
  date, noted ``ibkr snapshot <ISIN>``. A balance is not a purchase: the
  shares were owned before the file was written, and if they arrived from a
  broker this book already covers, the two legs net out instead of booking a
  sale that never happened (see stocks.portfolio.transfers). The cost basis is
  the broker's own and is exact; the date is not — shares with no departure to
  pair with land as one lot on one day, so FIFO tax lots and holding periods
  derived from them are a placeholder until a statement with real trades is
  imported over them. When the file *does* carry trades, the positions section
  is ignored: importing both would double the book.
* ``Financial Instrument Information``/``Información de instrumento
  financiero`` — not events: the ISIN and the listing venue behind each
  symbol. The ISIN is what lets a holding IBKR calls ``ASML`` be recognised as
  the one DEGIRO booked under ``NL0010273215``. The venue is what stops that
  same holding being priced as something else entirely — IBKR prints the bare
  local symbol on every market it lists, and a bare ``ASML`` is the Nasdaq ADR
  in dollars, not the Amsterdam share in euros the statement is reporting. A
  venue the map knows adds its Yahoo suffix (``ASML.AS``); one it does not
  leaves the symbol exactly as written.
* ``Change in Dividend Accruals``/``Modificación en los dividendos
  devengados`` — an accrual, not a payment. Listed as skipped so the reader
  sees it was read and deliberately left out; the cash dividend shows up in
  the Dividends section on the statement that covers its pay date.

Nothing here writes to the ledger; the Import page previews and commits.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult, money, parse_date
from stocks.portfolio.transfers import TRANSFER_IN

# "AAPL(US0378331005) Cash Dividend USD 0.24 per Share" -> AAPL
_DESC_TICKER = re.compile(r"^([A-Z0-9.\- ]+?)\s*\(")

# Two-letter country code, nine alphanumerics, check digit.
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")

# Logical section -> the names IBKR prints for it, normalised by `_norm`.
_SECTIONS: dict[str, tuple[str, ...]] = {
    "statement": ("statement", "extracto"),
    "trades": ("trades", "operaciones"),
    "dividends": ("dividends", "dividendos"),
    "withholding": ("withholding tax", "retencion de impuestos"),
    "positions": ("open positions", "posiciones abiertas"),
    "accruals": (
        "change in dividend accruals",
        "modificacion en los dividendos devengados",
    ),
    "instruments": (
        "financial instrument information",
        "informacion de instrumento financiero",
    ),
}

# Column aliases, per section: one section's "Cantidad" is a share count and
# another's is a cash amount, so these can never share one table.
_TRADE_ALIASES: dict[str, tuple[str, ...]] = {
    "discriminator": ("datadiscriminator",),
    "category": ("asset category", "categoria de activo"),
    "currency": ("currency", "divisa"),
    "symbol": ("symbol", "simbolo"),
    "date": ("date/time", "fecha/hora"),
    "quantity": ("quantity", "cantidad"),
    "price": ("t price", "t precio", "precio t"),
    "fee": ("comm/fee", "comm/fee in eur", "tarifa/com", "comision", "tarifa/comision"),
    "proceeds": ("proceeds", "productos", "beneficios"),
}
_DIVIDEND_ALIASES: dict[str, tuple[str, ...]] = {
    "currency": ("currency", "divisa"),
    "date": ("date", "fecha"),
    "description": ("description", "descripcion"),
    "amount": ("amount", "cantidad", "importe"),
}
_POSITION_ALIASES: dict[str, tuple[str, ...]] = {
    "discriminator": ("datadiscriminator",),
    "category": ("asset category", "categoria de activo"),
    "currency": ("currency", "divisa"),
    "symbol": ("symbol", "simbolo"),
    "quantity": ("quantity", "cantidad"),
    "price": ("cost price", "precio de coste"),
    "basis": ("cost basis", "base de coste"),
}
_ACCRUAL_ALIASES: dict[str, tuple[str, ...]] = {
    "category": ("asset category", "categoria de activo"),
    "currency": ("currency", "divisa"),
    "symbol": ("symbol", "simbolo"),
    "date": ("pay date", "fecha de pago", "date", "fecha"),
    "quantity": ("quantity", "cantidad"),
    "amount": ("gross amount", "cantidad bruta", "net amount", "cantidad neta"),
}
_INSTRUMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "simbolo"),
    "isin": ("security id", "id. de seguridad", "id de seguridad"),
    "exchange": ("listing exch", "merc de cotizacion", "mercado de cotizacion"),
}

# IBKR listing venue -> Yahoo suffix. IBKR prints a bare local symbol for every
# market it lists, and Yahoo reads a bare symbol as the US line: `ASML` is the
# Nasdaq ADR in dollars, not the Amsterdam share in euros the statement is
# reporting. Booked unqualified, that holding is priced off the ADR and read as
# EUR — a silent ~15% on a position nothing in the numbers flags. US venues map
# to no suffix because there the bare symbol is right, and a code not listed
# here keeps the symbol as IBKR wrote it (the same as before this map existed).
_VENUE_SUFFIX: dict[str, str] = {
    "nasdaq": "", "nasdaq nms": "", "nyse": "", "arca": "", "amex": "",
    "bats": "", "iex": "", "pink": "", "value": "", "nyseam": "",
    "aeb": ".AS", "sbf": ".PA", "enext be": ".BR", "bvl": ".LS",
    "ibis": ".DE", "ibis2": ".DE", "fwb": ".F", "swb": ".SG", "tgate": ".DE",
    "bm": ".MC", "mexi": ".MX",
    "bvme": ".MI", "bvme etf": ".MI",
    "lse": ".L", "lseetf": ".L",
    "ebs": ".SW", "vse": ".VI",
    "sfb": ".ST", "cph": ".CO", "hex": ".HE", "ose": ".OL",
    "sehk": ".HK", "tsej": ".T", "tse": ".TO", "asx": ".AX",
}
_ALIASES = {
    "trades": _TRADE_ALIASES,
    "dividends": _DIVIDEND_ALIASES,
    "positions": _POSITION_ALIASES,
    "accruals": _ACCRUAL_ALIASES,
    "withholding": _DIVIDEND_ALIASES,
    "instruments": _INSTRUMENT_ALIASES,
}

# What each section must name before the file counts as an IBKR statement.
_REQUIRED = {
    "trades": ("category", "symbol", "quantity", "price"),
    "dividends": ("date", "description", "amount"),
    "positions": ("symbol", "quantity"),
}

# Asset categories the ledger models. IBKR files ETFs under "Stocks" in
# English and under "Acciones" in Spanish, so one word covers both here.
_EQUITY = ("stocks", "acciones", "etfs")

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
# "Septiembre 14, 2026" / "September 14, 2026"
_LONG_DATE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _norm(text: str | None) -> str:
    """Lowercase, unaccented, dot- and space-collapsed — the matching key.

    Accents go because a statement may be re-encoded on its way here, and
    dots because IBKR writes "T. Price" and "Mult." with them but its own
    translations do not agree on where they land.
    """
    stripped = unicodedata.normalize("NFKD", (text or "").strip().lower())
    bare = "".join(c for c in stripped if not unicodedata.combining(c))
    return " ".join(bare.replace(".", " ").split())


@dataclass
class _Section:
    """One section's current header: where each logical column sits."""

    key: str
    cols: dict[str, int] = field(default_factory=dict)

    def get(self, row: list[str], name: str) -> str:
        i = self.cols.get(name)
        if i is None or i >= len(row):
            return ""
        return row[i].strip()


def _section_key(name: str) -> str:
    n = _norm(name)
    for key, names in _SECTIONS.items():
        if n in names:
            return key
    return ""


def _columns(key: str, header: list[str]) -> dict[str, int]:
    """Logical column -> index, from this section's header row."""
    names = [_norm(c) for c in header]
    cols: dict[str, int] = {}
    for logical, aliases in _ALIASES.get(key, {}).items():
        for alias in aliases:
            if alias in names:
                cols[logical] = names.index(alias)
                break
    return cols


def parse_csv(text: str) -> ParseResult:
    """Parse IBKR activity-statement CSV text into a ParseResult (no writes)."""
    result = ParseResult()
    sections: dict[str, _Section] = {}  # raw section name -> resolved header
    recognised = False
    positions: list[tuple[int, _Section, list[str]]] = []
    dates: dict[str, str] = {}  # "period" / "generated" -> ISO day
    isins: dict[str, str] = {}  # symbol -> ISIN, from the instrument table
    venues: dict[str, str] = {}  # symbol -> Yahoo suffix for its listing

    for i, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if len(row) < 3:
            continue
        name, kind, rest = row[0], row[1], row[2:]
        key = _section_key(name)
        if kind == "Header":
            section = _Section(key, _columns(key, rest))
            sections[name] = section
            need = _REQUIRED.get(key)
            # A section can appear more than once with different headers (the
            # NAV block has two); the one that names what we need wins.
            if need and all(c in section.cols for c in need):
                recognised = True
            elif need:
                sections[name] = _Section(key)  # header we cannot read
            continue
        if kind != "Data" or name not in sections:
            continue
        section = sections[name]
        if section.key == "statement":
            _statement_date(rest, dates)
        elif section.key == "trades":
            _trade_row(i, section, rest, result)
        elif section.key == "dividends":
            _dividend_row(i, section, rest, result)
        elif section.key == "withholding":
            _withholding_row(i, section, rest, result)
        elif section.key == "accruals":
            _accrual_row(i, section, rest, result)
        elif section.key == "positions":
            positions.append((i, section, rest))
        elif section.key == "instruments":
            symbol, isin = section.get(rest, "symbol"), section.get(rest, "isin")
            if symbol and _ISIN.fullmatch(isin):
                isins[symbol.upper()] = isin.upper()
            if symbol:
                suffix = _VENUE_SUFFIX.get(_norm(section.get(rest, "exchange")))
                if suffix:
                    venues[symbol.upper()] = suffix

    if not recognised:
        return ParseResult(
            skipped=[{
                "row": 1,
                "type": "header",
                "reason": (
                    "not an IBKR activity statement — no Trades/Dividends/"
                    "Open Positions section with the expected columns"
                ),
            }]
        )
    _pair_withholding(result)
    # The period the statement covers is what the holdings are valued on; the
    # moment the file was generated is a fallback, and it is a day later when
    # the statement is cut overnight.
    _positions(
        positions, result, dates.get("period") or dates.get("generated", ""), isins
    )
    # Last, because the instrument table is at the end of the file: the trades
    # above were booked before their listing venue was known.
    _qualify_listings(result, venues)
    return result


def _qualify_listings(result: ParseResult, venues: dict[str, str]) -> None:
    """Point each booked symbol at the listing the statement actually reports.

    A no-op for a US book, where the bare symbol is the right one, and for any
    venue `_VENUE_SUFFIX` does not know. The skipped rows keep the symbol IBKR
    printed: they are the audit trail of what the file said, not holdings.
    """
    for tx in result.transactions:
        suffix = venues.get(tx.ticker.upper())
        if suffix and not tx.ticker.upper().endswith(suffix):
            tx.ticker += suffix


# ------------------------------------------------------------------- sections
def _statement_date(row: list[str], into: dict[str, str]) -> None:
    """Record the statement's Period and WhenGenerated days, when readable.

    Both are free text ("Septiembre 14, 2026", or a range), so the *last*
    date in the line is taken: a period that spans months ends on the day the
    positions were valued, which is the one an opening snapshot belongs on.
    """
    which = {
        "period": "period", "periodo": "period", "whengenerated": "generated",
    }.get(_norm(row[0]))
    if not which:
        return
    value = " ".join(row[1:])
    iso = _ISO_DATE.findall(value)
    if iso:
        into[which] = iso[-1]
        return
    for month_name, day, year in reversed(_LONG_DATE.findall(value)):
        month = _MONTHS.get(_norm(month_name))
        if month:
            into[which] = f"{int(year):04d}-{month:02d}-{int(day):02d}"
            return


def _trade_row(
    line: int, section: _Section, row: list[str], result: ParseResult
) -> None:
    if "discriminator" in section.cols and section.get(row, "discriminator") != "Order":
        return  # ClosedLot / SubTotal / Total — derived lines, not events
    category = section.get(row, "category")
    ticker = section.get(row, "symbol")
    qty = money(section.get(row, "quantity"))
    try:
        if _norm(category) not in _EQUITY:
            raise ValueError(f"asset category {category or '?'} — not auto-imported")
        if not ticker:
            raise ValueError("missing symbol")
        date = parse_date(section.get(row, "date").split(",", 1)[0])
        price = money(section.get(row, "price"))
        if qty == 0:
            raise ValueError("trade row has no quantity")
        if price <= 0:
            raise ValueError(f"trade row has non-positive price {price:g}")
        result.transactions.append(
            Transaction(
                date=date,
                ticker=ticker,
                action="buy" if qty > 0 else "sell",
                quantity=abs(qty),
                price=price,
                currency=section.get(row, "currency") or "USD",
                fee=abs(money(section.get(row, "fee"))),
                note="ibkr",
            )
        )
    except ValueError as exc:
        result.skipped.append(
            _skip(line, section, row, category or "trade", str(exc), ticker, qty)
        )


def _dividend_row(
    line: int, section: _Section, row: list[str], result: ParseResult
) -> None:
    currency = section.get(row, "currency")
    if not currency or _norm(currency).startswith("total"):
        return  # per-currency summary line
    desc = section.get(row, "description")
    try:
        m = _DESC_TICKER.match(desc)
        if not m:
            raise ValueError(f"cannot read ticker from description {desc!r}")
        amount = money(section.get(row, "amount"))
        if amount <= 0:
            raise ValueError(f"dividend amount {amount:g} is not positive")
        result.transactions.append(
            Transaction(
                date=parse_date(section.get(row, "date")),
                ticker=m.group(1).strip(),
                action="dividend",
                price=amount,
                currency=currency,
                note="ibkr",
            )
        )
    except ValueError as exc:
        result.skipped.append(
            _skip(line, section, row, "dividend", str(exc), "", 0.0)
        )


def _withholding_row(
    line: int, section: _Section, row: list[str], result: ParseResult
) -> None:
    currency = section.get(row, "currency")
    if not currency or _norm(currency).startswith("total"):
        return
    m = _DESC_TICKER.match(section.get(row, "description"))
    result.skipped.append({
        "row": line,
        "type": "withholding tax",
        "reason": (
            "withholding tax — set it as the fee on the matching dividend "
            "row for the double-tax credit"
        ),
        "date": section.get(row, "date"),
        "ticker": m.group(1).strip() if m else "",
        "quantity": 0.0,
        "amount": money(section.get(row, "amount")),
        "currency": currency,
    })


def _pair_withholding(result: ParseResult) -> None:
    """Fold each unambiguous withholding row into the dividend it taxes.

    Without this the year reads its gross as its net: `dividends.by_year`
    takes the withheld tax from the dividend row's fee, and nothing else in
    the app ever looks at the skipped list. The pairing is deliberately timid
    — one dividend and one tax line for the same (ticker, day, currency) — so
    a restated payment is never netted against the wrong line; those keep the
    pointer that asks the reader to place them.
    """
    taxes: dict[tuple[str, str, str], list[dict]] = {}
    for row in result.skipped:
        if row.get("type") != "withholding tax":
            continue
        key = (row.get("ticker", ""), row.get("date", ""), row.get("currency", ""))
        if all(key):
            taxes.setdefault(key, []).append(row)

    dividends: dict[tuple[str, str, str], list[Transaction]] = {}
    for tx in result.transactions:
        if tx.action == "dividend":
            dividends.setdefault((tx.ticker, tx.date, tx.currency), []).append(tx)

    for key, rows in taxes.items():
        paid = dividends.get(key, [])
        if len(rows) != 1 or len(paid) != 1 or paid[0].fee:
            continue
        amount = abs(rows[0].get("amount") or 0.0)
        if not amount:
            continue
        paid[0].fee = amount
        rows[0]["reason"] = (
            f"withholding tax — applied as the fee on that day's {key[0]} "
            "dividend, for the double-tax credit"
        )


def _accrual_row(
    line: int, section: _Section, row: list[str], result: ParseResult
) -> None:
    """An accrued dividend: announced, not yet paid. Read, then left out."""
    ticker = section.get(row, "symbol")
    category = section.get(row, "category")
    if not ticker or _norm(category).startswith("total"):
        return  # the section's own opening/closing balance lines
    result.skipped.append({
        "row": line,
        "type": "accrued dividend",
        "reason": (
            "accrued dividend — not cash yet; it imports from the Dividends "
            "section of the statement covering its pay date"
        ),
        "date": section.get(row, "date"),
        "ticker": ticker.upper(),
        "quantity": money(section.get(row, "quantity")),
        "amount": money(section.get(row, "amount")),
        "currency": section.get(row, "currency").upper(),
    })


def _positions(
    rows: list[tuple[int, _Section, list[str]]],
    result: ParseResult,
    as_of: str,
    isins: dict[str, str] | None = None,
) -> None:
    """Open holdings as arriving shares — only for a statement with no movements.

    A statement that covers a period with activity carries those trades, and
    the same shares must not arrive twice; there, the holdings are the closing
    balance of what was just imported and are dropped silently. It is the
    statement with nothing in it — a single day, a quiet week — where the
    positions block is the only thing that says what is held, and turning it
    into dated lots is the only way that file can enter the ledger at all.

    They import as `transfer_in`, not as buys, because that is what a balance
    is: shares that were already owned before this file was written. Nobody
    bought them on the statement date, and a book that already holds them —
    because the broker they came from *was* imported — must not gain a second
    copy. stocks.portfolio.transfers nets those against the departure and
    promotes the rest to opening lots, so a first-ever import still behaves
    exactly as it used to. `price` is IBKR's own average cost, which is the
    basis the shares carry in; the ISIN from the instrument table rides along
    in the note so the same security can be recognised under a broker label
    that spells it differently.
    """
    if not rows:
        return
    if result.transactions:
        result.skipped.append({
            "row": rows[0][0],
            "type": "open positions",
            "reason": (
                f"{len(rows)} holdings listed — this statement carries its own "
                "trades, so the positions block is their closing balance, not "
                "a separate purchase"
            ),
            "date": as_of, "ticker": "", "quantity": 0.0,
            "amount": 0.0, "currency": "",
        })
        return
    for line, section, row in rows:
        if "discriminator" in section.cols:
            if section.get(row, "discriminator") != "Summary":
                continue  # Lot / Total breakdowns of the same holding
        category = section.get(row, "category")
        ticker = section.get(row, "symbol")
        qty = money(section.get(row, "quantity"))
        try:
            if not as_of:
                raise ValueError(
                    "statement has no period date to put the opening lot on"
                )
            if _norm(category) not in _EQUITY:
                raise ValueError(
                    f"asset category {category or '?'} — not auto-imported"
                )
            if not ticker:
                raise ValueError("missing symbol")
            if qty <= 0:
                raise ValueError(f"holding has no positive quantity ({qty:g})")
            price = money(section.get(row, "price"))
            if price <= 0:
                # Some locales round the per-share cost away; the basis is
                # always there and divides back to the same number.
                price = money(section.get(row, "basis")) / qty
            if price <= 0:
                raise ValueError("holding has no cost price")
            isin = (isins or {}).get(ticker.upper(), "")
            result.transactions.append(
                Transaction(
                    date=parse_date(as_of),
                    ticker=ticker,
                    action=TRANSFER_IN,
                    quantity=qty,
                    price=price,
                    currency=section.get(row, "currency") or "USD",
                    note=f"ibkr snapshot {isin}".strip(),
                )
            )
        except ValueError as exc:
            result.skipped.append(
                _skip(line, section, row, category or "open position", str(exc),
                      ticker, qty)
            )


def _skip(
    line: int, section: _Section, row: list[str], rtype: str, reason: str,
    ticker: str, qty: float,
) -> dict:
    return {
        "row": line,
        "type": rtype,
        "reason": reason,
        "date": section.get(row, "date").split(",", 1)[0],
        "ticker": ticker.upper(),
        "quantity": qty,
        "amount": money(
            section.get(row, "amount") or section.get(row, "proceeds")
            or section.get(row, "basis")
        ),
        "currency": section.get(row, "currency").upper(),
    }
