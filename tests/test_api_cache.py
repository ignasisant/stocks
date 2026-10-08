"""`api.cache`: the memo the API loaders share, and its single-flight misses.

The shell opens a page as a dozen concurrent requests. On a cold process every
one of them misses the same key at the same moment, and a memo that only stores
results lets each compute its own — measured 2026-09-27 as nine bulk downloads
of one book (523 Yahoo requests for 76 distinct URLs) behind a single cold Home.
These pin that a miss is computed once and shared, exception included.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import cache, loaders
from stocks.api.app import app
from stocks.portfolio import ledger
from stocks.portfolio.ledger import Transaction


def _together(fn, n: int, gate: threading.Event, *args):
    """Call `fn(*args)` from `n` threads at once, opening `gate` once every
    call is in — the shape of a page's requests landing on a cold key."""
    with ThreadPoolExecutor(n) as pool:
        futures = [pool.submit(fn, *args) for _ in range(n)]
        time.sleep(0.2)
        gate.set()
        return [f.result() for f in futures]


# ------------------------------------------------------------------ ttl_cache
def test_concurrent_misses_share_one_computation():
    calls: list[str] = []
    gate = threading.Event()

    @cache.ttl_cache(60.0)
    def slow(key: str):
        calls.append(key)
        gate.wait(timeout=5)
        return object()

    values = _together(slow, 8, gate, "book")
    assert calls == ["book"]
    assert all(v is values[0] for v in values)


def test_a_failed_flight_fails_its_waiters_once_and_the_next_call_retries():
    """A throttled download costs one attempt, not one per waiter — and the
    failure is not memoized, so the next request after it asks again."""
    calls: list[str] = []
    gate = threading.Event()

    @cache.ttl_cache(60.0)
    def flaky(key: str):
        calls.append(key)
        gate.wait(timeout=5)
        if len(calls) == 1:
            raise RuntimeError("throttled")
        return "priced"

    def attempt(key: str):
        try:
            return flaky(key)
        except RuntimeError as exc:
            return exc

    outcomes = _together(attempt, 8, gate, "book")
    assert calls == ["book"]
    assert all(isinstance(o, RuntimeError) for o in outcomes)
    assert len({id(o) for o in outcomes}) == 1, "one exception, shared"
    assert flaky("book") == "priced"
    assert calls == ["book", "book"]


def test_distinct_keys_do_not_wait_on_each_other():
    meet = threading.Barrier(2, timeout=2)

    @cache.ttl_cache(60.0)
    def slow(key: str):
        meet.wait()  # BrokenBarrierError if one key was queued behind the other
        return key

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(slow, ["a", "b"])) == ["a", "b"]


def test_a_just_expired_entry_is_served_stale_while_a_refresh_lands(monkeypatch):
    """Minute sixteen used to pay the whole download in-request. Now it gets
    the fifteen-minute-old figure at once and the refresh lands behind it."""
    clock = [0.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    calls: list[str] = []

    @cache.ttl_cache(10.0)
    def f(key: str):
        calls.append(key)
        return len(calls)

    assert f("x") == 1 and f("x") == 1
    clock[0] = 11.0  # past the ttl, inside the grace
    assert f("x") == 1  # the stale figure, at once
    for _ in range(300):  # ...and the refresh lands behind it
        if f("x") == 2:
            break
        time.sleep(0.01)
    assert f("x") == 2 and calls == ["x", "x"]
    clock[0] = 100.0  # past the grace too: a miss, computed in the request
    assert f("x") == 3
    f.cache_clear()
    assert f("x") == 4


def test_no_grace_means_a_strict_expiry(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    calls: list[str] = []

    @cache.ttl_cache(10.0, stale_s=0)
    def f(key: str):
        calls.append(key)
        return len(calls)

    assert f("x") == 1
    clock[0] = 11.0
    assert f("x") == 2


def test_a_failed_refresh_keeps_the_stale_entry(monkeypatch):
    """A throttled Yahoo behind a stale entry is an older number, never an
    empty card — and never an exception on the reader who happened to be
    the one whose request queued the refresh."""
    clock = [0.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    calls: list[str] = []
    tried = threading.Event()

    @cache.ttl_cache(10.0)
    def f(key: str):
        calls.append(key)
        if len(calls) > 1:
            tried.set()
            raise RuntimeError("throttled")
        return "priced"

    assert f("x") == "priced"
    clock[0] = 11.0
    assert f("x") == "priced"
    assert tried.wait(2)
    time.sleep(0.05)  # let that flight close
    assert f("x") == "priced"
    assert len(calls) >= 2


# --------------------------------------------------------------- _on_download
def test_frames_built_from_one_download_are_built_once(monkeypatch):
    closes = {"AAPL": None}
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: closes)
    calls: list[object] = []
    gate = threading.Event()

    @loaders._on_download
    def frame(db, mtime, base, got):
        calls.append(got)
        gate.wait(timeout=5)
        return object()

    values = _together(frame, 8, gate, "book.db", 1.0, "EUR")
    assert len(calls) == 1 and calls[0] is closes
    assert all(v is values[0] for v in values)
    # A new download is a new frame — the identity test is unchanged.
    monkeypatch.setattr(loaders, "held_closes", lambda db, mtime: dict(closes))
    assert frame("book.db", 1.0, "EUR") is not values[0]
    assert len(calls) == 2


# ------------------------------------------------------------ the whole page
EMAIL = "reader@example.com"
_BOOK = (
    loaders.ledger_state,
    loaders.held_closes,
    loaders.positions_table,
    loaders.history,
    loaders.basket_values,
    loaders.quotes,
)


@pytest.fixture
def book(monkeypatch, tmp_path):
    """A two-name EUR book behind a token caller, with every memo cold."""
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    ledger.add_many(
        [
            Transaction("2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 1.0),
            Transaction("2024-02-01", "MSFT", "buy", 5, 200.0, "EUR", 1.0),
        ],
        path=paths.db,
    )
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setenv("API_TOKEN", "t")
    for fn in _BOOK:
        fn.cache_clear()
    yield paths
    for fn in _BOOK:
        fn.cache_clear()


def test_one_cold_home_is_one_bulk_download(book, monkeypatch):
    """Eight requests that all price the book, at once, on a cold process:
    one `load_closes`, every response complete."""
    downloads: list[tuple[str, ...]] = []
    gate = threading.Event()
    days = pd.bdate_range("2024-01-02", periods=400)
    price = {"AAPL": 100.0, "MSFT": 200.0}

    def download(tickers, period="1y", interval="1d", auto_adjust=True, budget=60.0, **_):
        downloads.append(tuple(tickers))
        gate.wait(timeout=10)
        return {
            t: pd.DataFrame({"Close": price[t], "Adj Close": price[t]}, index=days)
            for t in tickers
        }

    monkeypatch.setattr("stocks.data.fetch.fetch_many", download)
    monkeypatch.setattr(loaders, "quotes", lambda tickers: {})
    client = TestClient(app)
    paths = [
        "/v1/portfolio/summary",
        "/v1/portfolio/performance",
        "/v1/portfolio/positions",
        "/v1/portfolio/history",
        "/v1/portfolio/monthly",
        "/v1/movers?window=day",
        "/v1/movers?window=week",
        "/v1/movers?window=month",
    ]

    def get(path: str):
        joiner = "&" if "?" in path else "?"
        return client.get(
            f"{path}{joiner}account={EMAIL}", headers={"Authorization": "Bearer t"}
        )

    with ThreadPoolExecutor(len(paths)) as pool:
        futures = [pool.submit(get, p) for p in paths]
        time.sleep(0.3)
        gate.set()
        responses = [f.result() for f in futures]
    assert [r.status_code for r in responses] == [200] * len(paths), [
        r.text[:120] for r in responses
    ]
    assert downloads == [("AAPL", "MSFT")]


# ------------------------------------------------------------------ the disk
def _persisted(name: str, calls: list[str], refuse: list[bool]):
    """A fresh memo instance over `name` — what a new process would build."""

    @cache.ttl_cache(10.0, persist=name, keep_s=3600.0)
    def f(key: str):
        calls.append(key)
        if refuse[0]:
            raise RuntimeError("throttled")
        return {"n": len(calls)}

    return f


def _clocks(monkeypatch, start: float) -> list[float]:
    clock = [start]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cache.time, "time", lambda: clock[0])
    return clock


def test_a_persisted_entry_comes_back_in_a_new_process():
    calls: list[str] = []
    first = _persisted("t_persist", calls, [False])
    assert first("x") == {"n": 1}
    assert list((cache.MEMO_DIR / "t_persist").glob("*.pkl"))
    second = _persisted("t_persist", calls, [False])  # a new process: empty store
    assert second("x") == {"n": 1}
    assert calls == ["x"]


def test_the_fetch_is_tried_first_and_the_old_entry_stands_in_only_when_it_fails(
    monkeypatch,
):
    clock = _clocks(monkeypatch, 1000.0)
    calls: list[str] = []
    refuse = [False]
    f = _persisted("t_salvage", calls, refuse)
    holder: dict[str, float] = {}
    token = cache.STALE.set(holder)
    try:
        assert f("x") == {"n": 1}
        clock[0] += 100  # past the ttl and its grace: a miss, computed in-request
        refuse[0] = True
        assert f("x") == {"n": 1}  # tried, refused, the old figure — and marked
        assert calls == ["x", "x"] and holder["since"] == 1000.0
        holder.clear()
        refuse[0] = False
        clock[0] += 1
        assert f("x") == {"n": 3}  # the source answers: the new figure, no mark
        assert "since" not in holder
        clock[0] += 3601  # beyond `keep_s`: the failure surfaces
        refuse[0] = True
        with pytest.raises(RuntimeError):
            f("x")
    finally:
        cache.STALE.reset(token)


def test_a_new_process_with_a_refusing_source_answers_from_disk(monkeypatch):
    clock = _clocks(monkeypatch, 1000.0)
    calls: list[str] = []
    _persisted("t_restart", calls, [False])("x")
    clock[0] += 100
    second = _persisted("t_restart", calls, [True])
    holder: dict[str, float] = {}
    token = cache.STALE.set(holder)
    try:
        assert second("x") == {"n": 1}
    finally:
        cache.STALE.reset(token)
    assert calls == ["x", "x"] and holder["since"] == 1000.0


def test_a_figure_built_from_a_salvaged_one_marks_every_request_it_answers(
    monkeypatch,
):
    """`held_closes` is computed from `_held_frames`; when the frames were
    salvaged, the closes — and everything priced off them, on every later
    request — are as old as the frames."""
    clock = _clocks(monkeypatch, 1000.0)
    calls: list[str] = []
    refuse = [False]
    frames = _persisted("t_frames", calls, refuse)

    @cache.ttl_cache(10.0)
    def closes(key: str):
        return {"from": frames(key)["n"]}

    closes("x")
    clock[0] += 100
    refuse[0] = True
    marks: list[float | None] = []
    for _ in range(3):  # the first computes `closes`; the next two hit it
        holder: dict[str, float] = {}
        token = cache.STALE.set(holder)
        try:
            assert closes("x") == {"from": 1}
        finally:
            cache.STALE.reset(token)
        marks.append(holder.get("since"))
    assert marks == [1000.0, 1000.0, 1000.0]


def test_clearing_makes_the_disk_copy_a_fallback_and_nothing_more():
    """A forced refresh must fetch — and must not, during a throttle, turn
    the last good figures into nothing."""
    calls: list[str] = []
    refuse = [False]
    first = _persisted("t_clear", calls, refuse)
    first("x")
    first.cache_clear(expire=False)  # memory only — what a restart loses
    assert first("x") == {"n": 1} and calls == ["x"]
    first.cache_clear()  # a forced refresh: the copy may not answer a read...
    assert first("x") == {"n": 2}
    first.cache_clear()
    refuse[0] = True  # ...but still stands in for a refused fetch
    holder: dict[str, float] = {}
    token = cache.STALE.set(holder)
    try:
        assert first("x") == {"n": 2}
    finally:
        cache.STALE.reset(token)
    assert calls == ["x", "x", "x"] and "since" in holder


def test_a_throttled_source_answers_with_the_last_good_prices_and_says_so(
    book, monkeypatch
):
    """The book was priced once. A new process meets a throttled Yahoo: the
    positions still carry values, and the response says how old they are —
    on this request and on the next one, which reads the same figures."""
    from yfinance.exceptions import YFRateLimitError

    days = pd.bdate_range("2024-01-02", periods=400)
    price = {"AAPL": 100.0, "MSFT": 200.0}
    refuse = [False]

    def download(tickers, period="1y", interval="1d", auto_adjust=True, budget=60.0, **_):
        if refuse[0]:
            raise YFRateLimitError()
        return {
            t: pd.DataFrame({"Close": price[t], "Adj Close": price[t]}, index=days)
            for t in tickers
        }

    monkeypatch.setattr("stocks.data.fetch.fetch_many", download)
    monkeypatch.setattr(loaders, "quotes", lambda tickers: {})
    client = TestClient(app)
    headers = {"Authorization": "Bearer t"}
    priced = client.get(f"/v1/portfolio/positions?account={EMAIL}", headers=headers)
    assert priced.status_code == 200 and "x-data-stale-since" not in priced.headers

    clock = _clocks(monkeypatch, time.time())
    loaders.held_closes.cache_clear(expire=False)  # the restart
    clock[0] += 3600  # an hour later, past the grace
    refuse[0] = True  # ...and Yahoo says no
    again = client.get(f"/v1/portfolio/positions?account={EMAIL}", headers=headers)
    assert again.status_code == 200
    assert again.json()["positions"] == priced.json()["positions"]
    assert again.headers["x-data-stale-since"]
    movers = client.get(f"/v1/movers?window=day&account={EMAIL}", headers=headers)
    assert movers.status_code == 200
    assert movers.headers["x-data-stale-since"] == again.headers["x-data-stale-since"]


# ------------------------------------------------------------- memory bounds
class _Frame:
    """A stand-in for a book's frames: something a weakref can watch go."""


def test_an_entry_past_its_grace_goes_at_the_next_landing(monkeypatch):
    """Keys carry the ledger's mtime, so an edit strands the book's old
    entries where nobody will ask again. They used to stay until enough new
    keys pushed them past the cap; now the next landing sweeps them."""
    import gc
    import weakref

    clock = [0.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])

    @cache.ttl_cache(10.0, stale_s=5.0, max_entries=32)
    def frames(db: str, mtime: float):
        return _Frame()

    old = weakref.ref(frames("book", 1.0))
    clock[0] = 14.0  # past the ttl, inside the grace: still able to answer
    frames("other", 1.0)
    gc.collect()
    assert old() is not None
    clock[0] = 16.0  # past ttl + grace: dead weight
    frames("book", 2.0)  # the edit that stranded it
    gc.collect()
    assert old() is None


def test_disk_max_caps_a_memo_directory(monkeypatch):
    clock = _clocks(monkeypatch, 1000.0)

    @cache.ttl_cache(10.0, persist="t_cap", disk_max=2)
    def f(key: str):
        return key

    for key in ("a", "b", "c"):
        clock[0] += 1
        f(key)
    assert len(list((cache.MEMO_DIR / "t_cap").glob("*.pkl"))) == 2


def test_a_restore_from_the_bucket_does_not_grow_the_directory_back(monkeypatch):
    """The bucket keeps every copy ever written; restoring them one miss at a
    time must not refill a directory the cap emptied."""
    import pickle

    from stocks import storage

    clock = _clocks(monkeypatch, 1000.0)

    @cache.ttl_cache(10.0, persist="t_restore", disk_max=2)
    def f(key: str):
        return key

    f("a")
    f("b")

    def restore(path):
        blob = {"wall": clock[0], "value": "from-bucket", "since": None}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(blob))
        return True

    monkeypatch.setattr(storage, "restore", restore)
    assert f("c") == "from-bucket"
    assert len(list((cache.MEMO_DIR / "t_restore").glob("*.pkl"))) == 2
