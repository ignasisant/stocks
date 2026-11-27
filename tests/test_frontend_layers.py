"""Import direction in the React app: an area reaches down, and a page keeps to
itself.

`frontend/app/src` has five areas and one folder per page. Their order is what
`tests/test_layers.py` is to the Python side:

    ui, shell  <  share  <  chat  <  pages/<page>, mcp

`ui` and `shell` are one base layer and import each other freely. Above it an
import may go down or stay inside its own area: two areas of the same rank,
two pages or a page and the MCP widget, do not import each other. Two things
may not happen unless listed in `_DEBT` with the reason:

* **An import that climbs.** A primitive in `ui` that needs the chat is no
  longer a primitive, and the chat reading a page's module means the drawer
  ships that page's code on every screen.
* **A page importing another page.** Pages are lazy chunks; one reaching into
  another either pulls that chunk in or proves the module was never the
  page's own. Shared code belongs in `ui` or `shell`.

`_DEBT` is what the app owed the day the guard was written. It is checked both
ways, so it only shrinks: a new edge fails, and so does an entry whose edge is
gone. A page is listed once per page it reaches; anything else per file.

`shell/pages.ts` is the registry of lazy pages, the one place that has to name
them all, and is outside the rule. So are the test files and the two entry
modules at the root.

Parsed rather than imported because the sources are TypeScript.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend/app/src"

_RANKS = {"ui": 0, "shell": 0, "share": 1, "chat": 2, "pages": 3, "mcp": 3}

_REGISTRY = "shell/pages.ts"

# A relative specifier after `from`, `import` or `import(`. No alias points at
# the app's own code, so every import of it is relative.
_IMPORT = re.compile(r"""(?:\bfrom|\bimport)\s*\(?\s*["'](\.{1,2}/[^"']+)["']""")

# (page, or file outside `pages/`; area it reaches): why it is still there.
_DEBT: dict[tuple[str, str], str] = {
    # The base layer reaching the chat.
    ("shell/Layout.tsx", "chat"): "the frame mounts the drawer",
    ("shell/assistant.ts", "chat"): "seeds the chat's draft",
    ("shell/Feedback.tsx", "chat"): "dictates with the chat's recorder",
    # The chat reading a page's modules.
    ("chat/Composer.tsx", "pages/import"): "accepts the importer's file types",
    ("chat/pasted.ts", "pages/import"): "a pasted statement is filed as the importer's",
    ("chat/useChat.ts", "pages/import"): "names a statement as the importer does",
    ("chat/Panel.tsx", "pages/import"): "shows the importer's moves table",
    ("chat/chart.tsx", "pages/ticker"): "an answer's chart is the ticker's plot",
    ("chat/donut.tsx", "pages/portfolio"): "an answer's donut is the portfolio's",
    ("chat/donut.tsx", "pages/review"): "country names for the donut's slices",
    ("chat/donut.tsx", "pages/sentiment"): "sector keys and the blank dash, from Pulse",
    # A page reaching into another page. Mostly a shared module that was
    # written in the first page to need it: `home/format`, `home/types`,
    # `sentiment/format`, `review/format`, `ticker/plot`, `portfolio/charts`.
    ("pages/earnings", "pages/portfolio"): "portfolio/format",
    ("pages/home", "pages/earnings"): "the calendar's strip and event sheet",
    ("pages/home", "pages/portfolio"): "portfolio/api and the tax words",
    ("pages/home", "pages/sentiment"): "sentiment/format and its types",
    ("pages/home", "pages/ticker"): "ticker/format",
    ("pages/portfolio", "pages/home"): "home/format",
    ("pages/portfolio", "pages/sentiment"): "sentiment/format",
    ("pages/portfolio", "pages/ticker"): "ticker/plot",
    ("pages/profile", "pages/portfolio"): "portfolio/api, for the plan",
    ("pages/review", "pages/home"): "home/format and the Go link",
    ("pages/review", "pages/portfolio"): "portfolio/format and its charts",
    ("pages/review", "pages/sentiment"): "sentiment/format",
    ("pages/review", "pages/ticker"): "ticker types and data, for the plan chart",
    ("pages/sector", "pages/review"): "the quality map, review/format, its types",
    ("pages/sector", "pages/ticker"): "ticker/format",
    ("pages/ticker", "pages/import"): "the importer's label for a split ratio",
    ("pages/ticker", "pages/portfolio"): "portfolio/charts, for Compare",
    ("pages/ticker", "pages/review"): "review/format, its lines and types",
    ("pages/ticker", "pages/sentiment"): "sentiment/format",
    ("pages/today", "pages/home"): "home/format, home/types, Go and the brief editor",
    ("pages/today", "pages/review"): "review/format and its types",
    ("pages/today", "pages/sentiment"): "sentiment/format",
}


def _area(rel: Path) -> str | None:
    """`pages/<page>` for a file of a page, the top folder for the rest, and
    None for a file at the root or loose in `pages/`."""
    parts = rel.parts
    if len(parts) < 2:
        return None
    if parts[0] == "pages":
        return f"pages/{parts[1]}" if len(parts) > 2 else None
    return parts[0]


def _edges() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    root = SRC.resolve()
    for path in sorted(root.rglob("*.ts*")):
        rel = path.relative_to(root)
        own = _area(rel)
        if own is None or ".test." in path.name or rel.as_posix() == _REGISTRY:
            continue
        for spec in _IMPORT.findall(path.read_text()):
            target = (path.parent / spec).resolve()
            if not target.is_relative_to(root):
                continue
            to = _area(target.relative_to(root))
            if to is None or to == own:
                continue
            rank, to_rank = (_RANKS[a.split("/")[0]] for a in (own, to))
            if to_rank > rank or (to_rank == rank and rank > 0):
                unit = own if own.startswith("pages/") else rel.as_posix()
                found.add((unit, to))
    return found


def test_every_area_has_a_rank():
    areas = {p.name for p in SRC.iterdir() if p.is_dir()}
    assert areas <= _RANKS.keys(), f"no rank for {sorted(areas - _RANKS.keys())}"


def test_the_parser_reads_the_imports():
    # A regex that stopped matching would pass every rule below in silence.
    registry = _IMPORT.findall((SRC / _REGISTRY).read_text())
    assert any(spec.startswith("../pages/") for spec in registry)
    assert _IMPORT.findall('const page = () => import("./pages/home/Home");') == [
        "./pages/home/Home"
    ]
    assert _IMPORT.findall('import "../portfolio/portfolio.css";') == [
        "../portfolio/portfolio.css"
    ]


def test_imports_reach_down_and_pages_keep_to_themselves():
    edges = _edges()
    new = edges - _DEBT.keys()
    assert not new, f"import climbs an area, or crosses pages: {sorted(new)}"
    paid = _DEBT.keys() - edges
    assert not paid, f"edge gone, drop it from _DEBT: {sorted(paid)}"
