"""The account's own settings: what it can read back, and what it may change.

Two rules shape this module, and both are about what is NOT here.

**Not every stored key is writable.** prefs.json also holds things the server
stamps (when this account was first and last seen) and things with a route
of their own (the recent-search list). A PATCH that accepted the whole file
would let a client forge its own signup date or its last visit, which the
reminder reads, so the writable set is an explicit allowlist
and anything outside it is refused by name rather than ignored.

**Not every caller may write.** A bearer token names nobody and any holder can
name any account, so a token that could write would be one leaked secret away
from editing every book on the deployment. `Writer` refuses it; reading stays
as it was.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from stocks import accounts
from stocks.accounts import UserPaths
from stocks.api.deps import Account, Writer
from stocks.api.schemas import HomeSlot, Prefs
from stocks.api.security import Caller, Who
from stocks.config import CURRENCIES
from stocks.portfolio import tax

router = APIRouter(tags=["prefs"])

# Filing statuses any jurisdiction distinguishes. Validated against the union
# rather than against the account's own country: the two settings are written
# in the same PATCH and a client that moves residence and status together must
# not be refused because the old country never had the new status.
_FILING_STATUSES = frozenset(
    {"single", *(s for c in tax.JURISDICTIONS for s in tax.get(c).filing_statuses)}
)

# More slots than the registry will ever hold, so a layout is never refused for
# being long — only a client sending something that is not a layout is.
_MAX_HOME_SLOTS = 32

# Rates stored as fractions, not percentages. 0.09 is a church-tax rate; 9 is a
# typo that would multiply somebody's tax bill by a hundred.
_MAX_RATE = 1.0


def _languages() -> frozenset[str]:
    """Language codes the catalogs actually ship.

    Imported here rather than at module scope, the same way `/i18n` does it:
    the catalogs live under `web/` and a headless caller never needs them.
    """
    from stocks.web.i18n import LANGUAGES

    return frozenset(LANGUAGES)


class PrefsPatch(BaseModel):
    """The writable subset. Only the fields actually sent are changed.

    `None` is a real value for three of these — it means "auto": follow the
    browser for language, the browser's region for residence. So the patch is
    applied on what was *set*, not on what is non-null, and a client clearing a
    setting sends an explicit null.
    """

    model_config = {"extra": "forbid"}

    currency: str | None = None
    language: str | None = None
    tax_residence: str | None = None
    tax_filing_status: str | None = None
    tax_other_income: float | None = None
    tax_niit: bool | None = None
    tax_church_rate: float | None = None
    tax_subnational_rate: float | None = None
    notify_digest: bool | None = None
    notify_weekly: bool | None = None
    notify_alerts: bool | None = None
    chat_panel_open: bool | None = None
    setup_card_dismissed: bool | None = None
    onboarding_dismissed: bool | None = None
    profile_prompt_off: bool | None = None
    # The whole list every time: a PATCH replaces the key, it does not merge
    # into it. null puts the default layout back.
    home_layout: list[HomeSlot] | None = None

    @field_validator("home_layout")
    @classmethod
    def _sane_layout(cls, value: list[HomeSlot] | None) -> list[HomeSlot] | None:
        if value is None:
            return value
        if len(value) > _MAX_HOME_SLOTS:
            raise ValueError(f"a Home holds at most {_MAX_HOME_SLOTS} cards")
        ids = [slot.id for slot in value]
        if len(set(ids)) != len(ids):
            raise ValueError("each card appears once")
        return value

    @field_validator("currency")
    @classmethod
    def _known_currency(cls, value: str | None) -> str | None:
        if value is None:
            return value
        code = value.strip().upper()
        if code not in CURRENCIES:
            raise ValueError(f"currency must be one of {', '.join(CURRENCIES)}")
        return code

    @field_validator("language")
    @classmethod
    def _known_language(cls, value: str | None) -> str | None:
        if value is None:
            return value  # auto — follow the browser
        code = value.strip().lower()
        if code not in _languages():
            raise ValueError(f"no catalog ships for language {value!r}")
        return code

    @field_validator("tax_residence")
    @classmethod
    def _known_jurisdiction(cls, value: str | None) -> str | None:
        if value is None or value.strip().lower() == "auto":
            return None  # auto — resolve from the browser's region
        code = value.strip().upper()
        if code not in tax.JURISDICTIONS:
            raise ValueError(f"no tax rules are modelled for {value!r}")
        return code

    @field_validator("tax_filing_status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        if value is None:
            return "single"
        code = value.strip().lower()
        if code not in _FILING_STATUSES:
            raise ValueError(f"unknown filing status {value!r}")
        return code

    @field_validator("tax_other_income")
    @classmethod
    def _sane_income(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value != value or value < 0:
            raise ValueError("other income cannot be negative")
        return float(value)

    @field_validator("tax_church_rate", "tax_subnational_rate")
    @classmethod
    def _sane_rate(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value != value or not 0.0 <= value <= _MAX_RATE:
            raise ValueError("a rate is a fraction between 0 and 1, not a percentage")
        return float(value)


def _view(stored: dict) -> Prefs:
    """The settings a client renders, and nothing else."""
    return Prefs(
        currency=str(stored.get("currency") or "EUR"),
        language=stored.get("language"),
        tax_residence=stored.get("tax_residence"),
        tax_filing_status=str(stored.get("tax_filing_status") or "single"),
        tax_other_income=float(stored.get("tax_other_income") or 0.0),
        tax_niit=bool(stored.get("tax_niit")),
        tax_church_rate=float(stored.get("tax_church_rate") or 0.0),
        tax_subnational_rate=float(stored.get("tax_subnational_rate") or 0.0),
        notify_digest=bool(stored.get("notify_digest")),
        # Defaulted here rather than read off the merged file, because unlike
        # its two neighbours this one is missing from `accounts.DEFAULT_PREFS`.
        # The cron sends on the assumption it is on
        # (`notify.fanout.iter_notify_users`), so reporting False for an
        # account that never touched it would draw the switch off beside a
        # review that is being delivered every Sunday.
        notify_weekly=bool(stored.get("notify_weekly", True)),
        setup_card_dismissed=bool(stored.get("setup_card_dismissed", False)),
        onboarding_dismissed=bool(stored.get("onboarding_dismissed", False)),
        profile_prompt_off=bool(stored.get("profile_prompt_off", False)),
        notify_alerts=bool(stored.get("notify_alerts")),
        chat_panel_open=bool(stored.get("chat_panel_open")),
        home_layout=_layout(stored.get("home_layout")),
    )


def _layout(stored: object) -> list[HomeSlot] | None:
    """The stored Home layout, or None for the default when it is not one.

    Written only through `PrefsPatch`, so this is a hand-edited or corrupt
    file's guard: a settings read must not 500 over one bad key.
    """
    if not isinstance(stored, list):
        return None
    try:
        return [HomeSlot.model_validate(slot) for slot in stored]
    except ValueError:
        return None


@router.get("/prefs", response_model=Prefs, summary="This account's settings")
def prefs(account: Account, who: Who) -> Prefs:
    return current(account, who)


def current(account: UserPaths, who: Caller) -> Prefs:
    """The settings `GET /prefs` answers `who` with, reading `account`.

    Its own function because the document that serves the app writes this
    answer into itself (`web.server`), so the first paint needs no round trip
    for it; the route and the document must answer the same thing.
    """
    if who.kind == "guest":
        # The defaults, built here, never read from disk. One prefs.json serves
        # every anonymous visitor on the deployment, so whatever is in it is not
        # this reader's preference — and a settings screen nobody can change
        # must not differ between two people looking at it. It is also the half
        # of the read-only rule a reader can see: this route does not open the
        # file it would otherwise be tempted to write.
        return _view({})
    return _view(accounts.load_prefs(account.prefs))


@router.patch("/prefs", response_model=Prefs, summary="Change some of them")
def update(
    account: Writer,
    patch: Annotated[PrefsPatch, ...],
) -> Prefs:
    """Merge the fields actually sent into the stored file, and return the whole.

    A JSON body, which is also what keeps it safe under cookie authentication:
    a cross-site form cannot set `Content-Type: application/json`, and a
    cross-site `fetch` that does gets preflighted — and nothing here answers a
    preflight.
    """
    changes = patch.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="send at least one setting to change",
        )
    return _view(accounts.update_prefs(account.prefs, changes))


# --------------------------------------------------------- the investor profile
# Who the account says it is, in five stored fields. It lives in prefs.json like
# every other setting, but it is not one of the settings above and cannot be:
# the PATCH allowlist is flat and this is a nested object whose every member has
# its own vocabulary, so a `PrefsPatch` field for it would accept any JSON at
# all under the one key that reaches the model's system prompt.
#
# `PUT`, not `PATCH`. The form is five controls stored as a whole; a partial
# write would let a client leave `risk` behind while moving `horizon` and end
# up describing somebody who never filled that combination in.

# How much free text the assistant is asked to carry. The notes ride in every
# system prompt the account ever sends (`chat.engine.persona`), so an unbounded
# field is an unbounded per-message cost on a shared free tier — and a novel
# pasted in here would crowd out the book snapshot underneath it. The widget on
# the page sets no limit, which is a smaller problem there: a person typing into
# a box is their own bound, and a client is not.
_MAX_NOTES = 2000


def _profile_options() -> tuple[tuple[str, ...], ...]:
    """(risk, horizon, focus, constraints), from `web.auth`'s own tuples.

    The lists come from there rather than being restated because they are the
    ones `chat.engine.persona` has English wording for — a value this route
    invented would store fine and then describe nobody.
    """
    from stocks.web.auth import (
        PROFILE_CONSTRAINTS,
        PROFILE_FOCUS,
        PROFILE_HORIZON,
        PROFILE_RISK,
    )

    return PROFILE_RISK, PROFILE_HORIZON, PROFILE_FOCUS, PROFILE_CONSTRAINTS


class InvestorProfile(BaseModel):
    """What the assistant is told about this account.

    Field names are the stored ones, because `chat.engine.persona` reads this
    dict directly: a rename here is a persona that silently loses a sentence.
    """

    risk: str = Field(description="One of `/profile-options`' `risk`.")
    horizon: str = Field(description="One of its `horizon`.")
    focus: list[str] = Field(description="Any number of its `focus`, in offering order.")
    constraints: list[str] = Field(
        description="Any number of its `constraints`, in offering order."
    )
    notes: str = Field(description="Free text the assistant is given verbatim.")
    set: bool = Field(
        description=(
            "Whether this account has ever saved the form. False means every "
            "field above is a default nobody chose — which is why the app "
            "nudges rather than assuming it knows the reader."
        )
    )
    persona: str = Field(
        default="",
        description=(
            "The sentence the assistant is actually given, built from the "
            "fields above (`chat.engine.persona`). Served rather than left to "
            "a client to reassemble: the form says what was chosen and this "
            "says what the model is told, and the whole point of showing it is "
            "that somebody can check the second follows from the first. "
            "English regardless of the interface language — it is a prompt, "
            "not a label."
        ),
    )


def _in_offering_order(chosen: list[str], allowed: tuple[str, ...], field: str):
    """The picks that are real options, deduplicated, in the order they are offered.

    Normalised rather than stored as sent. The Profile page autosaves on a
    *field by field* difference against what is stored, so a list that came
    back in a different order would read as an edit and toast "saved" at a
    reader who touched nothing.
    """
    codes = [c.strip().lower() for c in chosen]
    unknown = sorted(set(codes) - set(allowed))
    if unknown:
        raise ValueError(f"unknown {field}: {', '.join(unknown)}")
    return [option for option in allowed if option in codes]


class ProfileWrite(BaseModel):
    """The whole profile, replaced. Saving it marks the profile `set`."""

    model_config = {"extra": "forbid"}

    risk: str
    horizon: str
    focus: list[str] = []
    constraints: list[str] = []
    notes: str = ""

    @field_validator("risk")
    @classmethod
    def _known_risk(cls, value: str) -> str:
        risk, _, _, _ = _profile_options()
        code = value.strip().lower()
        if code not in risk:
            raise ValueError(f"risk must be one of {', '.join(risk)}")
        return code

    @field_validator("horizon")
    @classmethod
    def _known_horizon(cls, value: str) -> str:
        _, horizon, _, _ = _profile_options()
        code = value.strip().lower()
        if code not in horizon:
            raise ValueError(f"horizon must be one of {', '.join(horizon)}")
        return code

    @field_validator("focus")
    @classmethod
    def _known_focus(cls, value: list[str]) -> list[str]:
        _, _, focus, _ = _profile_options()
        return _in_offering_order(value, focus, "focus")

    @field_validator("constraints")
    @classmethod
    def _known_constraints(cls, value: list[str]) -> list[str]:
        _, _, _, constraints = _profile_options()
        return _in_offering_order(value, constraints, "constraints")

    @field_validator("notes")
    @classmethod
    def _bounded_notes(cls, value: str) -> str:
        text = value.strip()
        if len(text) > _MAX_NOTES:
            raise ValueError(f"notes must be at most {_MAX_NOTES} characters")
        return text


def _with_persona(profile: dict) -> InvestorProfile:
    """The stored profile plus the sentence it produces.

    The chat engine is a heavy import and this module has no other reason to
    pull it, so it is imported here rather than at module scope — the same
    local-import reasoning the Profile page uses for the very same call.
    """
    from stocks.chat.engine import persona

    return InvestorProfile(**profile, persona=persona(profile).strip())


@router.get("/profile", response_model=InvestorProfile, summary="The investor profile")
def profile(account: Account) -> InvestorProfile:
    """The stored profile with the defaults filled in, and whether it was ever set.

    Read through `auth.load_profile` so the defaults are the app's own — an
    account that never opened the form reads "balanced / 5y+", the middle of the
    risk scale rather than one end, because this is a guess about somebody we
    know nothing about.
    """
    from stocks.web.auth import load_profile

    return _with_persona(load_profile(accounts.load_prefs(account.prefs)))


@router.put("/profile", response_model=InvestorProfile, summary="Replace it")
def save(account: Writer, body: ProfileWrite) -> InvestorProfile:
    """Store the whole profile and mark it set.

    A session only, like every other write here. And a merge into prefs.json
    rather than a rewrite of it (`accounts.update_prefs`), so another tab open
    on the same account keeps whatever it saved next door.
    """
    from stocks.web.auth import load_profile

    stored = accounts.update_prefs(
        account.prefs,
        {"investor_profile": {**body.model_dump(), "set": True}},
    )
    # With the persona too: a form that just changed what the assistant is told
    # should hand back what it now says, not make the client ask again.
    return _with_persona(load_profile(stored))


# ------------------------------------------------------------- the investor plan
# The numbers the reader holds the book to (`stocks.portfolio.plan`): a mix by
# kind of asset, caps on one name, one sector and the speculative names, a
# contribution schedule and a cash reserve. Review sizes its moves to it and
# the daily card measures the book against it. Like the profile it is a nested
# object with its own vocabulary, so it has its own route rather than a PATCH
# field, and it is written whole: a mix whose targets were saved one at a time
# would add up to 100 only by accident.


class PlanMix(BaseModel):
    model_config = {"extra": "forbid"}

    targets: dict[str, float] = Field(
        description=(
            "Percent of the book per bucket (`stocks.portfolio.plan.BUCKETS`); "
            "adds up to 100."
        )
    )
    band_pp: float = Field(
        default=5.0, gt=0, le=50, description="Drift allowed either side, in points."
    )

    @field_validator("targets")
    @classmethod
    def _whole_book(cls, value: dict[str, float]) -> dict[str, float]:
        from stocks.portfolio.plan import BUCKETS, MIX_SLACK_PP

        unknown = sorted(set(value) - set(BUCKETS))
        if unknown:
            raise ValueError(f"unknown bucket: {', '.join(unknown)}")
        if any(not 0 <= v <= 100 for v in value.values()):
            raise ValueError("each target is a percent between 0 and 100")
        if abs(sum(value.values()) - 100) > MIX_SLACK_PP:
            raise ValueError("targets must add up to 100")
        # In offering order, every bucket present: see `_in_offering_order`.
        return {b: float(value.get(b, 0.0)) for b in BUCKETS}


class PlanLimits(BaseModel):
    model_config = {"extra": "forbid"}

    max_position_pct: float | None = Field(default=None, gt=0, le=100)
    max_sector_pct: float | None = Field(default=None, gt=0, le=100)
    max_speculative_pct: float | None = Field(default=None, gt=0, le=100)


class PlanContribution(BaseModel):
    model_config = {"extra": "forbid"}

    amount: float = Field(gt=0, description="In the account's reporting currency.")
    every: str = Field(default="monthly", description="`monthly` or `quarterly`.")
    day: int = Field(default=1, ge=1, le=28)

    @field_validator("every")
    @classmethod
    def _known_every(cls, value: str) -> str:
        from stocks.portfolio.plan import EVERY

        if value not in EVERY:
            raise ValueError(f"every must be one of {', '.join(EVERY)}")
        return value


class PlanReserve(BaseModel):
    model_config = {"extra": "forbid"}

    min_pct: float | None = Field(default=None, ge=0, le=100)
    max_pct: float | None = Field(default=None, ge=0, le=100)

    @field_validator("max_pct")
    @classmethod
    def _floor_under_ceiling(cls, value, info):
        low = info.data.get("min_pct")
        if value is not None and low is not None and low > value:
            raise ValueError("min_pct must not be over max_pct")
        return value


class PlanCash(BaseModel):
    """Money held outside any position, as the reader states it."""

    model_config = {"extra": "ignore"}

    investable: float | None = Field(
        default=None,
        ge=0,
        le=1e12,
        description=(
            "Uninvested money meant for the book (a broker's idle balance, a "
            "savings account), in the reporting currency. Counts as cash."
        ),
    )
    cushion: float | None = Field(
        default=None,
        ge=0,
        le=1e12,
        description="The emergency fund, kept apart and never counted.",
    )
    rate_pct: float | None = Field(
        default=None, ge=0, le=20, description="Interest the account pays, a year."
    )
    as_of: str | None = Field(
        default=None,
        description=(
            "ISO date the amounts were last stated. Set by the server when an "
            "amount changes; ignored on the way in."
        ),
    )


class PlanWrite(BaseModel):
    """The whole plan, replaced. Every block may be left out."""

    model_config = {"extra": "forbid"}

    mix: PlanMix | None = None
    limits: PlanLimits = PlanLimits()
    contribution: PlanContribution | None = None
    reserve: PlanReserve | None = None
    cash: PlanCash | None = None


class InvestorPlan(PlanWrite):
    model_config = {"extra": "ignore"}

    set: bool = Field(description="Whether this account has ever saved its plan.")
    actual: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "The book's share per bucket today, in percent — what the form "
            "draws beside the targets. Empty when no position is priced."
        ),
    )
    currency: str = Field(
        default="EUR", description="The currency `contribution.amount` is in."
    )
    next_contribution: str | None = Field(
        default=None, description="ISO date of the next scheduled contribution."
    )
    cash_stale_days: int | None = Field(
        default=None,
        description=(
            "Days since the stated cash was updated, once it is old enough to "
            "ask again (`plan.CASH_STALE_DAYS`); null while fresh."
        ),
    )


def _actual(paths: UserPaths, investable: float = 0.0) -> dict[str, float]:
    """Today's mix by bucket, with the stated `investable` cash in the cash
    bucket (`plan.with_cash`), or {} when the book cannot be read."""
    from stocks import obs
    from stocks.api import home, loaders
    from stocks.api.deps import reporting_currency
    from stocks.portfolio import plan as plans

    try:
        db = str(paths.db)
        tbl = home.enriched(db, loaders.db_mtime(db), reporting_currency(paths))
    except Exception as exc:  # noqa: BLE001 — the form stands without the bar
        obs.warn("plan.actual_unavailable", error_type=type(exc).__name__)
        return {}
    if tbl is None or tbl.empty or "weight" not in tbl:
        return plans.with_cash({}, 0.0, investable)
    shares = plans.buckets(tbl["weight"].to_dict(), loaders.asset_kind)
    value = float(tbl["value"].sum(skipna=True)) if "value" in tbl else 0.0
    return plans.with_cash(shares, value, investable)


def _plan_out(paths: UserPaths, prefs: dict) -> InvestorPlan:
    from datetime import date

    from stocks.api.deps import reporting_currency
    from stocks.portfolio import plan as plans

    investor = plans.load(prefs)
    today = date.today()
    upcoming = plans.next_contribution(investor, today)
    return InvestorPlan(
        **investor.to_dict(),
        actual=_actual(paths, investor.investable),
        currency=reporting_currency(paths),
        next_contribution=upcoming.isoformat() if upcoming else None,
        cash_stale_days=plans.cash_stale(investor, today),
    )


@router.get("/plan", response_model=InvestorPlan, summary="The investor plan")
def plan(account: Account) -> InvestorPlan:
    """The stored plan, read the way the app applies it, with today's mix.

    A block that does not hold together is not served (`plan.parse`), so the
    form never shows a line the app is not drawing.
    """
    return _plan_out(account, accounts.load_prefs(account.prefs))


@router.put("/plan", response_model=InvestorPlan, summary="Replace it")
def save_plan(account: Writer, body: PlanWrite) -> InvestorPlan:
    """Store the whole plan and mark it set; a merge into prefs.json, like
    the profile, so a setting saved next door survives. The cash block is
    dated here, when an amount changed (`plan.stamp_cash`): the client's own
    date would be a clock nobody checks."""
    from datetime import date

    from stocks.portfolio import plan as plans

    old = plans.load(accounts.load_prefs(account.prefs)).cash
    raw = body.model_dump()
    raw["cash"] = plans.stamp_cash(raw.get("cash"), old, date.today())
    stored = accounts.update_prefs(account.prefs, {plans.PREFS_KEY: {**raw, "set": True}})
    return _plan_out(account, stored)


@router.put(
    "/plan/contribution",
    response_model=InvestorPlan,
    summary="Set only its contribution",
)
def save_plan_contribution(account: Writer, body: PlanContribution) -> InvestorPlan:
    """Replace the plan's contribution and keep every other block as stored —
    the projection's "use in my plan", which knows the amount and nothing of
    the mix or the cash. Saving it sets the plan, as any plan write does."""
    from stocks.portfolio import plan as plans

    stored = accounts.load_prefs(account.prefs).get(plans.PREFS_KEY)
    raw = dict(stored) if isinstance(stored, dict) else {}
    raw["contribution"] = body.model_dump()
    stored = accounts.update_prefs(account.prefs, {plans.PREFS_KEY: {**raw, "set": True}})
    return _plan_out(account, stored)
