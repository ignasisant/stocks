"""Guided tour and per-release "what's new", both driven by one step registry.

Two surfaces over the same data:

* the **tour** — a modal that walks a new account through the app one feature
  at a time, and for the connectable ones (ledger import, AI key, Telegram,
  tax residence) says whether this account has it switched on and takes the
  user to the page where it is switched on.
* **what's new** — the same modal in a different mode, listing the releases
  the account has not seen yet. `RELEASES` carries the changelog as data and
  each entry names the tour steps its items belong to, so a new feature is
  announced and explained by the same copy.

Three design points worth knowing before editing this:

1. **One dialog per script run.** Streamlit allows exactly one open modal, so
   this module and `auth.maybe_prompt_profile()` cannot both fire on the same
   run. app.py gives the tour priority (`maybe_open()` returns True when it
   claims the run) — the investor profile is a tour step anyway.
2. **Navigating closes the modal.** `st.switch_page` ends the run, and a modal
   cannot survive it. So "take me there" does not try to stay open: it queues
   the step (`_GOTO`), the next full run navigates, and the tour reappears as a
   thin *resume strip* above the page body. That strip — not the modal — is
   what makes "go and look at it" work at all.
3. **A dialog is a fragment.** Back/Next are `on_click` callbacks so they rerun
   only the modal; the buttons that must leave it (take me there, finish, exit)
   call `st.rerun()` for a full-app rerun, which is what lets app.py act on the
   queued step.

Progress lives in prefs.json for signed-in accounts and in session state for
guests: the guest data dir is shared by every anonymous visitor, so writing a
guest's tour progress there would hand it to the next stranger.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import streamlit as st

from stocks import obs
from stocks.config import load_watchlist
from stocks.portfolio.ledger import has_transactions
from stocks.web import auth, i18n
from stocks.web.i18n import t as tr

# ------------------------------------------------------------- prefs / state
# prefs.json keys. `tour_seen_version` is the newest RELEASES version this
# account has been shown; `tour_done` is set once the tour is finished or
# exited, which is what stops it auto-opening on later sessions.
PREF_SEEN_VERSION = "tour_seen_version"
PREF_DONE = "tour_done"

# Session keys. The modal is kept open by _OPEN rather than by the run that
# opened it: every full rerun in this app (top-bar search, chat panel, page
# nav) would otherwise drop it mid-step.
_OPEN = "_tour_open"  # modal renders this run
_MODE = "_tour_mode"  # "tour" | "news"
_STEP = "_tour_step"  # index into visible_steps()
_NEWS = "_tour_news"  # index into unseen_news()
_GOTO = "_tour_goto"  # step id queued for navigation on the next full run
_RESUME = "_tour_resume"  # tour minimized: show the resume strip
_SEEN = "_tour_auto_seen"  # auto-open evaluated once per session


@dataclass(frozen=True)
class Step:
    """One stop on the tour.

    Copy comes from the catalog by convention — `tour.<id>_title`,
    `tour.<id>_body`, and an optional `tour.<id>_cta` overriding the generic
    "take me there" label — so adding a step means adding a registry entry
    plus its keys in every locale, and nothing else.

    `page` is the module path `st.navigation` knows the page by; `query` are
    query parameters to land with (the Portfolio tabs ride `?tab=`), `session`
    is state to seed before navigating (the Profile tabs and the assistant
    panel are session-driven), and `reset_keys` are widget-state keys to drop
    so a `default=` can take effect again on a page the user is already on.
    """

    id: str
    icon: str
    page: str | None = None
    query: dict[str, str] | None = None
    session: dict[str, object] = field(default_factory=dict)
    reset_keys: tuple[str, ...] = ()
    # Whether the step's target sits behind require_login(). Guests still read
    # the step; its button is disabled with a sign-in hint instead.
    gated: bool = False
    # Whether this account has the feature switched on, given prefs. None for
    # steps that are nothing to switch on (a page is a page).
    done: Callable[[dict], bool] | None = None


def _has_ledger(_prefs: dict) -> bool:
    try:
        return has_transactions(auth.db_path())
    except Exception:
        return False  # unreadable/missing ledger reads as "nothing imported"


def _has_watchlist(_prefs: dict) -> bool:
    """Whether this account follows anything yet.

    Reads the list rather than prefs: the watchlist is a YAML file, and it is
    filled by the Watchlist tab, the assistant and the focus examples alike —
    any of which should tick the step off.
    """
    try:
        return bool(load_watchlist(auth.watchlist_path()))
    except Exception:
        return False  # unreadable/missing list reads as "nothing followed"


def _has_ai_key(prefs: dict) -> bool:
    """A BYOK provider key saved to prefs (encrypted) or entered this session.

    The keyless TopStocks free chain deliberately does not count: the step is
    about connecting your own provider, which is what lifts the daily cap.
    """
    return any(k.endswith("_key_enc") for k in prefs) or any(
        k.startswith("llm_key::") and st.session_state[k] for k in st.session_state
    )


# The tour, in order. Sequenced as the work actually flows — get the ledger in,
# read what it derives, then the market tools, then the things that run without
# you (assistant, notifications) — rather than following the nav.
STEPS: tuple[Step, ...] = (
    Step(id="welcome", icon="waving_hand"),
    Step(
        id="import",
        icon="upload_file",
        page="app_pages/import_transactions.py",
        gated=True,
        done=_has_ledger,
    ),
    Step(
        id="positions",
        icon="pie_chart",
        page="app_pages/portfolio.py",
        query={"tab": "positions"},
        reset_keys=("portfolio_tab",),
    ),
    Step(
        id="risk",
        icon="show_chart",
        page="app_pages/portfolio.py",
        query={"tab": "risk"},
        reset_keys=("portfolio_tab",),
    ),
    Step(
        id="tax",
        icon="receipt_long",
        page="app_pages/portfolio.py",
        query={"tab": "tax"},
        reset_keys=("portfolio_tab",),
        done=lambda prefs: bool(prefs.get("tax_residence")),
    ),
    Step(
        id="income",
        icon="payments",
        page="app_pages/portfolio.py",
        query={"tab": "dividends"},
        reset_keys=("portfolio_tab",),
    ),
    Step(
        id="daily",
        icon="tips_and_updates",
        page="app_pages/home.py",
        gated=True,
    ),
    Step(
        id="watchlist",
        icon="format_list_bulleted",
        page="app_pages/profile.py",
        session={"profile_tab": "watch"},
        gated=True,
        done=_has_watchlist,
    ),
    Step(id="pulse", icon="speed", page="app_pages/sentiment.py"),
    Step(id="market", icon="query_stats", page="app_pages/ticker.py"),
    Step(id="screener", icon="filter_alt", page="app_pages/screener.py"),
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
        page="app_pages/profile.py",
        session={"profile_tab": "notify"},
        gated=True,
        done=lambda prefs: bool(prefs.get("telegram_chat_id")),
    ),
    Step(
        id="investor",
        icon="person",
        page="app_pages/profile.py",
        session={"profile_tab": "iv"},
        gated=True,
        done=auth.profile_is_set,
    ),
    Step(
        id="prefs",
        icon="tune",
        page="app_pages/profile.py",
        session={"profile_tab": "prefs"},
        gated=True,
    ),
)


# ------------------------------------------------------------------ releases
@dataclass(frozen=True)
class News:
    """One shipped feature, as one card in the "what's new" modal.

    Copy comes from the catalog by convention, keyed off the release version
    and this slug — `tour.news_<version with dots as underscores>_<slug>_title`
    and `_body` — so announcing a feature is one registry line plus its copy in
    every locale. `step` names the tour step that explains it, which is what
    turns an announcement into somewhere to go; a feature whose step this
    deploy does not carry is not announced at all (see `unseen_news`).
    """

    slug: str
    icon: str
    step: str | None = None


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
RELEASES: tuple[Release, ...] = (
    Release(
        version="2026.09",
        date="2026-09",
        items=(
            News(slug="tax", icon="receipt_long", step="tax"),
            News(slug="daily", icon="tips_and_updates", step="daily"),
            News(slug="chat", icon="auto_awesome", step="assistant"),
            News(slug="askai", icon="smart_toy", step="market"),
            News(slug="fees", icon="percent", step="income"),
            News(slug="demo", icon="science", step="import"),
            News(slug="guest", icon="lock_open", step="positions"),
            News(slug="pulse", icon="speed", step="pulse"),
            News(slug="profile", icon="tune", step="prefs"),
            News(slug="digest", icon="insights", step="notify"),
            News(slug="digestcal", icon="event_available", step="notify"),
            News(slug="digestlinks", icon="link", step="notify"),
            News(slug="weekly", icon="calendar_view_week", step="notify"),
            News(slug="watchlist", icon="playlist_add", step="watchlist"),
        ),
    ),
    Release(
        version="2026.09.1",
        date="2026-09",
        items=(
            News(slug="tips", icon="info", step="pulse"),
            News(slug="voice", icon="mic", step="assistant"),
        ),
    ),
)

CURRENT_VERSION = RELEASES[-1].version


# --------------------------------------------------------------- shared state
def _has_searched(prefs: dict) -> bool:
    """Whether this account has ever looked a ticker up in the top bar."""
    return bool(prefs.get("recent_searches"))


def _has_asked(_prefs: dict) -> bool:
    """Whether any conversation with the assistant has a turn in it."""
    try:
        book = auth.load_book()
    except Exception:
        return False
    return any(c.get("messages") for c in book.get("conversations", []))


def _watchlist_is_own(_prefs: dict) -> bool:
    """Whether the watchlist has been touched since it was seeded.

    Compared against the seed text rather than tracked with a flag, so it is
    also true for the accounts that predate this and for one restored from the
    bucket. An account that edits its way back to the exact seed reads as
    untouched, which is a shrug, not a bug.
    """
    try:
        return auth.watchlist_path().read_text() != auth.STARTER_WATCHLIST
    except OSError:
        return False


def explore_state(prefs: dict | None = None) -> dict[str, bool]:
    """Which of the no-setup-required things this account has actually tried.

    Separate from `setup_state`: those four are capabilities to switch on, and
    an account with none of them connected can still do all three of these
    right now — the search, the assistant's free chain and the watchlist
    editor need no key, no import and no statement. On a first visit they are
    the shortest path from "signed in" to "this is useful", which is exactly
    what a checklist of things still to connect fails to say.
    """
    p = prefs if prefs is not None else auth.load_prefs()
    return {
        "search": _has_searched(p),
        "ask": _has_asked(p),
        "watchlist": _watchlist_is_own(p),
    }


def setup_state(prefs: dict | None = None) -> dict[str, bool]:
    """Which connectable capabilities this account has switched on.

    One source of truth for the Home setup card and the tour's per-step
    badges — they used to compute this twice and could disagree.
    """
    p = prefs if prefs is not None else auth.load_prefs()
    return {
        "login": auth.is_logged_in(),
        "import": _has_ledger(p) if auth.is_logged_in() else False,
        "ai": _has_ai_key(p),
        "telegram": bool(p.get("telegram_chat_id")),
    }


def visible_steps() -> tuple[Step, ...]:
    """The steps this session may see.

    Every step ships on every deploy today, so this is the whole registry.
    The indirection stays because the tour renders and indexes through it:
    a step that only some deploys carry is filtered here, once, rather than
    at each call site.
    """
    return STEPS


def by_id(step_id: str) -> Step | None:
    return next((s for s in STEPS if s.id == step_id), None)


def unseen_releases(prefs: dict | None = None) -> tuple[Release, ...]:
    """Releases newer than the version this account was last shown.

    Compared by position in RELEASES, not by parsing the version string: the
    list is the ordering, and an unknown stamp (a downgrade, a hand-edited
    prefs.json) reads as "show everything" rather than crashing.
    """
    p = prefs if prefs is not None else auth.load_prefs()
    seen = p.get(PREF_SEEN_VERSION)
    versions = [r.version for r in RELEASES]
    if seen not in versions:
        return RELEASES
    return RELEASES[versions.index(seen) + 1 :]


def unseen_news(prefs: dict | None = None) -> tuple[NewsCard, ...]:
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
        if item.step is None or item.step in shown
    )


def _save(prefs: dict) -> None:
    """Persist prefs — for signed-in accounts only.

    A guest's paths point at the shared guest dir, so writing there would give
    the next anonymous visitor this one's tour progress. Guests keep everything
    in session state, which dies with the tab.
    """
    if auth.is_logged_in():
        auth.save_prefs(prefs)


# -------------------------------------------------------------- open / close
def open_tour(step_id: str | None = None) -> None:
    """Open the tour, at `step_id` when given (else where it was left off)."""
    steps = visible_steps()
    if step_id is not None:
        idx = next((i for i, s in enumerate(steps) if s.id == step_id), 0)
        st.session_state[_STEP] = idx
    st.session_state[_OPEN] = True
    st.session_state[_MODE] = "tour"
    st.session_state[_RESUME] = False


def open_news(index: int = 0) -> None:
    """Open "what's new" at `index` — the newest unseen feature by default."""
    st.session_state[_OPEN] = True
    st.session_state[_MODE] = "news"
    st.session_state[_NEWS] = index
    st.session_state[_RESUME] = False


def _consume_params() -> bool:
    """`?tour=1` (or `?tour=<step id>`) opens the tour, once per URL value.

    The parameter is deleted as it is read so a rerun doesn't reopen the modal
    the user just closed — same one-shot handling as the landing page's CTAs.
    """
    raw = str(st.query_params.get("tour") or "").strip().lower()
    if not raw:
        return False
    del st.query_params["tour"]
    if raw in {"1", "true", "yes"}:
        open_tour(step_id=visible_steps()[0].id)
        return True
    if by_id(raw) is not None:
        open_tour(step_id=raw)
        return True
    return False


def maybe_open() -> bool:
    """Auto-open on the session's first run; True when the tour owns the run.

    A brand-new signed-in account gets the tour; an account that has already
    finished it gets "what's new" when a release shipped since. Returns True
    whenever the tour is active — a modal open, or parked in the resume strip
    — which is what app.py uses to stand the investor-profile prompt down: two
    modals cannot share a run, and a nag over a walkthrough in progress is
    worse than a nag next session.

    Guests are never auto-opened: nothing is persisted for them, so it would
    pop on every new tab. They can still start it by hand.
    """
    # A modal the user asked for, one already open, or a tour parked on a page
    # the user was sent to. Each spends the session's one auto-open, so
    # "what's new" can never pop over the tour.
    if (
        _consume_params()
        or st.session_state.get(_OPEN)
        or st.session_state.get(_RESUME)
    ):
        st.session_state[_SEEN] = True
        return True
    if not auth.is_logged_in() or st.session_state.get(_SEEN):
        return False
    st.session_state[_SEEN] = True
    prefs = auth.load_prefs()
    if not prefs.get(PREF_DONE):
        open_tour(step_id=visible_steps()[0].id)
        return True
    # Asked over the release list, not the release stamp: a version whose
    # every feature this deploy filters out is nothing to announce, and an
    # empty modal is worse than no modal.
    if unseen_news(prefs):
        open_news()
        return True
    return False


def _minimize() -> None:
    """Dismissing the modal (X, ESC, click-outside) parks the tour in the
    strip instead of ending it — the tour is what the user came for."""
    st.session_state[_OPEN] = False
    st.session_state[_RESUME] = True


def _exit_tour(reason: str = "exit") -> None:
    """Close the tour for good, and record where it was left.

    The step the reader walked out on is the one piece of feedback the tour
    can give about itself: a step that most accounts abandon is either badly
    placed or badly written, and neither is visible from the code. `reason`
    separates the three ways out — finishing it is not the same signal as
    skipping from step two.
    """
    steps = visible_steps()
    idx = min(int(st.session_state.get(_STEP, 0)), len(steps) - 1)
    obs.event("tour.exit", reason=reason, step=steps[idx].id,
              index=idx + 1, of=len(steps))
    prefs = auth.load_prefs()
    prefs[PREF_DONE] = True
    # A first-timer who has just been walked through everything has no
    # "what's new" to catch up on, so stamp the current release too.
    prefs[PREF_SEEN_VERSION] = CURRENT_VERSION
    _save(prefs)
    st.session_state[_OPEN] = False
    st.session_state[_RESUME] = False


def _dismiss_news(reason: str = "dismissed") -> None:
    """Stamp the account as caught up, and close the list.

    Stamping here is what makes "what's new" a once-only surface: every way
    out of the modal — the last card's button, skipping the rest, the X — ends
    up in this function, and the stamp is the newest release rather than the
    card the reader stopped on. The one path that deliberately does *not*
    stamp is parking the list to go and look at a feature (`_news_strip`):
    a list abandoned half-read is still owed.

    `reason` separates reading it through from bailing on card one, which is
    the only feedback the modal can give about its own copy.
    """
    cards = unseen_news()
    idx = min(max(int(st.session_state.get(_NEWS, 0)), 0), max(len(cards) - 1, 0))
    obs.event("news.close", reason=reason, index=idx + 1, of=len(cards),
              version=CURRENT_VERSION)
    prefs = auth.load_prefs()
    prefs[PREF_SEEN_VERSION] = CURRENT_VERSION
    _save(prefs)
    st.session_state[_OPEN] = False
    st.session_state[_RESUME] = False


# ------------------------------------------------------------------ rendering
def render(page) -> bool:
    """The tour's visible half: the modal, or the resume strip.

    Call once from app.py after the topbar (which has to be the main column's
    first element to stay sticky) and before `page.run()`. Navigation is *not*
    done here — see `consume_goto`.

    Returns whether a *modal* went up (the resume strip does not count — it is
    one line in the page flow and blocks nothing). app.py skips the page while
    it is True: a dialog covers the viewport at every width, so the page behind
    it is invisible work that swallows the taps meant for the modal.
    """
    # The toast belongs to the run *after* the modal closed — one emitted
    # inside the dialog dies with the rerun that shuts it.
    if st.session_state.pop("_tour_finished", False):
        st.toast(tr("tour.finished"), icon=":material/check_circle:")
    if st.session_state.get(_OPEN):
        _render_modal()
        return True
    if st.session_state.get(_RESUME):
        _resume_strip()
    return False


def consume_goto(page) -> None:
    """Act on a step queued by "take me there" on the previous run.

    Split out of `render` and called early — right after `st.navigation`,
    before the topbar and the assistant panel — for two reasons: a step that
    switches pages ends the run, so anything rendered first is wasted work,
    and a step whose target is the panel itself (`session=` with no `page=`)
    has to seed its state *before* the panel renders or it would only open on
    the following interaction.
    """
    step = by_id(st.session_state.pop(_GOTO, "") or "")
    if step is None:
        return
    for key in step.reset_keys:
        st.session_state.pop(key, None)
    st.session_state.update(step.session)
    if step.page is None:
        return  # in-page target (the assistant panel) — nothing to navigate to
    if _url_path(step.page) != page.url_path:
        st.switch_page(step.page, query_params=step.query or None)
    elif step.query:
        # Already on the target page: the query parameter still has to move,
        # and the tab widget's stored state has to go for `default=` to win.
        st.query_params.update(step.query)


def _url_path(module: str) -> str:
    """The url_path st.navigation derives from a page module's filename."""
    stem = module.rsplit("/", 1)[-1].removesuffix(".py")
    return "" if stem == "home" else stem


def _render_modal() -> None:
    # Built at call time rather than with @st.dialog so the title resolves in
    # the run's active language instead of freezing at import — same as the
    # login, investor-profile and feedback modals.
    if st.session_state.get(_MODE) == "news":
        st.dialog(
            tr("tour.news_title"), width="medium", on_dismiss=_dismiss_news
        )(_news_body)()
        return
    # The title is fixed and the step number lives in the body on purpose: a
    # dialog is a fragment, so Back/Next re-execute only the body — anything
    # computed out here (title included) would still show the previous step.
    st.dialog(tr("tour.dialog_title"), width="medium", on_dismiss=_minimize)(
        _tour_body
    )()


def _cta_label(step: Step) -> str:
    key = f"tour.{step.id}_cta"
    return tr(key) if i18n.has(key) else tr("tour.goto")


def _step_back() -> None:
    st.session_state[_STEP] = max(int(st.session_state.get(_STEP, 0)) - 1, 0)


def _step_next() -> None:
    st.session_state[_STEP] = int(st.session_state.get(_STEP, 0)) + 1


def _current(steps: tuple[Step, ...]) -> int:
    """The step index, clamped and written back. Read inside the dialog body,
    never passed in: a fragment rerun re-executes the body with its *original*
    arguments, so a passed-in index would freeze on the first step shown."""
    idx = min(max(int(st.session_state.get(_STEP, 0)), 0), len(steps) - 1)
    st.session_state[_STEP] = idx
    return idx


def _tour_body() -> None:
    """One step: what it is, whether it is on, and the way to it.

    Back/Next are `on_click` callbacks — a dialog is a fragment, so they rerun
    the modal alone. The buttons that have to leave the modal call st.rerun()
    for a full-app rerun, which is the only thing that can navigate.
    """
    steps = visible_steps()
    idx = _current(steps)
    step = steps[idx]
    prefs = auth.load_prefs()
    signed_in = auth.is_logged_in()

    st.markdown(f":material/{step.icon}: **{tr(f'tour.{step.id}_title')}**")
    if step.done is not None:
        on = step.done(prefs)
        st.markdown(
            f":green-badge[:material/check: {tr('tour.active')}]"
            if on
            else f":gray-badge[{tr('tour.pending')}]"
        )
    st.markdown(tr(f"tour.{step.id}_body"))
    st.progress(
        (idx + 1) / len(steps),
        text=tr("tour.progress", n=idx + 1, total=len(steps)),
    )

    nav = st.container(horizontal=True, vertical_alignment="center")
    nav.button(
        tr("tour.back"),
        key="tour_back",
        icon=":material/chevron_left:",
        disabled=idx == 0,
        on_click=_step_back,
    )
    locked = step.gated and not signed_in
    if (step.page or step.session) and nav.button(
        _cta_label(step),
        key="tour_goto",
        type="secondary",
        icon=":material/open_in_new:",
        disabled=locked,
    ):
        st.session_state[_GOTO] = step.id
        _minimize()
        st.rerun()  # full run: closes the modal, consume_goto() navigates
    last = idx == len(steps) - 1
    if last:
        if nav.button(tr("tour.finish"), key="tour_finish", type="primary",
                      icon=":material/check:"):
            _exit_tour("finished")
            st.session_state["_tour_finished"] = True
            st.rerun()
    else:
        nav.button(
            tr("tour.next"),
            key="tour_next",
            type="primary",
            icon=":material/chevron_right:",
            on_click=_step_next,
        )
    if locked:
        st.caption(tr("tour.locked"))
    if not last and st.button(tr("tour.skip"), key="tour_skip", type="tertiary"):
        _exit_tour("skipped")
        st.rerun()


def _news_current(cards: tuple[NewsCard, ...]) -> int:
    """The card index, clamped and written back. Read inside the dialog body
    for the same reason as `_current`: a fragment rerun re-executes the body
    with its *original* arguments, so a passed-in index would freeze."""
    idx = min(max(int(st.session_state.get(_NEWS, 0)), 0), len(cards) - 1)
    st.session_state[_NEWS] = idx
    return idx


def _news_back() -> None:
    st.session_state[_NEWS] = max(int(st.session_state.get(_NEWS, 0)) - 1, 0)


def _news_next() -> None:
    st.session_state[_NEWS] = int(st.session_state.get(_NEWS, 0)) + 1


def _news_park(step_id: str) -> None:
    """Queue the feature's page and park the list in the strip.

    The modal cannot survive `st.switch_page` (design point 2), so a card's
    "take me there" hands the step to `consume_goto` and leaves the reader the
    strip — which still knows which card they were on, so the rest of the
    list survives the trip.
    """
    st.session_state[_GOTO] = step_id
    st.session_state[_OPEN] = False
    st.session_state[_RESUME] = True


def _news_body() -> None:
    """One shipped feature per card, newest first.

    Paged rather than listed, because the list is not a fixed length: an
    account that has been away for three releases gets the same cards as one
    that missed a single feature, just more of them, and each card carries the
    way into the tour step that explains it. Back/Next are `on_click`
    callbacks — a dialog is a fragment, so they rerun the modal alone; the
    buttons that have to leave it call `st.rerun()`.
    """
    cards = unseen_news()
    if not cards:
        # Nothing unseen: the modal was opened by hand, or the account was
        # stamped between runs. Show the last release rather than an empty
        # dialog.
        last = RELEASES[-1]
        cards = tuple(
            NewsCard(version=last.version, date=last.date, item=item)
            for item in last.items
        )
    idx = _news_current(cards)
    card = cards[idx]
    step = by_id(card.item.step or "")

    st.caption(tr("tour.news_intro"))
    st.markdown(
        f":material/{card.item.icon}: **{tr(card.title_key)}** "
        f":gray-badge[{card.date}]"
    )
    st.markdown(tr(card.body_key))
    st.progress(
        (idx + 1) / len(cards),
        text=tr("tour.news_progress", n=idx + 1, total=len(cards)),
    )

    nav = st.container(horizontal=True, vertical_alignment="center")
    nav.button(
        tr("tour.back"),
        key="tour_news_back",
        icon=":material/chevron_left:",
        disabled=idx == 0,
        on_click=_news_back,
    )
    locked = step is not None and step.gated and not auth.is_logged_in()
    if step is not None and nav.button(
        _cta_label(step),
        key="tour_news_goto",
        icon=":material/open_in_new:",
        disabled=locked,
    ):
        _news_park(step.id)
        st.rerun()  # full run: closes the modal, consume_goto() navigates
    last_card = idx == len(cards) - 1
    if last_card:
        if nav.button(tr("tour.close"), key="tour_news_close", type="primary",
                      icon=":material/check:"):
            _dismiss_news("read")
            st.rerun()
    else:
        nav.button(
            tr("tour.next"),
            key="tour_news_next",
            type="primary",
            icon=":material/chevron_right:",
            on_click=_news_next,
        )
    if locked:
        st.caption(tr("tour.locked"))

    foot = st.container(horizontal=True, vertical_alignment="center")
    if foot.button(tr("tour.full_tour"), key="tour_news_full", type="tertiary",
                   icon=":material/play_circle:"):
        _dismiss_news("full_tour")  # the list counts as read either way
        open_tour(step_id=visible_steps()[0].id)
        st.rerun()
    if not last_card and foot.button(
        tr("tour.news_skip"), key="tour_news_skip", type="tertiary"
    ):
        _dismiss_news("skipped")
        st.rerun()


def _news_strip() -> None:
    """The minimized "what's new": the reader is on the page a card sent them
    to, and this is the way back into the rest of the list.

    Parking does not stamp the version — only the ways *out* of the modal do
    (`_dismiss_news`) — so a reader who closes the tab three cards in is still
    owed the other six on the next session.
    """
    cards = unseen_news()
    if not cards:  # stamped from elsewhere (the guided tour finishing)
        st.session_state[_RESUME] = False
        return
    idx = min(max(int(st.session_state.get(_NEWS, 0)), 0), len(cards) - 1)
    card = cards[idx]
    with st.container(border=True):
        row = st.container(horizontal=True, vertical_alignment="center")
        row.markdown(
            f":material/{card.item.icon}: "
            + tr(
                "tour.news_strip_progress",
                n=idx + 1,
                total=len(cards),
                title=tr(card.title_key),
            )
        )
        if row.button(tr("tour.news_resume"), key="tour_news_strip_resume",
                      icon=":material/auto_awesome:"):
            open_news(idx)
            st.rerun()
        if idx < len(cards) - 1 and row.button(
            tr("tour.next"), key="tour_news_strip_next",
            icon=":material/chevron_right:",
        ):
            open_news(idx + 1)
            st.rerun()
        if row.button(tr("tour.news_dismiss"), key="tour_news_strip_close",
                      type="tertiary"):
            _dismiss_news("strip_close")
            st.rerun()


def _resume_strip() -> None:
    """The minimized tour: one line above the page body, on every page.

    Deliberately not a modal — the point of "take me there" is that the user
    is looking at the real page. The strip says which step they are on and
    holds the two ways out: back into the modal, or done with it. "What's new"
    parks the same way, on its own card list — `_news_strip`.
    """
    if st.session_state.get(_MODE) == "news":
        _news_strip()
        return
    steps = visible_steps()
    idx = min(max(int(st.session_state.get(_STEP, 0)), 0), len(steps) - 1)
    step = steps[idx]
    with st.container(border=True):
        row = st.container(horizontal=True, vertical_alignment="center")
        row.markdown(
            f":material/{step.icon}: "
            + tr(
                "tour.strip_progress",
                n=idx + 1,
                total=len(steps),
                title=tr(f"tour.{step.id}_title"),
            )
        )
        if row.button(tr("tour.resume"), key="tour_strip_resume",
                      icon=":material/menu_book:"):
            open_tour()
            st.rerun()
        if idx < len(steps) - 1 and row.button(
            tr("tour.next"), key="tour_strip_next",
            icon=":material/chevron_right:",
        ):
            _step_next()
            open_tour()
            st.rerun()
        if row.button(tr("tour.exit"), key="tour_strip_exit", type="tertiary"):
            _exit_tour("abandoned_strip")
            st.rerun()


def render_launcher(
    key: str,
    container=None,
    *,
    label: str | None = None,
    button_type: Literal["primary", "secondary", "tertiary"] = "secondary",
) -> None:
    """An "open the tutorial" button, for wherever the user looks for it — the
    Profile page, the Home setup card. `container` draws it into a row instead
    of the page flow. Always starts from the top: someone who asks for the
    tutorial wants the tutorial, not the step they abandoned weeks ago.
    """
    host = container if container is not None else st
    if host.button(
        label or tr("tour.launch"),
        key=key,
        # A caller-supplied label carries its own icon inline (the Home setup
        # card builds every pill that way), so don't add a second one.
        icon=None if label else ":material/menu_book:",
        type=button_type,
    ):
        # Which surface the button opens is the deploy's choice, not the call
        # site's — every launcher (Profile, the Home setup card) follows the
        # same flag. Imported here rather than at module scope: guide reads
        # this registry, so a top-level import would close the cycle.
        from stocks.web import guide

        if guide.surface() == "chat":
            guide.start()
        else:
            open_tour(step_id=visible_steps()[0].id)
        st.rerun()
