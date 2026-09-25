"""The Home page's scopes and frames, shared by the routes that draw it.

`web/app_pages/home.py` is one script, so the watchlist rows, the 52-week scan
and the daily card all read the same local variables: one set of held names,
one year of closes, one enriched positions frame. Over HTTP those are three
routes (`/home/closes`, `/extremes`, `/daily`), and the moment each of them
decides its own scope they disagree — which is exactly how `/extremes` came to
scan the whole watchlist, crypto pairs included, while missing a held name the
reader never starred. So the decisions live here, once, and every route asks.

Two of them are worth saying out loud:

* **A guest holds nothing.** The Streamlit page reads the ledger as
  `DB if is_logged_in() else None`: the demo book a guest can open on Portfolio
  is not *their* book, and Home does not pretend it is. The guest's Home is the
  shared watchlist and nothing else.
* **One year-of-closes download per page.** The watchlist rows and the 52-week
  scan both read `closes_tuple()`, the watchlist plus every held non-crypto
  name, so a held name missing from the list rides along in the same bulk
  request instead of costing a second one — `home.py`'s `_wl_tickers`, and the
  reason that page stopped getting itself rate-limited.
"""

from __future__ import annotations

import pandas as pd

from stocks import accounts
from stocks.analysis.portfolio import market_live, value_weights
from stocks.api import loaders
from stocks.config import Holding, load_watchlist
from stocks.data.crypto import is_crypto

# How close to an extreme still counts as being at it. A stock 1.4% off its
# 52-week high is at its high in every sense a reader cares about.
EDGE_BAND = 0.02


def is_guest(paths) -> bool:
    """True for the shared anonymous directory — see the module docstring."""
    return paths.root == accounts.GUEST_DIR


def held(paths) -> set[str]:
    """Tickers with an open position in this account's own book.

    Offline (`loaders.held` replays with an identity converter), so asking costs
    no FX and no prices. Empty for a guest, whose "book" is the demo one.
    """
    if is_guest(paths):
        return set()
    db = str(paths.db)
    return set(loaders.held(db, loaders.db_mtime(db)))


def holdings(paths) -> list[Holding]:
    """The watchlist entries, or none when the file is missing or unreadable.

    A broken watchlist must not take the whole Home down with it; the page's
    own empty state is the honest answer to a list nobody can read.
    """
    try:
        return load_watchlist(paths.watchlist)
    except Exception:  # noqa: BLE001 — the page degrades, it does not fail
        return []


def closes_tuple(entries: list[Holding], owned: set[str]) -> tuple[str, ...]:
    """The one set of names the page downloads a year of closes for.

    The watchlist (crypto included — its rows still show a last close) plus the
    held names that are not crypto. Sorted, because it is a cache key.
    """
    return tuple(
        sorted({h.ticker for h in entries} | {t for t in owned if not is_crypto(t)})
    )


def extremes_scope(entries: list[Holding], owned: set[str]) -> tuple[str, ...]:
    """Held ∪ favourites, crypto excluded — `home.py`'s `_xt_tickers`.

    Not the whole watchlist: a name somebody added once and never starred is
    not one they want a card about, and the scan stays small. Crypto has no
    meaningful 52-week story here (a pair that doubled in a month is at its
    high every other week) so it is skipped.
    """
    favourites = {h.ticker for h in entries if h.favorite}
    return tuple(sorted(t for t in owned | favourites if not is_crypto(t)))


def year_closes(tickers: tuple[str, ...]) -> dict[str, list[float]]:
    """A year of daily closes per name, oldest first, NaNs dropped.

    Off `loaders.watchlist_closes` — as-printed prices, which is what a 52-week
    high means — keyed on the tuple so the rows, the scan and the daily card
    share one entry.
    """
    if not tickers:
        return {}
    out: dict[str, list[float]] = {}
    for ticker, series in loaders.watchlist_closes(tickers).items():
        values = [float(v) for v in pd.Series(series).dropna()]
        if values:
            out[str(ticker)] = values
    return out


def scan_extremes(
    tickers: tuple[str, ...], year: dict[str, list[float]]
) -> list[tuple[str, float, str, float | None]]:
    """(ticker, last close, "high"/"low", distance) within EDGE_BAND of an edge.

    The tuple shape is `home.py`'s `_year_extremes`, on purpose: it is what
    `chat.daily.build_facts` and `chat.signals` read, so the daily card is fed
    the very rows the extremes card shows. Distance is None at or beyond the
    extreme — a different fact from being 0% away.
    """
    out: list[tuple[str, float, str, float | None]] = []
    for ticker in tickers:
        closes = year.get(ticker) or []
        if len(closes) < 2:
            continue
        last, high, low = closes[-1], max(closes), min(closes)
        if high and last >= high * (1 - EDGE_BAND):
            out.append((ticker, last, "high", None if last >= high else last / high - 1))
        elif low and last <= low * (1 + EDGE_BAND):
            out.append((ticker, last, "low", None if last <= low else last / low - 1))
    return out


def last_closes(
    tickers: list[str], year: dict[str, list[float]]
) -> dict[str, tuple[float | None, float | None, str | None]]:
    """{ticker: (last close, day %, as_of)} with `home.py`'s off-session rule.

    Close-to-close from the daily bars, except for names whose own exchange is
    not in a regular session right now: there the newest bar can be a flat
    premarket 0%, so the move is re-read from one quote burst — the live
    pre/after-hours move while there is one, the last completed session once
    those windows shut. Only the percentage is overridden; the price column is
    still the *close*, which is what its header says.
    """
    off = tuple(t for t in tickers if not market_live(t))
    quotes: dict[str, dict] = {}
    if off:
        try:
            quotes = loaders.quotes(off)
        except Exception:  # noqa: BLE001 — a throttled burst keeps the bars
            quotes = {}
    out: dict[str, tuple[float | None, float | None, str | None]] = {}
    for ticker in tickers:
        closes = year.get(ticker) or []
        last = closes[-1] if closes else None
        day = closes[-1] / closes[-2] - 1 if len(closes) >= 2 and closes[-2] else None
        quote = quotes.get(ticker) or {}
        as_of = None
        if quote.get("pct") is not None:
            day = float(quote["pct"])
            as_of = quote.get("as_of")
        out[ticker] = (last, day, as_of)
    return out


def enriched(db: str, mtime: float, base: str) -> pd.DataFrame:
    """`web.portfolio_data.enriched_positions`, over this API's own loaders.

    The positions frame plus weight / day / day_pct / day_asof, sorted by
    weight — the frame the daily card's facts and signals are written from.
    Same recipe as the page's: the day move is the basket's last two bars
    (FX included), re-read from the quote burst for names whose exchange is
    shut, and dated with the session it belongs to so the card never calls a
    last-completed-session move "today".

    A copy, always: `positions_table` is a cached frame shared by every reader
    of this book, and adding columns to it in place would leak this route's
    arithmetic into the next request's positions.
    """
    tbl = loaders.positions_table(db, mtime, base).copy()
    if tbl.empty:
        return tbl
    tbl["weight"] = value_weights(tbl)
    vals = loaders.basket_values(db, mtime, base).dropna(how="all")
    tbl["day_asof"] = None
    if len(vals) >= 2:
        last, prev = vals.iloc[-1], vals.iloc[-2]
        tbl["day"] = (last - prev).reindex(tbl.index)
        tbl["day_pct"] = (last / prev - 1).reindex(tbl.index)
        stamp = str(pd.Timestamp(vals.index[-1]).date())
        tbl["day_asof"] = pd.Series(stamp, index=tbl.index).where(tbl["day_pct"].notna())
    else:
        tbl["day"] = tbl["day_pct"] = float("nan")
    off = tuple(str(t) for t in tbl.index if not market_live(str(t)))
    if off:
        try:
            quotes = loaders.quotes(off)
        except Exception:  # noqa: BLE001 — the bars stand when the burst fails
            quotes = {}
        for ticker, quote in quotes.items():
            if ticker not in tbl.index or quote.get("pct") is None:
                continue
            pct = float(quote["pct"])
            tbl.at[ticker, "day_pct"] = pct
            tbl.at[ticker, "day_asof"] = quote.get("as_of")
            value = tbl.at[ticker, "value"]
            tbl.at[ticker, "day"] = (
                value * pct / (1 + pct) if pd.notna(value) and pct != -1 else float("nan")
            )
    return tbl.sort_values("weight", ascending=False, na_position="last")
