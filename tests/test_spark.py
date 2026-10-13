"""Daily closes from Yahoo's spark endpoint (stocks.data.spark) and the month a
book's refresh asks it for (stocks.data.fetch.fetch_tail).

What matters: twenty symbols a request, dates read in the exchange's zone (a
Sydney session opens the evening before in UTC), all or nothing when Yahoo
refuses, and only a refusal opening the host's cooldown. And that a name spark
leaves out or thins out still gets its month, from chart.
"""

from __future__ import annotations

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from stocks.data import fetch, spark

# 2026-10-07 .. 2026-10-09 session opens, as Yahoo stamped them.
NY = [1791379800, 1791466200, 1791552600]  # 13:30 UTC
SYDNEY = [1791327600, 1791414000, 1791500400]  # 23:00 UTC the evening before


def _entry(symbol, stamps, closes, zone="America/New_York"):
    meta = {"symbol": symbol, "currency": "USD"}
    if zone:
        meta["exchangeTimezoneName"] = zone
    return {
        "symbol": symbol,
        "response": [
            {
                "meta": meta,
                "timestamp": stamps,
                "indicators": {"quote": [{"close": closes}]},
            }
        ],
    }


def _market(**entries):
    """A `_fetch` stand-in answering from `entries` and logging each chunk."""
    calls: list[list[str]] = []

    def fake(symbols, range_, timeout):
        calls.append(list(symbols))
        return [entries[s] for s in symbols if s in entries]

    return fake, calls


def test_dates_are_the_exchanges_own(monkeypatch):
    fake, _ = _market(
        AAPL=_entry("AAPL", NY, [1.0, 2.0, 3.0]),
        **{"BHP.AX": _entry("BHP.AX", SYDNEY, [4.0, 5.0, 6.0], "Australia/Sydney")},
    )
    monkeypatch.setattr(spark, "_fetch", fake)
    out = spark.closes(["AAPL", "BHP.AX"])
    days = ["2026-10-07", "2026-10-08", "2026-10-09"]
    assert [str(d.date()) for d in out["AAPL"].index] == days
    assert [str(d.date()) for d in out["BHP.AX"].index] == days
    assert out["AAPL"].index.tz is None and out["AAPL"].index.name == "Date"
    assert out["AAPL"].name == "AAPL"


def test_gaps_and_a_repeated_live_day_are_dropped(monkeypatch):
    live = NY[-1] + 3600  # the session's own day, stamped again while trading
    fake, _ = _market(AAPL=_entry("AAPL", [*NY, live], [1.0, None, 3.0, 3.5]))
    monkeypatch.setattr(spark, "_fetch", fake)
    s = spark.closes(["AAPL"])["AAPL"]
    assert list(s) == [1.0, 3.5]


def test_symbols_yahoo_does_not_know_are_absent(monkeypatch):
    fake, _ = _market(AAPL=_entry("AAPL", NY, [1.0, 2.0, 3.0]))
    monkeypatch.setattr(spark, "_fetch", fake)
    assert list(spark.closes(["AAPL", "NOPE"])) == ["AAPL"]


def test_twenty_symbols_a_request(monkeypatch):
    fake, calls = _market()
    monkeypatch.setattr(spark, "_fetch", fake)
    spark.closes([f"S{i}" for i in range(45)] + ["S0"])
    assert [len(c) for c in calls] == [20, 20, 5]


class _Refused(Exception):
    def __init__(self, status: int, text: str = ""):
        super().__init__(text or f"HTTP Error {status}")
        self.response = type("R", (), {"status_code": status})()


def _failing(*errors):
    calls: list[list[str]] = []

    def fake(symbols, range_, timeout):
        calls.append(list(symbols))
        error = errors[len(calls) - 1] if len(calls) <= len(errors) else None
        if error is not None:
            raise error
        return [_entry(s, NY, [1.0, 2.0, 3.0]) for s in symbols]

    return fake, calls


def test_a_refusal_opens_the_cooldown(monkeypatch):
    fake, calls = _failing(_Refused(429, "Too Many Requests"))
    monkeypatch.setattr(spark, "_fetch", fake)
    with pytest.raises(YFRateLimitError):
        spark.closes(["AAPL"])
    assert fetch.throttle_remaining() > 0
    # The next call does not reach the network at all.
    with pytest.raises(YFRateLimitError):
        spark.closes(["AAPL"])
    assert len(calls) == 1


def test_a_stale_crumb_is_reset_and_asked_again(monkeypatch):
    resets = []
    monkeypatch.setattr(spark, "reset_crumb", lambda: resets.append(1))
    fake, calls = _failing(_Refused(401, "Invalid Crumb"))
    monkeypatch.setattr(spark, "_fetch", fake)
    assert list(spark.closes(["AAPL"])) == ["AAPL"]
    assert len(calls) == 2 and resets == [1]
    assert fetch.throttle_remaining() == 0


def test_anything_else_is_a_refusal_without_a_cooldown(monkeypatch):
    fake, _ = _failing(TimeoutError("read timed out"))
    monkeypatch.setattr(spark, "_fetch", fake)
    with pytest.raises(YFRateLimitError):
        spark.closes(["AAPL"])
    assert fetch.throttle_remaining() == 0


def test_one_refused_chunk_refuses_the_whole_call(monkeypatch):
    """A half-refreshed book reads as a book whose other half stopped trading."""
    fake, calls = _failing(None, _Refused(500, "Internal Server Error"))
    monkeypatch.setattr(spark, "_fetch", fake)
    with pytest.raises(YFRateLimitError):
        spark.closes([f"S{i}" for i in range(30)])
    assert len(calls) == 2


# ------------------------------------------------------------- fetch_tail
def _month(n: int = 21) -> pd.Series:
    days = pd.bdate_range("2026-09-10", periods=n, name="Date")
    return pd.Series([float(i) for i in range(n)], index=days)


@pytest.fixture
def tail(monkeypatch):
    """Spark answering `dense`/`thin` names, chart answering whatever is left;
    returns the log of both."""
    log: dict[str, list] = {"spark": [], "chart": []}

    def closes(symbols, range_="1mo", **_):
        log["spark"].append(list(symbols))
        out = {}
        for s in symbols:
            if s.startswith("THIN"):
                out[s] = _month(7)
            elif not s.startswith("GONE"):
                out[s] = _month()
        return out

    def chart(tickers, period, interval, auto_adjust, why):
        log["chart"].append((list(tickers), period, why))
        return {t: pd.DataFrame({"Close": _month(), "Open": _month()}) for t in tickers}

    monkeypatch.setattr(spark, "closes", closes)
    monkeypatch.setattr(fetch, "_errand", chart)
    monkeypatch.setattr(fetch, "_place_isins", lambda tickers: None)
    return log


def test_the_tail_is_spark_keyed_as_asked(tail, monkeypatch):
    monkeypatch.setattr(fetch, "resolve", lambda t: {"SIE": "SIE.DE"}.get(t, t))
    out = fetch.fetch_tail(["AAPL", "SIE"])
    assert tail["spark"] == [["AAPL", "SIE.DE"]]
    assert tail["chart"] == []
    assert sorted(out) == ["AAPL", "SIE"]
    assert list(out["SIE"].columns) == ["Close", "Adj Close"]
    assert (out["SIE"]["Close"] == out["SIE"]["Adj Close"]).all()


def test_names_spark_leaves_out_or_thins_out_go_to_chart(tail):
    out = fetch.fetch_tail(["AAPL", "THIN-EUR", "GONE-EUR", "DOGE-EUR"])
    assert tail["chart"] == [(["THIN-EUR", "GONE-EUR"], "1mo", "tail")]
    assert "Open" in out["THIN-EUR"]
    assert "Open" not in out["AAPL"]


def test_unlisted_and_hand_mapped_coins_skip_spark(tail):
    fetch.mark_unlisted("ORGN")
    fetch.fetch_tail(["AAPL", "ORGN", "MOODENG-EUR"])
    assert tail["spark"] == [["AAPL"]]
    assert tail["chart"] == [(["MOODENG-EUR"], "1mo", "tail")]


def test_a_refused_spark_is_a_refused_tail(monkeypatch):
    def refuse(symbols, range_="1mo", **_):
        raise YFRateLimitError()

    monkeypatch.setattr(spark, "closes", refuse)
    monkeypatch.setattr(fetch, "_place_isins", lambda tickers: None)
    with pytest.raises(YFRateLimitError):
        fetch.fetch_tail(["AAPL"])
