"""Validate parsed transactions before they touch the ledger.

The Revolut parser (revolut.py / revolut_pdf.py) does per-row shape checks;
this module does everything that needs context beyond one row:

* dates — parseable ISO, not in the future, not implausibly old
* tickers — checked against the local EDGAR map (data/edgar_tickers.json),
  with an optional live lookup fallback for non-US symbols; unknown tickers
  are a *warning*, not an error, because Revolut lists EU stocks under bare
  local symbols (DHER, NA9…) that no US source knows
* oversells — a sell larger than the position held at that date (replayed
  FIFO-style over prior ledger + the new batch, splits applied)
* duplicates — rows the ledger already holds, or that the batch repeats
  within itself: the classic re-import-of-an-overlapping-export accident,
  and the LLM-mapped statement that read the same page twice. Both an exact
  match and a same-trade-different-price match are flagged, and `Validation`
  offers the batch with them left out (`fresh`) next to the batch that keeps
  them (`importable`) — the caller chooses
* splits — Revolut reports shares *added* by a split, not the ratio
  positions.py needs; the ratio is derived from the quantity held the day
  of the split and snapped to a plausible ratio (6:1, 3:2, …)

Errors quarantine a row (not importable); warnings flag it but let it
through. Nothing here writes to the ledger.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from stocks.config import DATA_DIR, WATCHLIST_FILE, load_watchlist, ticker_aliases
from stocks.portfolio import transfers
from stocks.portfolio.ledger import DB_PATH, Transaction
from stocks.portfolio.statement import ParseResult

EDGAR_TICKER_CACHE = DATA_DIR / "edgar_tickers.json"

# Bare US-style symbol or one with an exchange suffix (RMS.PA, BRK-B), or an
# ISIN (DEGIRO exports carry no ticker; rows import under the ISIN until the
# user maps it in watchlist.yaml `aliases:`).
_TICKER_RE = re.compile(
    r"^([A-Z0-9]{1,6}([.\-][A-Z0-9]{1,4})?|[A-Z]{2}[A-Z0-9]{9}[0-9])$"
)

# Earliest plausible trade date — old enough for IBKR/DEGIRO history, recent
# enough to catch corrupt dates (a mangled year like 0203 or 1023).
_MIN_DATE = "1990-01-01"

# Snap targets for derived split ratios: forward N:1 and the common 3:2.
_SPLIT_RATIOS = [1.5] + [float(n) for n in range(2, 51)]

# Warning fields meaning "this row is already imported". Two strengths: an
# exact match, and a trade whose date/ticker/action/quantity match but whose
# price doesn't — what a re-read of the same PDF produces when the mapping
# lands on a different price column the second time around.
DUPLICATE = "duplicate"
NEAR_DUPLICATE = "near_duplicate"
_DUPE_FIELDS = (DUPLICATE, NEAR_DUPLICATE)

# Actions whose quantity is a share count, so (date, ticker, action, quantity)
# already names one trade. Dividends, fees and splits carry no share count and
# two of them on one day for one ticker are ordinary, so they get the exact
# check only.
_QUANTIFIED = ("buy", "sell")

# lookup(ticker) -> True (exists), False (doesn't), None (couldn't check)
Lookup = Callable[[str], bool | None]

# splits(ticker) -> [(YYYY-MM-DD, ratio), …] forward splits Yahoo knows about,
# [] when it knows none and when it can't be asked (see data.fetch.splits).
SplitLookup = Callable[[str], list[tuple[str, float]]]


# Issue text in English, keyed the way the web catalogs key it. The CLI
# prints `Issue.message` (this table); the web app translates `key`/`params`
# through locales/<lang>/validate.json, whose keys mirror this dict exactly —
# tests/test_i18n_parity.py fails if the two drift apart.
#
# Numbers arrive pre-formatted: a catalog string carrying a `{q:.4f}` spec
# would have to repeat that spec in every language to stay in step.
ISSUE_TEXT = {
    "validate.bad_date": "unparseable date {date}",
    "validate.future_date": "date {date} is in the future",
    "validate.ancient_date": "date {date} predates plausible trading history",
    "validate.missing_ticker": "missing ticker",
    "validate.malformed_ticker": "malformed ticker {ticker}",
    "validate.unknown_ticker": (
        "{ticker} not in {sources} — EU or OTC broker code? map it to a Yahoo "
        "symbol under `aliases:` in watchlist.yaml or prices won't resolve"
    ),
    "validate.zero_price_sell": (
        "sold at 0 — worthless disposal/delisting? this realizes the full "
        "loss of the position"
    ),
    "validate.duplicate": (
        "identical row already in ledger — re-importing an overlapping export "
        "doubles the position"
    ),
    "validate.near_duplicate": (
        "a {action} of {quantity} {ticker} on {date} is already in the ledger "
        "at a different price — the same trade read twice?"
    ),
    "validate.oversell": (
        "sell of {quantity} exceeds {held} held on {date} — missing earlier "
        "buys or a split?"
    ),
    "validate.split_added": (
        "{ratio}:1 split on {date}, from Yahoo's corporate actions — the "
        "statement doesn't carry it, and the sells after it don't add up "
        "without it"
    ),
}


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    field: str
    key: str  # catalog key, e.g. "validate.oversell"
    params: dict = field(default_factory=dict)

    @property
    def message(self) -> str:
        """English rendering — what the CLI prints and what tests read. The
        web app renders the same issue through its own catalog instead."""
        return ISSUE_TEXT.get(self.key, self.key).format(**self.params)


@dataclass
class Checked:
    """One parsed transaction plus everything validation found on it."""

    tx: Transaction
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def duplicate(self) -> bool:
        """Whether this row repeats one already imported (exactly, or bar
        its price)."""
        return any(i.field in _DUPE_FIELDS for i in self.issues)


@dataclass
class Validation:
    checked: list[Checked]

    @property
    def importable(self) -> list[Transaction]:
        """Clean + warned rows; errors stay quarantined."""
        return [c.tx for c in self.checked if not c.errors]

    @property
    def rejected(self) -> list[Checked]:
        return [c for c in self.checked if c.errors]

    @property
    def flagged(self) -> list[Checked]:
        return [c for c in self.checked if c.warnings and not c.errors]

    @property
    def duplicates(self) -> list[Checked]:
        """Importable rows the ledger (or an earlier row of this batch) has."""
        return [c for c in self.checked if not c.errors and c.duplicate]

    @property
    def fresh(self) -> list[Transaction]:
        """`importable` minus the duplicates — what a second upload of an
        overlapping export should actually add to the ledger."""
        return [c.tx for c in self.checked if not c.errors and not c.duplicate]

    @property
    def summary(self) -> str:
        return (
            f"{len(self.importable)} importable "
            f"({len(self.flagged)} with warnings), {len(self.rejected)} rejected"
        )


def known_tickers(
    watchlist_path: Path = WATCHLIST_FILE, db_path: Path = DB_PATH
) -> set[str]:
    """Symbols we can vouch for offline: EDGAR map + watchlist + aliases + ledger.

    Watchlist and ledger are per-user in the web app — pass that user's paths.
    Aliases stay global (root watchlist.yaml): broker-code mappings are
    reference data, not personal data.
    """
    known: set[str] = set()
    if EDGAR_TICKER_CACHE.exists():
        table = json.loads(EDGAR_TICKER_CACHE.read_text())
        known.update(row["ticker"].upper() for row in table.values())
    known.update(h.ticker.upper() for h in load_watchlist(watchlist_path))
    # Both halves of the map: the broker code the ledger stores, and the Yahoo
    # symbol it points at — a statement that already prints the mapped symbol
    # (or an importer that resolved a name to it) is not an unknown ticker.
    known.update(ticker_aliases())
    known.update(s.upper() for s in ticker_aliases().values())
    from stocks.portfolio.ledger import all_transactions

    known.update(t.ticker for t in all_transactions(db_path))
    return known


def validate(
    result: ParseResult,
    prior: list[Transaction],
    *,
    known: set[str] | None = None,
    lookup: Lookup | None = None,
    splits: SplitLookup | None = None,
    today: date | None = None,
) -> Validation:
    """Check a parsed batch against itself and the existing ledger.

    Mutates `result.skipped` only by resolving split rows into transactions
    (they move from skipped to checked). `prior` is the current ledger.

    `splits` is consulted only when a sell overshoots the position: most
    statements print trades and nothing else, so a share count that grew 20x
    on one day in 2022 is a corporate action the file never mentions, not a
    missing buy. Asked for the ticker that actually overshot, the split it
    names joins the batch as a row of its own — the ledger needs it too, or
    positions.py replays the same shortfall after the commit.
    """
    known = known_tickers() if known is None else known
    today = today or date.today()

    txs = list(result.transactions) + resolve_splits(result, prior)
    seen = {_dupe_key(t) for t in prior}
    similar = {_loose_key(t) for t in prior if _quantified(t)}
    checked = [Checked(tx=t) for t in txs]

    for c in checked:
        _check_date(c, today)
        _check_ticker(c, known, lookup)
        if c.tx.action == "sell" and c.tx.price == 0:
            c.issues.append(Issue("warning", "price", "validate.zero_price_sell"))
        _check_duplicate(c, seen, similar)
    _rescue_fills(checked, prior)
    _check_oversells(checked, prior, splits)
    return Validation(checked=checked)


# ------------------------------------------------------------------ split rows
def resolve_splits(result: ParseResult, prior: list[Transaction]) -> list[Transaction]:
    """Turn skipped STOCK SPLIT rows into split transactions when the ratio
    is derivable: ratio = (held + shares_added) / held at the split date.
    Resolved entries are removed from `result.skipped`; ambiguous ones stay
    there with the reason updated."""
    splits = [
        s
        for s in result.skipped
        if "SPLIT" in s.get("type", "").upper() and s.get("ticker")
    ]
    if not splits:
        return []

    resolved: list[Transaction] = []
    base = list(prior) + list(result.transactions)
    for s in sorted(splits, key=lambda s: s.get("date", "")):
        day = _iso_date(s.get("date", ""))
        added = float(s.get("quantity") or 0)
        held = _held_at(base + resolved, s["ticker"], day)
        ratio = _snap_ratio((held + added) / held) if held > 1e-9 and added > 0 else None
        if ratio is None:
            s["reason"] = (
                "stock split — ratio underivable from held quantity "
                f"({held:.4f} held, {added:.4f} added); add manually"
            )
            continue
        result.skipped.remove(s)
        resolved.append(
            Transaction(
                date=day,
                ticker=s["ticker"],
                action="split",
                quantity=ratio,
                currency=s.get("currency") or "USD",
                note=f"revolut split {ratio:g}:1 (derived from +{added:g} shares)",
            )
        )
    return resolved


def _snap_ratio(raw: float) -> float | None:
    for target in _SPLIT_RATIOS:
        if abs(raw - target) / target < 0.005:
            return target
    return None


def _held_at(txs: list[Transaction], ticker: str, day: str) -> float:
    """Share count held in `ticker` just before end of `day` (splits applied)."""
    qty = 0.0
    ordered = sorted(
        (t for t in txs if t.ticker == ticker.upper() and t.date <= day),
        key=lambda t: (t.date, t.id or 0),
    )
    for t in ordered:
        if t.action == "buy":
            qty += t.quantity
        elif t.action == "sell":
            qty -= t.quantity
        elif t.action == "split" and t.quantity > 0:
            qty *= t.quantity
    return qty


# ------------------------------------------------------------------ single-tx checks
def _check_date(c: Checked, today: date) -> None:
    d = _iso_date(c.tx.date)
    try:
        parsed = date.fromisoformat(d)
    except ValueError:
        c.issues.append(
            Issue("error", "date", "validate.bad_date", {"date": repr(c.tx.date)})
        )
        return
    if parsed > today:
        c.issues.append(Issue("error", "date", "validate.future_date", {"date": d}))
    elif d < _MIN_DATE:
        c.issues.append(
            Issue("error", "date", "validate.ancient_date", {"date": d})
        )


def _check_ticker(c: Checked, known: set[str], lookup: Lookup | None) -> None:
    t = c.tx.ticker
    if not t:
        c.issues.append(Issue("error", "ticker", "validate.missing_ticker"))
        return
    if not _TICKER_RE.match(t):
        c.issues.append(
            Issue("error", "ticker", "validate.malformed_ticker", {"ticker": repr(t)})
        )
        return
    if t in known:
        return
    found = lookup(t) if lookup else None
    if found:
        known.add(t)  # don't re-look-up the same symbol within a batch
        return
    sources = "EDGAR/watchlist/aliases" + (
        "/yfinance" if lookup and found is False else ""
    )
    c.issues.append(
        Issue(
            "warning",
            "ticker",
            "validate.unknown_ticker",
            {"ticker": t, "sources": sources},
        )
    )


def _check_duplicate(c: Checked, seen: set, similar: set) -> None:
    """Flag a row the ledger — or an earlier row of the same batch — already has.

    Both sets grow as the batch is walked, so a statement that lists the same
    movement twice flags its own repeat and not only its overlap with the
    ledger. That is the common shape of an LLM-mapped PDF: the page is read
    again and the trade comes back a second time, sometimes at a slightly
    different price, which is what the loose key is for.
    """
    key = _dupe_key(c.tx)
    if key in seen:
        c.issues.append(Issue("warning", DUPLICATE, "validate.duplicate"))
    elif _quantified(c.tx) and _loose_key(c.tx) in similar:
        c.issues.append(
            Issue(
                "warning",
                NEAR_DUPLICATE,
                "validate.near_duplicate",
                {
                    "action": c.tx.action,
                    "quantity": f"{c.tx.quantity:g}",
                    "ticker": c.tx.ticker,
                    "date": c.tx.date,
                },
            )
        )
    seen.add(key)
    if _quantified(c.tx):
        similar.add(_loose_key(c.tx))


def _rescue_fills(checked: list[Checked], prior: list[Transaction]) -> None:
    """Hand back a row dropped as a duplicate that the book cannot do without.

    One order filled in parts on a single day — two 1-share buys a minute
    apart at 248.6450 and 248.4450 — is indistinguishable from a page read
    twice at a mis-mapped price, so the duplicate check flags the second fill
    and `fresh` would drop it. Arithmetic is the arbiter: replay what is
    actually about to be committed, and any flagged row whose ticker comes up
    short was a real fill, so its duplicate warning is withdrawn. A genuine
    repeat is never restored by this — dropping it leaves the book closing
    exactly as it did before.

    Without this the shortfall is silent: the row vanishes at commit time and
    the ledger only fails later, when positions.py replays the sale it can no
    longer cover.
    """
    spare = [c for c in checked if not c.errors and c.duplicate]
    # Near-duplicates first: a row that matched on everything *but* its price
    # is the likelier of the two tiers to be a separate fill.
    spare.sort(key=lambda c: 0 if _near_duplicate(c) else 1)
    while spare:
        short = _replay(checked, prior)
        if not short:
            return
        tickers = {c.tx.ticker for c, _ in short}
        fill = next((c for c in spare if c.tx.ticker in tickers), None)
        if fill is None:
            return  # the shortfall is elsewhere — a real oversell
        spare.remove(fill)
        fill.issues = [i for i in fill.issues if i.field not in _DUPE_FIELDS]


def _near_duplicate(c: Checked) -> bool:
    return any(i.field == NEAR_DUPLICATE for i in c.issues)


# ------------------------------------------------------------------ cross-row checks
def _check_oversells(
    checked: list[Checked],
    prior: list[Transaction],
    splits: SplitLookup | None = None,
) -> None:
    """Mark every sell that overshoots the position it is selling from.

    Two replays when a shortfall turns up and a split lookup is available:
    the first names the tickers whose arithmetic doesn't close, the second
    checks it again with whatever corporate splits Yahoo knows about those
    tickers added to the batch. A statement that prints trades only (a bank
    PDF, most CSV exports) is the common case, and there the missing 20:1 is
    the whole shortfall — see `_market_splits`.
    """
    short = _replay(checked, prior)
    if short and splits is not None:
        added = _market_splits(short, checked, prior, splits)
        if added:
            checked.extend(added)
            short = _replay(checked, prior)
    for c, q in short:
        c.issues.append(
            Issue(
                "error",
                "quantity",
                "validate.oversell",
                {
                    "quantity": f"{c.tx.quantity:g}",
                    "held": f"{q:.4f}",
                    "date": c.tx.date,
                },
            )
        )


def _replay(
    checked: list[Checked], prior: list[Transaction]
) -> list[tuple[Checked, float]]:
    """Replay quantities per ticker over prior + new rows in date order.

    Returns (row, held) for every batch sell larger than the position at that
    point — nothing is mutated, so the caller can replay again after adding
    rows.
    """
    events: list[tuple[str, int, Transaction, Checked | None]] = [
        (t.date, t.id or 0, t, None) for t in prior
    ]
    # Batch rows have no id yet; a large sort key keeps them after ledger rows
    # on the same date, matching how positions.py will replay them post-commit.
    events += [(c.tx.date, 10**9 + i, c.tx, c) for i, c in enumerate(checked)]

    # Same rule positions.build replays under (stocks.portfolio.transfers): a
    # transfer out that has its arrival somewhere in the book moved the shares
    # rather than disposing of them, so neither leg changes what is held and
    # only an arrival nothing accounts for adds shares.
    arriving = transfers.unmatched_arrivals([e[2] for e in events])
    held: dict[str, float] = defaultdict(float)
    short: list[tuple[Checked, float]] = []
    for _, _, tx, c in sorted(events, key=lambda e: (e[0], e[1])):
        # Neither a quarantined row nor one dropped as a duplicate reaches the
        # ledger, so neither may prop up a sale here (Validation.fresh).
        if c and (c.errors or c.duplicate):
            continue
        q = held[tx.ticker]
        if tx.action == "buy":
            held[tx.ticker] = q + tx.quantity
        elif tx.action == "sell":
            if tx.quantity - q > 1e-6 and c is not None:
                short.append((c, q))
                continue
            held[tx.ticker] = q - tx.quantity
        elif tx.action == transfers.TRANSFER_IN:
            opens = min(tx.quantity, arriving.get(tx.ticker, 0.0))
            arriving[tx.ticker] = arriving.get(tx.ticker, 0.0) - opens
            held[tx.ticker] = q + opens
        elif tx.action == "split" and tx.quantity > 0:
            held[tx.ticker] = q * tx.quantity
    return short


def _market_splits(
    short: list[tuple[Checked, float]],
    checked: list[Checked],
    prior: list[Transaction],
    splits: SplitLookup,
) -> list[Checked]:
    """Split rows the shortfall tickers need, from Yahoo's corporate actions.

    Only splits dated inside the window the book already covers for that
    ticker — from its first row (ledger or batch) to the sell that overshot —
    are taken: a split that predates the first buy changed nothing the user
    holds, and one after the last sell can't be what made it overshoot. Rows
    the ledger or the batch already carries for that day are left alone, so
    re-importing an overlapping export doesn't stack two 20:1s.

    Reverse splits are skipped: they shrink a position, so they can never be
    the reason a sell came up short.
    """
    have = {(t.date, t.ticker) for t in prior if t.action == "split"}
    have |= {(c.tx.date, c.tx.ticker) for c in checked if c.tx.action == "split"}
    rows: list[Checked] = []
    for ticker in sorted({c.tx.ticker for c, _ in short}):
        mine = [t for t in prior if t.ticker == ticker]
        mine += [c.tx for c in checked if c.tx.ticker == ticker]
        first = min(t.date for t in mine)
        last = max(c.tx.date for c, _ in short if c.tx.ticker == ticker)
        try:
            events = splits(ticker) or []
        except Exception:  # a lookup that can't answer leaves the error standing
            continue
        currency = next((t.currency for t in mine if t.currency), "USD")
        for raw_day, raw_ratio in events:
            day, ratio = _iso_date(str(raw_day)), float(raw_ratio)
            if ratio <= 1 or not (first <= day <= last) or (day, ticker) in have:
                continue
            rows.append(
                Checked(
                    tx=Transaction(
                        date=day,
                        ticker=ticker,
                        action="split",
                        quantity=ratio,
                        currency=currency,
                        note=f"{ratio:g}:1 split (Yahoo corporate action)",
                    ),
                    issues=[
                        Issue(
                            "warning",
                            "split",
                            "validate.split_added",
                            {"ratio": f"{ratio:g}", "date": day},
                        )
                    ],
                )
            )
    return rows


def _dupe_key(t: Transaction) -> tuple:
    return (t.date, t.ticker, t.action, round(t.quantity, 6), round(t.price, 4))


def _loose_key(t: Transaction) -> tuple:
    """_dupe_key without the price — the same trade however it was priced."""
    return (t.date, t.ticker, t.action, round(t.quantity, 6))


def _quantified(t: Transaction) -> bool:
    return t.action in _QUANTIFIED and t.quantity > 0


def _iso_date(value: str) -> str:
    return value.split("T", 1)[0].split(" ", 1)[0]
