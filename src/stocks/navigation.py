"""Where this app's pages are, what they are called, and how they group.

One table, because three things draw the same menu and a fourth checks it: the
Streamlit sidebar (`st.navigation`), the phone tab bar (`web/nav.py`), and the
React shell, which asks the API for it. A page added to one menu and not the
others is not a bug anybody reports — it is a page nobody finds.

Labels are i18n *key names*, not strings. Nothing here imports Streamlit or a
catalog: this module says which pages exist, and each caller says them in the
reader's language.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    """One page in the menu."""

    module: str  # app_pages/<module>.py
    path: str  # its URL path; "" is the default page, served at /
    label: str  # i18n key
    icon: str  # Material Symbols ligature — the same glyph in every menu
    section: str | None = None  # i18n key of its group; None is the top group


# In the order the design's left menu lists them: Inicio on its own, then the
# portfolio pages, then the market ones, then the account. `st.navigation`
# derives a page's URL from its filename, so `path` repeats that rather than
# choosing it — except the default page, which Streamlit serves at the root.
DESTINATIONS: tuple[Destination, ...] = (
    Destination("home", "", "nav.home", "home"),
    Destination("portfolio", "portfolio", "nav.portfolio", "pie_chart",
                "nav.section_portfolio"),
    Destination("import_transactions", "import_transactions", "nav.import",
                "upload_file", "nav.section_portfolio"),
    Destination("ticker", "ticker", "nav.ticker", "query_stats",
                "nav.section_market"),
    Destination("sentiment", "sentiment", "nav.sentiment", "speed",
                "nav.section_market"),
    Destination("sector", "sector", "nav.sector", "donut_small",
                "nav.section_market"),
    Destination("earnings", "earnings", "nav.earnings", "calendar_month",
                "nav.section_market"),
    Destination("profile", "profile", "nav.profile", "account_circle",
                "nav.section_account"),
)

# The phone tab bar's four destinations, by path. The DS mobile spec replaces
# the sidebar with a fixed bar, and four is what fits a 360px row with legible
# labels; the rest of the pages stay reachable through the drawer.
BOTTOM_NAV: tuple[str, ...] = ("", "portfolio", "sector", "profile")


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
