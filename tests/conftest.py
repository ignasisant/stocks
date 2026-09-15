"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _no_yahoo_cooldown():
    """Start every test with `data.fetch`'s circuit breaker closed.

    The breaker is deliberately process-wide — one host, one verdict about
    Yahoo — which in a test run means one module's exhausted retry ladder would
    otherwise silence every fetch in the files that come after it, as a batch
    of unrelated failures. That is real behaviour, not a bug, so the reset
    belongs here rather than in each suite that happens to trip it.
    """
    from stocks.data.fetch import clear_throttle

    clear_throttle()
    yield
    clear_throttle()
