"""metering: what a chat turn spent on models, by step, in tokens and dollars."""

import threading
from datetime import date
from types import SimpleNamespace

import pytest

from stocks.web import metering
from stocks.web.metering import Meter, Use


def test_a_listed_model_has_a_price_and_an_unlisted_one_none():
    assert metering.price("claude-sonnet-5-5").output == 10.0
    assert metering.price("some-new-model") is None
    # Not before it was checked: a dated price says nothing about the past.
    assert metering.price("gpt-4o", on=date(2020, 1, 1)) is None


def test_an_openrouter_slug_is_priced_as_the_vendors_own_model():
    assert (metering.price("anthropic/claude-sonnet-5.5")
            == metering.price("claude-sonnet-5-5"))


def test_a_call_is_priced_by_its_kind_of_token():
    use = Use("claude-opus-5-5", "answer", input=1_000_000, cached=1_000_000,
              cache_write=1_000_000, output=1_000_000)
    assert use.usd() == pytest.approx(4.0 + 0.20 + 5.0 + 20.0)


def test_the_free_chain_costs_nothing_whatever_the_model():
    assert Use("nvidia/nemotron-x:free", "gather", input=10**6,
               free=True).usd() == 0.0


def test_one_unpriced_call_makes_the_turn_cost_unknown():
    m = Meter()
    m.add(Use("gpt-4o-mini", "gather", input=1000))
    assert m.usd() is not None
    m.add(Use("some-new-model", "answer", input=1000))
    assert m.usd() is None
    assert m.usd("gather") is not None  # the priced step still is


def test_tokens_are_kept_by_step():
    m = Meter()
    m.add(Use("m", "gather", input=100, output=10))
    m.add(Use("m", "gather", cached=50))
    m.add(Use("m", "answer", input=7))
    assert m.by_step() == {"gather": 160, "answer": 7}
    assert m.tokens("gather") == 160 and m.tokens() == 167


def test_a_call_outside_a_turn_is_not_recorded():
    metering.note("m", input=5)  # no meter current: nothing to fail on


def test_a_note_lands_on_the_current_meter_under_its_step():
    with metering.metered() as m, metering.step("gather"):
        metering.note("m", input=5, output=1)
    assert m.uses == [Use("m", "gather", input=5, output=1)]


def test_openai_usage_counts_the_cached_share_once():
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=50,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=400))
    with metering.metered() as m:
        metering.note_openai("gpt-4o", usage)
    (use,) = m.uses
    assert (use.input, use.cached, use.output) == (600, 400, 50)


def test_anthropic_usage_keeps_cache_reads_and_writes_apart():
    usage = SimpleNamespace(input_tokens=10, cache_read_input_tokens=200,
                            cache_creation_input_tokens=30, output_tokens=5)
    with metering.metered() as m:
        metering.note_anthropic("claude-haiku-4-5", usage)
    (use,) = m.uses
    assert (use.input, use.cached, use.cache_write, use.output) == (10, 200, 30, 5)


def test_a_bound_call_takes_the_meter_to_another_thread():
    m = Meter()
    fn = metering.bound(lambda: metering.note("m", input=1), meter=m,
                        step="gather")
    t = threading.Thread(target=fn)
    t.start()
    t.join()
    assert [u.step for u in m.uses] == ["gather"]


def test_a_generator_stepped_on_fresh_threads_keeps_its_meter():
    # How a server streams a response: every `next` on a pool thread, each
    # with a context of its own.
    def chunks():
        metering.note("m", input=1)
        yield "a"
        metering.note("m", output=1)
        yield "b"

    m = Meter()
    it = metering.iterate(chunks(), meter=m, step="answer")
    got = []

    def step():
        got.append(next(it, None))

    for _ in range(3):
        t = threading.Thread(target=step)
        t.start()
        t.join()
    assert got == ["a", "b", None]
    assert [(u.step, u.tokens) for u in m.uses] == [("answer", 1), ("answer", 1)]
