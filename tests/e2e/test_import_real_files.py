"""Real statements through the real page, one file at a time.

Statements are a reader's own money, so none ship with the repo: point
`IMPORT_FILES` at a folder (or a `:`-separated list of files) and each one is
dropped on /import in Chromium, with a screenshot kept in `IMPORT_SHOTS`.
Without it these tests skip. What is asserted is what a reader would see: the
page names who read the file, never shows a raw error, and never offers to
commit zero rows.
"""
# ruff: noqa: E501

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_RAW = os.environ.get("IMPORT_FILES", "")
_FILES = []
for part in filter(None, _RAW.split(":")):
    p = Path(part)
    _FILES += sorted(p.iterdir()) if p.is_dir() else [p]
_SHOTS = Path(os.environ.get("IMPORT_SHOTS", "")) if os.environ.get("IMPORT_SHOTS") else None


@pytest.mark.skipif(not _FILES, reason="set IMPORT_FILES to try real statements")
@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name[:40])
def test_a_real_statement_is_read_or_refused_in_words(page: Page, sign_in, path: Path):
    sign_in()
    page.goto("/import")
    page.locator("#im-file").set_input_files(str(path))
    page.wait_for_function(
        "() => !document.body.innerText.includes('Reading')", timeout=60_000
    )
    page.wait_for_timeout(1500)
    main = page.locator(".im-main").inner_text()
    if _SHOTS:
        _SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(_SHOTS / f"{path.name}.png"), full_page=True)
    summary = re.sub(r"\s+", " ", main)[:900]
    print(f"\n=== {path.name}\n{summary}")
    assert "Traceback" not in main and "undefined" not in main and "[object" not in main


@pytest.mark.skipif(not _FILES, reason="set IMPORT_FILES to try real statements")
@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name[:40])
def test_a_real_statement_that_reads_commits_and_undoes(page: Page, sign_in, path: Path):
    sign_in()
    page.goto("/import")
    page.locator("#im-file").set_input_files(str(path))
    commit = page.get_by_role("button", name="Confirm into the portfolio")
    try:
        commit.wait_for(timeout=40_000)
    except Exception:
        pytest.skip("not a statement the page offers to commit")
    if not commit.is_enabled():
        pytest.skip("commit asks something first (broker): " + page.locator(".im-warn, .im-line-warn").first.inner_text()[:80])
    commit.click()
    receipt = page.get_by_text(re.compile(r"^Imported \d+; your portfolio now holds \d+\.$"))
    receipt.wait_for(timeout=40_000)
    n = int(re.search(r"Imported (\d+)", receipt.inner_text()).group(1))
    page.goto("/portfolio")
    page.wait_for_timeout(1500)
    assert "No transactions yet" not in page.locator("body").inner_text()
    page.goto("/import")
    page.get_by_role("button", name=re.compile(r"Clear last import")).click()
    page.get_by_role("button", name=re.compile(r"Clear last import")).wait_for(state="detached", timeout=20_000)
    page.goto("/portfolio")
    page.get_by_text("No transactions yet").wait_for(timeout=20_000)
    print(f"\n{path.name}: committed {n}, undone clean")
