"""Live quote snapshots from Yahoo's batch endpoint — many symbols, ONE request.

`yfinance`'s `.info` is the obvious way to read a quote and the wrong one here.
It fires *two* requests per ticker (a five-module `quoteSummary` plus this same
v7 quote), and a Home render off-session asks for one per position: a 38-name
book cost ~76 requests from a datacenter IP that Yahoo already throttles. The
fields a day-change actually needs — `marketState`, the regular/pre/post prices
and the previous close — all live in the v7 quote, which takes a comma list.
So the whole page becomes one request.

The crumb/cookie dance that endpoint requires is `yfinance`'s (`YfData`), not
ours; we borrow its authenticated session rather than re-implement it.

When Yahoo will not answer — the cooldown is open, a chunk failed, the budget
ran out — the US symbols it never quoted go to Finnhub instead (`data.finnhub`,
only with a key). Symbols Yahoo answered for and simply skipped are not asked
again: a delisted name is missing everywhere.

Crypto pairs ask Kraken first (`data.kraken`): a coin is live around the
clock, and Kraken's public ticker costs Yahoo nothing. A coin priced from
CoinGecko because Yahoo's pair is another coin (`crypto.COINGECKO_IDS`) never
reaches Yahoo here either.

Every answer lands on one process-wide board, per symbol, shared by every
account: two books holding NVDA ask for it once. How old a row may be is the
caller's call (`max_age`, per ticker — a minute while its market trades, much
longer while it is shut), so a live name is re-asked about once a minute
however many readers it has, and a shut one hardly at all. Two callers
missing the same symbol at once share one request. A row that could not be
refreshed (cooldown, timeout) is served as it was, up to `KEEP_S`: its
`fetchedAt` says how old, and an older price beats a blank cell.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from stocks import obs
from stocks.data import finnhub, kraken
from stocks.data.crypto import COINGECKO_IDS, split_pair
from stocks.data.fetch import (
    failure_kind,
    reset_crumb,
    resolve,
    throttle_remaining,
    trip_throttle,
    unlisted,
)

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?"

# Per-request wall clock. The caller is a page render, not a batch job: a
# throttled Yahoo must cost the day-change column, never the page.
TIMEOUT = 8.0

# Symbols per request. Yahoo accepts long lists, but the URL is a GET and a
# book plus its benchmarks can run long; this keeps every request well inside
# any gateway's line limit.
CHUNK = 50

# The least the Finnhub fallback gets, even when Yahoo spent the whole budget
# hanging: without it the fallback would never run in the case it exists for.
FALLBACK_FLOOR = 2.5

# How old a board row may be when the caller says nothing: a live quote.
LIVE_AGE_S = 60.0

# A symbol its source answered for and left out (delisted, unknown) is not
# asked again for this long, whatever the caller's age.
MISS_AGE_S = 900.0

# The oldest row served when a refresh failed. Past it the cell goes blank
# rather than print a price from another part of the day.
KEEP_S = 1800.0

# A symbol no source answered (timeout, refusal, network down) is not asked
# again for this long: its last row is served meanwhile. Without it every
# reader of a dead feed would pay the whole budget again.
RETRY_S = 60.0

# Rows the board holds before it sheds the old ones: a few hundred books'
# names, far more than one instance serves.
BOARD_MAX = 4096

# symbol -> (monotonic when asked, row or None for "answered, nothing").
_board: dict[str, tuple[float, dict | None]] = {}
# symbol -> monotonic of the last ask no source answered.
_failed: dict[str, float] = {}
# symbol -> set once the request that is fetching it lands.
_flights: dict[str, threading.Event] = {}
_board_lock = threading.Lock()
_NEVER = float("-inf")


def clear_board() -> None:
    """Forget every row (tests, Home's refresh button)."""
    with _board_lock:
        _board.clear()
        _failed.clear()


def board_size() -> int:
    """Rows on the board (the RAM sampler)."""
    with _board_lock:
        return len(_board)


# The cooldown lives in `data.fetch`: Yahoo throttles the host, not the
# endpoint, so a quote that comes back 429 is also a statement about the next
# bulk download. One verdict, shared — the price path raises `YFRateLimitError`
# on it, this one just returns nothing.


def _fetch(symbols: list[str], timeout: float) -> list[dict]:
    """Raw quote rows for `symbols`, Yahoo's order. Symbols it has nothing for
    are simply absent from the response."""
    from yfinance.data import YfData

    raw = YfData().get_raw_json(
        QUOTE_URL,
        params={"symbols": ",".join(symbols), "formatted": "false"},
        timeout=timeout,
    )
    rows = (raw or {}).get("quoteResponse", {}).get("result") or []
    return [r for r in rows if isinstance(r, dict)]


def _ask(chunk: list[str], deadline: float) -> list[dict] | None:
    """One chunk's rows, or None when Yahoo would not answer it.

    A stale crumb gets one fresh one and one more try; a refusal opens the
    cooldown; anything else (a timeout, a 5xx) is just this chunk lost.
    """
    for again in (True, False):
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        try:
            return _fetch(chunk, timeout=left)
        except Exception as exc:  # noqa: BLE001 — a quote is never fatal
            kind = failure_kind(exc)
            obs.warn(
                "yahoo.quotes.failed",
                symbols=len(chunk),
                kind=kind,
                error=repr(exc)[:300],
            )
            if kind == "throttle":
                trip_throttle()
                return None
            if kind == "crumb" and again:
                reset_crumb()
                continue
            return None
    return None


def quotes(
    tickers: list[str],
    *,
    timeout: float = TIMEOUT,
    max_age: float | Callable[[str], float] = LIVE_AGE_S,
) -> dict[str, dict]:
    """`{ticker: quote blob}` for `tickers`, keyed by the ticker as asked.

    Broker codes are resolved to Yahoo symbols on the way out and mapped back
    on the way in (same contract as `fetch.fetch_many`), so callers never see
    the alias. Tickers no source has a quote for are absent — a delisted name
    is a missing row, not an error.

    `max_age` is how old a board row may be, in seconds, for this caller:
    one number, or a function of the ticker (`clock.quote_age`). Rows older
    than that are asked again; the rest cost nothing. Each row carries
    `fetchedAt`, the epoch second it was read.

    Never raises: a throttle, a timeout or a mangled response all return what
    arrived (possibly nothing, or what Finnhub filled in for the US names),
    plus the board's last rows for what did not. Only a refusal opens the
    cooldown. A 401 "Invalid crumb" is yfinance's session gone stale: the
    crumb is reset and the chunk asked once more. The callers here render a
    day-change cell; none of them has anything better to do with an exception
    than drop the column.
    """
    if not tickers:
        return {}
    symbol_of = {t: resolve(t) for t in tickers}
    ticker_of = {s: t for t, s in symbol_of.items()}  # last alias wins, as fetch does
    symbols = list(dict.fromkeys(symbol_of.values()))
    if isinstance(max_age, int | float):
        fixed = float(max_age)

        def age(_ticker: str) -> float:
            return fixed
    else:
        age = max_age


    rows: dict[str, dict] = {}
    mine: list[str] = []  # symbols this call fetches
    theirs: list[tuple[str, threading.Event]] = []  # fetched by a call in flight
    now = time.monotonic()
    with _board_lock:
        for symbol in symbols:
            hit = _board.get(symbol)
            if hit is not None:
                limit = age(ticker_of[symbol])
                if hit[1] is None:
                    limit = max(limit, MISS_AGE_S)
                if now - hit[0] < limit:
                    if hit[1] is not None:
                        rows[symbol] = hit[1]
                    continue
            if now - _failed.get(symbol, _NEVER) < RETRY_S:
                if hit is not None and hit[1] is not None and now - hit[0] < KEEP_S:
                    rows[symbol] = hit[1]
                continue
            if (flight := _flights.get(symbol)) is not None:
                theirs.append((symbol, flight))
            else:
                _flights[symbol] = threading.Event()
                mine.append(symbol)
    deadline = now + timeout
    if mine:
        got: dict[str, dict] = {}
        answered: set[str] = set()
        try:
            got, answered = _fill(mine, [ticker_of[s] for s in mine], deadline)
        finally:
            # Always land the flight: a waiter must never sit out its budget
            # on a fetch that died.
            asked_at = time.monotonic()
            with _board_lock:
                for symbol in answered | got.keys():
                    hit = _board.get(symbol)
                    if symbol not in got and _kept(hit, asked_at):
                        # A batch that leaves out a name it priced a minute
                        # ago is a hiccup (v7 drops symbols under load), not
                        # a delisting: keep the row, ask again in `RETRY_S`.
                        _failed[symbol] = asked_at
                        continue
                    _board[symbol] = (asked_at, got.get(symbol))
                    _failed.pop(symbol, None)
                for symbol in mine:
                    if symbol not in answered and symbol not in got:
                        _failed[symbol] = asked_at
                    if symbol not in got and (hit := _board.get(symbol)):
                        if hit[1] is not None and asked_at - hit[0] < KEEP_S:
                            got[symbol] = hit[1]  # the last row beats a blank
                    if (flight := _flights.pop(symbol, None)) is not None:
                        flight.set()
                _shed(asked_at)
        rows.update(got)
    for symbol, flight in theirs:
        flight.wait(max(deadline - time.monotonic(), 0.0))
        with _board_lock:
            hit = _board.get(symbol)
        if hit is not None and hit[1] is not None:
            if time.monotonic() - hit[0] < KEEP_S:
                rows[symbol] = hit[1]
    return {ticker_of[s]: row for s, row in rows.items()}


def _kept(hit: tuple[float, dict | None] | None, now: float) -> bool:
    """Whether a board entry is a row still young enough to serve."""
    return hit is not None and hit[1] is not None and now - hit[0] < KEEP_S


def _shed(now: float) -> None:
    """Forget failed asks past `RETRY_S`; drop rows past `KEEP_S` once the
    board is full, all of it if that is not enough. Caller holds
    `_board_lock`."""
    for symbol in [s for s, at in _failed.items() if now - at >= RETRY_S]:
        del _failed[symbol]
    if len(_board) < BOARD_MAX:
        return
    for symbol in [s for s, (at, _) in _board.items() if now - at >= KEEP_S]:
        del _board[symbol]
    if len(_board) >= BOARD_MAX:
        _board.clear()


def _fill(
    symbols: list[str], tickers: list[str], deadline: float
) -> tuple[dict[str, dict], set[str]]:
    """Fresh rows for `symbols` from Kraken, Yahoo and Finnhub, in that
    order, and the symbols a source answered for (rows or not).

    Each row is a copy stamped `fetchedAt`: the board's rows are shared."""
    out: dict[str, dict] = {}
    answered: set[str] = set()

    coins = [s for s in symbols if split_pair(s)]
    if coins:
        left = min(deadline - time.monotonic(), kraken.TIMEOUT)
        out.update(kraken.quotes(coins, timeout=max(left, 0.5)))
        # Yahoo's pair for these is another coin (`COINGECKO_IDS`): Kraken
        # or nothing.
        answered.update(s for s in coins if (split_pair(s) or ("",))[0] in COINGECKO_IDS)
        answered.update(out)
    yahoo = [s for s in symbols if s not in answered]

    cooling = throttle_remaining() if yahoo else 0.0
    if cooling > 0:
        obs.event(
            "yahoo.quotes.cooling_off",
            tickers=len(yahoo), remaining_s=round(cooling, 1),
        )
    elif yahoo:
        with obs.timed("yahoo.quotes", symbols=len(yahoo)) as rec:
            got = 0
            for i in range(0, len(yahoo), CHUNK):
                left = deadline - time.monotonic()
                if left <= 0:
                    obs.warn("yahoo.quotes.budget_spent", got=got, want=len(yahoo))
                    break
                chunk = yahoo[i : i + CHUNK]
                rows = _ask(chunk, deadline)
                if rows is None:
                    break
                answered.update(chunk)
                wanted = set(chunk)
                for row in rows:
                    symbol = str(row.get("symbol") or "")
                    if symbol in wanted:
                        out[symbol] = row
                        got += 1
            rec["quotes"] = got

    # A bare broker code Yahoo disowned (SAN for Santander) is not the US
    # listing that shares its letters: hold it out of the US-only fallback.
    disowned = {resolve(t) for t in unlisted(tickers)}
    missing = [s for s in symbols if s not in answered and s not in disowned]
    if missing:
        left = max(deadline - time.monotonic(), FALLBACK_FLOOR)
        for symbol, row in finnhub.quotes(missing, timeout=left).items():
            out[symbol] = row
            answered.add(symbol)
    stamp = time.time()
    return {s: {**row, "fetchedAt": stamp} for s, row in out.items()}, answered


def quote(ticker: str, *, timeout: float = TIMEOUT) -> dict:
    """The quote blob for one ticker, `{}` when neither Yahoo nor Finnhub has one."""
    return quotes([ticker], timeout=timeout).get(ticker, {})
