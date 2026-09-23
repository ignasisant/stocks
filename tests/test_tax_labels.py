"""Tax inputs have to be keyed the way the replay keys them.

`positions.build` relabels the ledger before replaying it
(`transfers.normalize`), so a `RealizedSale` carries one label per security.
The raw ledger does not: a book fed by two brokers spells the same holding two
ways — DEGIRO exports have no ticker column and book under the ISIN, IBKR uses
the symbol.

Anything a jurisdiction looks up by a sale's ticker therefore has to be built
from the relabelled rows. Built by hand from the raw ones, every repurchase
rule — Spain's two months, the US wash sale, Ireland's four weeks, Canada's
superficial loss — silently stops firing for such a security: the buy-back is
filed under a key nobody asks for, the loss is reported as deductible, and
nothing in the output says it happened. That is an under-declaration, which is
why these tests exist rather than a comment.
"""

from __future__ import annotations

import pytest

from stocks.portfolio import tax
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import build


def _two_broker_book() -> list[Transaction]:
    """One holding, spelled both ways, sold at a loss and bought straight back.

    The transfer is what makes the replay settle on the symbol for the whole
    security — and it is the buy-back, placed at the old broker under the old
    spelling, that the repurchase rule has to see.
    """
    isin, note = "US0378331005", "ISIN US0378331005"
    return [
        Transaction("2024-01-02", isin, "buy", 10, 100.0, "EUR", 1.0, note=note),
        Transaction("2024-02-01", isin, "transfer_out", 10, 0.0, "EUR", 0.0, note=note),
        Transaction("2024-02-01", "AAPL", "transfer_in", 10, 0.0, "EUR", 0.0, note=note),
        Transaction("2024-06-03", "AAPL", "sell", 10, 60.0, "EUR", 1.0, note=note),
        Transaction("2024-06-24", isin, "buy", 10, 62.0, "EUR", 1.0, note=note),
    ]


def test_acquisitions_are_keyed_the_way_a_sale_is():
    txs = _two_broker_book()
    _, realized = build(txs, base="EUR", matching="fifo")
    assert {s.ticker for s in realized} == {"AAPL"}
    assert set(tax.buy_dates(txs)) == {"AAPL"}


def test_a_repurchase_under_the_other_spelling_still_blocks_the_loss():
    """The regression this module exists for.

    Keyed the raw way the buy-back is invisible, the two-month rule never
    fires, and the whole loss comes back deductible.
    """
    txs = _two_broker_book()
    _, realized = build(txs, base="EUR", matching="fifo")
    period = tax.get("es").fiscal_year(
        realized, 2024, tax.buy_dates(txs), tax.TaxSettings()
    )
    assert period.realized_loss > 0
    assert period.disallowed_loss == pytest.approx(period.realized_loss)


def test_building_the_dates_by_hand_is_what_used_to_lose_the_loss():
    """Pins the failure mode itself, so nobody reintroduces it as a shortcut."""
    txs = _two_broker_book()
    _, realized = build(txs, base="EUR", matching="fifo")
    raw: dict[str, list[str]] = {}
    for t in txs:
        if t.action == "buy":
            raw.setdefault(t.ticker, []).append(t.date)
    period = tax.get("es").fiscal_year(realized, 2024, raw, tax.TaxSettings())
    assert period.realized_loss > 0
    assert period.disallowed_loss == 0  # the bug, kept visible


def test_only_purchases_count_as_acquisitions():
    """A transfer leg is not a buy: treating it as one would block a loss on a
    reacquisition that never happened."""
    dates = tax.buy_dates(_two_broker_book())
    assert dates["AAPL"] == ["2024-01-02", "2024-06-24"]


def test_the_fund_set_is_keyed_the_same_way():
    """Germany exempts 30% of a fund's result by testing a sale's ticker against
    that set, so it has to be spelled the way the sale is."""
    assert tax.labels(_two_broker_book()) == ["AAPL"]


def test_an_empty_ledger_is_empty_not_an_error():
    assert tax.buy_dates([]) == {}
    assert tax.labels([]) == []
