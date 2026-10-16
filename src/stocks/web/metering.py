"""What a chat turn spent on models: tokens per step, and dollars when known.

Every model call in web/llm.py reports its usage here (`note`), and lands on
the meter of the turn it ran for. A turn makes several calls on several
threads — the skill router, the gather's rounds, the debate, the answer — so
the meter rides a context variable, and the threads a turn starts are handed
a copy of its context (`bound`, `iterate`, engine.in_parallel).

Dollars are honest or absent. A price is the vendor's published list price on
the date it was checked; a model without one makes the whole turn's cost
None rather than a number that is quietly too low. The free chain is
operator-funded on free tiers and costs 0. OpenRouter slugs are priced at the
vendor's own list price, which is what OpenRouter passes through.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from stocks import obs


@dataclass(frozen=True)
class Price:
    """USD per million tokens, from `since`. `cache_write` is Anthropic's
    5-minute write (1.25x input); the other vendors cache without one."""

    since: date
    input: float
    cached: float
    output: float
    cache_write: float = 0.0


# Checked 2026-10-15 against platform.claude.com/docs/en/about-claude/pricing
# and developers.openai.com/api/docs/pricing. Newest first per model; a model
# missing here is unpriced, not free.
PRICES: dict[str, tuple[Price, ...]] = {
    "claude-opus-5-5": (Price(date(2026, 10, 15), 4.0, 0.20, 20.0, 5.0),),
    "claude-sonnet-5-5": (Price(date(2026, 10, 15), 2.0, 0.10, 10.0, 2.5),),
    "claude-haiku-4-5": (Price(date(2026, 10, 15), 1.0, 0.10, 5.0, 1.25),),
    "gpt-5": (Price(date(2026, 10, 15), 1.25, 0.125, 10.0),),
    "gpt-4o": (Price(date(2026, 10, 15), 2.5, 1.25, 10.0),),
    "gpt-4o-mini": (Price(date(2026, 10, 15), 0.15, 0.075, 0.6),),
}


def price(model: str, on: date | None = None) -> Price | None:
    """The list price of `model` on `on` (today), or None when unknown.

    An OpenRouter slug is looked up by its own name: "anthropic/claude-
    sonnet-5.5" is "claude-sonnet-5-5"."""
    name = model.rsplit("/", 1)[-1].replace(".", "-")
    on = on or date.today()
    for p in PRICES.get(name, ()):
        if p.since <= on:
            return p
    return None


@dataclass(frozen=True)
class Use:
    """One model call's tokens. `input` is billed at the full rate, so a
    vendor that counts cached tokens inside its prompt total has them taken
    out before they get here."""

    model: str
    step: str
    input: int = 0
    cached: int = 0
    cache_write: int = 0
    output: int = 0
    free: bool = False

    @property
    def tokens(self) -> int:
        return self.input + self.cached + self.cache_write + self.output

    def usd(self) -> float | None:
        if self.free:
            return 0.0
        p = price(self.model)
        if p is None:
            return None
        return (self.input * p.input + self.cached * p.cached
                + self.cache_write * (p.cache_write or p.input)
                + self.output * p.output) / 1_000_000


@dataclass
class Meter:
    """One turn's uses. Calls land from several threads, hence the lock."""

    uses: list[Use] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, use: Use) -> None:
        with self._lock:
            self.uses.append(use)

    def _snapshot(self, step: str | None) -> list[Use]:
        with self._lock:
            return [u for u in self.uses if step is None or u.step == step]

    def tokens(self, step: str | None = None) -> int:
        return sum(u.tokens for u in self._snapshot(step))

    def usd(self, step: str | None = None) -> float | None:
        """Dollars spent, or None when any call was on an unpriced model."""
        total = 0.0
        for u in self._snapshot(step):
            cost = u.usd()
            if cost is None:
                return None
            total += cost
        return round(total, 6)

    def by_step(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for u in self._snapshot(None):
            out[u.step] = out.get(u.step, 0) + u.tokens
        return out

    def models(self) -> list[str]:
        return sorted({u.model for u in self._snapshot(None)})


_current: contextvars.ContextVar[Meter | None] = contextvars.ContextVar(
    "stocks_meter", default=None)
_step: contextvars.ContextVar[str] = contextvars.ContextVar(
    "stocks_meter_step", default="other")


def current() -> Meter | None:
    return _current.get()


def _context(meter: Meter | None, step: str,
             fields: dict | None) -> contextvars.Context:
    ctx = contextvars.copy_context()
    if meter is not None:
        ctx.run(_current.set, meter)
    if step:
        ctx.run(_step.set, step)
    if fields:
        ctx.run(obs.bind, **fields)
    return ctx


def bound(fn: Callable[..., Any], *, meter: Meter | None = None,
          step: str = "", fields: dict | None = None) -> Callable[..., Any]:
    """`fn` in a copy of the caller's context — its meter, or `meter` — with
    its calls labelled `step` and its log lines carrying `fields`, on
    whichever thread runs it. Once: a context cannot be entered by two
    threads at a time."""
    ctx = _context(meter, step, fields)
    return lambda *a, **kw: ctx.run(fn, *a, **kw)


def iterate(items: Iterator[Any], *, meter: Meter | None = None,
            step: str = "", fields: dict | None = None) -> Iterator[Any]:
    """`items`, each step of it run as `bound` would run it.

    A generator runs in whatever context its consumer's `next` has, and a
    server that iterates a response on pool threads gives each `next` a fresh
    one: a meter set inside would not survive to the next chunk. Closed in
    the same context too, so its own cleanup sees what it set."""
    ctx = _context(meter, step, fields)
    try:
        while True:
            try:
                item = ctx.run(next, items)
            except StopIteration:
                return
            yield item
    finally:
        close = getattr(items, "close", None)
        if close is not None:
            ctx.run(close)


@contextlib.contextmanager
def metered(meter: Meter | None = None) -> Generator[Meter]:
    """Make `meter` (a new one) current for the block."""
    meter = meter or Meter()
    token = _current.set(meter)
    try:
        yield meter
    finally:
        _current.reset(token)


@contextlib.contextmanager
def step(name: str) -> Generator[None]:
    """Label the calls made in the block: "gather", "answer", ..."""
    token = _step.set(name)
    try:
        yield
    finally:
        _step.reset(token)


def note(model: str, *, input: int = 0, cached: int = 0, cache_write: int = 0,
         output: int = 0, free: bool = False) -> None:
    """Record one call's usage on the current turn's meter, if there is one."""
    meter = _current.get()
    if meter is None:
        return
    meter.add(Use(model, _step.get(), int(input or 0), int(cached or 0),
                  int(cache_write or 0), int(output or 0), free))


def _n(obj: Any, name: str) -> int:
    return int(getattr(obj, name, 0) or 0)


def note_anthropic(model: str, usage: Any) -> None:
    """From an Anthropic `usage`: input_tokens excludes the cache's share."""
    if usage is None:
        return
    note(model, input=_n(usage, "input_tokens"),
         cached=_n(usage, "cache_read_input_tokens"),
         cache_write=_n(usage, "cache_creation_input_tokens"),
         output=_n(usage, "output_tokens"))


def note_openai(model: str, usage: Any, *, free: bool = False) -> None:
    """From an OpenAI-shaped `usage`: prompt_tokens includes the cached."""
    if usage is None:
        return
    prompt = _n(usage, "prompt_tokens")
    cached = _n(getattr(usage, "prompt_tokens_details", None), "cached_tokens")
    note(model, input=max(0, prompt - cached), cached=cached,
         output=_n(usage, "completion_tokens"), free=free)


def note_gemini(model: str, usage: Any) -> None:
    """From Gemini's `usage_metadata`: thinking is billed as output."""
    if usage is None:
        return
    prompt = _n(usage, "prompt_token_count")
    cached = _n(usage, "cached_content_token_count")
    note(model, input=max(0, prompt - cached), cached=cached,
         output=_n(usage, "candidates_token_count")
         + _n(usage, "thoughts_token_count"))
