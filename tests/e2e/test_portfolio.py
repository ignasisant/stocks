"""Portfolio in a browser: the demo book goes in and out, and every tab draws.

Only the open tab is mounted (Portfolio.tsx), so a tab's fetches run only when
it is clicked — which is why the guest check in test_shell.py, which loads the
page and stops, cannot see a tab that asks for a route `guest.OPEN` leaves out.
These click through every one of them.

The tabs are read off the page rather than listed here: a tab added tomorrow is
walked by these tests without anybody remembering to add it.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _settle(page: Page) -> None:
    """Wait for the open tab's cards to answer, whatever they answer. Every
    card draws `Skeleton` while its query is in flight (Layout.tsx `Loaded`),
    and a client-side tab switch never reaches a load state to wait on."""
    expect(page.locator("main .ag-skeleton")).to_have_count(0, timeout=15_000)


def _walk_tabs(page: Page) -> list[str]:
    """Click every tab in order and hand back the slugs the URL took."""
    tabs = page.get_by_role("tab")
    expect(tabs.first).to_be_visible()
    slugs = []
    for n in range(tabs.count()):
        tab = tabs.nth(n)
        tab.click()
        expect(tab).to_have_attribute("aria-selected", "true")
        expect(page).to_have_url(re.compile(r"/portfolio\?tab=\w+$"))
        slugs.append(page.url.rsplit("=", 1)[1])
        _settle(page)
    return slugs


def test_every_tab_draws_for_a_guest_and_asks_only_what_a_guest_may_read(page: Page):
    """The guest's portfolio is the shared demo book, whole: a 401 on any tab
    is a card that paints an error for every anonymous visitor."""
    refused: list[str] = []
    page.on("response", lambda r: r.status == 401 and refused.append(r.url))
    page.goto("/portfolio")
    expect(page.get_by_text("These are demo transactions on a shared")).to_be_visible()

    slugs = _walk_tabs(page)

    assert len(set(slugs)) == len(slugs) > 1, f"tabs share a slug: {slugs}"
    assert not refused, f"a tab asked for what a guest may not read: {refused}"


def test_an_empty_book_takes_the_demo_and_gives_it_back(page: Page, sign_in):
    """The loop a new account runs before it has a statement to hand: seed the
    example book, look round every tab over it, remove it. Seeding and removing
    both go through the server (`/portfolio/demo`), and the page redraws from
    its answer, so what is on screen after each press is what the ledger holds."""
    sign_in()
    page.goto("/portfolio")
    empty = page.get_by_text("No transactions yet")
    expect(empty).to_be_visible()
    expect(page.get_by_role("tab")).to_have_count(0)

    page.get_by_role("button", name="Use demo transactions").click()
    expect(page.get_by_text("These are demo transactions, not yours.")).to_be_visible()
    expect(empty).to_be_hidden()

    _walk_tabs(page)

    page.get_by_role("button", name="Remove demo data").click()
    expect(empty).to_be_visible()
    expect(page.get_by_role("tab")).to_have_count(0)
    expect(page.get_by_role("button", name="Use demo transactions")).to_be_visible()


def test_a_guest_is_not_offered_the_demo_controls(page: Page):
    """The shared book is somebody else's to seed and clear: a guest sees the
    banner that says so, never the buttons that would try."""
    page.goto("/portfolio")
    expect(page.get_by_text("These are demo transactions on a shared")).to_be_visible()
    expect(page.get_by_role("button", name="Remove demo data")).to_have_count(0)
    expect(page.get_by_role("button", name="Use demo transactions")).to_have_count(0)
