"""The request-saving paths behind the page loaders.

Each of these exists to keep a page from asking Yahoo twice for one fact:
the profile memo (a holding's sector never changes), the shared ledger-span
download and its slices, and the earnings fetch that only pays for `calendar`
when the dates table lacks an upcoming row.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from stocks.analysis import portfolio as ap
from stocks.data import fetch, profiles
from stocks.web import portfolio_data as pdata


@pytest.fixture(autouse=True)
def _isolated_memo(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILE_CACHE", tmp_path / "profiles.json")
    profiles.clear()
    yield
    profiles.clear()


# ------------------------------------------------------------------ profiles
def test_remember_keeps_only_the_fixed_fields_and_survives_a_reload(tmp_path):
    profiles.remember("AAPL", {
        "sector": "Technology", "country": "United States", "currency": "USD",
        "quoteType": "EQUITY", "regularMarketPrice": 231.4, "marketCap": 3e12,
    })
    profiles.clear()  # the next read comes from disk
    assert profiles.known("aapl") == {
        "sector": "Technology", "country": "United States",
        "currency": "USD", "quoteType": "EQUITY",
    }


def test_a_stub_blob_without_a_quote_type_is_not_remembered():
    profiles.remember("ZZZZ", {"sector": "?"})
    profiles.remember("YYYY", None)
    assert profiles.known("ZZZZ") is None and profiles.known("YYYY") is None


def test_fetch_info_feeds_the_memo(monkeypatch):
    class _T:
        def __init__(self, sym):
            self.sym = sym

        @property
        def info(self):
            return {"quoteType": "EQUITY", "sector": "Energy", "country": "Norway",
                    "currency": "NOK", "regularMarketPrice": 1.0}

    monkeypatch.setattr(fetch.yf, "Ticker", _T)
    fetch.clear_info_cache()
    fetch.info("EQNR.OL")
    assert profiles.known("EQNR.OL")["sector"] == "Energy"


def test_a_known_stock_costs_no_info_request(monkeypatch):
    profiles.remember("MSFT", {"quoteType": "EQUITY", "sector": "Technology",
                               "country": "United States", "currency": "USD"})
    calls = []
    monkeypatch.setattr(fetch, "info", lambda t: calls.append(t) or {})
    assert ap._profile("MSFT") == {
        "sector": "Technology", "country": "United States", "currency": "USD",
    }
    assert calls == []


def test_a_known_fund_still_fetches_its_look_through(monkeypatch):
    """A fund's split is what it holds, which `.info` alone does not carry —
    the memo must not short-circuit that path."""
    profiles.remember("SPY", {"quoteType": "ETF", "currency": "USD"})
    calls = []
    monkeypatch.setattr(fetch, "info", lambda t: calls.append(t) or {"quoteType": "ETF"})
    monkeypatch.setattr("stocks.data.funds.fetch_profile", lambda t, info=None: None)
    ap._profile("SPY")
    assert calls == ["SPY"]


# ------------------------------------------------------------- shared closes
def _series(days: int, tz: str | None = None) -> pd.Series:
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days, tz=tz)
    return pd.Series(range(1, days + 1), index=idx, dtype=float)


def test_ledger_period_widens_with_the_span():
    today = date.today()
    assert pdata.ledger_period((today - timedelta(days=100)).isoformat()) == "2y"
    assert pdata.ledger_period((today - timedelta(days=1000)).isoformat()) == "5y"
    assert pdata.ledger_period((today - timedelta(days=3000)).isoformat()) == "max"


def test_window_slices_the_tail_whatever_the_timezone():
    closes = {"A": _series(600), "B": _series(600, tz="America/New_York")}
    out = pdata._window(closes, 3)
    for s in out.values():
        assert 55 <= len(s) <= 70  # ~3 months of sessions
        assert s.iloc[-1] == 600.0  # the latest bar survives


def test_window_drops_a_series_with_nothing_in_range():
    old = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp("2015-01-02")]))
    assert pdata._window({"OLD": old}, 3) == {}


def test_year_closes_takes_held_names_from_the_book_download(monkeypatch):
    asked: list[tuple] = []
    monkeypatch.setattr(pdata, "held_closes", lambda db, mtime: {"AAPL": _series(600)})
    monkeypatch.setattr(
        pdata, "watchlist_closes",
        lambda tickers: asked.append(tickers) or {t: [1.0, 2.0] for t in tickers},
    )
    out = pdata.year_closes(("AAPL", "NVDA", "SAP"), "book.db", 1.0)
    assert asked == [("NVDA", "SAP")]  # the held name never reaches Yahoo twice
    assert 240 <= len(out["AAPL"]) <= 265 and out["AAPL"][-1] == 600.0
    assert out["NVDA"] == [1.0, 2.0]


def test_year_closes_for_a_guest_is_the_watchlist_download_alone(monkeypatch):
    monkeypatch.setattr(
        pdata, "held_closes", lambda db, mtime: pytest.fail("no ledger for a guest")
    )
    monkeypatch.setattr(
        pdata, "watchlist_closes", lambda tickers: {t: [3.0] for t in tickers}
    )
    assert pdata.year_closes(("AAPL",), None) == {"AAPL": [3.0]}


def test_position_value_frames_accepts_closes_and_skips_the_download(monkeypatch):
    from stocks.portfolio.positions import Position

    monkeypatch.setattr(ap, "load_closes", lambda *a, **k: pytest.fail("downloaded"))
    pos = [Position(ticker="AAPL", quantity=2.0, cost=100.0, cost_native=100.0,
                    currency="EUR")]
    values, frozen = ap.position_value_frames(pos, "3mo", "EUR",
                                              closes={"AAPL": _series(10)})
    assert list(values["AAPL"]) == [2.0 * v for v in range(1, 11)]
    assert frozen.equals(values)


# ------------------------------------------------------------------ earnings
class _FakeYf:
    def __init__(self, rows: list[date]):
        self.rows = rows
        self.calendar_reads = 0

    def Ticker(self, symbol):  # noqa: N802 — yfinance's name
        outer = self

        class _T:
            def get_earnings_dates(self, limit=12):
                idx = pd.DatetimeIndex([pd.Timestamp(d) for d in outer.rows])
                return pd.DataFrame({"EPS Estimate": 1.0, "Reported EPS": 1.1,
                                     "Surprise(%)": 10.0}, index=idx)

            @property
            def calendar(self):
                outer.calendar_reads += 1
                return {"Earnings Date": [date.today() + timedelta(days=30)]}

        return _T()


def test_the_calendar_is_not_asked_when_the_table_has_an_upcoming_row(monkeypatch):
    from stocks.data import earnings

    fake = _FakeYf([date.today() + timedelta(days=12), date.today() - timedelta(days=80)])
    monkeypatch.setattr("yfinance.Ticker", fake.Ticker)
    monkeypatch.setattr("stocks.data.funds.is_fund", lambda t, fetch=True: False)
    dates, _ = earnings.fetch_earnings("AAPL")
    assert fake.calendar_reads == 0
    assert date.today() + timedelta(days=12) in dates


def test_the_calendar_fills_in_when_the_table_only_has_the_past(monkeypatch):
    from stocks.data import earnings

    fake = _FakeYf([date.today() - timedelta(days=80)])
    monkeypatch.setattr("yfinance.Ticker", fake.Ticker)
    monkeypatch.setattr("stocks.data.funds.is_fund", lambda t, fetch=True: False)
    dates, _ = earnings.fetch_earnings("AAPL")
    assert fake.calendar_reads == 1
    assert date.today() + timedelta(days=30) in dates
