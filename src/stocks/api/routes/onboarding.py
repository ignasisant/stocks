"""The guided tour and "what's new", for a front end that is not Streamlit.

`web/onboarding.py` is two things wearing one coat: a registry — which steps
exist, which releases shipped, and whether this account has each capability
switched on — and a Streamlit modal that draws it. This router serves the
registry. Nothing here draws anything, and nothing here decides what is worth
announcing: `CLAUDE.md` sets that bar and the registry is where it is applied.

Copy is not sent. Every step and every card names its catalog keys
(`tour.<id>_title`, `tour.news_<version>_<slug>_body`), and the client already
has the catalog from `/i18n/{lang}` — shipping the strings here would be a
second copy that is stale in whichever language the reader picked.

The stamp is a write, and a real one: it is what stops the modal interrupting
the same account twice. So it is `Writer` like every other write — a bearer
token could otherwise mark an account as having read an announcement it never
saw, which is a small lie the account can never get back.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from stocks import accounts
from stocks.api.deps import Account, Writer
from stocks.api.security import Who
from stocks.web import onboarding

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class TourStep(BaseModel):
    """One stop on the tour, with where it lands and whether it is switched on."""

    id: str
    icon: str
    # The page's URL path — "" is the default page, served at the root. Null
    # for a step whose target is not a page at all (the assistant panel).
    path: str | None = None
    params: dict[str, str] = {}
    # State the step wants seeded on arrival, in the registry's own words —
    # `profile_tab`, `chat_panel_open`. Deliberately not translated into query
    # parameters here: the Streamlit page reads these off session state and
    # this shell puts the Profile tab in `?tab=`, so the two encodings are the
    # front end's business and the intent is the API's. A client that ignores
    # this lands on the right page and the wrong tab.
    session: dict[str, str] = {}
    gated: bool = Field(
        description="Target sits behind a login; a guest reads the step anyway."
    )
    done: bool | None = Field(
        description=(
            "Whether this account has the capability switched on. Null for a "
            "step that is nothing to switch on — a page is a page, and a tick "
            "beside one would be a claim about nothing."
        )
    )
    title_key: str
    body_key: str
    cta_key: str | None = Field(
        description="Set only where the generic 'take me there' is not the label."
    )


class NewsCard(BaseModel):
    """One thing that shipped, as one card of the what's-new modal."""

    version: str
    date: str
    slug: str
    icon: str
    step: str | None = Field(
        description="The step that explains it; the card's button goes there."
    )
    title_key: str
    body_key: str


class Onboarding(BaseModel):
    version: str = Field(description="The newest release in the registry.")
    seen_version: str | None = Field(
        description="What this account was last shown; null for a new account."
    )
    tour_done: bool
    steps: list[TourStep]
    news: list[NewsCard] = Field(
        description=(
            "Everything shipped since this account's stamp, newest first — one "
            "card per feature. Empty for an account that is caught up."
        )
    )
    signed_in: bool = Field(
        description=(
            "Whether the caller is a signed-in account rather than a guest "
            "reading the shared demo book. Mirrors `setup.login`, and is here "
            "on its own so a client gating the tour's locked steps need not "
            "read it out of the setup card."
        )
    )
    setup: dict[str, bool] = Field(
        description="The four connectable capabilities, as the Home card reads them."
    )
    explore: dict[str, bool] = Field(
        description="The three that need no setup: search, ask, watchlist."
    )


class Seen(BaseModel):
    """Stamp the account as caught up, and optionally as done with the tour."""

    model_config = {"extra": "forbid"}

    done: bool | None = None


def _step(step: onboarding.Step, prefs: dict, paths) -> TourStep:
    return TourStep(
        id=step.id,
        icon=step.icon,
        path=onboarding._url_path(step.page) if step.page else None,
        params=dict(step.query or {}),
        session={k: str(v) for k, v in (step.session or {}).items()},
        gated=step.gated,
        done=None if step.done is None else bool(step.done(prefs, paths)),
        title_key=f"tour.{step.id}_title",
        body_key=f"tour.{step.id}_body",
        cta_key=(
            f"tour.{step.id}_cta"
            if onboarding.i18n.has(f"tour.{step.id}_cta")
            else None
        ),
    )


@router.get("", response_model=Onboarding, summary="The tour, and what is new")
def state(account: Account, caller: Who) -> Onboarding:
    """Everything a client needs to draw the tour and the what's-new modal.

    One call because the two are one registry and one account state: a client
    that fetched the steps and the cards separately could draw a card pointing
    at a step this deploy does not carry.
    """
    prefs = accounts.load_prefs(account.prefs)
    steps = onboarding.visible_steps()
    signed_in = caller.kind != "guest"
    return Onboarding(
        version=onboarding.CURRENT_VERSION,
        seen_version=prefs.get(onboarding.PREF_SEEN_VERSION),
        tour_done=bool(prefs.get(onboarding.PREF_DONE)),
        steps=[_step(s, prefs, account) for s in steps],
        news=[
            NewsCard(
                version=card.version,
                date=card.date,
                slug=card.item.slug,
                icon=card.item.icon,
                step=card.item.step,
                title_key=card.title_key,
                body_key=card.body_key,
            )
            for card in onboarding.unseen_news(prefs)
        ],
        signed_in=signed_in,
        # Reported from the real caller. This route is guest-open, and it used
        # to answer `signed_in=True` unconditionally — so an anonymous visitor
        # saw "Google sign-in ✓ Active" on the setup card of a demo book. A
        # token caller names an account that exists, which is what the tick
        # means; only a guest has no sign-in to report.
        setup=onboarding.setup_state(prefs, account, signed_in=signed_in),
        explore=onboarding.explore_state(prefs, account),
    )


@router.post("/seen", response_model=Onboarding, summary="Mark it read")
def seen(body: Seen, account: Writer, caller: Who) -> Onboarding:
    """Stamp this account as caught up with the current release.

    Every way out of the modal stamps it — finishing, dismissing, closing —
    because the card was interrupting somebody who came to look at their
    portfolio, and showing it a second time is worse than not showing it at
    all. `done` additionally retires the guided tour, which is what stops it
    auto-opening on later sessions.
    """
    changes: dict = {onboarding.PREF_SEEN_VERSION: onboarding.CURRENT_VERSION}
    if body.done is not None:
        changes[onboarding.PREF_DONE] = body.done
    accounts.update_prefs(account.prefs, changes)
    return state(account, caller)
