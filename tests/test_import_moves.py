"""The Import page's offer to record a phantom sale as the transfer it was.

The situation this exists for: a book imported from two brokers, where the
first one printed the departure as a sale at the market price and the second
listed the arrival as a balance. Nothing in either file says "transfer", so
the ledger reports a gain the account never made and a position that restarts
its holding period — until the page offers to join the two rows, and the
account accepts.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from stocks.portfolio import positions
from stocks.portfolio.ledger import Transaction, add_many, all_transactions
from stocks.web import auth

PAGE = "src/stocks/web/app_pages/import_transactions.py"
NO_FX = lambda amount, currency, day: amount  # noqa: E731

# One share of ASML: bought at DEGIRO (which books it under the ISIN), moved to
# IBKR (which books it under the symbol and reports the basis it came with).
BOUGHT = Transaction("2025-07-18", "NL0010273215", "buy", 1, 633.9, "EUR", 4.9,
                     "degiro ASML HOLDING N.V.")
SOLD = Transaction("2026-08-06", "NL0010273215", "sell", 1, 1465.8, "EUR", 0,
                   "degiro ASML HOLDING N.V.")
ARRIVED = Transaction("2026-09-14", "ASML", "transfer_in", 1, 633.9, "EUR", 0,
                      "ibkr snapshot NL0010273215")


@pytest.fixture
def paths(tmp_path):
    p = auth.paths_for("mover@example.com", users_dir=tmp_path)
    p.root.mkdir(parents=True, exist_ok=True)
    p.prefs.write_text(json.dumps(dict(auth.DEFAULT_PREFS) | {"language": "en"}))
    add_many([BOUGHT, SOLD, ARRIVED], p.db)
    return p


@pytest.fixture
def page(monkeypatch, paths):
    monkeypatch.setattr(auth, "require_login", lambda: paths)
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "db_path", lambda: paths.db)
    monkeypatch.setattr(auth, "watchlist_path", lambda: paths.watchlist)
    return AppTest.from_file(PAGE, default_timeout=120)


def _apply(at):
    return [b for b in at.button if b.label.startswith("Record ")]


def test_the_page_says_the_shares_only_changed_broker(page):
    page.run()
    assert not page.exception
    assert _apply(page)
    assert any("only changed broker" in str(w.value) for w in page.warning)


def test_accepting_retires_the_gain_nobody_made(page, paths):
    page.run()
    _apply(page)[0].click().run()
    assert not page.exception

    rows = all_transactions(paths.db)
    assert {t.action for t in rows} == {"buy", "transfer_out", "transfer_in"}
    # Both brokers' labels for the security are now one label, so the replay
    # can see that the shares never left the book.
    assert {t.ticker for t in rows} == {"ASML"}

    open_lots, realized = positions.build(rows, to_base=NO_FX)
    assert realized == []
    assert [(p.ticker, p.quantity, round(p.cost, 2)) for p in open_lots] == [
        ("ASML", 1.0, 638.8)
    ]


def test_the_offer_is_gone_once_it_has_been_taken(page):
    page.run()
    _apply(page)[0].click().run()
    assert not _apply(page)
    assert any("recorded as transfers" in str(t.value) for t in page.toast)


def test_a_book_with_nothing_to_repair_is_not_asked_about_it(monkeypatch, tmp_path):
    p = auth.paths_for("clean@example.com", users_dir=tmp_path)
    p.root.mkdir(parents=True, exist_ok=True)
    p.prefs.write_text(json.dumps(dict(auth.DEFAULT_PREFS) | {"language": "en"}))
    add_many([BOUGHT], p.db)
    for name in ("require_login", "user_paths"):
        monkeypatch.setattr(auth, name, lambda: p)
    monkeypatch.setattr(auth, "db_path", lambda: p.db)
    monkeypatch.setattr(auth, "watchlist_path", lambda: p.watchlist)

    at = AppTest.from_file(PAGE, default_timeout=120).run()
    assert not at.exception
    assert not _apply(at)
