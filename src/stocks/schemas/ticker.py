"""One ticker's page: its bars, comparisons, events, position and splits."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from stocks.schemas.assets import Trade

# ------------------------------------------------------------- one ticker's page


class Bars(BaseModel):
    ticker: str
    range: str = Field(description="The requested range label, e.g. 1y.")
    interval: str = Field(
        description=(
            "Bar size the range is drawn at, e.g. 1d — or 1wk/1mo for a max "
            "range too long to draw daily."
        )
    )
    dates: list[str] = Field(
        description=(
            "Exchange-local wall time, no zone — the axis the app draws. "
            "Stamping these UTC slides every session by its own offset."
        )
    )
    series: dict[str, list[float | None]] = Field(
        default_factory=dict,
        description=(
            "Column per series, aligned to `dates`. Null is a genuinely absent "
            "value — an indicator's warm-up, not a zero to plot."
        ),
    )
    dividends: list[float | None] = Field(
        default_factory=list,
        description="Per-bar dividend amount; empty for a ticker that pays none.",
    )
    rangebreaks: list[dict] = Field(
        default_factory=list,
        description=(
            "Axis breaks hiding closed-market time, so bars render contiguous. "
            "Pass straight to the x-axis; empty for a market that trades 24/7."
        ),
    )
    listed: str | None = Field(
        default=None,
        description=(
            "The listing's first trading day (YYYY-MM-DD), or null when Yahoo "
            "did not say and the range cannot tell."
        ),
    )
    ranges: list[str] = Field(
        default_factory=list,
        description=(
            "Range labels worth offering for this listing, in display order: a "
            "window longer than its whole history is dropped, since it would "
            "draw the same bars as `max`. Every label when `listed` is null."
        ),
    )


class Trend(BaseModel):
    """Where the price stands in its own trend and against its home index.

    Fractions, not percentages. Every field is null when the history is too
    short to say, and the whole read is empty for a money-market or bond
    fund, whose price is a yield line, not a trend.
    """

    ticker: str
    state: Literal["up", "down", "mixed"] | None = Field(
        default=None,
        description=(
            "up: above a rising 200-session average; down: below a falling "
            "one; mixed: the two disagree. Null under ~11 months of bars."
        ),
    )
    price: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    sma200_rising: bool | None = Field(
        default=None,
        description="The 200-session average is above where it was a month ago.",
    )
    pct_vs_sma200: float | None = Field(
        default=None, description="Price over its 200-session average, minus one."
    )
    mom_12_1: float | None = Field(
        default=None,
        description=(
            "Return from twelve months ago to one month ago (the last month skipped)."
        ),
    )
    pct_from_high: float | None = Field(
        default=None, description="Distance below the 52-week closing high (<= 0)."
    )
    high_52w: float | None = Field(
        default=None,
        description=(
            "The year's highest daily close. Below the quote's `high_52w`, "
            "which is the highest traded price, intraday included."
        ),
    )
    low_52w: float | None = Field(default=None, description="…and its lowest close.")
    rs_6m: float | None = Field(
        default=None, description="Return minus the home index's over six months."
    )
    rs_12m: float | None = Field(
        default=None, description="Return minus the home index's over twelve months."
    )
    bench: str | None = Field(
        default=None,
        description="The home index's symbol (^IBEX for a Madrid line); null for a coin.",
    )
    bench_name: str | None = None
    rsi14: float | None = Field(
        default=None, description="Context only, never a verdict."
    )
    atr_pct: float | None = Field(
        default=None, description="14-day average true range over the price."
    )
    sessions: int = Field(default=0, description="Daily bars the read stands on.")


class CompareLine(BaseModel):
    ticker: str
    name: str = Field(
        default="",
        description="SEC or watchlist name; empty for an index the app names itself.",
    )
    role: Literal["subject", "index", "sector", "peer", "pick"] = Field(
        description=(
            "Why the line is there: the page's own name, one of the three "
            "indices, its sector's ETF, a related company, or the reader's pick."
        )
    )
    points: list[float | None] = Field(
        description=(
            "Cumulative total return in `base` since the window's first day, a "
            "fraction, aligned to `dates`. Null before the listing has a price."
        )
    )


class CompareOffer(BaseModel):
    ticker: str
    name: str = ""
    role: Literal["index", "sector", "peer"]
    sector: str | None = Field(
        default=None, description="The yfinance sector a `sector` ETF stands for."
    )


class Comparison(BaseModel):
    """Several listings rebased to one day and one currency."""

    ticker: str
    range: str = Field(description="One of 1m, 6m, 1y, 2y.")
    base: str = Field(description="The currency every line is measured in.")
    dates: list[str] = Field(description="The subject's sessions, YYYY-MM-DD.")
    lines: list[CompareLine] = Field(
        default_factory=list,
        description="The subject first, then the asked names in the order asked.",
    )
    offered: list[CompareOffer] = Field(
        default_factory=list,
        description=(
            "What the picker suggests: the indices, the sector's ETF when the "
            "sector is known, and Yahoo's related names."
        ),
    )
    missing: list[str] = Field(
        default_factory=list,
        description=(
            "Asked names left off: no price history for the window, or no rate "
            "into `base` for the currency they are quoted in."
        ),
    )


class EarningsEvent(BaseModel):
    date: str
    eps_estimate: float | None = None
    reported_eps: float | None = Field(
        default=None, description="Null for a date that has not reported yet."
    )
    surprise_pct: float | None = None
    beat: bool | None = Field(
        default=None, description="Null when there is nothing to compare."
    )


class CycleEvent(BaseModel):
    """A dated event in a coin's history the chart marks: a halving, an ETF
    approval, a protocol upgrade."""

    date: str
    kind: str = Field(description="halving | etf | merge.")


class PriceEvents(BaseModel):
    ticker: str
    earnings: list[EarningsEvent] = Field(default_factory=list)
    cycle: list[CycleEvent] = Field(
        default_factory=list, description="A coin's dated events; empty for a share."
    )


class Custodian(BaseModel):
    """One broker holding part of a position, ready to draw as a mark.

    The header prints these beside the "in portfolio" badge, so what a client
    needs is a name and an image rather than a ledger key — resolving a key to
    a brand is a table this API already owns, and a second copy of it in a
    front end is a second thing to keep current.

    `name` is empty for the two buckets that are not brands: a hand-entered row
    (`manual`) and shares no note attributes (`unknown`). Those are localised,
    and a translated string does not belong in a language-neutral payload — the
    client prints `portfolio.broker_manual` / `portfolio.broker_unknown`, the
    same keys the app prints.
    """

    broker: str = Field(description="Ledger note prefix: revolut, clicktrade, manual…")
    name: str = Field(
        default="", description="Brand name; empty for `manual` and `unknown`."
    )
    logo: str | None = Field(
        default=None, description="Same-origin brand logo; null when none resolves."
    )
    shares: float = Field(description="Open shares in this broker's account.")
    share: float = Field(description="Its fraction of the open position, 0..1.")


class TickerPosition(BaseModel):
    ticker: str
    held: bool = Field(description="False when this account holds none of it.")
    shares: float | None = None
    currency: str | None = Field(
        default=None,
        description=(
            "The currency the ticker's chart is quoted in — the priced "
            "listing's own code, minor units included (GBp). Usually the one "
            "the shares were bought in; when an alias prices them off another "
            "venue, the basis and the fills are restated into this one at "
            "each trade date's rate so they sit on the chart's axis."
        ),
    )
    cost_native: float | None = Field(
        default=None, description="Basis in that currency, not the reporting one."
    )
    avg_cost_native: float | None = None
    base: str | None = Field(
        default=None, description="Reporting currency `value` and `weight` are in."
    )
    value: float | None = Field(
        default=None,
        description=(
            "Market value off the book's shared pricing pass. Null means "
            "unknown — a throttled fetch, a symbol with no series — never zero."
        ),
    )
    weight: float | None = Field(
        default=None, description="Share of the book by market value."
    )
    cost_base: float | None = Field(
        default=None,
        description=(
            "Basis in `base`, at each trade date's rate, off the same pricing "
            "pass as `value` — so value minus this is the gain the Portfolio "
            "page prints, FX moves included. Null whenever `value` is."
        ),
    )
    trades: list[Trade] = Field(
        default_factory=list,
        description=(
            "Every buy and sell of this name in the caller's ledger, oldest "
            "first, already scaled to today's shares. Present even when the "
            "position is closed — the chart still marks where it was entered."
        ),
    )
    brokers: dict[str, float] = Field(
        default_factory=dict,
        description="Open shares per broker, for a position split across accounts.",
    )
    custody: list[Custodian] = Field(
        default_factory=list,
        description=(
            "The same split, largest first and ready to draw: brand name, logo "
            "and share of the position. `brokers` stays the raw answer."
        ),
    )


class TickerSplit(BaseModel):
    """One forward split this name's ledger is missing, with its evidence."""

    date: str = Field(description="The split's own day, YYYY-MM-DD.")
    ratio: float = Field(description="Shares out per share in — 20.0 for 20-for-1.")
    held_before: float
    held_after: float
    priced_at: float = Field(description="The pre-split buy price that gave it away.")
    priced_on: str
    market_close: float = Field(description="Yahoo's split-adjusted close that day.")
    currency: str
    declined: bool = Field(
        default=False,
        description=(
            "This split was written once and the reader undid it. A client "
            "repairing on its own must leave it alone: the reader has already "
            "said no, and writing it back on every visit is an argument."
        ),
    )


class TickerSplits(BaseModel):
    ticker: str
    splits: list[TickerSplit] = Field(default_factory=list)
    throttled: bool = Field(
        default=False,
        description="Yahoo was refusing us: an empty list means 'could not tell'.",
    )


class TickerSplitsApplied(BaseModel):
    ticker: str
    change_id: int = Field(
        description="The journal entry — `DELETE /v1/portfolio/changes/{id}` undoes it."
    )
    splits: list[TickerSplit] = Field(default_factory=list)


class TickerSplitPick(BaseModel):
    model_config = {"extra": "forbid"}

    dates: list[str] = Field(
        min_length=1,
        max_length=20,
        description="Which of the scanned splits to write, by their YYYY-MM-DD.",
    )
