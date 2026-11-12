"""A name the model gave a row, held to the prices the row traded at.

The verdict is pure and tested as one: closes, the dollar rate and the splits
are handed in. What the preview and `/import/ticker` add on top is tested with
the other import routes (tests/test_api_import.py).
"""

from __future__ import annotations

import pytest

from stocks import obs
from stocks.api.routes.import_statement import doubts
from stocks.api.routes.import_statement.doubts import Doubt, verdict
from stocks.data import fetch, fx
from stocks.portfolio import consistency
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.validate import Checked

# The real one, held before the suite's conftest swaps it out for every test.
_real_find = doubts.find

DAY, EARLIER = "2025-03-03", "2025-02-03"


def asked(ticker, currency, fills, closes, *, rates=None, splits=()):
    return verdict(
        ticker,
        currency,
        fills,
        close=lambda symbol, day: closes.get((symbol, day)),
        usd_rate=lambda cur, day: (rates or {}).get(cur),
        splits=lambda symbol: list(splits),
    )


def test_a_fill_near_its_close_is_no_doubt():
    assert asked("MU", "USD", [(DAY, 92.0)], {("MU", DAY): 95.0}) is None


def test_a_fill_nowhere_near_its_close_is_one():
    """Micron bought near 95 and read as American Tower, which closed at 210."""
    found = asked("AMT", "USD", [(DAY, 95.0)], {("AMT", DAY): 210.0})
    assert found == Doubt(day=DAY, off=0.452)


def test_one_day_that_agrees_clears_the_name():
    """A flash print or a bad close on one day is not another company."""
    closes = {("MU", DAY): 200.0, ("MU", EARLIER): 90.0}
    assert asked("MU", "USD", [(DAY, 95.0), (EARLIER, 91.0)], closes) is None


def test_a_name_nobody_priced_is_not_doubted():
    assert asked("MU", "USD", [(DAY, 95.0)], {}) is None


def test_a_bare_line_is_read_in_the_rows_currency():
    closes = {("MU", DAY): 100.0, ("AMT", DAY): 210.0}
    rates = {"EUR": 0.9}
    assert asked("MU", "EUR", [(DAY, 88.0)], closes, rates=rates) is None
    found = asked("AMT", "EUR", [(DAY, 88.0)], closes, rates=rates)
    assert found == Doubt(day=DAY, off=round(88.0 / 189.0, 3))


def test_a_bare_line_without_a_rate_is_not_doubted():
    assert asked("AMT", "EUR", [(DAY, 88.0)], {("AMT", DAY): 210.0}) is None


def test_a_line_of_another_currencys_venues_is_not_compared():
    """A London line under euro fills: the gap would be the exchange rate's."""
    assert asked("SHEL.L", "EUR", [(DAY, 30.0)], {("SHEL.L", DAY): 2600.0}) is None
    found = asked("MRL.MC", "EUR", [(DAY, 30.0)], {("MRL.MC", DAY): 12.0})
    assert found == Doubt(day=DAY, off=2.5)


@pytest.mark.parametrize(
    ("fill", "splits"),
    [
        pytest.param(1200.0, [("2025-06-10", 10.0)], id="one-split-since"),
        pytest.param(6000.0, [("2025-06-10", 10.0), ("2026-01-05", 5.0)], id="two"),
        pytest.param(
            600.0, [("2025-06-10", 10.0), ("2026-01-05", 5.0)], id="one-restated"
        ),
        pytest.param(12.0, [("2025-06-10", 0.1)], id="reverse"),
    ],
)
def test_a_gap_the_size_of_a_later_split_is_the_splits(fill, splits):
    closes = {("NVDA", DAY): 120.0}
    assert asked("NVDA", "USD", [(DAY, fill)], closes, splits=splits) is None


def test_a_split_before_the_trade_explains_nothing():
    closes = {("NVDA", DAY): 120.0}
    found = asked("NVDA", "USD", [(DAY, 1200.0)], closes, splits=[("2024-06-10", 10.0)])
    assert found == Doubt(day=DAY, off=10.0)


def test_pence_for_pounds_is_not_another_company():
    assert asked("AMT", "USD", [(DAY, 21000.0)], {("AMT", DAY): 210.0}) is None


# ------------------------------------------------------- over a statement


def row(ticker="AMT", price=95.0, action="buy", currency="USD", day=DAY) -> Checked:
    return Checked(tx=Transaction(day, ticker, action, 3, price, currency, 0.0))


@pytest.fixture
def market(monkeypatch):
    """A Yahoo with AMT at 210 and MU at 95 on DAY, and nothing else."""
    closes = {("AMT", DAY): 210.0, ("MU", DAY): 95.0}
    seen: list[str] = []

    def close_on(symbol, day):
        seen.append(symbol)
        return closes.get((symbol, day))

    monkeypatch.setattr(doubts, "find", _real_find)
    monkeypatch.setattr(fetch, "close_on", close_on)
    monkeypatch.setattr(fetch, "splits", lambda ticker: [])
    monkeypatch.setattr(fetch, "throttle_remaining", lambda: 0)
    monkeypatch.setattr(fx, "rate_on", lambda day, base, quote: 1.0)
    return seen


@pytest.fixture
def lines(monkeypatch) -> list[dict]:
    said: list[dict] = []

    def warn(name, **fields):
        if name == consistency.EVENT:
            said.append(fields)

    monkeypatch.setattr(obs, "warn", warn)
    return said


def test_the_doubted_rows_are_warned_and_the_doubt_is_logged(market, lines):
    rows = [row(), row("MU"), row(action="dividend", price=0.0)]
    with obs.context(user="doubt-logged"):
        assert doubts.flag(rows) == ["AMT"]
    warned, fine, payout = rows
    assert [(i.severity, i.field, i.key) for i in warned.issues] == [
        ("warning", "ticker", "validate.ticker_doubt")
    ]
    assert warned.issues[0].params == {"ticker": "AMT", "date": DAY}
    assert not fine.issues and not payout.issues
    assert lines == [
        {
            "kind": "ticker_doubt",
            "source": "import",
            "ticker": "AMT",
            "traded": DAY,
            "off": 0.452,
        }
    ]


def test_what_cannot_be_priced_is_not_asked(market):
    rows = [
        row("BTC-EUR", 50000.0, currency="EUR"),
        row("US5951121038"),
        row("AMT", 0.0),
        row("AMT", action="dividend"),
    ]
    assert doubts.flag(rows) == []
    assert market == []


def test_a_throttled_yahoo_is_asked_nothing(market, monkeypatch):
    monkeypatch.setattr(fetch, "throttle_remaining", lambda: 30)
    rows = [row()]
    assert doubts.flag(rows) == []
    assert market == [] and not rows[0].issues


def test_a_lookup_that_breaks_doubts_nothing(market, monkeypatch):
    def broken(symbol, day):
        raise RuntimeError("yahoo")

    monkeypatch.setattr(fetch, "close_on", broken)
    assert doubts.flag([row()]) == []


def test_a_statement_is_priced_for_so_many_names(market, monkeypatch):
    monkeypatch.setattr(doubts, "DOUBT_MAX", 1)
    # Both are far from their closes; only the first name is priced at all.
    assert doubts.flag([row("MU", 10.0), row("AMT")]) == ["AMT"]
    assert set(market) == {"AMT"}
