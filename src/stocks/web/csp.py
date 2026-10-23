"""The Content-Security-Policy of every document this server writes.

No `'unsafe-inline'` anywhere: a page's own inline `<style>` and `<script>`
blocks are allowed by their SHA-256, and nothing else inline runs — no
`style=""` attributes, no `on*=` handlers.

The hashes come from text the server wrote itself (the design tokens, the
landing stylesheet, a page's one script), never from a response that has had
a request's values spliced into it: a hash of an injected block would allow
the injection. `inline_blocks` is for documents that are pure functions of
the build — the landing, the shell's index.html — and the callers with
reflected values (consent, sign-out, 404) hash their constants directly.

Script and style attributes set from JavaScript (`el.style.x = …`, React's
`style={{…}}`) go through the CSSOM and are not subject to `style-src`; only
markup is.
"""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import urlsplit

from stocks.data.logo import COINCAP_URL, FAVICON_URL, FMP_LOGO_URL


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


# The font stylesheet and the faces it names, the one third-party origin the
# documents load from.
FONTS_STYLES = "https://fonts.googleapis.com"
FONTS_FILES = "https://fonts.gstatic.com"

# The app's own third-party reach: the screenshot library the feedback form
# loads on demand, the BYOK key exchange the browser makes to OpenRouter, and
# the avatar the sign-in provider hands out.
APP_SCRIPTS = ("https://cdn.jsdelivr.net",)
APP_CONNECT = ("https://openrouter.ai",)
APP_IMAGES = (
    "https://*.googleusercontent.com",
    # A logo not yet mirrored onto this origin is drawn from where it was
    # found (`data.logo`); the next view reads the mirror.
    origin_of(FMP_LOGO_URL),
    origin_of(FAVICON_URL),
    origin_of(COINCAP_URL),
)

_BLOCK = re.compile(
    r"<(style|script)(?P<attrs>(?:\s[^>]*)?)>(?P<body>.*?)</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
# A script that is data, not code (JSON-LD, the MCP view's config): the browser
# never runs it, so the policy never looks at it.
_DATA_SCRIPT = re.compile(r"""type\s*=\s*["']?(?:application/(?:ld\+)?json)""", re.I)


def source(text: str) -> str:
    """`text` as a CSP source expression: `'sha256-…'`."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return f"'sha256-{base64.b64encode(digest).decode('ascii')}'"


def inline_blocks(html: str) -> tuple[list[str], list[str]]:
    """The (style, script) hash sources of `html`'s inline blocks.

    Only for a document the server built from constants — see the module
    docstring.
    """
    styles: list[str] = []
    scripts: list[str] = []
    for match in _BLOCK.finditer(html):
        attrs = match.group("attrs")
        if match.group(1).lower() == "style":
            styles.append(source(match.group("body")))
        elif "src=" not in attrs.lower() and not _DATA_SCRIPT.search(attrs):
            scripts.append(source(match.group("body")))
    return styles, scripts


def policy(
    *,
    styles: list[str] | tuple[str, ...] = (),
    scripts: list[str] | tuple[str, ...] = (),
    fonts: bool = True,
    app: bool = False,
    form_action: str = "",
) -> str:
    """The header value for a document.

    `styles` / `scripts` are hash sources for its inline blocks. `app` widens
    it to what the React shell reaches (see `APP_*`); `form_action` adds the
    origin a form may post to besides this one (the consent page's redirect).
    """
    unique = lambda items: list(dict.fromkeys(items))  # noqa: E731
    style_src = ["'self'"] + ([FONTS_STYLES] if fonts else []) + unique(styles)
    script_src = ["'self'", *(APP_SCRIPTS if app else ()), *unique(scripts)]
    font_src = ["'self'"] + ([FONTS_FILES] if fonts else [])
    img_src = ["'self'", "data:"] + (["blob:", *APP_IMAGES] if app else [])
    connect_src = ["'self'", *(APP_CONNECT if app else ())]
    directives = [
        "default-src 'self'",
        "script-src " + " ".join(script_src),
        "style-src " + " ".join(style_src),
        "font-src " + " ".join(font_src),
        "img-src " + " ".join(img_src),
        "connect-src " + " ".join(connect_src),
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'" + (f" {form_action}" if form_action else ""),
        "frame-ancestors 'none'",
    ]
    return "; ".join(directives)


def for_document(html: str, **kw) -> str:
    """`policy()` with the hashes of a build-constant document's own blocks."""
    styles, scripts = inline_blocks(html)
    return policy(styles=styles, scripts=scripts, **kw)
