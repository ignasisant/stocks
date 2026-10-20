"""`portfolio.split_sweep`: the warm writes a book's missing splits, once.

The 2026-10-20 triage (APP-01) found a book holding one AMZN bought at $2050
before the 2022 20-for-1 — weeks after import, because the only repair ran
when its reader opened AMZN, and they never had. Yahoo is replaced with the
answers it gives for the real split.
"""

from __future__ import annotations

from datetime import date

import pytest

from stocks.api import warm
from stocks.portfolio import edits, split_sweep
from stocks.portfolio.ledger import Transaction, add_many, all_transactions

SPLITS = {"AMZN": [("1999-09-02", 2.0), ("2022-06-06", 20.0)]}
CLOSES = {("AMZN", "2022-05-24"): 104.10}
TODAY = date(2026, 10, 20)

BOOK = [
    Transaction("2022-05-24", "AMZN", "buy", 1.0, 2050.0, "USD", 0.0, "clicktrade"),
    Transaction("2026-02-18", "AMZN", "buy", 9.72545587, 205.65, "USD", 0.0, "revolut"),
    Transaction("2025-01-10", "BTC-EUR", "buy", 0.01, 90000.0, "EUR", 0.0, "revolut"),
]


@pytest.fixture(autouse=True)
def no_bucket(monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    monkeypatch.setattr("stocks.storage.restore", lambda path: False)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "portfolio.db"
    add_many(BOOK, path)
    return path


@pytest.fixture
def yahoo():
    asked: list[str] = []

    def splits(ticker):
        asked.append(ticker)
        return list(SPLITS.get(ticker, []))

    return asked, splits, lambda ticker, day: CLOSES.get((ticker, day))


def run(db, yahoo, **kw):
    _, splits, close_on = yahoo
    return split_sweep.repair(db, splits=splits, close_on=close_on, today=TODAY, **kw)


def split_rows(db):
    return [
        (t.ticker, t.date, t.quantity)
        for t in all_transactions(db)
        if t.action == "split"
    ]


def test_writes_the_missing_split_as_one_undoable_edit(db, yahoo):
    assert run(db, yahoo) == 1
    assert split_rows(db) == [("AMZN", "2022-06-06", 20.0)]
    [change] = edits.history(db)
    assert "AMZN 20:1 split 2022-06-06" in change.summary


def test_never_asks_yahoo_about_a_coin(db, yahoo):
    run(db, yahoo)
    assert yahoo[0] == ["AMZN"]


def test_an_unchanged_book_is_not_scanned_again(db, yahoo):
    run(db, yahoo)
    yahoo[0].clear()
    assert run(db, yahoo) == 0
    assert yahoo[0] == []


def test_a_split_the_reader_undid_is_never_written_again(db, yahoo):
    run(db, yahoo)
    [change] = edits.history(db)
    edits.undo(change.id, path=db)
    assert split_rows(db) == []
    assert run(db, yahoo) == 0
    assert split_rows(db) == []


def test_a_throttled_scan_is_asked_again(db, yahoo):
    asked, _, close_on = yahoo
    split_sweep.repair(
        db, splits=lambda t: [], close_on=close_on, throttled=lambda: True, today=TODAY
    )
    assert split_rows(db) == []
    assert run(db, yahoo) == 1


def test_a_week_old_stamp_is_scanned_again(db, yahoo):
    _, _, close_on = yahoo
    split_sweep.repair(
        db, splits=lambda t: [], close_on=close_on, today=date(2026, 10, 1)
    )
    assert run(db, yahoo) == 1


def test_the_warm_repairs_before_it_prices(monkeypatch, db, yahoo):
    _, splits, close_on = yahoo
    monkeypatch.setattr("stocks.data.fetch.splits", splits)
    monkeypatch.setattr("stocks.data.fetch.close_on", close_on)
    warm.repair_splits(str(db))
    assert split_rows(db) == [("AMZN", "2022-06-06", 20.0)]


def test_a_failing_scan_never_stops_the_warm(monkeypatch, db):
    def boom(*a, **k):
        raise RuntimeError("bucket down")

    monkeypatch.setattr(split_sweep, "repair", boom)
    warm.repair_splits(str(db))  # no raise
