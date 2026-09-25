"""Parse a Revolut crypto account-statement CSV into ledger Transactions.

Revolut's crypto statement is a flat CSV like the stock one (one row per
event) but differs in three ways this parser absorbs:

* The symbol is a bare coin code (BTC), not a market symbol. Rows are
  normalized to the Yahoo pair for the statement's fiat currency (BTC + EUR
  money fields -> ticker BTC-EUR), so the transaction currency and the quote
  currency of every later price lookup are the same one — FIFO, FX and tax
  work unchanged, and no per-user alias is needed. Bare codes must NOT be
  kept: they collide with real stock tickers (SOL, LINK, …).
* There is usually no currency column: the fiat currency is sniffed from the
  money fields' symbol/code (€, $, £, "1.234,56 EUR", …), defaulting to USD.
* Fees come in an explicit column instead of being implied from the total.

Buy / sell rows become Transactions. Everything else — send/receive,
exchanges (coin-to-coin), staking/learn rewards — is reported as skipped
with a reason, never silently dropped: transfers carry no cost basis, and
rewards are acquisitions at market value the user must add manually (they
are taxable income in Spain).

Nothing here writes to the ledger; the Import page previews and commits.
"""

from __future__ import annotations

from stocks.data.crypto import to_pair
from stocks.portfolio import lexicon, statement
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import CsvFormat, ParseResult, Row

# Logical key -> accepted header names (lowercased); exports drift across
# app versions, so matching is case-insensitive like the stock parser's.
_COLS = {
    "symbol": ("symbol", "ticker", "asset", "cryptocurrency"),
    "type": ("type", "transaction type", "action"),
    "quantity": ("quantity", "amount"),
    "price": ("price", "price per coin", "price per unit"),
    "value": ("value", "total", "total amount", "fiat amount"),
    "fee": ("fees", "fee"),
    "date": ("date", "completed date", "started date", "timestamp"),
    "currency": ("currency", "fiat currency", "base currency"),
}

def parse_csv(text: str) -> ParseResult:
    """Parse Revolut crypto-statement CSV text (no side effects)."""
    return statement.parse_csv(text, FORMAT)


def _map_action(rtype: str) -> str | None:
    """Buy or sell, in whatever language the export was downloaded in.

    Only those two: a crypto statement's other types are moves and rewards,
    which carry no cost basis and are reported as skipped below. The words
    themselves live in lexicon.py, so a Spanish "Compra" reads the same here
    as an English "Buy" — matching on "BUY" alone is what made a whole
    es-locale export import as zero rows.
    """
    action = lexicon.action_of(rtype)
    return action if action in ("buy", "sell") else None


# Type words that mean "coins arrived for free", in the languages the export
# ships in — a reward is income, not a purchase. Checked before the plain
# staking words below, because "Recompensa de staking" is both.
_REWARD_WORDS = ("REWARD", "RECOMPENSA", "RECOMPENSE", "EARN", "LEARN",
                 "INTEREST", "INTERES", "PREMIO", "BONUS", "AIRDROP")
# Moving coins in or out of staking: the same coins, still yours, no price.
_STAKE_WORDS = ("STAKING", "STAKE", "UNSTAK", "DELEGAT", "LOCK")


def _skip_reason(rtype: str) -> str:
    t = lexicon.plain(rtype).upper()
    if any(k in t for k in _REWARD_WORDS):
        return (
            "reward — an acquisition at market value (taxable income in "
            "Spain); add manually as a buy at the reward-day price"
        )
    if any(k in t for k in _STAKE_WORDS):
        return (
            "moved in or out of staking — the same coins, no acquisition and "
            "no disposal; nothing to import"
        )
    if "EXCHANGE" in t or "CONVERT" in t:
        return (
            "coin-to-coin exchange — fiscally a sell plus a buy; add both "
            "legs manually at the exchange-day prices"
        )
    if any(k in t for k in ("SEND", "RECEIVE", "TRANSFER", "WITHDRAW", "DEPOSIT")):
        return (
            "transfer — moves coins without a price; adjust manually if it "
            "was a disposal"
        )
    return "unrecognised type — not imported"


def _audit(row: Row) -> dict:
    return {
        "date": row.text("date"),
        "ticker": row.upper("symbol"),
        "quantity": row.money("quantity"),
        "amount": row.money("value"),
        "currency": _currency(row),
    }


def _currency(row: Row) -> str:
    """Fiat currency: explicit column first, else sniffed from money fields."""
    explicit = row.upper("currency")
    if explicit:
        return explicit
    for key in ("price", "value", "fee"):
        if found := lexicon.currency_of(row.text(key)):
            return found
    return "USD"


def _parse_any_date(value: str | None) -> str:
    """ISO date from a timestamp or from the prose formats crypto apps use.

    Delegated whole to lexicon.iso_date: this used to fall back to pandas,
    which reads "3 feb 2025" and rejects "3 abr 2025" — the same file, half
    of it unreadable, because pandas' month names are English only.
    """
    return lexicon.iso_date(value)


def _build_tx(row: Row, action: str) -> Transaction:
    date = _parse_any_date(row.text("date"))
    coin = row.upper("symbol")
    if not coin:
        raise ValueError("missing symbol")
    currency = _currency(row)

    qty = row.money("quantity")
    price = row.money("price")
    value = row.money("value")
    fee = row.money("fee")
    if qty <= 0:
        raise ValueError(f"{action} row has no quantity")
    if price == 0.0 and value and qty:  # derive when per-coin price is blank
        price = value / qty
    if price <= 0:
        raise ValueError(f"{action} row has no price")
    if fee < 0:
        raise ValueError(f"{action} row has negative fee {fee}")
    # Value should be qty×price give or take the fee and price rounding;
    # beyond that the row is corrupt (wrong column, truncated number).
    if value > 0:
        gross = qty * price
        if abs(gross - value) > max(value * 0.02, fee + qty * 0.005 + 0.01):
            raise ValueError(
                f"{action} row inconsistent: {qty:g} × {price:g} = {gross:.2f} "
                f"but value is {value:.2f}"
            )
    return Transaction(
        date=date,
        # Full Yahoo pair, in the statement's fiat — see module doc.
        ticker=to_pair(coin, currency),
        action=action,
        quantity=qty,
        price=price,
        currency=currency,
        fee=fee,
        note=f"revolut crypto {coin}",
    )


FORMAT = CsvFormat(
    columns=_COLS,
    type_key="type",
    action_of=_map_action,
    skip_reason=_skip_reason,
    build=_build_tx,
    audit=_audit,
)
