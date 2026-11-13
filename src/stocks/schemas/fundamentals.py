"""What a company is worth and who says so: KPIs, valuation, moat,
insiders, shorts and analysts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ------------------------------------------------- fundamentals, moat, insiders


class Kpi(BaseModel):
    key: str = Field(description="`analysis.fundamentals.KPI_SOURCES` key.")
    label: str
    value: float | str | None = Field(
        default=None, description="The raw figure. Null where the data is missing."
    )
    formatted: str = Field(description='Ready to print, with units; "n/a" when absent.')
    unit: str = Field(description="x | pct | money | ratio.")
    level: str = Field(
        description=(
            "fact | consensus | derived — where the number comes from. Print it: "
            "a consensus figure shown as a fact is somebody's forecast wearing "
            "a filing's authority."
        )
    )
    verdict: str | None = Field(
        default=None, description="cheap | fair | expensive, where a band exists."
    )
    verdict_tone: str | None = Field(
        default=None,
        description=(
            "green | orange | red | gray — how the verdict should read, as the "
            "domain bands it. Shipped beside the label because the labels are a "
            "growing set ('net cash', 'buybacks', 'heavy dilution'): a client "
            "colouring by label needs a new rule per band it has never seen, "
            "and silently shows the newest one as neutral."
        ),
    )
    desc: str = ""
    peer_band: list[float] | None = Field(
        default=None,
        description=(
            "The rivals' [P25, median, P75] (`Metrics.peers`), raw like `value`. "
            "Only on the grid's ratios, and only with three rivals reporting it."
        ),
    )


class TickerJudged(BaseModel):
    """The Review page's verdict on a company read as a new buy: the same
    scores and reasons as its outside rows, so a name reads alike on both
    pages. A held name's verdict depends on its weight, which is the Review
    page's to draw."""

    verdict: str = Field(description="buy | watch | pass | bet | unrated")
    reasons: list[str] = Field(
        default_factory=list, description="Codes; print `review.reason_<code>`."
    )
    quality: float | None = Field(default=None, description="0-100; null unscored.")
    cheapness: float | None = Field(default=None, description="0-100; null unscored.")
    implied_growth: float | None = Field(
        default=None,
        description=(
            "Ratio: the owner's free cash flow's yearly growth, for ever, the "
            "price pays for at `review.HURDLE`; null off the standard lens."
        ),
    )
    past_growth: float | None = Field(
        default=None,
        description="Ratio: the lower of the cash flow's and the sales' multi-year pace.",
    )


class MetricTile(BaseModel):
    """One tile of the company grid: which KPI, and what to call it.

    The labels are i18n *key names*, never strings. Translating here would mean
    this API had a language, and it deliberately does not — a client that has
    no catalog entry for the key falls back to the KPI's own English label.
    """

    key: str = Field(description="The `Kpi.key` this tile shows.")
    label_key: str = Field(description="i18n key for its caption, e.g. ticker.kpi_roic.")
    help_key: str | None = Field(
        default=None, description="i18n key overriding the KPI's description."
    )


class PeerScope(BaseModel):
    """The rivals a company grid reads its middle off: the nightly scan's."""

    kind: str = Field(description="industry | sector — which cohort it fell back to.")
    name: str = Field(description="Yahoo's industry or sector name, in English.")
    count: int = Field(description="How many names the cohort holds, subject left out.")


class Metrics(BaseModel):
    ticker: str
    currency: str | None = None
    quote_type: str | None = Field(
        default=None, description="EQUITY | ETF | MUTUALFUND, as Yahoo classifies it."
    )
    kpis: list[Kpi] = Field(default_factory=list)
    grid: list[MetricTile] = Field(
        default_factory=list,
        description=(
            "The handful of KPIs a company page shows, in order "
            "(`fundamentals.fundamental_tiles(lens)`). `kpis` carries the rest; a page "
            "drawing every one of them is a reference table, not a screen."
        ),
    )
    lens: str = Field(
        default="standard",
        description=(
            "standard | financial | real_estate | utility — which ratios judge "
            "the business (`review.lens`), and so which `grid`."
        ),
    )
    peers: PeerScope | None = Field(
        default=None,
        description="Whose middle `Kpi.peer_band` is. Null when the scan has none.",
    )
    normal_pe: float | None = Field(
        default=None,
        description=(
            "Trailing P/E on the median operating margin, when today's margin is "
            "a cycle's peak (`review.peak_pe`). Null otherwise."
        ),
    )
    reported_pe: float | None = Field(
        default=None,
        description=(
            "Trailing P/E on reported earnings, one-offs and all, when `pe_ttm` is "
            "on normalized income instead (`fundamentals.ONE_OFF_SHARE`). Null "
            "otherwise."
        ),
    )
    cautions: list[str] = Field(
        default_factory=list,
        description=(
            "The review's warning codes on this company (`review.cautions`); a "
            "client prints `review.reason_<code>`."
        ),
    )
    judged: TickerJudged | None = Field(
        default=None,
        description=(
            "The Review page's read of this company as a new buy "
            "(`review.judge_candidate`). Null for a fund."
        ),
    )
    market_cap_base: float | None = Field(
        default=None,
        description=(
            "Market cap converted to the caller's reporting currency, when the "
            "company quotes in another one. Null when no conversion applies or "
            "the rate could not be fetched."
        ),
    )
    market_cap_base_formatted: str | None = Field(
        default=None,
        description=(
            "…the same figure through `format_value`, so every client prints "
            "one market cap the same way rather than two roundings of it."
        ),
    )
    fx_rate: float | None = Field(default=None, description="The rate used.")
    fx_as_of: str | None = Field(default=None, description="…and its date.")
    base: str | None = Field(default=None, description="The reporting currency.")


class AnnualRow(BaseModel):
    year: str
    revenue: float | None = None
    net_income: float | None = None
    eps: float | None = None


class ProjectedRow(BaseModel):
    period: str = Field(description='Label relative to the last reported year, "2027E".')
    revenue: float | None = None
    revenue_low: float | None = None
    revenue_high: float | None = None
    eps: float | None = None
    eps_low: float | None = None
    eps_high: float | None = None
    revenue_extrapolated: bool = Field(
        default=False,
        description=(
            "The period ran past the last published estimate and was carried "
            "forward on a growth rate — a guess, not a poll of analysts. The "
            "*Low/*High range is null once this is true."
        ),
    )
    eps_extrapolated: bool = False


class Financials(BaseModel):
    ticker: str
    currency: str | None = None
    annual: list[AnnualRow] = Field(default_factory=list)
    quarterly_eps: list[dict] = Field(
        default_factory=list,
        description=(
            '[{"period": "2024Q1", "eps": 1.53}, …]. `period` is the fiscal '
            'quarter: "FY2027Q2" when the fiscal year does not end in December.'
        ),
    )
    projection: list[ProjectedRow] = Field(
        default_factory=list,
        description=(
            "Sell-side consensus, not fact — the `level` on every KPI says the "
            "same thing, and a chart that draws these beside reported years has "
            "to mark them."
        ),
    )
    estimate_currency: str | None = None
    source: str | None = Field(
        default=None,
        description=(
            "Where the annual rows were audited when a primary source replaced "
            "Yahoo's: \"ESEF\" (the issuer's own filed annual report, EU/UK). "
            "Null = Yahoo's figures."
        ),
    )
    source_years: list[str] = Field(
        default_factory=list,
        description="Fiscal year ends that primary source covers, newest first.",
    )


class ValuationWindow(BaseModel):
    window: str = Field(description="e.g. 5y.")
    days: int = Field(
        default=0,
        description=(
            "Its span in calendar days, so a client can trim the series to the "
            "window it is showing without a table of its own."
        ),
    )
    mean: float | None = None
    median: float | None = None
    low: float | None = None
    high: float | None = None
    percentile: float | None = Field(
        default=None, description="Where today's P/E sits in the window, 0-100."
    )
    premium: float | None = Field(
        default=None, description="current / mean − 1. Positive = richer than usual."
    )


class Valuation(BaseModel):
    ticker: str
    source: str | None = Field(
        default=None,
        description=(
            "Which filing feed backed the reconstruction — SEC EDGAR, FMP, or "
            "null when neither yields quarterly EPS. Print it: a multiple with "
            "no provenance is a number somebody will act on."
        ),
    )
    current: float | None = None
    current_verdict: str | None = Field(
        default=None,
        description=(
            "Today's P/E on the KPI grid's own cheap/fair/expensive bands "
            "(`verdict('pe_ttm', current)`), so the chip under it matches the "
            "grid's reading of the same kind of number. Null with no band."
        ),
    )
    current_tone: str | None = None
    dates: list[str] = Field(default_factory=list)
    pe: list[float | None] = Field(default_factory=list)
    windows: list[ValuationWindow] = Field(default_factory=list)


class Dcf(BaseModel):
    ticker: str
    reason: str | None = Field(
        default=None,
        description=(
            "Why there is no value: `negative_fcf`, `lens` (a bank, insurer, "
            "REIT or utility), `not_equity` or `no_data`. Null when valued."
        ),
    )
    currency: str | None = None
    price: float | None = None
    fcf: float | None = Field(
        default=None,
        description="Base-year free cash flow to the firm, in the quote currency.",
    )
    net_debt: float | None = None
    shares: float | None = Field(default=None, description="Diluted shares.")
    growth: float | None = Field(
        default=None, description="Explicit five-year growth the value starts from."
    )
    growth_source: str | None = Field(
        default=None, description="`fcf_cagr`, `revenue_cagr` or `fallback`."
    )
    wacc: float
    terminal: float
    value: float | None = None
    upside: float | None = Field(default=None, description="value / price - 1.")
    waccs: list[float] = Field(default_factory=list)
    terminals: list[float] = Field(default_factory=list)
    grid: list[list[float | None]] = Field(
        default_factory=list,
        description="Per-share value, one row per WACC, one column per terminal "
        "growth; null where terminal growth >= WACC.",
    )


class MoatPillar(BaseModel):
    """One pillar, with its English words and the keys to word it otherwise.

    Like `MetricTile`, the API names i18n keys rather than translating: a
    client words `detail_key` with `facts` (fractions as fractions, counts as
    ints) and falls back to `label` / `detail` when its catalog lacks the key.
    """

    key: str
    label: str
    label_key: str = Field(
        description="i18n key for its name, e.g. ticker.moat_pillar_roic."
    )
    score: float | None = Field(default=None, description="0-100; null when unscored.")
    tone: str | None = Field(
        default=None,
        description="The moat band's colour at this score (green | orange | red).",
    )
    weight: float
    detail: str = Field(description="What the score was computed from, in English.")
    detail_key: str = Field(description="i18n key for `detail`, filled from `facts`.")
    facts: dict[str, float] = Field(default_factory=dict)


class Moat(BaseModel):
    ticker: str
    score: float | None = Field(
        default=None,
        description="Weighted composite 0-100; null when too few pillars scored.",
    )
    rating: str | None = Field(default=None, description="wide | narrow | no moat.")
    rating_key: str | None = Field(
        default=None, description="i18n key for `rating`, e.g. ticker.moat_rating_wide."
    )
    rating_tone: str | None = Field(
        default=None,
        description=(
            "The colour the domain's moat band carries (green | orange | red), "
            "so a client tints the rating chip without keeping its own copy of "
            "the thresholds. Null with no score."
        ),
    )
    years: int = Field(description="Annual statement years backing the score.")
    pillars: list[MoatPillar] = Field(default_factory=list)


class InsiderSummary(BaseModel):
    window_days: int
    buy_count: int = 0
    sell_count: int = 0
    buy_shares: float = 0.0
    sell_shares: float = 0.0
    buy_value: float = 0.0
    sell_value: float = 0.0
    buyers: int = Field(default=0, description="Distinct insiders with ≥1 buy.")
    sellers: int = 0
    net_value: float = Field(
        default=0.0, description="Buy value minus sell value; positive = net buying."
    )
    cluster_buy: bool = Field(
        default=False,
        description=(
            "Two or more distinct insiders buying, outweighing the sells. The "
            "signal the page calls out: one director buying is a person, three "
            "is a view."
        ),
    )


class InsiderTrade(BaseModel):
    date: str | None = None
    insider: str
    role: str
    code: str = Field(description="Raw Form 4 code: P buy, S sell, A grant, M exercise.")
    label: str = Field(
        default="",
        description=(
            "The code in English words (`insiders.CODE_LABELS`) — the fallback "
            "for a client whose catalog has no entry for `code`, so an unmapped "
            "code still reads as a word rather than a letter."
        ),
    )
    shares: float = Field(description="Signed: negative for a disposition.")
    price: float | None = None
    value: float | None = Field(
        default=None,
        description=(
            "Signed notional in `currency`, or null with no price. Never added "
            "across rows without checking that currency: Form 4 is in USD and "
            "the EU regulators publishing the same disclosure report in EUR."
        ),
    )
    is_open_market: bool = Field(
        default=False,
        description=(
            "A real purchase or sale (Form 4 codes P/S), as opposed to a grant "
            "or an option exercise. Only these say anything about conviction."
        ),
    )
    currency: str | None = None


class ShortHolderRow(BaseModel):
    name: str
    pct: float = Field(description="Net short position, percent of issued shares.")
    date: str | None = Field(default=None, description="Position date, ISO.")


class UsShortInterest(BaseModel):
    pct_float: float | None = Field(
        default=None,
        description="Percent of the float sold short.",
    )
    shares_short: float | None = None
    days_to_cover: float | None = Field(
        default=None,
        description="Shares short over average daily volume (Yahoo shortRatio).",
    )
    change_pct: float | None = Field(
        default=None,
        description="Shares short vs the prior reporting period, percent.",
    )
    as_of: str | None = Field(
        default=None,
        description="Settlement date of the figure, ISO.",
    )
    volume_ratio: float | None = Field(
        default=None,
        description=(
            "FINRA Reg SHO: percent of recent trading volume that was a short sale. "
            "Volume, not a position: market making puts it near 40-50 % for most names."
        ),
    )
    volume_days: int | None = None
    volume_as_of: str | None = None


class EuShortPositions(BaseModel):
    source: str = Field(description="AFM | BaFin | FCA")
    issuer: str
    total_pct: float = Field(
        description="Sum of the disclosed net short positions, percent.",
    )
    as_of: str | None = Field(default=None, description="Latest position date, ISO.")
    holders: list[ShortHolderRow] = Field(
        default_factory=list,
        description="Largest first; empty for the FCA, which gives only the total.",
    )
    holders_count: int = 0


class Shorts(BaseModel):
    ticker: str
    us: UsShortInterest | None = None
    eu: EuShortPositions | None = Field(
        default=None,
        description=(
            "Positions of 0.5 % or more disclosed under the EU Short Selling Regulation. "
            "Null when the register does not cover the name or is not loaded yet, "
            "never a claim "
            "that nobody is short."
        ),
    )


class Insiders(BaseModel):
    ticker: str
    source: str | None = Field(
        default=None, description="SEC | BaFin | CNMV | null when none covers this name."
    )
    summary: InsiderSummary | None = Field(
        default=None,
        description=(
            "Open-market buys vs sells only (codes P/S) — grants, exercises and "
            "tax withholding are excluded, so the net is discretionary and not "
            "grant noise."
        ),
    )
    trades: list[InsiderTrade] = Field(default_factory=list)
    sec_filer: bool | None = Field(
        default=None,
        description=(
            "Whether the SEC's ticker map knows this symbol; null when the "
            "lookup failed. An empty list means two very different things — a "
            "US filer whose insiders have not traded, or a foreign issuer that "
            "never files Form 4 — and only this tells them apart."
        ),
    )


class AnalystMonth(BaseModel):
    """One month of the sell-side rating split."""

    month: str = Field(description='Calendar month, "YYYY-MM".')
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0
    total: int = 0
    mean: float | None = Field(
        default=None, description="1 (strong buy) .. 5 (strong sell)."
    )


class AnalystTargets(BaseModel):
    """The 12-month price targets, in the quote's currency. Consensus."""

    low: float | None = None
    median: float | None = None
    mean: float | None = None
    high: float | None = None
    upside_mean: float | None = Field(
        default=None, description="Mean target over the price, minus one."
    )
    upside_median: float | None = Field(
        default=None,
        description="The same against the median, which one outlier cannot drag.",
    )
    dispersion: float | None = Field(
        default=None,
        description="(high - low) / mean: how far apart the analysts are.",
    )


class EpsRevisionRow(BaseModel):
    """One fiscal year's EPS consensus against itself 7/30/60/90 days ago."""

    period: str = Field(description='"0y" (current FY) or "+1y" (next FY).')
    current: float | None = None
    change_7d: float | None = None
    change_30d: float | None = None
    change_90d: float | None = None
    up_7d: int | None = None
    up_30d: int | None = None
    down_7d: int | None = None
    down_30d: int | None = None


class RatingChange(BaseModel):
    """One firm's move on a share: a new grade or a new price target."""

    date: str
    firm: str
    action: Literal["upgrade", "downgrade", "initiated", "reiterated"]
    from_grade: str | None = None
    to_grade: str | None = None
    target: float | None = Field(default=None, description="New price target.")
    prior_target: float | None = None
    target_move: Literal["raised", "lowered", "set"] | None = None


class OptionsView(BaseModel):
    """What the listed options say: implied volatility and the put/call mix.

    Market-implied, not a forecast. Null `iv` / ratios when the chain is too
    thin to read; the route answers an empty body for a name with no options.
    """

    ticker: str
    listed: bool = Field(description="False when the name has no listed options.")
    iv: float | None = Field(
        default=None,
        description="Annualised at-the-money implied volatility, 0.32 = 32 %.",
    )
    iv_expiry: str | None = Field(default=None, description="The expiry it is read at.")
    iv_days: int | None = Field(default=None, description="Days to that expiry.")
    put_call_oi: float | None = Field(
        default=None, description="Put open interest over call open interest."
    )
    put_call_volume: float | None = Field(
        default=None, description="Put volume over call volume, today's session."
    )
    open_interest: int = 0
    expiries: int = Field(default=0, description="Expiries the ratios sum over.")


class Analysts(BaseModel):
    """What the sell side says about a share: verdict, targets, revisions.

    All of it consensus — an aggregate of opinions with the sell side's
    incentives, never a fact — and `covered` false when too few analysts
    publish for any of it to be a consensus at all.
    """

    ticker: str
    currency: str | None = Field(
        default=None, description="The quote's currency, which the targets are in."
    )
    price: float | None = Field(
        default=None, description="The price the targets were measured against."
    )
    analysts: int = Field(
        default=0, description="Ratings in the latest month; 0 when nobody covers it."
    )
    covered: bool = Field(
        default=False, description="At least MIN_COVERAGE ratings this month."
    )
    min_coverage: int = 3
    rating: str | None = Field(
        default=None,
        description='"strong buy" | "buy" | "hold" | "sell" | "strong sell".',
    )
    rating_mean: float | None = None
    months: list[AnalystMonth] = Field(
        default_factory=list, description="Oldest month first."
    )
    targets: AnalystTargets | None = None
    revisions: list[EpsRevisionRow] = Field(default_factory=list)
    changes: list[RatingChange] = Field(
        default_factory=list,
        description=(
            "Recent upgrades, downgrades, initiations and price-target changes, "
            "newest first. Empty when Yahoo lists none, which is most non-US names."
        ),
    )


class KpiSourceRow(BaseModel):
    key: str
    label: str
    unit: str = Field(
        description=(
            "How the raw number reads: `pct` (a fraction shown as a "
            "percentage), `x` (a multiple), `money`, `score`, `ratio`. Sent "
            "because nothing else on the wire says it — a client formatting "
            "`roic` and `pe_ttm` the same way prints one of them wrong, and "
            "the alternative is every client carrying its own copy of this "
            "table and drifting from it."
        )
    )
    level: str = Field(description="fact | consensus | derived.")
    loader: str = Field(description="Where this toolkit loads the figure from.")
    verify: str = Field(description="Where to cross-check it before acting on it.")
    note: str = ""
    desc: str = ""


class KpiSources(BaseModel):
    kpis: list[KpiSourceRow] = Field(default_factory=list)
