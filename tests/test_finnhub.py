"""Finnhub quote fallback (stocks.data.finnhub) and its seam in data.quotes.

What matters: it only ever asks for US listings, it answers in the shape the
day-change code already reads, it stays inside Finnhub's free allowance, and
it only steps in for symbols Yahoo never answered for.
"""

import io
import time
import urllib.error

import pytest

import stocks.data.fetch as fetch
from stocks.analysis.portfolio import _snapshot
from stocks.data import finnhub
from stocks.data import quotes as q

BODY = {"c": 110.0, "pc": 100.0, "t": 1759780800, "d": 10.0, "dp": 10.0}


@pytest.fixture
def keyed(monkeypatch):
    """A key, and a `_fetch` that answers every symbol with BODY and logs it."""
    asked = []
    monkeypatch.setattr(finnhub, "api_key", lambda: "test-key")

    def fake(symbol, key, timeout):
        asked.append(symbol)
        return dict(BODY)

    monkeypatch.setattr(finnhub, "_fetch", fake)
    return asked


def _http_error(code):
    return urllib.error.HTTPError("https://finnhub.io", code, "no", {}, io.BytesIO())


# ------------------------------------------------------------------ coverage
@pytest.mark.parametrize("symbol", ["AAPL", "BRK-B", "GOOGL", "F"])
def test_us_listings_are_covered(symbol):
    assert finnhub.covers(symbol)


@pytest.mark.parametrize(
    "symbol", ["SAN.MC", "TEP.PA", "^GSPC", "EURUSD=X", "BTC-EUR", "aapl", "TOOLONG"]
)
def test_everything_else_is_not(symbol):
    assert not finnhub.covers(symbol)


def test_without_a_key_nothing_is_asked(monkeypatch):
    monkeypatch.setattr(finnhub, "_fetch", lambda *a: pytest.fail("fetched"))
    assert finnhub.quotes(["AAPL"], timeout=1) == {}


def test_only_covered_symbols_are_asked(keyed):
    out = finnhub.quotes(["AAPL", "SAN.MC", "^GSPC", "AAPL"], timeout=1)
    assert keyed == ["AAPL"]
    assert list(out) == ["AAPL"]


def test_share_classes_are_asked_in_finnhubs_spelling(keyed):
    out = finnhub.quotes(["BRK-B"], timeout=1)
    assert keyed == ["BRK.B"]
    assert list(out) == ["BRK-B"]  # keyed back by the Yahoo symbol


# --------------------------------------------------------------------- shape
def test_the_row_reads_as_a_regular_session_quote(keyed):
    row = finnhub.quotes(["AAPL"], timeout=1)["AAPL"]
    snap = _snapshot(row)
    assert snap["price"] == 110.0
    assert abs(snap["pct"] - 0.10) < 1e-9
    assert snap["session"] is None  # no extended hours on the free quote
    assert snap["currency"] == "USD"
    assert snap["as_of"] == "2025-10-06"


def test_an_unknown_symbol_is_absent_not_zero(monkeypatch, keyed):
    # Finnhub answers an unknown symbol 200 with every field zero.
    monkeypatch.setattr(finnhub, "_fetch", lambda *a: {"c": 0, "pc": 0, "t": 0})
    assert finnhub.quotes(["ZZZZ"], timeout=1) == {}


# ------------------------------------------------------------ rate and refusal
def test_the_minute_allowance_is_never_exceeded(monkeypatch, keyed):
    monkeypatch.setattr(finnhub, "PER_MINUTE", 2)
    out = finnhub.quotes(["A", "B", "C", "D"], timeout=1)
    assert len(keyed) == 2
    assert len(out) == 2


@pytest.mark.parametrize("code", [429, 401, 403])
def test_a_refusal_stops_asking(monkeypatch, keyed, code):
    calls = []

    def refuse(*a):
        calls.append(1)
        raise _http_error(code)

    monkeypatch.setattr(finnhub, "_fetch", refuse)
    monkeypatch.setattr(finnhub, "WORKERS", 1)  # one at a time, so the block lands
    assert finnhub.quotes(["A", "B", "C"], timeout=1) == {}
    assert calls == [1]


def test_a_network_error_costs_that_symbol_only(monkeypatch, keyed):
    def flaky(symbol, key, timeout):
        if symbol == "A":
            raise TimeoutError
        return dict(BODY)

    monkeypatch.setattr(finnhub, "_fetch", flaky)
    assert list(finnhub.quotes(["A", "B"], timeout=1)) == ["B"]


def test_a_hung_request_is_abandoned_at_the_timeout(monkeypatch, keyed):
    monkeypatch.setattr(finnhub, "_fetch", lambda *a: time.sleep(2) or dict(BODY))
    started = time.monotonic()
    assert finnhub.quotes(["AAPL"], timeout=0.1) == {}
    assert time.monotonic() - started < 1


# ------------------------------------------------------------ the quotes seam
def test_finnhub_fills_in_while_yahoo_cools_off(monkeypatch, keyed):
    monkeypatch.setattr(q, "_fetch", lambda *a, **k: pytest.fail("asked Yahoo"))
    fetch.trip_throttle()
    out = q.quotes(["AAPL", "NVDA"])
    assert sorted(out) == ["AAPL", "NVDA"]
    assert out["AAPL"]["quoteSource"] == "finnhub"


def test_finnhub_fills_in_when_yahoo_fails(monkeypatch, keyed):
    def boom(symbols, timeout):
        raise RuntimeError("429")

    monkeypatch.setattr(q, "_fetch", boom)
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"RCF": "TEP.PA"})
    out = q.quotes(["AAPL", "RCF"])
    assert list(out) == ["AAPL"]  # the Paris listing has no free fallback
    assert keyed == ["AAPL"]


def test_a_name_yahoo_answered_for_is_not_asked_again(monkeypatch, keyed):
    # Yahoo answered the chunk and left ORGN out: delisted, not throttled.
    monkeypatch.setattr(
        q, "_fetch",
        lambda symbols, timeout: [{"symbol": "AAPL", "regularMarketPrice": 1.0}],
    )
    out = q.quotes(["AAPL", "ORGN"])
    assert list(out) == ["AAPL"]
    assert keyed == []


def test_a_disowned_broker_code_is_not_taken_for_a_us_listing(monkeypatch, keyed):
    fetch._unlisted.add("SAN")
    fetch.trip_throttle()
    assert q.quotes(["SAN"]) == {}
    assert keyed == []


def test_the_caller_gets_its_own_code_back(monkeypatch, keyed):
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"BERKSHIRE": "BRK-B"})
    fetch.trip_throttle()
    out = q.quotes(["BERKSHIRE"])
    assert list(out) == ["BERKSHIRE"]
    assert keyed == ["BRK.B"]
