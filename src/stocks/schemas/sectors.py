"""The cohort a holding sits in, and how it compares there."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- the cohort
# A sector's comparable set, scanned nightly. The scores are percentile ranks
# within the cohort on valuation and quality only — no momentum, no analyst
# targets, no margin of safety — which is why `podium` ships with the caveat
# attached rather than as a bare list of three winners.


class SectorSummary(BaseModel):
    sector: str = Field(description='As `info["sector"]` spells it.')
    etf: str = Field(default="", description="The ETF whose basket seeds the cohort.")
    as_of: str | None = Field(
        default=None, description="Date of the scan; null when never scanned."
    )
    cohort: int = Field(default=0, description="Names in the scanned cohort.")
    podium: list[str] = Field(
        default_factory=list, description="Best three of the cohort, best first."
    )
    tech_podium: list[str] = Field(
        default_factory=list,
        description=(
            "Best three on technical momentum (trend, RSI, MACD, 52-week high, "
            "3-month return, volume) — a separate ranking from `podium`, which "
            "is valuation and quality only."
        ),
    )


class Sectors(BaseModel):
    sectors: list[SectorSummary] = Field(default_factory=list)


class CohortJudged(BaseModel):
    """Where the Review page would put a cohort name: the outside-name read
    (`review.judge_candidate`), the same scores and bars as its map, so a
    company sits on one spot on both pages."""

    verdict: str = Field(description="buy | watch | pass | bet | unrated")
    reasons: list[str] = Field(default_factory=list)
    quality: float | None = Field(default=None, description="0-100; null unscored.")
    cheapness: float | None = Field(default=None, description="0-100; null unscored.")
    metrics: dict[str, float | None] = Field(
        default_factory=dict, description="The KPIs the Review page shows, by key."
    )


class CohortRow(BaseModel):
    ticker: str
    currency: str | None = Field(
        default=None,
        description="Listing currency of the money metrics (price, market cap, EV, FCF).",
    )
    score: float | None = Field(
        default=None, description="Percentile rank in this cohort, 0-1; null if unranked."
    )
    rank: int | None = Field(
        default=None, description="Place on the requested sort, 1-based."
    )
    metrics: dict[str, float | None] = Field(
        default_factory=dict,
        description="Raw numbers, keyed as `metric_keys`. A missing one is null.",
    )
    judged: CohortJudged | None = Field(
        default=None,
        description=(
            "The Review page's read of the name as a new buy, for the quality "
            "against price map. Fundamentals rows only; null on `tech_rows`."
        ),
    )


class SectorCohort(BaseModel):
    sector: str
    etf: str = ""
    as_of: str | None = None
    sort: str = Field(description="Metric the rows are ordered by.")
    ascending: bool
    podium: list[str] = Field(default_factory=list)
    rows: list[CohortRow] = Field(default_factory=list)
    tech_podium: list[str] = Field(
        default_factory=list, description="Best three on technical momentum."
    )
    tech_rows: list[CohortRow] = Field(
        default_factory=list,
        description=(
            "One row per cohort ticker with an OHLC history, scored and keyed "
            "the same way as `rows` but over the technical metrics "
            "(trend_pct, rsi14, macd_hist, pct_from_high, roc_63, vol_ratio) "
            "rather than `metric_keys`."
        ),
    )
    metric_keys: list[str] = Field(
        default_factory=list, description="Every metric a row can carry, in order."
    )
    default_columns: list[str] = Field(
        default_factory=list, description="The subset a table shows before choosing."
    )
    lower_is_better: list[str] = Field(
        default_factory=list,
        description=(
            "Metrics where a smaller number is the better one — cheaper, less "
            "levered, less dilutive. A client sorting without this puts the "
            "worst rows on top."
        ),
    )
