"""memstat: the memory figures `/status` reports and `mem.step` logs.

Cloud Run kills the container at the cgroup's figure, which counts runtime
files as well as the process — so these must read the cgroup when it is
there, say None (never raise) when it is not, and the API must name a
request that grew the process by a step.
"""

import itertools
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import memstat, obs
from stocks.api import cache
from stocks.api.app import app

# The module, not `stocks.api.app` the attribute, which is the app itself.
app_module = sys.modules["stocks.api.app"]


@pytest.fixture(autouse=True)
def _quiet_upkeep(monkeypatch):
    """No sample or trim unless a test asks: either would read the RSS again
    and spend the readings a test hands the middleware."""
    monkeypatch.setattr(app_module, "_samples", memstat.Every(1e9))
    monkeypatch.setattr(app_module, "_trims", memstat.Trims())
    monkeypatch.setattr(memstat, "TRIM_MIN_MB", 1e9)


def test_snapshot_reads_without_proc_or_cgroup():
    snap = memstat.snapshot()
    assert snap["peak_mb"] > 0
    assert snap["threads"] >= 1
    assert snap["memo_mb"] >= 0


def test_cgroup_usage_and_limit(tmp_path, monkeypatch):
    usage, limit = tmp_path / "memory.current", tmp_path / "memory.max"
    usage.write_text(str(512 * 1024 * 1024))
    limit.write_text(str(1024 * 1024 * 1024))
    monkeypatch.setattr(memstat, "_CGROUP_USAGE", (usage,))
    monkeypatch.setattr(memstat, "_CGROUP_LIMIT", (limit,))
    assert memstat.cgroup_mb() == (512.0, 1024.0)
    limit.write_text("max")  # cgroup v2 for "no limit"
    assert memstat.cgroup_mb() == (512.0, None)


def test_a_request_that_grows_the_process_says_which(monkeypatch):
    readings = iter([300.0, 340.0])
    monkeypatch.setattr(memstat, "rss_mb", lambda: next(readings))
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(obs, "warn", lambda name, **fields: seen.append((name, fields)))
    assert TestClient(app).get("/v1/health").status_code == 200
    steps = [fields for name, fields in seen if name == "mem.step"]
    assert len(steps) == 1
    assert steps[0]["path"] == "/v1/health"
    assert steps[0]["delta_mb"] == 40.0
    assert steps[0]["concurrent"] == 1


def test_overlapping_requests_report_one_burst_not_one_line_each():
    steps = memstat.Steps()
    steps.start("/v1/movers", 640.0)
    steps.start("/v1/earnings", 660.0)
    steps.start("/v1/movers", 680.0)  # the same path twice is named once
    assert steps.end(700.0) == (False, None)
    assert steps.end(720.0) == (False, None)
    closed, step = steps.end(744.0)
    assert closed
    assert step == {
        "path": "/v1/movers, /v1/earnings",
        "concurrent": 3,
        "delta_mb": 104.0,  # from the burst's opening, not the last request's
        "rss_mb": 744.0,
    }


def test_a_new_burst_starts_from_the_rss_it_opens_at():
    steps = memstat.Steps()
    steps.start("/v1/daily", 300.0)
    steps.end(350.0)
    steps.start("/v1/health", 350.0)
    # 5 MB, not 55: the old burst is closed
    assert steps.end(355.0) == (True, None)
    steps.start("/v1/health", 355.0)
    assert steps.end(380.0)[1]["concurrent"] == 1


def test_a_wide_burst_caps_the_paths_it_names():
    steps = memstat.Steps()
    for i in range(memstat.Steps.MAX_PATHS + 3):
        steps.start(f"/v1/p{i}", 100.0)
    for _ in range(memstat.Steps.MAX_PATHS + 2):
        steps.end(100.0)
    _, step = steps.end(200.0)
    assert step["path"].endswith("(+3 more)")
    assert step["concurrent"] == memstat.Steps.MAX_PATHS + 3


def test_every_request_closes_its_burst_a_miss_too(monkeypatch):
    steps = memstat.Steps()
    monkeypatch.setattr(app_module, "_steps", steps)
    monkeypatch.setattr(memstat, "rss_mb", lambda: 300.0)
    TestClient(app, raise_server_exceptions=False).get("/v1/nope-not-a-route")
    assert steps._open == 0


def test_an_ordinary_request_logs_nothing(monkeypatch):
    readings = iter([300.0, 301.0])
    monkeypatch.setattr(memstat, "rss_mb", lambda: next(readings))
    seen: list[str] = []
    monkeypatch.setattr(obs, "warn", lambda name, **fields: seen.append(name))
    TestClient(app).get("/v1/health")
    assert "mem.step" not in seen


def test_a_burst_that_grew_past_the_last_trim_gets_one(monkeypatch):
    monkeypatch.setattr(memstat, "TRIM_MIN_MB", 10.0)
    readings = itertools.chain([300.0, 340.0], itertools.repeat(320.0))
    monkeypatch.setattr(memstat, "rss_mb", lambda: next(readings))
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(obs, "event", lambda name, **f: seen.append((name, f)))
    monkeypatch.setattr(obs, "warn", lambda name, **f: seen.append((name, f)))
    TestClient(app).get("/v1/health")
    trims = [f for name, f in seen if name == "mem.trim"]
    assert len(trims) == 1
    assert trims[0]["rss_before_mb"] == 320.0
    assert "swept" in trims[0]
    # Inside `TRIM_EVERY_S` of the last one: no second trim.
    TestClient(app).get("/v1/health")
    assert len([n for n, _ in seen if n == "mem.trim"]) == 1


def test_a_sample_reports_the_level_and_the_memos(monkeypatch):
    monkeypatch.setattr(app_module, "_samples", memstat.Every(0.0))
    monkeypatch.setattr(memstat, "rss_mb", lambda: 300.0)
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(obs, "event", lambda name, **f: seen.append((name, f)))
    TestClient(app).get("/v1/health")
    samples = [f for name, f in seen if name == "mem.sample"]
    assert samples
    assert samples[0]["rss_mb"] == 300.0
    assert {"cache_mb", "cache_entries", "top", "limit_mb"} <= samples[0].keys()


def test_trims_wait_for_growth_and_for_the_interval(monkeypatch):
    monkeypatch.setattr(memstat, "TRIM_MIN_MB", 10.0)
    trims = memstat.Trims()
    assert not trims.due(None)
    assert trims.due(400.0)
    assert not trims.due(500.0)  # one at a time
    trims.done(390.0)
    assert not trims.due(500.0)  # inside the interval
    monkeypatch.setattr(trims, "_at", float("-inf"))
    assert not trims.due(395.0)  # not 10 MB past where the last one left it
    assert trims.due(401.0)


def test_every_waits_one_period_before_the_first():
    assert not memstat.Every(60.0).due()
    every = memstat.Every(0.0)
    assert every.due() and every.due()


def test_trim_reports_what_it_handed_back():
    done = memstat.trim()
    assert done["collected"] >= 0
    assert done["ms"] >= 0
    assert isinstance(done["malloc_trim"], bool)


def test_footprint_names_the_memos_holding_the_most():
    @cache.ttl_cache(60.0, max_entries=4)
    def frames(n: int) -> pd.DataFrame:
        return pd.DataFrame({"close": range(n)}, dtype="float64")

    frames(200_000)
    found = cache.footprint(top=1000)
    row = next(c for c in found["caches"] if c["memo"].endswith("frames"))
    assert row["entries"] == 1
    assert 1.4 < row["mb"] < 1.7  # 200k float64 = 1.53 MB, index is a range
    assert found["cache_mb"] >= row["mb"]


def test_footprint_counts_a_shared_object_once():
    shared = pd.Series(range(100_000), dtype="float64")
    seen: set[int] = set()
    first = cache._bytes({"a": shared}, seen)
    assert first > 800_000
    assert cache._bytes([shared, shared], seen) < 1000


def test_sweep_drops_what_can_never_answer_again(monkeypatch):
    calls = []

    @cache.ttl_cache(10.0, stale_s=0.0)
    def quote(ticker: str) -> str:
        calls.append(ticker)
        return ticker

    quote("A")
    quote("B")
    store = next(m.store for m in cache._MEMOS if m.name.endswith("quote"))
    assert len(store) == 2
    clock = cache.time.monotonic() + 11.0
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock)
    assert cache.sweep() >= 2
    assert not store


def test_status_says_which_memos_hold_memory():
    from stocks.web.server import app as web

    memory = TestClient(web).get("/status").json()["memory"]
    assert {"cache_mb", "cache_entries", "caches", "rss_mb"} <= memory.keys()
