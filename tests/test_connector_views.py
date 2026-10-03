"""The connector's MCP App: the built file, and what the server writes into it.

The view is built by `frontend/app` and committed, like the app's bundle. A
host fetches it as one document into a frame that can load nothing but this
site's images, so it has to stand on its own — and the strings, tokens and
origin it reads at start are the server's to fill, from the same catalogs and
palette as every page.
"""

from __future__ import annotations

import json
import re
import typing
from pathlib import Path

import pytest

from stocks.connector import tools, views
from stocks.web import i18n

ORIGIN = "https://topstocks.example"
SOURCES = Path(__file__).resolve().parents[1] / "frontend" / "app" / "src" / "mcp"


def _config(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="ts-config">(.*?)</script>',
                      html, re.S)
    assert match, "no config in the view"
    return json.loads(match.group(1))


# ------------------------------------------------------------ the built file


def test_the_view_is_built_and_committed():
    assert views.HTML.is_file(), "run: npm --prefix frontend/app run build"


def test_the_view_is_one_document_that_loads_nothing():
    html = views.HTML.read_text(encoding="utf-8")
    # Hosts cap what a resource may weigh; the view is a few components.
    assert len(html) < 140_000
    assert "<link" not in html
    assert not re.search(r'\ssrc="', html), "a script or image left outside the file"
    assert not re.search(r'href="https?:', html)
    assert html.count(views.TOKENS_MARK) == 1
    assert html.count(views.CONFIG_MARK) == 1


# ----------------------------------------------------------- what is filled


def test_load_fills_the_tokens_and_the_config():
    html = views.load(ORIGIN)
    assert html is not None
    assert views.TOKENS_MARK not in html and views.CONFIG_MARK not in html
    assert "--ag-surface-card:" in html
    config = _config(html)
    assert config["origin"] == ORIGIN
    assert set(config["strings"]) == set(i18n.LANGUAGES)
    for strings in config["strings"].values():
        assert strings and all(k.startswith("connector.view_") for k in strings)


def test_every_string_the_view_names_is_in_every_language():
    named: set[str] = set()
    for source in SOURCES.glob("*.tsx"):
        if source.name.endswith(".test.tsx"):
            continue
        named |= set(re.findall(r'"(connector\.view_\w+)"', source.read_text()))
    # The window label is built from the tool's own literal.
    window = typing.get_args(tools.Window)
    named |= {f"connector.view_window_{w}" for w in window}
    assert len(named) > 20
    config = _config(views.load(ORIGIN) or "")
    for lang, strings in config["strings"].items():
        assert not named - set(strings), (lang, sorted(named - set(strings)))


def test_a_string_cannot_close_the_config_script(monkeypatch):
    monkeypatch.setattr(i18n, "catalog",
                        lambda lang: {"connector.view_value": "</script><b>x</b>"})
    block = views.config(ORIGIN)
    body = block.removeprefix('<script type="application/json" id="ts-config">')
    body = body.removesuffix("</script>")
    assert "<" not in body
    strings = json.loads(body)["strings"]["en"]
    assert strings["connector.view_value"] == "</script><b>x</b>"


def test_an_unbuilt_view_is_no_view_and_no_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(views, "HTML", tmp_path / "view.html")
    assert views.load(ORIGIN) is None


def test_an_unmarked_build_still_loads(monkeypatch, tmp_path):
    page = tmp_path / "view.html"
    page.write_text("<html><body>old build</body></html>")
    monkeypatch.setattr(views, "HTML", page)
    assert views.load(ORIGIN) == "<html><body>old build</body></html>"


# ------------------------------------------------------------------ logos


@pytest.mark.parametrize(
    ("mirrored", "origin", "expected"),
    [
        ("/app/static/logos/AAPL.png", ORIGIN, f"{ORIGIN}/app/static/logos/AAPL.png"),
        # Only the mirror is this site's; the CSP would refuse anything else.
        ("https://cdn.example/AAPL.png", ORIGIN, None),
        ("//cdn.example/AAPL.png", ORIGIN, None),
        (None, ORIGIN, None),
        ("/app/static/logos/AAPL.png", None, None),
    ],
)
def test_a_logo_is_this_sites_mirror_or_nothing(monkeypatch, mirrored, origin, expected):
    from stocks.api import loaders

    monkeypatch.setattr(loaders, "logo", lambda ticker: mirrored)
    assert tools._logo("AAPL", origin) == expected
