"""Missing-split detection — pure, no network, no ledger DB.

The running example is the real one that prompted the module: one AMZN share
bought on 2022-05-24 at $2050, Amazon's 20:1 split on 2022-06-06, and a
statement that printed the trade and not the split.
"""

import pytest

from stocks.portfolio.corporate import missing_splits, own_fills
from stocks.portfolio.ledger import Transaction

AMZN_SPLITS = [
    ("1998-06-02", 2.0),
    ("1999-01-05", 3.0),
    ("1999-09-02", 2.0),
    ("2022-06-06", 20.0),
]


def _splits(events):
    return lambda ticker: list(events)


def _closes(table):
    """close_on from a {(ticker, day): close} table; unknown days answer None."""
    return lambda ticker, day: table.get((ticker, day))


def _buy(day, qty, price, ticker="AMZN", fee=0.0):
    return Transaction(
        date=day, ticker=ticker, action="buy", quantity=qty, price=price,
        fee=fee, currency="USD",
    )


def _split_row(day, ratio, ticker="AMZN"):
    return Transaction(
        date=day, ticker=ticker, action="split", quantity=ratio, currency="USD",
    )


# The pre-split buy, as the statement printed it, plus a much later one.
RAW_LEDGER = [
    _buy("2022-05-24", 1.0, 2050.0, fee=9.36),
    _buy("2026-02-18", 9.72545587, 205.65),
]
RAW_CLOSES = _closes({("AMZN", "2022-05-24"): 104.10, ("AMZN", "2026-02-18"): 248.0})


def test_finds_the_split_the_statement_never_printed():
    found = missing_splits(
        RAW_LEDGER, splits=_splits(AMZN_SPLITS), close_on=RAW_CLOSES
    )
    assert len(found) == 1
    gap = found[0]
    assert (gap.ticker, gap.tx.date, gap.ratio) == ("AMZN", "2022-06-06", 20.0)
    assert gap.tx.action == "split"
    assert gap.held_before == pytest.approx(1.0)
    assert gap.held_after == pytest.approx(20.0)


def test_split_already_in_the_ledger_is_not_proposed_again():
    ledger = RAW_LEDGER + [_split_row("2022-06-06", 20.0)]
    assert not missing_splits(
        ledger, splits=_splits(AMZN_SPLITS), close_on=RAW_CLOSES
    )


def test_broker_that_already_restated_the_position_is_left_alone():
    """The same money, reported post-split: 20 shares at $102.50. Adding the
    split here would claim 400 shares of a 20-share position."""
    ledger = [_buy("2022-05-24", 20.0, 102.50), _buy("2026-02-18", 9.72545587, 205.65)]
    assert not missing_splits(
        ledger, splits=_splits(AMZN_SPLITS), close_on=RAW_CLOSES
    )


def test_split_before_the_first_buy_changed_nothing_held():
    ledger = [_buy("2026-02-18", 9.72545587, 205.65)]
    assert not missing_splits(
        ledger, splits=_splits(AMZN_SPLITS), close_on=RAW_CLOSES
    )


def test_position_sold_out_before_the_split_is_not_proposed():
    ledger = [
        _buy("2022-05-24", 1.0, 2050.0),
        Transaction(date="2022-06-01", ticker="AMZN", action="sell",
                    quantity=1.0, price=2100.0, currency="USD"),
    ]
    assert not missing_splits(
        ledger, splits=_splits(AMZN_SPLITS), close_on=RAW_CLOSES
    )


def test_no_close_means_no_evidence_and_no_proposal():
    """A throttled Yahoo must not be read as 'the price looks unadjusted'."""
    assert not missing_splits(
        RAW_LEDGER, splits=_splits(AMZN_SPLITS), close_on=lambda t, d: None
    )


def test_lookup_failures_propose_nothing():
    def boom(ticker):
        raise RuntimeError("yahoo down")

    assert not missing_splits(RAW_LEDGER, splits=boom, close_on=RAW_CLOSES)

    def boom_close(ticker, day):
        raise RuntimeError("yahoo down")

    assert not missing_splits(
        RAW_LEDGER, splits=_splits(AMZN_SPLITS), close_on=boom_close
    )


def test_reverse_splits_are_ignored():
    """A 1-for-10 shrinks a position; the broker reports what survives."""
    ledger = [_buy("2020-01-02", 100.0, 5.0, ticker="XYZ")]
    found = missing_splits(
        ledger,
        splits=_splits([("2021-06-01", 0.1)]),
        close_on=_closes({("XYZ", "2020-01-02"): 50.0}),
    )
    assert not found


def test_two_missing_splits_compound():
    """6:1 in total, in two steps, and the second one starts from the first."""
    ledger = [_buy("2018-01-02", 1.0, 600.0, ticker="XYZ")]
    found = missing_splits(
        ledger,
        splits=_splits([("2019-01-02", 2.0), ("2020-01-02", 3.0)]),
        close_on=_closes({("XYZ", "2018-01-02"): 100.0}),
    )
    assert [(m.tx.date, m.ratio) for m in found] == [
        ("2019-01-02", 2.0), ("2020-01-02", 3.0)
    ]
    assert [m.held_before for m in found] == [1.0, 2.0]
    assert found[-1].held_after == pytest.approx(6.0)


def test_only_the_split_the_price_predates_is_proposed():
    """The ledger carries the older split already; the price is still raw, so
    the newer one is the only row it lacks."""
    ledger = [
        _buy("2018-01-02", 1.0, 600.0, ticker="XYZ"),
        _split_row("2019-01-02", 2.0, ticker="XYZ"),
    ]
    found = missing_splits(
        ledger,
        splits=_splits([("2019-01-02", 2.0), ("2020-01-02", 3.0)]),
        close_on=_closes({("XYZ", "2018-01-02"): 100.0}),
    )
    assert [(m.tx.date, m.ratio) for m in found] == [("2020-01-02", 3.0)]
    assert found[0].held_before == pytest.approx(2.0)
    assert found[0].held_after == pytest.approx(6.0)


def test_partly_restated_statement_proposes_only_the_unrestated_split():
    """The broker restated the 2:1 (2 shares at $300) and not the 3:1 after
    it — the quotient names the suffix the price still carries."""
    ledger = [_buy("2018-01-02", 2.0, 300.0, ticker="XYZ")]
    found = missing_splits(
        ledger,
        splits=_splits([("2019-01-02", 2.0), ("2020-01-02", 3.0)]),
        close_on=_closes({("XYZ", "2018-01-02"): 100.0}),
    )
    assert [(m.tx.date, m.ratio) for m in found] == [("2020-01-02", 3.0)]
    assert found[0].held_before == pytest.approx(2.0)


def test_proposed_row_is_a_ledger_ready_split_transaction():
    gap = missing_splits(
        RAW_LEDGER, splits=_splits(AMZN_SPLITS), close_on=RAW_CLOSES
    )[0]
    assert gap.tx.action == "split"
    assert gap.tx.quantity == 20.0  # the ledger stores the ratio in `quantity`
    assert gap.tx.price == 0.0
    assert gap.tx.currency == "USD"
    assert "20:1" in gap.tx.note


def test_applying_the_row_puts_the_position_back_on_today_s_scale():
    """End to end: the basis the ticker page shows before and after the fix."""
    from stocks.portfolio.positions import build

    identity = lambda amount, currency, day: amount  # noqa: E731
    before, _ = build(RAW_LEDGER, to_base=identity, base="USD")
    assert before[0].quantity == pytest.approx(10.72545587)
    assert before[0].avg_cost == pytest.approx(378.48, abs=0.01)  # pre-split price

    found = missing_splits(
        RAW_LEDGER, splits=_splits(AMZN_SPLITS), close_on=RAW_CLOSES
    )
    after, _ = build(RAW_LEDGER + [g.tx for g in found], to_base=identity, base="USD")
    assert after[0].quantity == pytest.approx(29.72545587)
    assert after[0].avg_cost == pytest.approx(136.56, abs=0.01)
    # Same money paid, twenty times the shares behind it.
    assert after[0].cost == pytest.approx(before[0].cost)


# ------------------------------------------- restating trades onto Yahoo's scale


def test_on_market_scale_restates_a_pre_split_trade():
    """What the price chart plots: the $2050 ticket is $102.50 of today's stock."""
    from stocks.portfolio.corporate import on_market_scale, split_factors

    ledger = RAW_LEDGER + [_split_row("2022-06-06", 20.0)]
    factors = split_factors(ledger)
    price, qty = on_market_scale(ledger[0], factors)
    assert price == pytest.approx(102.50)
    assert qty == pytest.approx(20.0)
    # The money the row stands for never moves.
    assert price * qty == pytest.approx(ledger[0].price * ledger[0].quantity)


def test_trades_after_the_split_are_left_where_they_are():
    from stocks.portfolio.corporate import on_market_scale, split_factors

    factors = split_factors(RAW_LEDGER + [_split_row("2022-06-06", 20.0)])
    price, qty = on_market_scale(RAW_LEDGER[1], factors)
    assert (price, qty) == (205.65, pytest.approx(9.72545587))


def test_a_split_on_the_trade_s_own_day_does_not_scale_it():
    """positions.py replays it the same way: a split shares its date with the
    post-split trades, which need no scaling."""
    from stocks.portfolio.corporate import on_market_scale, split_factors

    same_day = _buy("2022-06-06", 20.0, 102.50)
    factors = split_factors([same_day, _split_row("2022-06-06", 20.0)])
    assert on_market_scale(same_day, factors) == (102.50, 20.0)


def test_unsplit_ticker_passes_through_untouched():
    from stocks.portfolio.corporate import on_market_scale, split_factors

    factors = split_factors(RAW_LEDGER)
    assert on_market_scale(RAW_LEDGER[0], factors) == (2050.0, 1.0)


# ------------------------------------------------------- fills drawn on a chart


def test_fills_are_found_under_the_label_the_position_is_built_on():
    """A book fed by two brokers spells one holding two ways: DEGIRO exports
    have no ticker column and book under the ISIN, IBKR uses the symbol.
    `positions.build` unifies them before replaying, so the open position and
    the page's URL speak the unified label while the raw rows do not — and a
    lookup by that label used to match nothing at all."""
    fills = own_fills(
        [
            Transaction(
                "2024-01-02", "US00724F1012", "buy", 5, 500.0, "USD", 1.0,
                note="ISIN US00724F1012",
            ),
            Transaction(
                "2024-06-01", "ADBE", "buy", 3, 450.0, "USD", 1.0,
                note="ISIN US00724F1012",
            ),
        ],
        "ADBE",
    )
    assert [f.date for f in fills] == ["2024-01-02", "2024-06-01"]


def test_fills_come_back_on_todays_share_scale():
    """Ledger prices are as-traded, Yahoo's bars are split-adjusted. A pre-split
    buy plotted raw sits twenty times above the candles it belongs to."""
    fills = own_fills(
        [
            Transaction("2024-01-02", "NVDA", "buy", 10, 400.0, "USD", 1.0),
            Transaction("2024-06-10", "NVDA", "split", 10, 0.0, "USD", 0.0),
            Transaction("2024-08-01", "NVDA", "buy", 5, 110.0, "USD", 1.0),
        ],
        "NVDA",
    )
    # Before the split: 10 @ 400 is 100 @ 40 today. The money is unchanged.
    assert (fills[0].price, fills[0].quantity) == (40.0, 100.0)
    # After it: untouched.
    assert (fills[1].price, fills[1].quantity) == (110.0, 5.0)


def test_only_buys_and_sells_are_fills():
    """A dividend is not a trade, and a split row is an event, not an entry."""
    kinds = {
        f.action
        for f in own_fills(
            [
                Transaction("2024-01-02", "AAPL", "buy", 1, 100.0, "USD", 1.0),
                Transaction("2024-02-02", "AAPL", "dividend", 0, 2.0, "USD", 0.0),
                Transaction("2024-03-02", "AAPL", "split", 4, 0.0, "USD", 0.0),
                Transaction("2024-04-02", "AAPL", "sell", 1, 120.0, "USD", 1.0),
            ],
            "AAPL",
        )
    }
    assert kinds == {"buy", "sell"}


def test_a_transfer_leg_never_becomes_a_purchase_marker():
    """`relabel`, not `normalize`: an unmatched transfer turned into a synthetic
    buy would draw a purchase marker at a price nobody paid."""
    fills = own_fills(
        [Transaction("2024-05-01", "ADBE", "transfer_in", 5, 0.0, "USD", 0.0)],
        "ADBE",
    )
    assert fills == []


def test_a_name_with_no_trades_is_empty_not_an_error():
    assert own_fills([], "AAPL") == []
