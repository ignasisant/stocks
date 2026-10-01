"""Which listing a bare broker code was traded on.

Revolut prints Allianz as "ALV", in euros. Yahoo quotes a bare "ALV" too —
Autoliv, in dollars — so the import never had a reason to look further
(`symbols.symbol_for_code` is for codes Yahoo does not quote at all), the row
went in as "ALV", and every price, return and tax figure on it was Autoliv's.
A bare Yahoo symbol is a US line, so a bare code traded in any other currency
is a line on another exchange that happens to share the letters.

`pick` names that line, and only on evidence: the trade's own price against
each candidate's close on the trade day (`TOLERANCE`). A code is a guess; a
fill at 248.60 EUR on a day ALV.DE closed at 249.10 is not. The candidates are
the labels the book already uses for the code in that currency (a ClickTrade
import books ALV.DE), then the venues the search offers
(`symbols.listings_for_code`), and the first one the price agrees with wins.
A venue the search offered loses, though, to the bare line itself when its
dollar close in the trade currency agrees as well: that is a US share booked
in euros, or an ADR that trades 1:1 (SAP, Santander's SAN), and moving it
buys nothing but a thin European mirror of a US line. Nothing agrees, or
nothing could be asked, and the code stays as the statement printed it: a
relabel is a verdict, and "Yahoo was throttled" is not one.

The answer is per (code, currency), never per code: the dollar "ALV" rows in
the same book are still Autoliv.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Sequence

from stocks.data import symbols
from stocks.data.crypto import is_crypto
from stocks.portfolio.ledger import Transaction

Key = tuple[str, str]  # (bare code as the ledger holds it, trade currency)

# How far a fill may sit from the day's close and still be that line's: wide
# enough for an intraday swing, far narrower than the gap between two
# companies that share a code (Santander ~5 EUR, Sanofi ~90).
TOLERANCE = 0.08

# Lines Yahoo quotes in the minor unit (London pence, JSE cents, TASE agorot)
# while brokers book either unit under one code.
_MINOR_UNIT = {"GBP", "GBX", "ZAR", "ZAC", "ILS", "ILA"}

# The major unit an exchange rate is published for; `agrees` scales by 100.
_MAJOR = {"GBX": "GBP", "ZAC": "ZAR", "ILA": "ILS"}

# Two most recent trade days: one can be an off-market print, both rarely are,
# and each one is a download.
_SAMPLES = 2


def _bare(tx: Transaction) -> bool:
    cur = tx.currency
    code = tx.ticker
    return (
        bool(code)
        and cur not in ("", "USD")
        and "." not in code
        and not is_crypto(code)
        and not symbols.is_isin(code)
        and bool(symbols.venue_symbols(code, cur))
    )


def keys(rows: Sequence[Transaction], prior: Sequence[Transaction]) -> list[Key]:
    """The (code, currency) pairs worth asking about, in first-seen order.

    Every bare code the statement brings, and every bare code already in the
    book that a suffixed label in the same currency claims (Revolut's "ALV"
    next to ClickTrade's "ALV.DE"): otherwise the two imports are two
    positions in one company.
    """
    labels = {(t.ticker, t.currency) for t in (*rows, *prior) if "." in t.ticker}
    out: list[Key] = []
    for t in rows:
        if _bare(t) and (k := (t.ticker, t.currency)) not in out:
            out.append(k)
    for t in prior:
        k = (t.ticker, t.currency)
        if k in out or not _bare(t):
            continue
        if any((s, t.currency) in labels for s in symbols.venue_symbols(*k)):
            out.append(k)
    return out


def _samples(key: Key, rows: Iterable[Transaction]) -> list[tuple[str, float]]:
    """(day, price) of the key's latest trades, one per day, newest first."""
    by_day: dict[str, float] = {}
    for t in rows:
        if (t.ticker, t.currency) == key and t.action in ("buy", "sell") and t.price > 0:
            by_day[t.date[:10]] = t.price
    return sorted(by_day.items(), reverse=True)[:_SAMPLES]


def _fill(t: Transaction) -> tuple:
    """A trade as validation's duplicate check sees it, label first."""
    return (t.ticker, t.date, t.action, round(t.quantity, 6), round(t.price, 4))


def agrees(
    symbol: str,
    samples: Sequence[tuple[str, float]],
    currency: str,
    close: Callable[[str, str], float | None],
) -> bool | None:
    """Whether `symbol` closed near every sampled fill; None when no sampled
    day has a close at all (unlisted there, or Yahoo could not be asked)."""
    units = (1.0, 0.01, 100.0) if currency in _MINOR_UNIT else (1.0,)
    seen = False
    for day, price in samples:
        last = close(symbol, day)
        if not last or last <= 0:
            continue
        seen = True
        if not any(abs(price - last * u) <= TOLERANCE * last * u for u in units):
            return False
    return True if seen else None


def pick(
    key: Key,
    rows: Sequence[Transaction],
    prior: Sequence[Transaction],
    *,
    quoted: Callable[[str], bool],
    candidates: Callable[[str, str], list[str]],
    close: Callable[[str, str], float | None],
    usd_rate: Callable[[str, str], float | None],
) -> str | None:
    """The listing `key`'s rows were traded on, or None to leave them be.

    `quoted(code)` says Yahoo quotes the bare code (the case the search was
    never asked about); only then are `candidates` searched for. A label the
    book already uses is tried either way, but proven by price like any
    other: "SAN.PA" in a ClickTrade import says nothing about whether
    Revolut's "SAN" is Sanofi or Santander.

    `usd_rate(currency, day)` turns the bare line's dollar close into the
    trade currency, for the one check a searched venue has to pass besides
    its own price: that the bare line does not explain the fill just as well.

    A fill the book already holds under a label, to the share and the cent,
    proves that label without a price: it is the same statement imported
    again, and it has to find its duplicates while Yahoo is throttled too.
    """
    code, currency = key
    samples = _samples(key, (*rows, *prior))
    if not samples:
        return None
    used = {t.ticker for t in (*rows, *prior) if t.currency == currency}
    booked = {_fill(t) for t in prior if t.currency == currency}
    mine = [_fill(t)[1:] for t in rows if (t.ticker, t.currency) == key]
    tried: list[str] = []
    for symbol in symbols.venue_symbols(code, currency):
        if symbol in used:
            tried.append(symbol)
            if any((symbol, *m) in booked for m in mine):
                return symbol
            if agrees(symbol, samples, currency, close):
                return symbol
    if not any((t.ticker, t.currency) == key for t in rows):
        return None  # only the book's own rows, claimed by a label: done above
    if not quoted(code):
        return None

    def bare_close(symbol: str, day: str) -> float | None:
        last = close(symbol, day)
        rate = usd_rate(_MAJOR.get(currency, currency), day) if last else None
        return last * rate if last and rate else None

    for symbol in candidates(code, currency):
        if symbol in tried or not agrees(symbol, samples, currency, close):
            continue
        # Unknown (no dollar history that day, no rate) is not "explains it":
        # the venue's own price already said where the fill was made.
        if agrees(code, samples, currency, bare_close):
            return None
        return symbol
    return None


def relabeled(rows: Iterable[Transaction], moved: dict[Key, str]) -> list[Transaction]:
    """`rows` with every moved (code, currency) under its listing."""
    return [
        dataclasses.replace(t, ticker=moved[(t.ticker, t.currency)])
        if (t.ticker, t.currency) in moved
        else t
        for t in rows
    ]


def relabel_skipped(skipped: list[dict], moved: dict[Key, str]) -> None:
    """Move the statement's split rows with their trades, in place: validation
    derives a split's ratio from the shares held under the same label."""
    for s in skipped:
        if "SPLIT" not in str(s.get("type", "")).upper():
            continue
        code = str(s.get("ticker") or "").upper()
        cur = str(s.get("currency") or "").upper()
        for (c, currency), symbol in moved.items():
            if code == c and cur in ("", currency):
                s["ticker"] = symbol
                break
