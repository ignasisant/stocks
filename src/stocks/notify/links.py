"""Deep links from a notification back into the app.

A digest that names six tickers and then leaves the reader to find them is a
report; one whose names are links is a way in. The whole module is optional by
design: the public origin is a deploy setting (`[app] public_url` /
`APP_PUBLIC_URL`, the same one `web.server` canonicalises on), and with it
unset every function here returns None so the messages render exactly as they
did before rather than emitting links to a hostname nobody can reach.

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
PORTFOLIO = "portfolio"
IMPORT = "import_transactions"
EARNINGS = "earnings"
TICKER = "ticker"


def app_base() -> str | None:
    """The app's public origin, or None when this deploy has not declared one.

    Deliberately the same secret `web.server.public_origin` reads: a link in a
    Telegram message and a canonical URL in a page head are the same promise
    about where this app lives, and two settings would let them disagree.
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
