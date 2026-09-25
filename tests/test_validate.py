"""Validation-layer tests — pure, no network, no real ledger DB."""

from datetime import date

from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult
from stocks.portfolio.validate import resolve_splits, validate

TODAY = date(2026, 8, 2)
KNOWN = {"AAPL", "SEZL", "GOOG"}


def _buy(ticker="AAPL", day="2025-01-03", qty=5.0, price=100.0):
    return Transaction(date=day, ticker=ticker, action="buy", quantity=qty, price=price)


def _sell(ticker="AAPL", day="2025-06-01", qty=2.0, price=150.0):
    return Transaction(date=day, ticker=ticker, action="sell", quantity=qty, price=price)


def _result(txs, skipped=None):
    return ParseResult(transactions=list(txs), skipped=list(skipped or []))


def test_clean_batch_is_importable():
    v = validate(_result([_buy(), _sell()]), [], known=KNOWN, today=TODAY)
    assert len(v.importable) == 2
    assert not v.rejected and not v.flagged


def test_future_and_ancient_dates_rejected():
    v = validate(
        _result([_buy(day="2026-12-31"), _buy(day="1985-01-01", ticker="GOOG")]),
        [],
        known=KNOWN,
        today=TODAY,
    )
    msgs = [i.message for c in v.rejected for i in c.errors]
    assert any("future" in m for m in msgs)
    assert any("predates" in m for m in msgs)
    assert v.importable == []


def test_unknown_ticker_warns_but_imports():
    v = validate(_result([_buy(ticker="DHER")]), [], known=KNOWN, today=TODAY)
    assert len(v.importable) == 1
    assert len(v.flagged) == 1
    assert "DHER" in v.flagged[0].warnings[0].message


def test_lookup_rescues_unknown_ticker():
    v = validate(
        _result([_buy(ticker="RMS.PA")]),
        [],
        known=set(KNOWN),
        lookup=lambda t: True,
        today=TODAY,
    )
    assert not v.flagged and len(v.importable) == 1


def test_malformed_ticker_rejected():
    v = validate(_result([_buy(ticker="TOOLONGSYM")]), [], known=KNOWN, today=TODAY)
    assert len(v.rejected) == 1
    assert "malformed" in v.rejected[0].errors[0].message


def test_oversell_rejected_including_prior_ledger():
    prior = [_buy(qty=3)]
    v = validate(
        _result([_sell(qty=5, day="2025-06-01")]), prior, known=KNOWN, today=TODAY
    )
    assert len(v.rejected) == 1
    assert "exceeds" in v.rejected[0].errors[0].message


def test_sell_covered_by_prior_ledger_passes():
    prior = [_buy(qty=10)]
    v = validate(_result([_sell(qty=5)]), prior, known=KNOWN, today=TODAY)
    assert not v.rejected


def test_duplicate_against_ledger_warns():
    prior = [_buy()]
    v = validate(_result([_buy()]), prior, known=KNOWN, today=TODAY)
    assert len(v.flagged) == 1
    assert "already in ledger" in v.flagged[0].warnings[0].message
    # Importable as ever — but named, so a caller can leave it out.
    assert len(v.importable) == 1
    assert v.fresh == []
    assert len(v.duplicates) == 1


def test_same_trade_at_a_different_price_is_a_near_duplicate():
    """A re-read of one statement prices the same trade off whichever column
    the mapping picked that time; the exact key misses it."""
    v = validate(_result([_buy(price=100.5)]), [_buy(price=100.0)],
                 known=KNOWN, today=TODAY)
    assert len(v.duplicates) == 1
    assert "read twice" in v.duplicates[0].warnings[0].message


def test_a_batch_repeating_itself_flags_its_own_repeat():
    v = validate(_result([_buy(), _buy()]), [], known=KNOWN, today=TODAY)
    assert len(v.fresh) == 1
    assert len(v.duplicates) == 1


def test_partial_fills_of_one_order_survive_the_duplicate_check():
    """Two 1-share fills a minute apart price the same order differently, so
    the loose key calls the second a near-duplicate. Dropping it leaves the
    later sale short, which is the proof it was a real fill."""
    v = validate(
        _result([
            _buy(qty=1.0, price=248.645),
            _buy(qty=1.0, price=248.445),
            _sell(qty=2.0),
        ]),
        [],
        known=KNOWN,
        today=TODAY,
    )
    assert not v.duplicates
    assert not v.rejected
    assert len(v.fresh) == 3


def test_a_true_repeat_is_still_dropped_when_the_book_closes_without_it():
    """The rescue is arithmetic, not amnesty: a repeat the sale does not need
    stays a duplicate."""
    v = validate(
        _result([_buy(qty=1.0, price=248.645), _buy(qty=1.0, price=248.445)]),
        [],
        known=KNOWN,
        today=TODAY,
    )
    assert len(v.duplicates) == 1
    assert len(v.fresh) == 1


def test_oversell_survives_a_dropped_duplicate_that_cannot_cover_it():
    """Restoring the duplicate still leaves the sale short, so the error stands."""
    v = validate(
        _result([_buy(qty=1.0, price=100.5), _buy(qty=1.0, price=100.0),
                 _sell(qty=9.0)]),
        [],
        known=KNOWN,
        today=TODAY,
    )
    assert len(v.rejected) == 1
    assert "exceeds" in v.rejected[0].errors[0].message


def test_two_same_day_dividends_are_not_duplicates():
    """No share count to key on, and a broker paying twice in a day is
    ordinary — only the exact check applies to these."""
    div = [
        Transaction(date="2025-03-01", ticker="AAPL", action="dividend",
                    quantity=0.0, price=12.0),
        Transaction(date="2025-03-01", ticker="AAPL", action="dividend",
                    quantity=0.0, price=4.5),
    ]
    v = validate(_result(div), [], known=KNOWN, today=TODAY)
    assert len(v.fresh) == 2
    assert not v.duplicates


def test_split_ratio_derived_from_held_quantity():
    # Real SEZL sequence: hold 6.20009223, split adds 31.00046115 -> exactly 6:1.
    txs = [
        _buy(ticker="SEZL", day="2025-02-24", qty=5.84960108, price=294.55),
        _sell(ticker="SEZL", day="2025-03-07", qty=5.84960108, price=220.99),
        _buy(ticker="SEZL", day="2025-03-28", qty=6.20009223, price=209.67),
    ]
    skipped = [
        {
            "row": 9, "type": "STOCK SPLIT", "reason": "stock split",
            "date": "2025-03-31", "ticker": "SEZL",
            "quantity": 31.00046115, "amount": 0.0, "currency": "USD",
        }
    ]
    result = _result(txs, skipped)
    v = validate(result, [], known=KNOWN, today=TODAY)
    splits = [t for t in v.importable if t.action == "split"]
    assert len(splits) == 1
    assert splits[0].quantity == 6.0
    assert splits[0].date == "2025-03-31"
    assert result.skipped == []  # resolved rows leave the skipped list


def test_underivable_split_stays_skipped():
    skipped = [
        {
            "row": 2, "type": "STOCK SPLIT", "reason": "stock split",
            "date": "2025-03-31", "ticker": "SEZL",
            "quantity": 10.0, "amount": 0.0, "currency": "USD",
        }
    ]
    result = _result([], skipped)  # nothing held -> no ratio
    assert resolve_splits(result, []) == []
    assert "underivable" in result.skipped[0]["reason"]


def test_sell_after_derived_split_not_flagged_as_oversell():
    txs = [
        _buy(ticker="SEZL", day="2025-03-28", qty=6.20009223, price=209.67),
        _sell(ticker="SEZL", day="2025-05-07", qty=20.0, price=100.59),
    ]
    skipped = [
        {
            "row": 5, "type": "STOCK SPLIT", "reason": "stock split",
            "date": "2025-03-31", "ticker": "SEZL",
            "quantity": 31.00046115, "amount": 0.0, "currency": "USD",
        }
    ]
    v = validate(_result(txs, skipped), [], known=KNOWN, today=TODAY)
    assert not v.rejected  # 6.2 held × 6 = 37.2 covers the 20-share sell


# ---------------------------------------------------------------- market splits
def _amzn_splits(ticker):
    return [("1999-09-02", 2.0), ("2022-06-06", 20.0)]


def test_oversell_rescued_by_a_market_split():
    """The statement prints the pre-split buy and the post-split sell and no
    corporate action between them — Yahoo's split is what closes the gap."""
    batch = [
        _buy(ticker="AMZN", day="2022-05-24", qty=1, price=2050),
        _sell(ticker="AMZN", day="2024-12-31", qty=20, price=221),
    ]
    v = validate(
        _result(batch), [], known={"AMZN"}, splits=_amzn_splits, today=TODAY
    )
    assert not v.rejected
    added = [c for c in v.checked if c.tx.action == "split"]
    assert len(added) == 1
    assert (added[0].tx.date, added[0].tx.quantity) == ("2022-06-06", 20.0)
    # It travels with the batch: the ledger needs it too, or positions.py
    # replays the same shortfall after the commit.
    assert added[0].tx in v.fresh
    assert "2022-06-06" in added[0].warnings[0].message


def test_split_outside_the_held_window_is_not_applied():
    """A split that predates the first buy changed nothing the user holds."""
    batch = [
        _buy(ticker="AMZN", day="2023-01-03", qty=1, price=100),
        _sell(ticker="AMZN", day="2023-06-01", qty=20, price=120),
    ]
    v = validate(
        _result(batch), [], known={"AMZN"}, splits=_amzn_splits, today=TODAY
    )
    assert len(v.rejected) == 1
    assert "exceeds" in v.rejected[0].errors[0].message
    assert not [c for c in v.checked if c.tx.action == "split"]


def test_split_already_in_the_ledger_is_not_added_twice():
    prior = [
        Transaction(date="2022-05-24", ticker="AMZN", action="buy",
                    quantity=1, price=2050),
        Transaction(date="2022-06-06", ticker="AMZN", action="split",
                    quantity=20),
    ]
    v = validate(
        _result([_sell(ticker="AMZN", day="2024-12-31", qty=20, price=221)]),
        prior,
        known={"AMZN"},
        splits=_amzn_splits,
        today=TODAY,
    )
    assert not v.rejected
    assert not [c for c in v.checked if c.tx.action == "split"]


def test_split_lookup_that_cannot_answer_leaves_the_error_standing():
    def boom(ticker):
        raise RuntimeError("yahoo said no")

    v = validate(
        _result([_sell(qty=5)]), [_buy(qty=1)], known=KNOWN, splits=boom,
        today=TODAY,
    )
    assert len(v.rejected) == 1
    assert "exceeds" in v.rejected[0].errors[0].message


def test_issues_carry_a_catalog_key_and_its_parameters():
    """The web app translates key/params; `message` is the English fallback."""
    v = validate(
        _result([_sell(qty=5)]), [_buy(qty=1)], known=KNOWN, today=TODAY
    )
    issue = v.rejected[0].errors[0]
    assert issue.key == "validate.oversell"
    assert issue.params["quantity"] == "5" and issue.params["held"] == "1.0000"


# --------------------------------------------------------------- crypto pairs

def test_a_long_coin_pair_is_not_a_malformed_ticker():
    """CHILLGUY-EUR is eight characters of coin; the symbol rule stops at six."""
    result = ParseResult(transactions=[
        Transaction(date="2025-05-08", ticker="CHILLGUY-EUR", action="buy",
                    quantity=9302.5, price=0.05, currency="EUR"),
    ])
    checked = validate(result, [], known=set())
    assert not checked.rejected
    assert [tx.ticker for tx in checked.importable] == ["CHILLGUY-EUR"]


def test_a_curated_coin_needs_no_watchlist_entry():
    result = ParseResult(transactions=[
        Transaction(date="2025-02-03", ticker="SOL-EUR", action="buy",
                    quantity=5.14, price=194.37, currency="EUR"),
    ])
    checked = validate(result, [], known=set())
    assert not checked.flagged  # no "unknown ticker": crypto is never in EDGAR
