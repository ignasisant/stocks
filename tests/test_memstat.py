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


def test_an_ordinary_request_logs_nothing(monkeypatch):
    readings = iter([300.0, 301.0])
    monkeypatch.setattr(memstat, "rss_mb", lambda: next(readings))
    seen: list[str] = []
    monkeypatch.setattr(obs, "warn", lambda name, **fields: seen.append(name))
    TestClient(app).get("/v1/health")
    assert "mem.step" not in seen
