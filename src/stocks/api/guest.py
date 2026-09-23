"""What an anonymous visitor may read, as one list.

The app has served guests since its first commit — the landing's main call to
action drops somebody straight into a demo book without an account — and this
is that same surface, restated where the API can enforce it: the watchlist
table, the whole Portfolio over the shared demo book, a ticker minus the parts
that are somebody's own (favourites, tags, alerts, the assistant), a sector's
computed cohort, the earnings calendar, the market regime, search, and a way to
say what is wrong.

Keyed on `(templated path, method)` exactly as the OpenAPI schema spells them —
the same strings `tests/test_api.py`'s WRITES and `tests/test_api_surface.py`'s
PUBLIC already use — because the alternative, a flag on the route, puts the
answer in fifty-odd places and the question in none.

**The default is closed and stays closed.** `api.app.gate` refuses anything not
named here, so a route added tomorrow is shut to a guest without anyone deciding
that it should be. The price of keying on a string is the opposite failure: a
*rename* silently closes a route the shell needs. That is what
`api.app._guest_surface_is_real()` checks at import, so it is a failed boot
rather than a page that will not paint.
"""

from __future__ import annotations

#: The one non-read, kept apart so "a guest may only read" stays a sentence a
#: test can check. Feedback is offered to guests because the app has always
#: offered it to them — a visitor who bounced off the pitch knowing why is worth
#: more than a login — and it writes `data/feedback/`, never the guest dir. It
#: is the only unauthenticated write in the API, so it carries an IP rate limit
#: of its own; see `routes/feedback.py`.
OPEN_WRITES: frozenset[tuple[str, str]] = frozenset(
    {
        ("/v1/feedback", "POST"),
    }
)

OPEN: frozenset[tuple[str, str]] = frozenset(
    {
        # --- who is asking, and what the numbers mean --------------------
        # `/me` answers "guest" and names nobody; `/prefs` answers the defaults
        # and never reads the shared file. Both before the first page renders.
        ("/v1/me", "GET"),
        ("/v1/prefs", "GET"),
        # --- Home ---------------------------------------------------------
        ("/v1/watchlist", "GET"),
        ("/v1/earnings", "GET"),
        ("/v1/search", "GET"),
        # The setup card and the tour read this; stamping it seen does not.
        ("/v1/onboarding", "GET"),
        # --- Portfolio, all five tabs, over the shared demo book ----------
        ("/v1/portfolio/positions", "GET"),
        ("/v1/portfolio/summary", "GET"),
        ("/v1/portfolio/transactions", "GET"),
        ("/v1/portfolio/transactions.csv", "GET"),
        ("/v1/portfolio/performance", "GET"),
        ("/v1/portfolio/history", "GET"),
        ("/v1/portfolio/fees", "GET"),
        ("/v1/portfolio/dividends", "GET"),
        ("/v1/portfolio/tax", "GET"),
        ("/v1/portfolio/risk", "GET"),
        # --- Ticker, minus favourites, tags, alerts and the assistant -----
        ("/v1/ticker/{symbol}/profile", "GET"),
        ("/v1/ticker/{symbol}/position", "GET"),
        ("/v1/ticker/{symbol}/bars", "GET"),
        ("/v1/ticker/{symbol}/quote", "GET"),
        ("/v1/ticker/{symbol}/events", "GET"),
        ("/v1/ticker/{symbol}/metrics", "GET"),
        ("/v1/ticker/{symbol}/financials", "GET"),
        ("/v1/ticker/{symbol}/crypto", "GET"),
        ("/v1/ticker/{symbol}/peers", "GET"),
        ("/v1/ticker/{symbol}/valuation", "GET"),
        ("/v1/ticker/{symbol}/moat", "GET"),
        ("/v1/ticker/{symbol}/insiders", "GET"),
        ("/v1/ticker/{symbol}/fund", "GET"),
        ("/v1/comparables", "GET"),
        ("/v1/market/quotes", "GET"),
        ("/v1/market/profiles", "GET"),
        ("/v1/market/status", "GET"),
        # --- Sector: the computed cohort, and the verdict's stand-in ------
        # The GET never spends and a guest can store nothing, so what it gets
        # is the computed read — the Streamlit card's answer for a visitor with
        # no account. Having one *written* is the POST, and that stays shut.
        ("/v1/sectors", "GET"),
        ("/v1/sectors/{sector}", "GET"),
        ("/v1/sectors/{sector}/verdict", "GET"),
        # --- Sentiment: the regime and the indices half -------------------
        ("/v1/pulse", "GET"),
        ("/v1/pulse/book", "GET"),
        ("/v1/pulse/tables", "GET"),
        # --- Reference the pages above cannot render without --------------
        # The menu, the provenance note under the metric grid, and the labels
        # the tax tab's jurisdiction row reads. Shipped tables, same for all.
        ("/v1/nav", "GET"),
        ("/v1/kpi-sources", "GET"),
        ("/v1/jurisdictions", "GET"),
        *OPEN_WRITES,
    }
)

# Deliberately absent, each for its own reason:
#
#   /v1/chat/*            spends the operator's API keys and writes chat.json.
#   /v1/import/*          including `platforms` and `sample`: a guest has no
#                         book to import into, and the shared one is not it.
#   /v1/profile           the assistant's persona; there is no assistant.
#   POST /v1/onboarding/seen   the tour's progress is per account — writing it
#                         would hand the next visitor this one's place in it.
#   /v1/daily             a generated briefing on a per-account budget, stored
#                         in a file every visitor would share.
#   /v1/movers /extremes  the dashboard cards the guest Home does not draw.
#   /v1/search/recent     a history a guest cannot have and must not share.
#   /v1/watchlist/tags, /suggestions, /{ticker}/alerts   somebody's own edits.
#   /v1/notify/*, /v1/account, /v1/bank/*, and every write but the one above.
