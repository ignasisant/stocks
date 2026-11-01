"""The drawer's `navigate` tool: the pages an answer may offer to open.

An AG-UI *frontend* tool — the model proposes, the client runs it — carried on
a marker rather than on the provider's tool calling. The free chain rotates
through models that cannot all call tools, and a page link is too small a
thing to cost a second round trip on the ones that can; one line of prose that
ends in `[[open:portfolio/tax]]` works on every backend the chain has.

The marker never reaches the reader. The HTTP route withholds it while the
answer streams (`guide_ai.MarkerFilter` with this module's pattern), checks it
against the page table below, and hands what survives to the client as a
`navigate` tool call; the drawer draws it as a button under the answer. A page
or tab the model invented is dropped without a trace — the answer stands and
simply ends in prose.

The page table mirrors the React shell's: its slugs are `shell/pages.ts`, its
tabs each page's own `?tab=` list. `tests/test_chat_navigate.py` reads those
files and fails when the two drift.
"""

from __future__ import annotations

import re

from stocks import obs

# page slug -> the `?tab=` values it answers, in the page's own order. `ticker`
# takes a symbol instead of a tab. The bank page is left out: it is hidden
# behind an allowlist, and a link to a page the reader cannot use is a 404
# with extra steps.
PAGES: dict[str, tuple[str, ...]] = {
    "home": (),
    "today": ("alerts", "routines", "book", "news", "insiders", "compare",
              "macro", "trends"),
    "portfolio": ("overview", "positions", "risk", "projection", "tax",
                  "dividends", "fees"),
    "review": (),
    "import": (),
    "ticker": (),
    "sentiment": ("indices", "gauges", "rates", "inflation", "rotation",
                  "factors", "cross", "positioning"),
    "sector": (),
    "earnings": (),
    "learn": ("paths", "glossary"),
    "profile": ("prefs", "iv", "plan", "watch", "notify", "claude"),
}

# Each tab's catalog key, by page slug and `?tab=` value: the label the shell
# draws on the tab itself (the drawer's `chat/links.tsx` keeps the same table
# for its buttons, and `tests/test_chat_navigate.py` holds the two together).
# The prompt names the tab the reader is on by this label, so "what is this
# column?" asked on the Fees tab is answered about fees.
TAB_LABELS: dict[str, dict[str, str]] = {
    "today": {
        "alerts": "today.tab_alerts",
        "routines": "today.tab_routines",
        "book": "today.tab_book",
        "news": "today.tab_news",
        "insiders": "today.tab_insiders",
        "compare": "today.tab_compare",
        "macro": "today.tab_macro",
        "trends": "today.tab_trends",
    },
    "portfolio": {
        "overview": "portfolio.tab_overview",
        "positions": "portfolio.tab_positions",
        "risk": "portfolio.tab_alloc_risk",
        "projection": "portfolio.tab_projection",
        "tax": "portfolio.tab_realized_tax",
        "dividends": "portfolio.tab_dividends",
        "fees": "portfolio.tab_fees",
    },
    "sentiment": {
        "indices": "sentiment.indices_title",
        "gauges": "sentiment.risk_title",
        "rates": "sentiment.rates_title",
        "inflation": "sentiment.inflation_title",
        "rotation": "sentiment.rotation_title",
        "factors": "sentiment.factors_title",
        "cross": "sentiment.cross_title",
        "positioning": "sentiment.positioning_title",
    },
    "learn": {
        "paths": "learn.tab_paths",
        "glossary": "learn.tab_glossary",
    },
    "profile": {
        "prefs": "profile.preferences",
        "iv": "profile.iv_section",
        "plan": "profile.plan_section",
        "watch": "profile.watchlist",
        "notify": "profile.notifications",
        "claude": "profile.connector_tab",
    },
}


def tab_label(page: str, tab: str) -> str:
    """The catalog key of `tab` on `page`, or '' when the page has no such
    tab — a value off the URL is never echoed into a prompt as it came."""
    return TAB_LABELS.get(page, {}).get((tab or "").strip().lower(), "")


# `[[open:page]]`, `[[open:page/tab]]` or `[[open:ticker/SYMBOL]]`. One group,
# so `MarkerFilter.found` collects the whole target.
MARKER_RE = re.compile(
    r"\[\[open:\s*([a-z_]{1,20}(?:/[A-Za-z0-9.\-]{1,20})?)\s*\]\]"
)

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")

# What each page is for, in the words the model needs to pick one. English:
# the prompt is, and the reader never sees these.
_WHAT = {
    "home": "the daily briefing and the book at a glance",
    "today": "the day's page: the reader's alerts, book, news, insider "
             "trades, comparisons against sector and index, macro and "
             "trends. Tabs: alerts, routines, book (the book against the "
             "S&P 500), news, insiders, compare, macro (rates, Fed, ECB, "
             "inflation), trends (regime, sectors, crypto)",
    "portfolio": "the reader's holdings. Tabs: overview, positions, "
                 "risk (allocation and risk), projection, tax (realized "
                 "gains and tax), dividends, fees",
    "review": "what to sell, trim or add to in the book, and which outside "
              "tickers to buy (verdicts on quality and price, with tax)",
    "import": "upload a broker statement",
    "ticker": "one company: chart, fundamentals, news. Write the symbol "
              "after a slash: ticker/AAPL",
    "sentiment": "market mood. Tabs: indices, gauges (fear and greed), "
                 "rates, inflation, rotation (sector rotation), factors "
                 "(style ratios), cross (other asset classes), positioning "
                 "(speculators' futures positions, CFTC)",
    "sector": "sector screen and peers",
    "earnings": "the earnings calendar",
    "learn": "short lessons on investing and Spanish tax. Tabs: paths "
             "(lessons), glossary (term definitions)",
    "profile": "account settings. Tabs: prefs (preferences), iv (investor "
               "profile), plan (target mix, risk caps, contribution and cash "
               "reserve), watch (watchlist), notify (alerts and notifications), claude "
               "(connect Claude to the account)",
}

TOOL_NAME = "navigate"

def target(raw: str) -> dict[str, str] | None:
    """`page`, `page/tab` or `ticker/SYM` as navigate args, or None if unknown.

    A known page with a tab it does not have keeps the page: "open Portfolio"
    is still the right answer to a question about a tab the model misnamed.
    """
    page, _, sub = str(raw or "").strip().partition("/")
    page = page.lower()
    if page not in PAGES:
        return None
    if page == "ticker":
        symbol = sub.strip().upper()
        return {"page": page, "ticker": symbol} if _SYMBOL_RE.match(symbol) \
            else {"page": page}
    tab = sub.strip().lower()
    return {"page": page, "tab": tab} if tab in PAGES[page] else {"page": page}


def scrub(text: str) -> str:
    return MARKER_RE.sub("", str(text or "")).rstrip()


def claim(entry: dict, found: list[str]) -> dict[str, str] | None:
    """File the answer's page link on the stored turn; return its args.

    The last valid marker wins, as `guide_ai.claim_goto` does it: a stream that
    fell to a second provider can carry one from each. The text is scrubbed
    either way, for the marker that arrived in a shape the filter could not
    withhold.
    """
    raw = str(entry.get("content") or "")
    seen = [*found, *(hit.group(1) for hit in MARKER_RE.finditer(raw))]
    entry["content"] = scrub(raw)
    for candidate in reversed(seen):
        args = target(candidate)
        if args is not None:
            entry["nav"] = args
            obs.event("chat.nav_offered", page=args["page"],
                      tab=args.get("tab", ""))
            return args
    return None


def prompt_block() -> str:
    """The system-prompt paragraph that offers the tool. Only sent when the
    client declared `navigate` — a surface with no pages is never
    told it can link to one."""
    pages = "\n".join(f"- {slug}: {what}" for slug, what in _WHAT.items())
    return (
        "\n\nApp pages: when the answer is about something one of these "
        "pages shows, you may end with ONE marker on its own line, "
        "[[open:<page>]] or [[open:<page>/<tab>]], and the reader gets a "
        "button that opens it. Never write the marker in any other form, "
        "never more than one, and skip it when no page genuinely helps.\n"
        f"{pages}"
    )
