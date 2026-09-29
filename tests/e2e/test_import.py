"""Import in a browser: a statement becomes a book, and the undo takes it back.

The example statement is the one input every machine has (it ships in
`web/assets`), and its bytes go through the same staging slot a file picker
fills (Sample.tsx), so this is the real pipeline — upload, parse, tiered
preview, commit, last-import record, undo — without a fixture file of our own.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_the_example_statement_goes_in_and_comes_back_out(page: Page, sign_in):
    sign_in()
    page.goto("/import")
    expect(page.get_by_role("heading", level=1)).to_have_text("Import transactions")

    page.get_by_role("button", name="Load an example statement").click()
    commit = page.get_by_role("button", name="Confirm into the portfolio")
    expect(commit).to_be_enabled(timeout=15_000)
    commit.click()

    receipt = page.get_by_text(
        re.compile(r"^Imported \d+; your portfolio now holds \d+\.$")
    )
    expect(receipt).to_be_visible()
    imported = int(re.search(r"Imported (\d+)", receipt.inner_text()).group(1))
    assert imported > 0

    # The book the portfolio draws is the one just committed: its tabs, and no
    # demo strip, because these rows are real to the ledger.
    page.goto("/portfolio")
    expect(page.get_by_role("tab", name="Positions")).to_be_visible()
    expect(page.get_by_role("button", name="Use demo transactions")).to_have_count(0)
    expect(page.get_by_text("These are demo transactions")).to_have_count(0)

    # The undo removes exactly the batch the commit wrote, and nothing is left.
    page.goto("/import")
    undo = page.get_by_role("button", name=f"Clear last import ({imported} rows)")
    undo.click()
    # Its label counts the rows still here, so it changes once the delete lands.
    expect(undo).to_have_count(0)
    page.goto("/portfolio")
    expect(page.get_by_text("No transactions yet")).to_be_visible()


def test_a_guest_meets_the_sign_in_wall_and_no_importer(page: Page):
    """A guest has no book to import into (`guest.py`): the page says so, and
    offers no control that would ask."""
    page.goto("/import")
    expect(page.get_by_text("Sign in to import your statements.")).to_be_visible()
    expect(page.get_by_role("button", name="Load an example statement")).to_have_count(0)
    expect(page.get_by_role("button", name="Confirm into the portfolio")).to_have_count(0)
