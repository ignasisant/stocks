"""Deep links from a notification back into the app.

A notification is a way in, not a report: tapping it should land on the page
that tells the rest. A push opens a path on the app's own origin (`path`,
`ticker_path`), which the service worker resolves, so it needs no setting.
An absolute URL (`page_url`) needs the public origin, a deploy setting
(`[app] public_url` / `APP_PUBLIC_URL`, the same one `web.server`
canonicalises on); with it unset those functions return None rather than
emitting links to a hostname nobody can reach.

Paths are the ones `stocks.navigation` gives each page, so a page renamed there
must be renamed here too. tests/test_links.py pins the pages that are linked to
the paths the shell answers.
"""

from __future__ import annotations

import urllib.parse

from stocks.secrets_env import secret

# Each page's path in `navigation.DESTINATIONS` (home is the default page and
# answers at the root).
HOME = ""
TODAY = "today"
PORTFOLIO = "portfolio"
IMPORT = "import_transactions"
EARNINGS = "earnings"
TICKER = "ticker"


def app_base() -> str | None:
    """The app's public origin, or None when this deploy has not declared one.

    Deliberately the same secret `web.server.public_origin` reads: a link
    sent out of the app and a canonical URL in a page head are the same
    promise about where this app lives, and two settings would let them
    disagree.
    """
    origin = secret("APP_PUBLIC_URL", "app", "public_url")
    return origin.rstrip("/") or None


def page_url(path: str, base: str | None = None, **query: str) -> str | None:
    """Absolute URL for an app page, or None without a configured origin."""
    base = base if base is not None else app_base()
    if not base:
        return None
    url = f"{base}/{path}" if path else f"{base}/"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def ticker_url(ticker: str, base: str | None = None) -> str | None:
    """The ticker page for `ticker` — the app reads `?ticker=` on arrival."""
    return page_url(TICKER, base, ticker=ticker.upper())


def path(page: str, **query: str) -> str:
    """An app page as a path on the app's own origin — what a push opens."""
    url = f"/{page}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def ticker_path(ticker: str) -> str:
    return path(TICKER, ticker=ticker.upper())
