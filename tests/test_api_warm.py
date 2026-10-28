"""`api.warm`: the boot-time pricing of recently seen books."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
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
    monkeypatch.setattr(warm, "warm_shared", lambda: None)
    warmed: list[tuple[str, str, str]] = []
    more: list[str] = []

    def account(db, watchlist, base):
        if db == "broken.db":
            raise RuntimeError("no ledger")
        warmed.append((db, watchlist, base))

    monkeypatch.setattr(warm, "warm_account", account)
    monkeypatch.setattr(warm, "warm_more", lambda db, w, b: more.append(db))
    assert warm.warm_recent(today=TODAY) == 1
    assert warmed == [("fresh.db", "fresh.yaml", "USD")]
    # The second pass skips the account whose Home would not warm.
    assert more == ["fresh.db"]


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
    # The held name comes out of the book's own prices, so the list download
    # is warmed under the key Home reads: the names those prices do not cover.
    monkeypatch.setattr(
        loaders,
        "held_printed_closes",
        lambda db, m: {
            "MSFT": pd.Series([1.0, 2.0], index=pd.bdate_range("2026-10-01", periods=2))
        },
    )
    monkeypatch.setattr(
        loaders, "watchlist_closes", lambda tickers: calls.append(f"year:{tickers}") or {}
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    warm.warm_account("book.db", str(watchlist), "EUR")
    assert calls == [
        "closes",
        "positions:EUR",
        "history",
        "basket",
        "year:('AAPL',)",
    ]


def _user(label: str, last_seen: str) -> SimpleNamespace:
    return SimpleNamespace(
        label=label, prefs={"last_seen": last_seen}, db=f"{label}.db", watchlist="w.yaml"
    )


def test_the_most_recently_seen_are_warmed_first_until_the_budget_runs_out(
    monkeypatch,
):
    from types import SimpleNamespace

    users = [
        _user("monday", "2026-09-25"),
        _user("today", "2026-09-27"),
        _user("yesterday", "2026-09-26"),
    ]
    monkeypatch.setattr("stocks.notify.fanout.iter_all_users", lambda: users)
    monkeypatch.setattr(warm, "warm_shared", lambda: None)
    monkeypatch.setattr(warm, "warm_more", lambda db, w, b: None)
    warmed: list[str] = []
    # Each account takes 50 "seconds" of a clock the test owns: a real sleep
    # against a real budget failed on a loaded CI runner (1 warmed, not 2).
    clock = [0.0]
    monkeypatch.setattr(warm, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def account(db, watchlist, base):
        warmed.append(db)
        clock[0] += 50

    monkeypatch.setattr(warm, "warm_account", account)
    assert warm.warm_recent(today=TODAY) == 3
    assert warmed == ["today.db", "yesterday.db", "monday.db"]
    warmed.clear()
    assert warm.warm_recent(today=TODAY, budget_s=60) == 2
    assert warmed == ["today.db", "yesterday.db"]


# ------------------------------------------------------------------ the route
TOKEN = "s3cret-token"


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from stocks.api.app import app

    monkeypatch.setenv("API_TOKEN", TOKEN)
    return TestClient(app)


@pytest.fixture
def ran(monkeypatch):
    """What `warm_recent` was called with, and whether refreshes ran in place."""
    from stocks.api import cache

    calls: list[dict] = []

    def fake(today=None, *, budget_s=None):
        calls.append({"budget_s": budget_s, "sync": cache.SYNC.get()})
        return 2

    monkeypatch.setattr(warm, "warm_recent", fake)
    return calls


def test_the_route_wants_the_api_token(client, ran):
    assert client.post("/v1/warm").status_code == 401
    wrong = client.post("/v1/warm", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert ran == []


def test_a_signed_in_account_cannot_warm_everybodys_book(client, ran, monkeypatch):
    from stocks import session

    monkeypatch.setattr(session, "signed_in_email", lambda cookies: "a@example.com")
    assert client.post("/v1/warm").status_code == 401
    assert ran == []


def test_the_route_warms_in_place_within_its_budget(client, ran):
    from stocks.api import cache

    res = client.post("/v1/warm", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json()["warmed"] == 2
    assert ran == [{"budget_s": warm.WARM_BUDGET_S, "sync": True}]
    assert cache.SYNC.get() is False


def test_a_second_warm_while_one_runs_is_busy(client, ran):
    assert warm._running.acquire(blocking=False)
    try:
        res = client.post("/v1/warm", headers={"Authorization": f"Bearer {TOKEN}"})
    finally:
        warm._running.release()
    assert res.json() == {"warmed": 0, "busy": True}
    assert ran == []


def test_in_place_a_stale_entry_is_refreshed_not_served():
    """`cache.SYNC`: the warm's thread has the CPU, so it waits for the new
    value where a reader would be answered with the old one at once."""
    import threading

    from stocks.api import cache

    def ask():
        store = {("k",): (0.0, "old", 0.0)}
        return cache.coalesced(
            store,
            {},
            threading.Lock(),
            ("k",),
            fresh=lambda e: False,
            usable=lambda e: True,
            compute=lambda: (1.0, "new", 1.0),
            max_entries=4,
        )

    assert ask() == "old"
    token = cache.SYNC.set(True)
    try:
        assert ask() == "new"
    finally:
        cache.SYNC.reset(token)


def test_warm_today_reads_the_largest_names_first_and_survives_a_feed(monkeypatch):
    tbl = pd.DataFrame(
        {"value": [100.0, 900.0, 500.0, 300.0]},
        index=["SAP.DE", "MSFT", "BTC-EUR", "AAPL"],
    )
    metrics: list[str] = []
    feeds: list[str] = []

    def insiders(ticker):
        feeds.append(ticker)
        if ticker == "MSFT":
            raise RuntimeError("SEC refused")

    monkeypatch.setattr(loaders, "review_metrics", metrics.append)
    monkeypatch.setattr(loaders, "insiders", insiders)
    monkeypatch.setattr(warm, "TODAY_INSIDERS", 2)
    warm.warm_today(tbl)
    # By value, coins left out; insiders only for US listings.
    assert metrics == ["MSFT", "AAPL", "SAP.DE"]
    assert feeds == ["MSFT", "AAPL"]


def test_warm_today_skips_an_empty_book(monkeypatch):
    monkeypatch.setattr(loaders, "review_metrics", lambda t: pytest.fail(t))
    warm.warm_today(pd.DataFrame())
    warm.warm_today(None)


def test_warm_recent_reads_the_shared_market_once(monkeypatch):
    monkeypatch.setattr("stocks.notify.fanout.iter_all_users", lambda: [])
    reads: list[int] = []
    monkeypatch.setattr(loaders, "today_market", lambda: reads.append(1) or {})
    for memo in ("pulse_closes", "pulse_rate_rows", "market_pulse"):
        monkeypatch.setattr(loaders, memo, lambda: {})
    warm.warm_recent(today=TODAY)
    assert reads == [1]


def test_warm_more_fills_the_memos_the_other_pages_read(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    monkeypatch.setattr(
        loaders,
        "positions_table",
        lambda db, m, b: pd.DataFrame({"ccy": ["USD", "EUR", "USD"]}),
    )
    monkeypatch.setattr(
        loaders,
        "basket_report",
        lambda db, m, b, period: calls.append(f"book:{b}:{period}"),
    )
    monkeypatch.setattr(
        loaders, "spot_rates", lambda ccys, base: calls.append(f"spots:{ccys}:{base}")
    )
    monkeypatch.setattr(
        loaders, "earnings_calendar", lambda tickers: calls.append(f"earnings:{tickers}")
    )
    monkeypatch.setattr(
        loaders, "dividend_payments", lambda db, m, b: calls.append("dividends")
    )
    monkeypatch.setattr("stocks.data.funds.is_fund", lambda t, fetch=True: t == "VWCE.DE")
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "watchlist:\n  - ticker: MSFT\n  - ticker: AAPL\n  - ticker: BTC-EUR\n"
        "  - ticker: VWCE.DE\n"
    )
    warm.warm_more("book.db", str(watchlist), "EUR")
    assert calls == [
        "book:EUR:2y",
        "spots:('EUR', 'USD'):EUR",
        "earnings:('AAPL', 'MSFT')",
        "dividends",
    ]


def test_warm_more_survives_a_feed_that_refuses(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    monkeypatch.setattr(loaders, "positions_table", lambda db, m, b: pd.DataFrame())
    monkeypatch.setattr(
        loaders, "basket_report", lambda *a: (_ for _ in ()).throw(RuntimeError("yahoo"))
    )
    monkeypatch.setattr(loaders, "earnings_calendar", lambda t: calls.append("earnings"))
    monkeypatch.setattr(loaders, "dividend_payments",
                        lambda *a: calls.append("dividends"))
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("watchlist: []\n")
    warm.warm_more("book.db", str(watchlist), "EUR")
    # An empty book has no spots to fetch; the refused backtest costs itself.
    assert calls == ["earnings", "dividends"]


def test_warm_recent_runs_the_second_pass_after_every_home(monkeypatch):
    from types import SimpleNamespace

    users = [_user("today", "2026-09-27"), _user("yesterday", "2026-09-26")]
    monkeypatch.setattr("stocks.notify.fanout.iter_all_users", lambda: users)
    monkeypatch.setattr(warm, "warm_shared", lambda: None)
    order: list[str] = []
    clock = [0.0]
    monkeypatch.setattr(warm, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def account(db, watchlist, base):
        order.append(f"home:{db}")
        clock[0] += 50

    def more(db, watchlist, base):
        order.append(f"more:{db}")
        clock[0] += 50

    monkeypatch.setattr(warm, "warm_account", account)
    monkeypatch.setattr(warm, "warm_more", more)
    assert warm.warm_recent(today=TODAY) == 2
    assert order == [
        "home:today.db", "home:yesterday.db", "more:today.db", "more:yesterday.db"
    ]
    order.clear()
    # The budget spent on Home leaves the second pass out, never the reverse.
    assert warm.warm_recent(today=TODAY, budget_s=120) == 2
    assert order == ["home:today.db", "home:yesterday.db", "more:today.db"]


def test_warm_shared_reads_the_market_memos_once_and_survives_one(monkeypatch):
    reads: list[str] = []
    monkeypatch.setattr(loaders, "today_market", lambda: reads.append("today") or {})
    monkeypatch.setattr(
        loaders, "pulse_closes", lambda: (_ for _ in ()).throw(RuntimeError("yahoo"))
    )
    monkeypatch.setattr(loaders, "pulse_rate_rows", lambda: reads.append("rates") or {})
    monkeypatch.setattr(loaders, "market_pulse", lambda: reads.append("pulse"))
    monkeypatch.setattr(loaders, "positioning", lambda: reads.append("cot"))
    warm.warm_shared()
    assert reads == ["today", "rates", "pulse", "cot"]
