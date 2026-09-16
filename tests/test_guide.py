"""The assistant-led walkthrough (stocks.web.guide).

The registry it walks is `onboarding.STEPS` and is tested there; what is worth
a test here is the machine on top of it:

* **starting** — who gets it, who never does (guests), and when it stops
  popping itself open, because that is the difference between an onboarding
  and a nag;
* **`sync`** — the part with no equivalent in the modal tour. It advances the
  guide over what the account has actually switched on and writes the step
  cards into a real conversation, so it has to be idempotent: the panel calls
  it on every single run;
* **the ways out** — finishing, skipping and walking off must all stamp prefs
  so neither this nor the modal tour reappears next session.

Everything runs through AppTest: `guide` reads and writes session state on
every path, and its copy resolves through the run's active language.
"""

from __future__ import annotations

import dataclasses

import pytest
from streamlit.testing.v1 import AppTest

from stocks.web import auth, guide, i18n, onboarding


# ------------------------------------------------------------------ harness
def _flag(at: AppTest, key: str) -> bool:
    """A session flag, defaulting to False. AppTest's session state proxy has
    no `.get()` — it would read "get" as a widget key."""
    return bool(at.session_state[key]) if key in at.session_state else False


def _button(at: AppTest, key: str):
    """The button with this key, or None. `at.button(key=…)` raises."""
    try:
        return at.button(key=key)
    except KeyError:
        return None


def _script() -> None:
    """app.py's guide hook plus the panel's, and nothing else.

    Defined at module level because AppTest re-executes the function's *source*
    as a script — a nested function's closure would not come with it. The
    conversation stands in for chat_core.render_conversation: hydrate a
    history, let the guide bring it up to date, draw each card.
    """
    import streamlit as st

    from stocks.web import guide as _g

    st.session_state["claimed"] = _g.maybe_start()
    if "hist" not in st.session_state:
        st.session_state["hist"] = []
    history = st.session_state["hist"]
    if _g.active():
        _g.sync(history)
    for i, msg in enumerate(history):
        if msg.get("guide"):
            st.markdown(msg["content"])
            _g.render_card("panel", msg, i)
    _g.render_strip()


@pytest.fixture
def app(monkeypatch):
    """Factory for an AppTest over the guide, backed by a prefs dict.

    Everything the guide persists lands in the dict the test passes in, so
    "did it stamp the version" is a plain assertion. The account's chat book
    is a stub: threads are auth's business and tested there, and a real one
    would need a data dir per test for nothing this module decides.
    """

    def make(prefs: dict, *, logged_in: bool = True,
             saved: list | None = None,
             done: dict[str, bool] | None = None) -> AppTest:
        monkeypatch.setattr(auth, "is_logged_in", lambda: logged_in)
        monkeypatch.setattr(auth, "load_prefs", lambda path=None: dict(prefs))
        monkeypatch.setattr(
            auth, "save_prefs", lambda p, path=None: prefs.update(p)
        )
        monkeypatch.setattr(auth, "list_conversations", lambda path=None: [])
        monkeypatch.setattr(
            auth, "active_conversation", lambda path=None: {"id": "c_guide"}
        )
        monkeypatch.setattr(
            auth, "new_conversation", lambda path=None, title="": "c_guide"
        )
        monkeypatch.setattr(
            auth, "set_active_conversation", lambda cid, path=None: None
        )
        monkeypatch.setattr(
            auth, "save_chat",
            lambda h, path=None: None if saved is None else saved.append(list(h)),
        )
        # No step is switched on unless a test says so. Patched on the
        # registry rather than on the detector functions: `Step.done` holds
        # the function object captured when STEPS was built, so replacing
        # `onboarding._has_ledger` would not reach it. Which steps *have* a
        # predicate is preserved — that is what draws the on/pending badge.
        marks = done or {}
        monkeypatch.setattr(onboarding, "STEPS", tuple(
            dataclasses.replace(
                s, done=(lambda _p, _id=s.id: marks.get(_id, False))
            ) if s.done is not None else s
            for s in onboarding.STEPS
        ))
        return AppTest.from_function(_script, default_timeout=15)

    return make


def _first() -> str:
    return guide.steps()[0].id


def _cards(at: AppTest) -> list[str]:
    """Step ids the thread presents, in order."""
    return [
        m["guide"]["step"]
        for m in at.session_state["hist"]
        if m.get("guide") and not m["guide"].get("state")
    ]


# -------------------------------------------------------------------- start
def test_a_new_account_gets_the_guide_in_the_panel(app):
    prefs: dict = {}
    at = app(prefs).run()
    assert at.session_state["claimed"] is True
    assert at.session_state["chat_panel_open"] is True
    assert prefs[guide.PREF_STEP] == _first()
    assert prefs[guide.PREF_THREAD] == "c_guide"


def test_the_first_step_card_is_written_into_the_thread(app):
    at = app({}).run()
    assert _cards(at) == [_first()]
    # Real copy, not a raw catalog key falling through.
    body = i18n.translate(f"tour.{_first()}_body", "en")
    assert any(body in m.value for m in at.markdown)


def test_a_guest_never_starts_it(app):
    prefs: dict = {}
    at = app(prefs, logged_in=False).run()
    assert at.session_state["claimed"] is False
    assert prefs == {}


def test_a_finished_account_is_left_alone(app):
    at = app({guide.PREF_DONE: True}).run()
    assert at.session_state["claimed"] is False
    assert not _flag(at, "chat_panel_open")


def test_the_modal_surface_hands_onboarding_back_to_the_tour(app, monkeypatch):
    """With the flag on "modal" the guide must not claim the run, or app.py
    would suppress the tour and show nothing in its place."""
    monkeypatch.setattr(guide, "surface", lambda: "modal")
    at = app({}).run()
    assert at.session_state["claimed"] is False


def test_it_stops_popping_itself_open_after_three_sessions(app):
    """Still running — the strip and the launcher resume it — it just stops
    opening itself, which is the line between an onboarding and a nag."""
    prefs = {guide.PREF_STEP: _first(), guide.PREF_OPENS: guide.MAX_AUTO_OPENS}
    at = app(prefs).run()
    assert at.session_state["claimed"] is True  # still owns onboarding
    assert not _flag(at, "chat_panel_open")  # but did not open
    assert prefs[guide.PREF_OPENS] == guide.MAX_AUTO_OPENS  # nothing spent


def test_the_query_param_opens_at_a_named_step_without_spending_a_pop(app):
    prefs: dict = {}
    at = app(prefs)
    at.query_params["guide"] = "notify"
    at.run()
    assert prefs[guide.PREF_STEP] == "notify"
    assert prefs.get(guide.PREF_OPENS) is None
    assert at.session_state["chat_panel_open"] is True


# --------------------------------------------------------------------- sync
def test_sync_never_writes_the_same_card_twice(app):
    at = app({}).run()
    at.run()  # a second run of the panel, as any rerun would be
    at.run()
    assert _cards(at) == [_first()]


def test_sync_walks_past_a_step_the_account_already_switched_on(app):
    """The point of the whole surface: import a statement in another tab, come
    back, and the guide has moved on by itself."""
    prefs = {guide.PREF_STEP: "import"}
    at = app(prefs, done={"import": True}).run()
    assert prefs[guide.PREF_STEP] != "import"
    # It says so rather than silently skipping — one receipt, then the card.
    states = [m["guide"].get("state") for m in at.session_state["hist"]
              if m.get("guide")]
    assert "done" in states
    assert _cards(at) == [guide._next(onboarding.by_id("import")).id]


def test_sync_chains_over_every_step_already_switched_on(app):
    """Three of the registry's connectable steps sit together, so an account
    that arrives with the lot already set up must not be walked through them
    one rerun at a time."""
    prefs = {guide.PREF_STEP: "assistant"}
    at = app(prefs, done={"assistant": True, "notify": True}).run()
    assert prefs[guide.PREF_STEP] == "investor"
    assert _cards(at) == ["investor"]


def test_sync_ends_the_guide_when_the_last_step_is_already_done(app,
                                                                monkeypatch):
    """Reachable only when the registry's final step has a predicate, which
    today's does not — the walk must still stop rather than run off the end."""
    at = app({guide.PREF_STEP: "investor"}, done={"investor": True})
    idx = [s.id for s in onboarding.STEPS].index("investor")
    monkeypatch.setattr(onboarding, "STEPS", onboarding.STEPS[: idx + 1])
    at.run()
    assert _flag(at, "claimed") is True  # it claimed the run, then ended
    assert any(m["guide"].get("state") == "end"
               for m in at.session_state["hist"] if m.get("guide"))


# ------------------------------------------------------------------ walking
def test_next_moves_one_step_on(app):
    prefs: dict = {}
    at = app(prefs).run()
    at.button(key="panel_guide_next_0").click().run()
    assert prefs[guide.PREF_STEP] == guide.steps()[1].id
    assert _cards(at) == [_first(), guide.steps()[1].id]


def test_only_the_step_you_are_on_can_move_the_guide(app):
    """A card further up the thread is history. Clicking Next on one would
    walk the guide backwards, and the reader would never know why."""
    at = app({}).run()
    at.button(key="panel_guide_next_0").click().run()
    assert _button(at, "panel_guide_next_0") is None  # the old card went quiet
    assert _button(at, "panel_guide_next_1") is not None


def test_an_older_card_keeps_its_way_there(app):
    """The thread is the walkthrough now, so it has to stay re-followable —
    the modal it replaced at least had a Back button. Navigating changes
    nothing about where the guide is, so this one stays live."""
    prefs = {guide.PREF_STEP: "import"}
    at = app(prefs).run()
    at.button(key="panel_guide_next_0").click().run()
    assert _button(at, "panel_guide_goto_0") is not None
    at.button(key="panel_guide_goto_0").click().run()
    assert at.session_state[onboarding._GOTO] == "import"
    assert prefs[guide.PREF_STEP] != "import"  # and it did not walk back


def test_take_me_there_queues_the_step_for_app_pys_navigator(app):
    """The guide never navigates itself: onboarding.consume_goto does, early
    in app.py, where switching page and seeding session state already live."""
    prefs = {guide.PREF_STEP: "notify"}
    at = app(prefs).run()
    at.button(key="panel_guide_goto_0").click().run()
    assert at.session_state[onboarding._GOTO] == "notify"


def test_next_walks_the_app_to_the_step_it_just_opened(app):
    """A card describing Pulso while the reader is still on Home describes
    something that is not on screen. Advancing queues the same jump the
    button does, so the page follows the conversation."""
    prefs = {guide.PREF_STEP: "watchlist"}
    at = app(prefs).run()
    at.button(key="panel_guide_next_0").click().run()
    assert prefs[guide.PREF_STEP] == "pulse"
    assert at.session_state[onboarding._GOTO] == "pulse"


def test_a_phone_is_not_dragged_along_by_next(app, monkeypatch):
    """On a phone the panel is the viewport: a jump parks the tour to uncover
    the page, so one per Next would spend the walkthrough reopening it. The
    card's own button still offers the trip."""
    monkeypatch.setattr(guide, "is_mobile", lambda: True)
    prefs = {guide.PREF_STEP: "watchlist"}
    at = app(prefs).run()
    at.button(key="panel_guide_next_0").click().run()
    assert prefs[guide.PREF_STEP] == "pulse"
    assert onboarding._GOTO not in at.session_state


def test_skipping_ends_it_without_walking_it(app):
    prefs: dict = {}
    at = app(prefs).run()
    at.button(key="panel_guide_skip_0").click().run()
    assert prefs[guide.PREF_DONE] is True
    assert prefs[guide.PREF_STEP] == ""


def test_finishing_stamps_the_modal_tour_too(app):
    """Both surfaces read one account. Someone who has just been walked
    through everything must not then be shown the tour, or "what's new"."""
    prefs = {guide.PREF_STEP: guide.steps()[-1].id}
    at = app(prefs).run()
    at.button(key="panel_guide_next_0").click().run()
    assert prefs[guide.PREF_DONE] is True
    assert prefs[onboarding.PREF_DONE] is True
    assert prefs[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION


def test_a_guest_progress_is_never_written_to_the_shared_dir(app):
    """The guest data dir belongs to every anonymous visitor at once."""
    prefs: dict = {}
    at = app(prefs, logged_in=False)
    at.query_params["guide"] = "1"
    at.run()
    assert prefs == {}


# ------------------------------------------------------------------- thread
def test_owns_is_true_only_for_the_guides_own_thread(app):
    at = app({guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"}).run()
    assert at is not None
    prefs = {guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"}
    assert guide.owns({"id": "c_guide"}, prefs) is True
    assert guide.owns({"id": "c_other"}, prefs) is False


def _turn_script() -> None:
    """The panel's own renderer over one stored guide turn.

    The seam chat_core owns: a guide turn must draw its card and *none* of the
    answer chrome — the model never wrote it, so Retry would replace the step
    with prose and the sources row would cite nothing.
    """
    from stocks.web import chat_core
    from stocks.web import guide as _g

    step = _g.steps()[1]
    chat_core._render_turn("panel", _g.turn_for(step), 0)


def test_a_guide_turn_renders_its_card_and_no_answer_chrome(app):
    app({guide.PREF_STEP: guide.steps()[1].id})  # stubs auth for the renderer
    at = AppTest.from_function(_turn_script, default_timeout=15).run()
    assert not at.exception
    assert _button(at, "panel_guide_next_0") is not None
    assert _button(at, "panel_guide_goto_0") is not None
    assert _button(at, "panel_tfoot_0") is None  # chat_core's own turn foot


def test_owns_is_false_once_the_guide_is_done():
    prefs = {guide.PREF_DONE: True, guide.PREF_THREAD: "c_guide"}
    assert guide.owns({"id": "c_guide"}, prefs) is False


# --------------------------------------------------------------- the fence
# Everything below is the model half (Fase 2). None of it may ever be load
# bearing: with no provider at all the walkthrough above still runs, so these
# test that the layer stays silent rather than that it speaks.


def test_the_fence_lists_the_registry_and_nothing_else(app):
    app({guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"})

    def _script() -> None:
        import streamlit as st

        from stocks.web import guide as _g

        st.session_state["fence"] = _g.prompt_fence()

    at = AppTest.from_function(_script, default_timeout=15).run()
    fence = at.session_state["fence"]
    assert "[[goto:" in fence
    for step in guide.steps():
        assert f"- {step.id}:" in fence


def test_the_fence_is_empty_outside_the_guides_own_thread(app, monkeypatch):
    app({guide.PREF_STEP: "import", guide.PREF_THREAD: "c_guide"})
    monkeypatch.setattr(auth, "active_conversation",
                        lambda path=None: {"id": "c_somewhere_else"})

    def _script() -> None:
        import streamlit as st

        from stocks.web import guide as _g

        st.session_state["fence"] = _g.prompt_fence()

    at = AppTest.from_function(_script, default_timeout=15).run()
    assert at.session_state["fence"] == ""


def test_the_fence_is_empty_once_the_guide_is_done(app):
    app({guide.PREF_DONE: True})

    def _script() -> None:
        import streamlit as st

        from stocks.web import guide as _g

        st.session_state["fence"] = _g.prompt_fence()

    at = AppTest.from_function(_script, default_timeout=15).run()
    assert at.session_state["fence"] == ""


# -------------------------------------------------------------- the marker
def _streamed(chunks: list[str]) -> tuple[str, list[str]]:
    found: list[str] = []
    return "".join(guide.hide_markers(chunks, found)), found


def test_a_marker_never_reaches_the_screen():
    """write_stream paints tokens as they arrive and never repaints, so a
    marker shown for one frame stays until the reader's next click."""
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
    assert guide.claim_goto(turn, ["import"]) == "import"
    assert turn["guide_goto"] == "import"
    assert "[[" not in turn["content"]


def test_claim_drops_a_step_the_model_invented():
    """The whole point of the fence: an id that is not in the registry leaves
    the answer standing and produces no button."""
    turn = {"role": "assistant", "content": "Open Settings. [[goto:settings]]"}
    assert guide.claim_goto(turn, ["settings"]) is None
    assert "guide_goto" not in turn
    assert turn["content"] == "Open Settings."


def test_claim_takes_the_last_marker_of_a_chain():
    """A stream that fell down to a second provider can carry one from each."""
    turn = {"role": "assistant", "content": "x"}
    assert guide.claim_goto(turn, ["import", "notify"]) == "notify"


def test_a_jump_button_sends_the_reader_where_the_answer_offered(app):
    prefs = {guide.PREF_STEP: "import"}
    app(prefs)

    def _script() -> None:
        from stocks.web import guide as _g

        _g.render_jump("panel", {"guide_goto": "notify"}, 7)

    at = AppTest.from_function(_script, default_timeout=15).run()
    at.button(key="panel_guide_jump_7").click().run()
    assert at.session_state[onboarding._GOTO] == "notify"


# ------------------------------------------------------------- the opening
def test_a_line_that_ignored_the_brief_is_refused():
    assert guide._accept("") is None
    assert guide._accept("See [the docs](http://x)") is None
    assert guide._accept("ok [[goto:import]]") is None
    assert guide._accept("x" * 1000) is None
    trimmed = guide._accept("word " * 100)
    assert trimmed is not None and len(trimmed) <= guide.NARRATE_MAX_CHARS


def _narrate_script() -> None:
    """The panel's narration hook over a thread already one step in."""
    import streamlit as st

    from stocks.web import guide as _g

    steps = _g.steps()
    if "hist" not in st.session_state:
        st.session_state["hist"] = [_g.turn_for(steps[0]), _g.turn_for(steps[1])]
    box = st.container()
    st.session_state["narrated"] = _g.narrate("panel", st.session_state["hist"],
                                              box)


def test_the_opening_line_lands_in_the_thread(app, monkeypatch):
    prefs = {guide.PREF_STEP: guide.steps()[1].id}
    app(prefs)
    monkeypatch.setattr(
        guide.engine, "complete_attempts",
        lambda *a, **k: "Empieza por el extracto: sin él no hay cartera.",
    )
    at = AppTest.from_function(_narrate_script, default_timeout=15).run()
    assert at.session_state["narrated"] is True
    assert at.session_state["hist"][-1]["guide"]["state"] == "note"
    assert prefs[guide.PREF_NARRATED] is True


def test_a_silent_provider_costs_the_walkthrough_nothing(app, monkeypatch):
    """No provider, a dead key, a spent allowance — all arrive here as None,
    and the walkthrough has to read exactly as it does without the layer."""
    prefs = {guide.PREF_STEP: guide.steps()[1].id}
    app(prefs)
    monkeypatch.setattr(guide.engine, "complete_attempts",
                        lambda *a, **k: None)
    at = AppTest.from_function(_narrate_script, default_timeout=15).run()
    assert not at.exception
    assert at.session_state["narrated"] is False
    assert len(at.session_state["hist"]) == 2  # the two cards, nothing else
    assert prefs[guide.PREF_NARRATED] is True  # attempted once, never again


def test_the_opening_line_waits_for_the_reader_to_press_something(app,
                                                                 monkeypatch):
    """On the first step the panel is being painted before page.run(), where
    a blocked run delays the whole page behind it."""
    called: list[int] = []
    prefs = {guide.PREF_STEP: guide.steps()[0].id}
    app(prefs)
    monkeypatch.setattr(guide.engine, "complete_attempts",
                        lambda *a, **k: called.append(1) or "x")
    at = AppTest.from_function(_narrate_script, default_timeout=15).run()
    assert at.session_state["narrated"] is False
    assert called == []


def test_it_is_attempted_once_per_account(app, monkeypatch):
    prefs = {guide.PREF_STEP: guide.steps()[1].id,
             guide.PREF_NARRATED: True}
    app(prefs)
    monkeypatch.setattr(guide.engine, "complete_attempts",
                        lambda *a, **k: "should never be asked for")
    at = AppTest.from_function(_narrate_script, default_timeout=15).run()
    assert at.session_state["narrated"] is False


def test_a_free_unit_spent_on_silence_is_handed_back(app, monkeypatch):
    """A new account gets five free messages a day (the trial allowance).
    Spending one on a welcome that never arrived is the guide taking from the
    reader what it was supposed to give them."""
    prefs = {guide.PREF_STEP: guide.steps()[1].id}
    app(prefs)
    refunded: list[int] = []

    def _attempts(p, system, msgs, timeout, *, spend_free, accept=None):
        spend_free(p)  # the free candidate charges before it is called
        return None  # …and then answers nothing

    monkeypatch.setattr(guide.engine, "complete_attempts", _attempts)
    monkeypatch.setattr(guide.engine, "spend_free_quota", lambda p: True)
    monkeypatch.setattr(guide.engine, "refund_free_quota",
                        lambda p, units=1: refunded.append(units))
    AppTest.from_function(_narrate_script, default_timeout=15).run()
    assert refunded == [1]
