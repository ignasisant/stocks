"""Market frames the daily card reads, cached across sessions.

The dashboard's daily action used to be built entirely from the reader's own
ledger, which is why every card it wrote was about one holding: the numbers it
had were per-position numbers. To say anything about the market the reader's
book sits in — the index's own trend, which sectors are leading it, what the
dollar did — the card needs prices for symbols nobody holds, and those are the
one input the Home page does not already have in hand.

Two properties make that affordable:

  - **The same for everybody.** An index close is not personal data, so one
    download serves every account in the process. `st.cache_data` is keyed on
    module and function, not on the session, which is exactly the sharing this
    wants — and it is the reason these loaders live in a module of their own
    rather than as private functions of the page that first needed them.
  - **Narrow.** The Pulso page downloads some fifty symbols for its own
    tables; the card needs thirteen. Yahoo throttles datacenter IPs and the
    card runs on every Home load, so it asks for the smallest set that answers
    its four questions and nothing else.

Every function here is best-effort by contract: the caller treats an empty
return as "no market signals today" and builds the card it always built.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from stocks.analysis import sentiment as sm
from stocks.analysis.portfolio import allocation, load_closes, load_meta
from stocks.chat.signals import MONTH_SESSIONS
from stocks.data.funds import sector_weights

# SPY for the index and as the sector ETFs' benchmark, the eleven sector ETFs
# for rotation and trend breadth, EUR/USD for the currency line. Sorted so the
# tuple is stable — it is part of a cache key.
CARD_TICKERS: tuple[str, ...] = tuple(
    sorted({"SPY", "EURUSD=X", *sm.SECTOR_ETFS.values()})
)
# Two years, because trend breadth is read against a 200-session average and a
# one-year window leaves the first half of it undefined.
CARD_PERIOD = "2y"


@st.cache_data(ttl=900, show_spinner=False)
def card_closes() -> dict[str, pd.Series]:
    """Close series for the card's symbols, in ONE bulk request.

    The same 15-minute ttl the Pulso page uses: this is a card about right now,
    and inside a quarter of an hour the index has not changed its mind.
    """
    return load_closes(list(CARD_TICKERS), period=CARD_PERIOD)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def benchmark_sectors() -> dict[str, float]:
    """SPY's sector split — what the reader's sector bet is measured against.

    Yahoo's own fund look-through, so the buckets are already spelled the way a
    stock's `info["sector"]` spells them and join straight onto a book's
    allocation with no mapping layer in between.
    """
    return sector_weights("SPY")


@st.cache_data(ttl=24 * 3600, show_spinner=False, max_entries=32)
def _meta(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Sector/country/currency per ticker. Cached hard: these four fields do
    not change, and `load_meta` is the one call here that can reach the network
    once per symbol rather than once per request."""
    return load_meta(list(tickers))


def book_sectors(weights) -> pd.Series:
    """A book's weights summed by sector, with funds looked through.

    Uncached on purpose, unlike the metadata it reads: weights move with every
    price tick, so a cache keyed on them would miss every time and hold a new
    entry for each miss. The arithmetic is a dict walk; the expensive half is
    `_meta`, which is keyed on the tickers alone and therefore hits.
    """
    if weights is None or not len(weights):
        return pd.Series(dtype=float)
    tickers = tuple(sorted(str(t) for t in weights.index))
    return allocation(
        {str(t): float(w) for t, w in weights.items()}, _meta(tickers), "sector"
    )


def index_month_base(closes: dict[str, pd.Series], base: str = "EUR") -> float:
    """SPY's month, in the reader's own currency.

    The book's month comes off a basket valued in `base`; the index's comes off
    a series quoted in dollars. Subtracting one from the other without this
    conversion reports the currency's move as skill, in whichever direction it
    happened to go — which is the single easiest way for this card to tell a
    reader something false about their own performance.
    """
    index = closes.get("SPY")
    if index is None or index.dropna().empty:
        return float("nan")
    series = index.dropna()
    if base != "EUR":
        # Only the euro pair is downloaded; any other base reads the index in
        # its own currency rather than inventing a cross rate.
        return sm.pct_over(series, MONTH_SESSIONS)
    pair = closes.get("EURUSD=X")
    if pair is None or pair.dropna().empty:
        return float("nan")
    # EURUSD=X is dollars per euro, so dividing a dollar price by it gives the
    # price in euros. Both sides are reindexed onto the index's own sessions:
    # FX quotes on days the New York market is closed, and an unaligned divide
    # would compare Monday's price against Sunday's rate.
    rate = pair.dropna().reindex(series.index, method="ffill")
    in_base = (series / rate).dropna()
    return sm.pct_over(in_base, MONTH_SESSIONS)
