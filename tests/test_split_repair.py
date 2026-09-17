"""The Import page's repair for splits the ledger never heard about.

The bug it exists for: a share bought before a 20:1 split and never sold keeps
the pre-split share count and the pre-split price the statement printed, so the
position reads as a 35% loss against a post-split market price. The import-time
rescue in validate.py only fires on a sell that comes up short, and a position
nobody sold never comes up short — so the repair has to be reachable without an
import.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from stocks.data import fetch
from stocks.portfolio.ledger import Transaction, add_many, all_transactions
from stocks.web import auth

PAGE = "src/stocks/web/app_pages/import_transactions.py"

AMZN_SPLITS = [("1999-09-02", 2.0), ("2022-06-06", 20.0)]
CLOSES = {("AMZN", "2022-05-24"): 104.10}

SCAN = "Check for missing splits"


@pytest.fixture
def paths(tmp_path):
    p = auth.paths_for("splitty@example.com", users_dir=tmp_path)
    p.root.mkdir(parents=True, exist_ok=True)
    p.prefs.write_text(json.dumps(dict(auth.DEFAULT_PREFS) | {"language": "en"}))
    return p


@pytest.fixture
def page(monkeypatch, paths):
    monkeypatch.setattr(auth, "require_login", lambda: paths)
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "db_path", lambda: paths.db)
    monkeypatch.setattr(auth, "watchlist_path", lambda: paths.watchlist)
    # No network: the page reaches Yahoo only through these two.
    monkeypatch.setattr(fetch, "splits", lambda ticker: list(AMZN_SPLITS))
    monkeypatch.setattr(fetch, "close_on", lambda ticker, day: CLOSES.get((ticker, day)))
    return AppTest.from_file(PAGE, default_timeout=120)


def _raw_amzn(paths):
    """The ledger as the statement left it: pre-split buy, no split row."""
    add_many(
        [
            Transaction("2022-05-24", "AMZN", "buy", 1.0, 2050.0, "USD", 9.36),
            Transaction("2026-02-18", "AMZN", "buy", 9.72545587, 205.65, "USD"),
        ],
        paths.db,
    )


def _button(at, label):
    return [b for b in at.button if b.label.startswith(label)]


def test_the_scan_is_offered_but_costs_nothing_until_asked(page, paths, monkeypatch):
    """The page must not spend a Yahoo round-trip per holding on every render."""
    asked: list[str] = []
    monkeypatch.setattr(fetch, "splits", lambda ticker: asked.append(ticker) or [])
    _raw_amzn(paths)
    page.run()
    assert not page.exception
    assert _button(page, SCAN)
    assert asked == []


def test_scan_finds_the_split_and_applying_it_writes_one_row(page, paths):
    _raw_amzn(paths)
    page.run()
    _button(page, SCAN)[0].click().run()
    assert not page.exception
    assert any("1 split(s) your ledger is missing" in w.value for w in page.warning)

    apply = _button(page, "Add 1 split row")
    assert apply
    apply[0].click().run()
    assert not page.exception

    rows = [t for t in all_transactions(paths.db) if t.action == "split"]
    assert len(rows) == 1
    assert (rows[0].ticker, rows[0].date, rows[0].quantity) == (
        "AMZN", "2022-06-06", 20.0,
    )


def test_a_ledger_with_nothing_missing_says_so(page, paths):
    add_many(
        [
            Transaction("2022-05-24", "AMZN", "buy", 1.0, 2050.0, "USD", 9.36),
            Transaction("2022-06-06", "AMZN", "split", 20.0, 0.0, "USD"),
        ],
        paths.db,
    )
    page.run()
    _button(page, SCAN)[0].click().run()
    assert not page.exception
    assert any("No missing splits" in s.value for s in page.success)
    assert not _button(page, "Add ")


def test_an_empty_ledger_has_nothing_to_scan(page):
    page.run()
    assert not page.exception
    assert _button(page, SCAN)[0].disabled
