"""The Yahoo circuit breaker and the bulk-download budget (stocks.data.fetch).

Not to be confused with `test_throttle.py`, which is the per-client HTTP burst
limit in front of the app — this one is about the provider throttling us.

Both exist for the same failure: Yahoo refuses this host's egress IP, and the
app spends minutes rediscovering that, once per block, on every rerun.
"""

import time

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

import stocks.data.fetch as fetch


# ------------------------------------------------------------------ breaker
def test_a_spent_retry_ladder_opens_the_cooldown():
    calls = []

    def always_limited():
        calls.append(1)
        raise YFRateLimitError()

    with pytest.raises(YFRateLimitError):
        fetch._retry(always_limited, attempts=2, base_delay=0.0)
    assert len(calls) == 2  # the ladder was climbed...
    assert fetch.throttle_remaining() > 0  # ...and lost, so the breaker is open


def test_the_cooldown_refuses_without_touching_the_network():
    fetch.trip_throttle()
    called = []
    with pytest.raises(YFRateLimitError):
        fetch._retry(lambda: called.append(1))
    assert called == []  # the point: no request, no backoff, no yfinance retries


def test_a_success_never_opens_the_cooldown():
    assert fetch._retry(lambda: "ok") == "ok"
    assert fetch.throttle_remaining() == 0


def test_one_transient_limit_still_clears_on_the_next_attempt():
    tries = []

    def flaky():
        tries.append(1)
        if len(tries) == 1:
            raise YFRateLimitError()
        return "ok"

    assert fetch._retry(flaky, attempts=3, base_delay=0.0) == "ok"
    assert fetch.throttle_remaining() == 0  # flaky is not burnt


def test_the_breaker_is_shared_with_the_quote_path():
    """One host, one verdict: a throttled price fetch also silences quotes."""
    from stocks.data import quotes as q

    fetch.trip_throttle()
    assert q.quotes(["AAPL"]) == {}


def test_clear_throttle_reopens_the_line():
    fetch.trip_throttle()
    assert fetch.throttle_remaining() > 0
    fetch.clear_throttle()
    assert fetch.throttle_remaining() == 0
    assert fetch._retry(lambda: "ok") == "ok"


def test_trip_throttle_never_shortens_a_longer_cooldown():
    fetch.trip_throttle(cooldown=120)
    fetch.trip_throttle(cooldown=1)
    assert fetch.throttle_remaining() > 60


# ------------------------------------------------------------------- budget
def test_a_hung_download_gives_up_at_the_budget():
    slow = []

    def hang():
        slow.append(1)
        time.sleep(5)

    started = time.monotonic()
    with pytest.raises(YFRateLimitError):
        fetch._budgeted(hang, budget=0.1)
    # The caller is freed on the budget, not on the hang.
    assert time.monotonic() - started < 2
    assert slow == [1]


def test_the_budget_does_not_open_the_cooldown():
    """Slow is not the same claim as refused — the next rerun must try again."""
    with pytest.raises(YFRateLimitError):
        fetch._budgeted(lambda: time.sleep(5), budget=0.1)
    assert fetch.throttle_remaining() == 0


def test_a_download_inside_its_budget_is_untouched():
    assert fetch._budgeted(lambda: "frames", budget=5) == "frames"


def test_an_error_under_budget_propagates_unchanged():
    def boom():
        raise ValueError("bad frame")

    with pytest.raises(ValueError, match="bad frame"):
        fetch._budgeted(boom, budget=5)


def test_fetch_many_bounds_the_whole_retry_ladder(monkeypatch):
    """The budget wraps the retries, not each one: three attempts must not buy
    three budgets."""
    monkeypatch.setattr(fetch, "ticker_aliases", dict)

    def hang(*a, **k):
        time.sleep(5)
        raise YFRateLimitError()

    monkeypatch.setattr(fetch.yf, "download", hang)
    started = time.monotonic()
    with pytest.raises(YFRateLimitError):
        fetch.fetch_many(["AAPL", "NVDA"], budget=0.2)
    assert time.monotonic() - started < 2


def test_fetch_many_still_returns_frames(monkeypatch):
    monkeypatch.setattr(fetch, "ticker_aliases", dict)
    idx = pd.date_range("2026-01-05", periods=2, name="Date")
    frame = pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
    monkeypatch.setattr(fetch.yf, "download", lambda *a, **k: frame)
    out = fetch.fetch_many(["AAPL"])
    assert list(out) == ["AAPL"] and len(out["AAPL"]) == 2
