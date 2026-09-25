"""Broker fees + spread estimation (stocks.portfolio.fees)."""

import pandas as pd

from stocks.portfolio.fees import (
    broker_of,
    by_broker,
    spread_by_broker,
    stamp_listing_currency,
)
from stocks.portfolio.ledger import Transaction


def _eur(amount: float, currency: str, day: str) -> float:
    return amount * (0.5 if currency == "USD" else 1.0)


def _bars(dates, highs, lows):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"High": highs, "Low": lows, "Close": lows}, index=idx)


def test_broker_of_note_prefix():
    assert broker_of(Transaction("2024-01-01", "A", "buy", note="revolut")) == "revolut"
    assert broker_of(
        Transaction("2024-01-01", "A", "buy", note="revolut crypto BTC")
    ) == "revolut"
    assert broker_of(Transaction("2024-01-01", "A", "buy", note="")) == "manual"


def test_by_broker_groups_and_excludes_dividend_withholding():
    txs = [
        Transaction("2024-01-01", "A", "buy", quantity=10, price=10,
                    currency="EUR", fee=2, note="revolut"),
        Transaction("2024-02-01", "A", "sell", quantity=5, price=12,
                    currency="EUR", fee=1, note="revolut"),
        Transaction("2024-03-01", "B", "buy", quantity=2, price=100,
                    currency="USD", fee=4, note="ibkr"),
        # Standalone charge (custody): amount rides the fee field.
        Transaction("2024-04-01", "B", "fee", currency="EUR", fee=3, note="ibkr"),
        # Dividend withholding must NOT count as a broker fee.
        Transaction("2024-05-01", "A", "dividend", price=50, currency="EUR",
                    fee=7.5, note="revolut"),
    ]
    out = by_broker(txs, to_base=_eur)
    rev, ibkr = out["revolut"], out["ibkr"]
    assert rev.trades == 2
    assert abs(rev.volume - 160.0) < 1e-9  # 100 buy + 60 sell
    assert abs(rev.commission - 3.0) < 1e-9
    assert rev.other_fees == 0.0
    assert ibkr.trades == 1
    assert abs(ibkr.volume - 100.0) < 1e-9  # 200 USD @ 0.5
    assert abs(ibkr.commission - 2.0) < 1e-9  # 4 USD @ 0.5
    assert abs(ibkr.other_fees - 3.0) < 1e-9
    assert abs(ibkr.explicit - 5.0) < 1e-9


def test_spread_vs_session_midpoint():
    txs = [
        # Mid = 10: buy at 10.2 costs 0.2/share, sell at 9.9 costs 0.1/share.
        Transaction("2024-01-02", "A", "buy", quantity=10, price=10.2,
                    currency="EUR", note="revolut"),
        Transaction("2024-01-03", "A", "sell", quantity=10, price=9.9,
                    currency="EUR", note="revolut"),
        # No bar on this date -> skipped, not guessed.
        Transaction("2024-01-04", "A", "buy", quantity=1, price=10,
                    currency="EUR", note="revolut"),
    ]
    bars = {"A": _bars(["2024-01-02", "2024-01-03"], [11, 11], [9, 9])}
    out = spread_by_broker(txs, bars, to_base=_eur)
    s = out["revolut"]
    assert s.measured == 2 and s.skipped == 1
    assert abs(s.spread - 3.0) < 1e-9  # 0.2*10 + 0.1*10
    assert abs(s.measured_volume - 201.0) < 1e-9
    assert s.outside_range == 0.0
    assert abs(s.spread_bps - 3.0 / 201.0 * 1e4) < 1e-6


def test_spread_outside_range_is_definite_markup():
    txs = [
        Transaction("2024-01-02", "A", "buy", quantity=2, price=10.7,
                    currency="EUR", note="revolut"),
    ]
    bars = {"A": _bars(["2024-01-02"], [10.5], [9.5])}
    s = spread_by_broker(txs, bars, to_base=_eur)["revolut"]
    assert abs(s.spread - 1.4) < 1e-9  # (10.7 - 10) * 2
    assert abs(s.outside_range - 0.4) < 1e-9  # (10.7 - 10.5) * 2


def test_spread_split_adjusts_pre_split_trades():
    # Bought at 100 pre-split; Yahoo's bars after a 4:1 split show ~25.
    txs = [
        Transaction("2024-01-02", "A", "buy", quantity=1, price=100.0,
                    currency="EUR", note="revolut"),
        Transaction("2024-06-01", "A", "split", quantity=4),
    ]
    bars = {"A": _bars(["2024-01-02"], [26], [24])}  # split-adjusted mid = 25
    s = spread_by_broker(txs, bars, to_base=_eur)["revolut"]
    # Adjusted execution 25 == mid -> no spread; EUR value preserved.
    assert abs(s.spread) < 1e-9
    assert abs(s.measured_volume - 100.0) < 1e-9


def test_spread_sign_can_be_negative():
    txs = [
        Transaction("2024-01-02", "A", "buy", quantity=10, price=9.5,
                    currency="EUR", note="degiro extra"),
    ]
    bars = {"A": _bars(["2024-01-02"], [11], [9])}
    s = spread_by_broker(txs, bars, to_base=_eur)["degiro"]
    assert abs(s.spread - (-5.0)) < 1e-9  # bought below mid


def test_spread_converts_bars_listed_in_another_currency():
    """The alias bug: a dollar ADR fill (Revolut ``ASML``) priced against the
    euro listing the alias resolves to (``ASML.AS``). Uncorrected, $720 vs a
    EUR 360 mid read as a 100% spread; converted at the day's rate (USD = 0.5
    EUR here, so EUR 360 = $720) it is none."""
    txs = [
        Transaction("2024-10-24", "ASML", "buy", quantity=2, price=720.0,
                    currency="USD", note="revolut"),
    ]
    bars = stamp_listing_currency(
        {"ASML": _bars(["2024-10-24"], [362.0], [358.0])}, {"ASML": "EUR"}
    )
    s = spread_by_broker(txs, bars, to_base=_eur)["revolut"]
    assert s.measured == 1 and s.skipped == 0
    assert abs(s.spread) < 1e-9
    assert abs(s.measured_volume - 720.0) < 1e-9  # 1440 USD in EUR


def test_spread_scales_minor_unit_listings():
    # London quotes in pence: a 1000p bar is a GBP 10 share.
    txs = [
        Transaction("2024-01-02", "SHEL", "buy", quantity=10, price=10.1,
                    currency="GBP", note="ibkr"),
    ]
    bars = stamp_listing_currency(
        {"SHEL": _bars(["2024-01-02"], [1010.0], [990.0])}, {"SHEL": "GBp"}
    )
    s = spread_by_broker(txs, bars, to_base=lambda a, c, d: a)["ibkr"]
    assert s.measured == 1
    assert abs(s.spread - 1.0) < 1e-9  # (10.1 - 10.0) * 10


def test_unstamped_bars_keep_the_execution_currency():
    # No listing currency known: same arithmetic as before the conversion.
    txs = [
        Transaction("2024-01-02", "A", "buy", quantity=1, price=10.2,
                    currency="USD", note="revolut"),
    ]
    bars = {"A": _bars(["2024-01-02"], [10.5], [9.5])}
    s = spread_by_broker(txs, bars, to_base=_eur)["revolut"]
    assert abs(s.spread - 0.1) < 1e-9  # (10.2 - 10) USD * 0.5


def test_fill_far_outside_the_day_is_skipped_not_measured():
    """A price no broker markup explains (the sample statement's made-up NVDA
    fill, a missing split row) must not swamp the book's estimate."""
    txs = [
        Transaction("2024-01-02", "A", "buy", quantity=1, price=10.0,
                    currency="EUR", note="revolut"),
        Transaction("2024-01-03", "A", "sell", quantity=1, price=7.0,
                    currency="EUR", note="revolut"),
    ]
    bars = {"A": _bars(["2024-01-02", "2024-01-03"], [10.5, 10.5], [9.5, 9.5])}
    s = spread_by_broker(txs, bars, to_base=_eur)["revolut"]
    assert (s.measured, s.skipped) == (1, 1)
    assert abs(s.spread) < 1e-9 and s.outside_range == 0.0
