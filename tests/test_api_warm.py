"""`api.warm`: the boot-time pricing of recently seen books."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from stocks.api import loaders, warm

TODAY = date(2026, 9, 27)


@pytest.mark.parametrize(
    ("last_seen", "recent"),
    [
        ("2026-09-27", True),
        ("2026-09-24", True),
        ("2026-09-23", False),
        ("2026-09-25T10:00:00", True),
        (None, False),
        ("", False),
        ("yesterday", False),
    ],
)
def test_seen_recently_reads_the_login_stamp(last_seen, recent):
    assert warm.seen_recently(last_seen, TODAY) is recent


def test_off_unless_the_deploy_says_so(monkeypatch):
    monkeypatch.delenv(warm.ENV_FLAG, raising=False)
    assert warm.start() is None
    monkeypatch.setenv(warm.ENV_FLAG, "0")
    assert warm.start() is None


def test_start_gives_the_warm_the_startup_window_and_no_more(monkeypatch):
    """Readiness waits for a quick warm and stops waiting for a slow one."""
    import threading
    import time

    monkeypatch.setenv(warm.ENV_FLAG, "1")
    release = threading.Event()
    monkeypatch.setattr(warm, "warm_recent", lambda: release.wait(5))
    started = time.perf_counter()
    thread = warm.start(wait_s=0.2)
    assert thread is not None and thread.is_alive()
    assert 0.15 <= time.perf_counter() - started < 2
    release.set()
    thread.join(2)
    assert not thread.is_alive()


def test_the_wait_budget_reads_the_environment(monkeypatch):
    monkeypatch.delenv(warm.WAIT_FLAG, raising=False)
    assert warm.wait_budget() == warm.WAIT_S
    monkeypatch.setenv(warm.WAIT_FLAG, "5")
    assert warm.wait_budget() == 5.0
    monkeypatch.setenv(warm.WAIT_FLAG, "soon")
    assert warm.wait_budget() == warm.WAIT_S


def test_warms_only_the_accounts_seen_lately_and_survives_a_bad_one(monkeypatch):
    users = [
        SimpleNamespace(
            label="fresh",
            prefs={"last_seen": "2026-09-26", "currency": "USD"},
            db="fresh.db",
            watchlist="fresh.yaml",
        ),
        SimpleNamespace(
            label="stale",
            prefs={"last_seen": "2026-08-01"},
            db="stale.db",
            watchlist="stale.yaml",
        ),
        SimpleNamespace(
            label="broken",
            prefs={"last_seen": "2026-09-27", "currency": "XXX"},
            db="broken.db",
            watchlist="broken.yaml",
        ),
    ]
    monkeypatch.setattr("stocks.notify.fanout.iter_all_users", lambda: users)
    warmed: list[tuple[str, str, str]] = []

    def account(db, watchlist, base):
        if db == "broken.db":
            raise RuntimeError("no ledger")
        warmed.append((db, watchlist, base))

    monkeypatch.setattr(warm, "warm_account", account)
    assert warm.warm_recent(today=TODAY) == 1
    assert warmed == [("fresh.db", "fresh.yaml", "USD")]


def test_warm_account_fills_the_memos_a_page_reads(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    monkeypatch.setattr(loaders, "held_closes", lambda db, m: calls.append("closes"))
    monkeypatch.setattr(
        loaders, "positions_table", lambda db, m, b: calls.append(f"positions:{b}")
    )
    monkeypatch.setattr(loaders, "history", lambda db, m, b: calls.append("history"))
    monkeypatch.setattr(loaders, "basket_values", lambda db, m, b: calls.append("basket"))
    monkeypatch.setattr(loaders, "held", lambda db, m: ("MSFT",))
    monkeypatch.setattr(
        loaders, "watchlist_closes", lambda tickers: calls.append(f"year:{tickers}")
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    warm.warm_account("book.db", str(watchlist), "EUR")
    assert calls == [
        "closes",
        "positions:EUR",
        "history",
        "basket",
        "year:('AAPL', 'MSFT')",
    ]
