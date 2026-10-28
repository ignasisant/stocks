"""Twelve Data daily fallback (stocks.data.twelvedata) and its seams in data.fetch.

What matters: inert without a key, US listings only, answers in the frame
shape Yahoo's callers read, only for names Yahoo did not answer, never for a
name it disowned, marked by source, and inside the free allowance.
"""

import io
import urllib.error

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

import stocks.data.fetch as fetch
from stocks.data import twelvedata as td

# Shape recorded from a live probe (2026-10-27, demo key, AAPL, 1day).
BODY = {
    "meta": {
        "symbol": "AAPL",
        "interval": "1day",
        "currency": "USD",
        "exchange_timezone": "America/New_York",
        "exchange": "NASDAQ",
        "mic_code": "XNGS",
        "type": "Common Stock",
    },
    "values": [
        {"datetime": "2026-10-27", "open": "343.165", "high": "347.77",
         "low": "342.4", "close": "346.005", "volume": "626090"},
        {"datetime": "2026-10-26", "open": "343.92001", "high": "347.089996",
         "low": "341.029999", "close": "343.91000", "volume": "42667300"},
        {"datetime": "2026-10-23", "open": "349.12000", "high": "351.73001",
         "low": "345.75", "close": "347.73001", "volume": "39539700"},
    ],
    "status": "ok",
}


@pytest.fixture
def keyed(monkeypatch):
    asked = []
    monkeypatch.setattr(td, "api_key", lambda: "k")

    def fake(url, **kw):
        asked.append(url)
        return dict(BODY)

    monkeypatch.setattr(td, "get_json", fake)
    return asked


def _err(code):
    url = "https://api.twelvedata.com"
    return urllib.error.HTTPError(url, code, "no", {}, io.BytesIO())


def test_keyless_is_inert(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network")

    monkeypatch.setattr(td, "get_json", boom)
    assert td.daily(["AAPL"]) == {}
    assert td.close_on("AAPL", "2026-10-26") is None
    assert td.room() == 0


@pytest.mark.parametrize("symbol", ["SAN.MC", "^GSPC", "EURUSD=X", "BTC-EUR", "aapl"])
def test_only_us_listings(keyed, symbol):
    assert td.daily([symbol]) == {}
    assert keyed == []


def test_frame_shape_and_source(keyed):
    df = td.daily(["AAPL"], 30)["AAPL"]
    assert list(df.index) == sorted(df.index)
    assert df.index.name == "Date"
    assert df["Close"].iloc[-1] == pytest.approx(346.005)
    assert (df["Adj Close"] == df["Close"]).all()
    assert df.attrs["source"] == "twelvedata"
    assert "adjust=splits" in keyed[0] and "start_date=" in keyed[0]


def test_dividend_adjusted_only_when_asked(keyed):
    td.daily(["AAPL"], auto_adjust=True)
    assert "adjust=all" in keyed[0]


def test_close_on_reads_the_last_session_before_the_day(keyed):
    assert td.close_on("AAPL", "2026-10-25") == pytest.approx(347.73001)


def test_a_non_us_answer_is_refused(monkeypatch):
    monkeypatch.setattr(td, "api_key", lambda: "k")
    body = {**BODY, "meta": {**BODY["meta"], "currency": "EUR",
                             "exchange_timezone": "Europe/Madrid"}}
    monkeypatch.setattr(td, "get_json", lambda *a, **k: body)
    assert td.daily(["SAN"]) == {}


def test_memo_spares_the_allowance(keyed):
    td.daily(["AAPL"], 30)
    td.daily(["AAPL"], 30)
    assert len(keyed) == 1


def test_allowance_is_per_minute(keyed):
    names = [f"A{c}" for c in "BCDEFGHIJ"]
    assert len(td.daily(names, 30)) == td.PER_MINUTE
    assert td.room() == 0


@pytest.mark.parametrize("code", [429, 401])
def test_refusal_opens_a_cooldown(monkeypatch, code):
    monkeypatch.setattr(td, "api_key", lambda: "k")

    def refuse(*a, **k):
        raise _err(code)

    monkeypatch.setattr(td, "get_json", refuse)
    assert td.daily(["AAPL"]) == {}
    assert td.room() == 0


def test_error_body_with_status_200_is_a_refusal(monkeypatch):
    monkeypatch.setattr(td, "api_key", lambda: "k")
    monkeypatch.setattr(
        td, "get_json", lambda *a, **k: {"code": 429, "status": "error", "message": "x"}
    )
    assert td.daily(["AAPL"]) == {}
    assert td.room() == 0


# ------------------------------------------------------------ fetch.py seams
def _blank_download(symbols, **kw):
    return pd.DataFrame()


def test_fetch_many_fills_only_names_yahoo_missed(keyed, monkeypatch):
    def download(symbols, **kw):
        idx = pd.date_range("2026-10-20", periods=2, name="Date")
        cols = pd.MultiIndex.from_product([["MSFT"], ["Close"]])
        return pd.DataFrame(1.0, index=idx, columns=cols)

    monkeypatch.setattr(fetch.yf, "download", download)
    out = fetch.fetch_many(["MSFT", "AAPL"], period="1mo")
    assert out["MSFT"]["Close"].iloc[-1] == 1.0  # Yahoo's bars untouched
    assert "source" not in out["MSFT"].attrs
    assert out["AAPL"].attrs["source"] == "twelvedata"
    assert len(keyed) == 1


def test_fetch_many_does_not_paper_over_an_unlisted_code(keyed, monkeypatch):
    def disowned(symbols, **kw):
        # What yfinance's log says for a code it does not know.
        fetch._download_log.sink["AAPL"] = fetch.UNLISTED_REASON + ", may be delisted"
        return pd.DataFrame()

    monkeypatch.setattr(fetch.yf, "download", disowned)
    assert fetch.fetch_many(["AAPL"], period="1mo") == {}
    assert "AAPL" in fetch.unlisted(["AAPL"])
    assert keyed == []


def test_fetch_many_skips_a_non_dollar_holding(keyed, monkeypatch):
    monkeypatch.setattr(fetch.yf, "download", _blank_download)
    assert fetch.fetch_many(["SAN"], period="1mo", currencies={"SAN": "EUR"}) == {}
    assert keyed == []


def test_a_refused_download_is_rescued_only_whole(keyed, monkeypatch):
    def refused(*a, **k):
        raise YFRateLimitError()

    monkeypatch.setattr(fetch.yf, "download", refused)
    monkeypatch.setattr(fetch, "retry", lambda fn, *a, **k: fn())
    out = fetch.fetch_many(["AAPL"], period="1mo")
    assert out["AAPL"].attrs["source"] == "twelvedata"
    # A name the fallback cannot answer keeps the refusal visible to callers.
    with pytest.raises(YFRateLimitError):
        fetch.fetch_many(["AAPL", "SAN.MC"], period="1mo")


def test_a_refused_download_without_a_key_still_raises(monkeypatch):
    def refused(*a, **k):
        raise YFRateLimitError()

    monkeypatch.setattr(fetch.yf, "download", refused)
    monkeypatch.setattr(fetch, "retry", lambda fn, *a, **k: fn())
    with pytest.raises(YFRateLimitError):
        fetch.fetch_many(["AAPL"], period="1mo")


def test_close_on_falls_back_and_counts_as_answered(keyed):
    fetch.trip_throttle()
    before = fetch.unanswered()
    day = BODY["values"][1]["datetime"]
    assert fetch.close_on("AAPL", day) == pytest.approx(343.91)
    assert fetch.unanswered() == before


def test_close_on_unanswered_when_the_fallback_is_silent():
    fetch.trip_throttle()
    before = fetch.unanswered()
    assert fetch.close_on("AAPL", "2026-10-26") is None
    assert fetch.unanswered() == before + 1
