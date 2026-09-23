"""The contract every broker-statement parser shares.

Each broker gets its own module (revolut, trading212, degiro, ibkr, …) because
each export is its own dialect — positional currency columns in DEGIRO,
sections in IBKR, locale-formatted numbers almost everywhere. What they have
in common is this module: the result type they all return, the primitives for
reading a money or date cell, and — for the DictReader-shaped exports — the
row loop itself.

This lived in `revolut.py` until every other parser ended up importing
`ParseResult`, `_money` and `_parse_date` from it, which made the first broker
we happened to support look like the base class for all of them. It isn't;
this module is.

Two layers, use whichever fits the dialect:

* **Primitives** — `ParseResult`, `money`, `parse_date`, `resolve_columns`,
  `Row`, plus the `implied_fee` / `check_consistency` pair that turns a
  cash total into a commission. The positional and section-based parsers use
  these and drive their own loop.
* **`parse_csv(text, fmt)`** — the whole DictReader pipeline for exports that
  are one flat row per event: resolve columns, refuse the file if a required
  one is absent, map each row's type to a ledger action, build or skip. A
  broker supplies a `CsvFormat` describing only what differs.

Nothing here writes to the ledger; callers preview a ParseResult and commit.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from stocks.portfolio.ledger import Transaction


@dataclass
class ParseResult:
    """Outcome of parsing one statement: importable rows plus a human-readable
    audit of everything that was left out."""

    transactions: list[Transaction] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {row, type, reason}

    @property
    def summary(self) -> str:
        n = len(self.transactions)
        return f"{n} importable, {len(self.skipped)} skipped"


# ------------------------------------------------------------------ primitives
# Tried in order against an upload. utf-8-sig covers UTF-8 with or without the
# BOM Excel writes; cp1252 is what a Windows-authored European export is, and
# it is a superset of latin-1 over the bytes brokers actually emit (curly
# quotes, the euro sign). The last one decodes any byte sequence, so `decode`
# always returns.
ENCODINGS = ("utf-8-sig", "cp1252")


def decode(data: bytes) -> str:
    """Statement text from upload bytes, whatever the export was saved as.

    Every caller used to hard-code `utf-8-sig`, so an export in a Windows
    codepage — a Spanish broker's "Comisión" column, a name with an accent —
    raised UnicodeDecodeError out of the parser and reached the reader as a
    crash page rather than as a statement.
    """
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode(ENCODINGS[-1], errors="replace")


def money(value: str | None) -> float:
    """Parse a money/number field: strip currency symbols and thousands commas.

    US formatting only — "1.234,56" reads as 1.23456 here, so exports in a
    European locale must normalise before calling (see degiro._num).
    """
    v = (value or "").strip()
    if not v:
        return 0.0
    kept = [c for c in v if c.isdigit() or c in ".-"]
    cleaned = "".join(kept)
    if cleaned in ("", "-", ".", "-."):
        return 0.0
    return float(cleaned)


def parse_date(value: str | None) -> str:
    """ISO YYYY-MM-DD from a date or ISO-timestamp field."""
    v = (value or "").strip()
    if not v:
        raise ValueError("missing date")
    # ISO timestamp "2023-01-03T14:30:00.000Z" -> "2023-01-03"; plain date passes.
    head = v.split("T", 1)[0].split(" ", 1)[0]
    parts = head.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return head
    raise ValueError(f"unrecognised date {v!r}")


def resolve_columns(
    fieldnames: Sequence[str], aliases: Mapping[str, tuple[str, ...]]
) -> dict[str, str]:
    """Map logical keys to the export's actual header names.

    Matching is case-insensitive and whitespace-tolerant; the first alias that
    is present wins, and a key with no match is simply absent from the result.
    """
    lower = {name.strip().lower(): name for name in fieldnames if name}
    resolved: dict[str, str] = {}
    for key, names in aliases.items():
        for alias in names:
            if alias in lower:
                resolved[key] = lower[alias]
                break
    return resolved


class Row:
    """One raw CSV row, read through the resolved column map.

    Every accessor tolerates an absent column — a statement that never had a
    `currency` header must read as "" rather than blowing up mid-file.
    """

    __slots__ = ("raw", "col", "number")

    def __init__(self, raw: dict, col: Mapping[str, str], number: int) -> None:
        self.raw = raw
        self.col = col
        self.number = number  # 1-based line in the file, header included

    def text(self, key: str) -> str:
        name = self.col.get(key)
        return (self.raw.get(name) or "").strip() if name else ""

    def upper(self, key: str) -> str:
        return self.text(key).upper()

    def money(self, key: str) -> float:
        return money(self.text(key))

    def empty(self, keys: Sequence[str]) -> bool:
        """True when none of `keys` holds anything — a blank line."""
        return not any(self.text(k) for k in keys)


def check_consistency(action: str, qty: float, price: float, amount: float) -> None:
    """Reject rows whose qty×price strays >2% from the cash total.

    Within 2% the gap is cent-rounding of the per-share price plus commission
    (absorbed by `implied_fee`); beyond it the row is corrupt — wrong column,
    truncated number — and importing it would silently distort cost basis.
    """
    if amount <= 0:  # blank total: price was derived from it or row has none
        return
    gross = qty * price
    if abs(gross - amount) > max(amount * 0.02, qty * 0.005 + 0.01):
        raise ValueError(
            f"{action} row inconsistent: {qty:g} × {price:g} = {gross:.2f} "
            f"but total is {amount:.2f} ({abs(gross - amount) / amount:.1%} off)"
        )


def implied_fee(action: str, qty: float, price: float, amount: float) -> float:
    """Commission implied by the cash total vs qty×price.

    A statement's total is cash actually moved: buys cost qty×price + fee,
    sells credit qty×price − fee. The per-share price is rounded to cents, so
    only a difference beyond rounding noise yet within 2% is trusted as a fee;
    anything larger is left at 0 for the validation layer to flag.
    """
    if amount <= 0:
        return 0.0
    gross = qty * price
    fee = (amount - gross) if action == "buy" else (gross - amount)
    # qty*0.005: worst-case cent rounding of the per-share price.
    if fee <= qty * 0.005 + 0.01 or fee > amount * 0.02:
        return 0.0
    return round(fee, 2)


# ------------------------------------------------------- the DictReader pipeline
@dataclass(frozen=True)
class CsvFormat:
    """Everything that differs between one flat-CSV broker export and the next.

    `action_of` returns the ledger action for a row's type string, or None to
    skip it; `skip_reason` then explains the skip in the user's words.
    `audit` adds the broker's own fields to a skipped entry — the preview
    table and validate.resolve_splits read `date`/`ticker`/`quantity`/
    `amount`/`currency` off those, so a parser that drops them makes split
    ratios underivable.
    """

    columns: Mapping[str, tuple[str, ...]]
    type_key: str
    action_of: Callable[[str], str | None]
    skip_reason: Callable[[str], str]
    build: Callable[[Row, str], Transaction]
    audit: Callable[[Row], dict]
    # Logical keys that must resolve, else the whole file is refused. Strict
    # parsers set this so another broker's statement is never half-imported.
    required: tuple[str, ...] = ()
    refusal: str = "missing column(s): "
    # Logical keys that are all blank on a padding line worth ignoring
    # silently, rather than reporting as a skipped row.
    blank_when_empty: tuple[str, ...] = ()


def skip_entry(fmt: CsvFormat, row: Row, rtype: str) -> dict:
    """The audit record for a row that did not become a Transaction."""
    return {
        "row": row.number,
        "type": rtype,
        "reason": fmt.skip_reason(rtype),
        **fmt.audit(row),
    }


def parse_rows(
    rows: list[dict], fmt: CsvFormat, col: Mapping[str, str] | None = None
) -> ParseResult:
    """Run already-read rows through the pipeline.

    `col` maps logical keys to the dicts' actual header names; None means the
    rows already use canonical keys (the PDF extractor emits those).
    """
    if col is None:
        col = {k: k for k in fmt.columns}
    result = ParseResult()
    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        row = Row(raw, col, i)
        rtype = row.text(fmt.type_key)
        if fmt.blank_when_empty and row.empty(fmt.blank_when_empty):
            continue
        action = fmt.action_of(rtype)
        if action is None:
            result.skipped.append(skip_entry(fmt, row, rtype))
            continue
        try:
            tx = fmt.build(row, action)
        except (KeyError, ValueError) as exc:
            entry = skip_entry(fmt, row, rtype)
            entry["reason"] = str(exc)
            result.skipped.append(entry)
            continue
        result.transactions.append(tx)
    return result


# Separators a broker export turns up with. Comma leads because a tie must
# resolve the way this module always did.
DELIMITERS = (",", ";", "\t", "|")


def sniff_delimiter(header: str, aliases: Mapping[str, tuple[str, ...]]) -> str:
    """The separator that resolves the most of `aliases` out of a header row.

    European exports are semicolon-delimited as often as comma-delimited, and
    reading one with the wrong separator does not fail loudly: the whole line
    becomes a single column, nothing resolves, and every row is skipped for
    want of a field that was there all along.

    Counting separator characters is the usual trick and the wrong one here —
    a comma file with semicolons inside a description column would be read as
    semicolon-delimited and break a statement that parses today. Scoring by
    how many columns each candidate actually resolves cannot regress that way:
    the wrong separator resolves nothing, so it loses.
    """
    best, best_score = DELIMITERS[0], -1
    for delimiter in DELIMITERS:
        try:
            names = next(csv.reader(io.StringIO(header), delimiter=delimiter))
        except (csv.Error, StopIteration):
            continue
        score = len(resolve_columns(names, aliases))
        if score > best_score:
            best, best_score = delimiter, score
    return best


def parse_csv(text: str, fmt: CsvFormat) -> ParseResult:
    """Parse flat-CSV statement text into a ParseResult (no side effects)."""
    head = text.splitlines()[0] if text.strip() else ""
    reader = csv.DictReader(
        io.StringIO(text), delimiter=sniff_delimiter(head, fmt.columns)
    )
    if reader.fieldnames is None:
        return ParseResult()
    col = resolve_columns(reader.fieldnames, fmt.columns)
    missing = [fmt.columns[k][0] for k in fmt.required if k not in col]
    if missing:
        return ParseResult(
            skipped=[{
                "row": 1,
                "type": "header",
                "reason": fmt.refusal + ", ".join(missing),
            }]
        )
    return parse_rows(list(reader), fmt, col)
