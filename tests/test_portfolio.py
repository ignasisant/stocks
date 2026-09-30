"""Portfolio analytics tests — synthetic price/return frames, no network."""

import math

import numpy as np
import pandas as pd
import pytest

from stocks.analysis.portfolio import (
    allocation,
    annualized_volatility,
    beta,
    drawdown_span,
    effective_positions,
    equal_weights,
    first_owned,
    hhi,
    market_value_weights,
    max_drawdown,
    portfolio_returns,
    position_table,
    priced_totals,
    returns_frame,
    top_n_weight,
    value_weights,
    weights_from_holdings,
)
from stocks.config import Holding


def test_equal_weights_sum_to_one():
    w = equal_weights(["A", "B", "C", "D"])
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert all(abs(v - 0.25) < 1e-12 for v in w.values())


def test_market_value_weights():
    w = market_value_weights({"A": 10, "B": 10}, {"A": 30.0, "B": 10.0})
    assert abs(w["A"] - 0.75) < 1e-12
    assert abs(w["B"] - 0.25) < 1e-12


def test_weights_prefer_positions_over_equal():
    holds = [
        Holding("A", shares=10),
        Holding("B", shares=0),  # watchlist-only, excluded when positions exist
    ]
    w = weights_from_holdings(holds, {"A": 5.0, "B": 5.0})
    assert set(w) == {"A"}
    assert abs(w["A"] - 1.0) < 1e-12


def test_weights_equal_when_no_positions():
    holds = [Holding("A"), Holding("B")]
    w = weights_from_holdings(holds, {"A": 5.0, "B": 5.0})
    assert set(w) == {"A", "B"}
    assert abs(w["A"] - 0.5) < 1e-12


def _prices() -> dict[str, pd.Series]:
    idx = pd.date_range("2024-01-01", periods=6, freq="D")
    return {
        "A": pd.Series([100, 101, 102, 103, 104, 105], index=idx, dtype=float),
        "B": pd.Series([50, 49, 50, 51, 50, 52], index=idx, dtype=float),
    }


def test_returns_frame_shape():
    r = returns_frame(_prices())
    assert list(r.columns) == ["A", "B"]
    assert len(r) == 5  # 6 prices -> 5 returns


def test_portfolio_returns_weighting():
    r = returns_frame(_prices())
    p = portfolio_returns(r, {"A": 0.5, "B": 0.5})
    # first day: A +1%, B -2% -> mean -0.5%
    assert abs(p.iloc[0] - ((0.01 + (-0.02)) / 2)) < 1e-12


def test_annualized_volatility_zero_for_constant():
    r = pd.Series([0.0, 0.0, 0.0, 0.0])
    assert annualized_volatility(r) == 0.0


def test_beta_of_series_with_itself_is_one():
    r = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02])
    assert abs(beta(r, r) - 1.0) < 1e-9


def test_beta_scaled():
    b = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02])
    a = b * 2  # perfectly correlated, twice the moves
    assert abs(beta(a, b) - 2.0) < 1e-9


def test_max_drawdown():
    prices = pd.Series([100, 120, 90, 110, 60], dtype=float)
    # peak 120 -> trough 60 => -50%
    assert abs(max_drawdown(prices) - (-0.5)) < 1e-12


def test_drawdown_span_dates_the_worst_fall():
    idx = pd.date_range("2024-01-01", periods=5)
    prices = pd.Series([100, 120, 90, 110, 60], index=idx, dtype=float)
    assert drawdown_span(prices) == (idx[1], idx[4])
    # A path that only ever rose has no fall to date.
    assert drawdown_span(pd.Series([1.0, 1.1, 1.2], index=idx[:3])) is None


def test_concentration_metrics():
    w = {"A": 0.5, "B": 0.3, "C": 0.2}
    assert abs(hhi(w) - (0.25 + 0.09 + 0.04)) < 1e-12
    assert abs(effective_positions({"A": 0.5, "B": 0.5}) - 2.0) < 1e-12
    assert abs(top_n_weight(w, 2) - 0.8) < 1e-12


def test_allocation_groups_by_meta():
    w = {"A": 0.5, "B": 0.3, "C": 0.2}
    meta = {
        "A": {"sector": "Tech"},
        "B": {"sector": "Tech"},
        "C": {"sector": "Health"},
    }
    alloc = allocation(w, meta, "sector")
    assert abs(alloc["Tech"] - 0.8) < 1e-12
    assert abs(alloc["Health"] - 0.2) < 1e-12


def test_allocation_unknown_bucket():
    alloc = allocation({"A": 1.0}, {"A": {}}, "country")
    assert alloc["Unknown"] == 1.0


def test_position_table_pnl():
    holds = [Holding("A", shares=10, cost=90.0), Holding("B")]  # B has no shares
    tbl = position_table(holds, {"A": 100.0, "B": 20.0})
    assert list(tbl.index) == ["A"]
    assert tbl.loc["A", "value"] == 1000.0
    assert abs(tbl.loc["A", "pnl"] - 100.0) < 1e-9
    assert abs(tbl.loc["A", "pnl_pct"] - (1000 / 900 - 1)) < 1e-9


def test_priced_totals_measure_the_same_rows_on_both_sides():
    # B's price download came back empty: its cost must leave the basis too,
    # or the tile divides the whole book's cost by part of its value.
    tbl = pd.DataFrame(
        [
            {"ticker": "A", "cost": 100.0, "value": 120.0},
            {"ticker": "B", "cost": 900.0, "value": float("nan")},
        ]
    ).set_index("ticker")
    assert priced_totals(tbl) == (100.0, 120.0, 1)


def test_priced_totals_on_an_empty_frame():
    assert priced_totals(pd.DataFrame()) == (0.0, 0.0, 0)


def test_value_weights_keep_unpriced_rows_in_the_denominator():
    # B never priced: A holds 120 of a ~9,120 book, not all of a 120 one.
    tbl = pd.DataFrame(
        [
            {"ticker": "A", "cost": 100.0, "value": 120.0},
            {"ticker": "B", "cost": 9000.0, "value": float("nan")},
        ]
    ).set_index("ticker")
    w = value_weights(tbl)
    assert abs(w["A"] - 120 / 9120) < 1e-9
    assert math.isnan(w["B"])


def test_position_table_empty_without_shares():
    assert position_table([Holding("A"), Holding("B")], {"A": 1.0}).empty


def test_market_value_weights_ignore_missing_price():
    w = market_value_weights({"A": 10, "B": 10}, {"A": 5.0})  # B has no price
    assert set(w) == {"A"}
    assert not np.isnan(w["A"])


# ------------------------------------------------------------ injected vs value
from stocks.analysis.portfolio import (  # noqa: E402
    injected_series,
    injected_vs_value,
    shares_frame,
)
from stocks.portfolio.ledger import Transaction  # noqa: E402


def _eur(amount: float, currency: str, day: str) -> float:
    return amount * (0.5 if currency == "USD" else 1.0)


def test_shares_frame_replays_buys_sells_and_back_adjusts_splits():
    """Splits are back-adjusted, matching the back-adjusted price history: the
    pre-split buy already counts in post-split shares and the split date is not
    a step (stepping there would price the pre-split stretch at 1/ratio)."""
    txs = [
        Transaction("2024-01-01", "A", "buy", quantity=10, price=1),
        Transaction("2024-01-03", "A", "buy", quantity=5, price=1),
        Transaction("2024-01-05", "A", "sell", quantity=8, price=1),
        Transaction("2024-01-02", "B", "buy", quantity=2, price=1),
        Transaction("2024-01-04", "B", "split", quantity=4),
    ]
    f = shares_frame(txs, end="2024-01-06")
    assert f.loc["2024-01-01", "A"] == 10
    assert f.loc["2024-01-04", "A"] == 15
    assert f.loc["2024-01-06", "A"] == 7
    assert f.loc["2024-01-01", "B"] == 0  # before first buy
    assert f.loc["2024-01-03", "B"] == 8  # pre-split buy, post-split shares
    assert f.loc["2024-01-04", "B"] == 8  # split day: no step
    assert f.loc["2024-01-05", "B"] == 8


def test_shares_frame_split_does_not_scale_same_day_trades():
    """A trade on the split date already executed at the post-split price."""
    txs = [
        Transaction("2024-01-01", "A", "buy", quantity=1, price=200),
        Transaction("2024-01-03", "A", "split", quantity=20),
        Transaction("2024-01-03", "A", "buy", quantity=5, price=10),
    ]
    f = shares_frame(txs, end="2024-01-04")
    assert f.loc["2024-01-02", "A"] == 20  # the one pre-split share
    assert f.loc["2024-01-03", "A"] == 25  # + 5 bought post-split


def test_injected_series_buys_minus_net_sell_proceeds():
    txs = [
        Transaction(
            "2024-01-01", "A", "buy", quantity=10, price=10, fee=5, currency="EUR"
        ),
        Transaction(
            "2024-01-03", "A", "sell", quantity=4, price=12, fee=3, currency="EUR"
        ),
        Transaction("2024-01-04", "A", "dividend", price=50, currency="EUR"),
    ]
    s = injected_series(txs, to_base=_eur)
    assert len(s) == 2  # dividend ignored
    assert abs(s.iloc[0] - 105.0) < 1e-9  # cost incl. fee
    assert abs(s.iloc[-1] - 60.0) < 1e-9  # minus net proceeds (48 - 3)


def test_injected_vs_value_marks_to_market_in_eur():
    txs = [
        Transaction("2024-01-01", "A", "buy", quantity=10, price=10, currency="USD"),
        Transaction("2024-01-02", "B", "buy", quantity=1, price=99, currency="EUR"),
    ]
    idx = pd.date_range("2024-01-01", "2024-01-04", freq="D")
    closes = {"A": pd.Series([10.0, 12.0, 12.0, 14.0], index=idx)}  # B: no prices
    fx = {"USD": pd.Series(0.5, index=idx)}
    df = injected_vs_value(txs, closes, fx, to_base=_eur)
    assert abs(df.loc["2024-01-01", "injected"] - 50.0) < 1e-9
    assert abs(df.loc["2024-01-01", "value"] - 50.0) < 1e-9
    assert abs(df.loc["2024-01-01", "pnl_pct"] - 0.0) < 1e-9
    assert abs(df.loc["2024-01-02", "injected"] - 149.0) < 1e-9
    # B has no close series: carried at cost (99) while held.
    assert abs(df.loc["2024-01-02", "value"] - (60.0 + 99.0)) < 1e-9
    assert abs(df.loc["2024-01-04", "value"] - (70.0 + 99.0)) < 1e-9
    assert abs(df.loc["2024-01-04", "pnl_pct"] - (169.0 / 149.0 - 1)) < 1e-9


def test_injected_vs_value_reads_the_book_in_the_currency_it_reports_in():
    """A book reported in dollars, priced as one.

    This used to test each holding against a literal "EUR": the dollar names
    found no rate and were carried at cost — flat, and listed as unpriced —
    while the euro ones were valued at parity. Two names both up 20% read
    +4.8%.
    """
    txs = [
        Transaction("2024-01-01", "A", "buy", quantity=10, price=10, currency="USD"),
        Transaction("2024-01-01", "B", "buy", quantity=10, price=10, currency="EUR"),
    ]
    idx = pd.date_range("2024-01-01", "2024-01-02", freq="D")
    closes = {
        "A": pd.Series([10.0, 12.0], index=idx),
        "B": pd.Series([10.0, 12.0], index=idx),
    }
    # EUR -> USD, which is what `book_history` builds for a USD book.
    fx = {"EUR": pd.Series(1.1, index=idx)}
    usd = lambda amount, ccy, day: amount * (1.1 if ccy == "EUR" else 1.0)  # noqa: E731
    df = injected_vs_value(txs, closes, fx, to_base=usd, base="USD")
    assert df.attrs["carried_at_cost"] == []  # the dollar names are priced
    assert abs(df.loc["2024-01-02", "value"] - (120.0 + 120.0 * 1.1)) < 1e-9
    assert abs(df.loc["2024-01-02", "pnl_pct"] - 0.2) < 1e-9


def test_injected_vs_value_empty_ledger():
    assert injected_vs_value([], {}, {}).empty


def test_injected_vs_value_stray_quote_outside_holding_carried_at_cost():
    """Delisted-ticker regression (ORGN): one stray quote after the position was
    sold must not zero out the holding period — carry at cost instead."""
    txs = [
        Transaction("2024-01-01", "A", "buy", quantity=10, price=10, currency="EUR"),
        Transaction("2024-01-03", "A", "sell", quantity=10, price=11, currency="EUR"),
    ]
    # Only quote is after the sale — useless for the holding window.
    closes = {"A": pd.Series([1.0], index=pd.to_datetime(["2024-06-01"]))}
    df = injected_vs_value(txs, closes, {}, to_base=_eur)
    assert abs(df.loc["2024-01-01", "value"] - 100.0) < 1e-9  # at cost
    assert abs(df.loc["2024-01-02", "value"] - 100.0) < 1e-9
    assert abs(df.loc["2024-01-03", "value"] - 0.0) < 1e-9  # sold out
    assert df.attrs["carried_at_cost"] == ["A"]


def _collided_book():
    """CAT-EUR regression: Revolut fills at ~1e-5 EUR, Yahoo's "CAT-EUR" is a
    different coin quoting ~0.02 — 2000x the price the book actually paid."""
    txs = [
        Transaction("2024-01-01", "A", "buy", quantity=10, price=10, currency="EUR"),
        Transaction(
            "2024-01-02", "CAT", "buy", quantity=44_000_000, price=1.1e-5,
            currency="EUR",
        ),
    ]
    idx = pd.date_range("2024-01-01", "2024-01-04", freq="D")
    closes = {
        "A": pd.Series([10.0, 10.5, 11.0, 11.0], index=idx),
        "CAT": pd.Series(0.02, index=idx),
    }
    return txs, closes


def test_injected_vs_value_rejects_a_close_the_fills_say_is_another_asset():
    txs, closes = _collided_book()
    df = injected_vs_value(txs, closes, {}, to_base=_eur)
    # CAT carried at its ~484 EUR cost, not marked at 44M x 0.02 = 880k.
    assert df.attrs["carried_at_cost"] == ["CAT"]
    assert df["value"].max() < 1_000
    assert abs(df.loc["2024-01-04", "value"] - (110.0 + 44_000_000 * 1.1e-5)) < 1e-6


def test_plausible_closes_drops_the_collided_series_only():
    txs, closes = _collided_book()
    kept = plausible_closes(closes, txs, units={})
    assert set(kept) == {"A"}


def test_plausible_closes_keeps_real_moves_and_short_histories():
    """A name up 5x since the fill is a real move, and a series that starts
    after the first buy (IPO, short download) has nothing to compare there."""
    idx = pd.date_range("2024-01-05", periods=3, freq="D")
    txs = [
        Transaction("2024-01-01", "X", "buy", quantity=1, price=10, currency="EUR"),
        Transaction("2024-01-06", "X", "buy", quantity=1, price=48, currency="EUR"),
    ]
    closes = {"X": pd.Series([45.0, 50.0, 55.0], index=idx)}
    assert set(plausible_closes(closes, txs, units={})) == {"X"}


# ------------------------------------------------------- time-weighted returns
from stocks.analysis.portfolio import (  # noqa: E402
    flow_series,
    plausible_closes,
    time_weighted_returns,
)


def test_portfolio_returns_ipo_partial_history_not_truncated():
    """A late-listing ticker (FIG-style IPO) must not truncate the series."""
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    returns = pd.DataFrame(
        {
            "A": [0.01, 0.02, 0.01, 0.02],
            "B": [np.nan, np.nan, 0.04, 0.02],  # lists on day 3
        },
        index=idx,
    )
    p = portfolio_returns(returns, {"A": 0.5, "B": 0.5})
    assert len(p) == 4  # full window, not just B's two days
    assert abs(p.iloc[0] - 0.01) < 1e-12  # A alone, weight renormalised
    assert abs(p.iloc[2] - 0.025) < 1e-12  # (0.01 + 0.04) / 2


def test_portfolio_returns_since_excludes_pre_purchase_history():
    """A name bought late does not backdate today's weight onto years it was
    never held — the exact bug a fixed-weight-since-inception backtest hits
    for any position bought after a rally that made it big enough to weight."""
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    returns = pd.DataFrame(
        {
            "A": [0.01, 0.01, 0.01, 0.01],
            "B": [1.00, -0.50, 0.02, 0.02],  # B doubles then halves, pre-purchase
        },
        index=idx,
    )
    unramped = portfolio_returns(returns, {"A": 0.5, "B": 0.5})
    ramped = portfolio_returns(
        returns, {"A": 0.5, "B": 0.5}, since={"B": pd.Timestamp("2024-01-03")}
    )
    assert not math.isclose(unramped.iloc[0], ramped.iloc[0])
    assert abs(ramped.iloc[0] - 0.01) < 1e-12  # A alone before B was owned
    assert abs(ramped.iloc[2] - 0.015) < 1e-12  # both, once B is masked in


def test_first_owned_takes_earliest_buy_and_ignores_transfers():
    txs = [
        Transaction("2024-03-01", "A", "buy", quantity=1, price=10),
        Transaction("2024-01-15", "A", "buy", quantity=1, price=10),  # earlier
        Transaction("2024-02-01", "A", "sell", quantity=1, price=12),
        Transaction("2024-06-01", "B", "transfer_in", quantity=1, price=10),
    ]
    since = first_owned(txs)
    assert since["A"] == pd.Timestamp("2024-01-15")
    assert "B" not in since  # snapshot import, real acquisition date unknown


def test_flow_series_signs_and_ticker_filter():
    txs = [
        Transaction(
            "2024-01-02", "A", "buy", quantity=10, price=10, currency="USD", fee=2
        ),
        Transaction(
            "2024-01-03", "A", "sell", quantity=5, price=12, currency="USD", fee=2
        ),
        Transaction("2024-01-04", "A", "dividend", price=50, currency="EUR", fee=5),
        Transaction("2024-01-02", "B", "buy", quantity=1, price=100, currency="EUR"),
    ]
    f = flow_series(txs, to_base=_eur, tickers={"A"})
    assert abs(f[pd.Timestamp("2024-01-02")] - 51.0) < 1e-9  # (100 + 2) * 0.5, B skipped
    assert abs(f[pd.Timestamp("2024-01-03")] - (-29.0)) < 1e-9  # -(60 - 2) * 0.5


def test_a_dividend_is_not_a_flow_because_the_price_path_already_has_it():
    """The value path is built on auto_adjusted closes, which walk every close
    before an ex-date down by the dividend — the payment is already in the
    series as growth. Booking it as a withdrawal on top paid it twice, which
    is a free year of return for anybody holding payers."""
    txs = [
        Transaction("2024-01-02", "A", "buy", quantity=10, price=10, currency="EUR"),
        Transaction("2024-01-04", "A", "dividend", price=50, currency="EUR", fee=5),
    ]
    f = flow_series(txs, to_base=_eur)
    assert pd.Timestamp("2024-01-04") not in f.index


def test_time_weighted_returns_flow_neutral():
    """A mid-period top-up must not change the return path (that's the point of TWR)."""
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    # 10 shares @100, price +10%/flat/+10%; day 3 buys 5 more @110.
    value = pd.Series([1000.0, 1100.0, 1650.0, 1815.0], index=idx)
    flows = pd.Series(
        {pd.Timestamp("2024-01-01"): 1000.0, pd.Timestamp("2024-01-03"): 550.0}
    )
    r = time_weighted_returns(value, flows)
    assert pd.Timestamp("2024-01-01") not in r.index  # no prior value
    assert abs(r[pd.Timestamp("2024-01-02")] - 0.10) < 1e-9
    assert abs(r[pd.Timestamp("2024-01-03")] - 0.0) < 1e-9  # top-up ≠ performance
    assert abs(r[pd.Timestamp("2024-01-04")] - 0.10) < 1e-9
    cum = float((1 + r).prod()) - 1
    assert abs(cum - 0.21) < 1e-9  # pure price move 100 -> 121


def test_time_weighted_returns_credits_dividends():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    value = pd.Series([1000.0, 1000.0], index=idx)
    flows = pd.Series({pd.Timestamp("2024-01-02"): -50.0})  # dividend paid out
    r = time_weighted_returns(value, flows)
    assert abs(r[pd.Timestamp("2024-01-02")] - 0.05) < 1e-9


def test_time_weighted_returns_drops_impossible_days():
    """A flow the value path never received (an unrecorded split) prices below
    -100%. Dropped, not kept: one such day sends the cumulative path negative
    and NaNs the annualised return."""
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    value = pd.Series([1000.0, 1100.0, 1210.0], index=idx)
    # Day 2 injects 3000 that never lands in the value: (1100 - 3000)/1000 - 1.
    flows = pd.Series({pd.Timestamp("2024-01-02"): 3000.0})
    r = time_weighted_returns(value, flows)
    assert pd.Timestamp("2024-01-02") not in r.index
    assert r.attrs["dropped_days"] == [pd.Timestamp("2024-01-02")]
    assert abs(r[pd.Timestamp("2024-01-03")] - 0.10) < 1e-9
    assert float((1 + r).prod()) > 0


def test_time_weighted_returns_keeps_ordinary_days():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    value = pd.Series([1000.0, 900.0], index=idx)
    r = time_weighted_returns(value, pd.Series(dtype=float))
    assert r.attrs["dropped_days"] == []
    assert abs(r[pd.Timestamp("2024-01-02")] + 0.10) < 1e-9


def test_time_weighted_returns_empty():
    assert time_weighted_returns(pd.Series(dtype=float), pd.Series(dtype=float)).empty


# ------------------------------------------------------ money-weighted returns
from stocks.analysis.portfolio import money_weighted_return  # noqa: E402


def test_money_weighted_return_doubling_year():
    idx = pd.to_datetime(["2023-01-01", "2024-01-01"])
    value = pd.Series([1000.0, 2000.0], index=idx)
    r = money_weighted_return(value, pd.Series(dtype=float))
    assert abs(r - 1.0) < 0.01  # doubled in ~a year -> ~+100%/yr


def test_money_weighted_return_flat_with_deposit_is_zero():
    """No price move -> IRR 0 regardless of a mid-window deposit."""
    idx = pd.to_datetime(["2024-01-01", "2024-02-20", "2024-04-10"])
    value = pd.Series([1000.0, 2000.0, 2000.0], index=idx)
    flows = pd.Series({pd.Timestamp("2024-02-20"): 1000.0})
    r = money_weighted_return(value, flows)
    assert abs(r) < 1e-6


def test_money_weighted_return_punishes_badly_timed_deposit():
    """Big deposit right before a -50% leg: IRR must read worse than -50%/yr
    (the TWR of the same path would be exactly -50% annualised)."""
    idx = pd.to_datetime(["2023-01-01", "2023-07-02", "2023-12-31"])
    value = pd.Series([100.0, 1000.0, 500.0], index=idx)
    flows = pd.Series({pd.Timestamp("2023-07-02"): 900.0})
    r = money_weighted_return(value, flows)
    assert r < -0.5


def test_money_weighted_return_start_clips_window():
    """Opening value at `start` counts as the buy-in; earlier flat history
    must not dilute the windowed rate."""
    idx = pd.to_datetime(["2022-06-01", "2023-01-01", "2024-01-01"])
    value = pd.Series([1000.0, 1000.0, 2000.0], index=idx)
    r = money_weighted_return(
        value, pd.Series(dtype=float), start=pd.Timestamp("2023-01-01")
    )
    assert abs(r - 1.0) < 0.01


def test_money_weighted_return_degenerate():
    empty = pd.Series(dtype=float)
    assert math.isnan(money_weighted_return(empty, empty))
    one = pd.Series([100.0], index=pd.to_datetime(["2024-01-01"]))
    assert math.isnan(money_weighted_return(one, pd.Series(dtype=float)))


from stocks.analysis.portfolio import basket_change  # noqa: E402


def test_basket_change_day_week_month_windows():
    idx = pd.date_range("2024-01-01", periods=40, freq="D")
    vals = pd.DataFrame({"A": [float(100 + i) for i in range(40)]}, index=idx)
    day = basket_change(vals, 1)
    assert abs(day[0] - 1.0) < 1e-9 and abs(day[1] - 1 / 138) < 1e-9
    week = basket_change(vals, 7)  # anchors exactly 7 days back: 132 -> 139
    assert abs(week[0] - 7.0) < 1e-9 and abs(week[1] - 7 / 132) < 1e-9
    month = basket_change(vals, 30)  # 109 -> 139
    assert abs(month[0] - 30.0) < 1e-9 and abs(month[1] - 30 / 109) < 1e-9


def test_basket_change_window_not_covered():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    vals = pd.DataFrame({"A": [1.0] * 5}, index=idx)
    assert basket_change(vals, 30) is None
    assert basket_change(vals.iloc[:1], 1) is None
    assert basket_change(pd.DataFrame(), 1) is None


def test_basket_change_ignores_tickers_missing_at_either_endpoint():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    vals = pd.DataFrame(
        {
            "A": [100.0, 100.0, 110.0],
            "B": [float("nan"), float("nan"), 500.0],  # listed mid-window
        },
        index=idx,
    )
    chg = basket_change(vals, 1)
    assert abs(chg[0] - 10.0) < 1e-9  # B's appearance isn't a +500 "gain"
    assert abs(chg[1] - 0.10) < 1e-9


from stocks.analysis.portfolio import ticker_changes  # noqa: E402


def test_ticker_changes_windows_match_the_basket_anchors():
    """Home's movers card reads per-name moves off the frame the tiles use, so
    it must anchor exactly where `basket_change` does — a "1w" gainer list that
    measured a different week from the "1 week" tile beside it would be wrong
    in a way nobody can see."""
    idx = pd.date_range("2024-01-01", periods=40, freq="D")
    vals = pd.DataFrame(
        {
            "A": [float(100 + i) for i in range(40)],   # rises all window
            "B": [float(200 - i) for i in range(40)],   # falls all window
        },
        index=idx,
    )
    day = ticker_changes(vals, 1)
    assert abs(day["A"] - 1 / 138) < 1e-9
    assert abs(day["B"] - (-1 / 162)) < 1e-9
    week = ticker_changes(vals, 7)  # anchors exactly 7 days back
    assert abs(week["A"] - 7 / 132) < 1e-9
    assert abs(week["B"] - (-7 / 168)) < 1e-9
    month = ticker_changes(vals, 30)
    assert abs(month["A"] - 30 / 109) < 1e-9
    # Gainer/loser split: sign, not magnitude, decides which list a name lands
    # in, and no name can be in both.
    assert list(month[month > 0].index) == ["A"]
    assert list(month[month < 0].index) == ["B"]


def test_ticker_changes_drops_names_missing_at_either_endpoint():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    vals = pd.DataFrame(
        {
            "A": [100.0, 100.0, 110.0],
            "B": [float("nan"), float("nan"), 500.0],  # listed mid-window
            "C": [0.0, 0.0, 50.0],                     # no position until now
        },
        index=idx,
    )
    chg = ticker_changes(vals, 1)
    assert list(chg.index) == ["A"]  # B and C would read as infinite gains
    assert abs(chg["A"] - 0.10) < 1e-9


def test_ticker_changes_window_not_covered():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    vals = pd.DataFrame({"A": [1.0] * 5}, index=idx)
    assert ticker_changes(vals, 30).empty
    assert ticker_changes(vals.iloc[:1], 1).empty
    assert ticker_changes(pd.DataFrame(), 1).empty


from stocks.analysis.portfolio import ticker_money_changes  # noqa: E402


def test_ticker_money_changes_sum_to_the_basket_change():
    """The contribution figures are only honest if they add up: the digest
    prints them under a header that already reported the basket's move, so a
    per-name breakdown that summed to something else would be visibly wrong."""
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    vals = pd.DataFrame(
        {
            "BIG": [float(10_000 + 10 * i) for i in range(10)],  # +0.1%/day, +€10
            "SMALL": [float(500 + 20 * i) for i in range(10)],   # +4%/day, +€20
        },
        index=idx,
    )
    day = ticker_money_changes(vals, 1)
    assert abs(day["BIG"] - 10.0) < 1e-9
    assert abs(day["SMALL"] - 20.0) < 1e-9
    change, _ = basket_change(vals, 1)
    assert abs(day.sum() - change) < 1e-9

    week = ticker_money_changes(vals, 7)
    assert abs(week.sum() - basket_change(vals, 7)[0]) < 1e-9


def test_ticker_money_changes_rank_differs_from_percent_rank():
    """The whole point of the money view: the loudest percentage is regularly
    the smallest position."""
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    vals = pd.DataFrame(
        {"BIG": [10_000.0, 10_150.0], "SMALL": [400.0, 440.0]}, index=idx
    )
    assert ticker_changes(vals, 1).idxmax() == "SMALL"   # +10% vs +1.5%
    assert ticker_money_changes(vals, 1).idxmax() == "BIG"  # +150 vs +40


def test_ticker_money_changes_keeps_new_positions_and_drops_unpriced():
    """Unlike the percentage view a zero start is fine here — a position opened
    yesterday genuinely added its value to the book — but a name unpriced at
    either endpoint contributed nothing measurable."""
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    vals = pd.DataFrame(
        {
            "NEW": [0.0, 300.0],
            "GHOST": [float("nan"), 500.0],
        },
        index=idx,
    )
    money = ticker_money_changes(vals, 1)
    assert list(money.index) == ["NEW"]
    assert abs(money["NEW"] - 300.0) < 1e-9


def test_ticker_money_changes_window_not_covered():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    vals = pd.DataFrame({"A": [1.0] * 5}, index=idx)
    assert ticker_money_changes(vals, 30).empty
    assert ticker_money_changes(pd.DataFrame(), 1).empty


from datetime import UTC, datetime  # noqa: E402

from stocks.analysis.portfolio import (  # noqa: E402
    _session_move,
    market_active,
    market_live,
    session_quote,
    us_extended_session,
)


def _utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A 2024 UTC instant (Jan = EST, UTC-5)."""
    return datetime(2024, month, day, hour, minute, tzinfo=UTC)


def test_us_extended_session_windows():
    # Jan 3 2024 is a Wednesday; ET = UTC-5.
    assert us_extended_session(_utc(1, 3, 8)) is None  # 03:00 ET, before the feed
    assert us_extended_session(_utc(1, 3, 9)) == "pre"  # 04:00 ET, feed opens
    assert us_extended_session(_utc(1, 3, 12)) == "pre"  # 07:00 ET
    assert us_extended_session(_utc(1, 3, 15)) is None  # 10:00 ET, regular
    assert us_extended_session(_utc(1, 3, 22)) == "post"  # 17:00 ET
    assert us_extended_session(_utc(1, 4, 2)) is None  # 21:00 ET, shut
    assert us_extended_session(_utc(1, 6, 12)) is None  # Saturday


def test_market_active_covers_us_extended_hours_but_not_foreign():
    pre = _utc(1, 3, 12)  # 07:00 ET — US premarket
    assert not market_live("AAPL", pre)
    assert market_active("AAPL", pre)  # premarket quote is live data
    shut = _utc(1, 4, 2)  # 21:00 ET — nothing trading anywhere
    assert not market_active("AAPL", shut)


def _patch_quote(monkeypatch, quote):
    """Make the batch quote endpoint answer `quote` for whatever is asked.

    Patched at `data.quotes._fetch` — below the cooldown and the budget, above
    the network — so these tests exercise the real keying and chunking.
    """
    from stocks.data import quotes as q

    q._blocked_until = 0.0
    monkeypatch.setattr(
        q, "_fetch",
        lambda symbols, timeout: [{**quote, "symbol": s} for s in symbols],
    )


def test_session_move_uses_premarket_against_last_close(monkeypatch):
    # Premarket: regularMarketPrice is still yesterday's close.
    _patch_quote(
        monkeypatch,
        {
            "marketState": "PRE",
            "regularMarketPrice": 200.0,
            "regularMarketPreviousClose": 190.0,
            "preMarketPrice": 220.0,
        },
    )
    assert abs(_session_move("CRM") - 0.10) < 1e-9


def test_session_move_compounds_after_hours_with_the_session(monkeypatch):
    _patch_quote(
        monkeypatch,
        {
            "marketState": "POST",
            "regularMarketPrice": 110.0,
            "regularMarketPreviousClose": 100.0,
            "postMarketPrice": 121.0,
        },
    )
    assert abs(_session_move("NVDA") - 0.21) < 1e-9


def test_session_move_falls_back_to_last_completed_session(monkeypatch):
    _patch_quote(
        monkeypatch,
        {
            "marketState": "CLOSED",
            "regularMarketPrice": 105.0,
            "regularMarketPreviousClose": 100.0,
        },
    )
    assert abs(_session_move("MSFT") - 0.05) < 1e-9


def test_session_move_none_when_quote_missing(monkeypatch):
    _patch_quote(monkeypatch, {"marketState": "PRE"})
    assert _session_move("AAPL") is None


def test_session_quote_prices_the_premarket_move(monkeypatch):
    # Earnings gap: the price hero has to show the premarket level, not the
    # last close, and label the session.
    _patch_quote(
        monkeypatch,
        {
            "marketState": "PRE",
            "regularMarketPrice": 500.0,
            "regularMarketPreviousClose": 480.0,
            "preMarketPrice": 435.0,
        },
    )
    quote = session_quote("MDB")
    assert quote["session"] == "pre"
    assert quote["price"] == 435.0
    assert abs(quote["pct"] - (435.0 / 500.0 - 1)) < 1e-9


def test_session_quote_labels_after_hours_but_not_a_shut_market(monkeypatch):
    info = {
        "marketState": "POST",
        "regularMarketPrice": 110.0,
        "regularMarketPreviousClose": 100.0,
        "postMarketPrice": 121.0,
    }
    _patch_quote(monkeypatch, info)
    quote = session_quote("NVDA")
    assert quote["session"] == "post" and quote["price"] == 121.0
    assert abs(quote["pct"] - 0.21) < 1e-9
    # Overnight the last after-hours print still sets the level, but it is not
    # a live session — the hero must not claim "after hours".
    _patch_quote(monkeypatch, {**info, "marketState": "CLOSED"})
    assert session_quote("NVDA")["session"] is None


def test_session_quote_stamps_the_exchange_session(monkeypatch):
    """The date is the point: off-hours `pct` is the last *completed* session,
    and a caller writing prose has no other way to know that."""
    _patch_quote(monkeypatch, {
        "marketState": "CLOSED",
        "regularMarketPrice": 145.59,
        "regularMarketPreviousClose": 136.72,
        # 2026-09-03 20:00 UTC = 16:00 in New York, that session's close.
        "regularMarketTime": 1788465600,
        "exchangeTimezoneName": "America/New_York",
    })
    assert session_quote("NOW")["as_of"] == "2026-09-03"


def test_a_premarket_move_belongs_to_today_not_to_the_last_close(monkeypatch):
    _patch_quote(monkeypatch, {
        "marketState": "PRE",
        "regularMarketPrice": 100.0,
        "regularMarketPreviousClose": 98.0,
        "preMarketPrice": 102.0,
        "regularMarketTime": 1788465600,
        "exchangeTimezoneName": "America/New_York",
    })
    from datetime import date as _date

    quote = session_quote("NOW")
    assert quote["session"] == "pre"
    # Today in New York — the premarket session's own date, not the close's.
    assert quote["as_of"] >= "2026-09-03" and len(quote["as_of"]) == len(
        _date.today().isoformat()
    )


def test_session_quote_none_when_quote_missing(monkeypatch):
    _patch_quote(monkeypatch, {"marketState": "PRE"})
    assert session_quote("AAPL") is None


from stocks.analysis.portfolio import (  # noqa: E402
    fx_share,
    position_value_frames,
)


def test_fx_share_isolates_the_currency_leg():
    """The digest tells a EUR investor how much of a US-heavy day was the
    dollar rather than the companies, so the split has to be exact: what the
    book actually did, minus what it would have done at today's rate."""
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    lived = pd.DataFrame({"A": [1000.0, 1100.0]}, index=idx)     # +100 as lived
    at_todays_rate = pd.DataFrame({"A": [1000.0, 1070.0]}, index=idx)  # +70 price
    assert abs(fx_share(lived, at_todays_rate, 1) - 30.0) < 1e-9
    # A currency that went the other way shows up negative.
    assert abs(fx_share(at_todays_rate, lived, 1) + 30.0) < 1e-9


def test_fx_share_is_none_when_the_window_is_not_covered():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    vals = pd.DataFrame({"A": [1.0, 2.0]}, index=idx)
    assert fx_share(vals, vals, 30) is None
    assert fx_share(pd.DataFrame(), vals, 1) is None
    assert fx_share(vals, pd.DataFrame(), 1) is None


class _Pos:
    def __init__(self, ticker, quantity, currency):
        self.ticker, self.quantity, self.currency = ticker, quantity, currency


def test_position_value_frames_freezes_fx_at_the_last_rate(monkeypatch):
    """One fetch, two readings: the second frame must move only when a price
    moves, so a same-price/different-rate day reads as flat in it."""
    idx = pd.to_datetime(["2024-01-01", "2024-01-02"])
    monkeypatch.setattr(
        "stocks.analysis.portfolio.load_closes",
        lambda tickers, period="1y": {
            "US": pd.Series([100.0, 110.0], index=idx),
            "EU": pd.Series([50.0, 50.0], index=idx),
        },
    )
    monkeypatch.setattr(
        "stocks.data.fx.rates_range",
        lambda start, end, base, quote: {"2024-01-01": 0.90, "2024-01-02": 1.00},
    )
    positions = [_Pos("US", 10, "USD"), _Pos("EU", 4, "EUR")]
    values, frozen = position_value_frames(positions, base="EUR")

    # Lived: 10 * 100 * 0.90 = 900 -> 10 * 110 * 1.00 = 1100.
    assert abs(values["US"].iloc[0] - 900.0) < 1e-9
    assert abs(values["US"].iloc[1] - 1100.0) < 1e-9
    # At today's rate throughout: 1000 -> 1100, so only the price shows.
    assert abs(frozen["US"].iloc[0] - 1000.0) < 1e-9
    assert abs(frozen["US"].iloc[1] - 1100.0) < 1e-9
    # A base-currency position is identical in both frames.
    assert list(frozen["EU"]) == list(values["EU"]) == [200.0, 200.0]
    # 200 of the 300 the book gained was the dollar.
    assert abs(fx_share(values, frozen, 1) - 100.0) < 1e-9


def test_position_value_frames_empty_without_prices(monkeypatch):
    monkeypatch.setattr(
        "stocks.analysis.portfolio.load_closes", lambda tickers, period="1y": {}
    )
    values, frozen = position_value_frames([_Pos("X", 1, "EUR")])
    assert values.empty and frozen.empty


def test_complete_download_refuses_a_gutted_bulk_download():
    """Yahoo drops a throttled symbol from `yf.download` silently; cached
    as-is, 46 of 51 positions read n/d. A few absentees (delisted names) pass,
    a majority raises so no cache keeps it."""
    import pytest
    from yfinance.exceptions import YFRateLimitError

    from stocks.analysis.portfolio import complete_download

    tickers = [f"T{i}" for i in range(20)]
    s = pd.Series([1.0])
    few_missing = {t: s for t in tickers[:16]}
    assert complete_download(few_missing, tickers) is few_missing
    with pytest.raises(YFRateLimitError):
        complete_download({t: s for t in tickers[:5]}, tickers)


def test_complete_download_does_not_count_names_yahoo_disowned():
    """A 17-name book with 9 bare broker codes Yahoo answered "No data found"
    for read as gutted on every attempt: nothing cached, every page 503'd for
    good. Those names are missing for a reason, so only the rest are judged."""
    import pytest
    from yfinance.exceptions import YFRateLimitError

    from stocks.analysis.portfolio import complete_download
    from stocks.data import fetch

    listed = [f"L{i}" for i in range(8)]
    codes = [f"C{i}" for i in range(9)]
    s = pd.Series([1.0])
    priced = {t: s for t in listed}
    with pytest.raises(YFRateLimitError):
        complete_download(priced, listed + codes)
    fetch._unlisted.update(codes)
    assert complete_download(priced, listed + codes) is priced
    # The rest are still judged: a Yahoo refusing the listed ones is weather.
    with pytest.raises(YFRateLimitError):
        complete_download({t: s for t in listed[:3]}, listed + codes)


from stocks.analysis.portfolio import flow_matched_curves  # noqa: E402


def test_flow_matched_curves_invests_each_buy_on_its_own_day():
    """1000 on each of three days: the index gets 1000 on each of those days,
    not 3000 on the first — so a rally before the later buys only pays on the
    money that was already in."""
    axis = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    flows = pd.Series([1000.0, 1000.0, 1000.0], index=axis)
    value = pd.Series([1000.0, 2000.0, 3000.0], index=axis)  # the book stood still
    index_move = pd.Series([0.0, 0.10, 0.0], index=axis)
    invested, book, shadows = flow_matched_curves(
        value, flows, axis, {"SPY": index_move}
    )
    assert list(invested) == [1000.0, 2000.0, 3000.0]
    assert list(book) == [0.0, 0.0, 0.0]
    # Only the first 1000 caught the +10%: 1100 + 1000 + 1000 over 3000 in.
    assert shadows["SPY"].iloc[-1] == pytest.approx(100 / 3000)


def test_flow_matched_curves_sales_withdraw_and_weekends_wait():
    """A sale takes the same euros out of the shadow; a Saturday buy lands on
    Monday's close; a sale bigger than the shadow empties it, never below."""
    axis = pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09"])  # Fri, Mon, Tue
    value = pd.Series([1000.0, 1500.0, 0.0], index=axis)
    flows = pd.Series(
        [1000.0, 500.0, -5000.0],
        index=pd.to_datetime(["2024-01-05", "2024-01-06", "2024-01-09"]),
    )
    moves = pd.Series([0.0, 0.0, 0.0], index=axis)
    invested, _, shadows = flow_matched_curves(value, flows, axis, {"X": moves})
    assert list(invested) == [1000.0, 1500.0, -3500.0]
    assert shadows["X"].iloc[1] == pytest.approx(0.0)
    assert math.isnan(shadows["X"].iloc[2])  # nothing left in: no line


def test_flow_matched_curves_window_opens_at_the_books_value():
    """A window starting mid-history buys in at what the book was worth then,
    and the start day's own flows are already inside that value."""
    days = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    value = pd.Series([500.0, 2000.0, 2200.0], index=days)
    flows = pd.Series([500.0, 1000.0], index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    axis = days[1:]
    invested, book, shadows = flow_matched_curves(
        value, flows, axis, {"B": pd.Series([0.0, 0.05], index=axis)}
    )
    assert list(invested) == [2000.0, 2000.0]
    assert list(book) == pytest.approx([0.0, 0.1])
    assert list(shadows["B"]) == pytest.approx([0.0, 0.05])


from stocks.analysis.portfolio import Sleeve, project_sleeves, sleeve_stats  # noqa: E402


def _one(value, growth, vol, share=1.0, key="stocks"):
    return Sleeve(key=key, value=value, growth=growth, volatility=vol, share=share)


def test_project_sleeves_without_volatility_is_plain_compounding():
    fan, finals = project_sleeves([_one(1000.0, 0.10, 0.0)], years=2)
    assert len(fan) == 25
    assert fan["p10"].iloc[-1] == pytest.approx(1000 * 1.1**2)
    assert finals == pytest.approx(1000 * 1.1**2)


def test_project_sleeves_growth_is_the_median_compound_rate():
    """"4% a year" is what the typical path does: the median lands on it
    however volatile the sleeve, and the spread opens around it."""
    fan, _ = project_sleeves([_one(1000.0, 0.04, 0.30)], years=5, paths=20000)
    assert fan["p50"].iloc[-1] == pytest.approx(1000 * 1.04**5, rel=0.02)
    assert fan["p10"].iloc[-1] < fan["p50"].iloc[-1] < fan["p90"].iloc[-1]


def test_project_sleeves_splits_contributions_and_deflates():
    sleeves = [_one(0.0, 0.0, 0.0, 0.75), _one(0.0, 0.0, 0.0, 0.25, "crypto")]
    fan, _ = project_sleeves(sleeves, monthly=100.0, years=1)
    assert fan["p50"].iloc[-1] == pytest.approx(1200.0)
    assert list(fan["contributed"])[:3] == [0.0, 100.0, 200.0]
    real, _ = project_sleeves(sleeves, monthly=100.0, years=1, inflation=0.02)
    assert real["p50"].iloc[-1] == pytest.approx(1200.0 / 1.02)


def test_sleeve_stats_measures_each_block_on_its_own_calendar():
    """Crypto every day, stocks on weekdays only: the stock sleeve's weekend
    rows are missing, not zero moves, and do not shrink its volatility."""
    days = pd.date_range("2024-01-01", periods=140, freq="D")
    rng = np.random.default_rng(1)
    stock = pd.Series(rng.normal(0, 0.01, len(days)), index=days)
    stock[days.dayofweek >= 5] = np.nan
    coin = pd.Series(rng.normal(0, 0.04, len(days)), index=days)
    returns = pd.DataFrame({"AAPL": stock, "BTC-EUR": coin})
    vols, corr = sleeve_stats(
        returns,
        {"AAPL": 0.8, "BTC-EUR": 0.2},
        {"stocks": ["AAPL"], "crypto": ["BTC-EUR"]},
    )
    assert vols["stocks"] == pytest.approx(0.01 * 252**0.5, rel=0.2)
    assert vols["crypto"] > 3 * vols["stocks"]
    assert corr is not None and abs(corr) < 0.5
