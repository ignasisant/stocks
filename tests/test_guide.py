"""The assistant-led walkthrough's pure half (stocks.web.guide, chat.guide_ai).

The registry it walks is `onboarding.STEPS` and is tested there; the routes
that start, sync and advance it are tested in test_api_guide.py. What is left
worth a test here is the state that both read and the model half's guards:

* **ownership** — the guide writes into one thread and must never append to a
  conversation the reader started;
* **the fence** — while on the guide's thread, the model is told which steps
  exist and nothing else;
* **the marker** — the one steering channel the model gets, withheld while it
  streams and checked against the registry when it lands;
* **the opening line** — refused when it ignored the brief, and never a cost
  to a new account's trial allowance when nothing came back.

None of the model half may ever be load bearing: with no provider at all the
walkthrough still runs, so these test that the layer stays silent rather than
that it speaks.
"""

from __future__ import annotations

from stocks.chat import guide_ai
from stocks.web import guide


def _first() -> str:
    return guide.steps()[0].id


# ------------------------------------------------------------------- thread
def test_owns_is_true_only_for_the_guides_own_thread():
    prefs = {guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"}
    assert guide.owns({"id": "c_guide"}, prefs) is True
    assert guide.owns({"id": "c_other"}, prefs) is False


def test_owns_is_false_once_the_guide_is_done():
    prefs = {guide.PREF_DONE: True, guide.PREF_THREAD: "c_guide"}
    assert guide.owns({"id": "c_guide"}, prefs) is False


def test_the_route_side_and_the_model_side_agree_on_the_thread():
    prefs = {guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"}
    assert guide_ai.owns("c_guide", prefs) is guide.owns({"id": "c_guide"}, prefs)
    assert guide_ai.owns("c_other", prefs) is guide.owns({"id": "c_other"}, prefs)


def test_current_is_none_until_started_and_after_finishing():
    assert guide.current({}) is None
    assert guide.current({guide.PREF_STEP: _first()}).id == _first()
    assert guide.current({guide.PREF_STEP: _first(), guide.PREF_DONE: True}) is None


def test_next_walks_the_registry_and_ends_after_the_last_step():
    all_steps = guide.steps()
    assert guide._next(all_steps[0]) == all_steps[1]
    assert guide._next(all_steps[-1]) is None
    assert guide._index(None) == -1


def test_a_card_is_told_apart_from_its_receipt():
    history = [{"role": "assistant", "content": "✓",
                "guide": {"step": "import", "state": "done"}}]
    assert guide._has_card(history, "import") is False
    history.append({"role": "assistant", "content": "…",
                    "guide": {"step": "import"}})
    assert guide._has_card(history, "import") is True


# --------------------------------------------------------------- the fence
def test_the_fence_lists_the_registry_and_nothing_else():
    prefs = {guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"}
    fence = guide_ai.prompt_fence(prefs, "c_guide", "en")
    assert "[[goto:" in fence
    for step in guide.steps():
        assert f"- {step.id}:" in fence


def test_the_fence_is_empty_outside_the_guides_own_thread():
    prefs = {guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"}
    assert guide_ai.prompt_fence(prefs, "c_somewhere_else", "en") == ""


def test_the_fence_is_empty_once_the_guide_is_done():
    prefs = {guide.PREF_DONE: True, guide.PREF_THREAD: "c_guide"}
    assert guide_ai.prompt_fence(prefs, "c_guide", "en") == ""


# -------------------------------------------------------------- the marker
def _streamed(chunks: list[str]) -> tuple[str, list[str]]:
    gate = guide_ai.MarkerFilter()
    text = "".join(gate.feed(c) for c in chunks) + gate.close()
    return text, gate.found


def test_a_marker_never_reaches_the_screen():
    """A client paints tokens as they arrive, so a marker shown for one frame
    reads as the assistant glitching."""
    text, found = _streamed(["Go to the import page. ", "[[goto:import]]"])
    assert "[[" not in text and "goto" not in text
    assert found == ["import"]


def test_a_marker_split_across_chunks_is_still_withheld():
    text, found = _streamed(["Sure. ", "[[go", "to:", "notify", "]]", ""])
    assert text.strip() == "Sure."
    assert found == ["notify"]


def test_a_stream_with_no_marker_arrives_whole():
    chunks = ["The ", "risk tab ", "shows [something] in brackets."]
    text, found = _streamed(chunks)
    assert text == "".join(chunks)
    assert found == []


def test_an_unclosed_bracket_is_not_swallowed():
    """A tail held back while a marker could still be forming has to be
    flushed when the stream ends, or the answer loses its last words."""
    text, _ = _streamed(["a cost basis of [30"])
    assert text == "a cost basis of [30"


def test_claim_turns_a_real_step_into_a_jump():
    turn = {"role": "assistant", "content": "Have a look. [[goto:import]]"}
    assert guide_ai.claim_goto(turn, ["import"]) == "import"
    assert turn["guide_goto"] == "import"
    assert "[[" not in turn["content"]


def test_claim_drops_a_step_the_model_invented():
    """The whole point of the fence: an id that is not in the registry leaves
    the answer standing and produces no button."""
    turn = {"role": "assistant", "content": "Open Settings. [[goto:settings]]"}
    assert guide_ai.claim_goto(turn, ["settings"]) is None
    assert "guide_goto" not in turn
    assert turn["content"] == "Open Settings."


def test_claim_takes_the_last_marker_of_a_chain():
    """A stream that fell down to a second provider can carry one from each."""
    turn = {"role": "assistant", "content": "x"}
    assert guide_ai.claim_goto(turn, ["import", "notify"]) == "notify"


# ------------------------------------------------------------- the opening
def test_a_line_that_ignored_the_brief_is_refused():
    assert guide_ai.accept("") is None
    assert guide_ai.accept("See [the docs](http://x)") is None
    assert guide_ai.accept("ok [[goto:import]]") is None
    assert guide_ai.accept("x" * 1000) is None
    trimmed = guide_ai.accept("word " * 100)
    assert trimmed is not None and len(trimmed) <= guide_ai.NARRATE_MAX_CHARS


def test_the_opening_line_waits_for_the_reader_to_press_something():
    """On the first step nothing has been asked of the reader yet, and a wait
    there reads as the app being slow rather than as the assistant thinking."""
    assert guide_ai.due_narration({guide.PREF_STEP: _first()}) is None
    second = guide.steps()[1]
    assert guide_ai.due_narration({guide.PREF_STEP: second.id}) == second


def test_it_is_attempted_once_per_account():
    prefs = {guide.PREF_STEP: guide.steps()[1].id, guide_ai.PREF_NARRATED: True}
    assert guide_ai.due_narration(prefs) is None


def test_a_free_unit_spent_on_silence_is_handed_back(monkeypatch):
    """A new account gets five free messages a day (the trial allowance).
    Spending one on a welcome that never arrived is the guide taking from the
    reader what it was supposed to give them."""
    prefs = {guide.PREF_STEP: guide.steps()[1].id}
    refunded: list[int] = []

    def _attempts(p, system, msgs, timeout, *, spend_free, accept=None):
        spend_free(p)  # the free candidate charges before it is called
        return None  # …and then answers nothing

    monkeypatch.setattr(guide_ai.engine, "complete_attempts", _attempts)
    monkeypatch.setattr(guide_ai.engine, "spend_free_quota", lambda p: True)
    monkeypatch.setattr(guide_ai.engine, "refund_free_quota",
                        lambda p, units=1: refunded.append(units))
    line = guide_ai.generate(prefs, guide.steps()[1], "en",
                             save=lambda p: None, account_facts="")
    assert line is None
    assert refunded == [1]
