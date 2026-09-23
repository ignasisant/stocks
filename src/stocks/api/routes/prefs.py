"""The account's own settings: what it can read back, and what it may change.

Two rules shape this module, and both are about what is NOT here.

**Not every stored key is writable.** prefs.json also holds things the server
stamps (when this account was first seen), things a verified flow owns (the
Telegram chat id, which is proved by the linking handshake, not asserted by a
client) and things with a route of their own (the recent-search list). A PATCH
that accepted the whole file would let a client forge its own signup date and
point another chat at its digest, so the writable set is an explicit allowlist
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
from stocks.api.deps import Account, Writer
from stocks.api.schemas import Prefs
from stocks.api.security import Who
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
    """The settings a client renders, and nothing else.

    The chat id itself does not cross the wire — a caller needs to know whether
    Telegram is linked, not what it is linked to, and the id is what the
    notification cron addresses.
    """
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
        # The page draws the toggle on (`prefs.get(key, True)`) and the cron
        # sends on the same assumption (`notify.fanout.iter_notify_users`), so
        # reporting False for an account that never touched it would draw the
        # switch off beside a review that is being delivered every Sunday.
        notify_weekly=bool(stored.get("notify_weekly", True)),
        setup_card_dismissed=bool(stored.get("setup_card_dismissed", False)),
        onboarding_dismissed=bool(stored.get("onboarding_dismissed", False)),
        notify_alerts=bool(stored.get("notify_alerts")),
        telegram_linked=bool(stored.get("telegram_chat_id")),
        chat_panel_open=bool(stored.get("chat_panel_open")),
    )


@router.get("/prefs", response_model=Prefs, summary="This account's settings")
def prefs(account: Account, who: Who) -> Prefs:
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
# `PUT`, not `PATCH`. The form is five controls saved together and the page
# stores it as a whole (`auth.save_profile`); a partial write would let a client
# leave `risk` behind while moving `horizon` and end up describing somebody who
# never filled that combination in.

# How much free text the assistant is asked to carry. The notes ride in every
# system prompt the account ever sends (`chat.engine.persona`), so an unbounded
# field is an unbounded per-message cost on a shared free tier — and a novel
# pasted in here would crowd out the book snapshot underneath it. The widget on
# the page sets no limit, which is a smaller problem there: a person typing into
# a box is their own bound, and a client is not.
_MAX_NOTES = 2000


def _profile_options() -> tuple[tuple[str, ...], ...]:
    """(risk, horizon, focus, constraints), from the page's own tuples.

    Imported here rather than at module scope, the same way `/i18n` does it:
    `stocks.web` pulls Streamlit in and a headless caller never needs it. The
    lists come from `web.auth` rather than being restated because they are the
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

    Normalised rather than stored as sent, exactly as `auth.render_profile_form`
    normalises the page's click order. The Profile page autosaves on a *field by
    field* difference against what is stored, so a list that came back in a
    different order would read as an edit on every rerun and toast "saved" at a
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
    rather than a rewrite of it (`accounts.update_prefs`), so a Streamlit tab
    open on the same account keeps whatever it saved next door.
    """
    from stocks.web.auth import load_profile

    stored = accounts.update_prefs(
        account.prefs,
        {"investor_profile": {**body.model_dump(), "set": True}},
    )
    # With the persona too: a form that just changed what the assistant is told
    # should hand back what it now says, not make the client ask again.
    return _with_persona(load_profile(stored))
