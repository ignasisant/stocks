"""Import any crypto exchange's export, whichever exchange wrote it.

A share statement is one row per trade, and llm_map's column mapping is built
for that. A crypto export rarely is. The same purchase can arrive in three
shapes:

* **rows** — one row per trade or event: asset, quantity, price or total, the
  currency it was paid in (Coinbase, Kraken trades, Binance spot history,
  KuCoin, Bitstamp, Bitpanda).
* **swaps** — one row per movement with a *sent* and a *received* side, often
  with what it was worth in fiat (Koinly's universal format, Crypto.com,
  Nexo, Binance Convert).
* **ledger** — one balance change per row, so a trade is two or three rows
  sharing a timestamp or a reference id (the Binance account statement,
  Kraken ledgers).

The model looks at a sample and names the layout and the columns — exactly as
llm_map asks it to, and for the same reason: it never transcribes a quantity
or a price. An export whose header is one we know (`_PRESETS`) skips the model
altogether, so Binance, Coinbase, Kraken and the rest read the same with the
assistant down. Python then does everything else:

1. every layout is normalised into the same events — an exchange of one asset
   for another, a reward, a deposit, a withdrawal, a fee;
2. events become ledger rows in **one fiat** (the file's own when it has one,
   the account's otherwise). Coins are always Yahoo pairs, BTC-EUR, never the
   bare code (crypto.py says why);
3. what an event doesn't price itself is valued at that day's close: a
   coin-to-coin swap is a sale of one and a purchase of the other at market
   value (that is how every tax system in tax/ treats it), and a reward is
   income at market value *plus* the coins at that cost basis.

What can't be valued, what is only money moving (a fiat deposit), and what is
only coins moving inside the exchange (a staking subscription) is listed in
``ParseResult.skipped`` with a reason, never guessed at. Skip reasons carry no
user values — they are what import diagnostics counts.
"""

from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date as _day
from typing import TYPE_CHECKING

from stocks import obs
from stocks.data import crypto
from stocks.portfolio import lexicon, platforms
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult

if TYPE_CHECKING:
    import pandas as pd

    from stocks.web.llm import Provider

LAYOUTS = ("rows", "swaps", "ledger")

# Every column a crypto export can have, by role.
COLUMNS = (
    "date", "type", "subtype", "asset", "pair", "quantity", "price", "total",
    "quote", "fee", "fee_asset", "sent_quantity", "sent_asset",
    "received_quantity", "received_asset", "value", "value_currency",
    "group", "direction", "asset_class", "note",
)

# What a type cell can mean. `trade` is a trade whose direction the row's
# signs give; `convert` a swap spelled out in a sentence ("Converted 0.01 ETH
# to 25.03 USDC"); `move` a transfer whose direction the sign gives.
ROLES = ("buy", "sell", "trade", "convert", "reward", "receive", "send",
         "move", "fee", "ignore")

# ISO codes an exchange uses for money. A leg in one of these is cash, not a
# position: it is what a trade was paid with, and depositing it books nothing.
FIAT = frozenset({
    "EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD", "NZD", "SEK", "NOK",
    "DKK", "PLN", "CZK", "HUF", "RON", "BGN", "TRY", "BRL", "MXN", "ARS",
    "CLP", "COP", "PEN", "ZAR", "INR", "IDR", "KRW", "SGD", "HKD", "CNY",
    "RUB", "UAH", "NGN", "AED", "SAR", "ILS", "THB", "PHP", "VND", "MYR",
    "TWD", "KZT",
})

# Stablecoins, by the fiat they track. Valued at parity when the market has no
# close for them: a dollar stablecoin a cent off its peg is noise, a swap
# skipped for want of a USDT price is a missing purchase.
PEGS = {
    "USDT": "USD", "USDC": "USD", "BUSD": "USD", "DAI": "USD", "FDUSD": "USD",
    "TUSD": "USD", "USDP": "USD", "PYUSD": "USD", "USDE": "USD", "GUSD": "USD",
    "EURC": "EUR", "EURT": "EUR", "EURI": "EUR", "EUROC": "EUR",
}

# Quote assets a glued pair ("BTCUSDT", "ETHBTC") can end in, longest first.
_QUOTES = sorted(
    {*FIAT, *PEGS, "BTC", "ETH", "BNB", "XBT", "SOL", "TRX", "DOGE", "XRP"},
    key=len, reverse=True,
)

_COIN = re.compile(r"^[A-Z0-9]{2,10}$")
_SCI = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")
_UNIT = re.compile(r"[A-Za-z][A-Za-z0-9]*")

HEADER_SCAN = 12  # rows searched for a preset's header (Coinbase has a preamble)


# ---------------------------------------------------------------- the spec
# How a file is read, whoever worked it out: a preset or the model.


@dataclass(frozen=True)
class Spec:
    exchange: str  # broker key the rows are stamped with ("binance"), or ""
    layout: str
    header_row: int
    columns: dict[str, int]
    date_format: str = ""
    decimal: str = "."
    thousands: str = ""
    type_map: dict[str, str] = field(default_factory=dict)
    # The fiat a money column's header names ("Importe EUR", "USD Equivalent"),
    # by role: what its cells are in when no currency column says. `apply`
    # fills it from the header row.
    units: dict[str, str] = field(default_factory=dict)


_HEAD_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")


def _header_units(grid: list[list[str]], spec: Spec) -> dict[str, str]:
    head = grid[spec.header_row] if spec.header_row < len(grid) else []
    units = {}
    for role in ("price", "total", "value", "fee"):
        i = spec.columns.get(role)
        if i is None or i >= len(head):
            continue
        codes = [c for c in _HEAD_CODE.findall(head[i]) if c in FIAT]
        if unit := codes[0] if codes else lexicon.currency_of(head[i]):
            units[role] = unit
    return units


@dataclass(frozen=True)
class Preset:
    """A known export, recognised by its header names."""

    exchange: str
    layout: str
    need: frozenset[str]  # headers that must all be present
    columns: dict[str, tuple[str, ...]]  # role -> header names, first found wins
    type_map: dict[str, str] = field(default_factory=dict)


def _p(exchange: str, layout: str, need: str, columns: dict[str, str],
       type_map: dict[str, str] | None = None) -> Preset:
    return Preset(
        exchange, layout,
        frozenset(h.strip() for h in need.split("|")),
        {role: tuple(h.strip() for h in names.split("|"))
         for role, names in columns.items()},
        type_map or {},
    )


# Headers as the exchanges document them (BittyTax keeps the reference set,
# version by version). Lowercased, single-spaced. A header that drifts falls
# through to the model, which reads it the same way — these only make the
# common exports free and model-independent.
_PRESETS: tuple[Preset, ...] = (
    _p("binance", "ledger", "utc_time|operation|coin|change", {
        "date": "utc_time", "type": "operation", "asset": "coin",
        "quantity": "change", "note": "remark",
    }, {
        "deposit": "receive", "withdraw": "send", "fiat deposit": "receive",
        "fiat withdraw": "send", "binance convert": "trade",
        "small assets exchange bnb": "trade", "large otc trading": "trade",
        "buy crypto": "trade", "transaction related": "trade",
        "eth 2.0 staking": "ignore", "staking purchase": "ignore",
        "staking redemption": "ignore", "savings purchase": "ignore",
        "pos savings purchase": "ignore", "pos savings redemption": "ignore",
        "savings principal redemption": "ignore",
        "commission history": "reward", "commission rebate": "reward",
        "crypto box": "reward", "auto invest transaction": "trade",
        "binance card spending": "trade",
    }),
    _p("binance", "rows", "date(utc)|market|type|price|amount|total", {
        "date": "date(utc)", "pair": "market", "type": "type", "price": "price",
        "quantity": "amount", "total": "total", "fee": "fee",
        "fee_asset": "fee coin",
    }),
    _p("binance", "rows", "date(utc)|pair|side|price|executed|amount", {
        "date": "date(utc)", "pair": "pair", "type": "side", "price": "price",
        "quantity": "executed", "total": "amount", "fee": "fee",
    }),
    _p("binance", "swaps", "date|pair|type|sell|buy|price|status", {
        "date": "date", "type": "type", "sent_quantity": "sell",
        "received_quantity": "buy",
    }, {"market": "trade", "limit": "trade"}),
    _p("coinbase", "rows",
       "timestamp|transaction type|asset|quantity transacted", {
        "date": "timestamp", "type": "transaction type", "asset": "asset",
        "quantity": "quantity transacted",
        "quote": "price currency|spot price currency",
        "price": "price at transaction|spot price at transaction",
        "total": "subtotal", "fee": "fees and/or spread|fees", "note": "notes",
    }, {
        "pro withdrawal": "receive", "exchange withdrawal": "receive",
        "pro deposit": "send", "exchange deposit": "send",
        "retail staking transfer": "ignore", "retail unstaking transfer": "ignore",
        "retail eth2 deprecation": "ignore",
    }),
    _p("kraken", "ledger", "txid|refid|time|type|asset|amount|fee", {
        "date": "time", "group": "refid", "type": "type", "subtype": "subtype",
        "asset": "asset", "quantity": "amount", "fee": "fee",
    }, {
        "trade": "trade", "spend": "trade", "receive": "trade",
        "staking": "reward", "transfer": "ignore", "margin": "ignore",
        "rollover": "ignore", "settled": "ignore", "adjustment": "ignore",
        "invite bonus": "reward",
    }),
    _p("kraken", "rows", "txid|ordertxid|pair|time|type|price|cost|fee|vol", {
        "date": "time", "pair": "pair", "type": "type", "price": "price",
        "total": "cost", "fee": "fee", "quantity": "vol",
    }),
    _p("bitpanda", "rows",
       "transaction id|timestamp|transaction type|in/out|amount fiat|fiat"
       "|amount asset|asset", {
        "date": "timestamp", "type": "transaction type", "direction": "in/out",
        "total": "amount fiat", "quote": "fiat", "quantity": "amount asset",
        "asset": "asset", "fee": "fee", "fee_asset": "fee asset",
        "asset_class": "asset class",
    }, {"transfer": "move", "deposit": "receive", "withdrawal": "send"}),
    _p("crypto.com", "swaps",
       "timestamp (utc)|transaction description|currency|amount|to currency"
       "|to amount|native currency|native amount", {
        "date": "timestamp (utc)", "type": "transaction kind",
        "asset": "currency", "quantity": "amount",
        "received_asset": "to currency", "received_quantity": "to amount",
        "value": "native amount", "value_currency": "native currency",
        "note": "transaction description",
    }, {
        "crypto_to_exchange_transfer": "send",
        "exchange_to_crypto_transfer": "receive",
        "crypto_earn_program_created": "ignore",
        "crypto_earn_program_withdrawn": "ignore",
        "supercharger_deposit": "ignore", "supercharger_withdrawal": "ignore",
        "viban_deposit": "ignore", "viban_withdrawal": "ignore",
        "viban_card_top_up": "ignore", "card_top_up": "sell",
        "crypto_viban_exchange": "trade", "crypto_transfer": "move",
        "dust_conversion_credited": "trade", "dust_conversion_debited": "trade",
    }),
    _p("kucoin", "rows",
       "order id|symbol|side|avg. filled price|filled amount|filled volume", {
        "date": "filled time (with utc offset)|filled time(utc+08:00)|filled time",
        "pair": "symbol", "type": "side", "price": "avg. filled price",
        "quantity": "filled amount", "total": "filled volume", "fee": "fee",
        "fee_asset": "fee currency",
    }),
    _p("bitstamp", "rows",
       "type|subtype|datetime|amount|amount currency|value|value currency", {
        "date": "datetime", "type": "type", "subtype": "subtype",
        "quantity": "amount", "asset": "amount currency", "total": "value",
        "quote": "value currency", "price": "rate", "fee": "fee",
        "fee_asset": "fee currency",
    }),
    _p("nexo", "swaps",
       "transaction|type|input currency|input amount|output currency|output amount", {
        "date": "date / time (utc)|date / time", "type": "type",
        "sent_asset": "input currency", "sent_quantity": "input amount",
        "received_asset": "output currency", "received_quantity": "output amount",
        "value": "usd equivalent", "fee": "fee", "fee_asset": "fee currency",
        "note": "details",
    }, {
        "top up crypto": "buy", "deposit to exchange": "ignore",
        "exchange deposited on": "ignore", "transfer to pro wallet": "ignore",
        "transfer from pro wallet": "ignore", "locking term deposit": "ignore",
        "unlocking term deposit": "ignore", "exchange to withdraw": "ignore",
    }),
    _p("koinly", "swaps",
       "date|sent amount|sent currency|received amount|received currency", {
        "date": "date", "type": "label", "sent_quantity": "sent amount",
        "sent_asset": "sent currency", "received_quantity": "received amount",
        "received_asset": "received currency", "fee": "fee amount",
        "fee_asset": "fee currency", "value": "net worth amount",
        "value_currency": "net worth currency", "note": "description",
    }),
)

# Display names and logos live in platforms.CRYPTO_EXCHANGES, which is also
# what puts these keys in platforms.BROKER_NAMES.


def _head(cell: str) -> str:
    return " ".join(cell.strip().lower().split())


def preset_spec(grid: list[list[str]]) -> Spec | None:
    """The spec of a known export, when the file's header is one; else None."""
    for i, row in enumerate(grid[:HEADER_SCAN]):
        heads = [_head(c) for c in row]
        have = set(heads)
        for preset in _PRESETS:
            if not preset.need <= have:
                continue
            cols = {}
            for role, names in preset.columns.items():
                index = next((heads.index(n) for n in names if n in have), None)
                if index is not None:
                    cols[role] = index
            return Spec(platforms.broker_key(preset.exchange), preset.layout, i,
                        cols, type_map=dict(preset.type_map))
    return None


# ------------------------------------------------------------------ cells


def _number(text: str, spec: Spec) -> float | None:
    from stocks.portfolio.llm_map import _number as number

    raw = (text or "").strip().replace(" ", "").replace(" ", "")
    if not raw or raw in ("-", "—", "–"):
        return None
    if _SCI.match(raw):
        return float(raw)
    return number(raw, spec.decimal, spec.thousands)


def _amount(text: str, spec: Spec) -> tuple[float | None, str]:
    """(number, unit) out of a cell like "0.001BTC", "58.20 EUR" or "€58.20".

    The unit is "" when the cell names none.
    """
    cell = (text or "").strip()
    value = _number(cell, spec)
    units = [u.upper() for u in _UNIT.findall(cell) if not re.fullmatch(r"[eE]\d*", u)]
    unit = units[-1] if units else (lexicon.currency_of(cell) or "")
    return value, _asset(unit)


def _asset(code: str) -> str:
    """A coin or currency code as everyone else writes it.

    Kraken prefixes its legacy codes (XXBT, ZEUR, XETH) and suffixes its
    staking variants (DOT.S, ETH2.S, USDC.M); Binance writes LD-prefixed
    Simple Earn balances. Each is the same asset as far as a holding goes.
    """
    code = (code or "").strip().upper()
    code = re.sub(r"\.(S|M|P|F|B|HOLD)$", "", code)
    if code.startswith("LD") and code[2:] in crypto.CRYPTO_NAMES:
        code = code[2:]
    if len(code) == 4 and code[0] in "XZ" and (
        code[1:] in FIAT or code[1:] in crypto.CRYPTO_NAMES or code[1:] == "XBT"
    ):
        code = code[1:]
    return {"XBT": "BTC", "XDG": "DOGE", "ETH2": "ETH", "BCC": "BCH"}.get(code, code)


def split_pair(text: str) -> tuple[str, str] | None:
    """(base, quote) out of "BTCEUR", "BTC/EUR", "BTC-USDT" or "XXBTZEUR"."""
    raw = (text or "").strip().upper()
    if not raw:
        return None
    parts = re.split(r"[/\-_: ]", raw)
    if len(parts) == 2 and all(parts):
        return _asset(parts[0]), _asset(parts[1])
    if len(raw) == 8 and raw[0] in "XZ" and raw[4] in "XZ":  # Kraken legacy
        return _asset(raw[:4]), _asset(raw[4:])
    for quote in _QUOTES:
        if raw.endswith(quote) and len(raw) > len(quote) + 1:
            return _asset(raw[: -len(quote)]), _asset(quote)
    return None


def _is_fiat(code: str) -> bool:
    return code in FIAT


_PLAIN = Spec("", "rows", 0, {})  # a number written the English way


def _cell(row: list[str], spec: Spec, role: str) -> str:
    index = spec.columns.get(role)
    return row[index].strip() if index is not None and index < len(row) else ""


# --------------------------------------------------------------- roles

_STRONG_REWARD = ("reward", "rewards", "interest", "cashback", "cash back",
                  "airdrop", "bonus", "referral", "rebate", "kickback", "income",
                  "mining", "mined", "distribution", "dividend", "gift",
                  "learn", "learning", "promo", "giveaway")
_IGNORE = ("subscription", "subscribe", "redemption", "redeem", "lock",
           "unlock", "locking", "unlocking", "lockup", "allocation",
           "deallocation", "migration", "spottostaking", "stakingfromspot",
           "stakingtospot", "spotfromstaking", "transfer between",
           "internal transfer", "wallet transfer", "program created",
           "program withdrawn", "term deposit", "supercharger", "stake",
           "unstake", "bonding", "unbonding", "margin", "futures", "loan",
           "borrow", "repay", "collateral", "liquidation", "realized",
           "unrealized", "funding fee")
_FEE = ("fee", "fees", "commission", "comision", "comisiones", "gebuhr")
_WEAK_REWARD = ("earn", "staking", "staked", "recompensa", "intereses")
_CONVERT = ("convert", "converted", "conversion")
_TRADE = ("exchange", "swap", "swapped", "trade", "trading", "spend",
          "revenue", "dust", "otc", "permuta", "intercambio")
_RECEIVE = ("deposit", "receive", "received", "incoming", "credit", "credited",
            "deposito", "recibido", "recepcion", "in")
_SEND = ("withdraw", "withdrawal", "send", "sent", "outgoing", "debit",
         "debited", "retirada", "retiro", "enviado", "out")
_MOVE = ("transfer", "transferencia")


def _words(*phrases: tuple[str, ...]) -> re.Pattern:
    alts = sorted((p for group in phrases for p in group), key=len, reverse=True)
    body = "|".join(map(re.escape, alts))
    return re.compile(rf"(?<![a-z0-9])({body})(?![a-z0-9])")


_ROLE_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (_words(_STRONG_REWARD), "reward"),
    (_words(_IGNORE), "ignore"),
    (_words(_FEE), "fee"),
    (_words(_WEAK_REWARD), "reward"),
    (_words(_CONVERT), "convert"),
    (_words(lexicon.ACTION_WORDS["sell"], ("sold",)), "sell"),
    (_words(lexicon.ACTION_WORDS["buy"], ("purchase",)), "buy"),
    (_words(_TRADE), "trade"),
    (_words(_SEND), "send"),
    (_words(_RECEIVE), "receive"),
    (_words(_MOVE), "move"),
)


def _flat(text: str) -> str:
    return " ".join(re.sub(r"[_\-/]+", " ", lexicon.plain(text)).split())


def role_of(text: str, type_map: dict[str, str] | None = None) -> str | None:
    """What an export's type cell says happened, or None when it says nothing.

    The spec's own map wins (a preset's, or the model's reading of this file);
    the vocabulary is the fallback for a type the sample never showed.
    """
    flat = _flat(text)
    if not flat:
        return None
    if type_map:
        for key, role in type_map.items():
            if _flat(key) == flat and role in ROLES:
                return role
    for pattern, role in _ROLE_PATTERNS:
        if pattern.search(flat):
            return role
    return None


# --------------------------------------------------------------- events


@dataclass
class Event:
    """One thing that happened, in assets, before any fiat is chosen."""

    row: int
    day: str
    kind: str  # exchange | reward | receive | send | fee
    got: tuple[str, float] | None = None
    gave: tuple[str, float] | None = None
    fee: tuple[str, float] | None = None
    value: tuple[str, float] | None = None  # (fiat, amount) the event was worth
    what: str = ""  # the export's own type text


def _skip(result: ParseResult, row: int, what: str, reason: str) -> None:
    result.skipped.append({"row": row, "type": what[:40], "reason": reason})


def _type_text(row: list[str], spec: Spec) -> str:
    kinds = (_cell(row, spec, "type"), _cell(row, spec, "subtype"))
    return " ".join(t for t in kinds if t)


def _fee(row: list[str], spec: Spec, default: str) -> tuple[str, float] | None:
    qty, unit = _amount(_cell(row, spec, "fee"), spec)
    if not qty:
        return None
    asset = (_asset(_cell(row, spec, "fee_asset")) or unit
             or spec.units.get("fee") or default)
    return (asset, abs(qty)) if asset else None


def _value(row: list[str], spec: Spec) -> tuple[str, float] | None:
    amount, unit = _amount(_cell(row, spec, "value"), spec)
    if not amount:
        return None
    ccy = (_asset(_cell(row, spec, "value_currency")) or unit
           or spec.units.get("value", ""))
    return (ccy, abs(amount)) if _is_fiat(ccy) else None


def _direction(row: list[str], spec: Spec) -> int:
    text = _flat(_cell(row, spec, "direction"))
    if not text:
        return 0
    if re.search(r"(?<![a-z])(in|incoming|credit|deposit|\+)(?![a-z])", text):
        return 1
    if re.search(r"(?<![a-z])(out|outgoing|debit|withdrawal|-)(?![a-z])", text):
        return -1
    return 0


_CONVERTED = re.compile(
    r"([\d.,]+(?:e-?\d+)?)\s*([A-Za-z0-9]{2,10})\s+(?:to|for|into|->|→|a|por)\s+"
    r"([\d.,]+(?:e-?\d+)?)\s*([A-Za-z0-9]{2,10})", re.I)


def _rows(grid: list[list[str]], spec: Spec, result: ParseResult) -> list[Event]:
    """One row, one event: Coinbase, Kraken trades, Binance spot, Bitpanda…"""
    from stocks.portfolio.llm_map import _date

    events = []
    for n, row in enumerate(grid[spec.header_row + 1:], start=spec.header_row + 2):
        what = _type_text(row, spec)
        if klass := _flat(_cell(row, spec, "asset_class")):
            if not re.search(r"crypto|coin|token|fiat", klass):
                _skip(result, n, what, "not a crypto asset")
                continue
        day = _date(_cell(row, spec, "date"), spec.date_format)
        if not day:
            _skip(result, n, what, "date not recognised")
            continue
        qty, qty_unit = _amount(_cell(row, spec, "quantity"), spec)
        asset = _asset(_cell(row, spec, "asset")) or qty_unit
        quote = _asset(_cell(row, spec, "quote"))
        if pair := split_pair(_cell(row, spec, "pair")):
            asset, quote = asset or pair[0], quote or pair[1]
        total, total_unit = _amount(_cell(row, spec, "total"), spec)
        price, price_unit = _amount(_cell(row, spec, "price"), spec)
        quote = (quote or total_unit or price_unit
                 or spec.units.get("total") or spec.units.get("price", ""))
        role = role_of(what, spec.type_map)
        if role is None and not what:
            role = "trade"  # a trades-only export with no type column
        if role is None:
            _skip(result, n, what, "transaction type not recognised")
            continue
        if role == "ignore":
            _skip(result, n, what, "moves coins inside the exchange, nothing to book")
            continue

        if role == "convert":
            text = " ".join(c for c in (_cell(row, spec, "note"), what) if c)
            m = _CONVERTED.search(text)
            spent = _number(m.group(1), _PLAIN) if m else None
            got = _number(m.group(3), _PLAIN) if m else None
            if not (m and spent and got):
                _skip(result, n, what, "conversion without both sides")
                continue
            gross = abs(total) if total else (abs(qty or 0) * abs(price) if price else 0)
            events.append(Event(
                n, day, "exchange", got=(_asset(m.group(4)), abs(got)),
                gave=(_asset(m.group(2)), abs(spent)),
                fee=_fee(row, spec, quote),
                value=(quote, gross) if gross and _is_fiat(quote) else None,
                what=what,
            ))
            continue

        if not qty or not asset:
            _skip(result, n, what, "no quantity or asset")
            continue
        gross = abs(total) if total else (abs(qty) * abs(price) if price else 0.0)
        sign = _direction(row, spec) or (1 if qty > 0 else -1)
        if role == "trade":
            if total and (total < 0) != (qty < 0):
                role = "buy" if qty > 0 else "sell"
            elif _direction(row, spec):
                role = "buy" if sign > 0 else "sell"
            else:
                _skip(result, n, what, "trade direction unclear")
                continue
        if role == "move":
            role = "receive" if sign > 0 else "send"
        qty = abs(qty)
        fee = _fee(row, spec, quote)
        value = (quote, gross) if gross and _is_fiat(quote) else None
        if role in ("buy", "sell"):
            if not quote or not gross:
                _skip(result, n, what, "trade without its price or total")
                continue
            legs = {"got": (asset, qty), "gave": (quote, gross)}
            if role == "sell":
                legs = {"got": (quote, gross), "gave": (asset, qty)}
            events.append(Event(n, day, "exchange", fee=fee, what=what, **legs))
        elif role in ("reward", "receive"):
            events.append(Event(n, day, role, got=(asset, qty), fee=fee,
                                value=value, what=what))
        else:  # send, fee
            events.append(Event(n, day, role, gave=(asset, qty), fee=fee,
                                value=value, what=what))
    return events


def _swaps(grid: list[list[str]], spec: Spec, result: ParseResult) -> list[Event]:
    """Sent and received on one row: Koinly, Crypto.com, Nexo, Binance Convert."""
    from stocks.portfolio.llm_map import _date

    events = []
    for n, row in enumerate(grid[spec.header_row + 1:], start=spec.header_row + 2):
        what = _type_text(row, spec)
        day = _date(_cell(row, spec, "date"), spec.date_format)
        if not day:
            _skip(result, n, what, "date not recognised")
            continue
        role = role_of(what, spec.type_map)
        if role == "ignore":
            _skip(result, n, what, "moves coins inside the exchange, nothing to book")
            continue
        sent = received = None
        q, unit = _amount(_cell(row, spec, "sent_quantity"), spec)
        if q:
            sent = (_asset(_cell(row, spec, "sent_asset")) or unit, abs(q))
        q, unit = _amount(_cell(row, spec, "received_quantity"), spec)
        if q:
            received = (_asset(_cell(row, spec, "received_asset")) or unit, abs(q))
        # A signed single leg (Crypto.com's Currency/Amount): negative left
        # the account, positive arrived.
        q, unit = _amount(_cell(row, spec, "quantity"), spec)
        if q:
            leg = (_asset(_cell(row, spec, "asset")) or unit, abs(q))
            if q < 0 and sent is None:
                sent = leg
            elif q > 0 and received is None:
                received = leg
        if sent and received and sent[0] == received[0]:
            # The same asset on both sides is one movement written twice
            # (Nexo's interest rows), never an exchange.
            sent = None if role in ("reward", "receive", None) else sent
            received = None if sent else received
        sent = sent if sent and sent[0] else None
        received = received if received and received[0] else None
        value = _value(row, spec)
        fee = _fee(row, spec, "")
        if sent and received:
            events.append(Event(n, day, "exchange", got=received, gave=sent,
                                fee=fee, value=value, what=what))
        elif received:
            if role in ("buy", "trade", "convert") and value:
                events.append(Event(n, day, "exchange", got=received,
                                    gave=value, fee=fee, value=value, what=what))
            elif role in ("sell", "send", "fee", "trade", "convert"):
                _skip(result, n, what, "trade without its other side")
            else:
                events.append(Event(n, day, "reward" if role == "reward" else "receive",
                                    got=received, fee=fee, value=value, what=what))
        elif sent:
            if role in ("sell", "trade", "convert") and value:
                events.append(Event(n, day, "exchange", got=value, gave=sent,
                                    fee=fee, value=value, what=what))
            elif role in ("buy", "reward", "receive", "trade", "convert"):
                _skip(result, n, what, "trade without its other side")
            else:
                events.append(Event(n, day, "fee" if role == "fee" else "send",
                                    gave=sent, fee=fee, value=value, what=what))
        else:
            _skip(result, n, what, "no quantity or asset")
    return events


def _ledger(grid: list[list[str]], spec: Spec, result: ParseResult) -> list[Event]:
    """One balance change per row: Binance statement, Kraken ledgers.

    A trade is the rows sharing a reference id — or, without one, the exact
    same timestamp — netted per asset: what went up was bought, what went
    down paid for it, fee rows and fee columns are the fee.
    """
    from stocks.portfolio.llm_map import _date

    events: list[Event] = []
    # group key -> (row, type text, day, asset, quantity, fee column, is a fee row)
    groups: dict[str, list[tuple[int, str, str, str, float, float, bool]]] = {}
    for n, row in enumerate(grid[spec.header_row + 1:], start=spec.header_row + 2):
        what = _type_text(row, spec)
        stamp = _cell(row, spec, "date")
        day = _date(stamp, spec.date_format)
        if not day:
            _skip(result, n, what, "date not recognised")
            continue
        qty, unit = _amount(_cell(row, spec, "quantity"), spec)
        asset = _asset(_cell(row, spec, "asset")) or unit
        if not qty or not asset:
            _skip(result, n, what, "no quantity or asset")
            continue
        fee = abs(_amount(_cell(row, spec, "fee"), spec)[0] or 0.0)
        role = role_of(what, spec.type_map)
        if role is None:
            _skip(result, n, what, "transaction type not recognised")
            continue
        if role == "ignore":
            _skip(result, n, what, "moves coins inside the exchange, nothing to book")
            continue
        if role in ("buy", "sell", "trade", "convert", "fee"):
            key = _cell(row, spec, "group") or stamp
            groups.setdefault(key, []).append(
                (n, what, day, asset, qty, fee, role == "fee"))
            continue
        leg = (asset, abs(qty))
        extra = (asset, fee) if fee else None
        if role == "move":
            role = "receive" if qty > 0 else "send"
        if role in ("reward", "receive"):
            events.append(Event(n, day, role, got=leg, fee=extra, what=what))
        else:
            events.append(Event(n, day, role, gave=leg, fee=extra, what=what))

    for rows in groups.values():
        n, _, day = rows[0][:3]
        what = next((r[1] for r in rows if not r[6]), rows[0][1])
        net: dict[str, float] = defaultdict(float)
        fees: dict[str, float] = defaultdict(float)
        for _, _, _, asset, qty, fee, is_fee in rows:
            if is_fee:
                fees[asset] += abs(qty)
            else:
                net[asset] += qty
                fees[asset] += fee
        got = [(a, q) for a, q in net.items() if q > 1e-12]
        gave = [(a, -q) for a, q in net.items() if q < -1e-12]
        fee_legs = [(a, q) for a, q in fees.items() if q > 0]
        first_fee = fee_legs[0] if fee_legs else None
        if len(got) == 1 and len(gave) == 1:
            events.append(Event(n, day, "exchange", got=got[0], gave=gave[0],
                                fee=first_fee, what=what))
            events += [Event(n, day, "fee", gave=leg, what="fee") for leg in fee_legs[1:]]
        elif len(got) == 1 and not gave:
            # A purchase whose paying leg is not in this file (a card buy).
            events.append(Event(n, day, "receive", got=got[0], fee=first_fee, what=what))
        elif len(gave) == 1 and not got:
            events.append(Event(n, day, "send", gave=gave[0], fee=first_fee, what=what))
        elif not got and not gave and fee_legs:
            events += [Event(n, day, "fee", gave=leg, what=what) for leg in fee_legs]
        else:
            _skip(result, n, what, "several assets traded at once, book by hand")
    return events


_LAYOUT = {"rows": _rows, "swaps": _swaps, "ledger": _ledger}


# ---------------------------------------------------------------- values


class Valuer:
    """What a coin was worth on a day, in a fiat; and fiat in another fiat.

    Market closes come from the shared price layer in one bulk download per
    import (`prefetch`), so a file of three thousand staking rewards is one
    request, not three thousand. Every answer may be None: Yahoo throttles,
    and an unpriced event is skipped with its reason rather than guessed.
    """

    def __init__(self) -> None:
        self._series: dict[str, pd.Series | None] = {}
        self._lock = threading.Lock()

    def prefetch(self, coins: set[str], fiat: str, since: str) -> None:
        from stocks.data import fetch

        pairs = [crypto.to_pair(c, fiat) for c in sorted(coins)
                 if _COIN.match(c) and c not in PEGS]
        pairs = [p for p in pairs if p not in self._series]
        if not pairs:
            return
        years = max(1, _day.today().year - int(since[:4]) + 1)
        period = next((p for y, p in ((1, "1y"), (2, "2y"), (5, "5y"), (10, "10y"))
                       if years <= y), "max")
        try:
            frames = fetch.fetch_many(pairs, period=period, auto_adjust=False)
        except Exception as exc:  # noqa: BLE001 — throttled is unpriced, not fatal
            obs.warn("import.crypto.prices_failed", error_type=type(exc).__name__,
                     pairs=len(pairs))
            frames = {}
        with self._lock:
            for pair in pairs:
                df = frames.get(pair)
                self._series[pair] = (
                    df["Close"].dropna() if df is not None and "Close" in df else None
                )

    def coin(self, coin: str, fiat: str, day: str) -> float | None:
        if coin in PEGS:
            return self.fiat(PEGS[coin], fiat, day)
        series = self._series.get(crypto.to_pair(coin, fiat))
        if series is None or len(series) == 0:
            return None
        import pandas as pd

        index = pd.DatetimeIndex(series.index).tz_localize(None)
        upto = series[index <= pd.Timestamp(day)]
        return float(upto.iloc[-1]) if len(upto) else None

    def fiat(self, base: str, quote: str, day: str) -> float | None:
        if base == quote:
            return 1.0
        from stocks.data import fx

        try:
            return fx.rate_on(day, base, quote)
        except Exception:  # noqa: BLE001
            return None


# ------------------------------------------------------------------ booking


def _fiat_of(events: list[Event], hint: str) -> str:
    """The one fiat the whole import is booked in.

    The file's own, when its trades are against one we price in; the
    account's otherwise (a USDT-only Binance history for a euro account is
    booked in euros); dollars last.
    """
    seen = Counter()
    for e in events:
        for leg in (e.got, e.gave, e.value):
            if leg and _is_fiat(leg[0]):
                seen[leg[0]] += 1
    for ccy, _ in seen.most_common():
        if ccy in crypto.QUOTE_CURRENCIES:
            return ccy
    hint = (hint or "").upper()
    return hint if hint in crypto.QUOTE_CURRENCIES else "USD"


class _Book:
    def __init__(self, fiat: str, valuer: Valuer, broker: str,
                 result: ParseResult) -> None:
        self.fiat, self.valuer, self.broker, self.result = fiat, valuer, broker, result
        self.rows: list[Transaction] = []

    def _note(self, *words: str) -> str:
        return " ".join(w for w in (self.broker, *words) if w)[:120]

    def money(self, leg: tuple[str, float], day: str) -> float | None:
        """A fiat leg in the book's fiat."""
        rate = self.valuer.fiat(leg[0], self.fiat, day)
        return leg[1] * rate if rate else None

    def worth(self, leg: tuple[str, float], day: str) -> float | None:
        """Any leg in the book's fiat: money converted, coins at that day's close."""
        if _is_fiat(leg[0]):
            return self.money(leg, day)
        price = self.valuer.coin(leg[0], self.fiat, day)
        return leg[1] * price if price else None

    def stated(self, e: Event) -> float | None:
        """What the export itself says the event was worth, in the book's fiat."""
        return self.money(e.value, e.day) if e.value else None

    def pair(self, coin: str) -> str | None:
        return crypto.to_pair(coin, self.fiat) if _COIN.match(coin) else None

    def add(self, day: str, coin: str, action: str, qty: float, price: float,
            fee: float = 0.0, note: str = "") -> None:
        self.rows.append(Transaction(
            date=day, ticker=self.pair(coin) or coin, action=action,
            quantity=qty, price=price, currency=self.fiat, fee=max(fee, 0.0),
            note=self._note(note),
        ))

    # -- each event

    def exchange(self, e: Event) -> None:
        if e.gave is None or e.got is None:
            return _skip(self.result, e.row, e.what, "trade without its other side")
        (a, qa), (b, qb) = e.gave, e.got
        if _is_fiat(a) and _is_fiat(b):
            return _skip(self.result, e.row, e.what, "currency exchange, no crypto")
        for coin in (a, b):
            if not _is_fiat(coin) and not self.pair(coin):
                return _skip(self.result, e.row, e.what, "coin code not supported")
        # What the swap was worth: the money side, else what the row says,
        # else the stablecoin side, else the coin received, else the one spent.
        if _is_fiat(a) or _is_fiat(b):
            value = self.money(e.gave if _is_fiat(a) else e.got, e.day)
        else:
            value = self.stated(e)
            legs = sorted((e.got, e.gave), key=lambda leg: leg[0] not in PEGS)
            for leg in legs:
                if value:
                    break
                value = self.worth(leg, e.day)
        if not value:
            return _skip(self.result, e.row, e.what, "could not be valued that day")

        fee_coin, fee_qty = e.fee or ("", 0.0)
        extra = 0.0  # a fee paid apart from both legs, in the book's fiat
        if fee_coin and (_is_fiat(fee_coin) or fee_coin not in (a, b)):
            worth = self.worth((fee_coin, fee_qty), e.day)
            if worth is None:
                _skip(self.result, e.row, e.what, "fee could not be valued, left out")
            else:
                extra = worth
                if not _is_fiat(fee_coin) and self.pair(fee_coin):
                    # Paying the fee in BNB disposes of the BNB.
                    self.add(e.day, fee_coin, "sell", fee_qty, worth / fee_qty,
                             note="fee paid in coin")
            fee_coin = ""

        if not _is_fiat(a):  # a coin left: a sale at the swap's value
            sold, spent = qa, 0.0  # spent: what the coins that paid the fee were worth
            if fee_coin == a:  # the fee came out of the coin sold
                spent, sold = fee_qty * value / qa, qa + fee_qty
            fee = spent + (extra if _is_fiat(b) else 0.0)
            self.add(e.day, a, "sell", sold, (value + spent) / sold, fee, note="trade")
        if not _is_fiat(b):  # a coin arrived: a purchase at the swap's value
            bought, fee = qb, extra
            if fee_coin == b:  # the fee came out of the coin bought
                fee, bought = fee + fee_qty * value / qb, qb - fee_qty
            if bought <= 0:
                return _skip(self.result, e.row, e.what, "fee larger than the trade")
            self.add(e.day, b, "buy", bought, value / qb, fee, note="trade")

    def reward(self, e: Event) -> None:
        if e.got is None:
            return _skip(self.result, e.row, e.what, "no quantity or asset")
        coin, qty = e.got
        if _is_fiat(coin):
            return _skip(self.result, e.row, e.what, "cash interest is not tracked")
        if not self.pair(coin):
            return _skip(self.result, e.row, e.what, "coin code not supported")
        value = self.stated(e) or self.worth(e.got, e.day)
        if not value:
            return _skip(self.result, e.row, e.what, "could not be valued that day")
        what = _flat(e.what) or "reward"
        # Income at market value, and the coins at that same cost basis: a
        # later sale gains only on what the coin did after it arrived.
        self.add(e.day, coin, "buy", qty, value / qty, note=f"reward {what}")
        self.add(e.day, coin, "dividend", 0.0, value, note=f"reward {what}")

    def receive(self, e: Event) -> None:
        if e.got is None:
            return _skip(self.result, e.row, e.what, "no quantity or asset")
        coin, qty = e.got
        if _is_fiat(coin):
            return _skip(self.result, e.row, e.what, "cash deposit, nothing to book")
        if not self.pair(coin):
            return _skip(self.result, e.row, e.what, "coin code not supported")
        value = self.stated(e) or self.worth(e.got, e.day)
        if not value:
            return _skip(self.result, e.row, e.what, "could not be valued that day")
        # The real basis is wherever the coins came from; until that wallet's
        # history is imported too, the day's value is the best estimate.
        self.add(e.day, coin, "transfer_in", qty, value / qty,
                 note="deposit basis at market value, edit if known")

    def send(self, e: Event) -> None:
        if e.gave is None:
            return _skip(self.result, e.row, e.what, "no quantity or asset")
        coin, qty = e.gave
        if _is_fiat(coin):
            return _skip(self.result, e.row, e.what, "cash withdrawal, nothing to book")
        if not self.pair(coin):
            return _skip(self.result, e.row, e.what, "coin code not supported")
        price = self.valuer.coin(coin, self.fiat, e.day) or 0.0
        self.add(e.day, coin, "transfer_out", qty, price, note="withdrawal")
        if e.fee and e.fee[0] == coin:
            self.fee(replace(e, gave=e.fee, fee=None, what="withdrawal fee"))

    def fee(self, e: Event) -> None:
        if e.gave is None:
            return _skip(self.result, e.row, e.what, "no quantity or asset")
        coin, qty = e.gave
        if _is_fiat(coin):
            return _skip(self.result, e.row, e.what, "cash fee, nothing to book")
        price = self.valuer.coin(coin, self.fiat, e.day)
        if not price or not self.pair(coin):
            return _skip(self.result, e.row, e.what, "could not be valued that day")
        # Coins spent on a fee are sold at market with nothing coming back.
        self.add(e.day, coin, "sell", qty, price, qty * price, note="fee paid in coin")


_FIRST = {"buy": 0, "transfer_in": 0, "dividend": 1, "sell": 2, "transfer_out": 2}


def _merge(rows: list[Transaction]) -> list[Transaction]:
    """One row per day, coin, action and kind of event.

    A staking export is one reward per coin per day and an exchange's history
    one row per fill; collapsing them keeps the book readable and keeps the
    duplicate check from flagging the second identical fill of the day.
    Transfers stay as they are: they pair with the other wallet's legs by
    quantity.
    """
    merged: dict[tuple, Transaction] = {}
    out: list[Transaction] = []
    for tx in rows:
        if tx.action.startswith("transfer"):
            out.append(tx)
            continue
        key = (tx.date, tx.ticker, tx.action, tx.note)
        if (have := merged.get(key)) is None:
            merged[key] = replace(tx)
            out.append(merged[key])
            continue
        if tx.action == "dividend":
            have.price += tx.price
        else:
            total = have.quantity + tx.quantity
            have.price = (have.price * have.quantity + tx.price * tx.quantity) / total
            have.quantity = total
        have.fee += tx.fee
    out.sort(key=lambda t: (t.date, _FIRST.get(t.action, 1)))
    for tx in out:
        tx.quantity = round(tx.quantity, 10)
        tx.price = round(tx.price, 10)
        tx.fee = round(tx.fee, 6)
    return out


def book(events: list[Event], *, fiat_hint: str = "", valuer: Valuer | None = None,
         broker: str = "", result: ParseResult | None = None) -> ParseResult:
    """Events to ledger rows, in one fiat."""
    result = result if result is not None else ParseResult()
    if not events:
        return result
    valuer = valuer or Valuer()
    fiat = _fiat_of(events, fiat_hint)
    coins = {leg[0] for e in events for leg in (e.got, e.gave, e.fee)
             if leg and not _is_fiat(leg[0])}
    valuer.prefetch(coins, fiat, min(e.day for e in events))
    ledger = _Book(fiat, valuer, broker, result)
    for e in sorted(events, key=lambda e: (e.day, e.row)):
        getattr(ledger, e.kind)(e)
    result.transactions = _merge(ledger.rows)
    result.skipped.sort(key=lambda s: s["row"])
    return result


def apply(grid: list[list[str]], spec: Spec, *, fiat_hint: str = "",
          valuer: Valuer | None = None) -> ParseResult:
    """Read every row with the spec and book it. No model here."""
    result = ParseResult()
    if not spec.units:
        spec = replace(spec, units=_header_units(grid, spec))
    events = _LAYOUT[spec.layout](grid, spec, result)
    return book(events, fiat_hint=fiat_hint, valuer=valuer, broker=spec.exchange,
                result=result)


# ------------------------------------------------------------- the model

_SYSTEM = """You map a cryptocurrency exchange or wallet export onto roles.
You are shown the first rows of the file, each cell separated by " | ",
numbered by row and (implicitly) by column, starting at 0.

First decide the layout:
- "rows": one row per trade or event, with the asset (or a pair like BTCEUR),
  its quantity and what it cost (price and/or total) in a quote currency.
- "swaps": each row has a sent side and a received side (sent/received or
  input/output amount and currency), sometimes with a fiat value.
- "ledger": each row is one balance change of one asset (positive in,
  negative out); a trade is several rows sharing a time or reference id.
If the file holds shares or funds rather than crypto, or is not a list of
transactions at all, set "layout" to null.

Then name the columns (0-based positions in the " | " list, NOT header names;
null when absent):
- date, type (what happened), subtype (a second type column, if any)
- asset, quantity: the coin and how much of it moved (signed or not)
- pair: a market column like BTCEUR or ETH/USDT, when there is no asset column
- price: per-unit price; total: the trade's value BEFORE fees; quote: the
  currency price and total are in
- fee, fee_asset: the fee and the coin or currency it was paid in
- sent_quantity, sent_asset, received_quantity, received_asset (swaps)
- value, value_currency: what the row was worth in fiat
- group: a reference id shared by the rows of one trade (ledgers)
- direction: an in/out column; asset_class: a crypto/fiat/stock column
- note: a free-text description

"type_map": one entry per distinct value you can see in the type column ->
one of buy, sell, trade (a trade leg whose sign gives the direction),
convert (a swap described in a sentence), reward (staking, interest, earn,
airdrops, cashback, referral), receive (deposit), send (withdrawal),
move (transfer whose sign gives the direction), fee, or ignore (moves inside
the exchange: subscriptions, redemptions, locks, wallet transfers).
"exchange": the platform's name when the file shows it (headers, title).
Never invent values from the sample rows; you are only naming columns.
"""


def _spec_from(data: dict, grid: list[list[str]]) -> Spec | None:
    from stocks.portfolio.llm_map import _index

    layout = data.get("layout")
    if layout not in LAYOUTS:
        return None
    width = max((len(r) for r in grid), default=0)
    header = _index(data.get("header_row"), len(grid))
    cols = {role: i for role in COLUMNS
            if (i := _index((data.get("columns") or {}).get(role), width)) is not None}
    if header is None or "date" not in cols:
        return None
    needs = {
        "rows": ("quantity",),
        "swaps": (),
        "ledger": ("quantity",),
    }[layout]
    if any(r not in cols for r in needs):
        return None
    legs = {"sent_quantity", "received_quantity", "quantity"}
    if layout == "swaps" and not legs & set(cols):
        return None
    type_map = {str(k): str(v).lower() for k, v in (data.get("type_map") or {}).items()
                if str(v).lower() in ROLES}
    return Spec(
        platforms.broker_key(data.get("exchange") or "") if data.get("exchange") else "",
        layout, header, cols,
        date_format=str(data.get("date_format") or ""),
        decimal=str(data.get("decimal") or "."),
        thousands=str(data.get("thousands") or ""),
        type_map=type_map,
    )


def map_crypto(provider: Provider, api_key: str, grid: list[list[str]]) -> Spec | None:
    """Ask the model how this crypto export is laid out; None when it can't say.

    A model that could not be reached raises llm_map.ProviderUnavailable.
    """
    from stocks.chat import structured
    from stocks.portfolio import llm_map

    raw = llm_map._ask(provider, api_key, "MapCrypto", _SYSTEM, llm_map.sample(grid))
    with llm_map._replying(provider):
        try:
            data = structured.parse(raw, "MapCrypto")
        except structured.OffContract:
            return None
    return _spec_from(data, grid) if isinstance(data, dict) else None


def looks_crypto(grid: list[list[str]]) -> bool:
    """Whether the file is worth asking the crypto mapper about.

    Two distinct coins we know by name, written as a whole cell, a pair or a
    glued amount ("0.5ETH"), in the first rows. A share statement holding
    ETH and SOL tickers can pass; the model then answers null and the share
    mapping reads it.
    """
    seen: set[str] = set()
    for row in grid[:60]:
        for cell in row:
            text = cell.strip()
            if not text or len(text) > 24:
                continue
            up = text.upper()
            candidates = {up}
            if pair := split_pair(up):
                candidates |= set(pair)
            glued = re.fullmatch(r"[-+]?[\d.,]+\s*([A-Za-z][A-Za-z0-9]{1,9})", text)
            if glued:
                candidates.add(glued.group(1).upper())
            seen |= {_asset(c) for c in candidates
                     if _asset(c) in crypto.CRYPTO_NAMES and _asset(c) not in FIAT}
            if len(seen) >= 2:
                return True
    return False


def label(exchange: str) -> str:
    """Display name for a spec's exchange key."""
    return platforms.broker_label(exchange) if exchange else ""

