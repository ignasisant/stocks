"""The live layer over a book's closes (stocks.api.loaders._overlay_live).

What matters: the last bar is the live regular price when the quote is newer
or of the same session; pre/after-hours and older quotes leave the bars
alone; another unit (pence for pounds) is refused; no quotes is the bars as
they were; and an overlay that has not moved hands back the very same object,
so nothing keyed on it rebuilds.
"""

from __future__ import annotations

import pandas as pd
import pytest

from stocks.analysis.portfolio import _snapshot
from stocks.api import loaders


def _closes(**last: float) -> dict[str, pd.Series]:
    days = pd.DatetimeIndex(["2026-10-08", "2026-10-09"], name="Date")
    return {
        t: pd.Series([price * 0.98, price], index=days, name=t)
        for t, price in last.items()
    }


@pytest.fixture
def live(monkeypatch):
    """Set `snaps[ticker] = (regular, as_of)`; `asks` counts quote requests."""
    snaps: dict[str, tuple[float, str]] = {}
    asks: list[tuple] = []

    def quotes(tickers):
        asks.append(tickers)
        return {
            t: {"regular": p, "regular_as_of": d, "price": p, "pct": 0.0}
            for t, (p, d) in snaps.items()
            if t in tickers
        }

    monkeypatch.setattr(loaders, "quotes", quotes)
    loaders._READINGS.clear()
    yield snaps, asks
    loaders._READINGS.clear()


def test_a_later_session_adds_its_bar(live):
    snaps, _ = live
    snaps["AAPL"] = (110.0, "2026-10-12")
    out = loaders._overlay_live(_closes(AAPL=100.0), ("db", "Close"))
    assert out["AAPL"].index[-1] == pd.Timestamp("2026-10-12")
    assert list(out["AAPL"])[-2:] == [100.0, 110.0]


def test_the_same_session_replaces_its_close(live):
    snaps, _ = live
    snaps["AAPL"] = (101.5, "2026-10-09")
    closes = _closes(AAPL=100.0)
    out = loaders._overlay_live(closes, ("db", "Close"))
    assert len(out["AAPL"]) == 2 and out["AAPL"].iloc[-1] == 101.5
    assert closes["AAPL"].iloc[-1] == 100.0  # the input is never written to


def test_an_older_quote_or_none_leaves_the_bars(live):
    snaps, _ = live
    snaps["AAPL"] = (90.0, "2026-10-08")
    closes = _closes(AAPL=100.0, MSFT=50.0)
    assert loaders._overlay_live(closes, ("db", "Close")) is closes


def test_another_unit_is_refused(live):
    snaps, _ = live
    snaps["VOD.L"] = (7200.0, "2026-10-12")  # pence, against bars in pounds
    closes = _closes(**{"VOD.L": 72.0})
    assert loaders._overlay_live(closes, ("db", "Close")) is closes


def test_quotes_failing_is_the_bars_as_they_were(monkeypatch):
    def boom(tickers):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(loaders, "quotes", boom)
    closes = _closes(AAPL=100.0)
    assert loaders._overlay_live(closes, ("db", "Close")) is closes


def test_an_unmoved_overlay_is_the_same_object(live):
    snaps, _ = live
    snaps["AAPL"] = (101.0, "2026-10-09")
    closes = _closes(AAPL=100.0)
    first = loaders._overlay_live(closes, ("db", "Close"))
    assert loaders._overlay_live(closes, ("db", "Close")) is first
    snaps["AAPL"] = (102.0, "2026-10-09")
    moved = loaders._overlay_live(closes, ("db", "Close"))
    assert moved is not first and moved["AAPL"].iloc[-1] == 102.0


def test_the_snapshot_carries_the_regular_close_through_extended_hours():
    quote = {
        "marketState": "POST",
        "regularMarketPrice": 100.0,
        "regularMarketPreviousClose": 98.0,
        "postMarketPrice": 103.0,
        "regularMarketTime": 1791576000,  # 2026-10-09 16:00 New York
        "exchangeTimezoneName": "America/New_York",
        "currency": "USD",
    }
    snap = _snapshot(quote)
    assert snap["price"] == 103.0 and snap["session"] == "post"
    assert snap["regular"] == 100.0 and snap["regular_as_of"] == "2026-10-09"


def test_held_closes_hand_the_same_object_until_something_moves(live, monkeypatch):
    """Recomputed every five minutes for the live layer, `held_closes` must not
    look new to `_on_download` while neither the frames nor the quotes moved."""
    snaps, asks = live
    days = pd.DatetimeIndex(["2026-10-08", "2026-10-09"], name="Date")
    bars = {"Close": [99.0, 100.0], "Adj Close": [98.0, 99.0]}
    frames = {"AAPL": pd.DataFrame(bars, index=days)}
    monkeypatch.setattr(loaders, "_held", lambda db: ([], ["AAPL"]))
    monkeypatch.setattr(loaders, "_held_frames", lambda db, mtime: frames)
    monkeypatch.setattr(loaders, "plausible_closes", lambda closes, txs: closes)
    compute = loaders.held_closes.__wrapped__
    snaps["AAPL"] = (101.0, "2026-10-12")
    first = compute("book.db", 1.0)
    assert first is compute("book.db", 1.0)
    assert first["AAPL"].iloc[-1] == 101.0
    snaps.clear()
    bare = compute("book.db", 1.0)
    assert bare is compute("book.db", 1.0)
    assert bare["AAPL"].iloc[-1] == 99.0
    assert len(asks) == 4
