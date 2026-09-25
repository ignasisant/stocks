"""Reference data: what the KPIs are and where each one comes from.

Not account data and not a computation — the same table for every caller on
every deployment. It is here rather than inlined in a client because the
verification hierarchy (SEC EDGAR first, then the ratio sites, then the
terminals) is a claim this project makes about its own numbers, and a client
repeating it from memory is how it goes stale.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from stocks import navigation
from stocks.analysis.fundamentals import KPI_SOURCES
from stocks.api.schemas import (
    AlertForm,
    AlertForms,
    KpiSourceRow,
    KpiSources,
    NavDestination,
    Navigation,
)
from stocks.config import ALERT_FORMS
from stocks.portfolio import tax

router = APIRouter(tags=["reference"])


@router.get("/kpi-sources", response_model=KpiSources, summary="Where each KPI is from")
def kpi_sources() -> KpiSources:
    return KpiSources(
        kpis=[
            KpiSourceRow(
                key=key,
                label=source.label,
                unit=source.unit,
                level=source.level,
                loader=source.loader,
                verify=source.verify,
                note=source.note,
                desc=source.desc,
            )
            for key, source in KPI_SOURCES.items()
        ]
    )


@router.get("/alert-types", response_model=AlertForms, summary="What a rule can ask")
def alert_types() -> AlertForms:
    """The alert editor's field table, in offering order.

    Reference for the same reason the KPI table is: which types exist, and what
    each one needs entered, is a decision this project makes once. A client
    holding its own list writes rules the evaluator cannot fire, and stops
    offering the ones added after it was written.
    """
    return AlertForms(
        forms=[
            AlertForm(
                type=form.type,
                field=form.field,
                default=form.default,
                window=form.window,
            )
            for form in ALERT_FORMS
        ]
    )


@router.get("/nav", response_model=Navigation, summary="The app's menu")
def nav() -> Navigation:
    """Which pages exist, in menu order, with their groups.

    Reference like the KPI table: a front end that keeps its own copy of the
    menu drops a page the day one is added, and nobody reports a page they
    cannot see. `stocks.navigation` is the same table the Streamlit sidebar and
    the phone tab bar are built from.
    """
    return Navigation(
        destinations=[
            NavDestination(
                path=destination.path,
                label=destination.label,
                icon=destination.icon,
                section=destination.section,
            )
            for destination in navigation.DESTINATIONS
        ],
        bottom=list(navigation.BOTTOM_NAV),
    )


# --------------------------------------------------------------- who you file as
# Models live in this module rather than in `api.schemas` because they describe
# one route's answer and nothing else reads them — the same call `routes/me.py`
# and `routes/i18n.py` make.


class Jurisdiction(BaseModel):
    """One country's tax treatment, as far as a settings screen needs it.

    No rates and no thresholds: those are the engine's, they move with the
    statute, and a client that cached them would report last year's tax. What
    is here is the shape of the form — which questions this country is asked,
    and which facts the card states back.
    """

    code: str = Field(description='The engine\'s own code, e.g. "ES", "UK".')
    label_key: str = Field(
        description=(
            "Catalog key naming the country, e.g. `profile.tax_residence_es`. "
            "The name is translated; the flag below is not."
        )
    )
    flag: str = Field(
        description=(
            "The flag emoji, built from the code's regional indicators. Empty "
            "for a code that is not ISO 3166-1 alpha-2."
        )
    )
    currency: str = Field(
        description=(
            "The currency the cost basis is replayed in — NOT the reporting "
            "currency. A US filer's basis is USD at each trade date."
        )
    )
    matching: str = Field(
        description=(
            "Share-identification rule for the replay: fifo, lifo, average or "
            "s104. `profile.tax_match_<matching>` names it."
        )
    )
    year_start: tuple[int, int] = Field(
        description="(month, day) the tax year opens on — (4, 6) in the UK."
    )
    filing_statuses: list[str] = Field(
        description=(
            "Statuses the brackets distinguish, in offering order. Empty where "
            "the rate scale does not care — Spain's savings base does not."
        )
    )
    settings_fields: list[str] = Field(
        description=(
            "Bracket inputs this country actually reads, in the order to offer "
            "them. An account whose jurisdiction reads none is asked nothing."
        )
    )
    carryforward_years: int | None = Field(
        description="Years a net loss may be carried forward; null = indefinitely."
    )
    repurchase_window: str | None = Field(
        description=(
            'How long a repurchase blocks a loss, as a bare token — "2m", '
            '"30d", "28d". Null where no such rule exists, or where the '
            "matching mode already absorbs it (the UK's 30-day rule)."
        )
    )
    splits_holding_period: bool = Field(
        description="Whether short- and long-term results are taxed differently."
    )
    pools_shares: bool = Field(
        description="Whether a sale's cost can be an average rather than a lot's own."
    )


class Jurisdictions(BaseModel):
    jurisdictions: list[Jurisdiction]
    default: str = Field(
        description=(
            "The code an account with no preference is taxed under. A null "
            "`tax_residence` means auto, which resolves from the browser's "
            "region and lands here when it recognizes nothing."
        )
    )


@router.get(
    "/jurisdictions",
    response_model=Jurisdictions,
    summary="Where an account can file",
)
def jurisdictions() -> Jurisdictions:
    """The tax jurisdictions the engine actually ships, in selector order.

    Reference for the same reason the menu is: adding a country is one module
    under `stocks.portfolio.tax` plus its catalog copy, and nothing in the web
    or CLI layer branches on the code. A front end holding its own list drops
    the eleventh country the day it ships, and nobody reports a country they
    cannot see — they just file under somebody else's rules.
    """
    # Imported here, not at module scope: `stocks.web` pulls Streamlit in, and
    # a headless caller of this API should never need it loaded. The flag comes
    # from there rather than being rebuilt because it is one decision — which
    # alpha-2 a tax code maps to, "UK" being GB — and two copies of it drift.
    from stocks.web.tax_ui import flag_emoji

    return Jurisdictions(
        default=tax.DEFAULT_CODE,
        jurisdictions=[
            Jurisdiction(
                code=code,
                label_key=f"profile.tax_residence_{code.lower()}",
                flag=flag_emoji(code),
                currency=j.currency,
                matching=j.matching,
                year_start=j.year_start,
                filing_statuses=list(j.filing_statuses),
                settings_fields=list(j.settings_fields),
                carryforward_years=j.carryforward_years,
                # "" is how the registry spells "no such rule"; null is how
                # JSON does, and a client testing truthiness gets it right
                # either way only if this is not an empty string.
                repurchase_window=j.repurchase_window or None,
                splits_holding_period=j.splits_holding_period,
                pools_shares=j.pools_shares,
            )
            for code, j in tax.JURISDICTIONS.items()
        ],
    )


class InvestorProfileOptions(BaseModel):
    """The investor-profile form's vocabulary, group by group.

    Every option is a stable enum key, deliberately locale-independent: the
    persona the chat engine builds is English whatever the UI language is, so
    the stored value must not be a translated label. `profile.iv_<group>_<option>`
    is the catalog key for each — `profile.iv_risk_balanced`,
    `profile.iv_focus_tech`.
    """

    risk: list[str] = Field(description="Risk appetite, low to high. Single choice.")
    horizon: list[str] = Field(description="Time horizon, short to long. Single choice.")
    focus: list[str] = Field(description="Areas followed. Any number, or none.")
    constraints: list[str] = Field(
        description="Rules the assistant must respect. Any number, or none."
    )


@router.get(
    "/profile-options",
    response_model=InvestorProfileOptions,
    summary="What the investor profile may say",
)
def profile_options() -> InvestorProfileOptions:
    """The options `PUT /profile` accepts, in the order to draw them.

    Both scales run low to high in the same direction: a row of chips only
    reads as a scale when its two halves agree on which end is "more". A client
    holding its own copy stops offering whatever was added after it was
    written, and — worse — keeps offering whatever was removed, which this API
    then refuses on save.
    """
    from stocks.web.auth import (
        PROFILE_CONSTRAINTS,
        PROFILE_FOCUS,
        PROFILE_HORIZON,
        PROFILE_RISK,
    )

    return InvestorProfileOptions(
        risk=list(PROFILE_RISK),
        horizon=list(PROFILE_HORIZON),
        focus=list(PROFILE_FOCUS),
        constraints=list(PROFILE_CONSTRAINTS),
    )
