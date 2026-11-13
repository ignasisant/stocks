"""Guided tour and per-release "what's new", both driven by one step registry.

The registry is data, and this module draws nothing: `api/routes/onboarding.py`
and `api/routes/guide.py` serve it, and the React shell renders it as the tour,
the "what's new" modal and the assistant-led walkthrough.

* **Steps** walk a new account through the app one feature at a time, in the
  order the work flows. Started plainly, the tour walks only the `core` ones
  (`CORE_STEPS_MAX` at most); the rest are reached from its last stop, from a
  "what's new" card or by `?tour=<id>`. For the connectable ones (ledger import, AI key,
  notifications, tax residence) a `done` predicate says whether this account has it
  switched on.
* **Releases** carry the changelog as data. Each item names the tour step it
  belongs to, so a new feature is announced and explained by the same copy.

Every predicate takes the account it answers for. The caller proved who that is
before reaching this module, so nothing here guesses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from stocks import accounts, userprefs
from stocks.chat import conversations
from stocks.config import load_watchlist
from stocks.notify import mail, webpush
from stocks.portfolio import demo

# ------------------------------------------------------------- prefs / state
# prefs.json keys. `tour_seen_version` is the newest RELEASES version this
# account has been shown; `tour_done` is set once the tour is finished or
# exited, which is what stops it auto-opening on later sessions.
PREF_SEEN_VERSION = "tour_seen_version"
PREF_DONE = "tour_done"


@dataclass(frozen=True)
class Step:
    """One stop on the tour.

    Copy comes from the catalog by convention — `tour.<id>_title`,
    `tour.<id>_body`, and an optional `tour.<id>_cta` overriding the generic
    "take me there" label — so adding a step means adding a registry entry
    plus its keys in every locale, and nothing else.

    `page` is the URL path the step lands on ("" is Home, None is no page at
    all); `query` are query parameters to land with (the Portfolio tabs ride
    `?tab=`), and `session` is client state to seed on arrival (the Profile
    tabs and the assistant drawer).
    """

    id: str
    icon: str
    page: str | None = None
    query: dict[str, str] | None = None
    session: dict[str, object] = field(default_factory=dict)
    # Whether the step's target needs a signed-in account. Guests still read
    # the step; its button is disabled with a sign-in hint instead.
    gated: bool = False
    # Whether this account has the feature switched on, given its prefs and
    # paths. None for steps that are nothing to switch on (a page is a page).
    # Every surface goes through these same predicates: two implementations of
    # "has this account imported anything" is two answers to one question, and
    # the one on screen would be whichever surface the reader happened to open.
    done: Callable[[dict, object], bool] | None = None
    # One of the few stops the tour walks when it is simply started. The whole
    # registry was a twenty-stop walk nobody finished; these are the ones an
    # account needs to get going and to come back. The rest stay stops — a
    # "what's new" card lands on one, `?tour=<id>` opens one, and the last core
    # stop offers the full walk.
    core: bool = False


def _has_ledger(_prefs: dict, paths) -> bool:
    # Demo rows are for looking: seeding them is not an import, and reading
    # them as one ticked the import step and hid the start card's next move.
    try:
        return demo.has_real(paths.db)
    except Exception:
        return False  # unreadable/missing ledger reads as "nothing imported"


def _has_watchlist(_prefs: dict, paths) -> bool:
    """Whether this account follows anything yet.

    Reads the list rather than prefs: the watchlist is a YAML file, and it is
    filled by the Watchlist tab, the assistant and the focus examples alike —
    any of which should tick the step off.
    """
    try:
        return bool(load_watchlist(paths.watchlist))
    except Exception:
        return False  # unreadable/missing list reads as "nothing followed"


def _has_ai_key(prefs: dict, _paths=None) -> bool:
    """A BYOK provider key saved to prefs (encrypted).

    The keyless TopStocks free chain deliberately does not count: the step is
    about connecting your own provider, which is what lifts the daily cap.
    """
    return any(k.endswith("_key_enc") for k in prefs)


def _has_push(_prefs: dict, paths=None) -> bool:
    """At least one device of this account receives notifications (Web Push)."""
    if paths is None:
        return False
    try:
        return webpush.devices(paths.push) > 0
    except Exception:
        return False  # unreadable/missing subscriptions read as "none"


# The tour, in order. Sequenced as the work actually flows — get the ledger in,
# read what it derives, then the market tools, then the things that run without
# you (assistant, notifications) — rather than following the nav.
STEPS: tuple[Step, ...] = (
    Step(id="welcome", icon="waving_hand"),
    Step(
        id="import",
        icon="upload_file",
        page="import_transactions",
        gated=True,
        done=_has_ledger,
        core=True,
    ),
    Step(
        id="positions",
        icon="pie_chart",
        page="portfolio",
        query={"tab": "positions"},
    ),
    Step(
        id="risk",
        icon="show_chart",
        page="portfolio",
        query={"tab": "risk"},
    ),
    Step(
        id="projection",
        icon="trending_up",
        page="portfolio",
        query={"tab": "projection"},
    ),
    Step(
        id="tax",
        icon="receipt_long",
        page="portfolio",
        query={"tab": "tax"},
        done=lambda prefs, _paths=None: bool(prefs.get("tax_residence")),
    ),
    Step(
        id="income",
        icon="payments",
        page="portfolio",
        query={"tab": "dividends"},
    ),
    Step(id="review", icon="swap_vert", page="review", core=True),
    Step(
        id="daily",
        icon="tips_and_updates",
        page="",
        gated=True,
    ),
    Step(
        id="today",
        icon="wb_sunny",
        page="today",
        gated=True,
    ),
    Step(
        id="watchlist",
        icon="format_list_bulleted",
        page="profile",
        session={"profile_tab": "watch"},
        gated=True,
        done=_has_watchlist,
    ),
    Step(id="pulse", icon="speed", page="sentiment"),
    Step(id="market", icon="query_stats", page="ticker"),
    Step(id="sector", icon="donut_small", page="sector"),
    Step(id="learn", icon="school", page="learn"),
    Step(
        id="assistant",
        icon="auto_awesome",
        session={"chat_panel_open": True},
        gated=True,
        done=_has_ai_key,
        core=True,
    ),
    Step(
        id="journal",
        icon="history_edu",
        page="profile",
        session={"profile_tab": "journal"},
        gated=True,
    ),
    Step(
        id="notify",
        icon="notifications",
        page="profile",
        session={"profile_tab": "notify"},
        gated=True,
        done=_has_push,
        core=True,
    ),
    # Its own Profile tab: asking about the book from inside Claude, ChatGPT
    # or any other MCP app is somewhere the app could not be reached from at
    # all, and a card at the foot of Preferences was a place nobody went. The
    # id stays "claude", the app it first explained: the October card and
    # stored progress name it. Only where the deploy serves the connector
    # (`visible_steps`).
    Step(
        id="claude",
        icon="hub",
        page="profile",
        session={"profile_tab": "mcp"},
        gated=True,
    ),
    Step(
        id="investor",
        icon="person",
        page="profile",
        session={"profile_tab": "iv"},
        gated=True,
        done=lambda prefs, _paths=None: userprefs.profile_is_set(prefs),
    ),
    Step(
        id="plan",
        icon="flag",
        page="profile",
        session={"profile_tab": "plan"},
        gated=True,
        done=lambda prefs, _paths=None: _has_plan(prefs),
    ),
    Step(
        id="prefs",
        icon="tune",
        page="profile",
        session={"profile_tab": "prefs"},
        gated=True,
    ),
)


# ------------------------------------------------------------------ releases
@dataclass(frozen=True)
class News:
    """One shipped feature, as one card in the "what's new" modal.

    The modal interrupts someone who came to look at their portfolio, so a
    card has to be somewhere new to go: a new section, page or tab, a screen
    rebuilt under them, or something they could not do at all before. One
    more of a kind that already ships — another broker, another jurisdiction,
    another field — belongs in the existing step's `_body` copy and nowhere
    here. See the update-tutorial skill, which is where that call is made.

    Copy comes from the catalog by convention, keyed off the release version
    and this slug — `tour.news_<version with dots as underscores>_<slug>_title`
    and `_body` — so announcing a feature is one registry line plus its copy in
    every locale. `step` names the tour step that explains it, which is what
    turns an announcement into somewhere to go; a feature whose step this
    deploy does not carry is not announced at all (see `unseen_news`).
    `needs`, when set, is the same gate for a feature whose page ships on
    every deploy but which only works once configured.

    """

    slug: str
    icon: str
    step: str | None = None
    needs: Callable[[], bool] | None = None

    def announced(self, steps: set[str]) -> bool:
        """Whether this deploy has the feature to send a reader to."""
        if self.needs is not None and not self.needs():
            return False
        return self.step is None or self.step in steps


@dataclass(frozen=True)
class Release:
    """One shipped version, as the "what's new" modal pages through it.

    Versions are date-based (`YYYY.MM`) on purpose: the tour's notion of "new"
    is about what the user can see change, which has no relation to the package
    version in pyproject.toml. `items` are the features announced, one card
    each, in the order the modal shows them.
    """

    version: str
    date: str
    items: tuple[News, ...]


def _news_key(version: str, slug: str, part: str) -> str:
    return f"tour.news_{version.replace('.', '_')}_{slug}_{part}"


@dataclass(frozen=True)
class NewsCard:
    """A `News` bound to the release it shipped in — one card of the modal.

    Built by `unseen_news`, which is the only thing that decides how many
    cards an account is owed and in what order.
    """

    version: str
    date: str
    item: News

    @property
    def title_key(self) -> str:
        return _news_key(self.version, self.item.slug, "title")

    @property
    def body_key(self) -> str:
        return _news_key(self.version, self.item.slug, "body")


# Oldest first; the newest entry's version is what an account gets stamped
# with. Add to the end when a release ships — see the update-tutorial skill.
#
# A release is a handful of cards, not a list of the month's work: what a
# returning account has to page through is exactly what is written here. The
# three below were written before that rule and read like a changelog, three
# months of work card by card. They were cut back in September 2026 to the ones
# that are somewhere new to go, dropping the fixes, the polish and the
# "one more broker / jurisdiction / column" items. What those carried is in
# the step copy for their feature, where it is read on the way to the thing
# itself rather than in a card: the tax step names all twelve jurisdictions,
# the import step every broker it reads.
def _connector_open() -> bool:
    from stocks.web.server import connector_open

    return connector_open()


RELEASES: tuple[Release, ...] = (
    Release(
        version="2026.09",
        date="2026-09",
        items=(
            News(slug="tax", icon="receipt_long", step="tax"),
            News(slug="daily", icon="tips_and_updates", step="daily"),
            News(slug="fees", icon="percent", step="income"),
            News(slug="demo", icon="science", step="import"),
            News(slug="pulse", icon="speed", step="pulse"),
            News(slug="profile", icon="tune", step="prefs"),
            News(slug="watchlist", icon="playlist_add", step="watchlist"),
        ),
    ),
    Release(
        version="2026.09.1",
        date="2026-09",
        items=(
            News(slug="voice", icon="mic", step="assistant"),
        ),
    ),
    Release(
        version="2026.09.2",
        date="2026-09",
        items=(
            News(slug="splitfix", icon="call_split", step="import"),
            News(slug="transfers", icon="swap_horiz", step="import"),
            News(slug="sectors", icon="donut_small", step="sector"),
        ),
    ),
    Release(
        version="2026.09.3",
        date="2026-09",
        items=(
            # One card for eight rebuilt screens, not eight cards: to the
            # reader this is one thing — the app looks different. No step:
            # there is no one place to send them, they are already standing
            # in it. The card says where the previous version went.
            News(slug="newapp", icon="rocket_launch"),
        ),
    ),
    Release(
        version="2026.09.4",
        date="2026-09",
        items=(
            News(slug="sector_tech", icon="donut_small", step="sector"),
            News(slug="projection", icon="trending_up", step="projection"),
        ),
    ),
    Release(
        version="2026.09.5",
        date="2026-09",
        items=(
            # One card: each line's analysis is the new thing to do. The card's memory
            # and its new triggers (rate decisions, the tax calendar, results)
            # are the daily step's body, not cards of their own.
            News(slug="daily_more", icon="tips_and_updates", step="daily"),
        ),
    ),
    Release(
        version="2026.09.6",
        date="2026-09",
        items=(
            # A screen rebuilt under the reader: the importer they knew is now
            # four numbered steps with the book in a rail beside them. Nothing
            # it does is new, so no step of its own — the import step's card.
            News(slug="import", icon="upload_file", step="import"),
        ),
    ),
    Release(
        version="2026.09.7",
        date="2026-09",
        items=(
            # One card: a sale simulated through the tax engine is something
            # the app could not do anywhere before. The rest of that change —
            # actions that wait for Confirm, the bull/bear debate, page links
            # under an answer — is the assistant step's body, not cards.
            News(slug="whatif", icon="calculate", step="assistant"),
        ),
    ),
    Release(
        version="2026.10",
        date="2026-10",
        items=(
            # One card: an assistant that carries what the reader told it from
            # one conversation to the next is something it could not do at all.
            # How it learns (asked or in passing), the Undo under the answer,
            # earlier threads brought back and the list in Settings are one
            # capability — the assistant step's body, not cards of their own.
            News(slug="memory", icon="psychology", step="assistant"),
            # One card: a question answered every morning before it is typed
            # is something the card could not do, and the card itself was
            # rebuilt under the reader (Portfolio, alerts, worth a look,
            # routines). The sections and the chart are the daily step's body.
            News(slug="routines", icon="tips_and_updates", step="daily"),
            # One card: reading the book from inside Claude is somewhere the
            # app could not be reached from at all. It is set up and revoked
            # on Profile's Claude tab, so the card hands over to that step; the
            # tools, the drawn view and the consent screen are the step's
            # body, not cards of their own.
            News(slug="claude", icon="hub", step="claude"),
        ),
    ),
    Release(
        version="2026.10.1",
        date="2026-10",
        items=(
            # One card: the ledger could not be corrected anywhere but a wipe
            # and a re-import. The kinds of edit, the book check, the
            # chat's typed yes and the transfers the import now recognises are the
            # assistant and import steps' bodies; Claude editing through the
            # connector is a sentence on the claude card, not a card.
            News(slug="fixbook", icon="build", step="assistant"),
        ),
    ),
    Release(
        version="2026.10.2",
        date="2026-10",
        items=(
            # One card: Home was rebuilt under the reader — its order is now
            # theirs to set, and it opens on the market. The Market strip and
            # the four cards brought over from Portfolio and the Pulse are what
            # the editor offers, so they are this card's body, not cards of
            # their own; the daily step is Home's tour stop.
            News(slug="home", icon="dashboard_customize", step="daily"),
            # One card: the daily card was rebuilt around the reader's brief —
            # what they write decides its sections, edited from the card's own
            # pencil. The sources a line can draw on (events, insiders, exits,
            # indices) are the daily step's body, not cards of their own.
            News(slug="brief", icon="edit_note", step="daily"),
        ),
    ),
    Release(
        version="2026.10.3",
        date="2026-10",
        items=(
            # One card: a coin's page was rebuilt around what a coin is read
            # by — its peak, its cycle, the leverage on it, the reader's own
            # holding. The cells and markers inside those cards are this
            # card's body and the market step's, not cards of their own.
            News(slug="crypto", icon="currency_bitcoin", step="market"),
        ),
    ),
    Release(
        version="2026.10.4",
        date="2026-10",
        items=(
            # One card: a share's page gained a section of its own — what the
            # sell side says, where it puts the price and which way it is
            # revising earnings. The blocks inside it are this card's body and
            # the market step's, not cards of their own.
            News(slug="analysts", icon="query_stats", step="market"),
        ),
    ),
    Release(
        version="2026.10.5",
        date="2026-10",
        items=(
            # A page of its own: the book judged name by name, and outside
            # names weighed beside it. The map, the tax and the typed tickers
            # are this card's body, not cards of their own.
            News(slug="review", icon="swap_vert", step="review"),
        ),
    ),
    Release(
        version="2026.10.6",
        date="2026-10",
        items=(
            # A tab of its own: what the app proposed, kept with its figures
            # and its fate. The ticker header's chip and the chat tool read
            # the same record and are this card's step body, not cards.
            News(slug="journal", icon="history_edu", step="journal"),
            # A page of its own: the day's alerts, news, insiders, comparisons
            # and the market read. Home's briefing card is now its teaser,
            # which is this card's step body, not a card.
            News(slug="today", icon="wb_sunny", step="today"),
        ),
    ),
    Release(
        version="2026.10.7",
        date="2026-10",
        items=(
            # Something the ticker page could not do at all: one listing over
            # the indices, its sector or a rival, in the reader's money. More
            # names or ranges on the card are its step body, not cards.
            News(slug="compare", icon="show_chart", step="market"),
        ),
    ),
    Release(
        version="2026.10.8",
        date="2026-10",
        items=(
            # Something the reader could not do at all: write down, per
            # holding, where they would sell — and have the daily card hold
            # them to it. The panel, the chat card and the card's lines are
            # this card's step body, not cards of their own.
            News(slug="criteria", icon="flag", step="journal"),
        ),
    ),
    Release(
        version="2026.10.9",
        date="2026-10",
        items=(
            # A screen rebuilt under the user: the statement preview in the
            # chat (counts, touch rows with an inline fix, "Open wide" on a
            # computer). The phone header and the failed-turn notice are
            # sentences in the assistant's app-features section, not cards.
            News(slug="chatimport", icon="upload_file", step="assistant"),
        ),
    ),
    Release(
        version="2026.10.10",
        date="2026-10",
        items=(
            # Somewhere new to go: the Learn page, paths of lessons and a
            # glossary, open to a guest.
            News(slug="learn", icon="school", step="learn"),
            # Something they could not see at all before: who is short a
            # share (the EU registers' named holders, FINRA short volume,
            # short interest). The positioning tab, options figures, rating
            # changes and coin on-chain cards are one more of a kind on pages
            # that already have a step: sentences in app-features, no cards.
            News(slug="shorts", icon="trending_down", step="market"),
        ),
    ),
    Release(
        version="2026.10.11",
        date="2026-10",
        items=(
            # Somewhere new to go: the Profile "My plan" tab. Review obeying
            # it (caps, mix notes, new money sized to the contribution) is
            # what the plan does, so it rides on this card, not one of its own.
            News(slug="plan", icon="flag", step="plan"),
            # A capability there was none of: the app reaching a device when
            # an answer is done. Lives on the Notifications tab, so it rides
            # on the notify step rather than a step of its own.
            News(slug="push", icon="notifications_active", step="notify"),
        ),
    ),
    Release(
        version="2026.10.12",
        date="2026-10",
        items=(
            # A capability there was none of: choosing when the daily summary
            # goes out (a time of one's own or the US close), each one kept as
            # a conversation under "Scheduled" in the chat. Rides on the notify
            # step, whose tab links to where the times are set.
            News(slug="scheduled", icon="schedule", step="notify"),
        ),
    ),
    Release(
        version="2026.11",
        date="2026-11",
        items=(
            # A capability there was none of: an answer sent out as a link
            # (amounts hidden by default) that opens the app with the chat on
            # it, for a guest too. Lives in the chat, so it rides on the
            # assistant step.
            News(slug="share", icon="share", step="assistant"),
        ),
    ),
    Release(
        version="2026.11.1",
        date="2026-11",
        items=(
            # A channel there was none of: the week by email on Fridays, to
            # every account with an import and no device needed. It arrives
            # unasked, so the card says where it is switched off: the notify
            # step's tab, which holds the Email card. Held back until the
            # deploy can send: a card for mail that never comes is a promise.
            News(
                slug="email", icon="mail", step="notify", needs=lambda: mail.configured()
            ),
        ),
    ),
    Release(
        version="2026.11.2",
        date="2026-11",
        items=(
            # A line there was none of: what a buy or an add has to meet, held
            # against every move Review proposes and counted on a company's
            # page. It is a block of the plan tab, so it rides on that step.
            # The per-name buy rules beside it are one more kind of the exit
            # rules the journal already holds: a word in its step, no card.
            News(slug="entry", icon="checklist", step="plan"),
        ),
    ),
    Release(
        version="2026.11.3",
        date="2026-11",
        items=(
            # A screen rebuilt under the reader: a company's page now opens
            # on the read (six answers, each a link to its card) under a
            # pinned strip of section tabs, so where things sit has moved.
            # The rest of the rebuild (opinions side by side, rivals filled
            # in, Compare from the book's first day) is a sentence in the
            # market step's knowledge, no card of its own.
            News(slug="ticker", icon="query_stats", step="market"),
            # Sell or add rebuilt: the plan says the moves in one line, the
            # table groups by verdict with the holds folded, a chip per
            # verdict picks names out, and the near misses get a card.
            News(slug="review", icon="swap_vert", step="review"),
            # Sectors rebuilt: chips with each scan's age and the reader's
            # weight replace the select, the reader's own names are placed
            # in the ranking, and ticked rows go to Sell or add together.
            News(slug="sector", icon="donut_small", step="sector"),
        ),
    ),
)

CURRENT_VERSION = RELEASES[-1].version

#: The short walk stays short: a fifth core stop is the long tour coming back.
CORE_STEPS_MAX = 4


# --------------------------------------------------------------- shared state
def _has_searched(prefs: dict) -> bool:
    """Whether this account has ever looked a ticker up in the top bar."""
    return bool(prefs.get("recent_searches"))


def _has_asked(_prefs: dict, paths) -> bool:
    """Whether any conversation with the assistant has a turn in it."""
    try:
        book = conversations.load_book(paths.chat)
    except Exception:
        return False
    return any(c.get("messages") for c in book.get("conversations", []))


def _watchlist_is_own(_prefs: dict, paths) -> bool:
    """Whether the watchlist has been touched since it was seeded.

    Compared against the seed text rather than tracked with a flag, so it is
    also true for the accounts that predate this and for one restored from the
    bucket. An account that edits its way back to the exact seed reads as
    untouched, which is a shrug, not a bug.
    """
    try:
        return paths.watchlist.read_text() != accounts.STARTER_WATCHLIST
    except OSError:
        return False


def explore_state(prefs: dict, paths) -> dict[str, bool]:
    """Which of the no-setup-required things this account has actually tried.

    Separate from `setup_state`: those are capabilities to switch on, and
    an account with none of them connected can still do all three of these
    right now — the search, the assistant's free chain and the watchlist
    editor need no key, no import and no statement. On a first visit they are
    the shortest path from "signed in" to "this is useful", which is exactly
    what a checklist of things still to connect fails to say.
    """
    return {
        "search": _has_searched(prefs),
        "ask": _has_asked(prefs, paths),
        "watchlist": _watchlist_is_own(prefs, paths),
    }


def _has_plan(prefs: dict) -> bool:
    """Saved once, by the form or the chat's plan builder."""
    return bool((prefs.get("investor_plan") or {}).get("set"))


def setup_state(prefs: dict, paths, *, signed_in: bool) -> dict[str, bool]:
    """Which connectable capabilities this account has switched on.

    One source of truth for the Home setup card and the tour's per-step
    badges — they used to compute this twice and could disagree. A guest's
    ledger is never read: the guest data dir is shared by every anonymous
    visitor, so whatever sits there is nobody's import.
    """
    return {
        "login": signed_in,
        "import": _has_ledger(prefs, paths) if signed_in else False,
        "plan": _has_plan(prefs) if signed_in else False,
        "ai": _has_ai_key(prefs, paths),
        "notify": _has_push(prefs, paths) if signed_in else False,
    }


@dataclass(frozen=True)
class Gap:
    """One thing this account has not set up, with the page that sets it.

    Copy is `email.gap_<key>` (filled with `args`, real counts from the book)
    and `email.gap_<key>_cta`; `page`/`query` are the app path the button
    opens (`notify.links.page_url`).
    """

    key: str
    page: str
    query: dict[str, str] = field(default_factory=dict)
    args: dict[str, str] = field(default_factory=dict)


#: A ledger whose newest row is older than this reads as not kept up to date.
STALE_LEDGER_DAYS = 30
GAPS_SHOWN = 4


def account_gaps(
    prefs: dict,
    paths,
    *,
    email: str | None = None,
    held: set[str] | None = None,
    unpriced: list[str] | tuple[str, ...] = (),
    today=None,
    lang: str = "en",
) -> list[Gap]:
    """What this account has not configured yet, most consequential first.

    First what makes its own figures wrong (records to fix, names without a
    price, a ledger left behind), then what it is missing out on. At most
    `GAPS_SHOWN`; empty when nothing is missing. Each check fails alone and
    reads as "nothing missing" — a broken check must not nag.

    `held` and `unpriced` come from the caller's book when it has one (the
    weekly email already replayed it); `held` is read here otherwise.
    """
    from datetime import date

    today = today or date.today()
    gaps: list[Gap] = []

    def check(fn) -> None:
        try:
            gap = fn()
        except Exception:  # noqa: BLE001 — one check, one silent miss
            return
        if gap is not None:
            gaps.append(gap)

    rows: list = []
    try:
        from stocks.portfolio.ledger import all_transactions

        rows = demo.without(all_transactions(paths.db))
    except Exception:  # noqa: BLE001 — unreadable ledger reads as empty
        rows = []

    def fixes() -> Gap | None:
        from stocks import loaders
        from stocks.api.routes.import_statement.book_checkup import _FIXABLE
        from stocks.portfolio import doctor
        from stocks.portfolio import held as held_sales

        if not rows:
            return None
        n = len(held_sales.ready(paths.db)) + len(held_sales.reuploads(rows, paths.db))
        n += sum(
            1 for f in doctor.scan(rows, resolve=loaders.display_symbol)
            if f.kind in _FIXABLE and f.fix
        )
        return Gap("fixes", "import_transactions", args={"n": str(n)}) if n else None

    def prices() -> Gap | None:
        if not unpriced:
            return None
        return Gap("unpriced", "ticker", {"ticker": unpriced[0]},
                   {"names": ", ".join(unpriced)})

    def stale() -> Gap | None:
        if not rows:
            return None
        newest = max(date.fromisoformat(r.date[:10]) for r in rows)
        if (today - newest).days <= STALE_LEDGER_DAYS:
            return None
        from stocks.notify.render import date_line

        return Gap("stale", "import_transactions",
                   args={"date": date_line(newest, lang)})

    def plan() -> Gap | None:
        return None if _has_plan(prefs) else Gap("plan", "profile", {"tab": "plan"})

    def rules() -> Gap | None:
        from stocks.chat import journal

        names = held
        if names is None:
            from stocks.views.briefing import held_symbols

            names = held_symbols(paths)
        if not names:
            return None
        live = journal.criteria(journal.load(paths.journal), side="exit")
        ruled = {e.ticker.upper() for e in live}
        bare = sorted(t for t in names if t.upper() not in ruled)
        if not bare:
            return None
        return Gap("rules", "portfolio", {"tab": "positions"},
                   {"n": str(len(bare)), "total": str(len(names))})

    def push() -> Gap | None:
        if _has_push(prefs, paths):
            return None
        return Gap("push", "profile", {"tab": "notify"})

    def tax() -> Gap | None:
        if prefs.get("tax_residence"):
            return None
        return Gap("tax", "portfolio", {"tab": "tax"})

    def investor() -> Gap | None:
        if (prefs.get("investor_profile") or {}).get("set"):
            return None
        return Gap("investor", "profile", {"tab": "iv"})

    def connector() -> Gap | None:
        if not email or not _connector_open():
            return None
        from stocks.connector import store

        if store.ledger().grants_for(email):
            return None
        return Gap("claude", "profile", {"tab": "mcp"})

    for fn in (fixes, prices, stale, plan, rules, push, tax, investor, connector):
        if len(gaps) >= GAPS_SHOWN:
            break
        check(fn)
    return gaps


def visible_steps() -> tuple[Step, ...]:
    """The steps this deploy serves.

    Every step ships on every deploy but `claude`, which needs the connector
    (`_connector_open`). Filtered here, once, rather than at each call site —
    and a "what's new" card pointing at a step this drops is dropped with it.
    """
    if _connector_open():
        return STEPS
    return tuple(s for s in STEPS if s.id != "claude")


def by_id(step_id: str) -> Step | None:
    return next((s for s in STEPS if s.id == step_id), None)


def unseen_releases(prefs: dict) -> tuple[Release, ...]:
    """Releases newer than the version this account was last shown.

    Compared by position in RELEASES, not by parsing the version string: the
    list is the ordering, and an unknown stamp (a downgrade, a hand-edited
    prefs.json) reads as "show everything" rather than crashing.
    """
    seen = prefs.get(PREF_SEEN_VERSION)
    versions = [r.version for r in RELEASES]
    if seen not in versions:
        return RELEASES
    return RELEASES[versions.index(seen) + 1 :]


def unseen_news(prefs: dict) -> tuple[NewsCard, ...]:
    """Every feature shipped since this account's stamp, newest first.

    The modal pages through these one card at a time, so how much a returning
    account reads is simply how much shipped while it was away — one card for
    one feature, nine for three releases missed — instead of one wall of
    bullets that grows silently with every version.

    A card whose step is not in `visible_steps()` is dropped: a deploy that
    does not carry the feature must not announce it. A card with no step at
    all (something with no tour stop of its own) is always shown.
    """
    shown = {s.id for s in visible_steps()}
    return tuple(
        NewsCard(version=rel.version, date=rel.date, item=item)
        for rel in reversed(unseen_releases(prefs))
        for item in rel.items
        if item.announced(shown)
    )
