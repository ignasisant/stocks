"""The modal that interrupts: it opens when it is owed, and never twice.

`web.onboarding` decides what is owed and is tested in test_onboarding.py. What
only a browser can show is the other half of the contract — that the shell
actually opens it, and that every way out stamps the account so the next load
does not open it again.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from stocks.portfolio import ledger
from stocks.web import onboarding

pytestmark = pytest.mark.e2e


def _prefs(root: Path) -> dict:
    return json.loads((root / "prefs.json").read_text())


def _stamped(root: Path, key: str, value, timeout: float = 5.0) -> None:
    """Wait for the account's prefs to carry `key = value`. The modal stamps
    them with a request it does not wait for, so the page is closed before the
    file is written."""
    deadline = time.monotonic() + timeout
    while _prefs(root).get(key) != value:
        assert time.monotonic() < deadline, f"no {key}={value!r} in {_prefs(root)}"
        time.sleep(0.1)


def _book(root: Path) -> None:
    """A row the account brought itself: "what's new" is for accounts that
    know the app, and one with no book is still being shown round."""
    ledger.add(
        ledger.Transaction("2024-03-12", "AAPL", "buy", 10, 173.2),
        root / "portfolio.db",
    )


def test_whats_new_opens_once_for_an_account_a_release_behind(page: Page, sign_in):
    # Two behind, not one: the newest release's only card (the Friday email)
    # waits for Resend keys this server does not have.
    behind = onboarding.RELEASES[-3].version
    root = sign_in({onboarding.PREF_SEEN_VERSION: behind})
    _book(root)

    page.goto("/home")
    dialog = page.get_by_role("dialog", name="What's new")
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()

    _stamped(root, onboarding.PREF_SEEN_VERSION, onboarding.CURRENT_VERSION)

    page.reload()
    page.wait_for_load_state("networkidle")
    expect(dialog).to_be_hidden()


def test_an_account_with_no_book_is_not_shown_whats_new(page: Page, sign_in):
    """Nothing is new to somebody who has not seen what is old: the same stale
    stamp, and no book, opens nothing."""
    sign_in({onboarding.PREF_SEEN_VERSION: onboarding.RELEASES[-3].version})
    page.goto("/home")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_a_caught_up_account_is_not_interrupted(page: Page, sign_in):
    sign_in()
    page.goto("/home")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("dialog")).to_have_count(0)


def _card(page: Page):
    """The section guide's card: a corner of the page, not a dialog."""
    return page.get_by_role("complementary", name=re.compile(r"^Step \d+ of \d+"))


def test_the_guide_walks_the_sections_and_parks_on_escape(page: Page, sign_in):
    """`?tour=1` is the deep link Home's and Profile's "take the tour" use. It
    opens no dialog: a card in the corner, and the app goes to the section each
    stop is about. Escape parks it in the strip above the page rather than
    ending it, and only "End tour" on the strip counts as taken."""
    root = sign_in({onboarding.PREF_DONE: False})

    page.goto("/home?tour=1")
    card = _card(page)
    expect(card).to_contain_text("Step 1 of")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/import$"))
    card.get_by_role("button", name="Next").click()
    expect(card).to_contain_text("Step 2 of")
    expect(page).to_have_url(re.compile(r"/home$"))
    page.keyboard.press("Escape")
    expect(card).to_be_hidden()

    strip = page.get_by_role("region", name="Guided tour")
    expect(strip).to_be_visible()
    assert _prefs(root).get(onboarding.PREF_DONE) is False

    strip.get_by_role("button", name="End tour").click()
    expect(strip).to_be_hidden()
    _stamped(root, onboarding.PREF_DONE, True)


def test_escape_in_the_search_box_leaves_the_guide_up(page: Page, sign_in):
    """The page under the card works, and its controls have an Escape of their
    own: closing the search panel must not put the guide away with it."""
    sign_in({onboarding.PREF_DONE: False})

    page.goto("/home?tour=1")
    card = _card(page)
    expect(card).to_contain_text("Step 1 of")
    field = page.get_by_label("Search ticker or name…").first
    field.fill("AAP")
    field.press("Escape")
    expect(card).to_be_visible()
    expect(page.get_by_role("region", name="Guided tour")).to_have_count(0)

    card.get_by_role("button", name="Next").focus()
    page.keyboard.press("Escape")
    expect(card).to_be_hidden()
    expect(page.get_by_role("region", name="Guided tour")).to_be_visible()


def test_skipping_the_guide_ends_it_and_catches_the_account_up(page: Page, sign_in):
    """Every stop can be skipped, and skipping is an answer: the guide is not
    offered again and the releases it was spared are not dealt afterwards."""
    root = sign_in(
        {
            onboarding.PREF_DONE: False,
            onboarding.PREF_OFFER: True,
            onboarding.PREF_SEEN_VERSION: onboarding.RELEASES[-3].version,
        }
    )
    _book(root)

    page.goto("/home?tour=1")
    card = _card(page)
    expect(card).to_be_visible()
    card.get_by_role("button", name="Skip the tour").click()
    expect(card).to_be_hidden()
    expect(page.get_by_role("region", name="Guided tour")).to_have_count(0)

    _stamped(root, onboarding.PREF_OFFER, False)
    assert _prefs(root)[onboarding.PREF_DONE] is True
    assert _prefs(root)[onboarding.PREF_SEEN_VERSION] == onboarding.CURRENT_VERSION

    page.goto("/home")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("dialog", name="What's new")).to_have_count(0)
