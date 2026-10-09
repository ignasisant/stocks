"""Chat turns that outlive the request that asked for them.

A turn used to be the response stream itself: the model was read only as fast
as the browser read the stream, so leaving the page (a closed tab, a phone that
put the browser to sleep) stopped the model mid-answer and nothing reached
chat.json — the question and the words were both lost, and the free unit spent.

Here a turn is a `Run`: a worker thread drives the turn's event stream and
keeps every frame it produced, and a response only *tails* that log. A reader
who leaves stops tailing and nothing else; the answer is written and stored as
if they had stayed, and a reader who comes back replays the log from the start
(`GET /chat/runs/{id}`) and watches the rest arrive.

Cloud Run allocates CPU to an instance only while it is serving a request, and
a worker whose reader left has none. So on Cloud Run the run also calls itself:
`POST …/hold` through the service's public URL, a request that does nothing
but stay open until the run is over (`hold`). That keeps request-based billing
— the turn is paid for the seconds it takes, as before — instead of
`--no-cpu-throttling`, which with the uptime check keeping the instance warm
would bill it around the clock.

In memory on purpose: the service runs at --max-instances 1, so every tail
and every hold reaches the process that holds the run. A deploy or a crash
loses a turn in flight; the reader who comes back finds the thread without it,
as everyone did before this.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field

from stocks import obs

#: How long a finished run stays replayable. A reader back from another tab
#: within it is shown the answer being finished rather than only the result;
#: after it, the stored thread is the whole story.
KEEP_S = 600.0
#: A comment line sent to a tail that has been waiting this long, so neither a
#: proxy nor the browser takes a quiet model for a dead connection.
PING_S = 15.0
#: The longest a hold stays open: under Cloud Run's 300 s request timeout, and
#: well past the engine's own 90 s per provider attempt.
HOLD_S = 280.0
#: Runs one account may have in the registry at once, finished ones included.
PER_OWNER = 8

PING = ": ping\n\n"


@dataclass
class Run:
    """One turn being answered, and everything it has said so far.

    `owner` is the account (its chat file), so a run id another account sends
    is simply not found. `failed` is a run that ended on a refusal, which
    stores nothing: a reader who never saw it end is shown it on return
    (`unseen`), because the thread alone would just have lost their question.
    """

    id: str
    owner: str
    thread: str
    question: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    frames: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    ended: float | None = None
    failed: bool = False
    seen: bool = False
    stop: threading.Event = field(default_factory=threading.Event)
    cond: threading.Condition = field(default_factory=threading.Condition)

    @property
    def live(self) -> bool:
        return self.ended is None

    def push(self, frame: str) -> None:
        with self.cond:
            self.frames.append(frame)
            self.cond.notify_all()

    def finish(self, *, failed: bool = False) -> None:
        with self.cond:
            self.failed = failed
            self.ended = time.monotonic()
            self.cond.notify_all()


_runs: dict[str, Run] = {}
_lock = threading.Lock()


def _key(owner: str, rid: str) -> str:
    return f"{owner}\0{rid}"


def _prune(now: float) -> None:
    """Drop runs finished more than KEEP_S ago. Caller holds `_lock`."""
    for key, run in list(_runs.items()):
        if run.ended is not None and now - run.ended > KEEP_S:
            del _runs[key]


class Busy(Exception):
    """The thread already has a turn being answered, or the id is taken."""


def start(*, owner: str, rid: str, thread: str, question: str,
          events: Callable[[Run], Generator[str]], stopped: str,
          failed: Callable[[str], bool]) -> Run:
    """Register run `rid` and start answering it on a worker thread.

    `events` is the turn's frame stream; the worker drives it to the end,
    keeping every frame. `stopped` is the frame a stop ends the log with, so a
    second window tailing the same run is told why it ended. `failed` says
    whether a frame is the run's refusal (`Run.failed`).
    """
    run = Run(id=rid, owner=owner, thread=thread, question=question)
    with _lock:
        _prune(time.monotonic())
        mine = [r for r in _runs.values() if r.owner == owner]
        if any(r.live and (r.thread == thread or r.id == rid) for r in mine):
            raise Busy(thread)
        # An id reused after its run ended names the new one.
        _runs.pop(_key(owner, rid), None)
        mine = [r for r in mine if r.id != rid]
        if len(mine) >= PER_OWNER:
            # The oldest finished one goes; live ones are each a thread's own.
            done = sorted((r for r in mine if not r.live), key=lambda r: r.started)
            if not done:
                raise Busy(thread)
            del _runs[_key(owner, done[0].id)]
        _runs[_key(owner, rid)] = run
    threading.Thread(target=_work, args=(run, events, stopped, failed),
                     name=f"chat-run-{rid[:8]}", daemon=True).start()
    return run


def _work(run: Run, events: Callable[[Run], Generator[str]], stopped: str,
          failed: Callable[[str], bool]) -> None:
    stream = events(run)
    refused = False
    try:
        for frame in stream:
            if run.stop.is_set():
                break
            run.push(frame)
            refused = refused or failed(frame)
    except Exception as exc:  # pragma: no cover — `events` handles its own
        obs.warn("chat.run_failed", error_type=type(exc).__name__,
                 error=str(exc)[:300])
        refused = True
    finally:
        # A stop closes the turn where it stands: the engine is left at a
        # yield, so nothing after it runs and nothing is stored — the same as
        # the reader's own abort did when the stream was the turn.
        stream.close()
        if run.stop.is_set():
            run.push(stopped)
        run.finish(failed=refused)
        obs.event("chat.run_ended", stopped=run.stop.is_set(), failed=refused,
                  seconds=round(time.monotonic() - run.started, 1),
                  tailed=run.seen)


def find(owner: str, rid: str) -> Run | None:
    with _lock:
        return _runs.get(_key(owner, rid))


def on_thread(owner: str, thread: str) -> Run | None:
    """The run a reader opening `thread` should be shown: one still being
    answered, or one that was refused while nobody was watching."""
    now = time.monotonic()
    with _lock:
        _prune(now)
        mine = [r for r in _runs.values() if r.owner == owner and r.thread == thread]
    for run in sorted(mine, key=lambda r: r.started, reverse=True):
        if run.live or (run.failed and not run.seen and not run.stop.is_set()):
            return run
    return None


def live_threads(owner: str) -> set[str]:
    """The threads of `owner` with an answer still being written."""
    with _lock:
        return {r.thread for r in _runs.values() if r.owner == owner and r.live}


def tail(run: Run) -> Iterator[str]:
    """Every frame of `run` from the first, then each new one as it arrives,
    until the run is over. A reader who leaves just stops reading this."""
    sent = 0
    while True:
        with run.cond:
            if sent >= len(run.frames) and run.live:
                run.cond.wait(PING_S)
            batch = run.frames[sent:]
            over = not run.live
        sent += len(batch)
        yield from batch
        if over and sent >= len(run.frames):
            run.seen = True
            return
        if not batch:
            yield PING


def stop(run: Run) -> None:
    """Cut the answer: the worker stops at the next thing the turn says."""
    run.seen = True
    run.stop.set()


def holding(rid: str, token: str) -> Run | None:
    """Run `rid`, for a hold that carries its token — any account's, since the
    caller is this service and the token is what proves it."""
    if not token:
        return None
    with _lock:
        found = [r for r in _runs.values() if r.id == rid]
    for run in found:
        if hmac.compare_digest(run.token, token):
            return run
    return None


def wait(run: Run, timeout: float = HOLD_S) -> None:
    """Block until `run` is over or `timeout` passes — the body of a hold."""
    deadline = time.monotonic() + timeout
    with run.cond:
        while run.live and (left := deadline - time.monotonic()) > 0:
            run.cond.wait(left)


def on_cloud_run() -> bool:
    """Cloud Run sets K_SERVICE in every instance; nothing else here does."""
    return bool(os.environ.get("K_SERVICE"))


def hold(run: Run, url: str) -> None:
    """Keep the instance's CPU while `run` is answered: one request to `url`
    (the run's own hold route, through the public front end, which is what
    Cloud Run counts) that stays open until the run is over.

    Fire and forget, on its own thread. A hold that fails costs nothing while
    the reader is still reading — their stream is a request too — and only
    risks a slow finish for one who left, so it is logged, never raised.
    """
    import httpx

    def go() -> None:
        try:
            httpx.post(url, headers={"X-Run-Hold": run.token},
                       timeout=httpx.Timeout(HOLD_S + 15, connect=10))
        except Exception as exc:
            obs.warn("chat.run_hold_failed", error_type=type(exc).__name__,
                     error=str(exc)[:300])

    threading.Thread(target=go, name=f"chat-hold-{run.id[:8]}", daemon=True).start()


def _reset() -> None:
    """Forget every run. Tests only."""
    with _lock:
        _runs.clear()
