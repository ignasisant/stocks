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
    "portfolio": ("overview", "positions", "risk", "projection", "tax",
                  "dividends", "fees"),
    "review": (),
    "import": (),
    "ticker": (),
    "sentiment": ("indices", "gauges", "rates", "inflation", "rotation",
                  "factors", "cross"),
    "sector": (),
    "earnings": (),
    "profile": ("prefs", "iv", "watch", "notify"),
}

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
                 "(style ratios), cross (other asset classes)",
    "sector": "sector screen and peers",
    "earnings": "the earnings calendar",
    "profile": "account settings. Tabs: prefs (preferences), iv (investor "
               "profile), watch (watchlist), notify (alerts and Telegram)",
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
    client declared `navigate` — a surface with no pages (Telegram) is never
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
