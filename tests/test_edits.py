"""Hand edits to the ledger: planned with their impact, applied whole, undone."""

import sqlite3

import pytest

from stocks.portfolio import edits, ledger
from stocks.portfolio.ledger import Transaction

# A Grifols move the pairing missed: DEGIRO booked the departure as a sale at
# market under the ISIN, IBKR booked the arrival as an ordinary buy at the
# basis it carried, under the symbol.
BUY = Transaction("2024-03-01", "ES0171996087", "buy", 100, 8.0, "EUR", 2.0,
                  "degiro GRIFOLS")
SALE = Transaction("2026-08-06", "ES0171996087", "sell", 100, 12.0, "EUR", 0.0,
                   "degiro GRIFOLS")
ARRIVAL = Transaction("2026-08-20", "GRF.MC", "buy", 100, 8.02, "EUR", 0.0, "ibkr")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "portfolio.db"
    ledger.add_many([BUY, SALE, ARRIVAL], path)
    return path


def ids(db):
    return [t.id for t in ledger.all_transactions(db)]


def test_a_plan_writes_nothing_and_shows_the_rows_it_would_touch(db):
    buy, sale, arrival = ids(db)
    planned = edits.plan([{"op": "delete", "ids": [arrival]}], db)
    assert [(c.id, c.kind) for c in planned.changes] == [(arrival, "deleted")]
    assert len(ledger.all_transactions(db)) == 3
    assert planned.token and planned.ok


def test_the_grifols_repair_turns_two_positions_and_a_phantom_gain_into_one_holding(db):
    _, sale, arrival = ids(db)
    ops = [
        {"op": "set_action", "ids": [sale], "action": "transfer_out"},
        {"op": "set_action", "ids": [arrival], "action": "transfer_in"},
        {"op": "relabel", "ids": [sale, ids(db)[0]], "to": "GRF.MC"},
    ]
    planned = edits.plan(ops, db)
    assert planned.ok
    assert (planned.positions_before, planned.positions_after) == (1, 1)
    # 398 of gain the account never made, gone. The holding itself was right
    # already (the IBKR buy carried the basis), so it is not an effect.
    (effect,) = planned.effects
    assert effect.ticker == "ES0171996087"
    assert effect.realized_before == {"2026": pytest.approx(398.0)}
    assert effect.realized_after == {}

    done = edits.commit(ops, planned.token, source="chat", summary="Grifols", path=db)
    assert {c.kind for c in done.changes} == {"updated"}
    after = {t.id: t for t in ledger.all_transactions(db)}
    assert after[sale].action == "transfer_out" and after[sale].ticker == "GRF.MC"
    assert after[arrival].action == "transfer_in"


def test_undo_puts_back_exactly_what_the_edit_replaced(db):
    before = ledger.all_transactions(db)
    buy, sale, arrival = ids(db)
    ops = [
        {"op": "delete", "ids": [arrival]},
        {"op": "update", "id": sale, "fields": {"price": 11.5}},
        {"op": "add", "row": {"date": "2026-09-01", "ticker": "GRF.MC",
                              "action": "buy", "quantity": 10, "price": 9,
                              "currency": "EUR", "note": "ibkr"}},
    ]
    planned = edits.plan(ops, db)
    done = edits.commit(ops, planned.token, source="api", path=db)
    added = next(c.id for c in done.changes if c.kind == "added")
    assert added > arrival  # the new row has a real id now

    edits.undo(done.id, path=db)
    assert ledger.all_transactions(db) == before
    assert edits.history(db)[0].undone_at


def test_a_stale_token_is_refused(db):
    _, _, arrival = ids(db)
    ops = [{"op": "delete", "ids": [arrival]}]
    planned = edits.plan(ops, db)
    ledger.add(Transaction("2026-09-02", "AAPL", "buy", 1, 200, "USD"), db)
    with pytest.raises(edits.Stale):
        edits.commit(ops, planned.token, source="chat", path=db)
    # And a token from a different edit on the same book.
    other = edits.plan([{"op": "delete", "ids": [ids(db)[0]]}], db)
    with pytest.raises(edits.Stale):
        edits.commit(ops, other.token, source="chat", path=db)
    assert len(ledger.all_transactions(db)) == 4


def test_an_edit_that_leaves_a_sale_uncovered_is_refused(db):
    buy, _, _ = ids(db)
    planned = edits.plan([{"op": "delete", "ids": [buy]}], db)
    assert not planned.ok
    assert "exceeds held" in planned.problems[0]
    with pytest.raises(edits.EditError):
        edits.commit(planned.ops, planned.token, source="chat", path=db)


def test_undo_refuses_rows_changed_again_since(db):
    _, sale, _ = ids(db)
    first = [{"op": "update", "id": sale, "fields": {"price": 11}}]
    done = edits.commit(first, edits.plan(first, db).token, source="chat", path=db)
    second = [{"op": "update", "id": sale, "fields": {"price": 10}}]
    edits.commit(second, edits.plan(second, db).token, source="chat", path=db)
    with pytest.raises(edits.Conflict):
        edits.undo(done.id, path=db)
    assert edits.last_undoable(db).summary == ""  # the second is still undoable


def test_split_row_parts_a_partial_move_and_the_new_half_is_addressable(db):
    _, sale, _ = ids(db)
    ops = [
        {"op": "split_row", "id": sale, "quantity": 40},
        {"op": "set_action", "ids": [-1], "action": "transfer_out"},
    ]
    planned = edits.plan(ops, db)
    kinds = sorted(c.kind for c in planned.changes)
    assert kinds == ["added", "updated"]
    new = next(c for c in planned.changes if c.kind == "added")
    assert new.after["quantity"] == 40 and new.after["action"] == "transfer_out"
    kept = next(c for c in planned.changes if c.kind == "updated")
    assert kept.after["quantity"] == 60


@pytest.mark.parametrize(
    "op, message",
    [
        ({"op": "delete", "ids": [999]}, "not in the book"),
        ({"op": "update", "id": 1, "fields": {"colour": "red"}}, "unknown fields"),
        ({"op": "update", "id": 1, "fields": {"date": "yesterday"}}, "not a date"),
        ({"op": "set_action", "ids": [1], "action": "gift"}, "unknown action"),
        ({"op": "add", "row": {"date": "2026-01-01", "ticker": "X",
                               "action": "buy", "quantity": 0}}, "above zero"),
        ({"op": "split_row", "id": 2, "quantity": 100}, "between 0"),
        ({"op": "nuke"}, "unknown operation"),
    ],
)
def test_malformed_edits_say_what_is_wrong(db, op, message):
    with pytest.raises(edits.EditError, match=message):
        edits.plan([op], db)


def test_select_finds_a_company_however_each_broker_spelled_it(db):
    rows = ledger.all_transactions(db)
    # Nothing in the rows links the ISIN to the symbol; the resolver does.
    assert edits.select(rows, edits.Selector(ticker="GRF.MC")) == [rows[2]]
    resolve = {"ES0171996087": "GRF.MC"}.get
    assert edits.select(rows, edits.Selector(ticker="grf.mc".upper()), resolve) == rows
    assert edits.select(rows, edits.Selector(ticker="GRF", broker="ibkr")) == [rows[2]]
    assert edits.select(rows, edits.Selector()) == []


def test_the_journal_lives_beside_the_ledger_without_a_schema_bump(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(ledger.SCHEMA)
    with ledger.connect(path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "changes" in tables


def test_a_wipe_takes_the_journal_with_it(db):
    """An undone deletion only checks its rows are still gone, which a wiped
    book always passes: it would put old rows into the next book."""
    _, _, arrival = ids(db)
    ops = [{"op": "delete", "ids": [arrival]}]
    edits.commit(ops, edits.plan(ops, db).token, source="chat", path=db)
    ledger.clear(db)
    assert edits.history(db) == []
