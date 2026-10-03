"""How much memory this process holds, and where the instance's limit is.

Cloud Run kills the container at its memory limit, and what it counts is the
cgroup's figure — the process's resident set *plus* every file written at
runtime, because the container filesystem is memory too (`data/memo`, the
R2 restores, the logo mirror). Neither number was visible anywhere: the
platform's utilization metric says how full the instance is, never which
request filled it. `/status` reports these, and `api.app` logs `mem.step`
for a request that grew the process by more than `STEP_MB`.

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
