"""How much memory this process holds, and where the instance's limit is.

Cloud Run kills the container at its memory limit, and what it counts is the
cgroup's figure — the process's resident set *plus* every file written at
runtime, because the container filesystem is memory too (`data/memo`, the
R2 restores, the logo mirror). Neither number was visible anywhere: the
platform's utilization metric says how full the instance is, never which
request filled it. `/status` reports these, and `api.app` logs `mem.step`
for a request, or a burst of overlapping ones (`Steps`), that grew the
process by more than `STEP_MB`.

Every read is a small file under /proc or /sys, so this is cheap enough to
run around every request. Off Linux (a laptop) the figures that need /proc
read None rather than raise.
"""

from __future__ import annotations

import resource
import sys
import threading
from pathlib import Path

from stocks.config import DATA_DIR

# A request that grows the process by this much is worth a log line: the
# steps that end in an OOM are tens of MB each, a normal request is noise.
STEP_MB = 20.0

_STATUS = Path("/proc/self/status")
# cgroup v2, then v1 — whichever the runtime mounts.
_CGROUP_USAGE = (
    Path("/sys/fs/cgroup/memory.current"),
    Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
)
_CGROUP_LIMIT = (
    Path("/sys/fs/cgroup/memory.max"),
    Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
)


def _proc_kb(field: str) -> float | None:
    try:
        for line in _STATUS.read_text().splitlines():
            if line.startswith(field + ":"):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def rss_mb() -> float | None:
    """Resident set right now, MB."""
    kb = _proc_kb("VmRSS")
    return round(kb / 1024, 1) if kb is not None else None


def peak_mb() -> float:
    """Highest resident set this process has reached, MB."""
    kb = _proc_kb("VmHWM")
    if kb is not None:
        return round(kb / 1024, 1)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Bytes on macOS, KB on Linux.
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


def _first_int(paths: tuple[Path, ...]) -> int | None:
    for path in paths:
        try:
            raw = path.read_text().strip()
        except OSError:
            continue
        # "max" in v2, a huge sentinel in v1: no limit either way.
        if raw.isdigit() and int(raw) < 1 << 60:
            return int(raw)
        return None
    return None


def cgroup_mb() -> tuple[float | None, float | None]:
    """(usage, limit) of the container, MB — the figure the OOM killer reads."""
    used, limit = _first_int(_CGROUP_USAGE), _first_int(_CGROUP_LIMIT)
    mb = 1024 * 1024
    return (
        round(used / mb, 1) if used is not None else None,
        round(limit / mb, 1) if limit is not None else None,
    )


def _dir_mb(path: Path) -> float:
    total = 0
    try:
        for file in path.rglob("*"):
            try:
                if file.is_file():
                    total += file.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return round(total / (1024 * 1024), 1)


class Steps:
    """Attribute RSS growth to requests without counting it once per request.

    The resident set is the process's, not a request's: a cold Home load fires
    fifteen API calls at once, each one's before/after spans the same climb,
    and fifteen lines each claimed the whole of it. So requests that overlap
    are one burst — it opens when the first starts, closes when the last ends,
    and yields a single step from the RSS at its opening, naming every path in
    it and how many ran at once. A request alone is a burst of one, which
    reads exactly as a per-request step. A burst that never closes (traffic
    that always overlaps a long stream) reports when it finally does.
    """

    MAX_PATHS = 12

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open = 0
        self._before = 0.0
        self._peak = 0
        self._paths: list[str] = []
        self._more = 0

    def start(self, path: str, rss: float) -> None:
        with self._lock:
            if self._open == 0:
                self._before, self._peak, self._paths, self._more = rss, 0, [], 0
            self._open += 1
            self._peak = max(self._peak, self._open)
            if path in self._paths:
                return
            if len(self._paths) < self.MAX_PATHS:
                self._paths.append(path)
            else:
                self._more += 1

    def end(self, rss: float | None) -> dict | None:
        """The step to log, once the last request of the burst ends."""
        with self._lock:
            self._open -= 1
            if self._open or rss is None or rss - self._before < STEP_MB:
                return None
            path = ", ".join(self._paths)
            if self._more:
                path += f" (+{self._more} more)"
            return {
                "path": path,
                "concurrent": self._peak,
                "delta_mb": round(rss - self._before, 1),
                "rss_mb": rss,
            }


def snapshot() -> dict:
    """Everything above, for `/status`."""
    used, limit = cgroup_mb()
    return {
        "rss_mb": rss_mb(),
        "peak_mb": peak_mb(),
        "cgroup_mb": used,
        "limit_mb": limit,
        "threads": threading.active_count(),
        # The disk memo is the part of the filesystem that grows with use.
        "memo_mb": _dir_mb(DATA_DIR / "memo"),
    }
