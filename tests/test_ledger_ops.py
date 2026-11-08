"""One request, one set of operations: what the chat and the connector share
when they rename, move or fix rows, and how the book's refusals are told."""

import pytest

from stocks import watchlist as wl
from stocks.portfolio import edits, ledger, ledger_ops
from stocks.portfolio.ledger import Transaction

DEGIRO = Transaction("2024-03-01", "ES0171996087", "buy", 100, 8.0, "EUR", 0.0,
                     "degiro GRIFOLS", id=1)
IBKR = Transaction("2026-08-20", "GRF.MC", "buy", 50, 8.0, "EUR", 0.0, "ibkr", id=2)
BANK = Transaction("2025-01-02", "SAN.PA", "buy", 10, 4.0, "EUR", 0.0, "ibkr", id=3)
OTHER = Transaction("2025-01-03", "SAN", "buy", 10, 4.0, "USD", 0.0, "ibkr", id=4)
ROWS = [DEGIRO, IBKR, BANK, OTHER]


def test_a_label_renames_only_rows_stored_under_it():
    got = ledger_ops.rename(ROWS, "san.mc", label="san")
    assert [t.id for t in got.rows] == [4]
    assert got.ops == [{"op": "relabel", "ids": [4], "to": "SAN.MC"}]


def test_a_company_name_falls_back_to_the_generous_match():
    def symbol(label):
        return "GRF.MC" if label.startswith("ES") else label

    got = ledger_ops.rename(ROWS, "GRF.MC", label="GRF.MC", broker="degiro",
                            resolve=symbol)
    assert [t.id for t in got.rows] == [1]


def test_rows_already_under_the_target_are_left_out():
    got = ledger_ops.rename(ROWS, "GRF.MC", ids=[1, 2])
    assert got.ops == [{"op": "relabel", "ids": [1], "to": "GRF.MC"}]
    assert not ledger_ops.rename(ROWS, "GRF.MC", label="GRF.MC").ops


def test_an_unknown_id_stays_in_the_edit_so_the_plan_refuses_it():
    got = ledger_ops.rename(ROWS, "X", ids=[1, 99])
    assert got.ops[0]["ids"] == [1, 99]


def test_a_transfer_sets_both_legs_and_may_relabel_them():
    assert ledger_ops.transfer_ops([1], [2], "grf.mc") == [
        {"op": "set_action", "ids": [1], "action": "transfer_out"},
        {"op": "set_action", "ids": [2], "action": "transfer_in"},
        {"op": "relabel", "ids": [1, 2], "to": "GRF.MC"},
    ]
    assert len(ledger_ops.transfer_ops([1])) == 1


def test_a_finding_key_that_is_gone_is_refused_in_words(tmp_path):
    db = tmp_path / "p.db"
    ledger.add_many([DEGIRO], db)
    with pytest.raises(edits.EditError, match="No such finding"):
        ledger_ops.fix_by_key(ledger.all_transactions(db), "transfer:1-2", db)


@pytest.mark.parametrize("error, status, kind", [
    (edits.EditError("x"), 422, "invalid"),
    (edits.Stale("x"), 409, "stale"),
    (edits.Conflict("x"), 409, "conflict"),
    (edits.Missing("x"), 404, "gone"),
])
def test_a_refusal_says_how_each_surface_should_treat_it(error, status, kind):
    assert (error.status, error.kind) == (status, kind)
    assert isinstance(error, edits.EditError)


def test_undoing_a_change_the_history_lacks_is_a_missing_error(tmp_path):
    with pytest.raises(edits.Missing):
        edits.undo(5, path=tmp_path / "p.db")


def test_alert_rules_are_validated_the_same_whoever_writes_them():
    above = {"type": "above", "price": 100}
    with pytest.raises(wl.AlertError, match="nope"):
        wl.add_alerts([], [{"type": "nope", "price": 1}])
    with pytest.raises(wl.AlertError, match="nope"):
        wl.replace_alerts([above, {"type": "nope", "price": 1}])


def test_adding_alerts_merges_and_replacing_replaces():
    above, below = {"type": "above", "price": 100}, {"type": "below", "price": 80}
    again = {"type": "above", "price": 100.0}
    assert wl.add_alerts([above], [again, below]) == [above, below]
    assert wl.replace_alerts([below, {**below, "pct": None}, {"price": 5}]) == [below]
