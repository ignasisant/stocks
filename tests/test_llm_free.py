"""Free-chain fallback semantics (web/llm.py) — pure, no network, no secrets."""

import json
import time
from pathlib import Path

import pytest

import stocks.web.llm as llm
from stocks.chat import engine
from stocks.web.llm import FreeTierExhausted, _FreeBackend


def _ok(bid, chunks):
    def stream(api_key, model, system, messages):
        yield from chunks

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream)


def _dead(bid, exc=None):
    exc = exc or RuntimeError("429 rate limited")

    def stream(api_key, model, system, messages):
        raise exc
        yield  # unreachable; makes this a generator like the real backends

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream)


def _dies_midway(bid, exc):
    def stream(api_key, model, system, messages):
        yield "partial "
        raise exc

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream)


def test_first_healthy_backend_wins(monkeypatch):
    monkeypatch.setattr(
        llm, "_free_backends",
        lambda: [_ok("groq", ["g1", "g2"]), _ok("openrouter", ["c"])],
    )
    assert list(llm._free_stream("", "auto", "sys", [])) == ["g1", "g2"]


def test_falls_back_when_first_backend_fails(monkeypatch):
    monkeypatch.setattr(
        llm, "_free_backends", lambda: [_dead("groq"), _ok("openrouter", ["a", "b"])]
    )
    assert list(llm._free_stream("", "auto", "sys", [])) == ["a", "b"]


def test_exhausted_when_all_backends_fail(monkeypatch):
    monkeypatch.setattr(llm, "_free_backends", lambda: [_dead("a"), _dead("b")])
    with pytest.raises(FreeTierExhausted):
        list(llm._free_stream("", "auto", "sys", []))


def test_exhausted_when_unconfigured(monkeypatch):
    monkeypatch.setattr(llm, "_free_backends", lambda: [])
    with pytest.raises(FreeTierExhausted):
        list(llm._free_stream("", "auto", "sys", []))


def test_mid_answer_failure_reraises_instead_of_switching(monkeypatch):
    # Once text has streamed to the screen, hopping to another backend would
    # splice two half-answers from different models — re-raise instead.
    boom = RuntimeError("connection reset")
    monkeypatch.setattr(
        llm, "_free_backends", lambda: [_dies_midway("a", boom), _ok("b", ["never"])]
    )
    out = []
    with pytest.raises(RuntimeError, match="connection reset"):
        for chunk in llm._free_stream("", "auto", "sys", []):
            out.append(chunk)
    assert out == ["partial "]


class _FakeModels:
    def __init__(self, ids):
        self._ids = ids

    def list(self):
        return [type("M", (), {"id": i})() for i in self._ids]


def _fake_openai(ids):
    """Stands in for openai.OpenAI so _live_model can read a /models list."""

    class _Client:
        def __init__(self, **kw):
            self.models = _FakeModels(ids)

    return _Client


def _retired(bid, live_model=None):
    """A backend whose configured slug is gone; `live_model` answers instead."""
    gone = RuntimeError(f"Error code: 404 - model_not_found: The model "
                        f"`model-{bid}` does not exist")

    def stream(api_key, model, system, messages):
        if model != live_model:
            raise gone
        yield f"{model}-said-hi"

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream,
                        f"https://{bid}.example/v1")


@pytest.fixture(autouse=True)
def _clear_live_model_cache():
    llm._free_live_model.clear()
    yield
    llm._free_live_model.clear()


def test_retired_slug_is_replaced_from_the_backends_model_list(monkeypatch):
    b = _retired("groq", live_model="llama-9-instant")
    monkeypatch.setattr(llm, "_free_backends", lambda: [b])
    monkeypatch.setattr("openai.OpenAI",
                        _fake_openai(["whisper-large-v3", "llama-9-instant"]))
    assert list(llm._free_stream("", "auto", "sys", [])) == ["llama-9-instant-said-hi"]


def test_a_proven_replacement_is_reused_for_the_next_call(monkeypatch):
    monkeypatch.setattr(llm, "_free_secrets",
                        lambda: {"groq": "gsk-x", "groq_model": "retired-slug"})
    llm._free_live_model["groq"] = "llama-9-instant"
    assert llm._free_backends()[0].model == "llama-9-instant"


def test_only_a_retired_model_triggers_the_model_list(monkeypatch):
    # A rate limit must fall straight through to the next backend: asking for
    # /models would spend a request on a tier that is already over its cap.
    calls = []
    monkeypatch.setattr(llm, "_live_model", lambda b: calls.append(b.id))
    monkeypatch.setattr(
        llm, "_free_backends", lambda: [_dead("groq"), _ok("openrouter", ["c"])]
    )
    assert list(llm._free_stream("", "auto", "sys", [])) == ["c"]
    assert calls == []


def test_backend_that_hides_its_model_list_falls_through(monkeypatch):
    monkeypatch.setattr(
        llm, "_free_backends",
        lambda: [_retired("groq", live_model="never"), _ok("openrouter", ["c"])],
    )

    def _boom(**kw):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr("openai.OpenAI", _boom)
    assert list(llm._free_stream("", "auto", "sys", [])) == ["c"]


def test_cerebras_left_the_chain(monkeypatch):
    # Every model has answered 402 since 2026-08-31: a key in the secrets must
    # not put the dead hop back.
    monkeypatch.setattr(llm, "_free_secrets", lambda: {"cerebras": "csk-x"})
    assert llm._free_backends() == []


def _capped(bid, chunks, tpm, seen):
    def stream(api_key, model, system, messages):
        seen.append((bid, messages))
        yield from chunks

    return _FreeBackend(bid, f"key-{bid}", f"model-{bid}", stream, tpm=tpm)


def _thread(turns, words=400):
    return [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"turn {i} " + "word " * words} for i in range(turns)]


def test_groq_carries_its_free_tier_cap(monkeypatch):
    monkeypatch.setattr(llm, "_free_secrets",
                        lambda: {"groq": "gsk-x", "openrouter": "sk-or-x"})
    groq, openrouter = llm._free_backends()
    assert (groq.tpm, openrouter.tpm) == (8000, 0)
    monkeypatch.setattr(llm, "_free_secrets",
                        lambda: {"groq": "gsk-x", "groq_tpm": "30000"})
    assert llm._free_backends()[0].tpm == 30000


def test_a_turn_that_fits_the_cap_goes_to_groq_untouched(monkeypatch):
    seen = []
    thread = _thread(2, words=50)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _capped("groq", ["g"], 8000, seen), _capped("openrouter", ["o"], 0, seen)])
    assert list(llm._free_stream("", "auto", "sys", thread)) == ["g"]
    assert seen == [("groq", thread)]


def test_a_turn_over_the_cap_tries_the_uncapped_backend_first(monkeypatch):
    # Groq refuses a request over its per-minute cap outright (413), so the
    # whole thread goes to a backend that can take it before Groq is asked.
    seen = []
    thread = _thread(40)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _capped("groq", ["g"], 8000, seen), _capped("openrouter", ["o"], 0, seen)])
    assert list(llm._free_stream("", "auto", "sys", thread)) == ["o"]
    assert seen == [("openrouter", thread)]


def test_groq_is_the_last_resort_with_the_thread_cut_to_its_cap(monkeypatch):
    from stocks.chat import tokens

    seen = []
    thread = _thread(40)
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _capped("groq", ["g"], 8000, seen), _dead("openrouter")])
    assert list(llm._free_stream("", "auto", "sys", thread)) == ["g"]
    (bid, sent), = seen
    assert bid == "groq"
    assert sent[-1] == thread[-1]  # the question survives; old turns went
    assert len(sent) < len(thread)
    assert tokens.count("sys") + tokens.count_messages(sent) <= 8000 * 0.9


def test_a_system_prompt_over_the_cap_skips_the_backend(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "_free_backends", lambda: [
        _capped("groq", ["g"], 8000, seen), _dead("openrouter")])
    with pytest.raises(FreeTierExhausted):
        list(llm._free_stream("", "auto", "word " * 9000, _thread(1, 5)))
    assert seen == []


def test_tool_schemas_count_against_the_cap(monkeypatch):
    from stocks.chat import tokens

    thread = _thread(1, words=20)
    backends = [_capped("groq", ["g"], 1000, []), _capped("openrouter", [], 0, [])]
    base = tokens.count("sys") + tokens.count_messages(thread)
    plan = llm._free_plan(backends, "sys", thread)
    assert [b.id for b, _ in plan] == ["groq", "openrouter"]
    plan = llm._free_plan(backends, "sys", thread, extra=900 - base + 1)
    assert [b.id for b, _ in plan] == ["openrouter", "groq"]


def test_chat_model_preference_skips_non_chat_slugs():
    assert llm._pick_chat_model(
        ["whisper-large-v3", "llama-guard-4-12b", "playai-tts",
         "llama-3.1-8b-instant", "llama-4-70b-versatile"]
    ) == "llama-4-70b-versatile"
    assert llm._pick_chat_model(["whisper-large-v3", "playai-tts"]) is None
    assert llm._pick_chat_model([]) is None
    # Nothing preferred: first chat slug alphabetically, not a guard model.
    assert llm._pick_chat_model(["zeta-9", "llama-guard-x", "alpha-1"]) == "alpha-1"


def test_retired_model_detection():
    assert llm._retired_model(RuntimeError("model_not_found"))
    assert llm._retired_model(RuntimeError("The model `x` does not exist"))
    assert not llm._retired_model(RuntimeError("429 rate limited"))
    rate_limited = RuntimeError("model_not_found")
    rate_limited.status_code = 429  # status wins over the message
    assert not llm._retired_model(rate_limited)


def test_error_mapping():
    assert llm._free_error(FreeTierExhausted()) == "chat.free_exhausted"
    assert llm._free_error(RuntimeError("anything else")) == "chat.api_error"


def test_backends_follow_fixed_order_and_model_override(monkeypatch):
    # Chain order comes from _FREE_BACKEND_DEFAULTS, not secrets order; extra
    # non-backend keys (daily_cap) are ignored; "<id>_model" overrides.
    monkeypatch.setattr(
        llm,
        "_free_secrets",
        lambda: {"openrouter": "sk-or-x", "groq": "gsk-x",
                 "groq_model": "qwen-32b", "daily_cap": 5},
    )
    got = llm._free_backends()
    assert [b.id for b in got] == ["groq", "openrouter"]
    assert got[0].model == "qwen-32b"
    assert got[1].model == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_blank_keys_are_skipped(monkeypatch):
    monkeypatch.setattr(llm, "_free_secrets", lambda: {"groq": "  ", "openrouter": ""})
    assert llm._free_backends() == []


def test_free_provider_registration(monkeypatch):
    p = llm.PROVIDERS["free"]
    assert p.needs_key is False
    assert p.default_model == "auto"

    monkeypatch.setattr(llm, "_free_backends", lambda: [])
    assert not p.available()
    assert llm.default_provider_id() == llm.DEFAULT_PROVIDER

    monkeypatch.setattr(llm, "_free_backends", lambda: [_ok("groq", ["x"])])
    assert p.available()
    assert llm.default_provider_id() == "free"


# --------------------------------------------- global cap across restarts


@pytest.fixture
def global_counter(tmp_path, monkeypatch):
    """A fresh persisted counter, isolated from the real data dir."""
    monkeypatch.setattr(engine, "GLOBAL_FREE_FILE", tmp_path / "free_llm_global.json")
    monkeypatch.setattr(engine, "_global_free", {"day": "", "used": 0})
    monkeypatch.setattr(engine, "_global_free_loaded", False)
    monkeypatch.setattr(engine.storage, "enabled", lambda: False)
    return engine.GLOBAL_FREE_FILE


def _restart(monkeypatch):
    """What a Cloud Run recycle does: same file, empty process memory."""
    monkeypatch.setattr(engine, "_global_free", {"day": "", "used": 0})
    monkeypatch.setattr(engine, "_global_free_loaded", False)


def test_the_global_spend_is_written_down(global_counter, monkeypatch):
    monkeypatch.setattr(engine, "free_global_daily_cap", lambda: 5)
    assert engine._spend_global_free()
    saved = json.loads(global_counter.read_text())
    assert saved["used"] == 1 and saved["day"] == time.strftime("%Y-%m-%d")


def test_a_restart_does_not_hand_out_the_days_budget_again(global_counter,
                                                           monkeypatch):
    # The lever an abuser leans on: a recycle is free to provoke, and an
    # in-memory counter reissues the whole cap on every one of them.
    monkeypatch.setattr(engine, "free_global_daily_cap", lambda: 3)
    for _ in range(3):
        assert engine._spend_global_free()
    assert not engine._spend_global_free()

    _restart(monkeypatch)
    assert not engine._spend_global_free()


def test_yesterdays_count_does_not_carry_over(global_counter, monkeypatch):
    monkeypatch.setattr(engine, "free_global_daily_cap", lambda: 2)
    global_counter.write_text(json.dumps({"day": "2000-01-01", "used": 999}))
    assert engine._spend_global_free()


def test_an_unreadable_counter_errs_generous(global_counter, monkeypatch):
    # A cost guard, not a ledger: a read hiccup must not deny the free tier to
    # everyone for the rest of the day.
    monkeypatch.setattr(engine, "free_global_daily_cap", lambda: 2)
    global_counter.write_text("{not json")
    assert engine._spend_global_free()


def test_an_unwritable_counter_still_counts_in_memory(global_counter, monkeypatch):
    # A counter that cannot be saved is a counter that forgets across
    # restarts, not one that stops counting inside this process.
    monkeypatch.setattr(engine, "free_global_daily_cap", lambda: 2)
    blocked = global_counter.parent / "a-file"
    blocked.write_text("not a directory")
    monkeypatch.setattr(engine, "GLOBAL_FREE_FILE", blocked / "counter.json")
    assert engine._spend_global_free()
    assert engine._spend_global_free()
    assert not engine._spend_global_free()  # the cap still holds


def test_the_file_is_read_once_per_process(global_counter, monkeypatch):
    monkeypatch.setattr(engine, "free_global_daily_cap", lambda: 10)
    reads = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text",
                        lambda self, *a, **kw: reads.append(self) or real(self, *a, **kw))
    for _ in range(3):
        engine._spend_global_free()
    assert sum(1 for r in reads if r == global_counter) <= 1
