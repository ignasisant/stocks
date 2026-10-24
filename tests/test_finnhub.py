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
        q,
        "_fetch",
        lambda symbols, timeout: [{"symbol": "AAPL", "regularMarketPrice": 1.0}],
    )
    out = q.quotes(["AAPL", "ORGN"])
    assert list(out) == ["AAPL"]
    assert keyed == []


def test_a_disowned_broker_code_is_not_taken_for_a_us_listing(monkeypatch, keyed):
    fetch.mark_unlisted("SAN")
    fetch.trip_throttle()
    assert q.quotes(["SAN"]) == {}
    assert keyed == []


def test_the_caller_gets_its_own_code_back(monkeypatch, keyed):
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {"BERKSHIRE": "BRK-B"})
    fetch.trip_throttle()
    out = q.quotes(["BERKSHIRE"])
    assert list(out) == ["BERKSHIRE"]
    assert keyed == ["BRK.B"]


# ------------------------------------------------------------- the calendar
# Everything below `quotes` rides on `_get`: patched here the way `_fetch` is
# above, so the slicing, the memo and the cooldowns are the real ones.
def _d(day: int):
    from datetime import date

    return date(2026, 10, day)


@pytest.fixture
def keyed_get(monkeypatch):
    """A key, and `install(answer)` to make `_get` answer `answer(path, params)`
    while logging every ask as (path, params)."""
    asked = []
    monkeypatch.setattr(finnhub, "api_key", lambda: "test-key")

    def install(answer):
        def fake(path, params, key, timeout):
            assert key == "test-key"
            asked.append((path, dict(params)))
            return answer(path, params)

        monkeypatch.setattr(finnhub, "_get", fake)

    return asked, install


def _rows(symbol, *days, actual=None):
    return [
        {"symbol": symbol, "date": d.isoformat(), "epsEstimate": 1.0, "epsActual": actual}
        for d in days
    ]


def test_the_calendar_is_keyed_by_symbol_in_finnhubs_spelling(keyed_get):
    asked, install = keyed_get
    install(
        lambda path, params: {
            "earningsCalendar": _rows("AAPL", _d(5))
            + _rows("BRK.B", _d(6))
            + _rows("AAPL", _d(7))
        }
    )
    out = finnhub.earnings_calendar(_d(1), _d(9))
    assert sorted(out) == ["AAPL", "BRK.B"]
    assert [r["date"] for r in out["AAPL"]] == ["2026-10-05", "2026-10-07"]
    assert asked == [("calendar/earnings", {"from": "2026-10-01", "to": "2026-10-09"})]


def test_a_span_goes_out_in_slices(keyed_get):
    asked, install = keyed_get
    install(lambda path, params: {"earningsCalendar": []})
    assert finnhub.earnings_calendar(_d(1), _d(25)) == {}
    spans = sorted((p["from"], p["to"]) for _, p in asked)
    assert spans == [
        ("2026-10-01", "2026-10-10"),
        ("2026-10-11", "2026-10-20"),
        ("2026-10-21", "2026-10-25"),
    ]


def test_a_capped_slice_is_halved_down_to_a_day(monkeypatch, keyed_get):
    """A slice answering the page's 1500 rows was cut short: its rows are
    dropped and both halves asked, until a day answers under the page."""
    from datetime import date

    asked, install = keyed_get
    monkeypatch.setattr(finnhub, "CALENDAR_CHUNK_DAYS", 4)

    def answer(path, params):
        a, b = date.fromisoformat(params["from"]), date.fromisoformat(params["to"])
        if a < b:
            # Over the page, and a symbol that must never reach the answer.
            return {"earningsCalendar": _rows("CUT", a) * finnhub.CALENDAR_PAGE}
        return {"earningsCalendar": _rows(f"DAY{a.day}", a)}

    install(answer)
    out = finnhub.earnings_calendar(_d(1), _d(4))
    assert sorted(out) == ["DAY1", "DAY2", "DAY3", "DAY4"]
    # The slice, its two halves, then the four days.
    assert len(asked) == 7


def test_a_single_day_over_the_page_is_kept_with_a_warning(monkeypatch, keyed_get):
    asked, install = keyed_get
    warned = []
    monkeypatch.setattr(finnhub.obs, "warn", lambda name, **f: warned.append(name))
    install(lambda path, params: {"earningsCalendar": _rows("BUSY", _d(1)) * 1500})
    out = finnhub.earnings_calendar(_d(1), _d(1))
    assert len(out["BUSY"]) == 1500
    assert warned == ["finnhub.earnings_page"]


def test_an_unanswered_slice_voids_the_whole_window(monkeypatch, keyed_get):
    """A window with a hole would read as "no print" for every name in the
    missing days; better no window, and Yahoo as before."""
    asked, install = keyed_get
    monkeypatch.setattr(finnhub, "WORKERS", 1)

    def answer(path, params):
        if params["from"] == "2026-10-11":
            raise TimeoutError
        return {"earningsCalendar": _rows("AAPL", _d(5))}

    install(answer)
    assert finnhub.earnings_calendar(_d(1), _d(25)) is None


def test_without_a_key_the_calendar_is_not_asked(monkeypatch):
    monkeypatch.setattr(finnhub, "_get", lambda *a: pytest.fail("asked"))
    assert finnhub.earnings_calendar(_d(1), _d(9)) is None
    assert finnhub.earnings_window(_d(1)) is None


def test_the_window_is_read_once_per_day_and_shared(keyed_get):
    asked, install = keyed_get
    install(
        lambda path, params: {
            "earningsCalendar": _rows("AAPL", _d(5))
            if params["from"] <= "2026-10-05" <= params["to"]
            else []
        }
    )
    first = finnhub.earnings_window(_d(1))
    assert first == {"AAPL": _rows("AAPL", _d(5))}
    requests = len(asked)
    assert requests > 1  # the span went out in slices
    assert finnhub.earnings_window(_d(1)) is first
    assert len(asked) == requests
    finnhub.earnings_window(_d(2))  # another day is another read
    assert len(asked) == 2 * requests


def test_a_failed_window_is_asked_again_after_the_pause(monkeypatch, keyed_get):
    asked, install = keyed_get
    monkeypatch.setattr(finnhub, "WORKERS", 1)
    monkeypatch.setattr(finnhub, "WINDOW_RETRY_S", 10_000.0)

    def boom(path, params):
        raise TimeoutError

    install(boom)
    assert finnhub.earnings_window(_d(1)) is None
    asked.clear()
    assert finnhub.earnings_window(_d(1)) is None  # inside the pause: not asked
    assert asked == []
    monkeypatch.setattr(finnhub, "WINDOW_RETRY_S", 0.0)
    install(lambda path, params: {"earningsCalendar": []})
    assert finnhub.earnings_window(_d(1)) == {}
    assert asked


# ------------------------------------------------------------ the market clock
@pytest.mark.parametrize(
    "body, expected",
    [
        (
            {"exchange": "US", "holiday": None, "isOpen": True, "session": "regular"},
            {"open": True, "session": "regular", "holiday": None},
        ),
        (
            {"exchange": "US", "holiday": None, "isOpen": False, "session": "pre-market"},
            {"open": False, "session": "pre", "holiday": None},
        ),
        (
            {"holiday": None, "isOpen": False, "session": "post-market"},
            {"open": False, "session": "post", "holiday": None},
        ),
        (
            {"holiday": "Thanksgiving", "isOpen": False, "session": None},
            {"open": False, "session": None, "holiday": "Thanksgiving"},
        ),
    ],
)
def test_us_session_reads_the_exchanges_own_clock(keyed_get, body, expected):
    asked, install = keyed_get
    install(lambda path, params: body)
    assert finnhub.us_session(sync=True) == expected
    assert asked == [("stock/market-status", {"exchange": "US"})]


def test_us_session_is_none_without_a_key(monkeypatch):
    monkeypatch.setattr(finnhub, "_get", lambda *a: pytest.fail("asked"))
    assert finnhub.us_session(sync=True) is None


def test_us_session_asks_on_a_machine_booted_a_moment_ago(keyed_get, monkeypatch):
    """The monotonic clock counts from boot: on a fresh CI runner it reads
    seconds, and "never asked" must still be older than the minute."""
    asked, install = keyed_get
    install(lambda path, params: {"isOpen": True, "session": "regular"})
    monkeypatch.setattr(finnhub.time, "monotonic", lambda: 5.0)
    assert finnhub.us_session(sync=True)["open"] is True
    assert len(asked) == 1


def test_us_session_is_a_memo_for_a_minute(keyed_get):
    asked, install = keyed_get
    install(lambda path, params: {"isOpen": True, "session": "regular"})
    finnhub.us_session(sync=True)
    assert finnhub.us_session(sync=True)["open"] is True
    assert len(asked) == 1


def test_us_session_keeps_the_last_answer_through_a_failed_read(monkeypatch, keyed_get):
    asked, install = keyed_get
    install(lambda path, params: {"isOpen": True, "session": "regular"})
    assert finnhub.us_session(sync=True)["open"] is True

    def boom(path, params):
        raise TimeoutError

    install(boom)
    monkeypatch.setattr(finnhub, "STATUS_TTL_S", 0.0)
    assert finnhub.us_session(sync=True)["open"] is True  # kept
    monkeypatch.setattr(finnhub, "STATUS_KEEP_S", 0.0)
    assert finnhub.us_session(sync=True) is None  # too old to vouch for


def test_us_session_never_holds_the_caller(monkeypatch, keyed_get):
    """Past the minute the caller gets the last answer at once; the read
    happens on another thread."""
    import threading

    asked, install = keyed_get
    started = threading.Event()

    def slow(timeout):
        started.set()

    monkeypatch.setattr(finnhub, "_refresh_status", slow)
    assert finnhub.us_session() is None  # nothing has landed yet
    assert started.wait(2)
    assert finnhub.us_session() is None  # the read is in flight: not asked twice


# ------------------------------------------------------------------ insiders
def test_insider_rows_come_back_as_finnhub_gives_them(keyed_get):
    asked, install = keyed_get
    rows = [{"name": "Cook Tim", "change": -1000, "transactionCode": "S"}]
    install(lambda path, params: {"symbol": "AAPL", "data": rows})
    assert finnhub.insider_transactions("AAPL", _d(1), _d(9)) == rows
    assert asked == [
        (
            "stock/insider-transactions",
            {"symbol": "AAPL", "from": "2026-10-01", "to": "2026-10-09"},
        )
    ]


def test_insider_rows_are_none_when_unanswered(keyed_get):
    asked, install = keyed_get

    def boom(path, params):
        raise TimeoutError

    install(boom)
    assert finnhub.insider_transactions("AAPL", _d(1), _d(9)) is None
    install(lambda path, params: {"symbol": "AAPL"})
    assert finnhub.insider_transactions("AAPL", _d(1), _d(9)) is None


def test_a_refused_side_read_opens_the_cooldown_for_every_read(monkeypatch, keyed_get):
    asked, install = keyed_get

    def refuse(path, params):
        raise _http_error(429)

    install(refuse)
    assert finnhub.us_session(sync=True) is None
    install(lambda path, params: pytest.fail("asked through the cooldown"))
    assert finnhub.insider_transactions("AAPL", _d(1), _d(9)) is None
    monkeypatch.setattr(finnhub, "_fetch", lambda *a: pytest.fail("asked in cooldown"))
    assert finnhub.quotes(["AAPL"], timeout=1) == {}


def test_a_rejected_side_read_closes_only_its_own_path(monkeypatch, keyed_get):
    """Prod: one 401 on a side read used to stop every quote for an hour."""
    asked, install = keyed_get
    warned = []
    monkeypatch.setattr(finnhub.obs, "warn", lambda event, **f: warned.append((event, f)))

    def refuse(path, params):
        raise _http_error(401)

    install(refuse)
    assert finnhub.us_session(sync=True) is None
    assert warned == [
        ("finnhub.rejected", {"status": 401, "path": "stock/market-status"})
    ]

    # The same path stays closed; the others and the quotes still go out.
    install(lambda path, params: pytest.fail("asked through the path's cooldown"))
    assert finnhub.us_session(sync=True) is None
    rows = [{"name": "Cook Tim", "change": -1000, "transactionCode": "S"}]
    install(lambda path, params: {"symbol": "AAPL", "data": rows})
    assert finnhub.insider_transactions("AAPL", _d(1), _d(9)) == rows
    monkeypatch.setattr(finnhub, "_fetch", lambda *a: {"c": 10.0, "pc": 9.0, "t": 1})
    assert "AAPL" in finnhub.quotes(["AAPL"], timeout=1)


def test_a_rejected_quote_still_closes_everything(monkeypatch, keyed_get):
    asked, install = keyed_get

    def refuse(*a):
        raise _http_error(401)

    monkeypatch.setattr(finnhub, "_fetch", refuse)
    assert finnhub.quotes(["AAPL"], timeout=1) == {}
    install(lambda path, params: pytest.fail("asked with a rejected key"))
    assert finnhub.insider_transactions("AAPL", _d(1), _d(9)) is None
