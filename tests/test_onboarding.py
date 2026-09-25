"""The guided tour (stocks.web.onboarding) — registry, gating and open/close.

Three things here are worth a test and the rest is Streamlit chrome:

* the **registry** has to stay consistent with the rest of the repo — every
  step's page module must exist, every release must point at real steps, and
  every step and release item must have copy in every shipped language. Those
  are exactly the mistakes a hand-edited registry (or the update-tutorial
  skill) makes, and they surface as a raw `tour.foo_body` key on screen.
* **`setup_state`** is shared with the Home setup card, so a change in one
  place must not silently move the other.
* **auto-open** decides what a returning account sees, which involves the
  release list, the persisted stamp and the guest rules — easy to get wrong
  and invisible until someone signs in for the first time.

The open/close cases run through AppTest because they need a real session
state; the rest are pure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from stocks.web import auth, i18n, onboarding

LOCALES = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "locales"
SRC = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web"


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((LOCALES / lang / "tour.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ registry
def test_step_ids_are_unique():
    ids = [s.id for s in onboarding.STEPS]
    assert len(ids) == len(set(ids))


def test_every_step_page_exists():
    """A typo'd module path only fails when the user clicks "take me there".

    Checked over `visible_steps()`, not `STEPS`: a step whose feature is not
    built into this deploy is filtered out before anyone can click it, and its
    page module is legitimately absent from the tree.
    """
    missing = [
        s.id
        for s in onboarding.visible_steps()
        if s.page and not (SRC / s.page).is_file()
    ]
    assert not missing, f"steps pointing at no page module: {missing}"


def test_home_page_maps_to_the_root_url_path():
    """st.navigation serves the default page at "", so the tour must compare
    against "" or it would switch to Home from Home, forever."""
    assert onboarding._url_path("app_pages/home.py") == ""
    assert onboarding._url_path("app_pages/portfolio.py") == "portfolio"


def test_releases_reference_real_steps():
    unknown = [
        (r.version, item.slug)
        for r in onboarding.RELEASES
        for item in r.items
        if item.step is not None and onboarding.by_id(item.step) is None
    ]
    assert not unknown, f"announced features naming no step: {unknown}"


def test_news_slugs_are_unique_within_a_release():
    """The slug is half the copy key, so a duplicate silently shows one
    feature's card twice and never shows the other's."""
    dupes = [
        r.version
        for r in onboarding.RELEASES
        if len({i.slug for i in r.items}) != len(r.items)
    ]
    assert not dupes, f"releases with a repeated news slug: {dupes}"


def test_current_version_is_the_last_release():
    assert onboarding.CURRENT_VERSION == onboarding.RELEASES[-1].version


@pytest.mark.parametrize("lang", sorted(i18n.LANGUAGES))
def test_every_step_has_copy(lang):
    cat = _catalog(lang)
    missing = [
        key
        for s in onboarding.STEPS
        for key in (f"tour.{s.id}_title", f"tour.{s.id}_body")
        if key not in cat
    ]
    assert not missing, f"{lang}: steps with no copy: {missing}"


@pytest.mark.parametrize("lang", sorted(i18n.LANGUAGES))
def test_every_announced_feature_has_copy(lang):
    """Every card the news modal can page to needs a title and a body: it
    shows one feature at a time, so a missing key is the whole card."""
    cat = _catalog(lang)
    missing = [
        key
        for r in onboarding.RELEASES
        for item in r.items
        for key in (
            onboarding.NewsCard(r.version, r.date, item).title_key,
            onboarding.NewsCard(r.version, r.date, item).body_key,
        )
        if key not in cat
    ]
    assert not missing, f"{lang}: announced features with no copy: {missing}"


def test_catalog_has_no_copy_for_news_that_is_gone():
    """Same trap as an orphaned step: a release item that was renamed leaves
    its old copy translated in every locale and nothing pointing at it."""
    live = {
        key
        for r in onboarding.RELEASES
        for item in r.items
        for key in (
            onboarding.NewsCard(r.version, r.date, item).title_key,
            onboarding.NewsCard(r.version, r.date, item).body_key,
        )
    }
    # `tour.news_<YYYY>_<MM>_…` is the card namespace; the modal's own chrome
    # (tour.news_title, tour.news_progress) shares the prefix and is not copy
    # for a feature.
    orphans = sorted(
        key
        for key in _catalog(i18n.DEFAULT_LANG)
        if re.fullmatch(r"tour\.news_\d{4}_\d{2}_.+_(title|body)", key)
        and key not in live
    )
    assert not orphans, f"copy for features no longer announced: {orphans}"


def test_catalog_has_no_copy_for_steps_that_are_gone():
    """Orphaned copy is how a renamed step goes unnoticed: the old block stays
    translated, the new one falls back to the raw key."""
    ids = {s.id for s in onboarding.STEPS}
    orphans = sorted(
        key
        for key in _catalog(i18n.DEFAULT_LANG)
        if key.endswith("_body")
        # The release cards own the `tour.news_*` half of the namespace, and
        # have their own orphan check above.
        and not key.startswith("tour.news_")
        and key.removeprefix("tour.").removesuffix("_body") not in ids
    )
    assert not orphans, f"copy for steps no longer in the registry: {orphans}"


# ---------------------------------------------------------------- setup_state
def test_setup_state_reads_the_four_capabilities(monkeypatch):
    monkeypatch.setattr(auth, "is_logged_in", lambda: True)
    monkeypatch.setattr(onboarding, "_has_ledger", lambda prefs, paths=None: True)
    state = onboarding.setup_state(
        {"anthropic_key_enc": "…", "telegram_chat_id": 42}
    )
    assert state == {"login": True, "import": True, "ai": True, "telegram": True}


def test_setup_state_for_a_guest_has_nothing_switched_on(monkeypatch):
    monkeypatch.setattr(auth, "is_logged_in", lambda: False)
    monkeypatch.setattr(onboarding, "_has_ledger", lambda prefs, paths=None: True)
    state = onboarding.setup_state({"telegram_chat_id": 42})
    # The ledger check is skipped for a guest on purpose — the guest data dir
    # is shared, so its starter ledger is nobody's import.
    assert state["login"] is False and state["import"] is False


def test_setup_state_ignores_the_keyless_free_chain(monkeypatch):
    monkeypatch.setattr(auth, "is_logged_in", lambda: True)
    monkeypatch.setattr(onboarding, "_has_ledger", lambda prefs, paths=None: False)
    assert onboarding.setup_state({})["ai"] is False


def test_unreadable_ledger_reads_as_nothing_imported(monkeypatch):
    def _boom():
        raise OSError("no such database")

    monkeypatch.setattr(auth, "db_path", _boom)
    assert onboarding._has_ledger({}) is False


# ----------------------------------------------------------------- releases
def test_unseen_releases_are_everything_for_a_new_account():
    assert onboarding.unseen_releases({}) == onboarding.RELEASES


def test_unseen_releases_are_nothing_once_stamped_current():
    prefs = {onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION}
    assert onboarding.unseen_releases(prefs) == ()


def test_unseen_releases_are_the_tail_after_the_stamp(monkeypatch):
    releases = (
        onboarding.Release(version="1.0", date="2026-01", items=()),
        onboarding.Release(version="1.1", date="2026-02", items=()),
        onboarding.Release(version="1.2", date="2026-03", items=()),
    )
    monkeypatch.setattr(onboarding, "RELEASES", releases)
    got = onboarding.unseen_releases({onboarding.PREF_SEEN_VERSION: "1.0"})
    assert [r.version for r in got] == ["1.1", "1.2"]


def test_an_unknown_stamp_shows_everything(monkeypatch):
    """A downgrade or a hand-edited prefs.json must not crash the app."""
    prefs = {onboarding.PREF_SEEN_VERSION: "not-a-version"}
    assert onboarding.unseen_releases(prefs) == onboarding.RELEASES


# ---------------------------------------------------------------- news cards

# What the modal actually pages through: one card per announced feature, so
# how much a returning account reads is how much shipped while it was away.


def test_news_copy_keys_are_built_from_the_version_and_slug():
    card = onboarding.NewsCard(
        "2026.10", "2026-10", onboarding.News(slug="thing", icon="rocket")
    )
    assert card.title_key == "tour.news_2026_10_thing_title"
    assert card.body_key == "tour.news_2026_10_thing_body"


def test_unseen_news_is_one_card_per_feature_newest_release_first(monkeypatch):
    releases = (
        onboarding.Release(
            version="1.0", date="2026-01",
            items=(onboarding.News(slug="old", icon="x"),),
        ),
        onboarding.Release(
            version="1.1", date="2026-02",
            items=(
                onboarding.News(slug="a", icon="x"),
                onboarding.News(slug="b", icon="x"),
            ),
        ),
    )
    monkeypatch.setattr(onboarding, "RELEASES", releases)
    cards = onboarding.unseen_news({})
    assert [(c.version, c.item.slug) for c in cards] == [
        ("1.1", "a"), ("1.1", "b"), ("1.0", "old"),
    ]


def test_unseen_news_stops_at_the_stamp(monkeypatch):
    releases = (
        onboarding.Release(
            version="1.0", date="2026-01",
            items=(onboarding.News(slug="old", icon="x"),),
        ),
        onboarding.Release(
            version="1.1", date="2026-02",
            items=(onboarding.News(slug="new", icon="x"),),
        ),
    )
    monkeypatch.setattr(onboarding, "RELEASES", releases)
    prefs = {onboarding.PREF_SEEN_VERSION: "1.0"}
    assert [c.item.slug for c in onboarding.unseen_news(prefs)] == ["new"]


def test_unseen_news_drops_a_feature_this_deploy_does_not_carry(monkeypatch):
    """A step filtered out of `visible_steps()` is a page that is not in the
    nav — announcing it would send the reader to a wall."""
    releases = (
        onboarding.Release(
            version="1.0", date="2026-01",
            items=(
                onboarding.News(slug="here", icon="x", step="welcome"),
                onboarding.News(slug="absent", icon="x", step="import"),
                onboarding.News(slug="stepless", icon="x"),
            ),
        ),
    )
    monkeypatch.setattr(onboarding, "RELEASES", releases)
    monkeypatch.setattr(
        onboarding, "visible_steps", lambda: (onboarding.by_id("welcome"),)
    )
    got = [c.item.slug for c in onboarding.unseen_news({})]
    # A card with no step of its own is not gated on one.
    assert got == ["here", "stepless"]


# ----------------------------------------------------------------- auto-open
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
    """What app.py does with the tour, and nothing else.

    Run through AppTest so the module gets a real session state. Defined at
    module level because AppTest re-executes the function's *source* as a
    script — a nested function's closure would not come with it. The stubs it
    needs are monkeypatched onto the modules themselves by `app` below.
    """
    import streamlit as st

    from stocks.web import onboarding as _onb

    # Stand-in for the StreamlitPage app.py passes in. It claims to be the
    # page the first announcement *with a step* points at, so "take me there"
    # parks instead of navigating: st.switch_page needs a real st.navigation,
    # which a harness of one script does not have, and which card ships first
    # is not this file's business. Newest-first is not enough — a release may
    # lead with a change to chrome that has no tour stop at all.
    _first = next(
        (step for card in _onb.unseen_news({})
         if (step := _onb.by_id(card.item.step or "")) is not None),
        None,
    )

    class _Page:
        url_path = _onb._url_path(_first.page) if _first and _first.page else ""
        title = "Page"

    st.session_state["claimed"] = _onb.maybe_open()
    _onb.consume_goto(_Page())
    # app.py skips the page while this is True — a modal is a viewport-wide
    # overlay, so the page behind it is invisible work that eats its taps.
    st.session_state["blocking"] = _onb.render(_Page())


@pytest.fixture
def app(monkeypatch):
    """Factory for an AppTest over the tour, backed by a prefs dict.

    Everything the tour persists lands in the dict the test passes in, so
    "did it stamp the version" is a plain assertion. The ledger is off unless
    a test says otherwise.
    """

    def make(prefs: dict, *, logged_in: bool = True) -> AppTest:
        monkeypatch.setattr(auth, "is_logged_in", lambda: logged_in)
        monkeypatch.setattr(auth, "load_prefs", lambda path=None: dict(prefs))
        monkeypatch.setattr(
            auth, "save_prefs", lambda p, path=None: prefs.update(p)
        )
        monkeypatch.setattr(onboarding, "_has_ledger", lambda p, paths=None: False)
        return AppTest.from_function(_script, default_timeout=15)

    return make


def test_a_new_account_gets_the_tour(app):
    at = app({}).run()
    assert at.session_state["claimed"] is True
    assert at.session_state[onboarding._MODE] == "tour"
    # The modal renders the first step's title, so the copy is really wired.
    assert any(
        i18n.translate("tour.welcome_title", "en") in m.value for m in at.markdown
    )


def test_a_finished_account_gets_whats_new_after_a_release(app):
    at = app({onboarding.PREF_DONE: True}).run()
    assert at.session_state[onboarding._MODE] == "news"


def test_a_finished_and_up_to_date_account_is_left_alone(app):
    prefs = {
        onboarding.PREF_DONE: True,
        onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION,
    }
    at = app(prefs).run()
    assert at.session_state["claimed"] is False
    assert not _flag(at, onboarding._OPEN)


def test_an_open_modal_tells_app_py_to_stand_the_page_down(app):
    """The page rendering behind a dialog is not just wasted — it is what ate
    the presses meant for the modal: 23s before Next moved a step."""
    at = app({}).run()

    assert at.session_state["blocking"] is True


def test_the_resume_strip_is_not_blocking(app):
    """The strip sits in the page flow and covers nothing, so the page behind
    it still has to render — it is the only thing under it."""
    prefs = {onboarding.PREF_DONE: True,
             onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION}
    at = app(prefs)
    at.session_state[onboarding._RESUME] = True
    at.run()

    assert at.session_state["blocking"] is False


def test_a_quiet_run_never_stands_the_page_down(app):
    prefs = {onboarding.PREF_DONE: True,
             onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION}
    at = app(prefs).run()

    assert at.session_state["blocking"] is False


def test_a_guest_is_never_auto_opened(app):
    at = app({}, logged_in=False).run()
    assert at.session_state["claimed"] is False


def test_a_guest_progress_is_never_written_to_the_shared_dir(app):
    """The guest data dir belongs to every anonymous visitor at once."""
    prefs: dict = {}
    at = app(prefs, logged_in=False)
    at.query_params["tour"] = "1"
    at.run()
    at.button(key="tour_skip").click().run()
    assert prefs == {}
    assert not _flag(at, onboarding._OPEN)


def test_finishing_the_tour_stamps_prefs_and_stops_the_nagging(app):
    prefs: dict = {}
    at = app(prefs).run()
    while _button(at, "tour_next"):  # walk to the last step
        at.button(key="tour_next").click().run()
    at.button(key="tour_finish").click().run()
    assert prefs[onboarding.PREF_DONE] is True
    assert prefs[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION
    assert not _flag(at, onboarding._OPEN)


def test_skipping_ends_the_tour_without_walking_it(app):
    prefs: dict = {}
    at = app(prefs).run()
    at.button(key="tour_skip").click().run()
    assert prefs[onboarding.PREF_DONE] is True
    assert not _flag(at, onboarding._RESUME)


def test_take_me_there_parks_the_tour_and_seeds_the_target(app):
    """The modal cannot survive the navigation, so the button hands the step
    to the next run and leaves the resume strip behind.

    Driven from the assistant step because its target is the chat panel rather
    than a page — st.switch_page needs a real st.navigation, which a test
    harness of one script does not have.
    """
    at = app({onboarding.PREF_DONE: True})
    at.query_params["tour"] = "assistant"
    at.run()
    # AppTest re-applies its query params on every run, where a browser would
    # have dropped the one the app deleted. Clear it so the tour isn't
    # reopened underneath the click.
    at.query_params.clear()
    at.button(key="tour_goto").click().run()
    assert _flag(at, onboarding._RESUME) is True
    assert not _flag(at, onboarding._OPEN)
    assert at.session_state["chat_panel_open"] is True  # the step's own state
    assert _button(at, "tour_strip_resume") is not None  # the way back in


def test_a_parked_tour_keeps_claiming_the_run(app):
    """While the tour sits in the resume strip it still owns the session, so
    app.py never pops the investor-profile modal over a walkthrough."""
    at = app({onboarding.PREF_DONE: True})
    at.query_params["tour"] = "assistant"
    at.run()
    at.query_params.clear()
    at.button(key="tour_goto").click().run()
    assert _flag(at, onboarding._RESUME) is True
    assert at.session_state["claimed"] is True


def test_the_tour_query_param_opens_at_a_named_step(app):
    at = app({onboarding.PREF_DONE: True})
    at.query_params["tour"] = "notify"
    at.run()
    steps = [s.id for s in onboarding.visible_steps()]
    assert at.session_state[onboarding._MODE] == "tour"
    assert steps[at.session_state[onboarding._STEP]] == "notify"


# ------------------------------------------------------------- what's new

# The modal a returning account gets: paged, once, and stamped by the ways
# out of it — but not by going off to look at one of the features.


def test_whats_new_pages_one_feature_at_a_time(app):
    at = app({onboarding.PREF_DONE: True}).run()
    cards = onboarding.unseen_news({})
    assert len(cards) > 1, "this test needs a release with more than one item"
    first, second = (i18n.translate(c.title_key, "en") for c in cards[:2])
    assert any(first in m.value for m in at.markdown)
    assert not any(second in m.value for m in at.markdown)
    at.button(key="tour_news_next").click().run()
    assert any(second in m.value for m in at.markdown)
    assert not any(first in m.value for m in at.markdown)


def test_the_card_count_is_how_much_shipped_while_the_account_was_away(app):
    """The modal is as long as the backlog, which is the whole point: nothing
    is batched into one page and nothing is dropped off the end."""
    at = app({onboarding.PREF_DONE: True}).run()
    pages = 1
    while _button(at, "tour_news_next"):
        at.button(key="tour_news_next").click().run()
        pages += 1
    assert pages == len(onboarding.unseen_news({}))
    assert _button(at, "tour_news_close") is not None  # the last card ends it


def test_reading_the_last_card_stamps_the_version_once(app):
    prefs = {onboarding.PREF_DONE: True}
    at = app(prefs).run()
    while _button(at, "tour_news_next"):
        at.button(key="tour_news_next").click().run()
    at.button(key="tour_news_close").click().run()
    assert prefs[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION
    assert not _flag(at, onboarding._OPEN)
    # And it is gone for good — the point of the whole surface.
    assert app(prefs).run().session_state["claimed"] is False


def test_skipping_the_rest_still_counts_as_read(app):
    prefs = {onboarding.PREF_DONE: True}
    at = app(prefs).run()
    at.button(key="tour_news_skip").click().run()
    assert prefs[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION


@pytest.fixture
def two_cards(monkeypatch):
    """A release of exactly two announced features, both with a tour step.

    The strip tests below are about what parking does to the rest of the list,
    not about what happened to ship — and shipped content moves under them: a
    release whose newest item is a change to chrome (no tour step, so no "take
    me there" button) used to break them, and which card is newest is nobody's
    contract. Two known cards make the arithmetic exact.
    """
    releases = (
        onboarding.Release(
            version="2999.01",
            date="2999-01",
            items=(
                onboarding.News(slug="alpha", icon="star", step="pulse"),
                onboarding.News(slug="beta", icon="star", step="market"),
            ),
        ),
    )
    monkeypatch.setattr(onboarding, "RELEASES", releases)
    monkeypatch.setattr(onboarding, "CURRENT_VERSION", "2999.01")
    return releases


def test_going_to_look_at_a_feature_keeps_the_rest_of_the_list(app, two_cards):
    """Parking must not stamp: the reader has seen one card out of several,
    and the strip is what hands them the others back."""
    prefs = {onboarding.PREF_DONE: True}
    at = app(prefs).run()
    at.button(key="tour_news_goto").click().run()
    assert _flag(at, onboarding._RESUME) is True
    assert onboarding.PREF_SEEN_VERSION not in prefs
    assert at.session_state["claimed"] is True  # still owns the run
    at.button(key="tour_news_strip_next").click().run()
    assert at.session_state[onboarding._NEWS] == 1
    assert _flag(at, onboarding._OPEN) is True


def test_closing_from_the_strip_stamps_the_version(app, two_cards):
    prefs = {onboarding.PREF_DONE: True}
    at = app(prefs).run()
    at.button(key="tour_news_goto").click().run()
    at.button(key="tour_news_strip_close").click().run()
    assert prefs[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION
    assert not _flag(at, onboarding._RESUME)


def test_the_full_tour_button_leaves_news_for_the_tour(app):
    prefs = {onboarding.PREF_DONE: True}
    at = app(prefs).run()
    at.button(key="tour_news_full").click().run()
    assert at.session_state[onboarding._MODE] == "tour"
    assert at.session_state[onboarding._STEP] == 0
    assert prefs[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION


# ------------------------------------------------------ explore_state (Home)

# The setup card's second strip: the three things an account that has
# connected nothing can still do today. Each detector reads state the app
# already keeps, so trying one of them costs no extra write.


@pytest.fixture
def account(monkeypatch, tmp_path):
    """A signed-in account's own dir, outside a script run.

    `is_logged_in`/`db_path` are stubbed because both detectors read them off
    Streamlit state (st.user, session_state["user_paths"]) that only exists
    inside one — these tests exercise the detectors, not the session.
    """
    paths = auth.paths_for("newbie@example.com", users_dir=tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "watchlist_path", lambda: paths.watchlist)
    monkeypatch.setattr(auth, "db_path", lambda: paths.db)
    monkeypatch.setattr(auth, "is_logged_in", lambda: True)
    return paths


def test_a_freshly_seeded_account_has_tried_nothing(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    assert onboarding.explore_state({}) == {
        "search": False, "ask": False, "watchlist": False,
    }


def test_a_looked_up_ticker_counts_as_the_search_tried(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    state = onboarding.explore_state({"recent_searches": ["NVDA"]})
    assert state["search"] is True


def test_an_answered_conversation_counts_as_the_assistant_tried(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    auth.save_chat([{"role": "user", "content": "how is my book?"}], account.chat)
    assert onboarding.explore_state({})["ask"] is True


def test_an_empty_conversation_does_not_count(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    account.chat.write_text('{"conversations": [{"id": "a", "messages": []}]}')
    assert onboarding.explore_state({})["ask"] is False


def test_editing_the_seeded_watchlist_is_what_makes_it_the_users_own(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    assert onboarding.explore_state({})["watchlist"] is False
    account.watchlist.write_text("watchlist:\n  - ticker: NVDA\n")
    assert onboarding.explore_state({})["watchlist"] is True


def test_a_missing_watchlist_reads_as_untouched_rather_than_raising(account):
    assert onboarding.explore_state({})["watchlist"] is False


def test_explore_state_is_kept_apart_from_the_four_setup_capabilities(account):
    """Two strips, two meanings. The tour badges every connectable step from
    setup_state, so a key that drifted across would badge a step for something
    there is nothing to connect."""
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    explore = set(onboarding.explore_state({}))
    setup = set(onboarding.setup_state({}))
    assert explore == {"search", "ask", "watchlist"}
    assert setup == {"login", "import", "ai", "telegram"}
    assert not explore & setup

