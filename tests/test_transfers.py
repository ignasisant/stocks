"""Shares moving between brokers: netting, custody, and pairing the legs."""

from dataclasses import replace
from datetime import date

from stocks.portfolio import custody, positions, transfers
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.statement import ParseResult
from stocks.portfolio.validate import validate

# No FX anywhere in here: every leg of a transfer is in the security's own
# currency, and a converter would only obscure which number came from where.
NO_FX = lambda amount, currency, day: amount  # noqa: E731

BUY = Transaction("2025-07-18", "ASML", "buy", 1, 633.9, "EUR", 4.9, "degiro ASML")
OUT = Transaction("2026-08-06", "ASML", "transfer_out", 1, 1465.8, "EUR", 0,
                  "degiro ASML")
IN = Transaction("2026-09-14", "ASML", "transfer_in", 1, 633.9, "EUR", 0, "ibkr snapshot")


def test_a_matched_pair_realizes_nothing_and_keeps_the_original_basis():
    open_lots, realized = positions.build([BUY, OUT, IN], to_base=NO_FX)
    assert realized == []
    assert [(p.ticker, p.quantity, round(p.cost, 2)) for p in open_lots] == [
        ("ASML", 1.0, 638.8)
    ]


def test_a_matched_pair_keeps_the_acquisition_date_the_shares_were_bought_on():
    """The holding period does not restart: the lot is still the 2025 lot."""
    open_lots, _ = positions.build([BUY, OUT, IN], to_base=NO_FX)
    sold = Transaction("2026-10-01", "ASML", "sell", 1, 1400, "EUR", 0, "ibkr")
    _, realized = positions.build([BUY, OUT, IN, sold], to_base=NO_FX)
    assert [s.buy_date for s in realized] == ["2025-07-18"]
    assert round(realized[0].gain, 2) == round(1400 - 638.8, 2)


def test_every_matching_rule_agrees_a_transfer_is_not_a_disposal():
    for rule in positions.MATCHING_MODES:
        open_lots, realized = positions.build(
            [BUY, OUT, IN], to_base=NO_FX, matching=rule
        )
        assert realized == [], rule
        assert [round(p.cost, 2) for p in open_lots] == [638.8], rule


def test_an_arrival_nothing_departed_opens_the_position_at_its_reported_basis():
    open_lots, realized = positions.build([IN], to_base=NO_FX)
    assert realized == []
    assert [(p.ticker, p.quantity, p.cost) for p in open_lots] == [("ASML", 1.0, 633.9)]


def test_a_departure_with_no_arrival_leaves_the_lot_open():
    """The shares are at a broker whose statements are not imported yet —
    gone from the book would be a loss the account never took."""
    open_lots, realized = positions.build([BUY, OUT], to_base=NO_FX)
    assert realized == []
    assert [(p.ticker, p.quantity) for p in open_lots] == [("ASML", 1.0)]


def test_a_partly_covered_arrival_opens_only_the_shares_nothing_sent():
    """Six arrive, four were sent: two of them are an opening balance."""
    buy = replace(BUY, quantity=4, price=100, fee=0)
    out = replace(OUT, quantity=4)
    arrive = replace(IN, quantity=6, price=100)
    open_lots, realized = positions.build([buy, out, arrive], to_base=NO_FX)
    assert realized == []
    assert [(p.ticker, p.quantity, p.cost) for p in open_lots] == [("ASML", 6.0, 600.0)]


def test_order_of_import_does_not_change_the_answer():
    """Destination statements are routinely imported before source ones."""
    forward, _ = positions.build([BUY, OUT, IN], to_base=NO_FX)
    reversed_, _ = positions.build([IN, OUT, BUY], to_base=NO_FX)
    assert [(p.ticker, p.quantity, p.cost) for p in forward] == [
        (p.ticker, p.quantity, p.cost) for p in reversed_
    ]


def test_custody_moves_the_shares_and_the_basis_to_the_receiving_broker():
    where = custody.by_position([BUY, OUT, IN], to_base=NO_FX)
    assert {b: (c.quantity, round(c.cost, 2)) for b, c in where["ASML"].items()} == {
        "ibkr": (1.0, 638.8)
    }


def test_custody_carries_the_basis_across_rather_than_restating_it():
    """The receiving broker rounds its average cost; the money did not change."""
    arrive = replace(IN, price=999.0)
    where = custody.by_position([BUY, OUT, arrive], to_base=NO_FX)
    assert round(where["ASML"]["ibkr"].cost, 2) == 638.8


def test_custody_opens_an_unpaired_arrival_at_the_reported_basis():
    where = custody.by_position([IN], to_base=NO_FX)
    assert {b: c.quantity for b, c in where["ASML"].items()} == {"ibkr": 1.0}
    assert round(where["ASML"]["ibkr"].cost, 2) == 633.9


def test_a_transfer_moves_no_cash_so_the_return_is_untouched():
    from stocks.analysis.portfolio import flow_series

    moved = flow_series([BUY, OUT, IN], to_base=NO_FX)
    traded = flow_series([BUY], to_base=NO_FX)
    assert list(moved.items()) == list(traded.items())


def test_shares_held_do_not_dip_while_the_shares_are_in_transit():
    from stocks.analysis.portfolio import shares_frame

    frame = shares_frame([BUY, OUT, IN], end="2026-09-20")
    assert frame["ASML"].min() == 1.0


# --------------------------------------------------------------- validation


TODAY = date(2026, 10, 1)


def _validated(*txs):
    return validate(ParseResult(transactions=list(txs)), [], known={"ASML"}, today=TODAY)


def test_selling_shares_that_arrived_by_transfer_is_not_an_oversell():
    sell = Transaction("2026-09-20", "ASML", "sell", 1, 1400, "EUR", 0, "ibkr")
    result = _validated(IN, sell)
    assert [t.action for t in result.importable] == ["transfer_in", "sell"]


def test_selling_more_than_arrived_is_still_an_oversell():
    """The netting is not a licence to sell shares the book never held."""
    sell = Transaction("2026-09-20", "ASML", "sell", 3, 1400, "EUR", 0, "ibkr")
    result = _validated(BUY, OUT, IN, sell)
    assert [c.tx.quantity for c in result.rejected] == [3]


# ------------------------------------------------------------------ pairing


def _ledger(*txs):
    return [replace(t, id=i + 1) for i, t in enumerate(txs)]


def test_pairing_reads_a_carried_over_basis_as_the_transfer_it_is():
    """DEGIRO books the departure as a sale at the market price; IBKR reports
    the basis the shares already had. That mismatch is the whole evidence."""
    sold = Transaction("2026-08-06", "NL0010273215", "sell", 1, 1465.8, "EUR", 0,
                       "degiro ASML HOLDING N.V.")
    arrived = Transaction("2026-09-14", "ASML", "transfer_in", 1, 633.9, "EUR", 0,
                          "ibkr snapshot NL0010273215")
    buy = replace(BUY, ticker="NL0010273215")
    [move] = transfers.propose(_ledger(buy, sold, arrived))
    assert (move.ticker_out, move.ticker_in) == ("NL0010273215", "ASML")
    assert (move.broker_out, move.broker_in) == ("degiro", "ibkr")
    assert move.quantity == 1 and move.rekey
    assert round(move.phantom_gain, 2) == 827.0


def test_pairing_leaves_a_real_sale_and_repurchase_alone():
    """Sold at 587 and bought back at 587: the new basis is the repurchase
    price, which is exactly what a transfer would not report."""
    sold = Transaction("2026-08-03", "US30303M1027", "sell", 8, 587.0, "USD", 0,
                       "degiro META PLATFORMS")
    bought = Transaction("2026-09-14", "META", "transfer_in", 8, 587.125, "USD", 0,
                         "ibkr snapshot US30303M1027")
    buy = Transaction("2025-01-02", "US30303M1027", "buy", 8, 581.8, "USD", 0, "degiro")
    assert transfers.propose(_ledger(buy, sold, bought)) == []


def test_pairing_needs_the_basis_to_be_distinguishable_at_all():
    """Sold at what the shares cost: neither reading is ruled out, so nothing
    is proposed rather than a coin flip."""
    buy = Transaction("2025-01-02", "US1234567890", "buy", 5, 100.0, "USD", 0, "degiro")
    sold = Transaction("2026-01-02", "US1234567890", "sell", 5, 100.5, "USD", 0, "degiro")
    arrived = Transaction("2026-01-05", "XYZ", "transfer_in", 5, 100.0, "USD", 0,
                          "ibkr snapshot US1234567890")
    assert transfers.propose(_ledger(buy, sold, arrived)) == []


def test_pairing_uses_fifo_because_that_is_what_the_broker_reports():
    """The oldest lots were sold off; the basis left behind is nothing like
    the position's lifetime average, and the receiving broker agrees."""
    old = Transaction("2024-01-02", "US1234567890", "buy", 2, 318.33, "USD", 0, "degiro")
    new = Transaction("2025-01-02", "US1234567890", "buy", 10, 261.93, "USD", 0, "degiro")
    sold_old = Transaction("2026-07-20", "US1234567890", "sell", 2, 422.31, "USD", 0,
                           "degiro")
    left = Transaction("2026-08-06", "US1234567890", "sell", 10, 412.75, "USD", 0,
                       "degiro")
    arrived = Transaction("2026-09-14", "UNH", "transfer_in", 10, 261.929, "USD", 0,
                          "ibkr snapshot US1234567890")
    [move] = transfers.propose(_ledger(old, new, sold_old, left, arrived))
    assert move.quantity == 10 and round(move.basis_out, 2) == 261.93


def test_pairing_refuses_a_partial_move():
    """33 left and 30 arrived: something else happened to the other three."""
    buy = Transaction("2025-01-02", "US1234567890", "buy", 33, 96.0, "USD", 0, "degiro")
    left = Transaction("2026-08-14", "US1234567890", "sell", 33, 127.25, "USD", 0,
                       "degiro")
    arrived = Transaction("2026-09-14", "NOW", "transfer_in", 30, 96.17, "USD", 0,
                          "ibkr snapshot US1234567890")
    assert transfers.propose(_ledger(buy, left, arrived)) == []


def test_pairing_refuses_two_rows_at_the_same_broker():
    buy = Transaction("2025-01-02", "AAA", "buy", 5, 10.0, "USD", 0, "degiro")
    left = Transaction("2026-01-02", "AAA", "sell", 5, 50.0, "USD", 0, "degiro")
    arrived = Transaction("2026-01-03", "AAA", "transfer_in", 5, 10.0, "USD", 0,
                          "degiro snapshot")
    assert transfers.propose(_ledger(buy, left, arrived)) == []


def test_pairing_refuses_an_arrival_half_a_year_later():
    buy = Transaction("2025-01-02", "AAA", "buy", 5, 10.0, "USD", 0, "degiro")
    left = Transaction("2026-01-02", "AAA", "sell", 5, 50.0, "USD", 0, "degiro")
    arrived = Transaction("2026-12-30", "AAA", "transfer_in", 5, 10.0, "USD", 0,
                          "ibkr snapshot")
    assert transfers.propose(_ledger(buy, left, arrived)) == []


def test_security_id_reads_the_isin_wherever_the_importer_left_it():
    assert transfers.security_id(replace(IN, note="ibkr snapshot NL0010273215")) == (
        "NL0010273215"
    )
    assert transfers.security_id(replace(IN, ticker="NL0010273215")) == "NL0010273215"
    assert transfers.security_id(replace(IN, note="ibkr snapshot")) == "ASML"


def _isin_map(**pairs):
    """An ISIN -> symbol lookup that records what it was asked."""
    asked: list[str] = []

    def resolve(isin: str) -> str:
        asked.append(isin)
        return pairs.get(isin, "")

    return resolve, asked


def test_pairing_joins_a_book_imported_before_any_of_this_existed():
    """The production case: DEGIRO history under the ISIN, an IBKR balance
    already committed as a plain buy under the symbol, nothing linking them."""
    buy = replace(BUY, ticker="NL0010273215")
    sold = Transaction("2026-08-06", "NL0010273215", "sell", 1, 1465.8, "EUR", 0,
                       "degiro ASML HOLDING N.V.")
    arrived = Transaction("2026-09-14", "ASML", "buy", 1, 633.9, "EUR", 0,
                          "ibkr snapshot")
    resolve, _ = _isin_map(NL0010273215="ASML")
    [move] = transfers.propose(_ledger(buy, sold, arrived), resolve=resolve)
    assert (move.ticker_out, move.ticker_in) == ("NL0010273215", "ASML")
    assert move.rekey and round(move.phantom_gain, 2) == 827.0


def test_two_labels_that_are_not_the_same_company_are_not_joined():
    buy = replace(BUY, ticker="NL0010273215")
    sold = Transaction("2026-08-06", "NL0010273215", "sell", 1, 1465.8, "EUR", 0,
                       "degiro ASML HOLDING N.V.")
    arrived = Transaction("2026-09-14", "SAP", "buy", 1, 633.9, "EUR", 0,
                          "ibkr snapshot")
    resolve, _ = _isin_map(NL0010273215="ASML")
    assert transfers.propose(_ledger(buy, sold, arrived), resolve=resolve) == []


def test_a_lookup_that_cannot_answer_proposes_nothing():
    buy = replace(BUY, ticker="NL0010273215")
    sold = Transaction("2026-08-06", "NL0010273215", "sell", 1, 1465.8, "EUR", 0,
                       "degiro")
    arrived = Transaction("2026-09-14", "ASML", "buy", 1, 633.9, "EUR", 0,
                          "ibkr snapshot")

    def dead(isin: str) -> str:
        raise RuntimeError("Yahoo is down")

    assert transfers.propose(_ledger(buy, sold, arrived), resolve=dead) == []


def test_nothing_is_looked_up_for_a_book_with_nothing_to_repair():
    """The lookup costs a network round-trip the first time an ISIN is seen,
    so it is asked only about rows that already match on every other count."""
    resolve, asked = _isin_map(NL0010273215="ASML")
    transfers.propose(_ledger(replace(BUY, ticker="NL0010273215")), resolve=resolve)
    assert asked == []

    # A sale of the wrong size is not a move, and settles no identity question.
    sold = Transaction("2026-08-06", "NL0010273215", "sell", 1, 1465.8, "EUR", 0,
                       "degiro")
    arrived = Transaction("2026-09-14", "ASML", "buy", 5, 633.9, "EUR", 0,
                          "ibkr snapshot")
    transfers.propose(
        _ledger(replace(BUY, ticker="NL0010273215"), sold, arrived), resolve=resolve
    )
    assert asked == []
