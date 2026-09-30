"""A sale that has not happened, run through the tax engine.

The figures are the Tax tab's own — the ledger replayed under the account's
jurisdiction, with and without one more sale today — so what is tested here
is that the scenario is that difference and nothing invented: the gain of the
lots the rule says go first, and this year's estimate moving by the tax on it.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from stocks.chat import a2ui, whatif
from stocks.portfolio.ledger import Transaction, add_many

TODAY = date(2026, 9, 29)
PRICE = (150.0, "EUR")


@pytest.fixture
def book(tmp_path):
    db = tmp_path / "portfolio.db"
    prefs = tmp_path / "prefs.json"
    prefs.write_text(json.dumps({"tax_residence": "ES"}))
    add_many([
        Transaction("2025-01-02", "AAPL", "buy", 10, 100.0, "EUR"),
        Transaction("2025-06-02", "AAPL", "buy", 10, 120.0, "EUR"),
    ], db)
    return db, prefs


def _sale(book, **kw):
    db, prefs = book
    return whatif.simulate(db=db, prefs_path=prefs, ticker="aapl", price=PRICE,
                           today=TODAY, **kw)


def test_selling_everything_is_the_whole_holding_at_today_s_price(book):
    sale = _sale(book)
    assert (sale.ticker, sale.held, sale.shares) == ("AAPL", 20.0, 20.0)
    assert sale.proceeds == pytest.approx(3000.0)
    assert sale.gain == pytest.approx(3000.0 - 2200.0)
    assert sale.tax_before == 0
    # Spain's savings base: 19% on the first 6,000.
    assert sale.extra_tax == pytest.approx(800.0 * 0.19)
    assert (sale.currency, sale.jurisdiction, sale.year) == ("EUR", "ES", "2026")


def test_part_of_a_holding_sells_the_lots_the_rule_says_go_first(book):
    """Spain is FIFO: ten shares sold are the ten bought at 100."""
    sale = _sale(book, shares=10)
    assert sale.gain == pytest.approx(500.0)
    assert sale.extra_tax == pytest.approx(95.0)


def test_a_count_is_asked_with_the_holding_s_size(book):
    sale = _sale(book, shares=lambda held: whatif.shares_asked("vendo la mitad", held))
    assert sale.shares == 10.0


def test_nothing_held_is_nothing_to_simulate(book):
    db, prefs = book
    assert whatif.simulate(db=db, prefs_path=prefs, ticker="MSFT", price=PRICE) is None


def test_more_than_is_held_sells_what_is_held(book):
    assert _sale(book, shares=500).shares == 20.0


@pytest.mark.parametrize(("said", "wants"), [
    ("¿Cuánto pagaría si vendo mis AAPL?", True),
    ("y si vendiera la mitad", True),
    ("what if I sell half my NVDA", True),
    ("should I trim Apple?", True),
    ("¿cómo va AAPL hoy?", False),
    ("the vendor reported earnings", False),
])
def test_only_a_sale_being_contemplated_opens_one(said, wants):
    assert whatif.wants(said) is wants


@pytest.mark.parametrize(("said", "shares"), [
    ("vendo 5 acciones", 5.0),
    ("sell 2.5 shares", 2.5),
    ("vendo la mitad", 10.0),
    ("vendo 400 acciones", 20.0),
    ("vendo todo", 20.0),
])
def test_how_many_is_read_off_the_message(said, shares):
    assert whatif.shares_asked(said, 20.0) == shares


def test_the_surface_is_a_slider_over_the_holding_with_three_figures(book):
    messages = whatif.surface(_sale(book, shares=10), lambda key, **kw: key)
    a2ui.check(messages)
    parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    slider = parts["shares"]
    assert (slider["min"], slider["max"], slider["step"]) == (0, 20.0, 1)
    assert slider["action"]["event"]["name"] == whatif.ACTION
    assert slider["action"]["event"]["context"]["shares"] == {"path": "/shares"}
    assert parts["ticker"] == {"id": "ticker", "component": "Ticker", "symbol": "AAPL"}
    data = messages[-1]["updateDataModel"]["value"]
    assert data["shares"] == 10.0
    assert data["view"]["gain"] == "+€500" and data["view"]["tax"] == "+€95"


def test_the_prompt_line_carries_the_engine_s_figures(book):
    line = _sale(book, shares=10).line()
    assert "tax engine" in line
    assert "+500.00 EUR" in line and "+95.00 EUR" in line
