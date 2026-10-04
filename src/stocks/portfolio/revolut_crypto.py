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
* A buy's Quantity is what the whole Value would have bought, but Revolut
  takes the fee out of that Value first: 500 € at a 4.95 € fee buys 495.05 €
  of coins, and that is what a later "sell everything" sells. The ledger
  keeps the coins that arrived (`qty × (value − fee) / value`) at the
  unrounded price (`value / qty`), so cost (net coins × price + fee) is the
  500 € paid and a full sale leaves nothing behind. Rows written this way say
  so in their note (`NET`); `portfolio/doctor.py` offers the same correction
  to rows imported before.

Buy / sell rows become Transactions. Everything else — send/receive,
exchanges (coin-to-coin), staking/learn rewards — is reported as skipped
with a reason, never silently dropped: transfers carry no cost basis, and
rewards are acquisitions at market value the user must add manually (they
are taxable income in Spain).

Nothing here writes to the ledger; the Import page previews and commits.
"""

from __future__ import annotations

from dataclasses import replace

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

# Last word of a buy's note when its quantity is the coins that arrived, net
# of the fee — what the doctor reads to leave a row it need not correct.
NET = "net"


_PREFIX = "revolut crypto"


def statement_buy(tx: Transaction) -> bool:
    """A buy this parser wrote, whichever way its quantity was booked — what
    the import check matches a re-imported buy against by day, coin and fee,
    since an older import, the doctor and this parser can each put it at a
    slightly different quantity and price."""
    return tx.action == "buy" and tx.note.lower().startswith(_PREFIX)


def gross_buy(tx: Transaction) -> bool:
    """A buy an older import wrote, its quantity still holding the fee's
    coins — what the doctor offers to correct."""
    return (statement_buy(tx) and tx.fee > 0 and tx.price > 0
            and tx.note.split()[-1].lower() != NET)


def parse_csv(text: str) -> ParseResult:
    """Parse Revolut crypto-statement CSV text (no side effects)."""
    result = statement.parse_csv(text, FORMAT)
    _sweep(result.transactions)
    return result


def _sweep(txs: list[Transaction]) -> None:
    """Take off the buys what a full sale leaves behind of the fees' cents.

    The Fees column is cut to the cent (4.94 € printed for 0.99 % of
    500 €), so the coins a fee took come out a cent's worth short, and selling
    everything leaves that cent's worth — 0.19 CHILLGUY — on the book as a
    position. A sale that leaves no more than a cent's worth of coins per buy
    since the coin was last empty emptied it: the remainder comes off the
    last of those buys.
    """
    order = sorted(range(len(txs)), key=lambda i: txs[i].date)  # stable
    held: dict[str, float] = {}
    since: dict[str, list[int]] = {}
    for i in order:
        tx = txs[i]
        if tx.action == "buy":
            held[tx.ticker] = held.get(tx.ticker, 0.0) + tx.quantity
            since.setdefault(tx.ticker, []).append(i)
            continue
        buys = since.get(tx.ticker, [])
        left = held.get(tx.ticker, 0.0) - tx.quantity
        held[tx.ticker] = left
        if not buys or left <= 0:
            if left <= 0:
                held[tx.ticker], since[tx.ticker] = 0.0, []
            continue
        if left <= sum(0.01 / txs[b].price for b in buys if txs[b].price > 0):
            last = buys[-1]
            txs[last] = replace(txs[last], quantity=txs[last].quantity - left)
            held[tx.ticker], since[tx.ticker] = 0.0, []


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


def _places(text: str) -> int:
    """Decimals the statement printed a quantity with; 8 when it does not say
    (fewer than 4 is a whole or trimmed number, not the coin's precision)."""
    _, dot, tail = "".join(c for c in text if c.isdigit() or c == ".").rpartition(".")
    return len(tail) if dot and len(tail) >= 4 else 8


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
    if value > 0:
        # Value is to the cent; the Price column is rounded for display
        # ("0,05 €" for a coin at 0.0537), which misstates the basis by 7%.
        # Checked against the printed price first, so a value from the wrong
        # column is still refused below rather than trusted.
        printed = price
        price = value / qty
        if printed > 0 and abs(printed - price) > max(printed * 0.02, 0.006):
            raise ValueError(
                f"{action} row inconsistent: {qty:g} × {printed:g} = "
                f"{qty * printed:.2f} but value is {value:.2f}"
            )
    if price <= 0:
        raise ValueError(f"{action} row has no price")
    if fee < 0:
        raise ValueError(f"{action} row has negative fee {fee}")
    note = f"revolut crypto {coin}"
    if action == "buy" and fee > 0:
        if fee >= (value or qty * price):
            raise ValueError(f"buy row fee {fee:g} is the whole value")
        # The coins that arrived: the fee came out of the value first. Rounded
        # as the statement prints coins, because the value and fee are only
        # to the cent: unrounded, a 44M-coin buy kept 4e-5 coins that its own
        # "sell all" never sold, and the position never closed.
        qty = round(qty - fee / price, _places(row.text("quantity")))
        note += f" {NET}"
    return Transaction(
        date=date,
        # Full Yahoo pair, in the statement's fiat — see module doc.
        ticker=to_pair(coin, currency),
        action=action,
        quantity=qty,
        price=price,
        currency=currency,
        fee=fee,
        note=note,
    )


FORMAT = CsvFormat(
    columns=_COLS,
    type_key="type",
    action_of=_map_action,
    skip_reason=_skip_reason,
    build=_build_tx,
    audit=_audit,
)
