"""Sell or add: the review rows, the plan they are held to, and returns."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ------------------------------------------------------------------- review


class EntryCheck(BaseModel):
    """One line of the reader's entry checklist read on one name
    (`portfolio.entry.Reading`)."""

    rule: str = Field(description="One of `stocks.portfolio.entry.RULES`.")
    level: float = Field(description="As written: a percent or a multiple.")
    value: float | None = Field(
        description="The name's figure, same unit; null if unknown."
    )
    state: str = Field(description="pass | fail | unknown.")


class EntryFit(BaseModel):
    """The reader's entry checklist read on one company, for its page."""

    ticker: str
    set: bool = Field(False, description="Whether the reader keeps a checklist.")
    met: int = 0
    failed: int = 0
    unknown: int = 0
    total: int = 0
    lines: list[EntryCheck] = Field(default_factory=list)


class ReviewRow(BaseModel):
    """One name on the Review page, held or not, and what to do about it."""

    ticker: str = Field(description="As stored in the book or as asked for.")
    symbol: str = Field(description="The Yahoo symbol the fundamentals came from.")
    kind: str | None = Field(
        default=None,
        description="Asset kind (`stocks.data.asset_kind`); null if unknown.",
    )
    sector: str | None = Field(
        default=None,
        description="Yahoo's sector name (English); null for a fund or unknown.",
    )
    country: str | None = Field(
        default=None,
        description="Yahoo's country name (English); null for a fund or unknown.",
    )
    currency: str | None = Field(
        default=None,
        description="ISO currency the name is quoted in (GBp folded to GBP).",
    )
    held: bool
    verdict: str = Field(
        description=(
            "Held: sell | trim | hold | add | bet | core | cash | unrated. "
            "Outside the book: buy | watch | bet | pass | unrated. `bet` is a "
            "business still proving its product, never scored. A key; the "
            "client has the words."
        )
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Reason codes, strongest first (`analysis.review`).",
    )
    quality: float | None = Field(default=None, description="0-100; null if unscored.")
    cheapness: float | None = Field(default=None, description="0-100; null if unscored.")
    metrics: dict[str, float | None] = Field(default_factory=dict)
    value: float | None = Field(default=None, description="Held value, base currency.")
    price: float | None = Field(
        default=None,
        description=(
            "Last price of ONE held share, in `currency` — the one its market "
            "quotes it in, not the base. Null for an outside name, an unpriced "
            "row, or when the pair to convert back could not be read."
        ),
    )
    weight: float | None = Field(
        default=None, description="Share of the priced book, 0-1."
    )
    risk_share: float | None = Field(
        default=None, description="Share of the book's volatility, 0-1."
    )
    pnl: float | None = Field(
        default=None, description="Unrealised gain or loss, base currency."
    )
    pnl_pct: float | None = None
    target_weight: float | None = Field(
        default=None,
        description="Where the verdict takes the weight; null if it moves nothing.",
    )
    delta: float | None = Field(
        default=None,
        description="Base-currency amount to buy (+) or sell (-) to reach the target.",
    )
    new_money: float | None = Field(
        default=None,
        description=(
            "Base-currency amount an add would take that the plan's sales do "
            "not pay for: what new money would buy, beyond `delta`."
        ),
    )
    tax: float | None = Field(
        default=None,
        description=(
            "Extra tax the sale would add to this year's bill, in the "
            "jurisdiction's currency; negative saves tax. Null when not a sale "
            "or the replay could not price it."
        ),
    )
    buy_after: str | None = Field(
        default=None,
        description=(
            "ISO day a buy stops blocking an earlier loss sale (the "
            "repurchase window); null when nothing blocks it."
        ),
    )
    watched: bool = Field(
        default=False, description="On the account's watchlist, held or not."
    )
    favorite: bool = Field(default=False, description="Starred on the watchlist.")
    lists: list[str] = Field(
        default_factory=list,
        description="The watchlist groups (tags) the name is filed under.",
    )
    entry: list[EntryCheck] = Field(
        default_factory=list,
        description=(
            "An add or a buy only: the reader's entry checklist read on it, "
            "every line. It warns, never changes the verdict."
        ),
    )


class ReviewPlan(BaseModel):
    """The moves added up: what the sales free, what the buys take, the tax."""

    sells: float = 0.0
    buys: float = 0.0
    tax: float | None = None
    tax_currency: str = ""
    new_money: float = Field(
        default=0.0,
        description="The rows' `new_money` added up: adds that wait for new cash.",
    )


class ReviewNote(BaseModel):
    """One thing the page says about the book as a whole."""

    key: str = Field(
        description=(
            "`review.note_<key>`: few_names, sector_heavy, crypto_heavy, "
            "tax_offset, country_heavy, currency_heavy, fund_core, cash_heavy, "
            "plan_over, plan_under."
        )
    )
    count: int | None = Field(default=None, description="Names it counts.")
    sector: str | None = Field(default=None, description="Yahoo's sector name, English.")
    weight: float | None = Field(default=None, description="Its share of the book.")
    amount: float | None = Field(
        default=None, description="Money, in the tax jurisdiction's currency."
    )
    tickers: list[str] = Field(default_factory=list, description="The names it is about.")
    day: str | None = Field(
        default=None, description="ISO day a repurchase stops undoing the loss."
    )
    country: str | None = Field(default=None, description="Yahoo's country, English.")
    currency: str | None = Field(default=None, description="ISO quote currency.")
    bucket: str | None = Field(
        default=None,
        description=(
            "The investor plan's bucket: stocks, equity_funds, bonds, cash, crypto."
        ),
    )
    target: float | None = Field(
        default=None, description="The share of the book the plan gives `bucket`."
    )


class ReviewDrift(BaseModel):
    """A bucket of the book outside the band the investor plan keeps it in."""

    bucket: str
    weight: float = Field(description="Its share of the book today.")
    target: float = Field(description="The share the plan gives it.")
    side: Literal["over", "under"]


class ReviewInvestorPlan(BaseModel):
    """How the reader's own plan (`/prefs/plan`) shaped this page."""

    set: bool = Field(default=False, description="The account has saved a plan.")
    limits_used: bool = Field(
        default=False,
        description="A cap from the plan replaced one of the page's own lines.",
    )
    drift: list[ReviewDrift] = Field(default_factory=list)
    next_contribution: str | None = Field(
        default=None, description="ISO day of the next scheduled contribution."
    )
    contribution: float | None = Field(
        default=None,
        description="Its amount in `base`: part of what `new_money` is sized to.",
    )
    cash: float | None = Field(
        default=None,
        description=(
            "The uninvested cash the plan states, in `base`: counted in the "
            "mix's cash bucket and spent by `new_money` with the contribution."
        ),
    )


class ReviewLines(BaseModel):
    """The weights this book's verdicts were drawn at: some scale with how
    many companies it holds, so the copy quotes them rather than constants."""

    concentrated: float | None = Field(
        default=None,
        description="One company from here is a concentration; None with too few.",
    )
    small: float = Field(description="A held company under this is a crumb.")
    add_to: float = Field(description="Where an add takes a mature company.")
    sector: float = Field(description="One sector from here is named and not added to.")


class ScorePoint(BaseModel):
    """Where a name sat on the review's map on the day a window opens."""

    quality: float = Field(description="0-100, the engine's quality score.")
    cheapness: float = Field(description="0-100, the engine's cheapness score.")
    source: Literal["record", "filings", "price"] = Field(
        description=(
            "`record`: the scores the review gave it that day. `filings`: none "
            "was recorded, so the business as its filings stood that day, at "
            "that day's share price. `price`: no filing goes back that far, so "
            "today's business at that day's share price."
        )
    )


class NameReturns(BaseModel):
    ticker: str
    returns: dict[str, float | None] = Field(
        description=(
            "Total return in `base` per window (1m, 6m, 1y, 2y), a fraction. "
            "Null where the listing has no price that far back."
        )
    )
    sector_etf: str | None = Field(
        default=None,
        description="The ETF its sector is measured by; null for a fund or a coin.",
    )
    then: dict[str, ScorePoint] = Field(
        default_factory=dict,
        description=(
            "Per window, where the name sat on the map the day it opened, plus "
            "`18m`: the map's trail steps back half a year at a time (2y, 18m, "
            "1y, 6m). A window is missing when it cannot be placed (no score "
            "today, no price that far back). Empty for the benchmarks."
        ),
    )


class ReviewReturns(BaseModel):
    """What each name on the review returned, beside what the index did."""

    base: str = Field(description="The currency every return is measured in.")
    as_of: str = Field(description="The day every window ends on, YYYY-MM-DD.")
    names: list[NameReturns] = Field(
        default_factory=list, description="The asked names, in the order asked."
    )
    benchmarks: list[NameReturns] = Field(
        default_factory=list,
        description="SPY, then each sector ETF a name points at, same windows.",
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Asked names with no history or no rate into `base`.",
    )
    pending: int = Field(
        default=0,
        description=(
            "Names whose download missed the time budget: neither measured nor "
            "missing. They keep loading, and asking again finds them."
        ),
    )


class Review(BaseModel):
    base: str
    as_of: str
    locked: bool = Field(
        default=False,
        description=(
            "The account has no import of its own (demo rows do not count): "
            "nothing is judged, and the page shows `/review/preview` behind "
            "an import wall."
        ),
    )
    total: float | None = Field(
        default=None, description="Priced book value, base currency."
    )
    held: list[ReviewRow] = Field(default_factory=list)
    candidates: list[ReviewRow] = Field(default_factory=list)
    plan: ReviewPlan = Field(default_factory=ReviewPlan)
    unpriced: int = 0
    jurisdiction: str = ""
    tax_status: str = Field(
        default="chosen",
        description=(
            "How the jurisdiction was settled: chosen on the Profile page, or "
            "assumed (unknown | unmodelled | region) and the page says so."
        ),
    )
    added: list[str] = Field(
        default_factory=list, description="The `add` tickers, as understood."
    )
    lines: ReviewLines | None = None
    investor_plan: ReviewInvestorPlan = Field(default_factory=ReviewInvestorPlan)
    pending: int = Field(
        default=0,
        description=(
            "Names whose figures missed the answer's time budget: read "
            "unrated here, still being fetched; ask again in a few seconds."
        ),
    )
    notes: list[ReviewNote] = Field(
        default_factory=list,
        description=(
            "Book-level notes: one or two companies carrying the book, one "
            "sector carrying 40% of it, one country or quote currency carrying "
            "most of it, funds or idle cash past their lines, coins past a "
            "quarter of it, losses that would cut the plan's tax."
        ),
    )
