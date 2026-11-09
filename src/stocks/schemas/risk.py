"""How risky the book is, how it is split, and where it could be headed."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ----------------------------------------------------------------- how risky
# Today's basket backtested at fixed weights — a profile of what is held now.
# `/portfolio/performance` answers the other question, what the book actually
# did, and the two disagree whenever the book has changed shape.


class AllocationHolding(BaseModel):
    """The part of one holding that sits in a slice, in `base`."""

    ticker: str
    value: float = Field(description="Market value inside this slice.")
    cost: float = Field(description="Cost basis of that same part.")


class AllocationSlice(BaseModel):
    label: str
    weight: float
    value: float | None = Field(
        default=None,
        description=(
            "Market value in `base` of the priced holdings in this slice. Null "
            "when none of them carried a live price."
        ),
    )
    cost: float | None = Field(
        default=None,
        description=(
            "Cost basis of the same rows as `value` — never the whole slice's "
            "basis against a partial value."
        ),
    )
    holdings: list[AllocationHolding] = Field(
        default_factory=list,
        description="What the slice is made of, largest value first.",
    )


class RiskCurves(BaseModel):
    """Return on the money put in over the window, the book against each
    alternative, on one date axis.

    The axis is the basket's own trading days. Every alternative is a shadow
    account fed the book's own cash flows on their own dates — a buy puts the
    same money in, a sale takes it out — and opens at the book's value on the
    window's first day. Rebasing an index to that day instead would invest
    the whole book there at once, which a book built up over time never did,
    and the early rally would be credited to money that arrived later.

    Each line is value over `invested`, minus one: what the book's money
    became, against what the same money would have become there. Fractions,
    not percents — the caller multiplies for display, as it does everywhere
    else in this API.
    """

    dates: list[str] = Field(default_factory=list)
    invested: list[float | None] = Field(
        default_factory=list,
        description=(
            "Net money in on each day, in `base`: the opening value plus every "
            "buy, minus every sale's proceeds. The denominator every line "
            "shares. Null while nothing is in."
        ),
    )
    portfolio: list[float | None] = Field(
        default_factory=list,
        description="The book's own value over `invested`. Null while nothing is in.",
    )
    basket: list[float | None] = Field(
        default_factory=list,
        description=(
            "The same flows put into today's holdings at today's weights. Not "
            "what the book did — what it would have done had it always been "
            "shaped like this."
        ),
    )
    benchmarks: dict[str, list[float | None]] = Field(
        default_factory=dict,
        description="The same flows put into each benchmark, keyed by ticker.",
    )


class RiskName(BaseModel):
    """One held name's own risk, read beside the correlation grid."""

    volatility: float | None = Field(default=None, description="Annualised.")
    betas: dict[str, float] = Field(
        default_factory=dict, description="Beta per benchmark ticker."
    )
    risk_share: float | None = Field(
        default=None,
        description=(
            "Share of the basket's variance this name carries "
            "(w·cov(name, basket) / var(basket)); the shares sum to one. Above "
            "the weight it adds risk, below it diversifies, negative it hedges."
        ),
    )


class Risk(BaseModel):
    base: str
    period: str = Field(description="Window the returns were measured over.")
    volatility: float | None = Field(default=None, description="Annualised.")
    max_drawdown: float | None = None
    var_95: float | None = Field(
        default=None,
        description=(
            "One-day historical VaR at 95% of today's basket over the window, "
            "as a return (<= 0). Null under 60 days."
        ),
    )
    effective_names: float | None = Field(
        default=None, description="1 / HHI — how many equal names it behaves like."
    )
    top5_weight: float | None = None
    betas: dict[str, float] = Field(
        default_factory=dict, description="Beta per benchmark ticker."
    )
    weights: dict[str, float] = Field(
        default_factory=dict,
        description="Market-value weights in `base`; unpriced names drop out.",
    )
    allocation: dict[str, list[AllocationSlice]] = Field(
        default_factory=dict, description="Keyed sector | country | currency | broker."
    )
    correlation: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="Pairwise return correlation, held names."
    )
    names: dict[str, RiskName] = Field(
        default_factory=dict,
        description="Per held name: volatility, beta and share of the risk.",
    )
    curves: RiskCurves | None = Field(
        default=None,
        description=(
            "The flow-matched return lines over this window. Null when the "
            "window holds no measurable return at all."
        ),
    )
    missing: list[str] = Field(
        default_factory=list,
        description=(
            "Held names with no price series, carried at cost inside the "
            "`portfolio` curve. Disclose them under the chart: a line drawn "
            "over part of a book reads as the whole of it."
        ),
    )
    dropped_days: list[str] = Field(
        default_factory=list,
        description=(
            "Days excluded from the `portfolio` curve — a flow the value path "
            "could not price, never a real loss. One of them drags the whole "
            "line negative, so they are dropped and named instead."
        ),
    )


class ProjectionSleeve(BaseModel):
    """One block of the book as the projection moved it."""

    key: str = Field(description="stocks | crypto")
    value: float = Field(description="Today's value of the sleeve, in `base`.")
    weight: float = Field(description="Share of today's value.")
    growth: float = Field(description="Median compound annual return, as used.")
    growth_own: bool = Field(
        default=False, description="True when `growth` is the sleeve's own measured rate."
    )
    own_growth: float | None = Field(
        default=None,
        description=(
            "Compound annual return today's holdings in the sleeve showed (up to "
            "2 years, a year at least); null when too short to annualise."
        ),
    )
    volatility: float = Field(description="Annual, as used.")
    volatility_measured: bool = Field(
        description="True when it is the sleeve's own; false when a default."
    )
    share: float = Field(description="Share of each monthly contribution it gets.")


class ProjectionPlan(BaseModel):
    """What the investor plan says about the inputs, for the page to offer
    and to write back (`PUT /plan/contribution`)."""

    currency: str = Field(description="The plan's currency: the reporting one.")
    monthly: float | None = Field(
        default=None,
        description="The plan's contribution per month, in `base`; null without one.",
    )
    amount: float | None = Field(
        default=None, description="The contribution as stored, in `currency`."
    )
    every: str | None = Field(default=None, description="`monthly` or `quarterly`.")
    day: int | None = None
    crypto_share: float | None = Field(
        default=None,
        description="The mix's crypto target, as a fraction; null without a mix.",
    )
    years: int | None = Field(
        default=None,
        description="The profile's horizon in projection years; null when never saved.",
    )


class Projection(BaseModel):
    """A range for the book's value, month by month, some years out.

    Not a forecast: a spread of outcomes under the assumptions it names, each
    one echoed back so the page can say what it drew. The book moves as two
    sleeves, stocks and crypto, each with its own growth and volatility and
    correlated as they have been. Growth is read as the *median* compound
    annual return — what "4% a year" means to a reader — and defaults to a
    long-run equity figure for stocks and zero for crypto, never the book's
    own past, which would project a lucky stretch forward as a plan — that
    rate is drawn only when asked for, and echoed as `own_growth` either way.
    """

    base: str
    years: int
    start_value: float | None = Field(
        default=None, description="Today's value of the book, in `base`."
    )
    sleeves: list[ProjectionSleeve] = Field(default_factory=list)
    correlation: float | None = Field(
        default=None,
        description="Weekly stocks-crypto correlation used; null if unmeasured.",
    )
    crypto_weight: float = Field(
        default=0.0, description="Crypto's share of today's value."
    )
    monthly: float = Field(description="Contribution added at each month's end.")
    monthly_suggested: float = Field(
        description="Average net monthly money put in over the last 12 months."
    )
    plan: ProjectionPlan | None = Field(
        default=None, description="The investor plan's inputs; null for a guest."
    )
    real: bool = Field(
        default=False, description="True when the future is in today's money."
    )
    inflation: float = Field(description="Annual rate `real` deflates by.")
    target: float | None = None
    target_probability: float | None = Field(
        default=None, description="Share of paths ending at or above `target`."
    )
    dates: list[str] = Field(default_factory=list, description="Month ends, today first.")
    p10: list[float] = Field(default_factory=list)
    p25: list[float] = Field(default_factory=list)
    p50: list[float] = Field(default_factory=list)
    p75: list[float] = Field(default_factory=list)
    p90: list[float] = Field(default_factory=list)
    contributed: list[float] = Field(
        default_factory=list, description="Today's value plus contributions so far."
    )
    history_dates: list[str] = Field(
        default_factory=list,
        description=(
            "Past month ends over the last year (since the first trade if "
            "younger), oldest first; not today."
        ),
    )
    history_value: list[float | None] = Field(
        default_factory=list, description="The book's value at each past month end."
    )
    history_invested: list[float | None] = Field(
        default_factory=list,
        description="Net money put in by each past month end (buys − sale proceeds).",
    )
