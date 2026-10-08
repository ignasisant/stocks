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


# ------------------------------------------------------------- one per process
def test_a_range_of_fx_rates_is_one_request_per_process(monkeypatch):
    """`book_history` asks for the same span every time a book is repriced;
    a range that ends today is the same answer until tomorrow."""
    from stocks.data import fx

    fx._range_memo.clear()
    calls: list[str] = []
    monkeypatch.setattr(
        fx,
        "get_json",
        lambda url, timeout=30: calls.append(url)
        or {"rates": {"2024-01-02": {"USD": 1.1}}},
    )
    first = fx.rates_range("2024-01-01", "2024-01-05", "EUR", "USD")
    assert first == {"2024-01-02": 1.1}
    assert fx.rates_range("2024-01-01", "2024-01-05", "EUR", "USD") is first
    assert len(calls) == 1
    fx.rates_range("2024-01-01", "2024-01-06", "EUR", "USD")  # another span
    assert len(calls) == 2
    fx._range_memo.clear()


def test_daily_labels_under_a_year_share_one_bars_download(monkeypatch):
    """1m, 3m, 6m and 1y are one 2y/1d frame cut four ways; the memo has to
    key on the download, or flipping through them is four fetches."""
    from stocks.api import loaders

    loaders.price_bars.cache_clear()
    calls: list[tuple[str, str]] = []
    idx = pd.date_range("2022-01-03", periods=520, freq="B", tz="America/New_York")
    frame = pd.DataFrame({"Close": range(520)}, index=idx)
    monkeypatch.setattr(
        loaders,
        "bars_download",
        lambda t, period, interval: calls.append((period, interval)) or frame,
    )
    month = loaders.price_bars("AAPL", "1m")
    year = loaders.price_bars("AAPL", "1y")
    assert calls == [("2y", "1d")]
    assert 0 < len(month) < len(year) and month.index.tz is None
    loaders.price_bars("AAPL", "5y")
    assert calls == [("2y", "1d"), ("10y", "1d")]
    loaders.price_bars.cache_clear()


def test_the_book_downloads_once_for_its_adjusted_and_printed_closes(
    tmp_path, monkeypatch
):
    """`Adj Close` and `Close` come out of one unadjusted request; the two
    memos read their own column of it."""
    from stocks.api import loaders
    from stocks.data import fetch as data_fetch
    from stocks.portfolio import ledger
    from stocks.portfolio.ledger import Transaction

    db = tmp_path / "portfolio.db"
    ledger.add_many(
        [
            Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0),
            Transaction("2024-02-01", "MSFT", "buy", 5, 200.0, "EUR", 1.0),
        ],
        path=db,
    )
    days = pd.bdate_range("2024-01-02", periods=300)
    calls: list[tuple[str, ...]] = []

    def download(tickers, period="1y", interval="1d", auto_adjust=True, budget=60.0, **_):
        calls.append(tuple(tickers))
        assert auto_adjust is False
        return {
            "AAPL": pd.DataFrame({"Close": 100.0, "Adj Close": 95.0}, index=days),
            "MSFT": pd.DataFrame({"Close": 200.0, "Adj Close": 190.0}, index=days),
        }

    monkeypatch.setattr(data_fetch, "fetch_many", download)
    loaders.held_closes.cache_clear()
    adjusted = loaders.held_closes(str(db), 1.0)
    printed = loaders.held_printed_closes(str(db), 1.0)
    assert calls == [("AAPL", "MSFT")]
    assert float(adjusted["AAPL"].iloc[-1]) == 95.0
    assert float(printed["AAPL"].iloc[-1]) == 100.0
    loaders.held_closes.cache_clear()
    loaders.held_closes(str(db), 1.0)
    assert len(calls) == 2, "clearing the adjusted memo drops the download too"
    loaders.held_closes.cache_clear()


def test_home_reads_held_names_off_the_book_download(monkeypatch):
    """The watchlist's year asks Yahoo only for the names the ledger does not
    hold; a held name's twelve months are sliced from the book's own frames."""
    from stocks.api import home, loaders

    days = pd.bdate_range("2022-01-03", periods=700)
    book = {"AAPL": pd.Series(range(700), index=days, dtype=float)}
    asked: list[tuple[str, ...]] = []

    def watchlist(tickers):
        asked.append(tickers)
        return {t: pd.Series([1.0, 2.0]) for t in tickers}

    monkeypatch.setattr(loaders, "held_printed_closes", lambda db, mtime: book)
    monkeypatch.setattr(loaders, "watchlist_closes", watchlist)
    year = home.year_closes(("AAPL", "MSFT", "NVDA"), "book.db", 1.0)
    assert asked == [("MSFT", "NVDA")]
    assert 250 <= len(year["AAPL"]) <= 265 and year["AAPL"][-1] == 699.0
    assert year["MSFT"] == [1.0, 2.0]
    # No book at all — a guest — is the watchlist download alone.
    asked.clear()
    home.year_closes(("AAPL",), None)
    assert asked == [("AAPL",)]
