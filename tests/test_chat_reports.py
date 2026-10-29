"""Which of my companies report soon: the calendar page's dates, on the question."""

from __future__ import annotations

from datetime import date

import pytest

from stocks.api import loaders
from stocks.chat import reports
from stocks.data import earnings, finnhub
from stocks.data.earnings import Consensus, EarningsEvent

TODAY = date(2026, 10, 29)


@pytest.mark.parametrize(("said", "wants"), [
    ("¿Qué empresas de mi cartera presentan resultados en 7 días?", True),
    ("which of my holdings report earnings next week?", True),
    ("¿cuándo presentan resultados mis acciones?", True),
    ("¿qué tal los resultados de Meta?", False),
    ("¿cuándo presenta resultados NVDA?", False),
    ("¿cómo está repartida mi cartera?", False),
])
def test_only_the_reader_s_own_calendar_opens_one(said, wants):
    assert reports.wants(said) is wants


@pytest.mark.parametrize(("said", "days"), [
    ("en 7 días", 7), ("en las próximas 2 semanas", 14), ("esta semana", 7),
    ("next 3 months", 90), ("mañana", 1), ("pronto", reports.DEFAULT_DAYS),
    ("en 999 días", reports.MAX_DAYS),
])
def test_the_window_is_the_one_asked(said, days):
    assert reports.days_asked(said) == days


def test_dates_of_held_and_followed_names_inside_the_window(tmp_path, monkeypatch):
    """Local review 2026-10-29: "dime qué tickers tienes", with the book and
    the calendar both in the app."""
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n- ticker: META\n- ticker: ASML\n"
                         "- ticker: BTC-EUR\n- ticker: NVDA\n")
    db = tmp_path / "prices.db"
    db.touch()
    monkeypatch.setattr(loaders, "held", lambda *_a: ("META", "BTC-EUR"))
    monkeypatch.setattr(loaders, "db_mtime", lambda *_a: 0.0)
    asked: list = []

    def calendar(tickers):
        asked.append(tickers)
        return [EarningsEvent("ASML", date(2026, 11, 2)),
                EarningsEvent("META", date(2026, 11, 4)),
                EarningsEvent("NVDA", date(2026, 11, 19))], []

    monkeypatch.setattr(loaders, "earnings_calendar", calendar)
    monkeypatch.setattr(reports, "_consensus_cache", {})
    monkeypatch.setattr(earnings, "consensus", lambda t, _day: (
        Consensus(7.12, 4.5e10, "amc") if t == "META" else None))
    ahead = reports.build(watchlist, db, 7, today=TODAY)
    assert asked == [("ASML", "META", "NVDA")]
    assert [(d.ticker, d.in_days, d.held) for d in ahead.due] == [
        ("ASML", 4, False), ("META", 6, True)]
    assert ahead.skipped == ("BTC-EUR",)
    line = ahead.line()
    assert ("META (held): 2026-11-04, in 6 days; after the close, consensus "
            "EPS 7.12, revenue 45.00B") in line
    assert ("ASML (followed, not held): 2026-11-02, in 4 days; "
            "no consensus on file") in line
    assert "never fill one in from memory" in line
    assert "do not ask the reader which tickers" in line
    assert "NVDA" not in line.split("\n- left out")[0].split(":\n", 1)[1]



def test_the_consensus_is_the_window_s_row_for_that_print(monkeypatch):
    """Local review 2026-10-30: RDDT quoted at 312 M$ of revenue, a 2024
    quarter, against an 875 M$ consensus."""
    monkeypatch.setattr(earnings, "_window_symbol", lambda t: t)
    monkeypatch.setattr(finnhub, "earnings_window", lambda ref=None: {"RDDT": [
        {"date": "2026-07-30", "epsEstimate": 1.1, "revenueEstimate": 6e8},
        {"date": "2026-10-30", "epsEstimate": 1.95, "revenueEstimate": 8.75e8,
         "hour": "amc"}]})
    got = earnings.consensus("RDDT", date(2026, 10, 30))
    assert got == Consensus(1.95, 8.75e8, "amc")


def test_yahoo_s_estimates_count_only_for_the_date_it_gives(monkeypatch):
    import yfinance as yf

    monkeypatch.setattr(earnings, "_window_symbol", lambda _t: None)
    monkeypatch.setattr(earnings, "resolve", lambda t: t)

    class Ticker:
        def __init__(self, _s):
            # Outside a season the calendar still shows the last print.
            self.calendar = {"Earnings Date": [date(2026, 10, 14)],
                             "Earnings Average": 15.39, "Revenue Average": 1.48e10}

    monkeypatch.setattr(yf, "Ticker", Ticker)
    assert earnings.consensus("ASML.AS", date(2026, 10, 15)) == Consensus(15.39, 1.48e10)
    assert earnings.consensus("ASML.AS", date(2027, 1, 20)) is None


# ------------------------------------------------------------------ dividends

from stocks.chat import income  # noqa: E402
from stocks.portfolio.ledger import Transaction  # noqa: E402


@pytest.mark.parametrize(("said", "wants"), [
    ("Dividendos netos y doble imposición deducible", True),
    ("¿cuánto he cobrado en dividendos este año?", True),
    ("my dividend income", True),
    ("¿qué es un dividendo?", False),
])
def test_only_the_reader_s_dividends_open_the_income(said, wants):
    assert income.wants(said) is wants


def test_dividend_years_carry_the_spanish_credit(tmp_path, monkeypatch):
    """Local review 2026-10-29: "No tengo acceso a tu información personal",
    with every dividend row in the ledger."""
    from stocks.portfolio import ledger

    db = tmp_path / "prices.db"
    db.touch()
    rows = [
        Transaction(date="2026-03-10", ticker="MSFT", action="dividend",
                    quantity=0, price=100.0, fee=30.0, currency="EUR"),
        Transaction(date="2026-06-10", ticker="KO", action="dividend",
                    quantity=0, price=50.0, fee=0.0, currency="USD"),
    ]
    monkeypatch.setattr(ledger, "all_transactions", lambda _db: rows)
    from stocks.portfolio import dividends

    monkeypatch.setattr(dividends, "prefetch", lambda _pairs: None)
    monkeypatch.setattr(dividends, "converter", lambda _base: (lambda a, c, d: a))
    found = income.build(db, None, today=TODAY)
    (year,) = found.years
    assert (year.gross, year.withheld, year.unreported) == (150.0, 30.0, 1)
    assert year.creditable == pytest.approx(22.5)  # 15 % of the gross
    line = found.line()
    assert "net received 120.00 EUR" in line and "art. 80 LIRPF" in line
    assert "statement did not report it" in line
