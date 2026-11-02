"""The book and its prices: positions, totals, the ledger, returns, the
watchlist and quotes, and the service's own health and load progress.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from stocks.api.schemas.ticker import Custodian


class Health(BaseModel):
    status: str = "ok"
    version: str
    booted: str = Field(description="ISO-8601 UTC timestamp of process start.")


class ProgressJob(BaseModel):
    step: str = Field(
        description=(
            "What the download is doing: `prices.tail` (the last month, twenty "
            "names a request), `prices.rebase` (the daily month of chart) or "
            "`prices.full` (whole histories)."
        )
    )
    done: int = Field(description="Names done in this step; 0 when it cannot count.")
    total: int = Field(description="Names in this step.")
    elapsed_s: float = Field(description="Seconds since the whole load started.")
    step_elapsed_s: float = Field(description="Seconds since this step started.")
    expected_s: float | None = Field(
        default=None,
        description="How long this step took last time on this book, if known.",
    )


class Progress(BaseModel):
    job: ProgressJob | None = None


class Position(BaseModel):
    ticker: str
    shares: float
    currency: str = Field(
        description=(
            "The currency the position is priced in: its listing's, in the "
            "major unit (GBP for a London line quoted in pence). A watchlist "
            "alias can price a name off another venue than the one it was "
            "bought on — Revolut's dollar ASML off the euro ASML.AS — and "
            "this is the listing's side, the one `price` and `value` use."
        )
    )
    cost: float = Field(description="Basis in the reporting currency.")
    value: float | None = Field(
        default=None, description="Market value; null when no price was available."
    )
    price: float | None = Field(
        default=None,
        description=(
            "Latest price of ONE share, in `currency` — the currency the name "
            "trades in, not the reporting one. A share price is quoted by its "
            "own market, and converting it would print a number no screen "
            "anywhere shows. Null when the position has no value, or when the "
            "pair could not be fetched to convert back."
        ),
    )
    pnl: float | None = None
    pnl_pct: float | None = None
    weight: float | None = Field(
        default=None,
        description=(
            "Share of the book by market value. Unpriced rows read null but "
            "still stand in the denominator at their cost, so the priced ones "
            "are not handed their share."
        ),
    )
    day: float | None = Field(
        default=None,
        description=(
            "Today's move in the reporting currency, FX included. Close-to-"
            "close on the basket while the name's exchange is open; outside "
            "it, the live pre/after-hours quote or the last completed "
            "session's move — never the flat 0 a stale premarket bar reads. "
            "Null when no two prices could be compared."
        ),
    )
    day_pct: float | None = Field(
        default=None, description="The same move as a fraction of yesterday's value."
    )
    market_active: bool = Field(
        default=True,
        description=(
            "Whether a live quote exists for this name right now (regular "
            "session, US extended hours, or crypto). False means `day` is the "
            "last session's move and the cell should be dimmed, not hidden."
        ),
    )
    custody: list[Custodian] = Field(
        default_factory=list,
        description=(
            "Which broker's account holds the shares, largest first — one "
            "entry for a single-broker position, several when it is split. "
            "Off the ledger's note prefixes, so it never costs a fetch."
        ),
    )


class Positions(BaseModel):
    base: str
    positions: list[Position]
    unpriced: int = Field(
        description="How many positions the price pass had no series for."
    )
    demo: bool = Field(
        default=False,
        description=(
            "These rows are the example book (`POST /portfolio/demo`), not an "
            "import: the assistant's opening screen asks for one instead of "
            "offering questions about a book that is not the reader's."
        ),
    )


class Summary(BaseModel):
    base: str
    cost: float = Field(description="Basis of the priced rows only.")
    value: float = Field(description="Market value of those same rows.")
    pnl: float
    pnl_pct: float | None = None
    positions: int
    unpriced: int = Field(
        description=(
            "Positions left out of cost and value alike — both sums come from "
            "the same rows, so the percentage between them is like-for-like."
        )
    )
    unpriced_cost: float = Field(
        default=0.0,
        description=(
            "Basis of the unpriced rows. A headline that sets the book's value "
            "beside everything that went in holds them at this, as the value "
            "history does — leaving them out sets a fraction of the book "
            "against all of the money."
        ),
    )
    stale: list[str] = Field(
        default_factory=list,
        description=(
            "Tickers valued at the book's last kept close, not a live price, "
            "because Yahoo refused this download. Counted in cost and value."
        ),
    )
    unlisted: list[str] = Field(
        default_factory=list,
        description=(
            "Held tickers among the unpriced that Yahoo said it has no symbol "
            "for — a broker code that needs mapping, not a feed that is down. "
            "Known only once this process has asked Yahoo for them."
        ),
    )
    realized: float | None = Field(
        default=None,
        description=(
            "All-time result of closed sales, FIFO-matched, in this base — each "
            "leg converted at its own trade date. Null for a book that has "
            "never sold anything: no sale is not a result of zero. This is NOT "
            "the tax report's figure, which replays under the jurisdiction's "
            "own currency and matching rule (`/portfolio/tax`)."
        ),
    )
    realized_cost: float | None = Field(
        default=None,
        description="Basis of those closed sales, so a client can show a percentage.",
    )
    demo: bool = Field(
        default=False,
        description=(
            "These rows are the example book (`POST /portfolio/demo`), not a "
            "real one. A client showing figures derived from them has to say "
            "so — an invented cost basis that reads as the reader's own is the "
            "one mistake this whole feature has to not make."
        ),
    )


class Transaction(BaseModel):
    id: int | None = None
    date: str
    ticker: str
    action: str
    quantity: float
    price: float
    currency: str
    fee: float
    note: str
    amount: float | None = Field(
        default=None,
        description=(
            "The cash the row moved, in the reporting currency at the trade "
            "date's ECB rate (Home's recent-transactions strip). Null for a "
            "split or a transfer, which move no cash, and for a rate that "
            "could not be found — never today's rate standing in for it."
        ),
    )


class Transactions(BaseModel):
    total: int = Field(description="Rows in the ledger, before limit/offset.")
    transactions: list[Transaction]
    base: str | None = Field(
        default=None, description="Currency every row's `amount` is counted in."
    )
    demo: bool = Field(
        default=False,
        description=(
            "These rows are the example book (`POST /portfolio/demo`), not a "
            "real one. A client showing figures derived from them has to say "
            "so — an invented cost basis that reads as the reader's own is the "
            "one mistake this whole feature has to not make."
        ),
    )


class AttributionMover(BaseModel):
    ticker: str
    amount: float = Field(
        description=(
            "What this holding added over the window in `base`: price, currency, "
            "income and commissions, contributions left out."
        )
    )


class Attribution(BaseModel):
    """Where the change in the book's value came from, bar by bar."""

    base: str
    window: str = Field(
        default="inception",
        description="Same windows as `/portfolio/performance`.",
    )
    start: str | None = None
    end: str | None = None
    start_value: float | None = Field(
        default=None,
        description="Book value at the window's first close (0 from inception).",
    )
    contributions: float = Field(
        default=0.0,
        description="Net cash put in: buys incl. commission minus sale proceeds.",
    )
    price: float = Field(
        default=0.0,
        description="Each holding's own-currency move, valued at the prior day's rate.",
    )
    fx: float = Field(
        default=0.0, description="The same holdings' move from the exchange rate alone."
    )
    dividends: float = Field(
        default=0.0,
        description=(
            "Gross dividends booked in the window. The value path is built from "
            "adjusted closes, so they are taken out of `price`, not added on top."
        ),
    )
    fees: float = Field(default=0.0, description="Trade commissions (<= 0).")
    other: float = Field(
        default=0.0,
        description=(
            "What no bar above can place, e.g. a name carried at cost. Zero "
            "unless beyond rounding."
        ),
    )
    end_value: float | None = Field(
        default=None,
        description=(
            "start_value + every bar, exactly. The last day of the same value "
            "path, so it can differ from the live `value` on `/performance`."
        ),
    )
    contributors: list[AttributionMover] = Field(default_factory=list)
    detractors: list[AttributionMover] = Field(default_factory=list)
    missing: list[str] = Field(
        default_factory=list,
        description="Names with no usable price: carried at cost at both ends.",
    )


class Performance(BaseModel):
    base: str
    window: str = Field(
        default="inception",
        description=(
            "Span every figure below was taken over: inception (the whole "
            "book, the default), or 6mo/1y/2y/5y back from today. `start` is "
            "where it actually began, which for a young book is later than "
            "the window asked for."
        ),
    )
    start: str | None = None
    end: str | None = None
    injected: float | None = Field(
        default=None, description="Net capital put in, at each trade date's rate."
    )
    injected_window: float | None = Field(
        default=None,
        description=(
            "The window's buy-in: the book's value on its first day plus the "
            "net money put in since. Equals `injected` since inception."
        ),
    )
    value: float | None = Field(default=None, description="Latest book value.")
    twr_cumulative: float | None = Field(
        default=None,
        description=(
            "Compounded time-weighted return over the whole span. Flow-adjusted, "
            "so deposits and withdrawals do not read as performance."
        ),
    )
    twr_annualised: float | None = Field(
        default=None,
        description=(
            "Per-year time-weighted return; equals `twr_cumulative` when the "
            "span is under a year (see `twr_is_annual`)."
        ),
    )
    twr_is_annual: bool = Field(
        default=True,
        description=(
            "False when the span is under a year: `twr_annualised` is then cumulative."
        ),
    )
    twr_volatility: float | None = Field(
        default=None,
        description=(
            "Annualised standard deviation of the same flow-adjusted daily "
            "series. Taken over the book's whole span, so it is not the risk "
            "of today's basket — that is `/portfolio/risk`, over a window, at "
            "fixed weights."
        ),
    )
    twr_max_drawdown: float | None = Field(
        default=None,
        description="Worst peak-to-trough fall of the TWR path (<= 0).",
    )
    twr_var_95: float | None = Field(
        default=None,
        description=(
            "One-day historical VaR at 95%: the daily flow-adjusted return "
            "that 19 days in 20 beat, as a return (<= 0). Null under 60 days."
        ),
    )
    twr_drawdown_peak: str | None = Field(
        default=None,
        description="ISO date the worst fall started from; null when it never fell.",
    )
    twr_drawdown_trough: str | None = Field(
        default=None, description="ISO date the worst fall bottomed out."
    )
    twr_drawdown_peak_value: float | None = Field(
        default=None,
        description=(
            "The book's value on the peak day, in `base`. The TWR weighs every "
            "day the same, so a fall on a small early book reads as large as "
            "one on today's — this is what says which it was."
        ),
    )
    dropped_days: list[str] = Field(
        default_factory=list,
        description=(
            "Days excluded from every figure above. A flow the value path "
            "cannot price — an unrecorded split, say — would otherwise read as "
            "a one-day collapse and drag the compounded return with it, so the "
            "day is dropped and named here instead of quietly wrecking the "
            "numbers."
        ),
    )
    irr: float | None = Field(
        default=None,
        description=(
            "Money-weighted return, per year from a year of span and "
            "cumulative before (`irr_annualised`). Unlike the TWR, flow timing "
            "moves it: it answers how the money did, not how the strategy did."
        ),
    )
    irr_annualised: bool = Field(
        default=True,
        description=(
            "False when the span is under a year: then `irr` is cumulative, "
            "not annualised."
        ),
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Held names with no price series, carried at cost in value.",
    )


class WatchlistEntry(BaseModel):
    ticker: str
    name: str = ""
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    shares: float | None = Field(
        default=None,
        description=(
            "Shares held as the watchlist records them — the hand-typed "
            "position set in the Profile's watchlist, which weights the analytics by "
            "market value instead of equally. Null when none is set (0 on "
            "disk), so a client draws an empty cell rather than a zero that "
            'reads as "sold". Written by `PATCH /watchlist/{ticker}`.'
        ),
    )
    cost: float | None = Field(
        default=None,
        description=(
            "Average cost per share, for unrealised P/L. Null when unset; "
            "`PATCH /watchlist/{ticker}` with `cost: 0` clears it."
        ),
    )
    is_crypto: bool = Field(
        default=False,
        description=(
            "A coin pair. Said here so a client does not have to re-derive it "
            "from the symbol's shape — the comps table ranks on KPIs a coin "
            "has none of, and the app leaves them out of it."
        ),
    )


class Watchlist(BaseModel):
    entries: list[WatchlistEntry]


class Quote(BaseModel):
    ticker: str
    price: float | None = None
    pct: float | None = Field(default=None, description="Day move, as a fraction.")
    session: str | None = Field(
        default=None,
        description='"pre", "post" or null for the regular session.',
    )
    as_of: str | None = Field(
        default=None,
        description=(
            "Which session the move belongs to. Off-hours this is the last "
            "completed session, not today — print it rather than assuming."
        ),
    )
    market_open: bool | None = Field(
        default=None,
        description=(
            "True while the ticker is inside its regular session. Set only on "
            "the single-ticker route: inside the session the bars already track "
            "the live price, and only outside it does this quote add anything. "
            "Null on the batch route, which does not work out a clock per name."
        ),
    )
    currency: str | None = Field(
        default=None,
        description=(
            "The listing's own quote currency, minor units included (GBp) — "
            "the same code `TickerPosition.currency` carries. Set only on the "
            "single-ticker route, and null for a coin pair, whose symbol "
            "already names its quote leg."
        ),
    )
    price_base: float | None = Field(
        default=None,
        description=(
            "`price` restated in `?base=`, when the two currencies differ and "
            "a rate could be had. Null otherwise — never an unconverted figure "
            "passed off as one."
        ),
    )
    fx_rate: float | None = Field(default=None, description="The rate used.")
    fx_as_of: str | None = Field(default=None, description="…and its date.")
    base: str | None = Field(
        default=None, description="The reporting currency asked for with `?base=`."
    )
    high_52w: float | None = Field(
        default=None,
        description=(
            "The year's highest regular-session price, in the listing's own "
            "currency, off the same quote row. Null when the feed had no year "
            "(a Finnhub fallback, a listing younger than that)."
        ),
    )
    low_52w: float | None = Field(default=None, description="…and its lowest.")


class Quotes(BaseModel):
    quotes: list[Quote]
    unavailable: list[str] = Field(
        default_factory=list,
        description="Tickers with no quote: unknown symbol, or a throttled fetch.",
    )
