"""Ledger and tax exports — the CSV files the Profile and Tax pages hand back.

The privacy policy promises the data is the account's own to take away, and
"take away" has to mean a file, not a screenshot of a table. The one thing
worth doing here beyond dumping the rows is the conversion: the app reckons in
the account's reference currency, so an export whose amounts are still in five
native currencies is not the book the user sees. Every row carries the ECB
rate for its OWN trade date and the converted amount alongside the original.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from stocks.portfolio.ledger import all_transactions

# The signed amount a row moves, by action. `split` has no cash leg, so it
# exports with an empty amount rather than a zero that would look like a
# free trade.
_GROSS = {
    "buy": lambda t: t.quantity * t.price,
    "sell": lambda t: t.quantity * t.price,
    "dividend": lambda t: t.price,
    "capital": lambda t: t.price,
    "fee": lambda t: t.fee,
}


def ledger_csv(db: Path | str, base: str = "EUR") -> bytes:
    """Every transaction as CSV, each row also converted to `base`.

    Best-effort on the FX: the rates are warmed in one range request per
    currency, and a row whose rate cannot be fetched exports with an empty
    rate and an empty converted amount rather than a wrong one — an offline
    export is still the ledger.
    """
    from stocks.data import fx

    txs = all_transactions(Path(db))
    if not txs:
        return b""
    try:
        fx.prefetch([(t.date, t.currency) for t in txs], base)
    except Exception:  # noqa: BLE001 — the native columns are the export
        pass

    rows = []
    for t in txs:
        gross = _GROSS[t.action](t) if t.action in _GROSS else None
        try:
            rate = fx.rate_on(t.date, t.currency, base) if gross is not None else None
        except Exception:  # noqa: BLE001 — one unreachable date, not the export
            rate = None
        rows.append(
            {
                "date": t.date,
                "ticker": t.ticker,
                "action": t.action,
                "quantity": t.quantity,
                "price": t.price,
                "currency": t.currency,
                "fee": t.fee,
                "note": t.note,
                "fx_rate": rate,
                f"amount_{base.lower()}": (
                    None if (gross is None or rate is None) else gross * rate
                ),
            }
        )
    return pd.DataFrame(rows).to_csv(index=False).encode()


# The tax file's columns, in the order a return reads them: what kind of row,
# the tax year it files under, the name, the dates, then the money. A cell is
# blank where the kind has no such figure — a dividend has no cost, a sale has
# nothing withheld — rather than a zero that would read as "nothing paid".
TAX_COLUMNS = [
    "kind",
    "tax_year",
    "ticker",
    "date",
    "acquired",
    "quantity",
    "cost",
    "proceeds",
    "gain",
    "gross",
    "withheld",
    "currency",
    "matched",
]


def tax_csv(
    realized,
    transactions,
    *,
    currency: str,
    tax_year_of: Callable[[str], int],
    year: int | None = None,
) -> bytes:
    """The taxable rows as CSV: one per matched lot sold, one per dividend.

    This is the Realized & tax tab as a file, so it follows the tab's rules
    rather than the ledger's: `realized` is the replay at the jurisdiction's
    currency under its own share-matching, so a sale's cost and proceeds are
    already in `currency` and `matched` says which rule paired the lot. A
    dividend is booked in whatever it was paid in and is converted here at its
    pay date's ECB rate, gross and withheld alike — the two figures a return
    asks for. `year` keeps one tax year by the jurisdiction's own calendar
    (`tax_year_of`: a UK year opens on 6 April), every year when None.

    Best-effort on the FX, as the ledger export is: a payment whose rate
    cannot be fetched exports with empty money cells rather than a wrong
    figure. No row at all is b"", the route's cue for a 404.
    """
    from stocks.data import fx

    rows: list[dict] = []
    for sale in realized:
        rows.append(
            {
                "kind": "sale",
                "tax_year": tax_year_of(sale.sell_date),
                "ticker": sale.ticker,
                "date": sale.sell_date,
                "acquired": sale.buy_date,
                "quantity": sale.quantity,
                "cost": round(sale.cost, 6),
                "proceeds": round(sale.proceeds, 6),
                "gain": round(sale.gain, 6),
                "gross": None,
                "withheld": None,
                "currency": currency,
                "matched": sale.matched,
            }
        )
    paid = [t for t in transactions if t.action == "dividend"]
    if paid:
        try:
            fx.prefetch([(t.date, t.currency) for t in paid], currency)
        except Exception:  # noqa: BLE001 — a row without a rate, not no file
            pass
        to_base = fx.converter(currency)
    for t in paid:
        try:
            gross: float | None = round(to_base(t.price, t.currency, t.date), 6)
            withheld: float | None = round(to_base(t.fee, t.currency, t.date), 6)
        except Exception:  # noqa: BLE001 — one unreachable date, not the export
            gross = withheld = None
        rows.append(
            {
                "kind": "dividend",
                "tax_year": tax_year_of(t.date),
                "ticker": t.ticker,
                "date": t.date,
                "acquired": None,
                "quantity": None,
                "cost": None,
                "proceeds": None,
                "gain": None,
                "gross": gross,
                "withheld": withheld,
                "currency": currency,
                "matched": None,
            }
        )
    if year is not None:
        rows = [row for row in rows if row["tax_year"] == year]
    if not rows:
        return b""
    rows.sort(key=lambda row: (row["date"], row["kind"], row["ticker"]))
    return pd.DataFrame(rows, columns=TAX_COLUMNS).to_csv(index=False).encode()
