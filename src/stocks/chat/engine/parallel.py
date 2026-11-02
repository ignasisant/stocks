"""A turn's independent lookups, run at once on pool threads.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TYPE_CHECKING

from stocks import obs

if TYPE_CHECKING:

    pass


def _settle(future, timeout: float | None,
            tick: Callable[[], None] | None, poll: float) -> object:
    """One lookup's result, None if it raises or overruns `timeout`.

    With a `tick`, the wait is a poll rather than one long block: the caller
    gets the thread back every `poll` seconds to do something with it — act
    on a stop the reader has pressed — and whatever `tick` raises comes out
    of here.
    """
    left = timeout
    while True:
        step = poll if tick is not None else left
        if left is not None and (step is None or step > left):
            step = left
        try:
            return future.result(timeout=step)
        except FutureTimeout:
            if left is not None:
                left -= step or 0
                if left <= 0:
                    obs.warn("chat.engine.completion_timeout",
                             error_type="TimeoutError", error="timed out")
                    return None
            if tick is None:  # no deadline and nothing to do while waiting
                return None
            tick()
        except Exception as exc:
            obs.warn("chat.engine.completion_timeout",
                     error_type=type(exc).__name__, error=str(exc)[:300])
            return None


def in_parallel(*calls: Callable[[], object],
                timeout: float | None = None,
                tick: Callable[[], None] | None = None,
                poll: float = 0.2) -> list:
    """Run this turn's independent lookups at once, in order of the results.

    Skill routing, search planning + page reading and quote fetching share no
    inputs, and back to back they are the bulk of a turn's latency (two
    classifier calls, three page fetches, a Yahoo round-trip). A call that
    raises or overruns yields None: one dead lookup must not take the answer
    with it. Callers resolve the account *before* handing a closure over —
    these run on pool threads.

    `tick` is called every `poll` seconds while a lookup is still out. It is
    what makes the wait interruptible: these are the seconds in which a turn
    touches nothing at all.
    """
    pool = ThreadPoolExecutor(max_workers=max(1, len(calls)))
    try:
        # Each in a copy of the turn's context, so its log fields and meter
        # (`metering`) reach the pool thread.
        futures = [pool.submit(contextvars.copy_context().run, c) for c in calls]
        return [_settle(f, timeout, tick, poll) for f in futures]
    finally:
        # No wait: shutdown would block on whatever the timeout just escaped.
        pool.shutdown(wait=False, cancel_futures=True)
