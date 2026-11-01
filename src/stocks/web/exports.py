"""Ledger and tax exports — the CSV files the Profile and Tax pages hand back.

The privacy policy promises the data is the account's own to take away, and
"take away" has to mean a file, not a screenshot of a table. The one thing
worth doing here beyond dumping the rows is the conversion: the app reckons in
the account's reference currency, so an export whose amounts are still in five
native currencies is not the book the user sees. Every row carries the ECB
rate for its OWN trade date and the converted amount alongside the original.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from stocks.portfolio.ledger import all_transactions

if TYPE_CHECKING:
    from stocks.accounts import UserPaths

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


# ------------------------------------------------------------ the whole account

# The account's files `account_bundle` leaves out, and why: the ledger goes as
# `ledger.csv` instead of its SQLite file (the rows are the data, the schema
# is the app's), and the conversation index is derived from chat.json and
# holds embeddings nobody can read back. The Web Push subscriptions are each
# a device's delivery address and keys: anyone holding one can push to it.
NOT_BUNDLED = frozenset({"portfolio.db", "chat_memory.db", "push.json"})

# Prefs keys that are credentials, or about one, rather than preferences: a
# provider key the account typed in (`engine.byok_fields`) is stored encrypted
# and never travels — an export is a file people forward.
_SECRET_SUFFIXES = ("_key_enc", "_key_saved_at", "_key_first_at")
_SECRET_WORDS = ("secret", "token", "password")

# What each file is, for the README — one line per name, in this order.
_ABOUT = {
    "ledger.csv": "every transaction, with the ECB rate of its own date",
    "watchlist.yaml": "the names you follow",
    "prefs.json": "your settings (provider keys left out)",
    "chat.json": "your conversations with the assistant",
    "chat_learnings.json": "what the assistant remembers about you",
    "decisions.json": "the decision journal: what the app proposed and what became of it",
    "daily_action.json": "the last daily briefing",
    "sector_verdict.json": "the last sector reads",
    "last_import.json": "the last statement import",
    "bank.json": "the bank connection, without credentials",
    "devices.json": "the browsers signed in (ids are hashes, no addresses)",
}


def bundled(paths: UserPaths) -> dict[str, Path]:
    """The account's files the bundle carries, by the name they get in it.

    Named through `UserPaths` rather than listed under `root`, because the
    owner's "root" is the checkout and its files live under data/.
    """
    files = (
        paths.watchlist, paths.prefs, paths.chat, paths.learnings, paths.journal,
        paths.action, paths.verdicts, paths.last_import, paths.bank, paths.devices,
    )
    return {path.name: path for path in files}


def _is_secret(key: str) -> bool:
    name = key.lower()
    return name.endswith(_SECRET_SUFFIXES) or any(w in name for w in _SECRET_WORDS)


def _public_prefs(raw: bytes) -> bytes:
    """The prefs file without its credentials. Unreadable prefs export as
    nothing rather than as bytes that might hold half a key."""
    try:
        prefs = json.loads(raw)
    except ValueError:
        return b"{}"
    if not isinstance(prefs, dict):
        return b"{}"
    kept = {k: v for k, v in prefs.items() if not _is_secret(k)}
    return json.dumps(kept, indent=2, ensure_ascii=False, sort_keys=True).encode()


def _readme(names: list[str], base: str) -> bytes:
    lines = [f"Your TopStocks data, exported {date.today():%Y-%m-%d}.", ""]
    width = max(len(n) for n in names) + 2
    for name in names:
        about = _ABOUT.get(name, "")
        if name == "ledger.csv":
            about += f" and the amount in {base}"
        lines.append(f"{name.ljust(width)}{about}".rstrip())
    lines += ["", "Only the files this account holds are included."]
    return "\n".join(lines).encode()


def account_bundle(paths: UserPaths, *, base: str = "EUR") -> bytes:
    """Everything the account holds, as one zip: the privacy policy's promise
    that the data can be taken away, kept for the whole account and not only
    the ledger.

    The ledger rides as `ledger_csv` in the reporting currency; the settings
    go without their provider keys; the rest — watchlist, conversations,
    memories, journal, briefings — is each file as it is. Files the account
    does not have are simply absent, and the README says what is there.
    """
    files: dict[str, bytes] = {}
    if paths.db.is_file():
        ledger = ledger_csv(paths.db, base)
        if ledger:
            files["ledger.csv"] = ledger
    for name, path in bundled(paths).items():
        if not path.is_file():
            continue
        data = path.read_bytes()
        files[name] = _public_prefs(data) if path == paths.prefs else data
    order = [n for n in _ABOUT if n in files] + sorted(set(files) - set(_ABOUT))
    files["README.txt"] = _readme(order, base)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["README.txt", *order]:
            archive.writestr(name, files[name])
    return buffer.getvalue()
