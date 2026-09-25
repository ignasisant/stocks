"""The modal that interrupts: it opens when it is owed, and never twice.

`web.onboarding` decides what is owed and is tested in test_onboarding.py. What
only a browser can show is the other half of the contract — that the shell
actually opens it, and that every way out stamps the account so the next load
does not open it again.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

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


def test_whats_new_opens_once_for_an_account_a_release_behind(page: Page, sign_in):
    behind = onboarding.RELEASES[-2].version
    root = sign_in({onboarding.PREF_SEEN_VERSION: behind})

    page.goto("/home")
    dialog = page.get_by_role("dialog", name="What's new")
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()

    _stamped(root, onboarding.PREF_SEEN_VERSION, onboarding.CURRENT_VERSION)

    page.reload()
    page.wait_for_load_state("networkidle")
    expect(dialog).to_be_hidden()


def test_a_caught_up_account_is_not_interrupted(page: Page, sign_in):
    sign_in()
    page.goto("/home")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_the_tour_opens_from_its_link_and_parks_on_escape(page: Page, sign_in):
    """`?tour=1` is the deep link Profile's "take the tour" and shared links
    use. Escape parks it in the strip above the page rather than ending it —
    same rule as the first-load tour (Streamlit's `_minimize`: X, Escape and
    click-outside all park, never stamp) — and only "End tour" on the strip
    counts as taken."""
    root = sign_in({onboarding.PREF_DONE: False})

    page.goto("/home?tour=1")
    dialog = page.get_by_role("dialog", name="Guided tour")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Next").click()
    expect(dialog).to_contain_text("Step 2 of")
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page).not_to_have_url("/home?tour=1")

    strip = page.get_by_role("region", name="Guided tour")
    expect(strip).to_be_visible()
    assert _prefs(root).get(onboarding.PREF_DONE) is False

    strip.get_by_role("button", name="End tour").click()
    expect(strip).to_be_hidden()
    _stamped(root, onboarding.PREF_DONE, True)
