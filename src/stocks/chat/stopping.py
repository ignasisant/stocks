"""A turn the reader stopped, as every thread still working on it sees it.

Stop used to end the *stream*: the engine was left at a yield and nothing
after it ran. Nothing after it — but the research already running on its own
threads went on, a deep gather for up to two minutes of model rounds and page
reads, every one of them paid for and none of them read. Here the turn carries
an event (`arm`), set when its stream is closed for any reason, and the work
beside it asks (`requested`, `check`) before each thing it would start: the
gather's next call and next round, the lookups' wait, the debate.

A context variable, because that is how the turn's other state (its meter, its
log fields) already reaches the pool threads it fans out to: whatever copies
the context to run a lookup carries this along.
"""

from __future__ import annotations

import contextvars
import threading

_halt: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "chat_halt", default=None)


class Stopped(Exception):
    """The reader stopped this turn; whatever was running for it gives up."""


def arm(event: threading.Event) -> None:
    """Make `event` this context's stop, for everything it fans out to."""
    _halt.set(event)


def current() -> threading.Event | None:
    """This context's stop, for code that will ask from threads which do not
    carry the context (a provider's own tool pool)."""
    return _halt.get()


def requested() -> bool:
    """Whether the turn this thread works for has been stopped."""
    event = _halt.get()
    return event is not None and event.is_set()


def check() -> None:
    """Raise `Stopped` when the turn has been stopped."""
    if requested():
        raise Stopped
