"""Response models.

Two rules run through all of them:

* A number the app could not compute is `null`, never 0 and never a guess. An
  unpriced position has no value and no weight; a book with no span has no
  return. Downstream has to see the difference between "nothing" and "zero".
* Anything derived from a partial price pass says so. `unpriced` and `missing`
  are fields, not footnotes, because a total that quietly drops part of the
  book is the same lie as a wrong one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str = "ok"
    version: str
    booted: str = Field(description="ISO-8601 UTC timestamp of process start.")


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
    value: float | None = Field(default=None, description="Latest book value.")
    twr_cumulative: float | None = Field(
        default=None,
        description=(
            "Compounded time-weighted return over the whole span. Flow-adjusted, "
            "so deposits and withdrawals do not read as performance."
        ),
    )
    twr_annualised: float | None = None
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
            "Annualised money-weighted return. Unlike the TWR, flow timing "
            "moves it: it answers how the money did, not how the strategy did."
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
            "position the Streamlit grid edits, which weights the analytics by "
            "market value instead of equally. Null when none is set (0 on "
            "disk), so a client draws an empty cell rather than a zero that "
            "reads as \"sold\". Written by `PATCH /watchlist/{ticker}`."
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


class Quotes(BaseModel):
    quotes: list[Quote]
    unavailable: list[str] = Field(
        default_factory=list,
        description="Tickers with no quote: unknown symbol, or a throttled fetch.",
    )


# ------------------------------------------------------------- one ticker's page


class Bars(BaseModel):
    ticker: str
    range: str = Field(description="The requested range label, e.g. 1y.")
    interval: str = Field(description="Bar size the range downloads at, e.g. 1d.")
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
    rsi_verdict: str | None = Field(
        default=None,
        description=(
            "oversold | neutral | overbought for the latest RSI(14), or null "
            "while the indicator is still warming up. Computed here so both "
            "front ends read the same bands."
        ),
    )
    rsi_tone: str | None = Field(default=None, description="green | gray | red.")
    rangebreaks: list[dict] = Field(
        default_factory=list,
        description=(
            "Axis breaks hiding closed-market time, so bars render contiguous. "
            "Pass straight to the x-axis; empty for a market that trades 24/7."
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


class PriceEvents(BaseModel):
    ticker: str
    earnings: list[EarningsEvent] = Field(default_factory=list)


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
            "(`fundamentals.FUNDAMENTAL_TILES`). `kpis` carries all 23; a page "
            "drawing every one of them is a reference table, not a screen."
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
            "…the same figure through `format_value`, so both front ends print "
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
        default_factory=list, description='[{"period": "2024Q1", "eps": 1.53}, …]'
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


class MoatPillar(BaseModel):
    key: str
    label: str
    score: float | None = Field(default=None, description="0-100; null when unscored.")
    weight: float
    detail: str = Field(description="What the score was computed from.")


class Moat(BaseModel):
    ticker: str
    score: float | None = Field(
        default=None,
        description="Weighted composite 0-100; null when too few pillars scored.",
    )
    rating: str | None = Field(default=None, description="wide | narrow | no moat.")
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


class Insiders(BaseModel):
    ticker: str
    source: str | None = Field(
        default=None, description="SEC | BaFin | null when neither covers this name."
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


class FundHolding(BaseModel):
    symbol: str
    name: str
    weight: float = Field(description="Fraction of the fund: 0.075 is 7.5%.")


class Fund(BaseModel):
    ticker: str
    is_fund: bool
    name: str = ""
    quote_type: str | None = None
    currency: str | None = None
    category: str | None = None
    family: str | None = None
    expense_ratio: float | None = None
    aum: float | None = None
    dividend_yield: float | None = None
    turnover: float | None = None
    description: str = ""
    legal_type: str | None = Field(
        default=None, description="Yahoo's legal form, e.g. 'Exchange Traded Fund'."
    )
    bond_duration: float | None = Field(
        default=None, description="Effective duration in years, bond sleeves only."
    )
    is_bond_fund: bool = Field(
        default=False,
        description=(
            "More than half the basket in bonds. A page shows such a fund its "
            "duration instead of its top-ten concentration: Yahoo publishes no "
            "basket for most of them, and duration is what a rate move acts on."
        ),
    )
    holdings: list[FundHolding] = Field(default_factory=list)
    disclosed_weight: float = Field(
        default=0.0,
        description=(
            "What the disclosed holdings add up to. Yahoo publishes the top ten "
            "only, so this is a floor on concentration, never the whole book — "
            "and a page showing ten names has to say so."
        ),
    )
    sectors: list[list] = Field(
        default_factory=list, description="[[label, fraction], …]"
    )
    asset_classes: list[list] = Field(
        default_factory=list, description="[[label, fraction], …] — stocks, bonds, cash."
    )


class Trade(BaseModel):
    """One of the caller's own fills, in TODAY's shares."""

    date: str
    action: str = Field(description="buy | sell.")
    price: float = Field(
        description=(
            "Split-adjusted to the scale the exchange quotes in now. Ledger "
            "prices are as-traded; a pre-split buy plotted raw sits twenty "
            "times above the candles it belongs on."
        )
    )
    quantity: float = Field(description="Scaled inversely, so the money is unchanged.")


class AssetStats(BaseModel):
    """The coin stand-in for fundamentals, insiders and comps — none of which
    exist for a currency pair."""

    ticker: str
    quote: str = Field(default="USD", description="The pair's quote currency.")
    market_cap: float | None = None
    volume_24h: float | None = None
    circulating_supply: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None


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


class Profile(BaseModel):
    """Who the reader is looking at, before any number is fetched."""

    ticker: str = Field(description="As asked for — the label the ledger stores.")
    symbol: str = Field(
        description=(
            "What it resolves to. An ISIN-keyed holding reads as its ticker "
            "here; the ledger and every link keep the original label."
        )
    )
    name: str = Field(
        default="",
        description=(
            "The account's own watchlist name first, then the coin map, the "
            "fund catalog and the SEC map. Empty when no source knows one — "
            "print the symbol, never invent."
        ),
    )
    logo: str | None = Field(
        default=None,
        description=(
            "This host's mirror where there is one, the source URL otherwise. "
            "Mirrored so the logo CDNs never see a request per viewer naming "
            "which tickers somebody looks at."
        ),
    )
    is_crypto: bool = False
    is_fund: bool = False


class Peer(BaseModel):
    ticker: str
    name: str = ""


class Peers(BaseModel):
    ticker: str
    related: list[Peer] = Field(
        default_factory=list,
        description=(
            "Yahoo's related symbols, minus the name itself. Suggestions for "
            "the comps picker — nothing is compared until a caller picks."
        ),
    )


class Comparables(BaseModel):
    tickers: list[str]
    labels: list[str] = Field(description="KPI row labels, in the app's order.")
    rows: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Ticker to its formatted column, aligned to `labels`.",
    )
    medals: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Ticker to 🥇/🥈/🥉 for the three best composite ranks. Empty below "
            "three qualifying names — a two-horse race has no podium."
        ),
    )


class SearchMatch(BaseModel):
    ticker: str
    name: str = ""
    kind: str = Field(
        description=(
            "Which tier answered: watch | crypto | fund | sec | world | analyze. "
            "`analyze` is not a match — it is a plausible symbol no catalog "
            "knows, offered so the reader can try it anyway."
        )
    )
    mark: str = Field(
        default="",
        description="favorite | held | '' — only own-list rows carry one.",
    )
    exchange: str = Field(default="", description="Venue, worldwide rows only.")


class SearchResults(BaseModel):
    query: str
    matches: list[SearchMatch] = Field(
        default_factory=list,
        description="Already in the order to draw, tiers included.",
    )


class Recents(BaseModel):
    tickers: list[str] = Field(
        default_factory=list, description="Newest first, capped, deduped."
    )


# ------------------------------------------------------------- the cost of it
# What a trade cost beyond the ticket: the commission the broker charged, and
# the spread it charged without saying so. The two are kept apart everywhere —
# one is a ledger fact, the other an estimate against the day's bars, and
# adding them into a single "fees" number would hide which is which.


class BrokerCost(BaseModel):
    broker: str = Field(description="Ledger note prefix: revolut, clicktrade, manual.")
    trades: int
    volume: float = Field(description="Traded value in the reporting currency.")
    commission: float = Field(description="Explicit commission, from the ledger.")
    other_fees: float = Field(
        default=0.0, description="Standalone fee rows: custody, FX, platform."
    )
    spread: float | None = Field(
        default=None,
        description=(
            "Estimated cost against the trade day's mid — signed, so a negative "
            "figure means the execution beat the mid. Null when no bar could be "
            "read for this broker's trades."
        ),
    )
    spread_bps: float | None = Field(
        default=None, description="`spread` over measured volume, in basis points."
    )
    measured: int = Field(
        default=0, description="Trades with a usable bar on the trade date."
    )
    skipped: int = Field(
        default=0, description="Trades the spread pass could not measure."
    )
    outside_range: float = Field(
        default=0.0,
        description="Executions beyond the day's high/low — a data smell, not a cost.",
    )
    total: float | None = Field(
        default=None, description="Commission + other fees + spread, when measured."
    )
    cost_pct: float | None = Field(
        default=None, description="`total` over this broker's volume."
    )


class Fees(BaseModel):
    base: str
    brokers: list[BrokerCost] = Field(default_factory=list)
    explicit: float = Field(
        default=0.0, description="Commission and fees across every broker."
    )
    spread: float | None = Field(
        default=None,
        description="Estimated spread across every broker; null when unmeasured.",
    )
    volume: float = Field(default=0.0)
    cost_pct: float | None = Field(
        default=None, description="Total cost over traded volume; null with no volume."
    )
    spread_measured: bool = Field(
        default=False,
        description=(
            "Whether the trade-day bars came back at all. False means every "
            "spread field is null because Yahoo was unreachable, NOT that the "
            "book traded at the mid."
        ),
    )


# --------------------------------------------------------------- what it pays
# Two different things with the same unit, so they never share a field: what
# the ledger was paid (a receipt) and what the shares were entitled to (an
# estimate from Yahoo's per-share history). A book whose import carried no
# dividend rows still has an estimate, and it must not read as income received.


class DividendYear(BaseModel):
    year: int
    gross: float
    withheld: float
    net: float
    creditable: float = Field(
        description="Foreign tax creditable at home, capped at the treaty rate."
    )
    reclaimable: float = Field(
        description="Withholding above the cap — reclaim from the source country."
    )
    estimated_gross: float | None = Field(
        default=None, description="What the shares were entitled to that year."
    )
    unrecorded: float | None = Field(
        default=None,
        description="Entitlement with no ledger row behind it: a gap in the import.",
    )


class ForwardHolding(BaseModel):
    ticker: str
    shares: float
    per_share: float = Field(description="Summed over the trailing 12 months.")
    payments: int = Field(description="Ex-dates in those 12 months; 4 = quarterly.")
    currency: str
    gross: float = Field(description="`per_share` * `shares`, in that currency.")
    gross_base: float | None = Field(
        default=None, description="The same, in the reporting currency."
    )
    last_ex: str | None = None


class Dividends(BaseModel):
    base: str
    years: list[DividendYear] = Field(default_factory=list)
    booked_total: float = Field(default=0.0, description="Gross ever booked.")
    booked_ytd: float = Field(default=0.0)
    estimated_total: float | None = None
    estimated_ytd: float | None = None
    forward_annual: float | None = Field(
        default=None,
        description="Next year's income at the trailing 12m rate, if nothing is sold.",
    )
    forward: list[ForwardHolding] = Field(default_factory=list)
    estimates_available: bool = Field(
        default=False,
        description=(
            "Whether the entitlement pass ran. False leaves every estimate null "
            "— the book may still pay, nobody could check."
        ),
    )


# ------------------------------------------------------------------ what it owes
# The jurisdiction is not a parameter of this endpoint: it is the account's own
# setting, and the ledger is replayed *at* that jurisdiction's currency and
# matching rule rather than converted afterwards. A US filer's basis is USD at
# each trade date, which is two rates and not one.


class TaxKpi(BaseModel):
    name: str = Field(description="Jurisdiction-neutral key, e.g. net_taxable.")
    value: float
    help: str = Field(default="", description="i18n key for the explanation.")


class TaxPeriod(BaseModel):
    period: str = Field(description='ISO prefix: "2024" for a year, "2024-03" a month.')
    realized_gain: float
    realized_loss: float
    disallowed_loss: float = Field(
        default=0.0, description="Blocked this period by the repurchase rule."
    )
    recovered_loss: float = Field(
        default=0.0, description="Earlier blocked losses that became deductible now."
    )
    deductible_loss: float = 0.0
    net_taxable: float
    estimated_tax: float
    carryforward_loss: float = 0.0
    sales: int = Field(default=0, description="Matched parcels in the period.")
    kpis: list[TaxKpi] = Field(default_factory=list)
    year_label: str = Field(
        default="",
        description=(
            'How the jurisdiction writes this tax year — "2025", or "2025/26" '
            "for a UK or Australian year that opens mid-calendar. Empty for a "
            "month. `period` stays the sortable key; this is what to print."
        ),
    )
    notes: list[TaxNote] = Field(
        default_factory=list,
        description=(
            "The sentences the jurisdiction appends under this period's "
            "figures (deferred losses, allowances used, a rate year borrowed), "
            "as catalog keys the client resolves the same way the KPI names "
            "are — `portfolio.<code>_<key>` first, then `portfolio.<key>`."
        ),
    )


class TaxNote(BaseModel):
    """One localized sentence under a period's figures: a key and its slots.

    Language-neutral on purpose, like `TaxKpi`: the number slots arrive already
    formatted (`"1,240"`), so a client only substitutes and never re-derives.
    """

    key: str
    kwargs: dict[str, str] = Field(default_factory=dict)


class TaxFlag(BaseModel):
    """A foreign-asset reporting threshold — Modelo 720, FBAR, Form 8938…

    `reportable` means the threshold is crossed, not that a filing is due:
    whether it applies depends on where the assets actually sit, which the
    ledger does not know. Hence a flag the client words as "may apply", never
    a verdict.
    """

    name: str = Field(description="i18n suffix: modelo_720, fbar, form_8938…")
    reportable: bool
    total_value: float = Field(
        description="The open book priced (cost where unpriced), in `currency`."
    )
    threshold: float = Field(description="The line, in the jurisdiction's currency.")


class TaxAllYears(BaseModel):
    """Every finished tax year added up — a history, not a taxable base.

    Deliberately NOT a `TaxPeriod`, and the difference is the whole reason this
    model exists: allowances reset, brackets restart and a loss only crosses a
    year boundary as a carryforward, so there is no such thing as "net taxable
    over five years". Replaying the ledger as one long period would run five
    years of gains up a single progressive scale and invent a tax nobody owes;
    summing the years' own figures cannot, which is why the totals arrive as
    `kpis` — each year's engine computed its own, and these are those, added.
    """

    years: list[int] = Field(description="The tax years summed, oldest first.")
    realized_gain: float
    realized_loss: float
    disallowed_loss: float = 0.0
    recovered_loss: float = 0.0
    deductible_loss: float = 0.0
    sales: int = Field(default=0, description="Matched parcels across them all.")
    kpis: list[TaxKpi] = Field(
        default_factory=list,
        description="Each year's KPIs summed by key, in first-seen order.",
    )


class TaxSale(BaseModel):
    ticker: str
    buy_date: str = Field(
        description='Acquisition; for a pooled holding, the earliest still held.'
    )
    sell_date: str
    quantity: float
    cost: float
    proceeds: float
    gain: float
    matched: str = Field(description="fifo | lifo | average | s104 | pool.")
    term: str | None = Field(
        default=None,
        description=(
            '"long" or "short" where the jurisdiction taxes the two holding '
            "periods differently (US, AU, PT); null where it does not — Spain "
            "taxes a gain the same after a week or a decade, and a column "
            "saying so would be noise."
        ),
    )


class TaxReport(BaseModel):
    jurisdiction: str = Field(description="ES, US, UK… — the account's own setting.")
    resolved: str = Field(
        description=(
            "How that was arrived at: chosen | region | unmodelled | unknown. "
            "`unmodelled` means the caller's country is not modelled and these "
            "are somebody else's rules — a client has to say so."
        )
    )
    currency: str = Field(description="The jurisdiction's currency, not `base`.")
    matching: str = Field(description="Share-matching rule this replay used.")
    years: list[TaxPeriod] = Field(default_factory=list)
    all_years: TaxAllYears | None = Field(
        default=None,
        description=(
            "Those years added together, for a book that has more than one. "
            "Null when there is only one — it is already all of them, and an "
            "option that repeats the view below it is a control that does "
            "nothing."
        ),
    )
    months: list[TaxPeriod] = Field(
        default_factory=list,
        description=(
            "The same result by month booked. A breakdown, never a taxable base: "
            "every jurisdiction here nets over its own tax year."
        ),
    )
    sales: list[TaxSale] = Field(default_factory=list)
    funds_classified: bool = Field(
        default=False,
        description=(
            "Whether fund holdings were identified (DE exempts 30% of a fund's "
            "result). False = nobody checked, so no exemption was applied."
        ),
    )
    flags: list[TaxFlag] = Field(
        default_factory=list,
        description=(
            "Foreign-asset reporting thresholds measured against today's open "
            "book, converted to the jurisdiction's currency at spot — a "
            "threshold check, not a basis. Empty when the book could not be "
            "priced or the rate could not be fetched: no line beats a wrong one."
        ),
    )


# ----------------------------------------------------------------- how risky
# Today's basket backtested at fixed weights — a profile of what is held now.
# `/portfolio/performance` answers the other question, what the book actually
# did, and the two disagree whenever the book has changed shape.


class AllocationSlice(BaseModel):
    label: str
    weight: float


class RiskCurves(BaseModel):
    """Cumulative return over the window, three ways, on one date axis.

    The axis is the basket's own trading days. The book's TWR is sampled on
    calendar days, so putting it here drops the weekends it spends standing
    still — no value is interpolated and none is invented, and the three lines
    can finally be read against each other at a glance.

    Every series is rebased to the window's first day, which is the only way a
    comparison means anything: a book two years old and a benchmark fetched
    over six months have nothing to say to each other from their own zeros.
    Fractions, not percents — the caller multiplies for display, as it does
    everywhere else in this API.
    """

    dates: list[str] = Field(default_factory=list)
    portfolio: list[float | None] = Field(
        default_factory=list,
        description=(
            "The book's own flow-adjusted return, so deposits do not read as "
            "performance. Null on a day it could not be taken."
        ),
    )
    basket: list[float | None] = Field(
        default_factory=list,
        description=(
            "Today's holdings at today's weights, backtested over the same "
            "window. Not what the book did — what it would have done had it "
            "always been shaped like this."
        ),
    )
    benchmarks: dict[str, list[float | None]] = Field(
        default_factory=dict, description="One series per benchmark ticker."
    )


class Risk(BaseModel):
    base: str
    period: str = Field(description="Window the returns were measured over.")
    volatility: float | None = Field(default=None, description="Annualised.")
    max_drawdown: float | None = None
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
    curves: RiskCurves | None = Field(
        default=None,
        description=(
            "The three cumulative-return lines over this window. Null when the "
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


class Sectors(BaseModel):
    sectors: list[SectorSummary] = Field(default_factory=list)


class CohortRow(BaseModel):
    ticker: str
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


class SectorCohort(BaseModel):
    sector: str
    etf: str = ""
    as_of: str | None = None
    sort: str = Field(description="Metric the rows are ordered by.")
    ascending: bool
    podium: list[str] = Field(default_factory=list)
    rows: list[CohortRow] = Field(default_factory=list)
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


# ------------------------------------------------------------ the next prints
# The watchlist's reporting calendar. Upcoming dates and past results come back
# together because one fetch produces both — asking for them separately would
# double the requests to say the same thing twice.


class CalendarEvent(BaseModel):
    ticker: str
    date: str | None = Field(default=None, description="Reporting date, ISO.")
    days_until: int | None = Field(
        default=None, description="Days from today; 0 is a print due today."
    )


class CalendarResult(BaseModel):
    ticker: str
    date: str
    eps_estimate: float | None = None
    reported_eps: float | None = None
    surprise_pct: float | None = None
    beat: bool | None = Field(
        default=None,
        description="Null when there was nothing to compare, never False.",
    )


class TaxDeadline(BaseModel):
    """A filing date the account's tax residence imposes."""

    key: str = Field(
        description=(
            "Catalog stem: `earnings.tax_<key>` names it and `…_body` explains "
            "it, with `{year}` slotted."
        )
    )
    date: str = Field(description="Deadline, ISO, weekend-rolled where the law rolls it.")
    days_until: int = Field(description="Days from today; negative once it has passed.")
    year: str = Field(description='The tax year it concerns: "2025", "2025/26".')
    approximate: bool = Field(
        default=False,
        description="True where the date varies (by département, by canton).",
    )
    remind: bool = Field(
        default=False,
        description="Inside the reminder window: due within the next 30 days.",
    )


class EarningsCalendar(BaseModel):
    upcoming: list[CalendarEvent] = Field(
        default_factory=list, description="Soonest first; a same-day print counts."
    )
    results: list[CalendarResult] = Field(
        default_factory=list, description="Newest first, strictly before today."
    )
    groups: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "The filter sets the calendar offers: `portfolio` (open positions), "
            "`favorites`, then one per watchlist tag. Empty sets are left out, "
            "so a client can draw a pill per key without checking each one."
        ),
    )
    skipped: list[str] = Field(
        default_factory=list,
        description="Watchlist names that never report: coins and funds.",
    )
    jurisdiction: str | None = Field(
        default=None, description="The tax residence the deadlines are for."
    )
    tax_deadlines: list[TaxDeadline] = Field(
        default_factory=list,
        description=(
            "That jurisdiction's filing dates, about two months back to a year "
            "ahead, soonest first. Independent of the watchlist."
        ),
    )


# ------------------------------------------------------------ one past print
# The result dialog a past chip opens. The calendar payload carries the three
# EPS figures; everything under them — revenue, margins, the GAAP result, the
# surprise record, next quarter's consensus — is per ticker, three Yahoo
# payloads deep, and only worth fetching for the one print somebody clicked.
# Ratios are FRACTIONS (0.183 is 18.3%) as `stocks.data.earnings` computes them;
# the one exception is `price_reaction`, a percentage like `surprise_pct`.


class QuarterFigures(BaseModel):
    """One fiscal quarter as filed (GAAP), plus the ratios derived from it."""

    end: str = Field(description="Fiscal quarter end, ISO — not the report date.")
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    pretax_income: float | None = None
    tax_provision: float | None = None
    rnd: float | None = None
    diluted_eps: float | None = None
    diluted_shares: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    rnd_intensity: float | None = Field(default=None, description="R&D / revenue.")
    tax_rate: float | None = Field(
        default=None, description="Tax provision / pretax income."
    )
    revenue_yoy: float | None = Field(
        default=None,
        description="vs the same fiscal quarter a year back; null on a negative base.",
    )
    revenue_qoq: float | None = Field(
        default=None, description="vs the quarter immediately before."
    )


class QuarterBreakdown(BaseModel):
    """The reported quarter, with every comparison the dialog's tiles print."""

    quarter: QuarterFigures
    revenue_ttm: float | None = Field(
        default=None,
        description="Sum of the last four quarters; null unless all four are known.",
    )
    net_income_yoy: float | None = None
    shares_yoy: float | None = Field(
        default=None,
        description="Diluted share count vs a year back. Up is dilution — the bad way.",
    )
    gross_margin_bps: float | None = Field(
        default=None, description="Margin move vs the year-ago quarter, basis points."
    )
    operating_margin_bps: float | None = None
    net_margin_bps: float | None = None


class ConsensusPeriod(BaseModel):
    """Sell-side consensus for one period. Never company guidance."""

    period: str = Field(description='yfinance label: "0q", "+1q", "0y" or "+1y".')
    eps_avg: float | None = None
    eps_low: float | None = None
    eps_high: float | None = None
    eps_growth: float | None = None
    eps_analysts: int | None = None
    rev_avg: float | None = None
    rev_low: float | None = None
    rev_high: float | None = None
    rev_growth: float | None = None
    rev_analysts: int | None = None
    currency: str | None = None
    currency_prefix: str = Field(
        default="", description='What a figure is printed behind: "$", "€", "CHF ".'
    )


class EarningsResultDetail(BaseModel):
    ticker: str
    name: str = Field(default="", description='"" when no catalog knows the name.')
    logo: str | None = None
    date: str = Field(description="The report date asked about, ISO.")
    result: CalendarResult | None = Field(
        default=None,
        description="The print on that date; null when the feed has no figures for it.",
    )
    price_reaction: float | None = Field(
        default=None,
        description=(
            "% move across the print: last close before the date vs first close "
            "after, so it always contains the gap whatever the report's timing."
        ),
    )
    quarter_state: str = Field(
        default="none",
        description=(
            "`matched` — the income statement for the reported quarter is out; "
            "`pending` — statements exist but this quarter's is not published "
            "yet; `none` — the feed has no quarterly statement for the name."
        ),
    )
    currency: str | None = Field(
        default=None, description="Currency the income statement is filed in."
    )
    currency_prefix: str = ""
    breakdown: QuarterBreakdown | None = None
    trend: list[QuarterFigures] = Field(
        default_factory=list,
        description="Up to five most recent quarters, newest first.",
    )
    eps_gaap_gap: float | None = Field(
        default=None,
        description="Headline EPS minus the filed GAAP diluted EPS: the adjustment.",
    )
    history: list[CalendarResult] = Field(
        default_factory=list,
        description="Every reported print the feed carries for the name, newest first.",
    )
    outlook: ConsensusPeriod | None = Field(
        default=None, description="Next quarter's consensus; null when nobody covers it."
    )
    outlook_periods: list[ConsensusPeriod] = Field(
        default_factory=list,
        description=(
            "The quarter in flight, next quarter and both fiscal years, where known."
        ),
    )
    unavailable: bool = Field(
        default=False,
        description=(
            "The statement or estimate fetch failed this time (usually a rate "
            "limit). The headline still stands; the sections are missing, not empty."
        ),
    )


# ------------------------------------------------------------------ the regime
# The composite that says what kind of market this is, and — separately — what
# that regime does to one reader's own book. They are two endpoints because
# they are two different facts: a VIX percentile is the same number for
# everyone, "71% of your value is priced in dollars" is not.


class PulseComponent(BaseModel):
    key: str = Field(description="momentum | breadth | volatility | term | …")
    score: float | None = Field(
        default=None, description="This input's own 0-100 score."
    )
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
    notify_digest: bool = True
    notify_weekly: bool = True
    notify_alerts: bool = True
    # The Home first-run card, dismissed. An account setting rather than a
    # browser one: a reader who put the checklist away has put it away, and
    # meeting it again on their phone is the app forgetting a decision.
    setup_card_dismissed: bool = False
    # The other first-run card, and a different decision: the three steps to a
    # live portfolio. It says what to *do*; `setup_card_dismissed` hides what is
    # switched *on*. Same key the Streamlit page writes, so putting one away on
    # either front end puts it away on both.
    onboarding_dismissed: bool = False
    telegram_linked: bool = Field(
        default=False,
        description=(
            "Whether a Telegram chat is linked. The chat id itself stays on the "
            "server: a caller needs to know that notifications can be sent, not "
            "where the cron sends them."
        ),
    )
    chat_panel_open: bool = False


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


# ---------------------------------------------------------------- the importer
# A broker statement becoming ledger rows. The shape mirrors what the page
# does, because the tiers are the safety property: a bad export must not be
# able to corrupt a cost basis quietly, so rows that failed validation are
# quarantined and reported rather than dropped or committed.


class ImportPlatform(BaseModel):
    key: str = Field(description="Stable id; what a preview or commit is asked for.")
    label: str
    file_types: list[str] = Field(description="Extensions this parser accepts.")
    hint: str = Field(description="Where to find the export on that platform.")
    domain: str | None = Field(default=None, description="Brand site, for a logo.")
    logo: str | None = Field(
        default=None,
        description=(
            "The brand mark, same-origin where this host could mirror it (the "
            "external URL otherwise) — what the Streamlit picker draws beside "
            "each name. Null for a platform with no brand, and the client "
            "prints the name alone."
        ),
    )
    has_sample: bool = Field(
        default=False, description="Whether a shipped example export exists."
    )


class ImportPlatforms(BaseModel):
    platforms: list[ImportPlatform] = Field(default_factory=list)


class ImportIssue(BaseModel):
    severity: str = Field(description="error | warning.")
    field: str
    key: str = Field(description="i18n key, e.g. `validate.oversell`.")
    params: dict = Field(default_factory=dict)
    message: str = Field(
        description="English rendering. A client with a catalog should use `key`."
    )


class ImportRow(BaseModel):
    date: str
    ticker: str
    action: str
    quantity: float
    price: float
    currency: str
    fee: float = 0.0
    note: str = ""
    issues: list[ImportIssue] = Field(default_factory=list)
    duplicate: bool = Field(
        default=False, description="Repeats a row the ledger already holds."
    )


class ImportPreview(BaseModel):
    """What a statement would do, having changed nothing.

    Three tiers, and they are not a presentation detail: `rejected` rows failed
    validation and are never committed, so a client that shows only a count has
    hidden the part the reader has to act on.
    """

    platform: str
    filename: str
    digest: str = Field(
        description=(
            "SHA-256 of the uploaded bytes. Pass it back as `expect` on commit "
            "to be told, rather than guess, whether you are committing the file "
            "you previewed."
        )
    )
    importable: list[ImportRow] = Field(
        default_factory=list, description="Clean and warned rows — what a commit writes."
    )
    rejected: list[ImportRow] = Field(
        default_factory=list,
        description="Failed validation: quarantined, never committed.",
    )
    duplicates: int = Field(
        default=0, description="Importable rows the ledger already holds."
    )
    skipped: list[dict] = Field(
        default_factory=list,
        description="Rows the parser leaves out by design: cash, fees, tax lines.",
    )
    broker: str = Field(
        default="",
        description=(
            "Origin detected from the rows' own notes. Empty means the parser "
            "stamped none — a generic CSV can come from anywhere — and a commit "
            "has to be told which broker, or the batch lands unattributed in the "
            "fees and custody views."
        ),
    )
    needs_broker: bool = Field(
        default=False, description="Whether a commit must supply `broker`."
    )


class ImportResult(BaseModel):
    platform: str
    filename: str
    imported: int = Field(description="Rows written to the ledger.")
    tx_ids: list[int] = Field(
        default_factory=list, description="Ledger ids, which is what an undo needs."
    )
    broker: str
    imported_at: str
    rejected: list[ImportRow] = Field(
        default_factory=list,
        description=(
            "Re-validated at commit time and refused. Reported rather than "
            "silently dropped: the ledger moved since the preview, and a row "
            "that passed then can fail now."
        ),
    )


class LastImport(BaseModel):
    """The most recent committed batch, or nothing.

    Kept so an import can be undone exactly — those ids and no others — rather
    than by guessing which rows a file put there.
    """

    filename: str | None = None
    imported_at: str | None = None
    platform: str | None = None
    rows: int = 0
    still_here: int = Field(
        default=0,
        description=(
            "How many of those rows are still in the ledger. Rows can leave "
            "after a commit — deleted one by one, or taken by another undo — "
            "and an offer to undo a batch has to be an offer to undo what is "
            "actually there."
        ),
    )
    transactions: list[Transaction] = Field(
        default_factory=list,
        description=(
            "Those surviving rows themselves, so the reader can see what an "
            "undo would take rather than trust a count."
        ),
    )
    wiped: bool = Field(
        default=False, description="Whether the ledger was cleared just before it."
    )


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


class LedgerCleared(BaseModel):
    """What a wipe destroyed, said in numbers because nothing else is left."""

    removed: int = Field(description="Transactions deleted.")


# ------------------------------------------------------------- the daily glance
# What the dashboard opens with. The briefing is prose a model wrote; the two
# below it are arithmetic over prices already in hand.


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
            "Which day's card is current right now. Before the 09:00 cutoff "
            "that is yesterday: at 07:40 the day has no numbers in it yet."
        )
    )
    cutoff_hour: int = Field(description="Local hour the action day rolls over.")
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
    positions: int = Field(
        default=0, description="Open positions in the book."
    )
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



class TrendBlock(BaseModel):
    block: str = Field(
        description="indices | gauges | rates | inflation | rotation | cross."
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


# ------------------------------------------------------------------ bank
# PSD2 account information: balances read from the user's own bank, which the
# ledger cannot see. Shaped for a card per connection, an account per row.


class BankAccount(BaseModel):
    """One account inside a consent, with its last read balance."""

    uid: str = Field(description="Opaque handle; the only id the bank hands out.")
    name: str = ""
    masked_id: str = Field(
        default="",
        description="IBAN down to what identifies it to its owner: ES12 ···· 3456.",
    )
    currency: str = ""
    product: str = ""
    balance: float | None = Field(
        default=None,
        description=(
            "The balance a person means by 'how much is in the account' — "
            "booked or available, whatever else the bank also reports. Null "
            "until the account has been read once, and null again when the "
            "bank's figure would not parse: a zero is a claim about somebody's "
            "money and 'unreadable' is not that claim."
        ),
    )
    balance_currency: str = ""
    fetched_at: str | None = Field(
        default=None,
        description=(
            "When that balance was read, ISO UTC. Banks cap fetches (commonly "
            "four a day), so the page shows a stored figure and says how old "
            "it is rather than refetching on every load."
        ),
    )


class BankConnection(BaseModel):
    """One bank, consented to once, until `valid_until`."""

    session_id: str
    name: str
    country: str
    valid_until: str = Field(
        default="", description="When the consent runs out, ISO. '' when unstated."
    )
    connected_at: str = ""
    expired: bool = Field(
        default=False,
        description=(
            "Whether that date has passed. Computed here because the same date "
            "is backdated when the bank refuses a fetch early, which is how a "
            "revoked consent becomes a reconnect offer instead of a dead button."
        ),
    )
    accounts: list[BankAccount] = Field(default_factory=list)


class BankState(BaseModel):
    """Everything the bank page draws."""

    available: bool = Field(
        description=(
            "Whether this account may use the feature. False is the ordinary "
            "answer and not a failure: the application runs in Enable Banking's "
            "restricted mode, so the gate is an allowlist that fails closed."
        )
    )
    redirect_url: str = Field(
        default="",
        description=(
            "Where the bank will send the user back to. '' when this host "
            "cannot offer one — banks only redirect to https, which is what "
            "makes a plain local dev server unable to start a consent."
        ),
    )
    connections: list[BankConnection] = Field(default_factory=list)


class BankChoice(BaseModel):
    """One bank that can be connected, from Enable Banking's own list."""

    name: str
    country: str
    logo: str | None = None


class BankAuth(BaseModel):
    """Where to send the user, and the round trip it belongs to."""

    url: str = Field(description="The bank's own authentication page.")
    bank: str
    state: str = Field(
        description=(
            "Echoed by the bank on the way back. Stored server-side too — this "
            "copy is for a client that wants to recognise its own round trip, "
            "never for proving one: the stored entry is the authority."
        )
    )
