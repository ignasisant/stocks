"""What looks wrong in a book: found, explained, and fixed by an undoable edit."""

from dataclasses import replace

from stocks.portfolio import doctor, edits, ledger
from stocks.portfolio.ledger import Transaction

GRF_BUY = Transaction("2024-03-01", "ES0171996087", "buy", 100, 8.0, "EUR", 2.0,
                      "degiro GRIFOLS")
GRF_SOLD = Transaction("2026-08-06", "ES0171996087", "sell", 100, 12.0, "EUR", 0,
                       "degiro GRIFOLS")
GRF_IN = Transaction("2026-08-20", "GRF", "buy", 100, 8.02, "EUR", 0, "ibkr")

SYMBOLS = {"ES0171996087": "GRF.MC", "GRF": "GRF.MC", "SAN": "SAN.MC",
           "SAN.MC": "SAN.MC", "SAN.PA": "SAN.PA", "AAPL": "AAPL"}


def resolve(label: str) -> str:
    return SYMBOLS.get(label, label)


def _ledger(*txs):
    return [replace(t, id=i + 1) for i, t in enumerate(txs)]


def test_the_grifols_book_is_found_and_the_fix_leaves_one_holding_and_no_gain(tmp_path):
    db = tmp_path / "portfolio.db"
    ledger.add_many([GRF_BUY, GRF_SOLD, GRF_IN], db)
    [finding] = doctor.scan(ledger.all_transactions(db), resolve)
    assert finding.kind == "transfer"
    assert finding.detail["phantom_gain"] == 398.0
    assert finding.detail["broker_out"] == "degiro"
    assert finding.key == "transfer:2-3"

    planned = edits.plan(finding.fix, db)
    assert planned.ok
    (gain,) = [e for e in planned.effects if e.realized_before]
    assert gain.realized_before == {"2026": 398.0} and gain.realized_after == {}
    edits.commit(finding.fix, planned.token, source="chat", path=db)
    assert doctor.scan(ledger.all_transactions(db), resolve) == []


def test_one_company_under_two_labels_is_joined_under_the_symbol():
    rows = _ledger(
        Transaction("2025-01-02", "SAN", "buy", 10, 3.0, "EUR", 1, "revolut"),
        Transaction("2025-02-02", "SAN.MC", "buy", 5, 3.5, "EUR", 1, "ibkr"),
    )
    [finding] = doctor.scan(rows, resolve)
    assert finding.kind == "two_labels" and finding.ticker == "SAN.MC"
    assert finding.fix == [{"op": "relabel", "ids": [1], "to": "SAN.MC"}]


def test_a_shared_root_is_never_reason_enough_to_join_two_companies():
    rows = _ledger(
        Transaction("2025-01-02", "SAN.MC", "buy", 10, 3.0, "EUR", 1, "revolut"),
        Transaction("2025-02-02", "SAN.PA", "buy", 5, 90.0, "EUR", 1, "ibkr"),
    )
    assert doctor.scan(rows, resolve) == []


def test_without_a_lookup_labels_are_left_as_they_are():
    rows = _ledger(
        Transaction("2025-01-02", "SAN", "buy", 10, 3.0, "EUR", 1, "revolut"),
        Transaction("2025-02-02", "SAN.MC", "buy", 5, 3.5, "EUR", 1, "ibkr"),
    )
    assert doctor.scan(rows) == []


def test_the_same_trade_from_two_exports_keeps_the_first_copy():
    trade = Transaction("2025-03-03", "AAPL", "buy", 4, 170.0, "USD", 1, "revolut")
    rows = _ledger(trade, replace(trade, price=170.4, note="ibkr"))
    [finding] = doctor.scan(rows)
    assert finding.kind == "duplicate"
    assert finding.fix == [{"op": "delete", "ids": [2]}]
    assert finding.detail["broker_dropped"] == "ibkr"


def test_two_fills_at_one_broker_are_two_trades():
    trade = Transaction("2025-03-03", "AAPL", "buy", 4, 170.0, "USD", 1, "revolut")
    assert doctor.scan(_ledger(trade, trade)) == []


def test_a_sale_of_shares_that_never_arrived_has_no_fix_to_offer():
    rows = _ledger(
        Transaction("2025-01-02", "AAPL", "buy", 1, 150.0, "USD", 0, "revolut"),
        Transaction("2025-06-02", "AAPL", "sell", 3, 190.0, "USD", 0, "revolut"),
    )
    [finding] = doctor.scan(rows)
    assert finding.kind == "oversold" and finding.fix == []
    assert "exceeds held" in finding.detail["message"]


def test_an_oversell_a_transfer_explains_is_reported_once_as_the_transfer():
    """The IBKR sale of Grifols oversells the bare label until the move joins
    the two — the move is the finding, not a second one about the symptom."""
    later = Transaction("2026-09-01", "GRF", "sell", 100, 9.0, "EUR", 0, "ibkr")
    rows = _ledger(GRF_BUY, replace(GRF_SOLD, action="transfer_out", price=0.0),
                   replace(GRF_IN, action="transfer_in"), later)
    kinds = [f.kind for f in doctor.scan(rows, resolve)]
    assert kinds == ["transfer"]


def test_a_healthy_book_has_nothing_to_say():
    rows = _ledger(GRF_BUY, replace(GRF_SOLD, quantity=40))
    assert doctor.scan(rows, resolve) == []


def test_a_key_still_names_its_finding_on_a_rescan():
    rows = _ledger(GRF_BUY, GRF_SOLD, GRF_IN)
    [finding] = doctor.scan(rows, resolve)
    assert doctor.by_key(rows, finding.key, resolve) == finding
    assert doctor.by_key(rows, "transfer:9-9", resolve) is None
