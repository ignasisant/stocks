"""Does every path the React pages call still exist on the API?

TypeScript checks the shape a call expects and nothing at all about the path it
asks for, so a route renamed underneath a page fails at runtime, on that page,
for that reader. This reads each page's directory plus the shell and the chat
drawer (mounted over every page) and checks every `get(…)` / `send(…)` path
against the API's own route table.

Parsed rather than imported, because the other side is TypeScript.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stocks.api.app import app as fastapi_app

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend" / "app" / "src"

pytestmark = pytest.mark.skipif(
    not FRONTEND.exists(), reason="frontend sources not checked out"
)


def _pages() -> list[str]:
    """One directory per page under `src/pages/`."""
    root = FRONTEND / "pages"
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


PAGES = _pages()


def _sources(*roots: Path) -> list[Path]:
    """Every TypeScript source under these roots, tests excluded."""
    return [
        path
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.suffix in {".ts", ".tsx"}
        and "__tests__" not in path.parts
        and not path.name.endswith((".test.ts", ".test.tsx"))
    ]


def _react_text(slug: str) -> str:
    """The page's own directory plus the shell and the chat drawer."""
    roots = [FRONTEND / "pages" / slug, FRONTEND / "shell", FRONTEND / "chat"]
    return "\n".join(path.read_text() for path in _sources(*roots))


def test_every_page_is_scanned():
    """An empty list would pass by checking nothing."""
    assert {"home", "portfolio", "ticker"} <= set(PAGES)


@pytest.mark.parametrize("slug", PAGES)
def test_every_endpoint_the_page_calls_exists_on_the_server(slug: str):
    # Call sites only, rather than every path-shaped literal in the file: this
    # scan reads the chat drawer too, and `src/chat/markdown.tsx` is full of
    # regular expressions that begin with a slash.
    text = _react_text(slug).replace("${at(ticker)}", "/ticker/{p}")
    called = set()
    for raw in re.findall(r"\b(?:get|send)\s*(?:<[^(]*>)?\(\s*[`\"](/[^`\"]+)", text):
        # `${encodeURIComponent(ticker)}` and friends are one path parameter.
        called.add(re.sub(r"\$\{[^}]*\}", "{p}", raw))
    served = {
        re.sub(r"\{[^}]*\}", "{p}", path.removeprefix("/v1"))
        for path in fastapi_app.openapi()["paths"]
    }
    # A path that is the *prefix* of a real route is a builder, not a call —
    # `/ticker/{p}` is where every one of that page's calls starts. Failing on
    # it would only teach somebody to stop scanning that file.
    unknown = sorted(
        path
        for path in called
        if path not in served
        and not any(route.startswith(f"{path}/") for route in served)
    )
    assert not unknown, f"the {slug} page calls paths the API does not serve: {unknown}"
