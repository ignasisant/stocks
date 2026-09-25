"""Shared cached loaders for ledger-derived data (Home + Portfolio pages).

st.cache_data entries key on the function's module + name: defining the same
loader in two page modules would double every fetch and price burst. Both
pages import these instead. Every function is keyed by (db, mtime, base) —
`db` isolates concurrent users, `mtime` (widgets.db_mtime) invalidates exactly
when the ledger file changes, and `base` is the reporting currency: money is
computed *in* it (each leg at its own trade-date rate), not converted after the
fact, so two users on different currencies must not share an entry. Callers
pass `auth.reporting_currency()`, or a tax jurisdiction's own currency for the
tax replay.

Every loader is `show_spinner=False`: the call site owns the loading state and
paints a `stocks.web.skeletons` placeholder shaped like the block it is about
to fill, so a cold cache holds the layout instead of collapsing it behind a
spinner.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from stocks import obs
from stocks.analysis import naive_dates
from stocks.analysis.portfolio import (
    HELD_ACTIONS,
    book_history,
    market_live,
    position_values_history,
    positions_frame,
    session_quote,
    session_quotes,
    value_weights,
)
from stocks.portfolio import fees, transfers
from stocks.portfolio.custody import Custody, by_position
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.positions import build

# What counts as held — buys, sells and transfer legs alike. Aliased from the
# analysis package rather than restated, so the loaders here and the shared
# `book_history` they call can never disagree about which rows get priced.
_HELD = HELD_ACTIONS


@st.cache_data(show_spinner=False, max_entries=32)
def ledger_state(
    db: str, mtime: float, base: str = "EUR", matching: str = "fifo"
):
    """Ledger + share-matching replay -> (transactions, positions, sales).

    Lots are valued in `base` at each transaction date's rate — a cost basis is
    a per-transaction conversion, so a USD book cannot be recovered by
    converting an EUR one at the end. `matching` is the jurisdiction's
    share-identification rule: the app's analytics use FIFO, a UK tax replay
    uses the s.104 pool, and the two produce different realized parcels from
    the same trades — hence both in the cache key. No ttl: `mtime` keys the
    cache, so this stays hot until the next import instead of expiring."""
    txs = all_transactions(Path(db))
    positions, realized = (
        build(txs, base=base, matching=matching) if txs else ([], [])
    )
    return txs, positions, realized


@st.cache_data(show_spinner=False, max_entries=32)
def custody_map(
    db: str, mtime: float, base: str = "EUR"
) -> dict[str, dict[str, Custody]]:
    """ticker -> broker -> open shares/cost: which broker's account each
    holding sits in (stocks.portfolio.custody).

    Ledger-only, so no ttl — `mtime` keys it like ledger_state and it stays
    hot until the next import.
    """
    return by_position(ledger_state(db, mtime, base)[0], base=base)


@st.cache_data(ttl=300, show_spinner=False)
def positions_table(db: str, mtime: float, base: str = "EUR") -> pd.DataFrame:
    """Live-priced positions table in `base`, cached so Home, plain reruns and
    the Realized & tax tab reuse it instead of pricing the book again.

    Values are the last row of `basket_history` — the same download that feeds
    the day/week/month chips and the per-ticker day change. Reusing it means
    the page makes one price download rather than two, and the market-value
    tile is the last point of the chart printed beside it by construction
    instead of by coincidence. Prices therefore age on the basket's ttl (which
    the day-change cells already followed), and names outside their session
    still get the fresher quote override in `enriched_positions`.

    Only when the basket comes back empty — no price series at all — does the
    frame fall through to pricing itself, where a wholesale throttle raises
    rather than valuing the book at zero (analysis.portfolio.market_values).
    """
    positions = ledger_state(db, mtime, base)[1]
    vals = basket_history(db, mtime, base)
    latest = (
        {t: float(v) for t, v in vals.iloc[-1].items() if pd.notna(v)}
        if not vals.empty
        else None
    )
    return positions_frame(positions, base=base, values=latest)


def ledger_period(first: str) -> str:
    """The yfinance period that covers a ledger whose first trade is `first`.

    One rule for every loader that prices the book across its whole life, so
    they all ask for the same span and share the download below.
    """
    span = (date.today() - date.fromisoformat(first)).days
    return "2y" if span <= 700 else "5y" if span <= 1780 else "max"


@st.cache_data(ttl=900, show_spinner=False, max_entries=16)
def held_closes(db: str, mtime: float) -> dict[str, pd.Series]:
    """Daily closes for every ticker the ledger ever held, ONE bulk download.

    The price side of the whole book, shared: the 3-month basket behind the
    chips and the day-change cells, the full-span value-vs-injected history,
    the Pulse page's book tab and the ticker page's position weights each used
    to download the same names over their own window — four requests per
    symbol per cold page for one fact. Fetched once over the ledger's span
    (`ledger_period`) and sliced by the readers; a symbol's request costs the
    same whatever the period, so the long window is free.

    Keyed by (db, mtime) like `ledger_state`: a new import may add a name or
    push the first trade back. The ttl is what ages intraday prices; the
    readers that cache their derived frames longer (an hour for the TWR
    history) pick up a fresh download when they next rebuild.
    """
    from stocks.analysis import portfolio as _analysis

    # The raw rows, not `ledger_state`: only tickers and dates are needed, and
    # the replay there is keyed by reporting currency — reading it with the
    # default would replay a USD account's book a second time in EUR.
    # `relabel` first: the replay gives a security that two brokers spell
    # differently ONE label (stocks.portfolio.transfers), and the value frames
    # are keyed on it. Downloading the other spelling prices nothing — a
    # DEGIRO→IBKR book asks for ISINs and holds symbols, and every transferred
    # position reads n/a with the whole book's cost still in the tile.
    txs = transfers.relabel(all_transactions(Path(db)))
    held = [t for t in txs if t.action in _HELD]
    if not held:
        return {}
    tickers = sorted({t.ticker for t in held})
    period = ledger_period(min(t.date for t in held))
    return _analysis.load_closes(tickers, period=period)


def _window(closes: dict[str, pd.Series], months: int) -> dict[str, pd.Series]:
    """The last `months` of each series — a `period="<n>mo"` download, sliced."""
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(months=months)
    out: dict[str, pd.Series] = {}
    for t, s in closes.items():
        # Series arrive naive or stamped in the exchange's zone depending on
        # the market; `naive_dates` is where the app flattens that.
        tail = s[naive_dates(s.index) >= cutoff]
        if not tail.empty:
            out[t] = tail
    return out


@st.cache_data(ttl=900, show_spinner=False)
def basket_history(db: str, mtime: float, base: str = "EUR") -> pd.DataFrame:
    """Fixed-basket daily values in `base` (3mo of closes × daily ECB FX at
    today's quantities) — feeds the day/week/month chips and per-ticker day
    change, so a position's move includes its FX move.

    Prices are the last three months of `held_closes`, not a download of
    their own."""
    positions = ledger_state(db, mtime, base)[1]
    return position_values_history(
        positions, period="3mo", base=base,
        closes=_window(held_closes(db, mtime), 3),
    )


@st.cache_data(ttl=300, show_spinner=False)
def last_session_quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Cached quote snapshot per ticker (one burst): price, day %, `as_of`.

    Only fetched for names outside their regular session — the daily close-to-
    close basket can collapse to ~0% there (a stale/flat premarket bar), so the
    day-change cells read from this instead: the live pre/after-hours move while
    Yahoo quotes one, the last completed session once those windows shut. Keyed
    by the ticker tuple; ttl refreshes it around the next open."""
    return session_quotes(list(tickers))


def last_session_moves(tickers: tuple[str, ...]) -> dict[str, float]:
    """Just the percentages from `last_session_quotes` — same cached burst.

    For cells that only render a number. Anything that writes the number into
    prose (the daily card) reads the quotes, because `as_of` is what keeps a
    last-completed-session move from being printed as "today"."""
    return {t: q["pct"] for t, q in last_session_quotes(tickers).items()}


@st.cache_data(ttl=120, show_spinner=False)
def last_session_quote(ticker: str) -> dict | None:
    """Cached one-ticker quote snapshot: price, day % move, pre/post label.

    The ticker page's price hero reads this off-session — the daily closes miss
    the extended-hours move entirely, so a -13% premarket gap would render as
    yesterday's session on both the price and the delta. Short ttl: premarket
    prices move fast and this is a single request."""
    return session_quote(ticker)


def enriched_positions(db: str, mtime: float, base: str = "EUR") -> pd.DataFrame:
    """positions_table plus weight / day-change columns, sorted by weight.

    weight = share of live market value; day/day_pct come from the
    basket history's last two closes (includes the FX move). Cheap frame math
    over two cached loads — not cached itself.
    """
    tbl = positions_table(db, mtime, base)
    if tbl.empty:
        return tbl
    tbl["weight"] = value_weights(tbl)
    vals = basket_history(db, mtime, base)
    tbl["day_asof"] = None
    if len(vals) >= 2:
        last, prev = vals.iloc[-1], vals.iloc[-2]
        tbl["day"] = (last - prev).reindex(tbl.index)
        tbl["day_pct"] = (last / prev - 1).reindex(tbl.index)
        # Which session those two closes are — the basket's last bar, and only
        # for rows that actually have a value there (a name whose latest daily
        # bar is still empty is priced off the two before it).
        stamp = getattr(vals.index[-1], "date", lambda: vals.index[-1])()
        tbl["day_asof"] = pd.Series(
            str(stamp), index=tbl.index
        ).where(tbl["day_pct"].notna())
    else:
        tbl["day"] = tbl["day_pct"] = float("nan")
    # Outside the regular session the close-to-close basket can be a flat
    # premarket 0%. Override those rows with the quote move (native): the live
    # pre/after-hours move, else the last completed session; day re-derives
    # from the EUR value. Crypto is 24/7 so it never overrides.
    off = tuple(t for t in tbl.index if not market_live(t))
    if off:
        for t, quote in last_session_quotes(off).items():
            if t not in tbl.index:
                continue
            pct = quote["pct"]
            tbl.at[t, "day_pct"] = pct
            # The override moves the row to the quote's session, which is the
            # last *completed* one off-hours — carried so the daily card can
            # date the figure instead of calling it today's.
            tbl.at[t, "day_asof"] = quote.get("as_of")
            val = tbl.at[t, "value"]
            tbl.at[t, "day"] = (
                val * pct / (1 + pct)
                if pd.notna(val) and pct != -1
                else float("nan")
            )
    return tbl.sort_values("weight", ascending=False, na_position="last")


@st.cache_data(ttl=3600, show_spinner=False)
def ledger_history(fingerprint: tuple, db: str, base: str = "EUR"):
    """Full-span daily history from the ledger: injected vs value, TWR, missing.

    One fetch shared by Home's glance chart and the Portfolio page's Positions
    and Allocation & risk tabs. TWR = daily time-weighted returns of the book
    (flow-adjusted), so deposits/withdrawals don't read as performance and it's
    comparable against benchmarks. `fingerprint` is the cache key the callers
    build as (len(txs), txs[-1].date, date.today()) — new transactions and day
    rollovers invalidate it; ttl refreshes intraday prices.
    """
    # The recipe itself is `analysis.portfolio.book_history` — shared with the
    # HTTP API, which computes the same numbers with no session to cache
    # against. What stays here is the caching and the shared price download:
    # the same names over the same span, hot already whenever the Home glance
    # or the Pulse page ran first.
    return book_history(
        all_transactions(Path(db)), base=base, closes=held_closes(db, db_mtime(db))
    )


@st.cache_data(ttl=86400, show_spinner=False, max_entries=8)
def trade_bars(db: str, mtime: float) -> dict[str, pd.DataFrame]:
    """Daily UNADJUSTED OHLC per traded ticker, spanning the whole ledger.

    Feeds the Fees tab's spread estimate: execution prices are as-traded, so
    the reference bars must not be dividend-adjusted (auto_adjust=False —
    splits are replayed from the ledger in portfolio.fees). Historical bars
    never change, hence the day-long ttl; `mtime` refetches after an import
    (new tickers / older first trade may widen the span)."""
    from stocks.data.fetch import fetch_many

    txs = ledger_state(db, mtime)[0]  # bars are native-currency: base is moot
    trades = [t for t in transfers.relabel(txs) if t.action in _HELD]
    if not trades:
        return {}
    tickers = sorted({t.ticker for t in trades})
    period = ledger_period(min(t.date for t in trades))
    bars = fetch_many(tickers, period=period, auto_adjust=False)
    # An alias can price a ticker on another venue (Revolut's dollar ASML ->
    # ASML.AS in euros); the spread converts when the frames say so.
    return fees.stamp_listing_currency(bars, fees.listing_currencies(list(bars)))


@st.cache_data(ttl=3600, show_spinner=False)
def eur_spot(quote: str, base: str = "EUR") -> float | None:
    """Latest `base`→quote spot rate, for a threshold or a one-off conversion.

    Money the pages *report* is computed in the reporting currency per date, so
    this is for the few places a single live rate is the right tool: a foreign-
    asset reporting threshold, or a figure already summed in another base."""
    try:
        from stocks.data.fx import rate_on

        return float(rate_on(date.today(), base, quote))
    except Exception:
        return None  # FX down → caller keeps the figure it has


@st.cache_data(ttl=900, show_spinner=False)
def native_base_rates(ccys: tuple[str, ...], base: str = "EUR") -> dict[str, float]:
    """{currency: native->`base` spot} for the currencies a book trades in.

    positions_frame multiplies each native price by this rate, so dividing a
    reported figure back by it recovers the quote-currency number a ticker is
    actually priced in. Pairs whose lookup fails are absent (caller falls back
    to "n/a" rather than printing a converted figure under a foreign
    symbol)."""
    from stocks.data.fx import spot

    out: dict[str, float] = {}
    for c in ccys:
        with obs.swallow("fx.spot", ccy=c, base=base):
            out[c] = float(spot(c, base)[0])
    return out


@st.cache_data(ttl=900, show_spinner=False)
def watchlist_closes(tickers: tuple[str, ...]) -> dict[str, list[float]]:
    """A year of daily closes per ticker, oldest first.

    One bulk download (data.fetch.fetch_many) for the whole watchlist, cached
    15 min so the ticker list renders without hammering the network on every
    rerun. The cache key is the ticker tuple, so every reader shares one
    download.

    A year rather than the five days the rows need, because Home also scans
    for 52-week extremes: those used to be a second bulk download over the
    same symbols, and two request sets over one watchlist is how a page gets
    itself rate-limited. `recent_closes` slices the tail off this; the
    extremes scan reads the whole series.
    """
    from stocks.data.fetch import fetch_many

    out: dict[str, list[float]] = {}
    for t, df in fetch_many(list(tickers), period="1y").items():
        close = df["Close"].dropna() if "Close" in df else None
        if close is not None and len(close):
            out[t] = [float(v) for v in close]
    return out


def year_closes(
    tickers: tuple[str, ...], db: str | None = None, mtime: float = 0.0
) -> dict[str, list[float]]:
    """A year of daily closes per ticker, oldest first, from the downloads the
    page already pays for.

    Names the ledger holds are sliced out of `held_closes` (the book's own
    download, hot after the glance card); only the rest go through
    `watchlist_closes`. On a book whose positions are also on the watchlist —
    the common case — that halves the symbols the Home page asks Yahoo for.
    Guests (`db` None) read the watchlist download alone.
    """
    out: dict[str, list[float]] = {}
    if db:
        wanted = set(tickers)
        for t, s in _window(held_closes(db, mtime), 12).items():
            if t in wanted:
                close = s.dropna()
                if len(close):
                    out[t] = [float(v) for v in close]
    rest = tuple(t for t in tickers if t not in out)
    if rest:
        out.update(watchlist_closes(rest))
    return out


def recent_closes(tickers: tuple[str, ...]) -> dict[str, list[float]]:
    """Last two daily closes per ticker (prev, last) — the day % change.

    A slice of `watchlist_closes`, not a fetch of its own — callers wanting to
    drop the download behind it clear `watchlist_closes`.
    """
    return {t: c[-2:] for t, c in watchlist_closes(tickers).items()}


def db_mtime(db: str) -> float:
    """Ledger file mtime — a cache key that changes only when the book does,
    so ledger-derived caches stay hot until the next import instead of
    expiring on a timer. 0.0 when the file doesn't exist yet."""
    try:
        return Path(db).stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False, max_entries=64)
def held_tickers(db: str, mtime: float) -> list[str]:
    """Tickers with an open position in the ledger — reachable in search even
    when they're not on the watchlist, so imported activity is browsable.
    `db` is the session user's ledger path; it keys the cache so concurrent
    users never see each other's positions. `mtime` (db_mtime) invalidates
    the entry exactly when the ledger file changes."""
    try:
        from stocks.portfolio.ledger import all_transactions
        from stocks.portfolio.positions import build

        # Identity converter: quantities don't need FX, keeps this offline.
        positions, _ = build(all_transactions(Path(db)), to_base=lambda a, c, d: a)
        return [p.ticker for p in positions]
    except Exception:
        return []  # empty/inconsistent ledger must never break search


@st.cache_data(ttl=21600, show_spinner=False, max_entries=8)
def dividend_estimates(db: str, mtime: float, base: str = "EUR") -> tuple:
    """(estimated years, forward income, forward totals in `base`, unrecorded).

    What the book was entitled to, from Yahoo's per-share history and the
    ledger's own share timeline — the half no statement can be asked for, since
    a dividend is owed to whoever held the share the day before it went ex
    whether or not the import carried a row for it. Six-hour ttl: a payment
    goes ex once a quarter and this is one request per name ever held.

    Raises YFRateLimitError when Yahoo is in cooldown and nothing came back, so
    a throttled minute is never cached as "this book pays nothing" — the call
    site toasts it the way every other fetch here degrades.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import histories
    from stocks.data.fetch import throttle_remaining
    from stocks.portfolio import dividends as div

    txs = ledger_state(db, mtime, base)[0]
    tickers = sorted(
        {t.ticker for t in transfers.relabel(txs) if t.action in _HELD}
    )
    history = histories(tickers)
    if not history and (tickers and throttle_remaining()):
        raise YFRateLimitError
    payments = div.estimate_payments(txs, history)
    estimated = div.estimate_by_year(payments, base=base)
    forward = div.forward_income(txs, history)
    totals = div.forward_totals(forward, base=base)
    unrecorded = div.unrecorded_by_year(div.by_year(txs, base=base), estimated)
    return estimated, forward, totals, unrecorded
