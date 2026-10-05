"""memstat: the memory figures `/status` reports and `mem.step` logs.

Cloud Run kills the container at the cgroup's figure, which counts runtime
files as well as the process — so these must read the cgroup when it is
there, say None (never raise) when it is not, and the API must name a
request that grew the process by a step.
"""

from fastapi.testclient import TestClient

from stocks import memstat, obs
from stocks.api.app import app


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
    assert steps.end(700.0) is None
    assert steps.end(720.0) is None
    step = steps.end(744.0)
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
    assert steps.end(355.0) is None  # 5 MB, not 55: the old burst is closed
    steps.start("/v1/health", 355.0)
    assert steps.end(380.0)["concurrent"] == 1


def test_a_wide_burst_caps_the_paths_it_names():
    steps = memstat.Steps()
    for i in range(memstat.Steps.MAX_PATHS + 3):
        steps.start(f"/v1/p{i}", 100.0)
    for _ in range(memstat.Steps.MAX_PATHS + 2):
        steps.end(100.0)
    step = steps.end(200.0)
    assert step["path"].endswith("(+3 more)")
    assert step["concurrent"] == memstat.Steps.MAX_PATHS + 3


def test_every_request_closes_its_burst_a_miss_too(monkeypatch):
    import sys

    # The module, not `stocks.api.app` the attribute, which is the app itself.
    app_module = sys.modules["stocks.api.app"]
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
