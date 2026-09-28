"""The sector screen in a browser: the picker is a link, and a guest cannot spend.

Whether a sector has a scan behind it depends on the machine (the nightly scan
is shared data, not checkout data), so nothing here reads the cohort itself —
only what holds with or without it: the picker offers every sector, a choice
rides the URL and survives a reload, and only an account is offered a rescan.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_a_picked_sector_rides_the_link_and_survives_a_reload(page: Page, sign_in):
    sign_in()
    page.goto("/sector")
    expect(page.get_by_role("heading", level=1)).to_have_text("Sector screen")
    picker = page.get_by_role("combobox", name="Sector")
    expect(picker).to_be_visible()
    options = picker.locator("option")
    assert options.count() >= 2, "the picker offers fewer than two sectors"

    wanted = options.nth(1).get_attribute("value")
    picker.select_option(wanted)
    page.wait_for_url(lambda url: parse_qs(urlparse(url).query).get("sector") == [wanted])

    page.reload()
    expect(picker).to_have_value(wanted)


def test_only_an_account_is_offered_a_rescan(page: Page, sign_in):
    """The rescan is a write that spends Yahoo standing (Rescan.tsx): a guest
    gets the explanation and no button that would answer 401."""
    page.goto("/sector")
    expect(page.get_by_role("combobox", name="Sector")).to_be_visible()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="Refresh this sector")).to_have_count(0)

    sign_in()
    page.reload()
    expect(page.get_by_role("button", name="Refresh this sector").first).to_be_visible()
