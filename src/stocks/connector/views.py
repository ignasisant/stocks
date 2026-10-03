"""The MCP App: one `ui://` view the host draws a tool's result with.

Built by `frontend/app` (`vite.mcp.config.ts`) into one self-contained HTML
file under `web/static/mcp/`. Without that build the connector still serves
every tool, as text and structured content only — a missing view is logged,
never fatal.

The build leaves two markers for the server to fill, once per lifespan: the
design tokens (`ds_vars_css()`, the same `:root` block every page of the site
gets) and a JSON config — this site's origin, which the view needs to turn a
ticker into a link back here, and the view's own strings in every language
shipped. Both at load rather than at build so the view cannot drift from the
catalogs or the palette, and so one build serves any deployment's origin.
"""

from __future__ import annotations

import json
from pathlib import Path

from stocks import obs

URI = "ui://topstocks/view"
HTML = Path(__file__).resolve().parents[1] / "web" / "static" / "mcp" / "view.html"

TOKENS_MARK = "<!--AG-TOKENS-->"
CONFIG_MARK = "<!--TS-CONFIG-->"

# The view reads only its own namespace; the rest of the catalog is ~2300
# strings it would carry for nothing.
_PREFIX = "connector.view_"


def config(origin: str) -> str:
    """The `<script type="application/json">` the view reads at start."""
    from stocks.web import i18n

    strings = {
        lang: {k: v for k, v in i18n.catalog(lang).items() if k.startswith(_PREFIX)}
        for lang in i18n.LANGUAGES
    }
    blob = json.dumps({"origin": origin, "strings": strings},
                      ensure_ascii=False, separators=(",", ":"))
    # Inside a <script>, "</script>" in a string would end the element; no
    # "<" at all is the simple way to make that impossible.
    blob = blob.replace("<", "\\u003c")
    return f'<script type="application/json" id="ts-config">{blob}</script>'


def load(origin: str) -> str | None:
    """The view's document for `origin`, or None when it was never built."""
    from stocks.web.ds import ds_vars_css

    try:
        html = HTML.read_text(encoding="utf-8")
    except OSError:
        obs.warn("mcp.view_missing")
        return None
    if TOKENS_MARK not in html or CONFIG_MARK not in html:
        obs.warn("mcp.view_unmarked")
    return (html.replace(TOKENS_MARK, ds_vars_css(), 1)
                .replace(CONFIG_MARK, config(origin), 1))
