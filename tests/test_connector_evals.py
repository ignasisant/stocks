"""The connector answered the way an investor would check it: thirteen questions
with an answer that can be worked out by hand.

`test_connector_tools.py` proves each tool reaches its route and refuses what
it should. This file is the other half, an eval that runs in CI: the fixture
book is three trades (10 AAPL at 100 with a 2.00 fee, 5 at 110 with a 1.00 fee,
4 sold at 130 with a 1.50 fee, all EUR) and every assertion below is that
book's arithmetic, written out, so a wrong figure fails on the number and
not on a shape. A tool that drifts — a fee counted twice, a lot matched in
the wrong order, a tax rate off — breaks a question here before a user asks
Claude the same one.

Prices are offline (`_offline_prices`); the one priced table is the test's
own, 11 shares at 120.
"""

# ruff: noqa: F811 — the fixtures below are imported by name, as the other
# modules sharing a fixture file do.
from __future__ import annotations

import pandas as pd
import pytest

from stocks.api import loaders
from tests.test_connector_tools import (  # noqa: F401 — fixtures by name
    _offline_prices,
    book,
    call,
    ok,
    site,
    token,
)

# The book, worked out once.
BOUGHT = 10 * 100.0 + 5 * 110.0  # 1550 of stock
SOLD = 4 * 130.0  # 520 of stock
FEES = 2.0 + 1.0 + 1.5
HELD = 10 + 5 - 4  # 11 shares
# FIFO: the 4 sold come from the first lot, carrying 4/10 of its fee.
SOLD_COST = 4 * 100.0 + 2.0 * 4 / 10  # 400.80
SOLD_PROCEEDS = SOLD - 1.5  # 518.50
GAIN = SOLD_PROCEEDS - SOLD_COST  # 117.70
# Spain's savings base, first bracket.
ES_RATE = 0.19


@pytest.fixture
def priced(monkeypatch):
    """Today's price for the 11 shares: 120, so the open position is worth
    1320 against a FIFO cost of 6 x 100 + 5 x 110 = 1150 (fees aside)."""
    table = pd.DataFrame(
        {
            "shares": [11.0],
            "ccy": ["EUR"],
            "cost": [1150.0],
            "value": [1320.0],
            "pnl": [170.0],
            "pnl_pct": [170 / 1150],
        },
        index=pd.Index(["AAPL"], name="ticker"),
    )
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)


def test_how_much_is_the_book_worth(site, token, priced):
    data = ok(call(site, token, "portfolio_overview"))
    summary = data["summary"]
    assert summary["base"] == "EUR"
    assert summary["positions"] == 1 and summary["unpriced"] == 0
    assert (summary["cost"], summary["value"], summary["pnl"]) == (1150.0, 1320.0, 170.0)
    assert summary["pnl_pct"] == pytest.approx(170 / 1150)
    # What was already banked, and what it cost.
    assert summary["realized"] == pytest.approx(GAIN)
    assert summary["realized_cost"] == pytest.approx(SOLD_COST)


def test_how_many_shares_are_held_and_where(site, token, priced):
    data = ok(call(site, token, "list_positions"))
    [position] = data["positions"]
    assert position["ticker"] == "AAPL" and position["shares"] == HELD
    assert position["price"] == 120.0 and position["weight"] == 1.0
    [custody] = position["custody"]
    assert (custody["broker"], custody["shares"], custody["share"]) == ("t", 11.0, 1.0)


def test_what_did_the_sale_bring_in(site, token):
    data = ok(call(site, token, "list_transactions", action="sell"))
    assert data["total"] == 1
    [row] = data["transactions"]
    assert (row["date"], row["quantity"], row["price"]) == ("2024-03-01", 4.0, 130.0)
    assert row["amount"] == pytest.approx(SOLD_PROCEEDS)


def test_the_ledger_can_be_asked_by_name_and_by_date(site, token):
    assert ok(call(site, token, "list_transactions", ticker="aapl"))["total"] == 3
    since = ok(call(site, token, "list_transactions", date_from="2024-02-01"))
    assert [r["date"] for r in since["transactions"]] == ["2024-03-01", "2024-02-01"]
    assert ok(call(site, token, "list_transactions", ticker="MSFT"))["total"] == 0


def test_what_did_trading_cost(site, token):
    fees = ok(call(site, token, "income_report"))["fees"]
    assert fees["explicit"] == pytest.approx(FEES)
    assert fees["volume"] == pytest.approx(BOUGHT + SOLD)
    assert fees["cost_pct"] == pytest.approx(FEES / (BOUGHT + SOLD))
    [broker] = fees["brokers"]
    assert (broker["broker"], broker["trades"]) == ("t", 3)
    assert broker["commission"] == pytest.approx(FEES)


def test_no_dividend_was_ever_paid(site, token):
    dividends = ok(call(site, token, "income_report"))["dividends"]
    assert dividends["years"] == [] and dividends["booked_total"] == 0.0


def test_what_tax_does_the_sale_owe(site, token):
    """Spain by default, FIFO, and the gain taxed at the first savings bracket."""
    data = ok(call(site, token, "tax_report"))
    assert (data["jurisdiction"], data["matching"], data["currency"]) == (
        "ES", "fifo", "EUR")
    [year] = data["years"]
    assert year["period"] == "2024"
    assert year["realized_gain"] == pytest.approx(GAIN)
    assert year["realized_loss"] == 0.0 and year["dividends"] == 0.0
    assert year["net_taxable"] == pytest.approx(GAIN)
    assert year["estimated_tax"] == pytest.approx(GAIN * ES_RATE)
    [sale] = data["sales"]
    assert (sale["buy_date"], sale["sell_date"], sale["quantity"]) == (
        "2024-01-02", "2024-03-01", 4.0)
    assert sale["cost"] == pytest.approx(SOLD_COST)
    assert sale["proceeds"] == pytest.approx(SOLD_PROCEEDS)
    assert sale["gain"] == pytest.approx(GAIN)
    assert sale["matched"] == "fifo" and sale["term"] is None


def test_what_would_selling_five_more_cost_in_tax(site, token):
    """FIFO again: the next five come off the first lot's six left, at 100
    plus their share of its fee (0.20 each)."""
    data = ok(call(site, token, "simulate_sale", ticker="AAPL", shares=5,
                   price=150, currency="EUR"))
    cost = 5 * (100.0 + 2.0 / 10)
    assert (data["held"], data["shares"], data["proceeds"]) == (11.0, 5.0, 750.0)
    assert data["gain"] == pytest.approx(750.0 - cost)
    assert data["tax_before"] == 0.0
    assert data["tax_after"] == pytest.approx((750.0 - cost) * ES_RATE)
    assert data["extra_tax"] == pytest.approx(data["tax_after"])
    assert data["jurisdiction"] == "ES"


def test_how_much_money_went_in(site, token, priced):
    """Cash in minus cash out: both buys with their fees, less the sale net."""
    perf = ok(call(site, token, "portfolio_performance"))["performance"]
    injected = (1000.0 + 2.0) + (550.0 + 1.0) - SOLD_PROCEEDS
    assert perf["injected"] == pytest.approx(injected)
    assert perf["value"] == 1320.0
    assert perf["start"] == "2024-01-02"


def test_what_is_watched_and_how_the_account_is_set(site, token):
    watch = ok(call(site, token, "get_watchlist"))
    assert [(e["ticker"], e["favorite"]) for e in watch["entries"]] == [("AAPL", False)]
    prefs = ok(call(site, token, "get_preferences"))
    assert prefs["currency"] == "EUR"
    assert prefs["tax_residence"] is None


def test_a_clean_book_has_nothing_to_fix_and_no_history(site, token):
    assert ok(call(site, token, "check_book"))["findings"] == []
    assert ok(call(site, token, "change_history"))["changes"] == []
    assert ok(call(site, token, "decision_journal"))["total"] == 0


def test_who_the_figures_belong_to(site, token):
    context = ok(call(site, token, "investor_context"))
    assert context["memory_enabled"] is True and context["memories"] == []
    assert context["profile"]["set"] is False
    assert "investor" in context["profile"]["persona"]


def test_is_it_above_its_200_day_average(site, token, monkeypatch):
    """300 flat sessions at 100, then one close at 110: the 200-day average is
    (199 x 100 + 110) / 200 = 100.05, up from 100 a month ago, so the price
    stands 110 / 100.05 - 1 above a rising average — an uptrend. The S&P 500
    stub is flat, so twelve months' return against it is the stock's own,
    110 / 100 - 1."""
    days = pd.date_range("2024-01-02", periods=301, freq="B")
    close = pd.Series([100.0] * 300 + [110.0], index=days)
    bars = pd.DataFrame({"High": close, "Low": close, "Close": close})
    monkeypatch.setattr(loaders, "asset_kind", lambda t: "stock")
    monkeypatch.setattr(loaders, "daily_bars", lambda t: bars)
    monkeypatch.setattr(loaders, "daily_closes",
                        lambda t, period="max": pd.Series(100.0, index=days))
    read = ok(call(site, token, "ticker_trend", ticker="aapl"))
    assert read["state"] == "up" and read["sma200_rising"] is True
    assert read["sma200"] == pytest.approx(100.05)
    assert read["pct_vs_sma200"] == pytest.approx(110 / 100.05 - 1)
    assert read["bench_name"] == "S&P 500"
    assert read["rs_12m"] == pytest.approx(0.10)
    assert read["pct_from_high"] == 0.0
