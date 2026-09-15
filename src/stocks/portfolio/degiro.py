"""Parse a DEGIRO Transactions.csv into ledger Transactions.

DEGIRO's transaction export (Actividad → Transacciones → Exportar → CSV) has
a positional quirk no DictReader survives: money columns are followed by
*unnamed* currency columns (``…,Price,,Local value,,…``), so rows are parsed
positionally and each money field's currency is read from the cell to its
right. English and Spanish headers are recognised; the parser refuses the
whole file unless the distinctive columns (date, product, ISIN, quantity,
price) are all found — a statement from another broker can never be
half-imported by accident (a ``Ticker`` header is an explicit refusal: DEGIRO
exports never have one).

Shape notes this parser absorbs:

* There is no ticker column — rows import with the **ISIN as the ticker**
  and the product name in the note. Validation flags each unknown ISIN with
  instructions to map it to a Yahoo symbol under ``aliases:`` in
  watchlist.yaml (the established EU-broker-code mechanism); prices won't
  resolve until then.
* Numbers are locale-formatted ("1.234,56" in the Spanish export) and dates
  are DD-MM-YYYY — both normalised here.
* Buy vs sell is the sign of the quantity column.
* Fees are split over several columns ("Transaction costs" / "Costes de
  transacción", "Comisión AutoFX") and billed in the **account** currency, so
  a USD trade carries EUR charges. They are summed, cross-checked against the
  row's own Total (``Value + costs == Total``), and converted into the trade
  currency with the row's own exchange rate. A charge that can't be
  reconciled that way imports as 0 rather than mixing currencies.
* Zero-price, zero-value rows are dropped silently: DEGIRO books a matching
  pair of them whenever it moves a holding between its tradeable and "NON
  TRADEABLE" listings. They net to nothing, so they are non-events rather
  than skips worth reporting.
* A product name DEGIRO wrapped onto a second line (a row with no date and no
  ISIN) is dropped rather than reported as a broken row.
* Each row is cross-checked against its own "Local value" column (qty × price
  within 2%) so a mis-detected decimal separator cannot corrupt cost basis.
* Dividends are NOT in Transactions.csv (they live in the Account statement)
  — import them via the generic CSV or add manually. Corporate actions
  (splits, ISIN changes) appear as ordinary buy/sell pairs and import as
  such; review those manually.

Nothing here writes to the ledger; the Import page previews and commits.
"""

from __future__ import annotations

import csv
import io

from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult

# Logical key -> accepted header names (lowercased), English and Spanish.
_HEADERS = {
    "date": ("date", "fecha"),
    "product": ("product", "producto"),
    "isin": ("isin",),
    "quantity": ("quantity", "número", "numero", "cantidad"),
    "price": ("price", "precio"),
    "local_value": ("local value", "valor local"),
    "fx_rate": ("exchange rate", "tipo de cambio"),
}
# Cost columns are matched by shape, not by exact name: DEGIRO splits one
# charge over several columns and localises each of them.
_COST_PREFIXES = ("transaction", "costes", "gastos")
_COST_CONTAINS = ("autofx",)
_REQUIRED = ("date", "product", "isin", "quantity", "price")


def parse_csv(text: str) -> ParseResult:
    """Parse DEGIRO Transactions.csv text into a ParseResult (no side effects)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ParseResult()
    header = [h.strip().lower() for h in rows[0]]

    if "ticker" in header:
        return _refuse("has a Ticker column — not a DEGIRO Transactions.csv")
    idx, costs = _find_columns(header)
    missing = [k for k in _REQUIRED if k not in idx]
    if missing:
        return _refuse(
            "not a DEGIRO Transactions.csv — missing column(s): " + ", ".join(missing)
        )

    result = ParseResult()
    for i, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue  # blank line
        if _is_continuation(row, idx) or _is_non_event(row, idx):
            continue  # a wrapped product name / a zero-value bookkeeping pair
        try:
            tx = _build_tx(header, row, idx, costs)
        except (IndexError, ValueError) as exc:
            result.skipped.append({
                "row": i,
                "type": _cell(row, idx.get("product")),
                "reason": str(exc),
                "date": _cell(row, idx.get("date")),
                "ticker": _cell(row, idx.get("isin")).upper(),
                "quantity": _num(_cell(row, idx.get("quantity"))),
                "amount": 0.0,
                "currency": "",
            })
            continue
        result.transactions.append(tx)
    return result


def _refuse(reason: str) -> ParseResult:
    return ParseResult(skipped=[{"row": 1, "type": "header", "reason": reason}])


def _find_columns(header: list[str]) -> tuple[dict[str, int], list[int]]:
    """Positional index of each logical column, plus every cost column.

    A money column carries its currency either in the *unnamed* cell to its
    right (the classic export) or as a suffix on its own header ("Total EUR");
    `_currency_of` reads whichever shape this file uses.
    """
    idx: dict[str, int] = {}
    for key, names in _HEADERS.items():
        for pos, name in enumerate(header):
            if name in names:
                idx[key] = pos
                break
    for pos, name in enumerate(header):
        if name.startswith("total"):
            idx.setdefault("total", pos)
        elif _is_base_value(name):
            idx.setdefault("base_value", pos)
    costs = [
        pos
        for pos, name in enumerate(header)
        if name.startswith(_COST_PREFIXES) or any(c in name for c in _COST_CONTAINS)
    ]
    return idx, costs


def _is_base_value(name: str) -> bool:
    """The account-currency value column ("Value", "Valor EUR") — not the local one."""
    if "local" in name:
        return False
    return name in ("value", "valor") or name.startswith(("value ", "valor "))


def _is_continuation(row: list[str], idx: dict[str, int]) -> bool:
    """A product name DEGIRO wrapped onto a second line: no date, no ISIN."""
    return not _cell(row, idx.get("date")) and not _cell(row, idx.get("isin"))


def _is_non_event(row: list[str], idx: dict[str, int]) -> bool:
    """A zero-price, zero-value row: one leg of a DEGIRO bookkeeping pair.

    Moving a holding between the tradeable and "NON TRADEABLE" listing of the
    same ISIN books two such rows. They net to nothing and carry no price to
    import, so they are dropped rather than filling the skip list with
    warnings about a non-event.
    """
    local = idx.get("local_value")
    if local is None or _num(_cell(row, idx.get("price"))) != 0:
        return False
    return _num(_cell(row, local)) == 0


def _cell(row: list[str], pos: int | None) -> str:
    return row[pos].strip() if pos is not None and pos < len(row) else ""


def _currency_of(header: list[str], row: list[str], pos: int | None) -> str:
    """Currency of a money column, in whichever place this export records it.

    The classic export puts it in the unnamed cell to the column's right; the
    current one bakes it into the header instead ("Costes de transacción y/o
    externos EUR"). Either reads as a bare three-letter code.
    """
    if pos is None:
        return ""
    right = _cell(row, pos + 1).upper()
    if len(right) == 3 and right.isalpha():
        return right
    name = header[pos].strip() if pos < len(header) else ""
    tail = name.rpartition(" ")[2].upper()
    return tail if len(tail) == 3 and tail.isalpha() else ""


def _fee(
    header: list[str], row: list[str], idx: dict[str, int],
    costs: list[int], currency: str,
) -> float:
    """What the trade really cost, expressed in the trade's own currency.

    DEGIRO bills every charge in the *account* currency and splits it across
    columns ("Comisión AutoFX" + "Costes de transacción"), so a USD trade
    carries EUR costs. The parts are summed and then reconciled against the
    row's own Total, which is what was actually debited: where they disagree
    the Total wins, so a cost column this parser doesn't know about still
    lands in the cost basis. Conversion uses the row's own exchange rate;
    without one, a cross-currency charge is dropped rather than mixed in.
    """
    account = _currency_of(header, row, idx.get("total")) or _currency_of(
        header, row, idx.get("base_value")
    )
    charged = 0.0
    for pos in costs:
        ccy = _currency_of(header, row, pos) or account
        if account and ccy != account:
            continue  # a charge in some third currency can't be reconciled
        charged += abs(_num(_cell(row, pos)))

    base = abs(_num(_cell(row, idx.get("base_value"))))
    total = abs(_num(_cell(row, idx.get("total"))))
    if base and total and abs(abs(total - base) - charged) > 0.02:
        charged = abs(total - base)

    if not charged or not account or account == currency:
        return charged
    rate = _num(_cell(row, idx.get("fx_rate")))
    return charged * rate if rate > 0 else 0.0


def _build_tx(
    header: list[str], row: list[str], idx: dict[str, int], costs: list[int]
) -> Transaction:
    isin = _cell(row, idx["isin"]).upper()
    if not isin:
        raise ValueError("missing ISIN")
    date = _parse_date(_cell(row, idx["date"]))
    qty = _num(_cell(row, idx["quantity"]))
    if qty == 0:
        raise ValueError("row has no quantity")
    price = _num(_cell(row, idx["price"]))
    if price <= 0:
        raise ValueError(f"row has non-positive price {price:g}")
    currency = _currency_of(header, row, idx["price"])
    if not currency:
        raise ValueError("price column has no currency")

    # Guard against decimal-separator misreads: qty × price must match the
    # statement's own Local value column (same currency) within 2%.
    local_pos = idx.get("local_value")
    local = abs(_num(_cell(row, local_pos))) if local_pos is not None else 0.0
    if local > 0 and _currency_of(header, row, local_pos) == currency:
        gross = abs(qty) * price
        if abs(gross - local) > local * 0.02:
            raise ValueError(
                f"row inconsistent: {abs(qty):g} × {price:g} = {gross:.2f} "
                f"but local value is {local:.2f}"
            )

    return Transaction(
        date=date,
        ticker=isin,
        action="buy" if qty > 0 else "sell",
        quantity=abs(qty),
        price=price,
        currency=currency,
        fee=round(_fee(header, row, idx, costs, currency), 4),
        note=f"degiro {_cell(row, idx['product'])}".strip(),
    )


def _parse_date(value: str) -> str:
    """DD-MM-YYYY (or DD/MM/YYYY, or already-ISO) to ISO YYYY-MM-DD."""
    v = value.strip().split(" ", 1)[0]
    if not v:
        raise ValueError("missing date")
    parts = v.replace("/", "-").split("-")
    if len(parts) == 3:
        if len(parts[0]) == 4:
            return "-".join(parts)
        if len(parts[2]) == 4:
            return f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
    raise ValueError(f"unrecognised date {value!r}")


def _num(value: str) -> float:
    """Parse a locale-formatted number: "1.234,56", "1,234.56", "-2,5", "10".

    When both separators appear the rightmost one is the decimal mark. A lone
    comma is a decimal mark unless it reads as a thousands group (",ddd" with
    a multi-digit head) — the Local-value cross-check catches the rare
    ambiguous case this heuristic gets wrong.
    """
    v = value.strip().replace("\xa0", "").replace(" ", "")
    if not v:
        return 0.0
    if "," in v and "." in v:
        if v.rfind(",") > v.rfind("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            v = v.replace(",", "")
    elif "," in v:
        head, _, tail = v.rpartition(",")
        if v.count(",") > 1 or (len(tail) == 3 and len(head.lstrip("+-")) > 1):
            v = v.replace(",", "")
        else:
            v = head + "." + tail
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"unparseable number {value!r}") from None
