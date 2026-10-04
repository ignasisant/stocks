"""The two Home reads and one write that no other route already answers.

`/market/quotes` is a live snapshot, and the Home watchlist is not: its column
says *last close*, and its day % is close-to-close — re-read from the quote
burst only for names whose own exchange is shut, where the newest daily bar can
be a flat premarket 0%. Printing a live premarket price under a "last close"
header is the kind of small untruth this page exists not to tell. So the rows
get their own route, reading the page's one year-of-closes download
(`api/home.py`).

The market strip (`/home/market`) is the Pulse compressed to one card: its
composite and a dozen of the series it already downloads, read over the day,
the week and the month. No fetch of its own — a Home that opened the Pulse's
caches warms them for the Pulse, and the other way round.

And the refresh. The button used to ask again, which answers from the same TTL
caches it meant to get past. `POST /home/refresh` is that button's server half.
"""

from __future__ import annotations

import threading
import time

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

from stocks.analysis import sentiment as sm
from stocks.analysis.portfolio import market_active
from stocks.api import briefing, home, loaders
from stocks.api.deps import Account, Writer
from stocks.api.jsonsafe import num as _num
from stocks.api.routes.pulse import _reason
from stocks.api.schemas import Breadth, MarketGlance, MarketTile

router = APIRouter(tags=["home"])

# The shortest gap between two cache drops. The caches are process-wide — a
# price download is shared by every account tracking the same names, which is
# the point of them — so a button anybody can press is a button that could keep
# the whole deployment asking Yahoo, and Yahoo throttles datacenter IPs. Inside
# this window a press is still answered, it just does not drop anything twice.
REFRESH_COOLDOWN_S = 30.0

# Never, rather than zero: `time.monotonic()` can itself be under the cooldown
# on a container that booted seconds ago.
_last_refresh = float("-inf")
_refresh_lock = threading.Lock()


# The strip, in reading order: what equities did, how scared the market is, what
# money costs, then the dollar, metals, energy and crypto. (i18n slug, symbol,
# group, welcome). Every symbol is one `sentiment.all_tickers()` already pulls,
# so the strip never widens the Pulse's download — the test pins that.
MARKET_TILES: tuple[tuple[str, str, str, int], ...] = (
    ("sp500", "^GSPC", "equity", 1),
    ("nasdaq", "^IXIC", "equity", 1),
    ("stoxx50", "^STOXX50E", "equity", 1),
    ("ibex", "^IBEX", "equity", 1),
    ("em", "EEM", "equity", 1),
    ("vix", "^VIX", "risk", -1),
    ("eurusd", "EURUSD=X", "fx", 0),
    ("gold", "GC=F", "commodity", 0),
    ("oil", "CL=F", "commodity", 0),
    ("btc", "BTC-USD", "crypto", 1),
)
# The one rate on the strip, from FRED rather than Yahoo — the Pulse's rates
# block reads it from the same cache. Placed after the VIX.
MARKET_RATE = ("us10y", "DGS10", "rates", -1)
# The three horizons a returning reader asks about: since yesterday, this week,
# this month. In sessions, as everywhere on the Pulse.
MARKET_HORIZONS = {"day": 1, "week": 5, "month": 21}
# Enough of the composite's path for the week and month deltas the card quotes.
MARKET_HISTORY = 30
# Indices above their 200-session average — the Pulse's own breadth window.
MARKET_BREADTH_WINDOW = 200


def _as_of(series: pd.Series) -> str:
    return str(pd.Timestamp(series.index[-1]).date())


def _price_tile(key: str, symbol: str, group: str, welcome: int, series) -> MarketTile:
    clean = series.dropna()
    tile = MarketTile(
        key=key,
        symbol=symbol,
        group=group,
        unit="percent",
        value=_num(clean.iloc[-1]),
        changes={k: float(v) for k, v in sm.pct_changes(clean, MARKET_HORIZONS).items()},
        welcome=welcome,
        state=sm.trend_state(clean),
        as_of=_as_of(clean),
    )
    if group == "risk":
        # A VIX of 18 means nothing without its year: the percentile is what
        # says "calm" or "scared", and the card labels it.
        tile.percentile = _num(sm.percentile_now(clean))
    return tile


def _rate_tile(series) -> MarketTile | None:
    key, symbol, group, welcome = MARKET_RATE
    if series is None or series.dropna().empty:
        return None
    clean = series.dropna()
    return MarketTile(
        key=key,
        symbol=symbol,
        group=group,
        # Basis points, not a percent of a percentage — the Pulse's own rule.
        unit="basis_points",
        value=_num(clean.iloc[-1]),
        changes={
            k: float(v) * 100 for k, v in sm.changes(clean, MARKET_HORIZONS).items()
        },
        welcome=welcome,
        state=sm.trend_state(clean),
        linkable=False,
        as_of=_as_of(clean),
    )


class CloseRow(BaseModel):
    ticker: str
    close: float | None = Field(
        default=None, description="Last daily close, in the name's own currency."
    )
    pct: float | None = Field(
        default=None,
        description=(
            "Day move as a fraction: close-to-close, or — for a name whose "
            "exchange is shut — the quote's pre/after-hours or last-session move."
        ),
    )
    as_of: str | None = Field(
        default=None,
        description="The session `pct` is from, when it came off a quote.",
    )
    active: bool = Field(
        description=(
            "Whether the name has a live quote now (regular session, or US "
            "pre/after-hours). False greys the day figure: it is real, but it "
            "is not moving."
        )
    )


class Closes(BaseModel):
    rows: list[CloseRow] = Field(default_factory=list)


class Refreshed(BaseModel):
    cleared: bool = Field(
        description=(
            "Whether this press dropped the caches. False inside the cooldown "
            "after somebody else's press — the prices are already that fresh."
        )
    )


@router.get("/home/closes", response_model=Closes, summary="Watchlist closes")
def closes(account: Account) -> Closes:
    """Last close and day % for every watchlist name.

    One row per watchlist entry, in list order. A name the download missed
    still gets its row, with null figures, so the group keeps its shape and the
    cell says "n/a" instead of the name vanishing.
    """
    entries = home.holdings(account)
    if not entries:
        return Closes()
    tickers = list(dict.fromkeys(h.ticker for h in entries))
    try:
        year = home.year_closes(
            home.closes_tuple(entries, home.held(account)), *home.book(account)
        )
    except Exception:  # noqa: BLE001 — a throttled burst is n/a cells, not a 500
        year = {}
    moves = home.last_closes(tickers, year)
    return Closes(
        rows=[
            CloseRow(
                ticker=ticker,
                close=moves[ticker][0],
                pct=moves[ticker][1],
                as_of=moves[ticker][2],
                active=market_active(ticker),
            )
            for ticker in tickers
        ]
    )


@router.post("/home/refresh", response_model=Refreshed, summary="Refresh prices")
def refresh(account: Writer) -> Refreshed:
    """Drop the price caches, so the next reads download again.

    Watchlist closes (the rows and the 52-week scan), the book's close download
    and everything priced off it (positions, the basket, the history), plus the
    quote burst, which is what the off-session day figures read. The ledger
    replays stay hot: a refresh is about prices, and the ledger only changes
    on an import, which rekeys its own entries by mtime.

    Process-wide, because the caches are: a price download is shared by every
    account tracking the same names. Hence the cooldown. A session only, like
    every other write — a bearer token has no business pressing buttons.
    """
    global _last_refresh
    now = time.monotonic()
    with _refresh_lock:
        if now - _last_refresh < REFRESH_COOLDOWN_S:
            return Refreshed(cleared=False)
        _last_refresh = now
    for memo in (
        loaders.watchlist_closes,
        loaders.held_closes,
        loaders.positions_table,
        loaders.basket_values,
        loaders.history,
        loaders.quotes,
        briefing._card_closes,
    ):
        # Looked up rather than assumed: every one of these is a `ttl_cache`
        # today, and a loader that stops being one should stop being cleared,
        # not turn the button into a 500.
        clear = getattr(memo, "cache_clear", None)
        if clear is not None:
            clear()
    return Refreshed(cleared=True)


@router.get(
    "/home/market", response_model=MarketGlance, summary="The market, at a glance"
)
def market() -> MarketGlance:
    """The regime and a dozen readings over the day, the week and the month.

    No account: the same answer for every reader, guests included. Each half
    fails on its own — a dead FRED call costs the yield tile, a dead composite
    costs the chip — and only a dead price burst empties the card, with the
    reason set so it can say which source it was.
    """
    try:
        closes = loaders.pulse_closes()
    except Exception as exc:  # noqa: BLE001 — answered as a reason, not a 500
        return MarketGlance(unavailable=_reason(exc))

    tiles: list[MarketTile] = []
    for key, symbol, group, welcome in MARKET_TILES:
        series = closes.get(symbol)
        if series is None or series.dropna().empty:
            continue
        tiles.append(_price_tile(key, symbol, group, welcome, series))
        if group == "risk":
            try:
                rate = _rate_tile(loaders.pulse_rate_rows().get(MARKET_RATE[1]))
            except Exception:  # noqa: BLE001 — FRED down costs one tile
                rate = None
            if rate is not None:
                tiles.append(rate)

    hits, total = sm.above_ma_share(
        closes, [i.ticker for i in sm.INDICES], MARKET_BREADTH_WINDOW
    )
    out = MarketGlance(
        tiles=tiles,
        breadth=Breadth(hits=hits, total=total, window=MARKET_BREADTH_WINDOW)
        if total
        else None,
        as_of=max((t.as_of for t in tiles if t.as_of), default=None),
    )
    try:
        built = loaders.market_pulse()
    except Exception:  # noqa: BLE001 — the tiles stand without the chip
        return out
    history = built.history.dropna()
    out.score = _num(built.score)
    out.regime = built.regime
    out.run = sm.regime_run(history)
    out.history = [float(v) for v in history.tail(MARKET_HISTORY)]
    return out
