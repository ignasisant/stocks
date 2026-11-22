"""What each of a sector's funds did, in the reader's money.

The facts of a sector fund are the same for every reader (`analysis.
sector_funds`); its return is not. A euro reader and a dollar reader see the
same fund move by different amounts, and "since your book started" starts on
each reader's own first day. So this half is per account, computed on demand
and never stored, while the page's facts stay account-free.

The windows follow the rule every comparison in the app follows: the
book's own first day first (the span the card opens on), the last twelve
months beside it. A fund listed after the book started is read from its own
first close and says so (`opens`); a series that cannot be put into the
reader's currency has no number rather than one that is half exchange rate.
"""

from __future__ import annotations

import pandas as pd

from stocks import loaders, obs
from stocks.analysis import sector_funds
from stocks.cache import ttl_cache
from stocks.chat import today_sections
from stocks.portfolio.tax import prefs as tax_prefs
from stocks.views.evidence import perf


def _period(first) -> str:
    """The shortest download that reaches back to `first` and a year."""
    if first is None:
        return "2y"
    age = pd.Timestamp.today().normalize() - pd.Timestamp(first)
    if age <= pd.Timedelta(days=2 * 365 - 7):
        return "2y"
    return "6y" if age <= pd.Timedelta(days=6 * 365 - 7) else "max"


@ttl_cache(6 * 3600.0, max_entries=40)
def _closes(symbols: tuple[str, ...], period: str) -> dict[str, pd.Series]:
    """Adjusted (total-return) closes, shared by every reader: a fund's price
    is not personal."""
    from stocks.analysis.portfolio import load_closes

    return load_closes(list(symbols), period=period)


def _book_start(paths, base: str):
    hist, _twr, _missing = loaders.history(
        str(paths.db), loaders.db_mtime(str(paths.db)), base
    )
    return today_sections.book_start(hist)


def transfer_free(paths) -> bool:
    """The reader files in Spain, where a switch between two mutual funds (a
    traspaso) carries the gain over untaxed. Resolved like `/portfolio/tax`."""
    try:
        code, _ = tax_prefs.resolve(tax_prefs.load(paths.prefs))
    except Exception:  # noqa: BLE001 — unknown residence claims nothing
        return False
    return code == "ES"


def returns(sector: str, paths, base: str, *, own_book: bool) -> dict:
    """{since, returns: [{ticker, y1, since, opens}]} for `sector`'s vehicles.

    `own_book` False (a guest) skips the book: the demo's first day is not
    the reader's, so only the twelve months are given.
    """
    symbols = tuple(v.symbol for v in sector_funds.vehicles(sector))
    start = None
    if own_book and symbols:
        try:
            start = _book_start(paths, base)
        except Exception as exc:  # noqa: BLE001 — the twelve months still stand
            obs.warn("sector.funds_history_failed", error_type=type(exc).__name__)
    closes: dict = {}
    if symbols:
        try:
            closes = _closes(symbols, _period(start))
        except Exception as exc:  # noqa: BLE001 — a card with facts and no returns
            obs.warn(
                "sector.funds_closes_failed", sector=sector, error_type=type(exc).__name__
            )
    stored = loaders.sector_funds()
    rows = []
    for symbol in symbols:
        unit = (stored.get(symbol) or {}).get("currency")
        series, now_in = today_sections._in_base(closes.get(symbol), unit, base, closes)
        if series is None or now_in != base:
            rows.append({"ticker": symbol, "y1": None, "since": None, "opens": None})
            continue
        opens = today_sections._opens(series, start) if start is not None else None
        late = opens is not None and opens - start > pd.Timedelta(
            days=today_sections.OPEN_SLACK_DAYS
        )
        rows.append(
            {
                "ticker": symbol,
                "y1": perf(series).get("y1_pct"),
                "since": today_sections._since(series, opens)
                if opens is not None
                else None,
                "opens": opens.date().isoformat() if late else None,
            }
        )
    return {
        "since": start.date().isoformat() if start is not None else None,
        "returns": rows,
    }
