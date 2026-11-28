"""Import with no broker to pick: the file says whose it is.

Synthetic statements only (the reader's own are tried by
`test_import_real_files.py`). The server here has no model, so an unknown
layout is read by the column heuristic, which is the path that must not lie.
"""
# ruff: noqa: E501

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

SAMPLE = Path(__file__).parents[2] / "src/stocks/web/assets/sample-statement-revolut.csv"

LISTING = (
    "When,What,Did,Units,Each,Money\n"
    "2025-03-03,NVDA,buy,2,114,USD\n"
    "2025-03-05,AAPL,buy,1,235.5,USD\n"
)


def _drop(page: Page, name: str, body: bytes | Path):
    payload = body.read_bytes() if isinstance(body, Path) else body
    page.locator("#im-file").set_input_files(
        files=[{"name": name, "mimeType": "text/csv", "buffer": payload}]
    )


def test_there_is_no_broker_to_pick_before_the_file(page: Page, sign_in):
    sign_in()
    page.goto("/import")
    expect(page.locator("#im-file")).to_be_attached()
    # The chips live folded under "where do I get my statement".
    expect(page.get_by_text("Where do I get my statement?")).to_be_visible()
    expect(page.locator(".im-where .im-chip").first).not_to_be_visible()
    expect(page.get_by_role("list", name="Import steps")).to_contain_text("Statement")
    expect(page.get_by_text("Platform", exact=True)).to_have_count(0)


def test_a_revolut_file_is_named_and_can_be_overruled(page: Page, sign_in):
    sign_in()
    page.goto("/import")
    _drop(page, "revolut.csv", SAMPLE)
    expect(page.get_by_text("Read as Revolut.")).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="Not it? Change").click()
    page.get_by_label("Read as").select_option(label="Detect automatically")
    expect(page.get_by_text("Read as Revolut.")).to_be_visible(timeout=20_000)
    expect(page.get_by_role("button", name="Confirm into the portfolio")).to_be_enabled()


def test_an_unknown_layout_shows_which_column_fed_which_field(page: Page, sign_in):
    sign_in()
    page.goto("/import")
    _drop(page, "mine.csv", LISTING.encode())
    expect(page.get_by_text("New format, read by the AI.")).to_be_visible(timeout=20_000)
    cols = page.locator(".im-readas-cols")
    for field, column in (("Date", "When"), ("Price", "Each"), ("Action", "Did")):
        expect(cols).to_contain_text(field)
        expect(cols).to_contain_text(column)


def test_a_file_that_is_not_a_statement_is_refused_in_words(page: Page, sign_in):
    sign_in()
    page.goto("/import")
    _drop(page, "ship.csv", b"order,sku,qty,address\n1001,ABC,2,Calle 1\n1002,DEF,1,Calle 2\n")
    expect(page.get_by_text("No trades found in this file.")).to_be_visible(timeout=20_000)
    expect(page.get_by_role("button", name="Confirm into the portfolio")).to_have_count(0)


def test_the_same_file_twice_is_all_duplicates(page: Page, sign_in):
    sign_in()
    page.goto("/import")
    _drop(page, "revolut.csv", SAMPLE)
    commit = page.get_by_role("button", name="Confirm into the portfolio")
    expect(commit).to_be_enabled(timeout=20_000)
    commit.click()
    expect(page.get_by_text(re.compile(r"^Imported \d+;"))).to_be_visible()
    _drop(page, "revolut.csv", SAMPLE)
    expect(page.get_by_text(re.compile("already in your portfolio", re.I)).first).to_be_visible(timeout=20_000)
    expect(page.get_by_role("button", name="Confirm into the portfolio")).to_be_disabled()


def test_a_phone_sees_the_drop_zone_and_no_sideways_scroll(page: Page, sign_in):
    page.set_viewport_size({"width": 390, "height": 800})
    sign_in()
    page.goto("/import")
    expect(page.locator(".im-drop")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
