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
"""

from __future__ import annotations

import time

from stocks import obs
from stocks.data.fetch import resolve, throttle_remaining, trip_throttle

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote?"

# Per-request wall clock. The caller is a page render, not a batch job: a
# throttled Yahoo must cost the day-change column, never the page.
TIMEOUT = 8.0

# Symbols per request. Yahoo accepts long lists, but the URL is a GET and a
# book plus its benchmarks can run long; this keeps every request well inside
# any gateway's line limit.
CHUNK = 50

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


def quotes(
    tickers: list[str], *, timeout: float = TIMEOUT
) -> dict[str, dict]:
    """`{ticker: quote blob}` for `tickers`, keyed by the ticker as asked.

    Broker codes are resolved to Yahoo symbols on the way out and mapped back
    on the way in (same contract as `fetch.fetch_many`), so callers never see
    the alias. Tickers Yahoo has no quote for are absent — a delisted name is
    a missing row, not an error.

    Never raises: a throttle, a timeout or a mangled response all return what
    arrived (possibly nothing) and open the cooldown. The callers here render
    a day-change cell; none of them has anything better to do with an
    exception than drop the column.
    """
    if not tickers:
        return {}
    cooling = throttle_remaining()
    if cooling > 0:
        obs.event(
            "yahoo.quotes.cooling_off",
            tickers=len(tickers), remaining_s=round(cooling, 1),
        )
        return {}

    symbol_of = {t: resolve(t) for t in tickers}
    ticker_of = {s: t for t, s in symbol_of.items()}  # last alias wins, as fetch does
    symbols = list(dict.fromkeys(symbol_of.values()))

    out: dict[str, dict] = {}
    deadline = time.monotonic() + timeout
    with obs.timed("yahoo.quotes", symbols=len(symbols)) as rec:
        for i in range(0, len(symbols), CHUNK):
            left = deadline - time.monotonic()
            if left <= 0:
                obs.warn("yahoo.quotes.budget_spent", got=len(out), want=len(symbols))
                break
            chunk = symbols[i : i + CHUNK]
            try:
                rows = _fetch(chunk, timeout=left)
            except Exception as exc:  # noqa: BLE001 — a quote is never fatal
                trip_throttle()
                obs.warn("yahoo.quotes.failed", symbols=len(chunk), error=repr(exc))
                break
            for row in rows:
                ticker = ticker_of.get(str(row.get("symbol") or ""))
                if ticker is not None:
                    out[ticker] = row
        rec["quotes"] = len(out)
    return out


def quote(ticker: str, *, timeout: float = TIMEOUT) -> dict:
    """The quote blob for one ticker, `{}` when Yahoo has none."""
    return quotes([ticker], timeout=timeout).get(ticker, {})
