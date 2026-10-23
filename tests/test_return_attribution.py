"""The "what moved my portfolio" waterfall: bars that add up, and say what they are.

Hand-computed cases (a currency move alone, a dividend alone, a deposit
mid-window, a commission) plus a property over generated books: whatever the
prices, rates and trades, start + every bar == end, and a book with prices and
rates for every name leaves nothing in "other".
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stocks.analysis.portfolio import injected_vs_value
from stocks.analysis.return_attribution import attribution
from stocks.portfolio.ledger import Transaction

D = pd.to_datetime


def _hist(txs, closes, rates=None, to_base=None, units=None):
    """A replay with each ISO currency converting at its own daily rate."""
    fx = {c: pd.Series(r) for c, r in (rates or {}).items()}

    def conv(amount, ccy, day):
        if ccy == "EUR":
            return amount
        series = fx[ccy]
        return amount * float(series[series.index <= day].iloc[-1])

    return injected_vs_value(txs, closes, fx, to_base=to_base or conv, units=units), conv


def _bars(a):
    return {
        "start": a.start_value,
        "contrib": a.contributions,
        "price": a.price,
        "fx": a.fx,
        "div": a.dividends,
        "fees": a.fees,
        "other": a.other,
        "end": a.end_value,
    }


def test_a_currency_move_alone_is_all_currency():
    txs = [Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "USD")]
    days = D(["2024-01-02", "2024-01-03", "2024-01-04"])
    closes = {"AAPL": pd.Series([100.0, 100.0, 100.0], index=days)}
    rates = {"USD": {"2024-01-02": 0.9, "2024-01-03": 0.95, "2024-01-04": 1.0}}
    hist, conv = _hist(txs, closes, rates)
    a = attribution(hist, txs, to_base=conv)
    assert a is not None
    assert a.contributions == pytest.approx(900.0)  # 10 x 100 USD at 0.9
    assert a.fx == pytest.approx(100.0)  # 1000 USD now worth 1000 EUR, was 900
    assert a.price == pytest.approx(0.0, abs=1e-9)
    assert a.dividends == 0 and a.fees == 0 and a.other == 0
    assert a.end_value == pytest.approx(1000.0)
    assert a.residual == pytest.approx(0.0, abs=1e-9)


def test_a_price_move_in_a_foreign_currency_is_priced_at_the_rate_it_happened():
    txs = [Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "USD")]
    closes = {"AAPL": pd.Series([100.0, 110.0], index=D(["2024-01-02", "2024-01-03"]))}
    rates = {"USD": {"2024-01-02": 0.9, "2024-01-03": 1.0}}
    hist, conv = _hist(txs, closes, rates)
    a = attribution(hist, txs, to_base=conv)
    assert a is not None
    # Price: 10 x (110 - 100) x 0.9 = 90. Currency: 10 x 110 x (1.0 - 0.9) = 110.
    assert a.price == pytest.approx(90.0)
    assert a.fx == pytest.approx(110.0)
    assert a.end_value == pytest.approx(1100.0)
    assert a.residual == pytest.approx(0.0, abs=1e-9)


def test_a_dividend_alone_is_income_and_not_price():
    """The adjusted close carries the payment as a rise; the bar takes it back out."""
    txs = [
        Transaction("2024-01-02", "KO", "buy", 10, 100.0, "EUR"),
        Transaction("2024-01-04", "KO", "dividend", 0, 5.0, "EUR", 1.0),
    ]
    days = D(["2024-01-02", "2024-01-03", "2024-01-04"])
    closes = {"KO": pd.Series([100.0, 100.0, 100.5], index=days)}
    hist, conv = _hist(txs, closes)
    a = attribution(hist, txs, to_base=conv)
    assert a is not None
    assert a.dividends == pytest.approx(5.0)
    assert a.price == pytest.approx(0.0, abs=1e-9)
    assert a.fx == 0
    assert a.contributions == pytest.approx(1000.0)
    assert a.end_value == pytest.approx(1005.0)
    assert a.residual == pytest.approx(0.0, abs=1e-9)


def test_a_mid_window_deposit_is_a_contribution_not_a_gain():
    txs = [
        Transaction("2024-01-02", "MSFT", "buy", 10, 100.0, "EUR"),
        Transaction("2024-01-04", "MSFT", "buy", 10, 120.0, "EUR"),
    ]
    idx = D(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    closes = {"MSFT": pd.Series([100.0, 110.0, 120.0, 130.0], index=idx)}
    hist, conv = _hist(txs, closes)

    whole = attribution(hist, txs, to_base=conv)
    assert whole is not None
    assert whole.contributions == pytest.approx(2200.0)
    assert whole.price == pytest.approx(10 * 30 + 10 * 10)  # 10 sh +30, 10 sh +10
    assert whole.end_value == pytest.approx(2600.0)

    # From the 3rd: opens at 10 x 110, then a 1200 deposit, then +10 on 20 shares.
    later = attribution(hist, txs, start=pd.Timestamp("2024-01-03"), to_base=conv)
    assert later is not None
    assert later.start_value == pytest.approx(1100.0)
    assert later.contributions == pytest.approx(1200.0)
    assert later.price == pytest.approx(10 * 10 + 20 * 10)
    assert later.end_value == pytest.approx(2600.0)
    assert later.residual == pytest.approx(0.0, abs=1e-9)


def test_a_commission_is_a_fee_bar_not_a_loss_in_price():
    txs = [Transaction("2024-01-02", "MSFT", "buy", 10, 100.0, "EUR", 4.0)]
    closes = {"MSFT": pd.Series([100.0, 100.0], index=D(["2024-01-02", "2024-01-03"]))}
    hist, conv = _hist(txs, closes)
    a = attribution(hist, txs, to_base=conv)
    assert a is not None
    assert a.contributions == pytest.approx(1004.0)
    assert a.fees == pytest.approx(-4.0)
    assert a.price == pytest.approx(0.0, abs=1e-9)
    assert a.end_value == pytest.approx(1000.0)


def test_a_name_without_a_price_stays_at_cost_and_still_adds_up():
    txs = [
        Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR"),
        Transaction("2024-01-02", "GHOST", "buy", 5, 20.0, "EUR"),
    ]
    closes = {"AAPL": pd.Series([100.0, 110.0], index=D(["2024-01-02", "2024-01-03"]))}
    hist, conv = _hist(txs, closes)
    a = attribution(hist, txs, to_base=conv)
    assert a is not None
    assert a.price == pytest.approx(100.0)
    assert a.contributions == pytest.approx(1100.0)
    assert a.end_value == pytest.approx(1200.0)
    assert a.residual == pytest.approx(0.0, abs=1e-9)
    assert "GHOST" not in a.movers  # carried at cost: it moved nothing


def test_movers_name_the_tickers_behind_the_bars():
    txs = [
        Transaction("2024-01-02", "UP", "buy", 10, 100.0, "EUR"),
        Transaction("2024-01-02", "DOWN", "buy", 10, 100.0, "EUR"),
    ]
    idx = D(["2024-01-02", "2024-01-03"])
    closes = {
        "UP": pd.Series([100.0, 110.0], index=idx),
        "DOWN": pd.Series([100.0, 95.0], index=idx),
    }
    hist, conv = _hist(txs, closes)
    a = attribution(hist, txs, to_base=conv)
    assert a is not None
    assert a.movers == {"UP": pytest.approx(100.0), "DOWN": pytest.approx(-50.0)}


def test_empty_history_has_nothing_to_explain():
    assert attribution(pd.DataFrame(), []) is None


MOVE = st.floats(min_value=0.8, max_value=1.25, allow_nan=False)
RATE = st.floats(min_value=0.6, max_value=1.5, allow_nan=False)


@settings(max_examples=25, deadline=None)
@given(
    prices=st.lists(MOVE, min_size=4, max_size=12),
    rates=st.lists(RATE, min_size=12, max_size=12),
    qtys=st.lists(st.integers(min_value=-5, max_value=20), min_size=12, max_size=12),
    fee=st.floats(min_value=0, max_value=3, allow_nan=False),
    pay=st.floats(min_value=0, max_value=4, allow_nan=False),
    cut=st.integers(min_value=0, max_value=6),
)
def test_the_bars_always_sum_to_end_minus_start(prices, rates, qtys, fee, pay, cut):
    n = len(prices)
    days = [str(d.date()) for d in pd.date_range("2024-01-02", periods=n)]
    path, level = [], 100.0
    for m in prices:
        level *= m
        path.append(level)
    closes = {"AAA": pd.Series(path, index=D(days))}
    rate_path = dict(zip(days, rates[:n], strict=False))
    txs = [Transaction(days[0], "AAA", "buy", 10, path[0], "USD", fee)]
    held = 10
    for i in range(1, n):
        q = qtys[i]
        if q > 0:
            txs.append(Transaction(days[i], "AAA", "buy", q, path[i], "USD", fee))
            held += q
        elif q < 0 and held + q >= 1:
            txs.append(Transaction(days[i], "AAA", "sell", -q, path[i], "USD", fee))
            held += q
    if pay:
        txs.append(Transaction(days[-1], "AAA", "dividend", 0, pay, "USD", 0.0))
    hist, conv = _hist(txs, closes, {"USD": rate_path})
    # Windows opening anywhere in the span, plus inception.
    start = D(days[cut % n]) if cut else None
    a = attribution(hist, txs, start=start, to_base=conv)
    if a is None:
        return
    bars = _bars(a)
    moved = sum(v for k, v in bars.items() if k not in ("start", "end"))
    assert bars["start"] + moved == pytest.approx(bars["end"], abs=1e-6)
    assert a.residual == pytest.approx(0.0, abs=1e-6)
    # Priced throughout: nothing is left unexplained.
    assert a.other == 0.0
