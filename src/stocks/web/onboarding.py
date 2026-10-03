"""Guided tour and per-release "what's new", both driven by one step registry.

The registry is data, and this module draws nothing: `api/routes/onboarding.py`
and `api/routes/guide.py` serve it, and the React shell renders it as the tour,
the "what's new" modal and the assistant-led walkthrough.

* **Steps** walk a new account through the app one feature at a time, in the
  order the work flows. For the connectable ones (ledger import, AI key,
  Telegram, tax residence) a `done` predicate says whether this account has it
  switched on.
* **Releases** carry the changelog as data. Each item names the tour step it
  belongs to, so a new feature is announced and explained by the same copy.

Every predicate takes the account it answers for. The caller proved who that is
before reaching this module, so nothing here guesses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from stocks.config import load_watchlist
from stocks.portfolio.ledger import has_transactions
from stocks.web import auth

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


def _has_ledger(_prefs: dict, paths) -> bool:
    try:
        return has_transactions(paths.db)
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
    Step(
        id="daily",
        icon="tips_and_updates",
        page="",
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
    Step(
        id="assistant",
        icon="auto_awesome",
        session={"chat_panel_open": True},
        gated=True,
        done=_has_ai_key,
    ),
    Step(
        id="notify",
        icon="notifications",
        page="profile",
        session={"profile_tab": "notify"},
        gated=True,
        done=lambda prefs, _paths=None: bool(prefs.get("telegram_chat_id")),
    ),
    Step(
        id="investor",
        icon="person",
        page="profile",
        session={"profile_tab": "iv"},
        gated=True,
        done=lambda prefs, _paths=None: auth.profile_is_set(prefs),
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

    `carried` is the same rule for a feature that lives inside a step every
    deploy has but is itself only on some deploys: None for every deploy,
    otherwise asked each time the cards are dealt.
    """

    slug: str
    icon: str
    step: str | None = None
    carried: Callable[[], bool] | None = None

    def announced(self, steps: set[str]) -> bool:
        """Whether this deploy has the feature to send a reader to."""
        if self.step is not None and self.step not in steps:
            return False
        return self.carried is None or self.carried()


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
    """Whether this deploy serves the Claude connector, which needs the site's
    public URL to name itself to Claude (`connector/server.py`)."""
    from stocks.web.server import public_origin

    return public_origin() is not None


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
            News(slug="weekly", icon="calendar_view_week", step="notify"),
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
            # on the Profile card, so the card hands over to that step; the
            # tools, the drawn view and the consent screen are the step's
            # body, not cards of their own.
            News(slug="claude", icon="hub", step="prefs", carried=_connector_open),
        ),
    ),
    Release(
        version="2026.10.1",
        date="2026-10",
        items=(
            # One card: the ledger could not be corrected anywhere but a wipe
            # and a re-import. The kinds of edit, the book check, Telegram's
            # typed yes and the transfers the import now recognises are the
            # assistant and import steps' bodies; Claude editing through the
            # connector is a sentence on the claude card, not a card.
            News(slug="fixbook", icon="build", step="assistant"),
        ),
    ),
)

CURRENT_VERSION = RELEASES[-1].version


# --------------------------------------------------------------- shared state
def _has_searched(prefs: dict) -> bool:
    """Whether this account has ever looked a ticker up in the top bar."""
    return bool(prefs.get("recent_searches"))


def _has_asked(_prefs: dict, paths) -> bool:
    """Whether any conversation with the assistant has a turn in it."""
    try:
        book = auth.load_book(paths.chat)
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
        return paths.watchlist.read_text() != auth.STARTER_WATCHLIST
    except OSError:
        return False


def explore_state(prefs: dict, paths) -> dict[str, bool]:
    """Which of the no-setup-required things this account has actually tried.

    Separate from `setup_state`: those four are capabilities to switch on, and
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
        "ai": _has_ai_key(prefs, paths),
        "telegram": bool(prefs.get("telegram_chat_id")),
    }


def visible_steps() -> tuple[Step, ...]:
    """The steps this deploy serves.

    Every step ships on every deploy today, so this is the whole registry.
    The indirection stays because the tour indexes through it: a step that
    only some deploys carry is filtered here, once, rather than at each call
    site.
    """
    return STEPS


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
