"""The book's one price download, and the month every refresh asks instead.

`loaders._held_frames` used to download every held name's whole history each
time its quarter hour ran out — most of a minute on the production vCPU, all
to learn one new close. Now the first download is whole and each refresh asks
`_TAIL` for the names the previous frames already hold, laying it over them.
What is pinned here is when that shortcut is *not* taken: a name the base
lacks, a history Yahoo rewrote (a dividend restates every earlier `Adj
Close`), a trade imported from before the base began. And that the base
outlives the process, since a boot is exactly when the slow download hurt.
"""

from __future__ import annotations

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


class Yahoo:
    """A fake `fetch_many` over a market whose bars a test can rewrite.

    A month is the last 22 sessions of what a whole download would return;
    every request is logged as (names, period)."""

    def __init__(self, market: dict[str, pd.DataFrame]):
        self.market = market
        self.asked: list[tuple[tuple[str, ...], str]] = []

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
    assert y.asked[1:] == [(("AAPL", "MSFT"), loaders._TAIL)]
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
    assert [p for _, p in y.asked] == [y.asked[0][1], loaders._TAIL]
    assert float(again["AAPL"]["Close"].iloc[-1]) == 104.0


def test_a_dividend_sends_that_name_back_for_its_whole_history(book, yahoo):
    db = book(("2024-01-02", "AAPL"), ("2024-01-02", "MSFT"))
    y = yahoo({"AAPL": _bars(100.0), "MSFT": _bars(200.0)})
    loaders._held_frames(db, 1.0)
    # Ex-dividend: Yahoo now adjusts every earlier AAPL close down.
    y.market["AAPL"] = _bars(100.0, adj=99.0)
    again = _refresh(db)
    assert y.asked[1] == (("AAPL", "MSFT"), loaders._TAIL)
    assert y.asked[2][0] == ("AAPL",) and y.asked[2][1] != loaders._TAIL
    assert len(y.asked) == 3
    assert (again["AAPL"]["Adj Close"] == 99.0).all()
    assert len(again["MSFT"]) == len(DAYS)


def test_a_name_the_base_never_had_is_downloaded_whole(book, yahoo):
    db = book(("2024-01-02", "AAPL"))
    y = yahoo({"AAPL": _bars(100.0), "NVDA": _bars(50.0)})
    loaders._held_frames(db, 1.0)
    book(("2024-03-01", "NVDA"))
    again = _refresh(db)
    assert y.asked[1] == (("AAPL",), loaders._TAIL)
    assert y.asked[2][0] == ("NVDA",) and y.asked[2][1] != loaders._TAIL
    assert len(again["NVDA"]) == len(DAYS)


def test_a_name_yahoo_disowned_is_not_asked_for_again(book, yahoo, monkeypatch):
    db = book(("2024-01-02", "AAPL"), ("2024-01-02", "ORGN"))
    y = yahoo({"AAPL": _bars(100.0)})
    loaders._held_frames(db, 1.0)
    monkeypatch.setattr(fetch, "_unlisted", {"ORGN"})
    again = _refresh(db)
    assert y.asked[1:] == [(("AAPL",), loaders._TAIL)]
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
    assert y.asked[1:] == [(("AAPL",), loaders._TAIL)]


def test_a_refused_month_is_a_refused_download(book, yahoo):
    """Yahoo gutting the month fails like a gutted whole download — the last
    good frames answer, marked stale — rather than falling through to a
    whole-history request per name."""
    from stocks.api import cache

    tickers = [f"T{i}" for i in range(8)]
    db = book(*(("2024-01-02", t) for t in tickers))
    y = yahoo({t: _bars(10.0) for t in tickers})
    first = loaders._held_frames(db, 1.0)
    y.market = {}
    holder: dict[str, float] = {}
    token = cache.STALE.set(holder)
    try:
        again = _refresh(db)
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
    assert y.asked[1:] == [(("AAPL",), loaders._TAIL)]
    assert (again["AAPL"]["Close"] == 101.0).all()
