"""The Dividends tab: the ledger's own payments beside the estimated ones.

The arithmetic is covered offline in test_dividend_estimate; this covers what
the page does with it — that a book whose statement never carried a dividend
still gets an answer, that estimates are never mixed into the ledger's table,
and that a throttled Yahoo costs the tab its estimate and nothing else.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from yfinance.exceptions import YFRateLimitError

from stocks.data import fx
from stocks.portfolio import dividends as div
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction
from stocks.web import auth, portfolio_data

PAGE = "src/stocks/web/app_pages/portfolio.py"

TXS = [
    Transaction("2024-01-10", "KO", "buy", 100, 60.0, "USD", 1.0),
    Transaction("2024-01-10", "PG", "buy", 50, 150.0, "USD", 1.0),
    # One imported dividend, for KO only: PG's payments exist and were never
    # booked, which is the case the estimate is for.
    Transaction("2024-03-20", "KO", "dividend", 0, 48.0, "USD", 0.0),
]

# What the (stubbed) fetch would have returned for this book.
ESTIMATED = {
    2024: div.EstimatedYear(
        2024, gross=133.2, by_ticker={"KO": 43.2, "PG": 90.0}
    ),
}
FORWARD = [
    div.ForwardIncome("PG", 50.0, 4.00, 4, "USD", "2026-07-18"),
    div.ForwardIncome("KO", 100.0, 2.08, 4, "USD", "2026-06-12"),
]
TOTALS = {"PG": 180.0, "KO": 187.2}
UNRECORDED = {2024: 90.0}


@pytest.fixture
def paths(tmp_path):
    p = auth.UserPaths(
        root=tmp_path,
        watchlist=tmp_path / "watchlist.yaml",
        db=tmp_path / "portfolio.db",
        last_import=tmp_path / "last_import.json",
        prefs=tmp_path / "prefs.json",
        chat=tmp_path / "chat.json",
        bank=tmp_path / "bank.json",
        action=tmp_path / "daily_action.json",
    )
    ledger.add_many(TXS, p.db)
    return p


@pytest.fixture
def page(monkeypatch, paths):
    """The Dividends tab, signed in, with FX and every fetch stubbed."""
    monkeypatch.setattr(auth, "require_login", lambda: paths)
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "db_path", lambda: paths.db)
    monkeypatch.setattr(auth, "current_email", lambda: "me@example.com")
    monkeypatch.setattr(fx, "prefetch", lambda *a, **k: None)
    monkeypatch.setattr(
        fx, "rate_on",
        lambda day, base, quote: {("USD", "EUR"): 0.9, ("EUR", "USD"): 1 / 0.9}.get(
            (base.upper(), quote.upper()), 1.0
        ),
    )
    priced = pd.DataFrame(
        {
            "shares": [100.0],
            "ccy": ["USD"],
            "cost": [5_401.0],
            "value": [6_000.0],
            "pnl": [599.0],
            "pnl_pct": [11.0],
        },
        index=["KO"],
    )
    priced.index.name = "ticker"
    monkeypatch.setattr(portfolio_data, "positions_table", lambda *a: priced.copy())
    monkeypatch.setattr(portfolio_data, "eur_spot", lambda quote, base="EUR": 1 / 0.9)
    portfolio_data.ledger_state.clear()

    def _run(estimates=(ESTIMATED, FORWARD, TOTALS, UNRECORDED)):
        def _estimates(*_a, **_k):
            if isinstance(estimates, BaseException):
                raise estimates
            return estimates

        monkeypatch.setattr(portfolio_data, "dividend_estimates", _estimates)
        prefs = dict(auth.DEFAULT_PREFS)
        prefs["language"] = "en"
        prefs["currency"] = "EUR"
        paths.prefs.write_text(json.dumps(prefs))
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.query_params["tab"] = "dividends"
        at.run()
        assert not at.exception, at.exception
        return at

    return _run


def _text(at) -> str:
    parts = [str(e.value) for e in at.markdown] + [str(e.value) for e in at.caption]
    parts += [str(e.value) for e in at.subheader]
    parts += [str(e.value) for e in at.info] + [str(e.value) for e in at.warning]
    parts += [str(getattr(e, "body", "")) for e in at.get("html")]
    return "\n".join(parts)


def _frames(at) -> list[pd.DataFrame]:
    """Every rendered table as a plain frame (data_table styles some)."""
    return [getattr(e.value, "data", e.value) for e in at.dataframe]


def test_the_tab_shows_the_ledger_and_the_estimate_as_separate_cards(page):
    body = _text(page())
    assert "Recorded in your ledger" in body
    assert "Next 12 months, estimated" in body
    assert "What your shares were entitled to" in body


def test_the_headline_kpis_answer_all_time_this_year_and_next(page):
    body = _text(page())
    # Booked: one 48 USD dividend at 0.90. Entitled: €133 over the same span,
    # €90 of it never imported — the chip, never added into the figure.
    assert "€43" in body and "est. €133" in body
    # Next year is the loader's totals, already in the reporting currency.
    assert "€367" in body


def test_the_forward_estimate_is_shares_times_the_trailing_rate(page):
    body = _text(page())
    # €367 a year, a twelfth of it a month.
    assert "€31" in body
    assert body.index("<b>PG</b>") < body.index("<b>KO</b>")  # biggest first
    # Per-share amounts keep the company's own currency, never the report's.
    assert "$4.00" in body and "$2.08" in body


def test_every_payer_is_a_link_to_its_own_page(page):
    body = _text(page())
    # The golden rule: a symbol on screen carries its logo and opens the
    # company — the same cell the Positions table uses.
    for ticker in ("PG", "KO"):
        assert f'href="ticker?ticker={ticker}"' in body
        assert f"<b>{ticker}</b>" in body


def test_the_unrecorded_gap_is_called_out_but_kept_out_of_the_ledger_table(page):
    at = page()
    ledger_table = next(f for f in _frames(at) if "Creditable" in f.columns)
    # The ledger table is the ledger's: 48 USD at 0.90, and nothing estimated.
    assert ledger_table["Gross"].tolist() == [pytest.approx(43.2)]
    gap = next(f for f in _frames(at) if "Not recorded" in f.columns)
    assert gap["Not recorded"].tolist() == [pytest.approx(90.0)]
    assert "€90" in _text(at)


def test_a_book_with_no_imported_dividends_still_gets_an_estimate(paths, page):
    for booked in ledger.all_transactions(paths.db):
        if booked.action == "dividend":
            ledger.delete(booked.id, paths.db)
    portfolio_data.ledger_state.clear()
    body = _text(page())
    assert "no dividend rows" in body  # the estimate is not read as a receipt
    assert "Recorded in your ledger" not in body
    assert "Next 12 months, estimated" in body


def test_a_throttled_yahoo_costs_the_estimate_and_nothing_else(page):
    body = _text(page(estimates=YFRateLimitError()))
    assert "Recorded in your ledger" in body
    assert "Next 12 months, estimated" not in body

