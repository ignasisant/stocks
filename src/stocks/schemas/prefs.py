"""The reader's own settings: home layout, schedules, tags, alerts and
the app's navigation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class HomeSlot(BaseModel):
    """One card on the account's Home, in the order the reader put it.

    The ids are the client's card registry, not a list the server keeps: a
    card a later release removes is dropped where the layout is drawn, and one
    it adds is slotted in there too, so the stored list never has to be
    migrated. The server checks the shape only.
    """

    model_config = {"extra": "forbid"}

    id: str = Field(pattern=r"^[a-z_]{1,24}$")
    hidden: bool = False


class ScheduleSlot(BaseModel):
    """One scheduled run: whether it goes out, at what local time, on which days."""

    model_config = {"extra": "forbid"}

    on: bool = True
    time: str = Field(description='Local wall-clock time, "HH:MM".')
    days: list[int] = Field(description="Weekdays it runs on, Monday = 0.")
    close: bool = Field(
        default=False,
        description=(
            "Goes out the evening of each US close, as soon as its card is "
            "written, instead of at `time` (which is kept for switching back). "
            "`days` are then the sessions' weekdays."
        ),
    )

    @field_validator("time")
    @classmethod
    def _clock(cls, value: str) -> str:
        from stocks.notify.schedule import parse_time

        at = parse_time(value)
        if at is None:
            raise ValueError('time is "HH:MM"')
        return at.strftime("%H:%M")

    @field_validator("days")
    @classmethod
    def _weekdays(cls, value: list[int]) -> list[int]:
        if any(not 0 <= d <= 6 for d in value):
            raise ValueError("days are weekday numbers, Monday = 0")
        return sorted(set(value))


class Prefs(BaseModel):
    """The account's settings as a client renders them.

    A curated view, not the stored file: the keys the server stamps (signup
    accounting), the address (that is `/me`) and the recent-search list (that
    has its own route) are not settings anybody edits on a settings screen.
    """

    currency: str
    language: str | None = Field(
        default=None, description="null means auto — follow the browser."
    )
    tax_residence: str | None = Field(
        default=None, description="null means auto — resolve from the browser region."
    )
    tax_filing_status: str = "single"
    tax_other_income: float = 0.0
    tax_niit: bool = False
    tax_church_rate: float = 0.0
    tax_subnational_rate: float = 0.0
    # The Friday email (`notify/weekly_email.py`): on for every imported
    # book, device or not, until the reader turns it off.
    notify_weekly_email: bool = True
    notify_alerts: bool = True
    # The Home first-run card, dismissed. An account setting rather than a
    # browser one: a reader who put the checklist away has put it away, and
    # meeting it again on their phone is the app forgetting a decision.
    setup_card_dismissed: bool = False
    # The other first-run card, and a different decision: the three steps to a
    # live portfolio. It says what to *do*; `setup_card_dismissed` hides what is
    # switched *on*.
    onboarding_dismissed: bool = False
    # "Don't ask again" on the investor-profile nudge. Without it the dialog
    # asks every session until the profile is saved, and a reader who would
    # rather not answer had no way to say so.
    profile_prompt_off: bool = False
    # The one-time "rate TopStocks" prompt has been shown — answered or not.
    # Per account, so the phone does not ask what the laptop already asked.
    rate_prompt_done: bool = False
    home_layout: list[HomeSlot] | None = Field(
        default=None,
        description=(
            "The Home cards in the reader's order, each shown or hidden. null "
            "means the default layout."
        ),
    )
    chat_panel_open: bool = False
    notify_briefing: bool = True
    timezone: str | None = Field(
        default=None,
        description=(
            "IANA zone the scheduled runs keep time in; null until the browser "
            "has sent one (`notify.schedule.DEFAULT_ZONE` meanwhile)."
        ),
    )
    schedules: dict[str, ScheduleSlot] = Field(
        default_factory=dict,
        description=(
            "The scheduled runs (`briefing`, the one summary a day) as the "
            "app applies them, defaults filled in."
        ),
    )


class Tags(BaseModel):
    tags: list[str] = Field(
        default_factory=list,
        description="Every tag in use, sorted case-insensitively.",
    )


class TagEdit(BaseModel):
    """How many holdings an edit to a tag group touched.

    A group exists only as the tag repeated on its members, so renaming or
    dropping one is a rewrite of each member's tag list — and the count is the
    only honest confirmation of what happened.
    """

    tag: str
    holdings: int = Field(description="Holdings the edit touched; 0 means none did.")


class AlertRule(BaseModel):
    """One watchlist alert rule.

    Which fields a rule uses depends on its type: the price thresholds read
    `price`, the history-based ones read `pct`, `level` or `window`. The unused
    ones stay null rather than zero — a drawdown alert has no price, and a
    price of 0 would be a threshold nothing can ever be below.
    """

    type: str = Field(
        description=(
            "above | below | pct_move | drawdown | rsi_below | rsi_above | "
            "sma_cross | high_52w | low_52w."
        )
    )
    price: float | None = Field(default=None, description="Threshold, for above/below.")
    pct: float | None = Field(default=None, description="Percent magnitude; 5 == 5%.")
    level: float | None = Field(default=None, description="Absolute level, e.g. RSI 30.")
    window: int | None = Field(
        default=None, description="Lookback in trading days (SMA span, drawdown window)."
    )


class NavDestination(BaseModel):
    """One page of the app's menu.

    `label` is an i18n key, like everything else here that will be read: the
    API has no language. `icon` is a Material Symbols ligature, which is the
    same glyph the app's own sidebar and phone bar draw for this page.
    """

    path: str = Field(description='URL path; "" is the default page, served at /.')
    label: str = Field(description="i18n key, e.g. nav.portfolio.")
    icon: str = Field(description="Material Symbols ligature, e.g. pie_chart.")
    section: str | None = Field(
        default=None, description="i18n key of its group; null for the top group."
    )


class Navigation(BaseModel):
    destinations: list[NavDestination] = Field(
        description="Every page, in menu order. Groups are runs of one section."
    )
    bottom: list[str] = Field(
        description=(
            "The paths a phone's fixed tab bar carries — the design replaces "
            "the sidebar with four destinations below 640px."
        )
    )


class AlertForm(BaseModel):
    """How one alert type is *entered* — the editor's half of a rule.

    `AlertRule` says what a rule is; this says what to ask for before there is
    one. Served rather than hardcoded in a client because the app's watchlist
    widget reads the same table (`config.ALERT_FORMS`), and a client with its
    own copy silently stops offering the next alert type this project adds.
    """

    type: str = Field(description="Rule type, as `AlertRule.type` takes it.")
    field: str | None = Field(
        default=None, description="Which number it asks for: price | pct | level."
    )
    default: float | None = Field(
        default=None, description="What to prefill; null means start empty."
    )
    window: int | None = Field(
        default=None,
        description="Default lookback in trading days; null when it takes none.",
    )


class AlertForms(BaseModel):
    forms: list[AlertForm] = Field(description="In the order they are offered.")


class Alerts(BaseModel):
    ticker: str
    alerts: list[AlertRule] = Field(default_factory=list)
