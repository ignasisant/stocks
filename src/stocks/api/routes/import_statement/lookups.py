"""What validation asks the market: does a symbol trade, did a ticker split."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from concurrent.futures import TimeoutError as FuturesTimeout

from stocks import obs
from stocks.data import fetch, symbols
from stocks.portfolio import (
    venue,
)

# Validation asks the market two things the ledger cannot answer
# (`_ticker_exists` and `fetch.splits`): does a symbol the EDGAR map and the
# watchlist have never heard of trade at all — so an ordinary European listing
# stops arriving with an "unknown ticker" warning — and did a ticker whose
# sells overshoot split in between, so a statement that prints trades and no
# corporate actions is rescued with the split row instead of rejected as an
# oversell.
#
# Each call holds an ASGI worker thread, so every answer is bounded — per
# symbol, and in total per statement — and a throttled host is not asked at
# all. Running out of budget answers None, which validation already reads as
# "could not check": the warning stays and nothing is rejected on its account.
# Only definite answers are remembered — "network down" is not "ticker invalid",
# and caching it would make the outage outlive itself.

LOOKUP_BUDGET_S = 4.0  # one symbol's existence check
SPLITS_BUDGET_S = 8.0  # one ticker's corporate-actions history
BATCH_BUDGET_S = 15.0  # every existence check one statement makes, together
_EXISTS_TTL_S = 24 * 3600.0
_EXISTS_MAX = 2048

_exists_memo: dict[str, tuple[float, bool]] = {}
_UNANSWERED = object()  # a search `_within` gave up on, told apart from "no"
_exists_lock = threading.Lock()


def _within(fn, budget: float, default, **fields):
    """`fn()` on a worker, or `default` once `budget` seconds have passed.

    No `with` on the pool, for the reason `fetch._budgeted` gives: shutting it
    down and waiting would block on exactly the hung call the timeout escaped.
    The abandoned thread finishes into nothing — yfinance bounds each request.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=max(budget, 0.0))
    except FuturesTimeout:
        obs.warn("api.import_lookup_budget_spent", budget_s=budget, **fields)
        return default
    except Exception as exc:  # a lookup that breaks is a lookup that could not say
        obs.warn("api.import_lookup_failed", error_type=type(exc).__name__, **fields)
        return default
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _ticker_exists(ticker: str) -> bool | None:
    """Does Yahoo quote this symbol? None when it could not be asked.

    A last price means a listing. A rate limit trips the host-wide cooldown
    (`fetch.trip_throttle`) so the next statement does not ask again into a
    throttle and deepen it.
    """
    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError

    try:
        return bool(yf.Ticker(ticker).fast_info.get("lastPrice"))
    except YFRateLimitError:
        fetch.trip_throttle()
        return None
    except Exception:
        return None  # network down ≠ ticker invalid


def _charted(ticker: str, budget: float) -> bool | None:
    """Does Yahoo have bars for this symbol? Its own last word on a code.

    The quote check cannot always say: yfinance 1.7 raises the same KeyError
    on a symbol Yahoo has no quote for as on a reply it could not read. The
    bulk download can — it hears Yahoo's 404 reason, "No data found", and
    files the code under `fetch.unlisted`, the verdict the price pass reaches
    on the book. Five days of bars, asked only once nothing else could place
    the code. None when the download did not finish or Yahoo is throttled.
    """
    if budget <= 0 or fetch.throttle_remaining() > 0:
        return None
    priced = _within(
        lambda: fetch.fetch_many([ticker], period="5d", budget=budget),
        budget,
        None,
        ticker=ticker,
    )
    if priced is None:
        return None
    if ticker in priced:
        return True
    return False if fetch.unlisted({ticker}) else None


class _Lookup:
    """`validate`'s `lookup`, bounded: one instance per statement.

    The batch deadline starts when the instance is made, so a statement of two
    hundred unfamiliar symbols spends at most `BATCH_BUDGET_S` finding out
    which of them trade, and the rest stay "could not check".

    A symbol the price pass already heard Yahoo disown (`fetch.unlisted`) is
    answered False without asking again: that verdict came from the download
    that prices the book, which is the one that matters.

    Anything short of a quote is not the last word, though. A bare code Yahoo
    does not quote is usually a European line printed without its venue —
    Revolut's SIE is Yahoo's SIE.DE — so the code is looked up in Yahoo's
    search, on the venues its trade currency (`currencies`) trades on
    (`symbols.symbol_for_code`). That includes a quote check that could not
    say: yfinance 1.7 raises on a symbol it has no quote for (KeyError
    'currentTradingPeriod') rather than answering empty, which reads as None,
    and a statement of nine euro codes then warned on every row without the
    search ever being asked. A hit is remembered for good, so the price
    download resolves the code through it (`fetch.resolve`) and the row is
    known. `disowned` collects what is still False after that, so the preview
    can name the rows that will import unpriced.

    Answers are kept per instance: validation asks once per row, and a code a
    statement trades nine times would otherwise spend nine quote checks of the
    one budget.

    The search is told what the statement knows of each code, so it can land
    on the issuer's home line rather than a German regional floor (MEQA is
    MRL.MC in Madrid, not MEQA.F): the ISIN the statement prints beside it
    (`isins`), and the code's fills (`samples`), which a line found by name
    has to have closed near (`venue.agrees`). `home` asks the same of the
    codes the map already holds on a floor.
    """

    def __init__(
        self,
        currencies: dict[str, str] | None = None,
        isins: dict[str, str] | None = None,
        samples: dict[str, list[tuple[str, float]]] | None = None,
    ) -> None:
        self.deadline = time.monotonic() + BATCH_BUDGET_S
        self.currencies = currencies or {}
        self.isins = isins or {}
        self.samples = samples or {}
        self.disowned: set[str] = set()
        self.answers: dict[str, bool | None] = {}

    def __call__(self, ticker: str) -> bool | None:
        if ticker in self.answers:
            return self.answers[ticker]
        answer = self._ask(ticker)
        if answer is not True:
            listed = self._listed(ticker)
            # A venue found is a listing whatever the quote check said; no
            # venue only confirms a False — it cannot turn "could not ask"
            # into "unlisted". The chart can: a code nothing placed is asked
            # once more, of the download that will price it.
            if listed or (listed is None and answer is False):
                answer = listed
            elif listed is False and answer is None:
                answer = _charted(
                    ticker, min(LOOKUP_BUDGET_S, self.deadline - time.monotonic())
                )
        if answer is False:
            self.disowned.add(ticker)
        self.answers[ticker] = answer
        return answer

    def _listed(self, ticker: str) -> bool | None:
        """Whether the search places this code on a venue (SIE -> SIE.DE).

        None when the search ran out of time: its thread still finishes into
        the cache, so the next preview may know, and "unpriced" would be a
        verdict nobody reached.
        """
        if symbols.code_symbol(ticker):
            return True
        left = self.deadline - time.monotonic()
        if left <= 0:
            return False
        found = _within(
            lambda: self._search(ticker),
            min(LOOKUP_BUDGET_S, left),
            _UNANSWERED,
            ticker=ticker,
        )
        return None if found is _UNANSWERED else bool(found)

    def home(self) -> None:
        """Ask for the home line of each code here the map holds on a floor.

        `__call__` only reaches codes the book does not know, and a code
        imported before the search looked past the floors is known: without
        this its MEQA.F would stand for good. All at once, within one lookup's
        budget; a search still running then finishes into the map, and one
        that could not decide is asked again by the next statement.
        """
        floored = [
            ticker
            for ticker in self.currencies
            if symbols.on_floor(symbols.code_symbol(ticker) or "")
        ]
        left = self.deadline - time.monotonic()
        if not floored or left <= 0:
            return
        pool = ThreadPoolExecutor(max_workers=min(len(floored), _HOME_WORKERS))
        try:
            asked = [pool.submit(self._search, ticker) for ticker in floored]
            wait(asked, timeout=min(LOOKUP_BUDGET_S, left))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _search(self, ticker: str) -> str | None:
        currency = self.currencies.get(ticker, "")
        samples = self.samples.get(ticker)

        def vet(symbol: str) -> bool | None:
            return venue.agrees(symbol, samples or [], currency, _close)

        return symbols.symbol_for_code(
            ticker,
            currency,
            isin=self.isins.get(ticker, ""),
            vet=vet if samples else None,
        )

    def _ask(self, ticker: str) -> bool | None:
        if fetch.unlisted({ticker}):
            return False
        now = time.monotonic()
        with _exists_lock:
            hit = _exists_memo.get(ticker)
        if hit is not None and now - hit[0] < _EXISTS_TTL_S:
            return hit[1]
        left = self.deadline - now
        if left <= 0 or fetch.throttle_remaining() > 0:
            return None
        answer = _within(
            lambda: _ticker_exists(ticker),
            min(LOOKUP_BUDGET_S, left),
            None,
            ticker=ticker,
        )
        if answer is not None:
            with _exists_lock:
                _exists_memo[ticker] = (now, answer)
                while len(_exists_memo) > _EXISTS_MAX:
                    _exists_memo.pop(next(iter(_exists_memo)))
        return answer


_HOME_WORKERS = 4


def _close(symbol: str, day: str) -> float | None:
    """`fetch.close_on`, bounded, and not asked of a throttled host."""
    if fetch.throttle_remaining() > 0:
        return None
    return _within(
        lambda: fetch.close_on(symbol, day), LOOKUP_BUDGET_S, None, ticker=symbol
    )
