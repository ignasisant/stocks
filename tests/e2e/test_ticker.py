"""A ticker page in a browser: it draws with Yahoo down, and the star is a write.

The star is the one control on the page that edits the account's own files
(`watchlist.yaml`), so its test reads the file back rather than trusting the
button: a star that lights up and saves nothing looks exactly like one that
works until the next load.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
import yaml
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _favorite(root: Path, ticker: str) -> bool:
    entries = yaml.safe_load((root / "watchlist.yaml").read_text())["watchlist"]
    return any(e["ticker"] == ticker and e.get("favorite") for e in entries)


def _written(root: Path, ticker: str, want: bool, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while _favorite(root, ticker) is not want:
        assert time.monotonic() < deadline, f"{ticker} favorite never became {want}"
        time.sleep(0.1)


def test_the_star_saves_a_favorite_and_the_reload_remembers_it(page: Page, sign_in):
    # MSFT is on the starter watchlist and not a favourite there.
    root = sign_in()
    assert not _favorite(root, "MSFT")
    page.goto("/ticker?ticker=MSFT")
    expect(page.get_by_role("heading", level=1)).to_have_text("MSFT")

    page.get_by_role("button", name="Add to favorites").click()
    unstar = page.get_by_role("button", name="Remove from favorites")
    expect(unstar).to_have_attribute("aria-pressed", "true")
    _written(root, "MSFT", True)

    page.reload()
    expect(unstar).to_have_attribute("aria-pressed", "true")
    unstar.click()
    expect(page.get_by_role("button", name="Add to favorites")).to_have_attribute(
        "aria-pressed", "false"
    )
    _written(root, "MSFT", False)


def test_a_guest_is_offered_a_sign_in_instead_of_the_star(page: Page):
    page.goto("/ticker?ticker=AAPL")
    expect(page.get_by_role("heading", level=1)).to_have_text("AAPL")
    expect(page.get_by_role("button", name="Add to favorites")).to_have_count(0)
    expect(
        page.locator(".tk-header").get_by_role("link", name="Sign in with Google")
    ).to_be_visible()


def test_no_ticker_in_the_link_opens_the_first_favorite(page: Page, sign_in):
    """The bare `/ticker` a menu link lands on picks a company rather than an
    empty page: the first favourite, as the Streamlit page did."""
    sign_in()
    page.goto("/ticker")
    expect(page).to_have_url(re.compile(r"/ticker\?ticker=AAPL$"))
    expect(page.get_by_role("heading", level=1)).to_have_text("AAPL")
