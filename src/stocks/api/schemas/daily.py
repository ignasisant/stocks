"""The daily glance: the briefing card, the market card, movers, extremes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ------------------------------------------------------------- the daily glance
# What the dashboard opens with. The briefing is prose a model wrote; the two
# below it are arithmetic over prices already in hand.


class DailyItem(BaseModel):
    """One line of the daily card."""

    key: str = Field(description="The trigger it is about, e.g. `earnings:NVDA`.")
    kind: str = Field(
        default="", description="The trigger's kind; empty for a context line."
    )
    line: str
    tickers: list[str] = Field(default_factory=list)
    go: str = Field(
        default="",
        description="The page that resolves it, as a shell path with its "
        "query (`/review`, `/profile?tab=plan`); empty for a context line.",
    )
    section: Literal["alerts", "watch"] = Field(
        default="watch",
        description=(
            "Where the card lists it: `alerts` for a price alert that fired "
            "today, `watch` for the rest."
        ),
    )


class DailyChartLine(BaseModel):
    """One line of a chart on the daily card — the chat's chart, same shape."""

    symbol: str = Field(description="A ticker, or `@BOOK` for the reader's book.")
    currency: str = ""
    dates: list[str]
    values: list[float]
    label: str | None = None
    index: bool = Field(
        default=False,
        description="Growth from the window's first day, not a price.",
    )
    money: bool = Field(
        default=False,
        description="An amount in `currency` each day, not a price: the "
        "book's value, or the same money in an index.",
    )
    injected: list[float] | None = Field(
        default=None,
        description="The book only: the money put in by each of `dates`, net "
        "of withdrawals, in `currency`.",
    )
    opens: str | None = Field(
        default=None,
        description="The same money in an index only: the day it was first "
        "bought (the book's first day the index reaches), before `dates` "
        "when the window is shorter.",
    )


class DailyBookRow(BaseModel):
    window: Literal["day", "week", "month"]
    pct: float | None = Field(default=None, description="The book's change, %.")
    amount: float | None = Field(
        default=None, description="The same change in the card's currency."
    )
    index_pct: float | None = Field(
        default=None, description="The index's change over the window, %."
    )


class DailyContribution(BaseModel):
    ticker: str
    amount: float = Field(description="The position's day in the card's currency.")
    pct: float | None = Field(default=None, description="Its price move, %.")
    pp: float | None = Field(
        default=None, description="Its share of the book's day, percentage points."
    )
    weight_pct: float | None = None


class DailyBlock(BaseModel):
    kind: Literal["sector", "fund", "crypto"] = Field(
        description="A sector of single names, one fund, or the coins."
    )
    label: str = Field(description="The sector's name, or the fund's ticker.")
    amount: float
    pp: float | None = None
    tickers: list[str]


class DailyExplained(BaseModel):
    ticker: str
    pct: float | None = None
    sigmas: float = Field(description="The move in its own daily standard deviations.")
    etf: str = Field(description="The sector ETF it is set against, e.g. `XLK`.")
    etf_pct: float
    verdict: Literal["sector", "company"] = Field(
        description="`sector` when the ETF made at least half the move the same "
        "way, else `company`."
    )


class DailyAlphaDay(BaseModel):
    date: str
    book: float = Field(description="The held names' day, %.")
    index: float = Field(description="The index's day over the same stretch, %.")


class DailyAlpha(BaseModel):
    sessions: list[DailyAlphaDay]
    ahead: int = Field(description="Sessions the book beat the index.")
    excess_pp: float = Field(description="The days' differences summed, points.")


class DailyAttribution(BaseModel):
    """The day split by position and block: blocks sum to positions, and
    positions to `amount` — `gap` is what the stated day adds on top."""

    amount: float
    up: list[DailyContribution] = Field(default_factory=list)
    down: list[DailyContribution] = Field(default_factory=list)
    blocks: list[DailyBlock] = Field(default_factory=list)
    gap: float | None = Field(
        default=None,
        description="The card's day less the positions' sum, when a session "
        "under way reads them from different prices.",
    )
    stale: list[str] = Field(
        default_factory=list,
        description="Positions whose bar the feed repeated from the session before.",
    )
    explained: list[DailyExplained] = Field(default_factory=list)
    alpha: DailyAlpha | None = None


class DailyBook(BaseModel):
    """The card's Portfolio section: the book against the index."""

    index: str = Field(description="The index measured against, e.g. `S&P 500`.")
    currency: str
    rows: list[DailyBookRow]
    chart: list[DailyChartLine] = Field(
        default_factory=list,
        description="The month drawn, book and index rebased to 100.",
    )
    attribution: DailyAttribution | None = Field(
        default=None,
        description="What moved the book on the day; null on a card built "
        "before it, or when the positions could not be priced.",
    )


class BookCompare(BaseModel):
    """The Today chart over a chosen window, against a chosen index."""

    range: str = Field(description="`1m`, `3m`, `6m`, `ytd`, `1y`, `2y`, `5y` or `max`.")
    index: str = Field(description="The index's symbol, e.g. `QQQ` or `^IBEX`.")
    chart: list[DailyChartLine] = Field(
        default_factory=list,
        description="The book and the index, rebased to 100; empty when the "
        "basket or the index has no series for the window.",
    )
    since: str | None = Field(
        default=None,
        description="The first day drawn, when the book is younger than the "
        "window and its prices begin later; null when the window is whole.",
    )


class DailySectionChart(BaseModel):
    window: str
    rebased: bool = False
    series: list[DailyChartLine]


class DailySection(BaseModel):
    """One part of the reader's brief, answered on the card."""

    title: str = Field(description="A few words naming what it covers.")
    asks: list[int] = Field(
        default_factory=list,
        description="The brief's lines it answers, numbered from 1.",
    )
    lines: list[DailyItem]
    chart: DailySectionChart | None = None


class TodayRow(BaseModel):
    """One computed line of a Today section: a headline, an insider trade, or
    a holding measured against its sector and the index."""

    key: str = Field(description="What it is about, e.g. `news:NVDA:1a2b3c4d`.")
    kind: str = Field(
        default="", description="news | filing | results | insider | compare."
    )
    line: str
    tickers: list[str] = Field(default_factory=list)
    source: str = Field(
        default="",
        description="Where it was read: yahoo | 8k | earnings | sec | bafin | computed.",
    )
    url: str = Field(default="", description="The article or filing; empty when none.")
    date: str = Field(default="", description="ISO day it is from; empty when undated.")
    data: dict[str, float | int | str | bool | None] = Field(
        default_factory=dict,
        description=(
            "The figures behind the line — for a comparison: weight, m1, m6, "
            "y1, all (since the book's first day), sector, sector_etf, "
            "vs_sector_<span> and vs_index_<span> per span, vs_all:<symbol> "
            "to each benchmark since that day, all_from when the name was "
            "listed later, vs_sector / vs_index (six months), verdict, currency."
        ),
    )


class TodayBenchmark(BaseModel):
    """An index the comparisons are laid against, over each span."""

    symbol: str = Field(description="`SPY`, `^IBEX`…; `@BOOK` for the book itself.")
    name: str = Field(default="", description="Empty for `@BOOK`.")
    currency: str | None = Field(
        default=None,
        description="What its moves are in; the section's unless a rate failed.",
    )
    m1: float | None = None
    m6: float | None = None
    y1: float | None = None
    all: float | None = Field(
        default=None,
        description="Since the book's first day: the book's own money for `@BOOK`, "
        "that same money bought into the index on the same days for the rest.",
    )


class TodaySection(BaseModel):
    """A computed section of the Today page, with at most one written note."""

    id: Literal["news", "insiders", "compare"]
    title: str = ""
    rows: list[TodayRow] = Field(default_factory=list)
    note: str = Field(
        default="", description="The model's one remark on the section; empty when none."
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Sources that did not answer, e.g. `yahoo`, `edgar`.",
    )
    benchmarks: list[TodayBenchmark] = Field(
        default_factory=list,
        description="Comparisons only: the book and the indexes over each span.",
    )
    currency: str = Field(
        default="",
        description="Comparisons only: the currency every move is measured in; "
        "empty on a card stored before they were.",
    )
    since: str = Field(
        default="",
        description="Comparisons only: the book's first day, ISO, where the `all` "
        "span starts; empty without a history.",
    )


class DailyCard(BaseModel):
    """Today's briefing, whether it still stands, and whether one is coming.

    `GET /daily` never writes one: writing fans out a fetch and spends this
    account's free-model allowance, and a GET that could do that is a GET a
    prefetch could empty. `POST /daily` asks for one (see `api/briefing.py`),
    and while that generation is still out both routes answer `pending`.
    """

    day: str | None = Field(
        default=None, description="The action day the stored card was written for."
    )
    headline: str | None = None
    bullets: list[str] = Field(default_factory=list)
    focus: list[str] = Field(
        default_factory=list, description="Tickers the card says to look at."
    )
    as_of: str | None = Field(
        default=None, description="The trading session its figures come from."
    )
    lang: str | None = None
    source: str | None = Field(
        default=None,
        description=(
            "llm | computed. A computed card is the fallback the app writes "
            "from the triggers alone when no model answered — it is not prose "
            "and should not be presented as a briefing."
        ),
    )
    action_day: str = Field(
        description=(
            "Which day's card is current right now. It turns over at 16:45 "
            "New York time, after the US close, to the next day's: the card "
            "is written from settled closes and read the next morning."
        )
    )
    fresh: bool = Field(
        default=False,
        description=(
            "Whether the card still stands for `action_day` in the requested "
            "language. False means it is an older card: `POST /daily` writes "
            "today's, and a client shows this one as dated meanwhile."
        ),
    )
    generated: float | None = Field(
        default=None,
        description=(
            "Epoch seconds the card was written — the clock in the "
            "'Today · 09:14' stamp under the badge. Null for a card from before "
            "the field existed, which the stamp prints without a time."
        ),
    )
    pending: bool = Field(
        default=False,
        description=(
            "A briefing is being written right now. With a headline, the "
            "headline is the computed stand-in shown meanwhile; without one, "
            "the reader asked to regenerate and the old card is already gone. "
            "Poll `GET /daily` until this turns false."
        ),
    )
    items: list[DailyItem] = Field(
        default_factory=list,
        description=(
            "The card's lines, each with the trigger it is about — the same "
            "text as `bullets`, keyed so `POST /daily/analysis` can open each "
            "one. A card stored before keys existed has none; read `bullets`."
        ),
    )
    upgradable: bool = Field(
        default=False,
        description=(
            "A computed stand-in that a `POST /daily` may still replace with a "
            "written briefing — the model gets a few more tries a day. The "
            "card stands meanwhile (`fresh` stays true)."
        ),
    )
    analysed: list[str] = Field(
        default_factory=list,
        description=(
            "Keys of the lines whose analysis is already written: `POST "
            "/daily/analysis` returns it without spending anything."
        ),
    )
    thread: str | None = Field(
        default=None,
        description=(
            "The chat conversation the card is filed in — what its 'Ask' "
            "opens, so a question is asked with the card above it. Null for a "
            "card not filed (still being written, or filing failed)."
        ),
    )
    book: DailyBook | None = Field(
        default=None,
        description=(
            "The Portfolio section. Null when the index could not be read, or "
            "for an account with no positions."
        ),
    )
    sections: list[DailySection] = Field(
        default_factory=list,
        description=(
            "The reader's brief, answered: one section per line they wrote, "
            "in their order, below the alerts that fired (`items`). Empty "
            "for the default card."
        ),
    )
    brief: Literal["", "pending", "written", "missed"] = Field(
        default="",
        description=(
            "Where the reader's brief stands: empty with none (the default "
            "card); `pending` while its data is fetched and written; "
            "`written` when `sections` hold it; `missed` when no model wrote "
            "it today and the default card stands in."
        ),
    )
    today: list[TodaySection] = Field(
        default_factory=list,
        description=(
            "The Today page's computed sections — news, insiders, comparisons "
            "— in the order they are read. Empty on a card written before the "
            "page existed."
        ),
    )
    shape: str = Field(
        default="",
        description=(
            "The kind of book the sections were chosen for: empty | fund_only "
            "| crypto_only | concentrated | dividend | mixed."
        ),
    )


class MarketLine(BaseModel):
    topic: Literal["trend", "sector", "rates", "macro", "crypto"]
    line: str


class MarketRegime(BaseModel):
    score: float
    key: str = Field(description="stress | caution | neutral | appetite | euphoria.")
    run: int = Field(default=0, description="Sessions the score has held its band.")
    score_month: float | None = Field(
        default=None, description="The score 21 sessions ago."
    )


class MarketBreadth(BaseModel):
    indices_hits: int = 0
    indices_total: int = 0
    sectors_hits: int = 0
    sectors_total: int = 0


class MarketRate(BaseModel):
    key: str = Field(
        description="us10y | curve_2s10s | hy_spread | policy_fed | policy_ecb."
    )
    value: float
    change_bp: float | None = Field(
        default=None, description="Change over a month of sessions, basis points."
    )


class MarketBank(BaseModel):
    bank: Literal["fed", "ecb"]
    rate: float | None = None
    last_move_bp: float | None = Field(
        default=None, description="The rate's last change, bp, whenever it was."
    )
    last_date: str | None = Field(default=None, description="Its last meeting.")
    moved_on: str | None = Field(default=None, description="When the rate last changed.")
    next_date: str | None = None
    days: int | None = Field(default=None, description="Days to the next decision.")


class MarketSector(BaseModel):
    ticker: str
    name: str
    week: float | None = Field(default=None, description="5-session excess over SPY, %.")
    month: float | None = Field(
        default=None, description="21-session excess over SPY, %."
    )


class MarketInflation(BaseModel):
    area: str
    period: str
    headline: float
    core: float | None = None
    momentum: float | None = Field(
        default=None, description="Annual rate now minus six months ago, pp."
    )


class MarketCrypto(BaseModel):
    fear_greed: float | None = None
    fear_greed_week: float | None = None
    btc_dominance: float | None = None


class MarketIndex(BaseModel):
    name: str
    day: float | None = Field(default=None, description="Last session, %.")
    week: float | None = Field(default=None, description="Five sessions, %.")
    month: float | None = Field(default=None, description="21 sessions, %.")


class MarketCard(BaseModel):
    """The day's market read, shared by every account: written once each
    morning by the cron (`stocks today-market`), figures and all."""

    session: str = Field(description="The last US session the figures close on.")
    built_at: float = Field(description="Epoch seconds it was written.")
    lang: str
    source: Literal["llm", "computed"]
    headline: str
    lines: list[MarketLine] = Field(default_factory=list)
    regime: MarketRegime | None = None
    breadth: MarketBreadth | None = None
    rates: list[MarketRate] = Field(default_factory=list)
    banks: list[MarketBank] = Field(default_factory=list)
    sectors: list[MarketSector] = Field(
        default_factory=list, description="Sector ETFs, best month first."
    )
    inflation: list[MarketInflation] = Field(default_factory=list)
    crypto: MarketCrypto | None = None
    index: MarketIndex | None = None
    missing: list[str] = Field(default_factory=list)


class TodayCard(BaseModel):
    """The Today page: the shared market read plus the reader's own card.

    `GET /today` never writes anything; `POST /today` asks for the personal
    part the way `POST /daily` does (one job per account, shared with Home).
    """

    action_day: str
    market: MarketCard | None = Field(
        default=None, description="Null until the first morning's read exists."
    )
    market_stale: bool = Field(
        default=False,
        description="The read is older than the last session; a newer one is on its way.",
    )
    personal: DailyCard | None = Field(
        default=None, description="Null for a guest; the reader's daily card otherwise."
    )


class DailyAnalysisPoint(BaseModel):
    title: str
    text: str


class DailyAnalysisRow(BaseModel):
    ticker: str | None = Field(
        default=None,
        description="The row's symbol, drawn as a ticker cell; null for a label row.",
    )
    label: str = Field(
        default="",
        description="The row's name when it has no ticker, or a note beside it.",
    )
    cells: list[str] = Field(
        default_factory=list,
        description="The values, formatted in the card's language, one per column.",
    )
    highlight: bool = Field(default=False, description="The row the analysis is about.")


class DailyAnalysisTable(BaseModel):
    title: str
    columns: list[str] = Field(
        description="Headers, the name column first — one more than each row's cells."
    )
    rows: list[DailyAnalysisRow] = Field(default_factory=list)
    note: str = ""


class DailyAnalysis(BaseModel):
    """The analysis behind one line of today's card.

    Written on the first request for that line and stored with the card. The
    figures come from what the app fetched for it — the company against its
    peers, its sector's ETF and the index, its business figures and the
    analysts' consensus, the tax arithmetic of a sale, the month's
    attribution — and every figure the prose quotes was checked against
    those. The tables are computed, never written.
    """

    key: str
    day: str | None = None
    source: str | None = Field(
        default=None,
        description="llm | computed — computed when no model answered.",
    )
    verdict: str = ""
    points: list[DailyAnalysisPoint] = Field(default_factory=list)
    tables: list[DailyAnalysisTable] = Field(default_factory=list)
    as_of: str | None = Field(
        default=None, description="The day the evidence was read for."
    )


class Mover(BaseModel):
    ticker: str
    pct: float = Field(description="Change over the window, as a fraction.")
    active: bool | None = Field(
        default=None,
        description=(
            "Day window only: whether the name has a live quote now (regular "
            "session, or US pre/after-hours). False greys the figure — it is the "
            "last completed session, real but not moving. Null on the longer "
            "windows, which are close-to-close by construction."
        ),
    )
    premarket: bool = Field(
        default=False,
        description=(
            "Day window only: the name is in US premarket, and `pct` is its last "
            "regular session compounded with the premarket move on top of it."
        ),
    )


class Movers(BaseModel):
    window: str = Field(description="day | week | month.")
    base: str = Field(default="EUR", description="Currency `amount` is counted in.")
    gainers: list[Mover] = Field(default_factory=list, description="Best first.")
    losers: list[Mover] = Field(default_factory=list, description="Worst first.")
    amount: float | None = Field(
        default=None,
        description=(
            "What the book's change is worth in `base` over the window — the "
            "figure a tile leads with, because a percentage on its own says "
            "nothing about how much money moved. Same rows as `basket`, so the "
            "two are the same statement twice."
        ),
    )
    positions: int = Field(default=0, description="Open positions in the book.")
    unpriced: int = Field(
        default=0,
        description=(
            "Positions the basket could not measure over this window — no "
            "price series, or no FX path for their currency. They are in "
            "neither `amount` nor `basket`, and a client that does not "
            "disclose them is reporting part of a book as the whole of it."
        ),
    )
    as_of: str | None = Field(
        default=None,
        description=(
            "Which session the figures belong to. Off-hours the day window is "
            "the last completed session, not today, and saying so is the "
            "difference between a stale number and a dated one."
        ),
    )
    basket: float | None = Field(
        default=None,
        description=(
            "The whole book's change over the same window. Null when the price "
            "history does not cover it — not 0, which would read as a flat book."
        ),
    )


class Extreme(BaseModel):
    ticker: str
    price: float
    edge: str = Field(description="high | low — which end of the 52-week range.")
    distance: float | None = Field(
        default=None,
        description=(
            "How far off the extreme, as a fraction. Null means at or beyond "
            "it, which is a different fact from being 0% away."
        ),
    )


class Extremes(BaseModel):
    extremes: list[Extreme] = Field(
        default_factory=list, description="Names within 2% of a 52-week edge."
    )
    scanned: int = Field(
        default=0,
        description=(
            "How many names were scanned: held positions plus favourites, "
            "crypto excluded. Zero means there was nothing to scan — the card "
            "has no reason to be on the page — which is a different fact from "
            "a scan that found no name at an edge."
        ),
    )
