"""Parse a Trade Republic "Transaction export" CSV into ledger Transactions.

Trade Republic's native export (app → Profile → Account statements →
Transaction export, since April 2026) is one flat row per booking with an
English, snake_case header — `datetime, date, account_type, category, type,
asset_class, name, symbol, shares, price, amount, fee, tax, currency, …,
transaction_id, …` — the same in every app language. Comma-delimited with
every cell quoted; a semicolon variant exists, so the separator is sniffed.
The parser is strict: it refuses the whole file unless the distinctive
columns are all present, so another broker's statement is never half-read.

Before this parser the file reached the model-mapped fallback, which read it
differently on every upload (some of the rows one time, others the next) and,
when the first rows held two coins, as a crypto export that threw away every
share in it.

Shape notes this parser absorbs:

* `category` + `type` name the booking: TRADING BUY/SELL are trades (a
  savings-plan execution is a BUY too); CASH holds dividends, interest, card
  payments, transfers and tax bookings; CORPORATE_ACTION splits and
  redemptions. Only the pair decides — the type alone repeats across them.
* `symbol` is the ISIN for securities, which is what the row imports under —
  the same convention as DEGIRO, resolved to a listing on screen. Crypto
  carries the coin code (BTC) and `asset_class` CRYPTO, and imports as the
  Yahoo pair in the row's currency (BTC-EUR).
* `amount` is the gross value, signed as the cash moves (negative on a buy);
  `fee` and `tax` are signed columns of their own. Quantity and money are read
  as magnitudes, the direction comes from the type.
* Dividends book gross with the withholding (`tax`) as the fee, the
  convention the Spanish double-tax credit reads. Trade Republic cancels a
  dividend by repeating the row with the signs flipped and then books it
  again; the cancelled pair is left out, both rows reported, and the
  re-booking imports.
* A bond's coupon is an INTEREST_PAYMENT on its ISIN and imports as that
  bond's dividend; interest on cash does not. A maturity is two rows — the
  position leaving (CORPORATE_ACTION REDEMPTION) and the payout (CASH
  FINAL_MATURITY); the payout books the sale, the other is reported.
* Card payments, transfers, Saveback, Vorabpauschale and other tax bookings
  are skipped with a reason, never silently dropped. A repeated
  `transaction_id` is the same booking twice and is dropped.

Nothing here writes to the ledger; the Import page previews and commits.
"""

from __future__ import annotations

import csv
import io
import re

from stocks.data import crypto
from stocks.portfolio import statement
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult, Row

NOTE = "trade_republic"

# Logical key -> the export's header name. One spelling each: the header is
# not translated with the app.
_COLS = {
    "datetime": ("datetime",),
    "date": ("date",),
    "account": ("account_type",),
    "category": ("category",),
    "type": ("type",),
    "asset_class": ("asset_class",),
    "name": ("name",),
    "symbol": ("symbol",),
    "shares": ("shares",),
    "price": ("price",),
    "amount": ("amount",),
    "fee": ("fee",),
    "tax": ("tax",),
    "currency": ("currency",),
    "description": ("description",),
    "id": ("transaction_id",),
}

# Every one of these must be present or the file is not a Trade Republic export.
_REQUIRED = ("datetime", "category", "type", "symbol", "shares", "amount",
             "currency", "id")

REFUSAL = "not a Trade Republic transaction export — missing column(s): "

CASH = "cash movement — not position-affecting"
INTEREST = "interest — cash credit, not position-affecting"
SPLIT = "stock split — ratio derived at validation, or add manually"
TAX = "tax booking — not position-affecting"
REDEMPTION = "redemption — the payout row books the sale"
REVERSED = "dividend reversed by the broker — neither row is booked"
UNKNOWN = "unrecognised type — not imported"

_DIVIDEND = {"DIVIDEND", "DISTRIBUTION", "DIVIDEND_EQUIVALENT_PAYMENT"}
_MATURITY = {"FINAL_MATURITY", "TILG"}
_TAX = {"TAX", "EARNINGS", "PRE_DETERMINED_TAX_BASE", "SEC_ACCOUNT",
        "TAX_OPTIMIZATION"}
# Money in or out of the account, and charges that are not a trade's.
_CASH = {
    "CUSTOMER_INBOUND", "CUSTOMER_INPAYMENT", "CUSTOMER_INPAYMENT_REVERSAL",
    "CUSTOMER_OUTBOUND_REQUEST", "TRANSFER_IN", "TRANSFER_OUT",
    "TRANSFER_INBOUND", "TRANSFER_OUTBOUND", "TRANSFER_INSTANT_INBOUND",
    "TRANSFER_INSTANT_OUTBOUND", "TRANSFER_DIRECT_DEBIT_INBOUND",
    "VIBAN_TRANSFER_INBOUND", "VIBAN_TRANSFER_OUTBOUND", "GENERAL_INBOUND",
    "MANUAL_CASH_TRANSFER", "PAYMENT", "GIFT", "CARD_TRANSACTION",
    "CARD_TRANSACTION_INTERNATIONAL", "CARD_TRANSACTION_REFUND",
    "CARD_TRANSACTION_REFUND_REVERSAL", "BENEFITS_SAVEBACK", "BONUS",
    "REFERRAL", "KINDERGELD_BONUS", "PEA_MARKETING", "COMPENSATION", "FEE",
    "CARD_ORDERING_FEE",
}

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")


def _num(value: str) -> float:
    """A number cell. The comma export writes dots ("-500.00"); a semicolon
    export may write a decimal comma, which `statement.money` would read as a
    thousands separator — ten times too much."""
    v = value.strip()
    if "," in v and ("." not in v or v.rfind(",") > v.rfind(".")):
        v = v.replace(".", "").replace(",", ".")
    return statement.money(v)


def _kind(category: str, rtype: str) -> str:
    """What a booking is: buy, sell, dividend, coupon, maturity, or a skip
    reason (any other string)."""
    if category == "TRADING":
        return {"BUY": "buy", "SELL": "sell"}.get(rtype, UNKNOWN)
    if category == "CORPORATE_ACTION":
        if rtype == "SPLIT":
            return SPLIT
        if rtype in {"REDEMPTION", "WARRANT_EXERCISE"} | _MATURITY:
            return REDEMPTION
        return UNKNOWN
    if category != "CASH":
        return UNKNOWN
    if rtype in _DIVIDEND:
        return "dividend"
    if rtype == "INTEREST_PAYMENT":
        return "coupon"
    if rtype in _MATURITY:
        return "maturity"
    if rtype in _TAX:
        return TAX
    if rtype in _CASH:
        return CASH
    return UNKNOWN


def _skip_reason(rtype: str) -> str:
    """The reason for a skipped `"CATEGORY TYPE"` booking (tx_text names each)."""
    category, _, kind = rtype.partition(" ")
    reason = _kind(category, kind)
    return reason if reason not in {"buy", "sell", "dividend", "coupon",
                                    "maturity"} else UNKNOWN


def _audit(row: Row) -> dict:
    """The fields validate.resolve_splits and the preview read off a skip."""
    return {
        "date": _date(row),
        "ticker": row.upper("symbol"),
        "quantity": abs(_num(row.text("shares"))),
        "amount": _num(row.text("amount")),
        "currency": row.upper("currency"),
    }


def _date(row: Row) -> str:
    # `date` is the booking day; `datetime` is UTC and can fall on the next one.
    return statement.parse_date(row.text("date") or row.text("datetime"))


def _ticker(row: Row) -> str:
    symbol = row.upper("symbol")
    if row.upper("asset_class") == "CRYPTO" or (symbol and not _ISIN_RE.match(symbol)
                                                 and symbol in crypto.CRYPTO_NAMES):
        return crypto.to_pair(symbol, row.upper("currency") or "EUR")
    return symbol


def _note(row: Row) -> str:
    return f"{NOTE} {row.text('name')}".strip()[:120]


def _trade(row: Row, action: str) -> Transaction:
    ticker = _ticker(row)
    if not ticker:
        raise ValueError(f"{action} row has no symbol")
    qty = abs(_num(row.text("shares")))
    amount = abs(_num(row.text("amount")))
    if qty <= 0:
        raise ValueError(f"{action} row has no quantity")
    price = abs(_num(row.text("price"))) or amount / qty
    if price <= 0:
        raise ValueError(f"{action} row has no price")
    statement.check_consistency(action, qty, price, amount, ticker)
    return Transaction(
        date=_date(row), ticker=ticker, action=action, quantity=qty,
        price=price, currency=row.upper("currency") or "EUR",
        fee=abs(_num(row.text("fee"))), note=_note(row),
    )


def _income(row: Row) -> Transaction:
    ticker = _ticker(row)
    if not ticker:
        raise ValueError("dividend row has no symbol")
    amount = _num(row.text("amount"))
    if amount <= 0:
        raise ValueError(f"dividend amount {amount} is not positive")
    tax = _num(row.text("tax"))
    return Transaction(
        date=_date(row), ticker=ticker, action="dividend", price=amount,
        currency=row.upper("currency") or "EUR",
        fee=-tax if tax < 0 else 0.0, note=_note(row),
    )


def _maturity(row: Row) -> Transaction:
    """A bond paid back: the payout is the sale of the whole position."""
    ticker = _ticker(row)
    qty = abs(_num(row.text("shares")))
    amount = abs(_num(row.text("amount")))
    if not ticker or qty <= 0 or amount <= 0:
        raise ValueError("maturity row without its symbol, quantity or payout")
    return Transaction(
        date=_date(row), ticker=ticker, action="sell", quantity=qty,
        price=amount / qty, currency=row.upper("currency") or "EUR",
        fee=abs(_num(row.text("fee"))), note=_note(row),
    )


def _skip(result: ParseResult, row: Row, rtype: str, reason: str) -> None:
    result.skipped.append({"row": row.number, "type": rtype, "reason": reason,
                           **_audit(row)})


def parse_csv(text: str) -> ParseResult:
    """Parse Trade Republic export CSV text into a ParseResult (no side effects)."""
    head = text.splitlines()[0] if text.strip() else ""
    reader = csv.DictReader(io.StringIO(text),
                            delimiter=statement.sniff_delimiter(head, _COLS))
    if reader.fieldnames is None:
        return ParseResult()
    col = statement.resolve_columns(reader.fieldnames, _COLS)
    missing = [_COLS[k][0] for k in _REQUIRED if k not in col]
    if missing:
        return ParseResult(skipped=[{
            "row": 1, "type": "header", "reason": REFUSAL + ", ".join(missing),
        }])

    result = ParseResult()
    seen: set[str] = set()
    # Index into result.transactions of each dividend still standing, by
    # (ticker, amount, withholding): what a reversal row cancels.
    dividends: dict[tuple, list[int]] = {}
    cancelled: set[int] = set()
    lines: dict[int, int] = {}  # transaction index -> its line in the file
    for number, raw in enumerate(reader, start=2):
        row = Row(raw, col, number)
        if row.empty(("category", "type", "datetime")):
            continue
        booking = row.text("id")
        if booking:
            if booking in seen:
                continue
            seen.add(booking)
        category, kind = row.upper("category"), row.upper("type")
        rtype = f"{category} {kind}"
        what = _kind(category, kind)
        try:
            if what in ("buy", "sell"):
                result.transactions.append(_trade(row, what))
            elif what == "maturity":
                result.transactions.append(_maturity(row))
            elif what == "coupon" and not _ISIN_RE.match(row.upper("symbol")):
                _skip(result, row, rtype, INTEREST)
            elif what in ("dividend", "coupon"):
                amount = _num(row.text("amount"))
                key = (_ticker(row), round(abs(amount), 2),
                       round(abs(_num(row.text("tax"))), 2))
                if amount < 0:
                    standing = dividends.get(key)
                    if not standing:
                        raise ValueError(
                            "dividend reversal without the dividend it cancels"
                        )
                    cancelled.add(standing.pop())
                    _skip(result, row, rtype, REVERSED)
                    continue
                dividends.setdefault(key, []).append(len(result.transactions))
                lines[len(result.transactions)] = number
                result.transactions.append(_income(row))
            else:
                _skip(result, row, rtype, what)
        except ValueError as exc:
            _skip(result, row, rtype, str(exc))
    if cancelled:
        for index in sorted(cancelled, reverse=True):
            tx = result.transactions.pop(index)
            result.skipped.append({
                "row": lines[index], "type": "CASH DIVIDEND", "reason": REVERSED,
                "date": tx.date, "ticker": tx.ticker, "quantity": 0.0,
                "amount": tx.price, "currency": tx.currency,
            })
    return result
