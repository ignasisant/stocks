"""The guided tour (stocks.web.onboarding) — registry and per-account state.

The module is data: the shell draws the tour, the "what's new" modal and the
walkthrough from what `api/routes/onboarding.py` and `api/routes/guide.py`
serve, and those routes are tested in test_api_onboarding.py and
test_api_guide.py. What is worth a test here:

* the **registry** has to stay consistent with the rest of the repo — every
  step lands on a page the shell answers, every release must point at real
  steps, and every step and release item must have copy in every shipped
  language. Those are exactly the mistakes a hand-edited registry (or the
  update-tutorial skill) makes, and they surface as a raw `tour.foo_body` key
  on screen.
* **`setup_state`** is shared with the Home setup card, so a change in one
  place must not silently move the other.
* **`unseen_news`** decides what a returning account is shown, which involves
  the release list and the persisted stamp — easy to get wrong and invisible
  until someone signs in for the first time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from stocks import navigation
from stocks.web import auth, i18n, onboarding

LOCALES = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "locales"


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((LOCALES / lang / "tour.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ registry
def test_step_ids_are_unique():
    ids = [s.id for s in onboarding.STEPS]
    assert len(ids) == len(set(ids))


def test_every_step_lands_on_a_page_the_shell_serves():
    """A typo'd path only fails when the user clicks "take me there", and then
    as a 404 on the server rather than as anything a test would see.

    Checked over `visible_steps()`, not `STEPS`: a step whose feature is not
    built into this deploy is filtered out before anyone can click it.
    """
    missing = [
        s.id
        for s in onboarding.visible_steps()
        if s.page and s.page not in navigation.SHELL_PATHS
    ]
    assert not missing, f"steps pointing at no shell page: {missing}"


def test_home_is_the_root_path_and_a_pageless_step_says_so():
    """The shell serves Home at "", so the tour must say "" or it would
    navigate to Home from Home; None is a step that goes nowhere at all."""
    assert onboarding.by_id("daily").page == ""
    assert onboarding.by_id("positions").page == "portfolio"
    assert onboarding.by_id("welcome").page is None
    assert onboarding.by_id("assistant").page is None


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
def _paths(tmp_path: Path) -> SimpleNamespace:
    """The three files the predicates read, none of which exist yet."""
    return SimpleNamespace(
        db=tmp_path / "ledger.db",
        watchlist=tmp_path / "watchlist.yaml",
        chat=tmp_path / "chat.json",
    )


def test_setup_state_reads_the_four_capabilities(monkeypatch, tmp_path):
    monkeypatch.setattr(onboarding, "_has_ledger", lambda prefs, paths: True)
    state = onboarding.setup_state(
        {"anthropic_key_enc": "…", "telegram_chat_id": 42},
        _paths(tmp_path),
        signed_in=True,
    )
    assert state == {"login": True, "import": True, "ai": True, "telegram": True}


def test_setup_state_for_a_guest_has_nothing_switched_on(monkeypatch, tmp_path):
    monkeypatch.setattr(onboarding, "_has_ledger", lambda prefs, paths: True)
    state = onboarding.setup_state(
        {"telegram_chat_id": 42}, _paths(tmp_path), signed_in=False
    )
    # The ledger check is skipped for a guest on purpose — the guest data dir
    # is shared, so its starter ledger is nobody's import.
    assert state["login"] is False and state["import"] is False


def test_setup_state_ignores_the_keyless_free_chain(monkeypatch, tmp_path):
    monkeypatch.setattr(onboarding, "_has_ledger", lambda prefs, paths: False)
    state = onboarding.setup_state({}, _paths(tmp_path), signed_in=True)
    assert state["ai"] is False


def test_unreadable_ledger_reads_as_nothing_imported(tmp_path):
    paths = _paths(tmp_path)
    paths.db.write_text("this is not a sqlite database")
    assert onboarding._has_ledger({}, paths) is False


def test_a_missing_ledger_reads_as_nothing_imported(tmp_path):
    assert onboarding._has_ledger({}, _paths(tmp_path)) is False


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


def test_unseen_news_drops_a_feature_off_on_this_deploy(monkeypatch):
    """`carried` gates a card whose step is shown everywhere but whose feature
    is not — the step's page is there, the thing to do on it is not."""
    releases = (
        onboarding.Release(
            version="1.0", date="2026-01",
            items=(
                onboarding.News(slug="on", icon="x", step="prefs",
                                carried=lambda: True),
                onboarding.News(slug="off", icon="x", step="prefs",
                                carried=lambda: False),
            ),
        ),
    )
    monkeypatch.setattr(onboarding, "RELEASES", releases)
    assert [c.item.slug for c in onboarding.unseen_news({})] == ["on"]


@pytest.mark.parametrize(
    ("origin", "shown"), [(None, False), ("https://x.example", True)]
)
def test_the_claude_card_needs_the_public_url(monkeypatch, origin, shown):
    """The connector names itself to Claude by the site's public URL; without
    one it is off and Profile has no Claude card to send the reader to."""
    from stocks.web import server

    monkeypatch.setattr(server, "public_origin", lambda: origin)
    slugs = {(c.version, c.item.slug) for c in onboarding.unseen_news({})}
    assert (("2026.10", "claude") in slugs) is shown


# ------------------------------------------------------ explore_state (Home)

# The setup card's second strip: the three things an account that has
# connected nothing can still do today. Each detector reads state the app
# already keeps, so trying one of them costs no extra write.


@pytest.fixture
def account(tmp_path):
    """A signed-in account's own dir. The predicates are handed it, so nothing
    here has to pretend to be a session."""
    paths = auth.paths_for("newbie@example.com", users_dir=tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    return paths


def test_a_freshly_seeded_account_has_tried_nothing(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    assert onboarding.explore_state({}, account) == {
        "search": False, "ask": False, "watchlist": False,
    }


def test_a_looked_up_ticker_counts_as_the_search_tried(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    state = onboarding.explore_state({"recent_searches": ["NVDA"]}, account)
    assert state["search"] is True


def test_an_answered_conversation_counts_as_the_assistant_tried(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    auth.save_chat([{"role": "user", "content": "how is my book?"}], account.chat)
    assert onboarding.explore_state({}, account)["ask"] is True


def test_an_empty_conversation_does_not_count(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    account.chat.write_text('{"conversations": [{"id": "a", "messages": []}]}')
    assert onboarding.explore_state({}, account)["ask"] is False


def test_editing_the_seeded_watchlist_is_what_makes_it_the_users_own(account):
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    assert onboarding.explore_state({}, account)["watchlist"] is False
    account.watchlist.write_text("watchlist:\n  - ticker: NVDA\n")
    assert onboarding.explore_state({}, account)["watchlist"] is True


def test_a_missing_watchlist_reads_as_untouched_rather_than_raising(account):
    assert onboarding.explore_state({}, account)["watchlist"] is False


def test_explore_state_is_kept_apart_from_the_four_setup_capabilities(account):
    """Two strips, two meanings. The tour badges every connectable step from
    setup_state, so a key that drifted across would badge a step for something
    there is nothing to connect."""
    account.watchlist.write_text(auth.STARTER_WATCHLIST)
    explore = set(onboarding.explore_state({}, account))
    setup = set(onboarding.setup_state({}, account, signed_in=True))
    assert explore == {"search", "ask", "watchlist"}
    assert setup == {"login", "import", "ai", "telegram"}
    assert not explore & setup
