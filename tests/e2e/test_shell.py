"""The shell in a browser: every page draws, links survive a reload, phones fit.

Run with `uv run pytest -m e2e` — see conftest.py for the server these hit.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from stocks import navigation

pytestmark = pytest.mark.e2e

# `/` is the landing for a browser that has never been to the app, which is
# every fresh test context — the shell's own name for its home is `/home`.
PAGES = sorted(navigation.SHELL_PATHS)


@pytest.mark.parametrize("path", PAGES)
def test_every_page_draws_for_a_guest(page: Page, path: str):
    """The guest is the one visitor every deployment has, and the one whose
    requests the API refuses most often: a page that throws on a 401 or a 503
    instead of drawing its empty state throws for them first."""
    page.goto(f"/{path}")
    expect(page.get_by_role("navigation", name="Sections")).to_be_visible()
    expect(page).to_have_title(re.compile(r" · TopStocks$"))
    expect(page.locator("main.ag-main")).not_to_be_empty()


@pytest.mark.parametrize("path", PAGES)
def test_every_page_draws_for_a_signed_in_account(page: Page, sign_in, path: str):
    sign_in()
    page.goto(f"/{path}")
    expect(page.get_by_role("navigation", name="Sections")).to_be_visible()
    expect(page.locator("main.ag-main")).not_to_be_empty()


@pytest.mark.parametrize("path", ["home", "portfolio", "bank"])
def test_a_guest_page_asks_only_for_what_a_guest_may_read(page: Page, path: str):
    """A 401 on a guest's page is a request the page should not have made: the
    card it feeds either belongs to a guest (and the route belongs in
    `api.guest.OPEN`) or does not (and the page walls it off before asking)."""
    refused: list[str] = []
    page.on("response", lambda r: r.status == 401 and refused.append(r.url))
    page.goto(f"/{path}")
    page.wait_for_load_state("networkidle")
    assert not refused, f"asked for what a guest may not read: {refused}"


def test_the_guest_is_told_it_is_a_demo_and_offered_a_way_in(page: Page):
    page.goto("/home")
    expect(page.get_by_text("Browsing as a guest")).to_be_visible()
    expect(page.get_by_role("link", name="Sign in with Google").first).to_be_visible()


def test_a_deep_link_survives_a_reload(page: Page, sign_in):
    """The server hands every shell path the same document; the page it names
    is drawn in the browser. A reload is where that contract breaks."""
    sign_in()
    page.goto("/portfolio?tab=fees")
    page.reload()
    expect(page).to_have_url(re.compile(r"/portfolio\?tab=fees$"))
    expect(page.locator("a.ag-nav-on")).to_have_attribute("href", "/portfolio")


def test_the_menu_moves_between_pages_without_a_document_load(page: Page, sign_in):
    sign_in()
    page.goto("/home")
    page.evaluate("window.__sameDocument = true")
    page.get_by_role("navigation", name="Sections").get_by_role(
        "link", name="Sectors"
    ).click()
    expect(page).to_have_url(re.compile(r"/sector$"))
    assert page.evaluate("window.__sameDocument") is True, "the menu reloaded the page"


def test_search_opens_the_ticker_page(page: Page):
    """Resolved offline: the search matches against the reference lists the
    app ships, not against Yahoo."""
    page.goto("/home")
    box = page.get_by_role("searchbox")
    box.fill("AAPL")
    expect(page.get_by_role("listbox")).to_contain_text("Apple")
    box.press("Enter")
    expect(page).to_have_url(re.compile(r"/ticker\?ticker=AAPL$"))
    expect(page.get_by_role("heading", level=1)).to_have_text("AAPL")


@pytest.mark.parametrize("path", ["home", "portfolio", "ticker?ticker=AAPL", "profile"])
def test_a_phone_gets_a_bottom_tab_bar_and_no_sideways_scroll(
    browser, base_url: str, path: str
):
    context = browser.new_context(
        base_url=base_url,
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        locale="en-US",
    )
    try:
        page = context.new_page()
        page.goto(f"/{path}")
        nav = page.get_by_role("navigation", name="Sections")
        expect(nav).to_be_visible()
        box = nav.bounding_box()
        assert box is not None
        assert box["y"] + box["height"] == pytest.approx(844, abs=1), (
            "the menu is not pinned to the bottom of the screen"
        )
        # The DS bar: four destinations and "More" (`navigation.BOTTOM_NAV`).
        tabs = nav.locator(".ag-nav-item:visible")
        expect(tabs).to_have_count(len(navigation.BOTTOM_NAV) + 1)
        page.wait_for_load_state("networkidle")
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 0, f"the page scrolls {overflow}px sideways on a phone"
    finally:
        context.close()


def test_a_phone_reaches_the_other_pages_through_more(browser, base_url: str):
    context = browser.new_context(
        base_url=base_url,
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        locale="en-US",
    )
    try:
        page = context.new_page()
        page.goto("/home")
        nav = page.get_by_role("navigation", name="Sections")
        pulse = nav.get_by_role("link", name="Pulse")
        expect(pulse).to_be_hidden()
        nav.get_by_role("button", name="More").click()
        expect(pulse).to_be_visible()
        expect(nav.get_by_role("link", name="Sign in with Google")).to_be_visible()
        pulse.click()
        expect(page).to_have_url(re.compile(r"/sentiment$"))
        expect(pulse).to_be_hidden()
    finally:
        context.close()
