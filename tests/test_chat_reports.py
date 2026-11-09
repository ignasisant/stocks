"""Which of my companies report soon: the calendar page's dates, on the question."""

from __future__ import annotations

from datetime import date

import pytest

from stocks.chat import reports
from stocks.data import earnings, finnhub
from stocks.data.earnings import Consensus, EarningsEvent, EarningsResult
from tests.patching import patch_loaders

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
    patch_loaders(monkeypatch, "held", lambda *_a: ("META", "BTC-EUR"))
    patch_loaders(monkeypatch, "db_mtime", lambda *_a: 0.0)
    asked: list = []

    def calendar(tickers):
        asked.append(tickers)
        return [EarningsEvent("ASML", date(2026, 11, 2)),
                EarningsEvent("META", date(2026, 11, 4)),
                EarningsEvent("NVDA", date(2026, 11, 19))], []

    patch_loaders(monkeypatch, "earnings_calendar", calendar)
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



@pytest.mark.parametrize(("said", "back", "days"), [
    ("resultados semana pasada de acciones en mi cartera", True, 7),
    ("which of my holdings reported earnings last week?", True, 7),
    ("¿qué empresas de mi cartera presentaron resultados ayer?", True, 1),
    ("resultados de mis acciones en los últimos 10 días", True, 10),
    ("¿qué empresas de mi cartera presentan resultados esta semana?", False, 7),
    ("¿mis empresas presentan resultados pasado mañana?", False, 1),
])
def test_a_window_behind_today_reads_the_prints_already_out(said, back, days):
    """Prod 2026-11-08: "resultados semana pasada…" was read fourteen days
    forward and answered that nothing had been reported."""
    assert reports.wants(said)
    assert reports.looks_back(said) is back
    assert reports.days_asked(said) == days


def test_the_prints_of_the_window_with_the_move_across_them(tmp_path, monkeypatch):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n- ticker: DUOL\n- ticker: RDDT\n"
                         "- ticker: SHOP\n- ticker: NVDA\n")
    db = tmp_path / "prices.db"
    db.touch()
    patch_loaders(monkeypatch, "held", lambda *_a: ("DUOL", "RDDT", "SHOP"))
    patch_loaders(monkeypatch, "db_mtime", lambda *_a: 0.0)
    today = date(2026, 11, 9)
    patch_loaders(monkeypatch, "earnings_calendar", lambda _t: (
        [EarningsEvent("NVDA", date(2026, 11, 19))],
        [EarningsResult("SHOP", date(2026, 11, 4), 0.33, 0.41, 24.2),
         EarningsResult("DUOL", date(2026, 11, 5), None, 1.3, None),
         EarningsResult("RDDT", date(2026, 10, 28), 0.5, 0.6, 20.0),
         EarningsResult("SHOP", date(2026, 8, 6), 0.3, 0.3, 0.0)]))
    monkeypatch.setattr(reports, "_reaction_cache", {})
    monkeypatch.setattr(reports, "_facts_cache", {})
    monkeypatch.setattr(reports, "_print_facts", lambda _t, _day: {})
    monkeypatch.setattr(earnings, "price_reaction", lambda t, _day: (
        22.1 if t == "DUOL" else None))
    behind = reports.build(watchlist, db, 7, today=today, back=True)
    assert [(p.ticker, p.days_ago) for p in behind.printed] == [
        ("DUOL", 4), ("SHOP", 5)]
    assert behind.due == ()
    line = behind.line()
    assert ("DUOL (held): 2026-11-05, 4 days ago; EPS 1.30 against no consensus "
            "on file; shares +22.1% across the print") in line
    assert ("SHOP (held): 2026-11-04, 5 days ago; EPS 0.41 against a consensus "
            "of 0.33 (surprise +24.2%); no price move on file") in line
    assert "RDDT" not in line and "NVDA" not in line
    assert "reported in the last 7 days" in line
    assert "never fill one in from memory" in line


RELEASE = (
    "EX-99.1 2 shop-ex991.htm EX-99.1 Document Shopify Q3 2026 revenue grew "
    "31% to $2.84 billion, with gross merchandise volume up 29% and free cash "
    "flow margin of 19%. " + "Merchant Solutions led the quarter. " * 12
    + "For the fourth quarter, we expect revenue to grow at a mid-twenties "
    "percentage rate, to between $3.2 and $3.3 billion.")


def test_a_print_read_back_carries_the_quarter_the_release_and_the_rules(
        tmp_path, monkeypatch):
    """Prod 2026-11-09: the reader expected each print's revenue, margin,
    outlook and release, and whether it touched the thesis they wrote; and
    named the held names with no exit rule."""
    from stocks.chat import journal

    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n- ticker: SHOP\n- ticker: BKNG\n"
                         "- ticker: NVDA\n- ticker: MNDY\n")
    db = tmp_path / "prices.db"
    db.touch()
    patch_loaders(monkeypatch, "held", lambda *_a: ("SHOP", "BKNG"))
    patch_loaders(monkeypatch, "db_mtime", lambda *_a: 0.0)
    today = date(2026, 11, 9)
    patch_loaders(monkeypatch, "earnings_calendar", lambda _t: (
        [EarningsEvent("MNDY", date(2026, 11, 9)),
         EarningsEvent("NVDA", date(2026, 11, 19))],
        [EarningsResult("SHOP", date(2026, 11, 4), 0.33, 0.41, 24.2),
         EarningsResult("BKNG", date(2026, 11, 3), 60.1, 62.0, 3.2)]))
    monkeypatch.setattr(reports, "_reaction_cache", {})
    monkeypatch.setattr(reports, "_facts_cache", {})
    monkeypatch.setattr(earnings, "price_reaction", lambda _t, _day: None)
    monkeypatch.setattr(reports, "_print_facts", lambda t, _day: {
        "SHOP": {"revenue": 2.84e9, "currency": "USD", "revenue_yoy_pct": 31.0,
                 "operating_margin_pct": 15.2, "release": RELEASE},
    }.get(t, {}))
    log = tmp_path / "journal.json"
    log.write_text("[]")
    rules = [journal.Entry(
        id="k1", type="criterion", source="chat", action="thesis",
        subject="criterion:SHOP", ticker="SHOP", state="open", day="2026-10-01",
        snapshot={"rule": "thesis",
                  "pillars": ["GMV grows over 20%", "Take rate holds"],
                  "watch": ["0:2026-11-05"]})]
    monkeypatch.setattr(journal, "load", lambda _p: rules)

    behind = reports.build(watchlist, db, 7, today=today, back=True,
                           journal=log)
    line = behind.line()
    assert ("SHOP (held): 2026-11-04, 5 days ago; EPS 0.41 against a consensus "
            "of 0.33 (surprise +24.2%); revenue 2.84B USD (+31.0% on the year); "
            "operating margin 15.2%; no price move on file") in line
    assert ('outlook in the release: "For the fourth quarter, we expect '
            "revenue to grow") in line
    assert 'release opens: "Shopify Q3 2026 revenue grew 31%' in line
    assert "EX-99.1" not in line
    assert ("exit rule: the thesis breaks: GMV grows over 20% / Take rate "
            "holds; pillar on watch since 2026-11-05: GMV grows over 20%") in line
    bkng = line.split("- BKNG (held)")[1].split("\n- ")[0]
    assert "no exit rule saved for it" in bkng
    assert "Reporting in the next 7 days: MNDY 2026-11-09 (followed)" in line
    assert "NVDA 2026-11-19" not in line
    assert "name the held names that reported with no rule saved" in line


def test_a_headline_is_not_quoted_as_the_outlook():
    """AAPL 2026-11-02: the headline ran into the dateline and read as a
    sentence about the fourth quarter, quoted twice."""
    release = ("Exhibit 99.1Apple reports fourth quarter resultsSeptember "
               "quarter records for total company revenue, iPhone revenue, and "
               "EPSServices revenue reaches new all-time highCUPERTINO — Apple "
               "today announced results for its fiscal 2026 fourth quarter.")
    p = reports.Printed("AAPL", date(2026, 11, 2), 7, True, 2.1, 2.03, 3.6,
                        facts={"release": release})
    detail = p.detail()
    assert not any(line.startswith("outlook") for line in detail)
    assert detail[0].startswith('release opens: "Apple reports fourth quarter')


def test_the_book_s_week_beside_the_index_on_the_same_money(tmp_path, monkeypatch):
    """CLAUDE.md: a book against an index runs on the same money, and also
    from the book's first day."""
    import pandas as pd

    from stocks.chat import daily_book
    from stocks.views import briefing

    days = pd.date_range(end=pd.Timestamp.today().normalize(), periods=120)
    hist = pd.DataFrame({"value": [1000.0 + i for i in range(120)],
                         "injected": [1000.0] * 120}, index=days)
    patch_loaders(monkeypatch, "history", lambda *_a: (hist, None, None))
    patch_loaders(monkeypatch, "db_mtime", lambda *_a: 0.0)
    monkeypatch.setattr(briefing, "closes_since", lambda _first: {})
    monkeypatch.setattr(daily_book, "index_in_currency",
                        lambda _c, _ccy: pd.Series(500.0, index=days))
    db = tmp_path / "prices.db"
    db.touch()
    book = reports._book(db, "EUR", 7)
    assert [r[0] for r in book.rows] == [7, 30, 119]
    assert book.since == days[0].date().isoformat()
    line = book.line()
    assert "- the book over the last 7 days: +0.6" in line
    assert "+7 EUR" in line
    assert f"- the book since the book's first day ({book.since}): +11.90%" in line
    assert line.count("the S&P 500 bought with the same money: +0.00%") == 3


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
