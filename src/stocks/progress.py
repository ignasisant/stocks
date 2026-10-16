"""What a slow load is doing right now, for the corner banner (`GET /progress`).

A cold book waits twenty seconds to a minute on its price download, and all a
browser can see of it is one request that has not answered. A bar counting
requests stands still at eleven of twelve for that whole wait, which reads as
stuck. This is the inside view: which step the download is on, how many names
it has done, and how long the same step took last time, so the banner can
move with the work instead of with the request count.

Process memory only. The deployment runs one instance (`scripts/deploy.sh`),
so the request that downloads and the poll that asks about it meet here; a
restart loses the last durations, and the banner falls back to elapsed time.

Keyed by the book's database path, which is what the download itself is keyed
by (`loaders._held_frames`) and what `GET /progress` resolves from the
caller's own account — a reader only ever sees their own book's work.
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Job:
    """One slow load of one book: the step it is on and how far along."""

    key: str
    step: str
    done: int = 0
    total: int = 0
    started: float = field(default_factory=time.monotonic)
    step_started: float = field(default_factory=time.monotonic)
    expected_s: float | None = None


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
# How long each (book, step) took the last time it finished, in seconds. What
# lets the banner say "usually ~25 s" and draw a bar for a step that cannot
# count its names (one bulk download).
_last: dict[tuple[str, str], float] = {}
_LAST_MAX = 256

_current: contextvars.ContextVar[Job | None] = contextvars.ContextVar(
    "progress_job", default=None
)


@contextmanager
def job(key: str, step: str, total: int = 0) -> Generator[Job]:
    """Mark `key` as busy on `step` for the length of the block.

    Nested calls for a key already busy join the outer job rather than
    replace it: the banner speaks for the whole load, not the inner call.
    """
    with _lock:
        outer = _jobs.get(key)
    if outer is not None:
        token = _current.set(outer)
        try:
            yield outer
        finally:
            _current.reset(token)
        return
    entry = Job(key=key, step=step, total=total, expected_s=_last.get((key, step)))
    with _lock:
        _jobs[key] = entry
    token = _current.set(entry)
    try:
        yield entry
        # Only a step that finished sets the next estimate: one refused in
        # half a second would promise the next reader a wait it never has.
        _finish_step(entry)
    finally:
        _current.reset(token)
        with _lock:
            if _jobs.get(key) is entry:
                del _jobs[key]


def _finish_step(entry: Job) -> None:
    took = time.monotonic() - entry.step_started
    with _lock:
        _last.pop((entry.key, entry.step), None)
        _last[(entry.key, entry.step)] = took
        while len(_last) > _LAST_MAX:
            _last.pop(next(iter(_last)))


def step(name: str, total: int = 0) -> None:
    """Move the current job on to `name`, with `total` names to do in it."""
    entry = _current.get()
    if entry is None or entry.step == name:
        if entry is not None and total:
            entry.total = total
        return
    _finish_step(entry)
    with _lock:
        entry.step = name
        entry.done = 0
        entry.total = total
        entry.step_started = time.monotonic()
        entry.expected_s = _last.get((entry.key, name))


def tick(n: int = 1) -> None:
    """`n` more names done in the current step. A no-op outside a job."""
    entry = _current.get()
    if entry is None:
        return
    with _lock:
        entry.done = min(entry.total or entry.done + n, entry.done + n)


def snapshot(key: str) -> dict | None:
    """The job running for `key`, as the banner reads it, or None when idle."""
    with _lock:
        entry = _jobs.get(key)
        if entry is None:
            return None
        now = time.monotonic()
        return {
            "step": entry.step,
            "done": entry.done,
            "total": entry.total,
            "elapsed_s": round(now - entry.started, 1),
            "step_elapsed_s": round(now - entry.step_started, 1),
            "expected_s": round(entry.expected_s, 1) if entry.expected_s else None,
        }


def reset() -> None:
    """Forget every job and duration (tests)."""
    with _lock:
        _jobs.clear()
        _last.clear()
