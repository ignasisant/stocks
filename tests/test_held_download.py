"""The book's one price download, and the month every refresh asks instead.

`loaders._held_frames` used to download every held name's whole history each
time its quarter hour ran out — most of a minute on the production vCPU, all
to learn one new close. Now the first download is whole and each refresh asks
for the last month of the names the previous frames already hold, laying it
over them: spark's closes on most refreshes, chart's whole month once a day
(the rebase). What is pinned here is when that shortcut is *not* taken: a name
the base lacks, a history Yahoo rewrote (a split restates every earlier
price; a dividend every earlier `Adj Close`, which only the rebase sees), a
trade imported from before the base began. And that the base outlives the
process, since a boot is exactly when the slow download hurt.
"""

from __future__ import annotations

import threading

import pandas as pd
import pytest

from stocks.api import loaders
from stocks.data import fetch
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction

DAYS = pd.bdate_range("2024-01-02", periods=400)


def _bars(close: float, adj: float | None = None, days=DAYS) -> pd.DataFrame:
    adj = close if adj is None else adj
    return pd.DataFrame(
        {"Close": [close] * len(days), "Adj Close": [adj] * len(days)}, index=days
    )


# What the log calls a spark month (`fetch.fetch_tail`).
SPARK = "spark"


class Yahoo:
    """A fake `fetch_many` and `fetch_tail` over a market whose bars a test
    can rewrite.

    A month is the last 22 sessions of what a whole download would return —
    spark's carries the printed close in both columns; every request is
    logged as (names, period), spark's period as `SPARK`."""

    def __init__(self, market: dict[str, pd.DataFrame]):
        self.market = market
        self.asked: list[tuple[tuple[str, ...], str]] = []

    def tail(self, tickers):
        self.asked.append((tuple(tickers), SPARK))
        out = {}
        for t in tickers:
            if t in self.market:
                close = self.market[t]["Close"].iloc[-22:]
                out[t] = pd.DataFrame({"Close": close, "Adj Close": close})
        return out

    def __call__(self, tickers, period="1y", auto_adjust=True, **_):
        assert auto_adjust is False
        self.asked.append((tuple(tickers), period))
        rows = 22 if period == loaders._TAIL else None
        return {
            t: (self.market[t].iloc[-rows:] if rows else self.market[t]).copy()
            for t in tickers
            if t in self.market
        }


@pytest.fixture
def book(tmp_path):
    db = tmp_path / "portfolio.db"

    def write(*trades: tuple[str, str]) -> str:
        ledger.add_many(
            [Transaction(day, t, "buy", 1, 10.0, "EUR", 1.0) for day, t in trades],
            path=db,
        )
        return str(db)

    return write


@pytest.fixture
def yahoo(monkeypatch):
    def use(market: dict[str, pd.DataFrame]) -> Yahoo:
        fake = Yahoo(market)
        monkeypatch.setattr(fetch, "fetch_many", fake)
        monkeypatch.setattr(fetch, "fetch_tail", fake.tail)
        return fake

    loaders._held_frames.cache_clear()
    fetch.clear_unlisted()
    yield use
    loaders._held_frames.cache_clear()
    fetch.clear_unlisted()


def _refresh(db: str) -> dict[str, pd.DataFrame]:
    """The quarter hour running out: the memo goes, the base stays."""
    loaders._held_frames.cache_clear()
    return loaders._held_frames(db, 1.0)


def test_the_first_download_is_whole_and_a_refresh_asks_a_month(book, yahoo):
    db = book(("2024-01-02", "AAPL"), ("2024-02-01", "MSFT"))
    y = yahoo({"AAPL": _bars(100.0), "MSFT": _bars(200.0)})
    first = loaders._held_frames(db, 1.0)
    assert [names for names, _ in y.asked] == [("AAPL", "MSFT")]
    assert y.asked[0][1] != loaders._TAIL

    # A new close printed since: only the month is asked, and it lands on
    # the end of the history the base already had.
    tomorrow = DAYS[-1] + pd.offsets.BDay()
    for t, price in (("AAPL", 101.0), ("MSFT", 202.0)):
        y.market[t] = pd.concat([y.market[t], _bars(price, days=[tomorrow])])
    again = _refresh(db)
    assert y.asked[1:] == [(("AAPL", "MSFT"), SPARK)]
    assert len(again["AAPL"]) == len(first["AAPL"]) + 1
    assert again["AAPL"].index.is_unique and again["AAPL"].index.is_monotonic_increasing
    assert float(again["AAPL"]["Close"].iloc[-1]) == 101.0
    assert float(again["AAPL"]["Close"].iloc[0]) == 100.0


def test_the_base_session_still_trading_is_replaced_not_compared(book, yahoo):
    """The base's last bar may have been taken mid-session; the month's copy
    of that day wins rather than counting as a rewritten history."""
    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    y.market["AAPL"].iloc[-1] = [104.0, 104.0]  # the close settled higher
    again = _refresh(db)
    assert [p for _, p in y.asked] == [y.asked[0][1], SPARK]
    assert float(again["AAPL"]["Close"].iloc[-1]) == 104.0


def test_a_split_sends_that_name_back_for_its_whole_history(book, yahoo):
    db = book(("2024-01-02", "AAPL"), ("2024-01-02", "MSFT"))
    y = yahoo({"AAPL": _bars(100.0), "MSFT": _bars(200.0)})
    loaders._held_frames(db, 1.0)
    # Two-for-one: Yahoo now prints every earlier AAPL close halved.
    y.market["AAPL"] = _bars(50.0)
    again = _refresh(db)
    assert y.asked[1] == (("AAPL", "MSFT"), SPARK)
    assert y.asked[2][0] == ("AAPL",) and y.asked[2][1] not in (loaders._TAIL, SPARK)
    assert len(y.asked) == 3
    assert (again["AAPL"]["Close"] == 50.0).all()
    assert len(again["MSFT"]) == len(DAYS)


def test_a_dividend_waits_for_the_rebase(book, yahoo, monkeypatch):
    """Spark's month has no adjusted close to disagree with: the base's stands
    until the day's chart month sees the restated history and sends the name
    back whole."""
    db = book(("2024-01-02", "AAPL"), ("2024-01-02", "MSFT"))
    y = yahoo({"AAPL": _bars(100.0), "MSFT": _bars(200.0)})
    loaders._held_frames(db, 1.0)
    # Ex-dividend: Yahoo now adjusts every earlier AAPL close down.
    y.market["AAPL"] = _bars(100.0, adj=99.0)
    again = _refresh(db)
    assert y.asked[1:] == [(("AAPL", "MSFT"), SPARK)]
    assert (again["AAPL"]["Adj Close"] == 100.0).all()

    monkeypatch.setattr(loaders, "_REBASE_S", -1.0)  # a day later
    again = _refresh(db)
    assert y.asked[2] == (("AAPL", "MSFT"), loaders._TAIL)
    assert y.asked[3][0] == ("AAPL",) and y.asked[3][1] not in (loaders._TAIL, SPARK)
    assert len(y.asked) == 4
    assert (again["AAPL"]["Adj Close"] == 99.0).all()
    assert len(again["MSFT"]) == len(DAYS)


def test_the_rebase_is_once_a_day(book, yahoo, monkeypatch):
    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    _refresh(db)
    monkeypatch.setattr(loaders, "_REBASE_S", -1.0)
    _refresh(db)
    monkeypatch.setattr(loaders, "_REBASE_S", 20 * 3600.0)
    _refresh(db)
    assert [p for _, p in y.asked[1:]] == [SPARK, loaders._TAIL, SPARK]


def test_a_refused_rebase_still_brings_the_closes(book, yahoo, monkeypatch):
    """Fifty chart requests refused is no verdict on one spark request: the
    closes still arrive, and the rebase is asked again next time."""
    from yfinance.exceptions import YFRateLimitError

    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    _, stamped = loaders._frames_base(db, "2024-01-02")
    monkeypatch.setattr(loaders, "_REBASE_S", -1.0)

    def refuse(tickers, period="1y", **kwargs):
        if period == loaders._TAIL:
            y.asked.append((tuple(tickers), period))
            raise YFRateLimitError()
        return Yahoo.__call__(y, tickers, period, **kwargs)

    monkeypatch.setattr(fetch, "fetch_many", refuse)
    tomorrow = DAYS[-1] + pd.offsets.BDay()
    y.market["AAPL"] = pd.concat([y.market["AAPL"], _bars(101.0, days=[tomorrow])])
    again = _refresh(db)
    assert [p for _, p in y.asked[1:]] == [loaders._TAIL, SPARK]
    assert float(again["AAPL"]["Close"].iloc[-1]) == 101.0
    _, rebased_at = loaders._frames_base(db, "2024-01-02")
    assert rebased_at == stamped


def test_a_base_from_before_rebases_were_stamped_is_rebased(book, yahoo):
    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    since, frames, _ = loaders._bases[db]
    loaders._bases[db] = (since, frames)  # as the last release wrote it
    _refresh(db)
    assert y.asked[1:] == [(("AAPL",), loaders._TAIL)]


def test_spark_closes_keep_the_bases_other_columns(book, yahoo):
    """The day's high and low the Fees tab reads stay on every day the
    base had; the new day carries only its close until the rebase."""
    db = book(("2024-01-02", "AAPL"))
    market = _bars(100.0)
    market["High"], market["Low"] = 102.0, 98.0
    y = yahoo({"AAPL": market})
    loaders._held_frames(db, 1.0)
    tomorrow = DAYS[-1] + pd.offsets.BDay()
    y.market["AAPL"] = pd.concat([market, _bars(101.0, days=[tomorrow])])
    y.market["AAPL"].loc[DAYS[-1], "Close"] = 100.5  # yesterday settled
    again = _refresh(db)["AAPL"]
    assert list(again.columns) == list(market.columns)
    assert (again["High"].iloc[:-1] == 102.0).all()
    assert pd.isna(again["High"].iloc[-1])
    assert float(again["Close"].loc[DAYS[-1]]) == 100.5
    assert float(again["Close"].iloc[-1]) == 101.0


def test_a_name_the_base_never_had_is_downloaded_whole(book, yahoo):
    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0), "NVDA": _bars(50.0)})
    loaders._held_frames(db, 1.0)
    book(("2024-03-01", "NVDA"))
    again = _refresh(db)
    assert y.asked[1] == (("AAPL",), SPARK)
    assert y.asked[2][0] == ("NVDA",) and y.asked[2][1] not in (loaders._TAIL, SPARK)
    assert len(again["NVDA"]) == len(DAYS)


def test_a_name_yahoo_disowned_is_not_asked_for_again(book, yahoo, monkeypatch):
    db = book(("2024-01-02", "AAPL"), ("2024-01-02", "ORGN"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    fetch.mark_unlisted("ORGN")
    again = _refresh(db)
    assert y.asked[1:] == [(("AAPL",), SPARK)]
    assert "ORGN" not in again


def test_a_trade_from_before_the_base_starts_over(book, yahoo):
    """An import that reaches further back than the base: its first months
    are missing, so the whole book is downloaded again."""
    db = book(("2024-06-03", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    book(("2024-01-02", "AAPL"))
    _refresh(db)
    assert [p for _, p in y.asked].count(loaders._TAIL) == 0
    assert [p for _, p in y.asked].count(SPARK) == 0
    assert len(y.asked) == 2


def test_the_base_outlives_the_process(book, yahoo):
    """A boot is when the whole download hurt most: the next process extends
    the base it finds on disk, even though the ledger it restores carries a
    new mtime."""
    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    loaders._bases.clear()  # the restart
    loaders._held_frames.cache_clear(expire=False)
    loaders._held_frames(db, 2.0)
    assert y.asked[1:] == [(("AAPL",), SPARK)]


def test_a_refused_month_is_a_refused_download(book, yahoo, monkeypatch):
    """Yahoo gutting the month fails like a gutted whole download — the last
    good frames answer from memory, marked stale — rather than falling through
    to a whole-history request per name."""
    import time

    from stocks.api import cache

    tickers = [f"T{i}" for i in range(8)]
    db = book(*(("2024-01-02", t) for t in tickers))
    y = yahoo({t: _bars(10.0) for t in tickers})
    first = loaders._held_frames(db, 1.0)
    y.market = {}
    later = time.monotonic() + loaders._PRICES_TTL + 1  # the quarter hour runs out
    monkeypatch.setattr(cache.time, "monotonic", lambda: later)
    holder: dict[str, float] = {}
    token = cache.STALE.set(holder)
    try:
        again = loaders._held_frames(db, 1.0)
    finally:
        cache.STALE.reset(token)
    assert len(y.asked) == 2 and "since" in holder
    assert set(again) == set(first)


def test_a_month_that_covers_the_whole_base_is_taken_as_it_is(book, yahoo):
    """A name first priced inside the month has no settled day to compare:
    the month is its whole history, not a reason to download it again."""
    db = book(("2024-01-02", "AAPL"))
    recent = DAYS[-3:]
    y = yahoo({"AAPL": _bars(100.0, days=recent)})
    loaders._held_frames(db, 1.0)
    y.market["AAPL"] = _bars(101.0, days=recent)
    again = _refresh(db)
    assert y.asked[1:] == [(("AAPL",), SPARK)]
    assert (again["AAPL"]["Close"] == 101.0).all()


def _sell(db: str, day: str, ticker: str) -> None:
    ledger.add_many([Transaction(day, ticker, "sell", 1, 10.0, "EUR", 1.0)], path=db)


def test_a_name_closed_a_month_before_the_base_ends_is_not_asked_again(book, yahoo):
    """A third of the names a book ever held are long sold: their history ends
    at the sale, and the base already holds it."""
    db = book(("2024-01-02", "AAPL"), ("2024-01-02", "OLD"), ("2024-01-02", "NEW"))
    _sell(db, str(DAYS[100].date()), "OLD")  # sold long before the base ends
    _sell(db, str(DAYS[-5].date()), "NEW")  # sold last week: still settling
    y = yahoo({t: _bars(10.0) for t in ("AAPL", "OLD", "NEW")})
    first = loaders._held_frames(db, 1.0)
    again = _refresh(db)
    assert y.asked[1:] == [(("AAPL", "NEW"), SPARK)]
    assert again["OLD"] is first["OLD"]


def test_a_name_bought_back_is_refreshed_again(book, yahoo):
    db = book(("2024-01-02", "AAPL"))
    _sell(db, str(DAYS[100].date()), "AAPL")
    y = yahoo({"AAPL": _bars(10.0)})
    loaders._held_frames(db, 1.0)
    book((str(DAYS[-2].date()), "AAPL"))
    _refresh(db)
    assert y.asked[1:] == [(("AAPL",), SPARK)]


def test_a_month_that_came_back_without_a_name_keeps_its_bars(book, yahoo):
    """A coin while CoinGecko cools off: its whole history would come from the
    same source that just said nothing. It stands at its last close instead
    of dropping out of the book's prices."""
    tickers = ["AAPL", "MSFT", "NVDA", "MOODENG-EUR"]
    db = book(*(("2024-01-02", t) for t in tickers))
    y = yahoo({t: _bars(10.0) for t in tickers})
    first = loaders._held_frames(db, 1.0)
    del y.market["MOODENG-EUR"]
    again = _refresh(db)
    assert y.asked[1:] == [(tuple(sorted(tickers)), SPARK)]
    assert again["MOODENG-EUR"] is first["MOODENG-EUR"]


def test_the_book_answers_from_the_last_process_while_it_downloads(
    book, yahoo, monkeypatch
):
    """The first visit of a morning, on a new process: last night's prices
    answer at once, marked, and the download lands behind them."""
    from stocks.api import cache

    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    for memo in (loaders.held_closes, loaders.held_printed_closes):
        memo.cache_clear()
    loaders.held_closes(db, 1.0)
    # The restart, ten hours later: memory gone, the disk copy aged.
    loaders.held_closes.cache_clear(expire=False)
    loaders._bases.clear()
    later = cache.time.time() + 10 * 3600
    monkeypatch.setattr(cache.time, "time", lambda: later)
    monkeypatch.setattr(cache.time, "monotonic", lambda: later)
    gate = threading.Event()

    def slow(*args, **kwargs):
        gate.wait(5)
        return Yahoo.__call__(y, *args, **kwargs)

    def slow_tail(*args, **kwargs):
        gate.wait(5)
        return y.tail(*args, **kwargs)

    monkeypatch.setattr(fetch, "fetch_many", slow)
    monkeypatch.setattr(fetch, "fetch_tail", slow_tail)
    holder: dict[str, float] = {}
    token = cache.STALE.set(holder)
    try:
        closes = loaders.held_closes(db, 1.0)
    finally:
        cache.STALE.reset(token)
    assert float(closes["AAPL"].iloc[-1]) == 100.0
    assert "since" in holder
    gate.set()
    loaders.held_closes.cache_clear()


def test_the_fees_bars_are_the_books_download_not_a_second_one(
    book, yahoo, monkeypatch
):
    """The spread reads the same unadjusted bars the closes do: once the book
    has downloaded, the Fees tab asks Yahoo for nothing."""
    from stocks.portfolio import fees

    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0)})
    monkeypatch.setattr(fees, "listing_currencies", lambda names: {"AAPL": "USD"})
    loaders.trade_bars.cache_clear()
    try:
        loaders.held_closes(db, 1.0)
        bars = loaders.trade_bars(db, 1.0)
    finally:
        loaders.trade_bars.cache_clear()
        loaders.held_closes.cache_clear()
    assert len(y.asked) == 1
    assert bars["AAPL"].attrs["currency"] == "USD"
    assert "currency" not in loaders._held_frames(db, 1.0)["AAPL"].attrs
