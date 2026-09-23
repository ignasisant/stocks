"""Cached domain calls — this package's answer to `web.portfolio_data`.

Same job, same cache keys, different runtime. The page loaders are wrapped in
`@st.cache_data`, which needs a script run to key against and so cannot cross
into an ASGI worker; these are wrapped in `api.cache.ttl_cache`.

The keys follow the pages' convention exactly — `(db path, ledger mtime, base
currency)`. `mtime` invalidates a book the moment an import rewrites the file
rather than when a timer expires, and `base` is in the key because money is
computed *in* the reporting currency (each leg at its own trade-date rate),
so two accounts on different currencies must never share an entry.

Nothing is reimplemented here: every function is a cache around a call into
`stocks.portfolio` / `stocks.analysis`. When a number needs changing, it
changes in the domain and both runtimes get it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stocks import identity, obs
from stocks.analysis import naive_dates
from stocks.analysis.history import price_history
from stocks.analysis.portfolio import (
    HELD_ACTIONS,
    book_history,
    load_closes,
    position_values_history,
    positions_frame,
    session_quotes,
)
from stocks.api.cache import ttl_cache
from stocks.portfolio import transfers
from stocks.portfolio.custody import Custody, by_position
from stocks.portfolio.ledger import all_transactions
from stocks.portfolio.positions import build

# Held prices move all day but a book's shape does not; these mirror the ttls
# the pages use for the same loads.
_LEDGER_TTL = 3600.0
_PRICES_TTL = 900.0
_QUOTES_TTL = 300.0


def db_mtime(db: str) -> float:
    """The ledger file's mtime, or 0.0 when it does not exist yet.

    Part of every cache key below, so a committed import invalidates exactly
    the entries that read the file it rewrote.
    """
    path = Path(db)
    return path.stat().st_mtime if path.exists() else 0.0


@ttl_cache(_LEDGER_TTL, max_entries=32)
def ledger_state(db: str, mtime: float, base: str = "EUR", matching: str = "fifo"):
    """Ledger + share-matching replay -> (transactions, positions, realized).

    `matching` is in the key as well as the arguments: FIFO and s.104 produce
    different realized parcels — and different basis left behind — from the
    very same trades.
    """
    txs = all_transactions(Path(db))
    positions, realized = (
        build(txs, base=base, matching=matching) if txs else ([], [])
    )
    return txs, positions, realized


@ttl_cache(_PRICES_TTL, max_entries=16)
def held_closes(db: str, mtime: float) -> dict[str, pd.Series]:
    """One bulk close download covering every name the book has ever held.

    Relabelled first (`transfers.relabel`): a book moved between brokers holds
    one position under two spellings, and downloading the other one prices
    nothing.
    """
    txs = transfers.relabel(all_transactions(Path(db)))
    held = [t for t in txs if t.action in HELD_ACTIONS]
    if not held:
        return {}
    tickers = sorted({t.ticker for t in held})
    span = (pd.Timestamp.today() - pd.Timestamp(min(t.date for t in held))).days
    return load_closes(tickers, period=f"{max(1, span // 30 + 1)}mo")


@ttl_cache(_PRICES_TTL, max_entries=32)
def positions_table(db: str, mtime: float, base: str = "EUR") -> pd.DataFrame:
    """Per-position frame in `base`: shares, cost, live value, unrealised P/L.

    Priced through `positions_frame`'s own `market_values` pass. A name it has
    no series for reads NaN in `value` rather than zero, which is what keeps
    `priced_totals` from dividing an intact book's whole basis by a fraction
    of its market value.
    """
    positions = ledger_state(db, mtime, base)[1]
    return positions_frame(positions, base=base)


@ttl_cache(_LEDGER_TTL, max_entries=16)
def history(db: str, mtime: float, base: str = "EUR"):
    """Full-span daily history: (injected-vs-value frame, daily TWR, unpriced).

    Shares the book's close download with `positions_table` rather than making
    one of its own.
    """
    return book_history(
        all_transactions(Path(db)), base=base, closes=held_closes(db, mtime)
    )


# How far back the fixed basket reaches. The movers card's longest window is a
# month, and three months is what `web.portfolio_data.basket_history` slices —
# the same frame, so the two front ends anchor on the same rows.
_BASKET_MONTHS = 3


@ttl_cache(_PRICES_TTL, max_entries=16)
def basket_values(db: str, mtime: float, base: str = "EUR") -> pd.DataFrame:
    """Daily `base` value per open position at *today's* quantities.

    The frame the day/week/month deltas are measured on, and NOT
    `history()`'s `value` column: that one is the book as it happened, so a
    deposit or an import inside the window lands in it and reads as a gain —
    a €12k book that took €38k on a Monday shows "+316% this week" when
    nothing moved. A basket held at today's shares cannot say that: every day
    carries the same quantities, so money moving in or out is invisible to it
    and only prices and rates move the line.

    Which also makes the question it answers a hypothetical one — what today's
    book would have done over the window, a name bought yesterday included,
    priced back across days nobody held it. That is the right question for
    "how is my portfolio doing" and the wrong one for "what did this account
    earn", which is `history()` and `/portfolio/performance`. A name with no
    price at one end of a window drops out there (`basket_change`) rather than
    being counted from zero.

    Values rather than closes, because the shares are in them: a book is
    judged in its reporting currency, so a position's move includes its FX
    move. Prices come off the book's shared download, sliced to the window —
    no request of its own.
    """
    positions = ledger_state(db, mtime, base)[1]
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(months=_BASKET_MONTHS)
    window = {}
    for ticker, series in held_closes(db, mtime).items():
        # Series arrive naive or stamped in the exchange's zone depending on
        # the market; `naive_dates` is where the app flattens that.
        tail = series[naive_dates(series.index) >= cutoff]
        if not tail.empty:
            window[ticker] = tail
    return position_values_history(
        positions, period=f"{_BASKET_MONTHS}mo", base=base, closes=window
    )


@ttl_cache(_QUOTES_TTL, max_entries=64)
def quotes(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Live snapshot per ticker in ONE request; unquotable names drop out.

    The full snapshot rather than the bare percentage, because `as_of` is what
    stops a Wednesday response from printing Monday's close as "today".
    """
    return session_quotes(list(tickers))


# ----------------------------------------------------------- one ticker's page
# Ranges and quotes move all day; a company's calendar does not. The ttls below
# mirror what the Ticker page uses for the same loads.
_HISTORY_TTL = 300.0
_EVENTS_TTL = 3600.0


@ttl_cache(_HISTORY_TTL, max_entries=64)
def price_bars(ticker: str, label: str) -> pd.DataFrame:
    """OHLCV plus indicators for one range label, shaped by `analysis.history`.

    Shared with the Ticker page down to the trimming and the indicator columns,
    so the two front ends cannot draw different bars for the same range.
    """
    return price_history(ticker, label)


@ttl_cache(_EVENTS_TTL, max_entries=64)
def earnings(ticker: str):
    """(all known earnings dates, reported results) — one yfinance pass.

    Never raises: Yahoo throttles shared cloud IPs hard, and a calendar is
    garnish on a price chart. An empty answer degrades the markers; an
    exception would take the whole response down with them.
    """
    from stocks.data.earnings import fetch_earnings

    try:
        return fetch_earnings(ticker)
    except Exception as exc:
        obs.warn("api.earnings_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return [], []


@ttl_cache(_PRICES_TTL, max_entries=32)
def spot_rates(ccys: tuple[str, ...], base: str = "EUR") -> dict[str, float]:
    """{currency: native->`base` spot} for the currencies a book trades in.

    The page's `web.portfolio_data.native_base_rates`, same ttl and same
    contract: every money figure here is computed *in* the reporting currency,
    so dividing one back by its rate is how a share price gets quoted in the
    currency its market quotes it in. Pairs whose lookup fails are absent —
    the caller prints nothing rather than a dollar figure under a euro sign.
    """
    from stocks.data.fx import spot

    out: dict[str, float] = {}
    for ccy in ccys:
        if str(ccy).upper() == base.upper():
            out[ccy] = 1.0
            continue
        with obs.swallow("fx.spot", ccy=ccy, base=base):
            out[ccy] = float(spot(ccy, base)[0])
    return out


@ttl_cache(_LEDGER_TTL, max_entries=32)
def native_positions(db: str, mtime: float):
    """Open positions carrying *native-currency* cost — identity FX, no network.

    What a per-ticker view needs: the share count and the average buy price in
    the currency the position actually trades in. Converting those to a
    reporting currency would price the whole book to answer a question about
    one name.
    """
    txs = all_transactions(Path(db))
    positions, _ = build(txs, to_base=lambda amount, ccy, day: amount)
    return {p.ticker: p for p in positions}


@ttl_cache(_LEDGER_TTL, max_entries=32)
def custody(db: str, mtime: float) -> dict[str, dict[str, Custody]]:
    """Open shares per (ticker, broker): which broker's account holds them.

    Identity FX like `native_positions` — the split is a share count, not a
    basis, so this stays off the network too.
    """
    return by_position(all_transactions(Path(db)), to_base=lambda a, c, d: a)


@ttl_cache(_EVENTS_TTL, max_entries=32)
def fundamentals(ticker: str):
    """One yfinance fundamentals pull: info, income statements, cash flow.

    Three sections of the page read it — the KPI grid, the financials charts
    and the moat score — and each used to be its own cached call. One pull,
    one cache entry, three derivations.
    """
    from stocks.data.fundamentals import fetch_fundamentals

    return fetch_fundamentals(ticker)


@ttl_cache(_EVENTS_TTL, max_entries=32)
def estimates(ticker: str):
    """Analyst price targets, EPS/revenue consensus and ratings.

    Degrades to an empty RawEstimates per field rather than raising, so a name
    with no coverage renders as "no consensus" instead of failing the request.
    """
    from stocks.data.estimates import fetch_estimates

    return fetch_estimates(ticker)


@ttl_cache(_EVENTS_TTL, max_entries=32)
def valuation(ticker: str) -> dict:
    """P/E reconstructed against its own history: {source, pe, stats, current}.

    `source` says which filing feed backed it — SEC EDGAR, FMP, or None when
    neither yields quarterly EPS. A client has to print that: a multiple with
    no provenance is a number somebody will act on.
    """
    from stocks.analysis.pe_history import pe_vs_history

    try:
        return pe_vs_history(ticker)
    except Exception as exc:
        obs.warn("api.pe_history_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return {"source": None, "pe": None, "stats": None, "current": None}


@ttl_cache(_EVENTS_TTL, max_entries=32)
def insiders(ticker: str):
    """Recent Form 4 lines, newest filing first; [] when the feed says nothing.

    US filers only through this path. The EU regulators publishing the same
    disclosure are `data.bafin`, which the route folds in separately.
    """
    from stocks.data.insiders import insider_transactions

    try:
        return insider_transactions(ticker)
    except Exception as exc:
        obs.warn("api.insiders_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return []


@ttl_cache(86400.0, max_entries=32)
def fund_profile(ticker: str):
    """What a fund is and what it holds, or None for an ordinary company.

    A day's ttl: an expense ratio and a holdings list change on the fund's
    schedule, not the market's.
    """
    from stocks.data.funds import fetch_profile

    try:
        return fetch_profile(ticker)
    except Exception as exc:
        obs.warn("api.fund_profile_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:300])
        return None


# ---------------------------------------------------------------- search tiers
# The page wraps these five in `st.cache_data`; the tiers themselves live in
# `stocks.search` and are handed whichever of the two a runtime owns. Every one
# swallows its exceptions: search degrading to the tiers that answered is the
# app's behaviour, and a dead Yahoo must not 500 a keystroke.

_SEARCH_TTL = 86400.0
_WORLD_TTL = 3600.0


@ttl_cache(_LEDGER_TTL, max_entries=32)
def held(db: str, mtime: float) -> tuple[str, ...]:
    """Tickers with an open position, so imported activity is searchable.

    Quantities need no FX, so the replay runs with an identity converter and
    stays offline — this is on the path of every keystroke.
    """
    try:
        positions, _ = build(all_transactions(Path(db)), to_base=lambda a, c, d: a)
        return tuple(p.ticker for p in positions)
    except Exception:
        return ()  # an empty or inconsistent ledger must never break search


@ttl_cache(_SEARCH_TTL, max_entries=256)
def sec_title(ticker: str) -> str | None:
    """Company name for a held-but-unlisted ticker, from the SEC map."""
    from stocks.data.edgar import title_for

    try:
        return title_for(ticker)
    except Exception:
        return None


@ttl_cache(_SEARCH_TTL, max_entries=128)
def sec_matches(query: str) -> list[tuple[str, str]]:
    """SEC ticker-map search. In-memory, but memoised so typing doesn't rescan."""
    from stocks.data.edgar import search_companies

    try:
        return search_companies(query, limit=6)
    except Exception:
        return []


@ttl_cache(_WORLD_TTL, max_entries=128)
def world_matches(query: str) -> list[tuple[str, str, str]]:
    """Worldwide symbol search (Yahoo) — the only search tier that is a network
    round-trip, hence an hour per query and a hard cap inside `search_symbols`.
    """
    from stocks.data.symbols import search_symbols

    try:
        return search_symbols(query, limit=6)
    except Exception:
        return []


@ttl_cache(_SEARCH_TTL, max_entries=128)
def coin_matches(query: str) -> list[tuple[str, str]]:
    """Coin pairs for a query — a local table, cached only to skip the rescan."""
    from stocks.data.crypto import search_crypto

    try:
        return search_crypto(query)
    except Exception:
        return []


@ttl_cache(_SEARCH_TTL, max_entries=128)
def fund_matches(query: str) -> list[tuple[str, str]]:
    """Fund catalog matches — the tier that still answers while Yahoo throttles."""
    from stocks.data.funds import search_funds

    try:
        return search_funds(query)
    except Exception:
        return []


@ttl_cache(86400.0, max_entries=128)
def related(ticker: str) -> tuple[str, ...]:
    """Symbols Yahoo considers related — the comps picker's suggestions.

    A day's ttl and empty on any failure: a suggestion nobody asked for must
    never be the thing that fails the page.
    """
    from stocks.data.related import related_tickers

    try:
        return tuple(related_tickers(ticker))
    except Exception:
        return ()


# ------------------------------------------------------------------- identity
# What a ticker is called and what it looks like. All three reach the network
# on a cold path and none of them changes within a day.

_IDENTITY_TTL = 86400.0


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def display_symbol(ticker: str) -> str:
    """The Yahoo symbol a stored broker label resolves to."""
    return identity.yahoo_symbol(ticker)


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def company_name(ticker: str, watchlist: str) -> str | None:
    """Human name for a ticker.

    `watchlist` is in the key, not just the arguments: a custom name one
    account set on its own list must never render for another.
    """
    return identity.company_name(ticker, watchlist)


@ttl_cache(_IDENTITY_TTL, max_entries=512)
def logo(ticker: str) -> str | None:
    """Same-origin logo URL, absolute.

    Absolute rather than the app's relative form because the React document is
    served from `/ticker`, not from the Streamlit mount — a relative path would
    resolve against whatever route the reader happens to be on.
    """
    return identity.logo_src(ticker, prefix="/" + identity.STATIC_PREFIX)


@ttl_cache(_IDENTITY_TTL, max_entries=64)
def brand_logo(broker: str) -> str | None:
    """Same-origin logo for a broker brand — the custody marks in the header.

    Mirrored into the same directory ticker logos are, for the same reason: the
    brand's CDN never sees a request per viewer telling it who banks where. The
    external URL is the fallback for an image this host could not fetch, and
    None is the honest answer for a key that declares no domain at all — a
    hand-entered row has no brand, and the client draws a name pill instead.
    """
    from stocks.data.logo import brand_logo_url, mirror_brand
    from stocks.portfolio import platforms

    domain = platforms.broker_domain(broker)
    if not domain:
        return None
    if name := mirror_brand(broker, domain, identity.STATIC_LOGO_DIR):
        return "/" + identity.STATIC_PREFIX + name
    return brand_logo_url(domain)


@ttl_cache(_QUOTES_TTL * 12, max_entries=64)
def crypto_info(ticker: str) -> dict:
    """Snapshot info for a coin pair — market cap, volume, supply, 52w range."""
    from stocks.data.fetch import info as quote_info

    try:
        return quote_info(ticker)
    except Exception as exc:
        obs.warn(
            "api.crypto_info_failed",
            ticker=ticker,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        return {}


# --------------------------------------------------------------- the book's cost
# What the Portfolio page's Fees, Dividends and Risk tabs each need, with the
# ttls those tabs already use. Same rule as everything above: the cache lives
# here, the arithmetic lives in the domain.


@ttl_cache(86400.0, max_entries=8)
def trade_bars(db: str, mtime: float) -> dict[str, pd.DataFrame]:
    """Daily UNADJUSTED OHLC per traded ticker, spanning the whole ledger.

    Feeds the spread estimate: execution prices are as-traded, so the reference
    bars must not be dividend-adjusted (`auto_adjust=False` — splits are
    replayed from the ledger in `portfolio.fees`). Historical bars never change,
    hence the day-long ttl; `mtime` refetches after an import, which can widen
    the span or add a name.
    """
    from stocks.data.fetch import fetch_many

    txs = ledger_state(db, mtime)[0]  # bars are native-currency: base is moot
    trades = [t for t in transfers.relabel(txs) if t.action in HELD_ACTIONS]
    if not trades:
        return {}
    tickers = sorted({t.ticker for t in trades})
    span = (pd.Timestamp.today() - pd.Timestamp(min(t.date for t in trades))).days
    return fetch_many(
        tickers, period=f"{max(1, span // 30 + 1)}mo", auto_adjust=False
    )


@ttl_cache(21600.0, max_entries=8)
def dividend_estimates(db: str, mtime: float, base: str = "EUR") -> tuple:
    """(estimated years, forward income, forward totals in `base`, unrecorded).

    What the book was entitled to, from Yahoo's per-share history and the
    ledger's own share timeline — the half no statement can be asked for, since
    a dividend is owed to whoever held the share the day before it went ex
    whether or not the import carried a row for it. Six-hour ttl: a payment goes
    ex once a quarter and this is one request per name ever held.

    Raises `YFRateLimitError` when Yahoo is in cooldown and nothing came back,
    so a throttled minute is never cached as "this book pays nothing" — the
    route turns it into a 503 with a `Retry-After` like every other fetch here.
    """
    from yfinance.exceptions import YFRateLimitError

    from stocks.data.dividends import histories
    from stocks.data.fetch import throttle_remaining
    from stocks.portfolio import dividends as div

    txs = ledger_state(db, mtime, base)[0]
    tickers = sorted(
        {t.ticker for t in transfers.relabel(txs) if t.action in HELD_ACTIONS}
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


@ttl_cache(_LEDGER_TTL, max_entries=16)
def basket_report(db: str, mtime: float, base: str, period: str):
    """Today's holdings backtested at fixed `base` weights over `period`.

    A risk profile of what is held *now* — not a performance figure, which is
    what `history` returns. The weights are rebuilt on one currency's footing
    after the fetch, because `analyze` weights in native prices and a book that
    is mostly USD with some EUR is measured wrong by that.

    So are the returns, and for the same reason. `analyze` reads them off
    native closes, which measured a book whose *weights* were in the reporting
    currency against moves that were not: the volatility, the drawdown, the
    betas and the whole correlation matrix came out with the currency leg
    missing — for a EUR reader in US names, the seven-odd annual points of
    EUR/USD simply were not in the answer. Per-position values in `base` are
    the same prices times the daily rate, and their ratio is the move that
    reader actually lived. The benchmarks are converted with them
    (`rebase_returns`), because a beta with the dollar on one side only is not
    a beta.
    """
    from stocks.analysis.portfolio import (
        analyze,
        holdings_from_positions,
        rebase_report,
    )

    positions = ledger_state(db, mtime, base)[1]
    if not positions:
        return None
    report = analyze(period=period, holdings=holdings_from_positions(positions))
    return rebase_report(report, positions, base, period)


@ttl_cache(_LEDGER_TTL, max_entries=1)
def sector_scans() -> dict:
    """The nightly sector scan, restored from the bucket if it is not on disk.

    Market-wide, not per-account: every reader gets the same cohorts, so this
    is a shared file and the cache takes no account in its key. The ttl is the
    ledger's rather than a price one because the scan is rebuilt once a night —
    an hour-old cohort is the same cohort.
    """
    from stocks.analysis.sectors import load_scan

    return load_scan()


@ttl_cache(21600.0, max_entries=16)
def earnings_calendar(tickers: tuple[str, ...]):
    """(upcoming events, past results) for a set of names, in ONE parallel pass.

    Keyed on the ticker tuple rather than a watchlist path, because that is what
    actually invalidates it: two accounts tracking the same names share the
    answer, and editing a watchlist changes the key by itself. Six hours — a
    company reports once a quarter, and the date moves rarely.
    """
    from stocks.config import Holding
    from stocks.data.earnings import calendar_events

    if not tickers:
        return [], []
    return calendar_events([Holding(ticker=t) for t in tickers])


# ------------------------------------------------------------------ the pulse
# The market-regime screen. Two years of history because the trailing-year
# percentile needs a full year before it scores anything and the 200-session
# trend average needs most of another.

_PULSE_HISTORY = "2y"


@ttl_cache(_PRICES_TTL, max_entries=2)
def pulse_closes() -> dict[str, pd.Series]:
    """Close series for every symbol the pulse reads, in ONE bulk request."""
    from stocks.analysis.sentiment import all_tickers

    return load_closes(all_tickers(), period=_PULSE_HISTORY)


@ttl_cache(21600.0, max_entries=1)
def pulse_rates() -> dict[str, pd.Series]:
    """The FRED series the composite's credit input needs.

    Only the high-yield spread, not the page's whole rates block: this is what
    `sentiment.pulse` takes, and pulling the rest here would spend a slow
    request on rows nothing in the API reads yet.
    """
    from stocks.data import macro

    return macro.fred_many(["BAMLH0A0HYM2"])


@ttl_cache(_PRICES_TTL, max_entries=2)
def market_pulse():
    """The composite, built from the two loads above.

    Its own entry rather than a recompute per request: the arithmetic walks two
    years of eight series and the answer is the same for every reader.
    """
    from stocks.analysis.sentiment import pulse

    return pulse(pulse_closes(), hy_spread=pulse_rates().get("BAMLH0A0HYM2"))


@ttl_cache(86400.0, max_entries=1)
def benchmark_sectors() -> dict[str, float]:
    """SPY's own sector split — what a book's sector bet is measured against.

    Yahoo's fund look-through, so the buckets are already spelled the way a
    stock's `info["sector"]` spells them and join onto a book's allocation with
    no mapping layer in between. A day-long ttl: an index fund's sector split
    does not move between requests.
    """
    from stocks.data.funds import sector_weights

    return sector_weights("SPY")


@ttl_cache(_PRICES_TTL, max_entries=32)
def watchlist_closes(tickers: tuple[str, ...]) -> dict[str, pd.Series]:
    """A year of closes for a set of names, in ONE bulk download.

    Keyed on the ticker tuple rather than an account, so two accounts tracking
    the same names share it. A year because that is what a 52-week extreme
    needs; anything shorter cannot answer the question at all.

    Prices as they printed (`adjusted=False`), which is the difference between
    a 52-week high and a 52-week total return. An adjusted series walks every
    close before an ex-date down by the dividend, so the high of a payer sits
    under the price somebody actually paid for it — and the name reads as
    sitting at its high while it is a dividend's worth below it. This is the
    only reader of the download, so nothing else pays for the distinction.
    """
    if not tickers:
        return {}
    return load_closes(list(tickers), period="1y", adjusted=False)


def file_mtime(path: Path) -> float:
    """Any account file's mtime, or 0.0 when it does not exist yet.

    The sibling of `db_mtime` for the JSON files beside the ledger: part of a
    cache key so a rewrite invalidates exactly the entry that read it.
    """
    return path.stat().st_mtime if path.exists() else 0.0


@ttl_cache(_LEDGER_TTL, max_entries=32)
def stored_action(path: str, mtime: float) -> dict:
    """The stored daily card as a raw dict ({} when there is none).

    Unreadable reads as "nothing stored", which is what sends the dashboard
    down the regenerate path rather than to an error.
    """
    import json

    try:
        out = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}


@ttl_cache(21600.0, max_entries=1)
def pulse_rate_rows() -> dict[str, pd.Series]:
    """Every FRED series the rates block draws, plus the conditions index.

    Separate from `pulse_rates`, which pulls only the one series the composite
    needs: this is a slower call and a client that never opens the rates tab
    should not pay for it.
    """
    from stocks.analysis.sentiment import RATE_ROWS
    from stocks.data import macro

    return macro.fred_many([*RATE_ROWS, "NFCI"])


@ttl_cache(21600.0, max_entries=1)
def inflation() -> pd.DataFrame:
    """Annual inflation per area — the slowest source on the page."""
    from stocks.data import macro

    return macro.inflation()


# Enable Banking's own bank list. Reference data: identical for every account,
# and the API rate-limits it like everything else — an hour is what the page
# already held it for.
_ASPSPS_TTL = 3600.0


@ttl_cache(_ASPSPS_TTL, max_entries=32)
def aspsps(country: str) -> list[dict]:
    """The banks that can be connected in one country."""
    from stocks.bank import enablebanking

    return enablebanking.aspsps(country)
