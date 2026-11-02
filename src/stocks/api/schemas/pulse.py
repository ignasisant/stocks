"""The market's regime and the book's exposure to it."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ------------------------------------------------------------------ the regime
# The composite that says what kind of market this is, and — separately — what
# that regime does to one reader's own book. They are two endpoints because
# they are two different facts: a VIX percentile is the same number for
# everyone, "71% of your value is priced in dollars" is not.


class PulseComponent(BaseModel):
    key: str = Field(description="momentum | breadth | volatility | term | …")
    score: float | None = Field(default=None, description="This input's own 0-100 score.")
    raw: float | None = Field(default=None, description="What it actually read.")
    text: str | None = Field(
        default=None,
        description=(
            "`raw` formatted in its own units (+4.2%, 15.2, 1.19…) by the "
            "registry that knows them — what a row prints. Null with `raw`."
        ),
    )
    then: float | None = Field(
        default=None,
        description="The same score 21 sessions ago; null when history is short.",
    )


class PulsePoint(BaseModel):
    date: str
    score: float


class Breadth(BaseModel):
    """How many of a set are in an uptrend, and how many could be read at all.

    Both numbers, never a percentage: three of four and thirty of forty are the
    same fraction and not the same statement, and a denominator that shrank
    because a source failed has to be visible.
    """

    hits: int
    total: int
    window: int = Field(description="Sessions in the moving average.")


class Pulse(BaseModel):
    score: float | None = Field(
        default=None, description="0-100 composite; null when too few inputs built."
    )
    regime: str = Field(
        description=(
            "Band key, not prose: stress | caution | neutral | appetite | "
            "euphoria | unknown. The middle band is deliberately wide — the "
            "honest reading of a mid-range composite is 'no signal'."
        )
    )
    as_of: str | None = Field(
        default=None,
        description=(
            "The row the composite was quoted from, which is not always today: "
            "inputs land on different calendars and a score is only quoted for "
            "a row holding enough of them."
        ),
    )
    run: int = Field(
        default=0, description="Consecutive sessions the score has held this band."
    )
    components: list[PulseComponent] = Field(default_factory=list)
    missing: list[str] = Field(
        default_factory=list,
        description=(
            "Inputs that could not be built. Named rather than dropped, so a "
            "client can say what the number is missing instead of quietly "
            "averaging fewer things."
        ),
    )
    history: list[PulsePoint] = Field(
        default_factory=list,
        description="Daily path of the composite — a real series, not a back-fill.",
    )
    breadth_indices: Breadth | None = Field(
        default=None,
        description=(
            "How many headline indices trade above their own 200-session "
            "average. Trend breadth, not today's advance-decline: an index at "
            "a high with a third of its sectors below trend is a narrowing "
            "market, and the index level cannot say so."
        ),
    )
    breadth_sectors: Breadth | None = Field(
        default=None, description="The same over the sector ETFs, 100 sessions."
    )
    stock_bond_correlation: float | None = Field(
        default=None,
        description=(
            "Rolling correlation of SPY and TLT daily returns. The market's "
            "pair, the same for every reader — `/pulse/book` answers the "
            "different question of how THIS basket moves with bonds. Negative "
            "means bonds cushion an equity drawdown; positive means the "
            "diversification a reader thinks they have is not there."
        ),
    )
    stock_bond_correlation_then: float | None = Field(
        default=None, description="The same, a quarter ago — is it drifting?"
    )
    loaded_at: str | None = Field(
        default=None,
        description=(
            "Server clock when this was answered, `YYYY-MM-DD HH:MM UTC` — the "
            "page's 'loaded …' caption. Not `as_of`: that is the market row the "
            "score was quoted from."
        ),
    )
    unavailable: str | None = Field(
        default=None,
        description=(
            "Why the composite could not be built at all: rate_limited | "
            "offline | no_data. Set with a null score and an 'unknown' band, "
            "so a throttle answers 200 and the page keeps its headings."
        ),
    )


class BookBeta(BaseModel):
    """One of the book's secondary betas: to duration, credit or EM.

    Same contract as the equity beta on `PulseBook`: the full-window level is
    the headline, and the drift is the 60-session rolling beta against itself
    a quarter back — never the level against the rolling value, which are two
    windows whose difference is not drift.
    """

    key: str = Field(description="duration | credit | em — the i18n suffix.")
    ticker: str = Field(description="The benchmark regressed against: TLT, HYG, EEM.")
    beta: float | None = None
    rolling: float | None = None
    rolling_then: float | None = None


class PulseBook(BaseModel):
    base: str
    beta: float | None = Field(
        default=None,
        description="Book's beta to the S&P over the whole window — the headline.",
    )
    beta_rolling: float | None = Field(
        default=None, description="The 60-session rolling beta, latest value."
    )
    beta_rolling_then: float | None = Field(
        default=None,
        description=(
            "The same rolling beta a quarter ago. Compare it with "
            "`beta_rolling`, never with `beta`: those two are different windows "
            "and their difference is not drift."
        ),
    )
    stance: str | None = Field(
        default=None,
        description=(
            "amplify | track | cushion — which side of 1 the beta sits, with a "
            "dead band either side so a book at 1.01 does not read as leveraged."
        ),
    )
    bond_correlation: float | None = Field(
        default=None,
        description="Correlation with the long bond: are the bonds still hedging?",
    )
    bond_correlation_then: float | None = None
    usd_share: float | None = Field(
        default=None, description="Share of book value priced in dollars."
    )
    fx_drag: float | None = Field(
        default=None,
        description=(
            "Last month's return that came from currency rather than assets. "
            "Positive is a tailwind. Null when no FX move could be read."
        ),
    )
    currency_weights: dict[str, float] = Field(default_factory=dict)
    rotation_capture: float | None = Field(
        default=None,
        description=(
            "Weight-weighted excess return of the sectors held, over the month. "
            "Positive = the book sat in the sectors that beat the index."
        ),
    )
    sector_tilt: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Active weight per sector against the benchmark. A sector the book "
            "does not hold is a real underweight and is included as one."
        ),
    )
    betas: list[BookBeta] = Field(
        default_factory=list,
        description=(
            "Betas to the long bond, high-yield credit and emerging markets, "
            "on the same EUR-rebased returns as `beta`. A benchmark whose "
            "series did not load keeps its entry with nulls."
        ),
    )
    sector_weights: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "The book's own sector allocation, largest first, including the "
            "buckets no sector ETF tracks (Unknown, a crypto sleeve). What "
            "'your three largest sectors' is read off — the rotation block only "
            "carries the sectors it has a fund for."
        ),
    )
    unavailable: str | None = Field(
        default=None,
        description=(
            "Why the price-derived figures are null: rate_limited | offline | "
            "no_data. The weights need no price feed and are still filled, so "
            "a throttle costs the betas, not the card."
        ),
    )


class MarketTile(BaseModel):
    """One reading on the Home market strip: a level and how far it moved."""

    key: str = Field(description="i18n slug: sp500 | nasdaq | vix | us10y | gold | …")
    symbol: str = Field(description="The Yahoo ticker or FRED id it was read off.")
    group: str = Field(description="equity | risk | rates | fx | commodity | crypto")
    unit: str = Field(
        description=(
            "How `changes` reads: percent (a price move, as a fraction) or "
            "basis_points (a rate's move)."
        )
    )
    value: float | None = None
    changes: dict[str, float] = Field(
        default_factory=dict,
        description="day / week / month, absent where the series is too short.",
    )
    welcome: int = Field(
        default=1,
        description=(
            "+1 a rise is good news, -1 a rise is bad news (VIX, yields), 0 neither."
        ),
    )
    state: str | None = Field(
        default=None, description="up | turning_down | turning_up | down."
    )
    percentile: float | None = Field(
        default=None, description="Where the level sits in its own year (VIX only)."
    )
    linkable: bool = Field(
        default=True,
        description="Whether the symbol has a ticker page (FRED ids do not).",
    )
    as_of: str | None = None


class MarketGlance(BaseModel):
    """What the market did, compressed to one Home card.

    The regime is the Pulse's own composite, not a second opinion; the tiles
    are a fixed handful of the series the Pulse already downloads, with the
    one horizon the Pulse never quotes — the day.
    """

    score: float | None = None
    regime: str = "unknown"
    run: int | None = Field(default=None, description="Sessions in the current band.")
    history: list[float] = Field(
        default_factory=list,
        description="The composite's last 30 readings, oldest first.",
    )
    tiles: list[MarketTile] = Field(default_factory=list)
    breadth: Breadth | None = None
    as_of: str | None = None
    unavailable: str | None = Field(
        default=None,
        description="rate_limited | offline | no_data when the price burst died.",
    )
