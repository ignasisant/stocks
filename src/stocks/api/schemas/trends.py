"""The trend rows and the name and logo behind every listed ticker."""

from __future__ import annotations

from pydantic import BaseModel, Field

from stocks.api.schemas.companies import Profile

# ------------------------------------------------------------- the trend rows
# Six blocks, one row shape. That is not a convenience: almost every line on
# the market screen is the same question — the level, where it has been over
# four horizons, and where it sits in its own trend — and a reader who learns
# the shape once reads all six.
#
# Numbers only. Units, labels and which direction is the welcome one are the
# client's to render: a falling credit spread and a rising index are both good
# news, and that judgement belongs with the words, not with the arithmetic.


class TrendRow(BaseModel):
    key: str = Field(
        description=(
            "Series id — a ticker for a price row, a FRED id for a rate, an "
            "area code for inflation. What an i18n label is looked up by."
        )
    )
    name: str = Field(default="", description="Source's own name, unlocalized.")
    value: float | None = Field(default=None, description="Latest level.")
    changes: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Change per horizon, in this block's `unit`. Usually week | month | "
            "quarter | year; inflation reports `print` (against the previous "
            "release) and `half_year` instead, because a weekly change in a "
            "series published twelve times a year is arithmetic on data that "
            "does not exist. A horizon the series is too short for is absent, "
            "not null — the difference is 'no data' versus 'no change'."
        ),
    )
    spark: list[float] = Field(
        default_factory=list, description="Last 90 observations, oldest first."
    )
    state: str | None = Field(
        default=None,
        description=(
            "up | turning_up | turning_down | down | unknown | stale. Null "
            "where a trend label would be noise — a policy rate steps when a "
            "committee decides and is flat in between."
        ),
    )
    percentile: float | None = Field(
        default=None, description="Where in its own trailing year, 0-100."
    )
    percentile_then: float | None = Field(
        default=None, description="The same, a month ago."
    )
    welcome: int = Field(
        default=0,
        description=(
            "Which direction is the good news: +1 a rise, -1 a fall, 0 neither. "
            "NOT the sign of the change — a widening spread and a falling index "
            "are both bad and a client colouring on sign alone paints half the "
            "screen backwards."
        ),
    )
    stale: bool = Field(
        default=False,
        description="The source stopped publishing this one; show it dimmed, not gone.",
    )
    weight: float | None = Field(
        default=None,
        description=(
            "Share of the reader's own book this row stands for, where that "
            "means something — the geography an index covers, the sector an ETF "
            "is. Null when it does not."
        ),
    )
    as_of: str | None = Field(
        default=None,
        description=(
            "The observation this row quotes, ISO. The server already decides "
            "whether a row is stale; without the date that verdict cannot be "
            "worded — 'stale' alone does not say how stale."
        ),
    )
    core: float | None = Field(
        default=None,
        description="Inflation rows only: the core rate beside the headline.",
    )
    spy_weight: float | None = Field(
        default=None,
        description=(
            "Rotation rows only: the sector's share of the benchmark, so the "
            "reader's own weight can be read as an over- or underweight "
            "against something rather than against nothing."
        ),
    )
    net_pct: float | None = Field(
        default=None,
        description="Positioning rows only: net position as a % of open interest.",
    )
    zscore: float | None = Field(
        default=None,
        description=(
            "Positioning rows only: net position in standard deviations from "
            "its 3-year mean. `percentile` is the same ranking over those years."
        ),
    )


class TrendBlock(BaseModel):
    block: str = Field(
        description=(
            "indices | gauges | rates | inflation | rotation | cross | "
            "factors | positioning."
        )
    )
    unit: str = Field(
        description=(
            "How to read `changes`: percent (a fraction), basis_points, or "
            "points (the series' own units)."
        )
    )
    rows: list[TrendRow] = Field(default_factory=list)
    unavailable: str | None = Field(
        default=None,
        description=(
            "Why the block is empty: rate_limited | offline | no_data. A block "
            "whose source died keeps its place and says so rather than "
            "vanishing, which would read as 'nothing is happening here'."
        ),
    )
    expected: int | None = Field(
        default=None,
        description=(
            "How many rows the block is configured to carry — the tab's "
            "badge. Fixed, so a block that is down still says what it would "
            "hold rather than losing its count."
        ),
    )


class TrendTables(BaseModel):
    blocks: list[TrendBlock] = Field(default_factory=list)


class Profiles(BaseModel):
    """Name and logo for a list of tickers, in one call.

    Exists because every screen that lists holdings needs both — the house rule
    is that a ticker on screen is a logo and a link, never a bare symbol — and
    the per-ticker `/ticker/{symbol}/profile` would make a seventeen-row table
    seventeen requests. Nothing here fetches: names and logos come from caches
    the account already warmed.
    """

    profiles: list[Profile] = Field(default_factory=list)
