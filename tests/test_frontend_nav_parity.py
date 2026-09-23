"""Every page the app ships is reachable in the React shell, under its own URL.

`stocks.navigation` is the one table three menus are built from — the Streamlit
sidebar, the phone tab bar and the shell's rail. The shell cannot read it at
build time (it is a Python module and the rail is a bundled registry of lazy
imports), so the two are kept in step by this test instead of by discipline.

Two failures it exists to catch, both silent in production:

* **A page that is not in the shell at all.** `pageFor` falls back to Home for
  an unknown slug, so a page dropped from the registry does not 404 — it
  quietly serves the dashboard under the missing page's URL.
* **A path that changed on one side only.** Streamlit derives a page's URL from
  its filename, so Import is served at `/import_transactions` and Home at the
  root; the shell calls them `import` and `home`. Those are declared as
  `aliases` in the registry. A rename on either side without the alias breaks
  every bookmark and every link ever shared, and breaks them into a page that
  loads fine.

Parsed rather than imported because the other side is TypeScript.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stocks import navigation

REGISTRY = Path(__file__).resolve().parents[1] / "frontend/app/src/shell/pages.ts"

_SLUG = re.compile(r'slug:\s*"([^"]*)"')
_ALIASES = re.compile(r"aliases:\s*\[([^\]]*)\]")
_STRING = re.compile(r'"([^"]*)"')


@pytest.fixture(scope="module")
def registry() -> str:
    return REGISTRY.read_text(encoding="utf-8")


def _entries(source: str) -> list[tuple[str, list[str]]]:
    """(slug, aliases) per entry, split on the slug that opens each one."""
    out: list[tuple[str, list[str]]] = []
    marks = list(_SLUG.finditer(source))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(source)
        block = source[mark.end() : end]
        alias = _ALIASES.search(block)
        out.append(
            (mark.group(1), _STRING.findall(alias.group(1)) if alias else [])
        )
    return out


def test_the_shell_has_a_page_for_every_destination(registry):
    reachable = {slug for slug, _ in _entries(registry)}
    reachable |= {a for _, aliases in _entries(registry) for a in aliases}
    missing = {d.path for d in navigation.DESTINATIONS} - reachable
    assert not missing, f"no page in the React shell answers: {sorted(missing)}"


def test_no_slug_is_claimed_twice(registry):
    """Including aliases: two entries answering one path is a coin toss over
    which page a bookmark opens, decided by list order."""
    claimed = [slug for slug, _ in _entries(registry)]
    claimed += [a for _, aliases in _entries(registry) for a in aliases]
    duplicates = {s for s in claimed if claimed.count(s) > 1}
    assert not duplicates, f"claimed by more than one page: {sorted(duplicates)}"


def test_the_two_paths_that_do_not_match_are_declared(registry):
    """The named ones, so the reason survives a refactor that 'tidies' them.

    Home is Streamlit's default page and is served at the root; Import is
    `import_transactions` because that is its module's filename. Neither is a
    name the shell would have chosen, and neither is free to drop.
    """
    aliases = {a for _, aliases in _entries(registry) for a in aliases}
    assert "" in aliases
    assert "import_transactions" in aliases
