"""The `navigate` tool's page table, held to the React shell it links into.

`chat/navigate.py` keeps its own copy of the pages and their `?tab=` values —
the prompt is written from it and every marker is checked against it — so a
tab renamed in a page and not here would have the assistant offering a button
that lands on the page's default tab, and one added there would never be
offered. These read the TypeScript the way `test_frontend_nav_parity` does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stocks.chat import navigate, tools

APP = Path(__file__).resolve().parents[1] / "frontend" / "app" / "src"


def _slugs() -> dict[str, bool]:
    """slug -> hidden, off `PAGES` in shell/pages.ts."""
    text = (APP / "shell" / "pages.ts").read_text()
    body = text[text.index("export const PAGES"):text.index("export const BOTTOM")]
    out = {}
    for entry in re.split(r"\n  \{", body)[1:]:
        slug = re.search(r'slug: "([a-z_]+)"', entry)
        assert slug, entry
        out[slug.group(1)] = "hidden: true" in entry
    return out


def _tabs(path: str, pattern: str) -> tuple[str, ...]:
    """The page's tab ids, in its own order, off its `TABS`/`SPECS` table."""
    return tuple(re.findall(re.compile(pattern, re.M), (APP / path).read_text()))


def test_every_page_the_reader_can_see_is_linkable_and_nothing_else():
    shell = _slugs()
    assert set(navigate.PAGES) == {slug for slug, hidden in shell.items() if not hidden}


@pytest.mark.parametrize(
    ("page", "path", "pattern"),
    [
        ("portfolio", "pages/portfolio/Portfolio.tsx",
         r'^\s+\["([a-z]+)", "portfolio\.tab_'),
        ("profile", "pages/profile/Profile.tsx",
         r'^\s+\{ id: "([a-z]+)", label: "profile\.'),
        ("sentiment", "pages/sentiment/Detail.tsx", r'^\s+key: "([a-z]+)",'),
    ],
)
def test_the_tabs_are_the_pages_own(page, path, pattern):
    assert navigate.PAGES[page] == _tabs(path, pattern)


def test_every_tab_the_server_accepts_has_a_button_label():
    """The drawer names a tab off `chat/links.tsx`'s `TAB_LABELS`; a tab missing
    there is drawn as the bare page, which is a link that lies about where it
    goes."""
    text = (APP / "chat" / "links.tsx").read_text()
    start = text.index("const TAB_LABELS")
    block = text[start:text.index("};\n", start)]
    drawn: dict[str, tuple[str, ...]] = {}
    for page, body in re.findall(r"\n  ([a-z]+): \{(.*?)\n  \}", block, re.S):
        drawn[page] = tuple(re.findall(r"\n    ([a-z]+): \"", body))
    assert drawn == {page: tabs for page, tabs in navigate.PAGES.items() if tabs}


def test_the_prompt_names_every_tab_it_would_accept():
    block = navigate.prompt_block()
    for page, tabs in navigate.PAGES.items():
        assert f"- {page}:" in block
        for tab in tabs:
            assert tab in block


@pytest.mark.parametrize(
    ("raw", "args"),
    [
        ("home", {"page": "home"}),
        ("portfolio/fees", {"page": "portfolio", "tab": "fees"}),
        ("Portfolio/FEES", {"page": "portfolio", "tab": "fees"}),
        ("ticker/brk.b", {"page": "ticker", "ticker": "BRK.B"}),
        ("ticker", {"page": "ticker"}),
        ("sector/whatever", {"page": "sector"}),
        ("bank", None),
        ("", None),
    ],
)
def test_a_target_is_a_page_the_shell_has(raw, args):
    assert navigate.target(raw) == args


# ------------------------------------------------------------ proposal edits


@pytest.mark.parametrize(
    ("said", "verdict"),
    [
        ("sí", True), ("Si!", True), ("ok.", True), ("vale", True),
        ("Yes please", True), ("no", False), ("Cancélalo", False),
        ("mejor no", False), ("sí, pero a 150", None), ("hola", None), ("", None),
    ],
)
def test_only_a_whole_yes_or_no_answers_a_proposal(said, verdict):
    assert tools.verdict(said) is verdict


def test_an_edit_goes_back_through_the_tools_own_parser():
    base = tools.Action("set_alerts", "AAPL",
                        {"alerts": [{"type": "above", "price": 200.0}]})
    edited = tools.revise(base, None, {"alerts": [{"type": "below", "price": 150}]})
    assert edited == tools.Action("set_alerts", "AAPL",
                                  {"alerts": [{"type": "below", "price": 150.0}]})
    assert tools.revise(base, "msft", None).ticker == "MSFT"
    # The tool itself is not editable: a "kind" in the edit is overwritten.
    assert tools.revise(base, None, {"action": "remove_ticker"}).kind == "set_alerts"
    assert tools.revise(base, None, {"alerts": [{"type": "above", "price": -1}]}) is None
    assert tools.revise(base, "AAPL US", None) is None
