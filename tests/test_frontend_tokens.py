"""The React front ends may only name design tokens the design system publishes.

Both of them — the Ticker page and the app shell — read `--ag-*` custom
properties back out of the document through their own `theme.ts`, and every
rule in their stylesheets is written in them. Both carry a
fallback, which is the trap: a name that `ds.tokens()` does not publish does not
fail, it silently freezes at whatever hex was typed beside it and drifts from
the app the next time the palette moves. That is exactly how `candle-up`,
`candle-down`, `sma-fast` and `sma-slow` sat hardcoded in the chart.

Parsed rather than imported because the other side is TypeScript. The regexes
are deliberately dumb: anything that looks like a token name counts, so a new
one cannot slip in through a spelling this test does not recognise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stocks.web.ds import tokens

REPO = Path(__file__).resolve().parents[1]
# Both front ends, because a token frozen at a hex is the same bug in either —
# and the app shell is where the pages the Ticker page has not absorbed land.
FRONTENDS = [REPO / "frontend" / "app" / "src"]

# `var(--ag-name)` in CSS or TSX, and `token("name")` in theme.ts.
_VAR = re.compile(r"var\(\s*--ag-([a-z0-9-]+)")
_TOKEN = re.compile(r'token\(\s*"([a-z0-9-]+)"')


def _named() -> dict[str, set[str]]:
    """Token name -> the files that use it, named by front end."""
    used: dict[str, set[str]] = {}
    for root in FRONTENDS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".css", ".ts", ".tsx"}:
                continue
            text = path.read_text()
            where = f"{root.parent.name}/{path.name}"
            for name in set(_VAR.findall(text)) | set(_TOKEN.findall(text)):
                used.setdefault(name, set()).add(where)
    return used


@pytest.mark.skipif(
    not any(root.exists() for root in FRONTENDS),
    reason="frontend sources not checked out",
)
def test_every_token_the_react_page_names_is_published_by_the_design_system():
    published = set(tokens())
    used = _named()
    unknown = {
        name: sorted(files)
        for name, files in used.items()
        if name not in published
    }
    assert not unknown, (
        "these read as a design token but ds.tokens() does not publish them, so "
        f"they silently fall back to a hardcoded value: {unknown}"
    )


@pytest.mark.skipif(
    not any(root.exists() for root in FRONTENDS),
    reason="frontend sources not checked out",
)
def test_the_page_actually_uses_tokens_rather_than_hexes():
    """A guard on the guard: if the stylesheet stopped naming tokens at all, the
    test above would pass by using none."""
    assert len(_named()) > 20
