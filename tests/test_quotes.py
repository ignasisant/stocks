"""Batch quote endpoint — one request for the whole book (stocks.data.quotes).

The unit under test is the thing that replaced a `.info` fan-out: what matters
is that it asks ONCE, keys the answer back to the caller's ticker, and never
lets a throttled Yahoo outlive its budget.
"""

import time

import pytest

import stocks.data.fetch as fetch
from stocks.data import quotes as q

ALIASES = {"RCF": "TEP.PA"}


def _rows(*symbols, **fields):
    return [{"symbol": s, "regularMarketPrice": 1.0, **fields} for s in symbols]


def _recorder(calls):
    """A `_fetch` stand-in that answers every symbol and logs the batches."""

    def fetch(symbols, timeout):
        calls.append(list(symbols))
        return _rows(*symbols)

    return fetch


# ------------------------------------------------------------------ batching
def test_one_request_carries_every_symbol(monkeypatch):
    calls = []

    def fake(symbols, timeout):
        calls.append(list(symbols))
        return _rows(*symbols)

    monkeypatch.setattr(q, "_fetch", fake)
    out = q.quotes(["AAPL", "NVDA", "MDB"])
    assert calls == [["AAPL", "NVDA", "MDB"]]  # one call, not three
    assert sorted(out) == ["AAPL", "MDB", "NVDA"]


def test_long_lists_are_chunked(monkeypatch):
    monkeypatch.setattr(q, "CHUNK", 2)
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    out = q.quotes(["A", "B", "C", "D", "E"])
    assert calls == [["A", "B"], ["C", "D"], ["E"]]
    assert len(out) == 5


def test_duplicate_tickers_are_asked_for_once(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    q.quotes(["AAPL", "AAPL", "aapl"])
    assert calls == [["AAPL", "aapl"]]  # resolve() is case-preserving, dedupe isn't


# ------------------------------------------------------------------- keying
def test_broker_codes_resolve_out_and_map_back(monkeypatch):
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: dict(ALIASES))
    asked = {}
    monkeypatch.setattr(
        q, "_fetch",
        lambda symbols, timeout: asked.update(symbols=list(symbols)) or _rows(*symbols),
    )
    out = q.quotes(["RCF", "NVDA"])
    # Yahoo is asked for the resolved symbol...
    assert asked["symbols"] == ["TEP.PA", "NVDA"]
    # ...but the caller gets its own code back, never the alias.
    assert sorted(out) == ["NVDA", "RCF"]
    assert out["RCF"]["symbol"] == "TEP.PA"


def test_a_symbol_yahoo_skips_is_simply_absent(monkeypatch):
    # A delisted name (ORGN) drops out of the response. That is a missing row,
    # not an error: the rest of the book must still price.
    monkeypatch.setattr(q, "_fetch", lambda symbols, timeout: _rows("AAPL"))
    out = q.quotes(["AAPL", "ORGN"])
    assert list(out) == ["AAPL"]


def test_empty_input_never_touches_the_network(monkeypatch):
    monkeypatch.setattr(q, "_fetch", lambda symbols, timeout: pytest.fail("fetched"))
    assert q.quotes([]) == {}


def test_junk_rows_are_dropped(monkeypatch):
    monkeypatch.setattr(
        q, "_fetch", lambda symbols, timeout: [{"symbol": "AAPL"}, {"no": "symbol"}]
    )
    assert list(q.quotes(["AAPL"])) == ["AAPL"]


# ------------------------------------------------------- failure and budget
def test_a_failure_degrades_to_nothing_and_opens_the_cooldown(monkeypatch):
    def boom(symbols, timeout):
        raise RuntimeError("429")

    monkeypatch.setattr(q, "_fetch", boom)
    assert q.quotes(["AAPL"]) == {}
    assert fetch.throttle_remaining() > 0


def test_the_cooldown_stops_asking_at_all(monkeypatch):
    calls = []
    monkeypatch.setattr(q, "_fetch", _recorder(calls))
    fetch.trip_throttle()
    assert q.quotes(["AAPL"]) == {}
    assert calls == []  # the point: a throttled host stops making it worse


def test_a_spent_budget_keeps_what_already_arrived(monkeypatch):
    """A slow first chunk must not buy a second one — the caller is a render."""
    monkeypatch.setattr(q, "CHUNK", 1)
    calls = []

    def slow(symbols, timeout):
        calls.append(list(symbols))
        time.sleep(0.1)
        return _rows(*symbols)

    monkeypatch.setattr(q, "_fetch", slow)
    out = q.quotes(["A", "B", "C"], timeout=0.05)
    assert calls == [["A"]]  # budget spent, the rest never asked for
    assert list(out) == ["A"]  # and what did arrive is kept


def test_the_timeout_shrinks_with_the_remaining_budget(monkeypatch):
    monkeypatch.setattr(q, "CHUNK", 1)
    seen = []

    def record(symbols, timeout):
        seen.append(timeout)
        time.sleep(0.02)
        return _rows(*symbols)

    monkeypatch.setattr(q, "_fetch", record)
    q.quotes(["A", "B"], timeout=1.0)
    assert seen[1] < seen[0] <= 1.0


# -------------------------------------------------------------- single read
def test_quote_reads_one_and_returns_a_blob(monkeypatch):
    monkeypatch.setattr(q, "_fetch", lambda symbols, timeout: _rows(*symbols))
    assert q.quote("AAPL")["symbol"] == "AAPL"


def test_quote_is_empty_when_yahoo_has_none(monkeypatch):
    monkeypatch.setattr(q, "_fetch", lambda symbols, timeout: [])
    assert q.quote("ORGN") == {}
