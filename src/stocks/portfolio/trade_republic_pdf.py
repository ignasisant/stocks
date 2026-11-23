"""Parse a Trade Republic "Account statement" PDF into ledger Transactions.

The statement the app hands out under Profile → Account statements is a PDF:
a summary of the cash account, then a table of every booking — date, type,
description, money in, money out, balance. It is not the CSV "Transaction
export" (`trade_republic.parse_csv`), and readers upload it because it is the
first file the app offers them.

The layout was taken from the pdf-to-text samples Portfolio Performance keeps
as test resources (English, Spanish, German and Italian statements, 2024–2026),
not from a statement uploaded here, so the parser is strict about what it
claims to understand and reports everything else as skipped:

* The table's section title names the document — ACCOUNT TRANSACTIONS,
  TRANSACCIONES DE CUENTA, UMSATZÜBERSICHT, TRANSAZIONI SUL CONTO — and every
  page repeats its column header (DATUM TYP BESCHREIBUNG …), which opens the
  table too: a page cut out of a statement has no title.
* A booking starts on a line opening with a day and a month name ("24 Sep",
  "03 nov", "02 Jan.", "04 Juni") and runs until the next one. The cell
  wraps freely: the year sits on the same line, on a line of its own, or in
  the middle of the description ("quantity: 2024 100"); the type word and the
  amounts can land on the second line, between halves of the security's name.
  So a booking is read by pattern from its joined lines, not by column.
* In the statements the app makes today pdfplumber stacks the date cell: the
  day alone on a line, the month (with the type word and the amounts) on a
  later one, the year last — and a line of the description, or the quantity
  itself, can fall between them. Such a booking runs from its day to its year.
* The quantity can run straight into the amount ("quantity: 302.324,47 €" is
  30 shares for 2.324,47 €). Only the balance can split that: the amount is
  the change in balance, and what is left before it is the quantity. Without
  the balance before it the booking is skipped, never guessed.
* The page footer (Trade Republic Bank GmbH …, "Seite 2 von 22") ends the
  booking above it.
* The description stays English in every app language: "Buy trade",
  "Sell trade", "Savings plan execution" with the ISIN and "quantity: N"
  (always a decimal point), and "Cash Dividend for ISIN …". The type word is
  translated (Trade, Comercio, Handel, Commercio) and only skipped over.
* The last two amounts are the booking's and the balance after it. When the
  previous balance plus or minus the amount reconciles, that says which way
  the cash went; a trade whose wording says the opposite is skipped rather
  than booked backwards.
* There is no fee or tax column. A trade's price is its cash over its
  quantity, so the €1 order fee (and, on a sale, any tax withheld) is inside
  it; a dividend books what was paid out, net of withholding.

Shares import under their ISIN, as from the CSV export; Trade Republic's
crypto ISINs (XF000BTC0017) import as the Yahoo pair in euros. The pre-2024
"Kontoauszug" prints trades without a quantity and is refused with a pointer
to the CSV export.
"""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

from stocks.data import crypto
from stocks.portfolio import upload_guard
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult
from stocks.portfolio.trade_republic import CASH, INTEREST, NOTE, TAX, UNKNOWN

# The title over the bookings table, per app language. The document is only
# read when one of these is on a line of its own.
_SECTIONS = (
    "ACCOUNT TRANSACTIONS",
    "TRANSACCIONES DE CUENTA",
    "UMSATZÜBERSICHT",
    "TRANSAZIONI SUL CONTO",
)
# Every page's column header: DATE TYPE …, DATUM TYP …, FECHA TIPO …, DATA TIPO ….
_COLUMNS_RE = re.compile(r"^(?:DATE|DATUM|FECHA|DATA)\s+(?:TYPE|TYP|TIPO)\b")
# The page footer: the bank's name opening a line, or "Page 2 of 22".
_FOOTER_RE = re.compile(
    r"^Trade Republic Bank GmbH\b"
    r"|\b(?:Page|Seite|Página|Pagina) \d+ (?:of|von|de|di) \d+\b",
    re.IGNORECASE,
)
# The summary table's header; the first row under it holds the opening balance.
_SUMMARY_RE = re.compile(r"^(PRODUCT|PRODUCTO|PRODUKT|PRODOTTO)\b")
# The older statement (to mid-2023): dated 03.04.2023 rows, no quantity.
_OLD_LAYOUT = re.compile(r"\bBUCHUNGSTAG\b")

REFUSAL = "not a Trade Republic account statement"
OLD_LAYOUT = (
    "older Trade Republic statement — it prints no quantities; export "
    "Profile → Account statements → Transaction export (CSV) instead"
)
NO_QUANTITY = "trade without a quantity — not imported; the CSV Transaction export has it"
NO_AMOUNT = "no amount on this line"
NO_DATE = "no year on this line"
CONTRADICTS = "wording and balance disagree on the direction — not imported"
GLUED = "quantity and amount run together and no balance to split them — not imported"

_MONTHS = {
    m: i + 1
    for i, names in enumerate([
        ("jan", "january", "ene", "enero", "januar", "gen", "gennaio"),
        ("feb", "february", "febrero", "februar", "febbraio"),
        ("mar", "march", "marzo", "mär", "märz"),
        ("apr", "april", "abr", "abril", "aprile"),
        ("may", "mayo", "mai", "mag", "maggio"),
        ("jun", "june", "junio", "juni", "giu", "giugno"),
        ("jul", "july", "julio", "juli", "lug", "luglio"),
        ("aug", "august", "ago", "agosto"),
        ("sep", "sept", "september", "septiembre", "set", "settembre"),
        ("oct", "october", "octubre", "okt", "oktober", "ott", "ottobre"),
        ("nov", "november", "noviembre", "novembre"),
        ("dec", "december", "dic", "diciembre", "dez", "dezember", "dicembre"),
    ])
    for m in names
}

# "24 Sep 2024 Trade …", "03 nov ", "02 Jan. ", "04 Juni Handel …".
_START_RE = re.compile(r"^(\d{1,2}) ([^\W\d_]{3,10})\.?(?: (\d{4}))?(?=\s|$)")
_YEAR_LINE_RE = re.compile(r"^((?:19|20)\d{2})(?=\s|$)")
# A stacked date cell's day, alone or ahead of a line of the description.
_DAY_RE = re.compile(r"^(\d{1,2})(?:\s+(.*))?$")
# The stacked cell's month, opening its line: "Sept. Handel 9.028,00 € …".
_MONTH_LEAD_RE = re.compile(r"^([^\W\d_]{3,10})\.?(?=\s|$)")
# The quantity run into the amount: "quantity: 302.324,47 €".
_GLUED_RE = re.compile(r"quantity:\s*(\d[\d.,]*[.,]\d{2})\s?€", re.IGNORECASE)
# A year dropped into the description by the wrap; never part of a number.
_YEAR_RE = re.compile(r"(?<![\d.,])(?:19|20)\d{2}(?![\d.,])")
_MONEY_RE = re.compile(
    r"€\s?(?P<pre>\d{1,3}(?:[.,]\d{3})*[.,]\d{2})(?!\d)"
    r"|(?<![\d.,])(?P<suf>\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s?€"
)
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")
_QUANTITY_RE = re.compile(r"\bquantity:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_DIVIDEND_RE = re.compile(r"\bDividend for ISIN ([A-Z]{2}[A-Z0-9]{9}\d)\b", re.IGNORECASE)
_BUY_RE = re.compile(r"\b(?:Buy trade|Savings plan execution|Saveback execution)\b",
                     re.IGNORECASE)
_SELL_RE = re.compile(r"\bSell trade\b", re.IGNORECASE)
_TAX_RE = re.compile(r"\b(?:Vorabpauschale|Tax Optimisation|steueroptimierung)",
                     re.IGNORECASE)
_INTEREST_RE = re.compile(r"\binterest payment\b", re.IGNORECASE)
# The translated type words that land between halves of a security's name.
_TYPE_WORDS = re.compile(r"\b(?:Trade|Comercio|Handel|Commercio)\b")
# Trade Republic's crypto pseudo-ISINs: XF000BTC0017, XF000ETH0019.
_CRYPTO_RE = re.compile(r"^XF000([A-Z]{2,5})\d{4}$")


def parse_pdf(source: str | Path | bytes) -> ParseResult:
    """Extract the bookings table from a Trade Republic account statement."""
    import pdfplumber  # heavy import, only needed on the PDF path

    opened = io.BytesIO(source) if isinstance(source, bytes) else source
    lines: list[str] = []
    with pdfplumber.open(opened) as pdf:
        for number, page in enumerate(upload_guard.pages(pdf)):
            lines += (page.extract_text() or "").splitlines()
            # The cascade hands every PDF to this parser before Revolut's, so a
            # first page with no trace of Trade Republic ends the read there.
            if number == 0 and not _ours(lines):
                break
    return parse_lines(lines)


def _ours(lines: list[str]) -> bool:
    """Whether a statement's first page could be Trade Republic's."""
    text = "\n".join(line.strip() for line in lines)
    return bool(
        "TRADE REPUBLIC" in text.upper()
        or any(title in text for title in _SECTIONS)
        or any(_SUMMARY_RE.match(line.strip()) for line in lines)
        or _OLD_LAYOUT.search(text)
    )


def parse_lines(lines: list[str]) -> ParseResult:
    """The whole PDF path minus text extraction; separate for testability."""
    stripped = [line.strip() for line in lines]
    if not any(line in _SECTIONS or _COLUMNS_RE.match(line) for line in stripped):
        reason = OLD_LAYOUT if any(_OLD_LAYOUT.search(s) for s in stripped) else REFUSAL
        return ParseResult(skipped=[{"row": 0, "type": "file", "reason": reason}])
    result = ParseResult()
    balance = _opening(stripped)
    year: int | None = None
    for number, record in _records(stripped):
        booking = _Booking(record, year)
        year = booking.year or year
        balance = _read(result, number, booking, balance)
    return result


def _opening(lines: list[str]) -> float | None:
    """The opening balance: the first amount of the first summary row."""
    for i, line in enumerate(lines):
        if _SUMMARY_RE.match(line):
            for row in lines[i + 1:i + 4]:
                amounts = _amounts(row)
                if len(amounts) == 4:
                    return amounts[0]
            return None
    return None


def _records(lines: list[str]) -> list[tuple[int, list[str]]]:
    """Each booking's lines, with the line number it starts on."""
    out: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    inside = False
    # A booking whose year has not come yet: a lone number inside it is the
    # wrapped quantity, not the next booking's day.
    awaiting = False
    for index, line in enumerate(lines):
        number = index + 1
        if line in _SECTIONS or _COLUMNS_RE.match(line):
            inside, current, awaiting = True, None, False
            continue
        if not inside or not line:
            continue
        if _FOOTER_RE.search(line):
            current, awaiting = None, False
            continue
        start = _START_RE.match(line)
        if start and start.group(2).lower() in _MONTHS:
            current = [line]
            out.append((number, current))
            awaiting = start.group(3) is None
        elif not awaiting and _stacked_day(lines, index):
            current = [line]
            out.append((number, current))
            awaiting = True
        elif _heading(line) and (
            current is None or len(_amounts(" ".join(current))) >= 2
        ):
            # A page's column header, or the cash and fund tables after the
            # bookings: never part of a booking that already has its amounts.
            # Before them, a line in capitals is the security's name wrapping.
            current = None
        elif current is not None:
            current.append(line)
            if awaiting and _YEAR_LINE_RE.match(line):
                awaiting = False
    return out


def _month_lead(line: str) -> re.Match[str] | None:
    found = _MONTH_LEAD_RE.match(line)
    return found if found and found.group(1).lower() in _MONTHS else None


def _stacked_day(lines: list[str], index: int) -> bool:
    """A day alone (or ahead of the description) whose month comes within
    the next three lines, before any year."""
    found = _DAY_RE.match(lines[index])
    if not found or not 1 <= int(found.group(1)) <= 31:
        return False
    for line in lines[index + 1:index + 4]:
        if _YEAR_LINE_RE.match(line) or _START_RE.match(line):
            return False
        if _month_lead(line):
            return True
    return False


def _heading(line: str) -> bool:
    """An all-capitals line of words: a section title or a column header."""
    letters = [c for c in line if c.isalpha()]
    return (len(letters) >= 6 and not any(c.isdigit() for c in line)
            and all(c.isupper() for c in letters))


def _amounts(text: str) -> list[float]:
    return [_number(m.group("pre") or m.group("suf")) for m in _MONEY_RE.finditer(text)]


def _number(token: str) -> float:
    """An amount, always printed with two decimals: "1.071,00" or "1,071.00"."""
    decimal = token[-3]
    whole = token[:-3].replace("." if decimal == "," else ",", "")
    return float(f"{whole}.{token[-2:]}")


class _Booking:
    """One booking's joined text, its date, and the amounts in it."""

    def __init__(self, lines: list[str], last_year: int | None) -> None:
        start = _START_RE.match(lines[0])
        year: int | None = None
        if start and start.group(2).lower() in _MONTHS:
            day, month = int(start.group(1)), _MONTHS[start.group(2).lower()]
            rest = [lines[0][start.end():].strip(), *lines[1:]]
            year = int(start.group(3)) if start.group(3) else None
        else:  # the stacked cell: day, then the month a line or two below
            found = _DAY_RE.match(lines[0])
            assert found is not None
            day, rest = int(found.group(1)), [found.group(2) or "", *lines[1:]]
            at = next(i for i in range(1, len(rest)) if _month_lead(rest[i]))
            lead = _month_lead(rest[at])
            assert lead is not None
            month = _MONTHS[lead.group(1).lower()]
            rest[at] = rest[at][lead.end():].strip()
        if year is None:
            for i, line in enumerate(rest[1:], start=1):
                found = _YEAR_LINE_RE.match(line)
                if found:
                    year = int(found.group(1))
                    rest[i] = line[found.end():].strip()
                    break
        text = " ".join(part for part in rest if part)
        if year is None:
            found = _YEAR_RE.search(text)
            if found:
                year = int(found.group())
                text = f"{text[:found.start()]} {text[found.end():]}"
        self.year = year
        self.text = " ".join(text.split())
        try:
            self.date = date(year or last_year or 0, month, day).isoformat()
        except ValueError:
            self.date = ""
        amounts = _amounts(self.text)
        glued = _GLUED_RE.search(self.text)
        self.glued = glued.group(1) if glued else None
        self.amount = amounts[-2] if len(amounts) >= 2 else None
        # A glued amount may not read as one, leaving the balance alone.
        enough = 1 if self.glued else 2
        self.balance = amounts[-1] if len(amounts) >= enough else None

    @property
    def words(self) -> str:
        """The text without its amounts or the translated type word."""
        return " ".join(_TYPE_WORDS.sub(" ", _MONEY_RE.sub(" ", self.text)).split())


def _read(result: ParseResult, number: int, b: _Booking,
          balance: float | None) -> float | None:
    """Book or skip one booking; returns the balance after it."""
    def skip(reason: str) -> float | None:
        result.skipped.append({
            "row": number, "type": _kind(b.words), "reason": reason,
            "date": b.date, "amount": b.amount,
        })
        return b.balance if b.balance is not None else balance

    amount, quantity_text = b.amount, None
    if b.glued and b.balance is not None:
        split = _unglue(b.glued, balance, b.balance)
        if split is not None:
            quantity_text, amount = split
    if amount is None or b.balance is None:
        return skip(GLUED if b.glued else NO_AMOUNT)
    if not b.date:
        return skip(NO_DATE)
    flow = _flow(balance, amount, b.balance)
    dividend = _DIVIDEND_RE.search(b.text)
    if _TAX_RE.search(b.text):
        return skip(TAX)
    if dividend:
        if flow == "out":
            return skip(CONTRADICTS)
        result.transactions.append(Transaction(
            date=b.date, ticker=_ticker(dividend.group(1)), action="dividend",
            price=amount, currency="EUR", note=f"{NOTE} dividend, net"[:120],
        ))
        return b.balance
    isin = next((m.group(1) for m in _ISIN_RE.finditer(b.text)
                 if _isin_ok(m.group(1))), None)
    if isin is None:
        return skip(INTEREST if _INTEREST_RE.search(b.text) else CASH)
    # Read from the words: a wrapped quantity sits past the amounts.
    quantity = quantity_text or (
        found.group(1) if (found := _QUANTITY_RE.search(b.words)) else None)
    if quantity is None:
        return skip(GLUED if b.glued else NO_QUANTITY)
    said = (
        "buy" if _BUY_RE.search(b.text)
        else "sell" if _SELL_RE.search(b.text)
        else None
    )
    went = {"out": "buy", "in": "sell"}.get(flow or "")
    if said and went and said != went:
        return skip(CONTRADICTS)
    action = said or went
    qty = float(quantity)
    if action is None:
        return skip(UNKNOWN)
    if qty <= 0 or amount <= 0:
        return skip(NO_QUANTITY)
    result.transactions.append(Transaction(
        date=b.date, ticker=_ticker(isin), action=action, quantity=qty,
        price=amount / qty, currency="EUR", note=_note(b.words, isin),
    ))
    return b.balance


def _unglue(token: str, before: float | None,
            after: float) -> tuple[str, float] | None:
    """Split "302.324,47" into the quantity "30" and the amount 2324.47, by
    the change in balance; None when the balance cannot say."""
    if before is None:
        return None
    delta = round(abs(after - before), 2)
    whole, cents = f"{delta:.2f}".split(".")
    grouped = f"{int(whole):,}"
    for shape in (f"{grouped.replace(',', '.')},{cents}", f"{whole},{cents}",
                  f"{grouped}.{cents}", f"{whole}.{cents}"):
        head = token[:-len(shape)]
        if token.endswith(shape) and re.fullmatch(r"\d+(?:\.\d+)?", head):
            return head, delta
    return None


def _flow(before: float | None, amount: float, after: float) -> str | None:
    """Which way the cash went, when the balances say so unambiguously."""
    if before is None:
        return None
    came_in = abs(before + amount - after) < 0.011
    went_out = abs(before - amount - after) < 0.011
    if came_in == went_out:
        return None
    return "in" if came_in else "out"


def _isin_ok(code: str) -> bool:
    """The ISIN check digit (Luhn over the letters spelled as numbers)."""
    digits = "".join(str(int(c, 36)) for c in code[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n // 10 + n % 10
    return (10 - total % 10) % 10 == int(code[-1])


def _ticker(isin: str) -> str:
    coin = _CRYPTO_RE.match(isin)
    if coin and coin.group(1) in crypto.CRYPTO_NAMES:
        return crypto.to_pair(coin.group(1), "EUR")
    return isin


def _note(words: str, isin: str) -> str:
    """NOTE plus the security's name, as the CSV parser files it."""
    _, _, after = words.partition(isin)
    name = re.split(r",?\s*quantity:", after, flags=re.IGNORECASE)[0]
    return f"{NOTE} {' '.join(name.split())}".strip()[:120]


def _kind(words: str) -> str:
    """A short label for a skipped booking: its first words, no figures."""
    # Two words: a third is a card payment's merchant.
    return " ".join(w for w in words.split()[:2] if not any(c.isdigit() for c in w))[:40]
