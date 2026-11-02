"""The day-change columns come from daily closes, so outside a live regular
session they show the LAST completed session's move, not a live tick. These
helpers flag that state so the UI can render those cells muted ("market
closed — last close") instead of implying they're moving right now.
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from stocks import obs
from stocks.data.crypto import is_crypto
from stocks.portfolio import consistency

if TYPE_CHECKING:
    from datetime import datetime

# Regular-session hours per exchange, keyed by the Yahoo symbol suffix
# (resolve() gives it — e.g. RCF -> TEP.PA -> "PA"). (IANA tz, open, close) in
# exchange-local time; continuous session (HK/Tokyo lunch breaks ignored — a
# soft cue, not a trading gate). No suffix / unknown = US.
_EXCHANGE_HOURS: dict[str, tuple[str, tuple[int, int], tuple[int, int]]] = {
    # Euronext + Southern Europe (CET)
    "PA": ("Europe/Paris", (9, 0), (17, 30)),
    "AS": ("Europe/Amsterdam", (9, 0), (17, 30)),
    "BR": ("Europe/Brussels", (9, 0), (17, 30)),
    "LS": ("Europe/Lisbon", (8, 0), (16, 30)),
    "MI": ("Europe/Rome", (9, 0), (17, 30)),
    "MC": ("Europe/Madrid", (9, 0), (17, 30)),
    "VI": ("Europe/Vienna", (9, 0), (17, 30)),
    # Germany (Xetra + Frankfurt floor)
    "DE": ("Europe/Berlin", (9, 0), (17, 30)),
    "F": ("Europe/Berlin", (8, 0), (20, 0)),
    # UK / Ireland
    "L": ("Europe/London", (8, 0), (16, 30)),
    "IR": ("Europe/Dublin", (8, 0), (16, 30)),
    # Switzerland + Nordics
    "SW": ("Europe/Zurich", (9, 0), (17, 30)),
    "ST": ("Europe/Stockholm", (9, 0), (17, 30)),
    "HE": ("Europe/Helsinki", (10, 0), (18, 30)),
    "CO": ("Europe/Copenhagen", (9, 0), (17, 0)),
    "OL": ("Europe/Oslo", (9, 0), (16, 30)),
    # Asia-Pacific
    "HK": ("Asia/Hong_Kong", (9, 30), (16, 0)),
    "T": ("Asia/Tokyo", (9, 0), (15, 0)),
    "SS": ("Asia/Shanghai", (9, 30), (15, 0)),
    "SZ": ("Asia/Shanghai", (9, 30), (15, 0)),
    "KS": ("Asia/Seoul", (9, 0), (15, 30)),
    "TW": ("Asia/Taipei", (9, 0), (13, 30)),
    "NS": ("Asia/Kolkata", (9, 15), (15, 30)),
    "BO": ("Asia/Kolkata", (9, 15), (15, 30)),
    "AX": ("Australia/Sydney", (10, 0), (16, 0)),
    # Other Americas
    "TO": ("America/Toronto", (9, 30), (16, 0)),
    "SA": ("America/Sao_Paulo", (10, 0), (17, 0)),
}


_NEW_YORK = "America/New_York"


def _closure(venue: str | None, tz_name: str, now_utc: datetime | None) -> str | None:
    """The calendar's mark on `venue`'s local day — "closed", "early" — or None."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from stocks.data import market_holidays

    if venue is None:
        return None
    local = (now_utc or datetime.now(UTC)).astimezone(ZoneInfo(tz_name)).date()
    return market_holidays.DAYS.get(venue, {}).get(local)


def _session_open(
    tz_name: str,
    open_hm: tuple[int, int],
    close_hm: tuple[int, int],
    now_utc: datetime | None = None,
    venue: str | None = None,
) -> bool:
    """Whether `now` is inside a Mon–Fri open→close window in `tz_name`.

    With `venue` (a `market_holidays` calendar) a day it marks closed reads
    as shut, and a half session ends at the venue's early close. Without one
    it is time alone — a soft display cue. `now_utc` is injectable for tests.
    """
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    from stocks.data import market_holidays

    now = (now_utc or datetime.now(UTC)).astimezone(ZoneInfo(tz_name))
    if now.weekday() >= 5:  # Sat/Sun
        return False
    closure = _closure(venue, tz_name, now_utc)
    if closure == market_holidays.CLOSED:
        return False
    if closure == market_holidays.EARLY and venue in market_holidays.EARLY_CLOSE:
        close_hm = min(close_hm, market_holidays.EARLY_CLOSE[venue])
    return time(*open_hm) <= now.time() < time(*close_hm)


def _us_live() -> dict | None:
    """Finnhub's word on the US session — `{open, session, holiday}` — when
    a key is set and an answer has landed (`finnhub.us_session`, a minute
    old at most, refreshed off this thread); None otherwise, and the
    time-table clock decides."""
    from stocks.data import finnhub

    return finnhub.us_session()


def us_market_open(now_utc: datetime | None = None) -> bool:
    """Whether the US equity regular session (Mon–Fri, 09:30–16:00 America/
    New_York, less the NYSE calendar's closures) is open right now.

    On the live clock the exchange's own status wins when Finnhub has it;
    an injected `now_utc` is always the time table, so a test reads the
    same answer with or without a key."""
    from stocks.data import market_holidays

    if now_utc is None and (live := _us_live()) is not None:
        return live["open"]
    return _session_open(_NEW_YORK, (9, 30), (16, 0), now_utc, market_holidays.US)


def market_live(ticker: str, now_utc: datetime | None = None) -> bool:
    """Whether `ticker` is in a live regular session on its own exchange now.

    Crypto trades 24/7 (always live). Equities key off the Yahoo symbol suffix
    (`_EXCHANGE_HOURS`) so a Paris/London/HK name follows its local hours; an
    unsuffixed or unknown symbol falls back to US hours. Exchange-local, so a
    European stock reads open during CET hours even while US premarket is closed.
    """
    from stocks.data import market_holidays
    from stocks.data.fetch import resolve

    if is_crypto(ticker):
        return True
    symbol = resolve(ticker)
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    hours = _EXCHANGE_HOURS.get(suffix)
    if hours is None:
        return us_market_open(now_utc)
    # The calendar knows Xetra, Madrid and London; any other venue is time alone.
    return _session_open(*hours, now_utc, market_holidays.venue(symbol))


def us_extended_session(now_utc: datetime | None = None) -> str | None:
    """ "pre" / "post" while a US extended-hours window is open, else None.

    Yahoo quotes those windows (04:00-09:30 and 16:00-20:00 America/New_York),
    so the day change keeps moving outside the regular session. On the live
    clock Finnhub's session wins when it has one (`_us_live`); otherwise the
    time table, with no window on a day the calendar closes and the post
    window opening at the early close on a half day."""
    from stocks.data import market_holidays

    if now_utc is None and (live := _us_live()) is not None:
        return live["session"] if live["session"] in ("pre", "post") else None
    closure = _closure(market_holidays.US, _NEW_YORK, now_utc)
    if closure == market_holidays.CLOSED:
        return None
    close = (
        market_holidays.EARLY_CLOSE[market_holidays.US]
        if closure == market_holidays.EARLY
        else (16, 0)
    )
    if _session_open(_NEW_YORK, (4, 0), (9, 30), now_utc):
        return "pre"
    if _session_open(_NEW_YORK, close, (20, 0), now_utc):
        return "post"
    return None


def market_active(ticker: str, now_utc: datetime | None = None) -> bool:
    """Whether `ticker` has a live quote now: regular session OR US pre/post.

    Drives the dimmed day-change cells. A premarket quote is live data, so it
    reads in full colour; a name whose exchange is fully shut stays dimmed.
    Only US symbols get an extended feed here, so anything on a foreign
    exchange follows `market_live`."""
    if market_live(ticker, now_utc):
        return True
    from stocks.data.fetch import resolve

    symbol = resolve(ticker)
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    return suffix not in _EXCHANGE_HOURS and us_extended_session(now_utc) is not None


def _quote_date(quote: dict, *, today: bool = False) -> str | None:
    """The exchange-local trading date behind a quote, ISO, or None.

    `today` asks for the exchange's current date instead of the last regular
    trade's — what a premarket move belongs to, since `regularMarketTime` is
    still yesterday's close while the premarket quotes.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(str(quote.get("exchangeTimezoneName") or "America/New_York"))
    except Exception:
        zone = ZoneInfo("America/New_York")
    if today:
        return datetime.now(UTC).astimezone(zone).date().isoformat()
    stamp = quote.get("regularMarketTime")
    if hasattr(stamp, "astimezone"):
        return stamp.astimezone(zone).date().isoformat()
    if stamp is None:
        return None  # no trade stamp in the quote — the caller prints no date
    try:
        moment = datetime.fromtimestamp(float(stamp), UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return moment.astimezone(zone).date().isoformat()


def session_quote(ticker: str) -> dict | None:
    """Yahoo quote snapshot: `{"price", "pct", "session"}`, or None if missing.

    `pct` is the move since the previous regular close, extended hours
    included. Reads Yahoo's batch quote (`data.quotes`): during premarket
    `regularMarketPrice` is still the last close, so `preMarketPrice /
    regularMarketPrice - 1` is the move so far today; after the close
    `postMarketPrice / regularMarketPreviousClose - 1` compounds the session
    with after-hours. Outside those windows it falls back to the last completed
    session (`regularMarketPrice / regularMarketPreviousClose - 1`), which is
    what the daily close-to-close basket gets wrong (a stale/flat premarket bar
    collapses it to ~0%).

    `price` is the price `pct` was measured to — the extended-hours quote while
    one is trading, else the last regular price. `session` is "pre"/"post" only
    while that window is actually open per `marketState`, so a fully closed
    market reads None even though its last after-hours price is still used.

    `as_of` is the exchange-local trading date `pct` belongs to, which is the
    part a caller cannot infer: outside the session the move is the *last
    completed* session, so a card that calls it "today" is off by a day (or by
    a weekend). Premarket stamps today; every other branch stamps the regular
    session the quote closed. None when the quote carries no timestamp.
    """
    from stocks.data.quotes import quote as live_quote

    return _snapshot(live_quote(ticker))


def _snapshot(quote: dict) -> dict | None:
    """`session_quote`'s reading of one raw Yahoo quote row — pure, no network.

    Split out because the batch path parses the same rows: one place decides
    which price a day change is measured from, whoever fetched it. `currency`
    is the listing's quote currency as Yahoo spells it (GBp for pence), for a
    caller setting the price beside a figure of its own.

    `regular` / `regular_as_of` are the regular session's own price and date
    whatever window is open — the close a daily bar would print, which is what
    `loaders._overlay_live` lays over a book's last bar. Extended hours are a
    move, not a close.

    `pct` is None, the price kept, when the quote and the close it is measured
    from cannot be one session apart (`consistency.day_move`): a feed that
    mixed pence with pounds is a logged contradiction, not a +9,900 % day.

    `basis` is which price the move is measured to — "pre", "post" or
    "regular" — whether or not that window is still open: overnight
    (PREPRE, CLOSED) the after-hours print is the latest trade, and for a
    company that reported after the bell it is the whole reaction.

    `prior`, premarket only, is the last regular session's own move (the close
    `pct` starts from over the one before it): a premarket reading that wants
    "yesterday plus this morning" compounds the two.
    """
    with obs.swallow("quote.session"):
        symbol = str(quote.get("symbol") or "")
        state = str(quote.get("marketState") or "")
        regular = quote.get("regularMarketPrice")
        prev = quote.get("regularMarketPreviousClose")
        pre, post = quote.get("preMarketPrice"), quote.get("postMarketPrice")
        high, low = quote.get("fiftyTwoWeekHigh"), quote.get("fiftyTwoWeekLow")
        session = {
            "currency": quote.get("currency"),
            "regular": float(regular) if regular else None,
            "regular_as_of": _quote_date(quote) if regular else None,
            # The year's extremes ride the same row: the price card's range
            # tile reads them here rather than paying a second fetch. Absent
            # on a Finnhub fallback row, which carries no year.
            "high_52w": float(high) if high else None,
            "low_52w": float(low) if low else None,
        }
        if state.startswith("PRE") and pre and regular:
            price = float(pre)
            return {
                "price": price,
                "pct": consistency.day_move(price, float(regular), ticker=symbol),
                "prior": (
                    consistency.day_move(float(regular), float(prev), ticker=symbol)
                    if prev
                    else None
                ),
                "session": "pre",
                "basis": "pre",
                "as_of": _quote_date(quote, today=True),
                **session,
            }
        # Not in PRE itself, where Yahoo has moved on to today's session.
        if post and prev and state != "PRE":
            price = float(post)
            return {
                "price": price,
                "pct": consistency.day_move(price, float(prev), ticker=symbol),
                "session": "post" if state.startswith("POST") else None,
                "basis": "post",
                "as_of": _quote_date(quote),
                **session,
            }
        if regular and prev:
            price = float(regular)
            return {
                "price": price,
                "pct": consistency.day_move(price, float(prev), ticker=symbol),
                "session": None,
                "basis": "regular",
                "as_of": _quote_date(quote),
                **session,
            }
    return None


def _session_move(ticker: str) -> float | None:
    """Day % move from the quote (see `session_quote`), None when unavailable."""
    quote = session_quote(ticker)
    return quote["pct"] if quote else None


def session_quotes(tickers: list[str]) -> dict[str, dict]:
    """`session_quote` for every ticker, in ONE request. Missing quotes absent.

    The full snapshot rather than the bare percentage, because a day move is
    only half a fact: `as_of` says which session it is, and a caller that
    prints it as "today" without looking is how a Wednesday card ends up
    quoting Monday's close.

    This used to fan `.info` out over a thread pool — two requests per ticker,
    eight at a time, and a `with` block that waited on whatever hung. Off-
    session that is the whole book, and a throttled Yahoo turned a Home render
    into a nineteen-minute one. `data.quotes` asks once, under one budget.
    """
    from stocks.data.quotes import quotes as live_quotes

    if not tickers:
        return {}
    snapshots = ((t, _snapshot(row)) for t, row in live_quotes(list(tickers)).items())
    return {t: q for t, q in snapshots if q and q.get("pct") is not None}


def session_moves(tickers: list[str]) -> dict[str, float]:
    """Day % move per ticker (native), extended hours included, concurrent.

    Feeds the off-session day-change cells: premarket / after-hours while those
    windows are open, the last completed session once they close — never the
    flat premarket 0% the daily basket can produce. Tickers whose quote is
    unavailable are absent (caller falls back to the basket value). Callers
    that will *write* the number into prose want `session_quotes` instead, for
    the `as_of` that says which session it is."""
    return {t: q["pct"] for t, q in session_quotes(tickers).items()}
