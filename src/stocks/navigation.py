"""Where this app's pages are, what they are called, and how they group.

One table, because the menu is drawn in one place and its routes are answered
in another: the React shell asks the API for it (`/v1/nav`) and draws the left
menu and the phone tab bar from it, and the server routes the same paths to
the shell (`SHELL_PATHS`). A page added to one and not the other is not a bug
anybody reports — it is a page nobody finds, or one that 404s on reload.

Labels are i18n *key names*, not strings. Nothing here imports a catalog: this
module says which pages exist, and each caller says them in the reader's
language.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    """One page in the menu."""

    path: str  # its URL path; "" is the default page, served at /
    label: str  # i18n key
    icon: str  # Material Symbols ligature — the same glyph in every menu
    section: str | None = None  # i18n key of its group; None is the top group


# In the order the design's left menu lists them: Inicio on its own, then the
# portfolio pages, then the market ones, then the account. The paths are the
# app's first ones, kept so old links and bookmarks still land; the default
# page is served at the root.
DESTINATIONS: tuple[Destination, ...] = (
    Destination("", "nav.home", "home"),
    Destination("portfolio", "nav.portfolio", "pie_chart",
                "nav.section_portfolio"),
    Destination("review", "nav.review", "swap_vert",
                "nav.section_portfolio"),
    Destination("import_transactions", "nav.import",
                "upload_file", "nav.section_portfolio"),
    Destination("ticker", "nav.ticker", "query_stats",
                "nav.section_market"),
    Destination("sentiment", "nav.sentiment", "speed",
                "nav.section_market"),
    Destination("sector", "nav.sector", "donut_small",
                "nav.section_market"),
    Destination("earnings", "nav.earnings", "calendar_month",
                "nav.section_market"),
    Destination("profile", "nav.profile", "account_circle",
                "nav.section_account"),
)

# The phone tab bar's four destinations, by path. The DS mobile spec replaces
# the sidebar with a fixed bar, and four is what fits a 360px row with legible
# labels; the rest of the pages stay reachable through the drawer.
BOTTOM_NAV: tuple[str, ...] = ("", "portfolio", "sector", "profile")

# Every first path segment the React shell answers, for the server that has to
# hand it the document. The menu's own paths, plus the shell's own names for
# two of them (`home` for the root, `import` for `import_transactions`) and the
# bank page, which is reached from Portfolio
# rather than from the menu. `tests/test_frontend_nav_parity.py` holds this to
# the shell's registry: a slug missing here is a page that 404s on reload.
SHELL_PATHS: tuple[str, ...] = tuple(
    sorted({d.path for d in DESTINATIONS if d.path} | {"home", "import", "bank"})
)


def by_path(path: str) -> Destination | None:
    """The destination a URL path names, or None for a path that is not a page."""
    wanted = path.strip("/")
    return next((d for d in DESTINATIONS if d.path == wanted), None)


def sections() -> list[tuple[str | None, list[Destination]]]:
    """The menu as its groups, in order, each one in order.

    Groups are built by walking the list rather than by sorting it: the order
    of the menu is the order of this table, and a group that appears twice
    would be two groups on screen — which is what a reader would see, so it is
    what this returns.
    """
    groups: list[tuple[str | None, list[Destination]]] = []
    for destination in DESTINATIONS:
        if groups and groups[-1][0] == destination.section:
            groups[-1][1].append(destination)
        else:
            groups.append((destination.section, [destination]))
    return groups
