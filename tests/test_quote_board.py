"""The shared quote board and its crypto source (stocks.data.quotes, .kraken).

What matters: a price someone just read is not asked for again within its age,
a coin never costs a Yahoo request when Kraken has it, a thin Kraken pair is
not a quote, and Home's day moves to a minute-old price without the book being
rebuilt (`book_moves.live_frame`).
"""

import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from stocks.data import kraken
from stocks.data import quotes as q
from stocks.views import book_moves

PAIRS = {
    "result": {
        "XXBTZEUR": {"wsname": "XBT/EUR", "altname": "XBTEUR", "status": "online"},
        "CATEUR": {"wsname": "CAT/EUR", "altname": "CATEUR", "status": "online"},
        "XETHZJPY": {"wsname": "ETH/JPY", "altname": "ETHJPY", "status": "online"},
    }
}


def _tick(last, opened, trades):
    return {"c": [str(last), "1"], "o": str(opened), "t": [trades, trades]}


def _kraken(ticker, calls=None):
    def get(url, timeout):
        if calls is not None:
            calls.append(url)
        return PAIRS if url.endswith("/AssetPairs") else ticker

    return get


def _recorder(calls):
    def fetch(symbols, timeout):
        calls.append(list(symbols))
        return [{"symbol": s, "regularMarketPrice": 1.0} for s in symbols if s != "GONE"]

    return fetch


# ------------------------------------------------------------------- kraken
def test_kraken_answers_under_its_own_names(monkeypatch):
    """XBT is Bitcoin, and an old pair answers under its legacy key."""
    body = {"error": [], "result": {"XXBTZEUR": _tick(80_000, 79_000, 5000)}}
    monkeypatch.setattr(kraken, "_get", _kraken(body))
    out = kraken.quotes(["BTC-EUR", "AAPL"])
    assert list(out) == ["BTC-EUR"]
    row = out["BTC-EUR"]
    assert row["regularMarketPrice"] == 80_000
    assert row["regularMarketPreviousClose"] == 79_000
    assert row["currency"] == "EUR" and row["marketState"] == "REGULAR"
    assert row["shortName"] == "Bitcoin EUR"


def test_a_thin_pair_is_not_a_quote(monkeypatch):
    body = {"error": [], "result": {"CATEUR": _tick(1.2e-6, 1.1e-6, 1)}}
    monkeypatch.setattr(kraken, "_get", _kraken(body))
    assert kraken.quotes(["CAT-EUR"]) == {}


def test_a_pair_kraken_does_not_list_is_never_asked(monkeypatch):
    calls = []
    monkeypatch.setattr(kraken, "_get", _kraken({"result": {}}, calls))
    assert kraken.quotes(["DOGE-USD"]) == {}
    assert not any("Ticker" in url for url in calls)


def test_a_failed_ticker_request_cools_off(monkeypatch):
    calls = []

    def get(url, timeout):
        calls.append(url)
        if url.endswith("/AssetPairs"):
            return PAIRS
        raise ConnectionError("down")

    monkeypatch.setattr(kraken, "_get", get)
    assert kraken.quotes(["BTC-EUR"]) == {}
    asked = len(calls)
    assert kraken.quotes(["BTC-EUR"]) == {}
    assert len(calls) == asked  # the cooldown asked nothing


# -------------------------------------------------------------------- board
def test_a_fresh_row_is_not_asked_again(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    first = q.quotes(["AAPL"])
    second = q.quotes(["AAPL"])
    assert calls == [["AAPL"]]
    assert second["AAPL"] is first["AAPL"]
    assert first["AAPL"]["fetchedAt"] <= time.time()


def test_a_row_past_its_age_is_asked_again(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    q.quotes(["AAPL"])
    q.quotes(["AAPL"], max_age=0)
    assert calls == [["AAPL"], ["AAPL"]]


def test_the_age_can_differ_by_ticker(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    q.quotes(["AAPL", "SAP.DE"])
    q.quotes(["AAPL", "SAP.DE"], max_age=lambda t: 0 if t == "AAPL" else 900)
    assert calls == [["AAPL", "SAP.DE"], ["AAPL"]]


def test_a_symbol_nobody_quotes_is_not_asked_every_time(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    assert q.quotes(["GONE"]) == {}
    assert q.quotes(["GONE"], max_age=0) == {}  # a miss keeps MISS_AGE_S
    assert calls == [["GONE"]]


def test_a_failed_refresh_serves_the_last_row(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    first = q.quotes(["AAPL"])

    def boom(symbols, timeout):
        raise RuntimeError("Too Many Requests")

    monkeypatch.setattr(q, "_fetch", boom)
    again = q.quotes(["AAPL"], max_age=0)
    assert again["AAPL"] is first["AAPL"]


def test_a_dead_feed_is_not_asked_again_by_every_reader(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    first = q.quotes(["AAPL"])

    def boom(symbols, timeout):
        calls.append(list(symbols))
        raise TimeoutError("read timed out")

    monkeypatch.setattr(q, "_fetch", boom)
    q.quotes(["AAPL", "NVDA"], max_age=0)
    again = q.quotes(["AAPL", "NVDA"], max_age=0)
    assert calls == [["AAPL"], ["AAPL", "NVDA"]]  # once per RETRY_S, not per reader
    assert again == {"AAPL": first["AAPL"]}

    monkeypatch.setattr(q, "RETRY_S", 0.0)
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    assert sorted(q.quotes(["AAPL", "NVDA"], max_age=0)) == ["AAPL", "NVDA"]


def test_a_name_a_batch_leaves_out_keeps_its_last_row(monkeypatch):
    """v7 drops symbols under load: one miss is not a delisting."""
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    first = q.quotes(["AAPL", "NVDA"])
    monkeypatch.setattr(
        q,
        "_fetch",
        lambda symbols, timeout: [{"symbol": "NVDA", "regularMarketPrice": 2.0}],
    )
    again = q.quotes(["AAPL", "NVDA"], max_age=0)
    assert again["AAPL"] is first["AAPL"]
    assert again["NVDA"]["regularMarketPrice"] == 2.0


def test_a_name_never_priced_is_a_miss(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    assert q.quotes(["GONE"]) == {}
    assert q._board["GONE"][1] is None


def test_concurrent_readers_share_one_request(monkeypatch):
    calls = []
    release = threading.Event()

    def slow(symbols, timeout):
        calls.append(list(symbols))
        release.wait(2)
        return [{"symbol": s, "regularMarketPrice": 1.0} for s in symbols]

    monkeypatch.setattr(q, "_fetch", slow)
    out = []
    readers = [
        threading.Thread(target=lambda: out.append(q.quotes(["AAPL"]))) for _ in range(4)
    ]
    for reader in readers:
        reader.start()
    time.sleep(0.2)
    release.set()
    for reader in readers:
        reader.join(5)
    assert calls == [["AAPL"]]
    assert len(out) == 4 and all("AAPL" in got for got in out)


def test_coins_go_to_kraken_not_yahoo(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    body = {"error": [], "result": {"XXBTZEUR": _tick(80_000, 79_000, 5000)}}
    monkeypatch.setattr(kraken, "_get", _kraken(body))
    out = q.quotes(["BTC-EUR", "AAPL"])
    assert calls == [["AAPL"]]
    assert out["BTC-EUR"]["quoteSource"] == "kraken"


def test_a_coin_yahoo_spells_as_another_coin_never_reaches_yahoo(monkeypatch):
    """Yahoo's CAT-EUR is not Simon's Cat: Kraken or nothing."""
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    body = {"error": [], "result": {"CATEUR": _tick(1.2e-6, 1.1e-6, 1)}}
    monkeypatch.setattr(kraken, "_get", _kraken(body))
    assert q.quotes(["CAT-EUR"]) == {}
    assert calls == []


def test_a_coin_kraken_cannot_quote_falls_back_to_yahoo(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    out = q.quotes(["BTC-EUR"])  # conftest's Kraken is offline
    assert calls == [["BTC-EUR"]]
    assert "BTC-EUR" in out


# --------------------------------------------------------------- live frame
DAYS = pd.DatetimeIndex(["2026-11-25", "2026-11-26"])


def _live(monkeypatch, snaps, closes, live=("AAPL",)):
    monkeypatch.setattr(book_moves, "market_live", lambda t: t in live)
    monkeypatch.setattr(
        book_moves,
        "loaders",
        SimpleNamespace(
            quotes=lambda tickers: snaps, held_closes=lambda db, mtime: closes
        ),
    )


def _frame():
    return pd.DataFrame({"AAPL": [980.0, 1000.0], "SAP.DE": [500.0, 510.0]}, index=DAYS)


def test_a_live_name_moves_to_the_board_price(monkeypatch):
    closes = {"AAPL": pd.Series([98.0, 100.0], index=DAYS)}
    snap = {"regular": 102.0, "regular_as_of": "2026-11-26", "fetched_at": 1.0}
    _live(monkeypatch, {"AAPL": snap}, closes)
    frame = _frame()
    moved, used = book_moves.live_frame(frame, "db", 0.0)
    assert moved.loc[DAYS[-1], "AAPL"] == pytest.approx(1020.0)
    assert moved.loc[DAYS[-1], "SAP.DE"] == 510.0  # shut: left as built
    assert frame.loc[DAYS[-1], "AAPL"] == 1000.0  # the cached frame is untouched
    assert used == {"AAPL": snap}


@pytest.mark.parametrize(
    "snap",
    [
        {"regular": 102.0, "regular_as_of": "2026-11-25"},  # another session
        {"regular": 350.0, "regular_as_of": "2026-11-26"},  # past LIVE_SWING
        {"regular": None, "regular_as_of": "2026-11-26"},
    ],
)
def test_a_quote_that_does_not_fit_the_bar_leaves_the_frame(monkeypatch, snap):
    closes = {"AAPL": pd.Series([98.0, 100.0], index=DAYS)}
    _live(monkeypatch, {"AAPL": snap}, closes)
    moved, used = book_moves.live_frame(_frame(), "db", 0.0)
    assert moved.loc[DAYS[-1], "AAPL"] == 1000.0
    assert used == {}


def test_nothing_live_asks_for_nothing(monkeypatch):
    monkeypatch.setattr(book_moves, "market_live", lambda t: False)
    monkeypatch.setattr(
        book_moves, "loaders", SimpleNamespace(quotes=lambda t: pytest.fail("asked"))
    )
    frame = _frame()
    assert book_moves.live_frame(frame, "db", 0.0) == (frame, {})


def test_quoted_at_is_the_oldest_moving_read(monkeypatch):
    monkeypatch.setattr(book_moves, "market_live", lambda t: t == "AAPL")
    old, new = 1_764_165_600.0, 1_764_165_660.0
    live = {"AAPL": {"fetched_at": new}}
    session = {
        "NVDA": {"fetched_at": old, "session": "post"},
        "SAP.DE": {"fetched_at": old - 600, "session": None},  # shut: no claim
    }
    stamp = book_moves.quoted_at(live, session)
    assert stamp == datetime.fromtimestamp(old, UTC).isoformat(timespec="seconds")
    assert book_moves.quoted_at({}, {"SAP.DE": session["SAP.DE"]}) is None
