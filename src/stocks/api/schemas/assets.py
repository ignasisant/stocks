"""What only some kinds of asset carry: fund holdings, cash yield,
closed-end discounts, crypto's cycle and positioning.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FundHolding(BaseModel):
    symbol: str
    name: str
    weight: float = Field(description="Fraction of the fund: 0.075 is 7.5%.")


class FundWrapper(BaseModel):
    share_class: str | None = Field(
        default=None, description="'acc' reinvests income, 'dist' pays it out."
    )
    domicile: str | None = Field(
        default=None, description="ISO country of the fund, from its ISIN or name."
    )
    ucits: bool = False
    hedged: str | None = Field(
        default=None, description="The currency the line is hedged to, if any."
    )
    synthetic: bool = Field(
        default=False,
        description="The name says swap or synthetic. False is not 'physical'.",
    )
    tracks: str | None = Field(default=None, description="The index, as named.")
    exposure: str | None = Field(
        default=None,
        description=(
            "Where its stocks trade: em, china, japan, nasdaq, world, europe, us."
        ),
    )
    window_start: str | None = Field(
        default=None,
        description=(
            "Today's stretch when the line and its stocks are both open, ISO "
            "UTC: when its spread is tightest. Null with `underlying_closed` "
            "false means the whole session overlaps."
        ),
    )
    window_end: str | None = None
    underlying_closed: bool = Field(
        default=False,
        description="Its stocks' market is shut for the line's whole session.",
    )


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
    average_traded: float | None = Field(
        default=None,
        description=(
            "Money that changes hands on an average day (Yahoo's average "
            "volume times the price), in `traded_currency`."
        ),
    )
    traded_currency: str | None = None
    wrapper: FundWrapper | None = Field(
        default=None,
        description=(
            "What the fund's name says about the wrapper around its basket: "
            "share class, domicile, hedge, the index it tracks and where its "
            "stocks trade. Each field null where the name is silent."
        ),
    )
    closed_end: ClosedEnd | None = Field(
        default=None,
        description=(
            "Set for a listed closed-end fund (Yahoo files those as EQUITY): "
            "its NAV, premium, distribution rate and filed balance sheet, each "
            "with the source it came from. None for an ETF or mutual fund."
        ),
    )
    cash: CashYield | None = Field(
        default=None,
        description=(
            "Set for a money-market fund only: what it has earned, annualised, "
            "beside the central bank rate it tracks. The number that fund is "
            "held for — its chart is a straight line."
        ),
    )


class CashYield(BaseModel):
    yield_3m: float | None = Field(
        default=None, description="Last three months, annualised: 0.021 is 2.1%."
    )
    yield_1y: float | None = Field(default=None, description="Last twelve months.")
    as_of: str | None = Field(
        default=None, description="YYYY-MM-DD of the last close read."
    )
    source: str = Field(
        default="price",
        description=(
            "price — read off the accumulating price; distribution — Yahoo's "
            "yield, for a fund whose price is pinned at 1 and pays it out."
        ),
    )
    bank: str | None = Field(
        default=None, description="ecb | fed — whose rate it tracks."
    )
    policy_rate: float | None = Field(
        default=None, description="That bank's rate (Fed: its target range's midpoint)."
    )
    policy_as_of: str | None = None


class SourcedFigure(BaseModel):
    """One number and the source it was read from — or the sources asked."""

    value: float | None = None
    source: str | None = Field(
        default=None,
        description=(
            "yahoo | yahoo_nav | edgar_xbrl | edgar_nport; None when no source had it."
        ),
    )
    as_of: str | None = Field(default=None, description="YYYY-MM-DD the figure is for.")
    tried: list[str] = Field(
        default_factory=list,
        description=(
            "Sources asked that had nothing. With no value, why the tile is "
            "empty; with a value, the second opinion that could not be had."
        ),
    )


class SourceCheck(BaseModel):
    """A filed figure against the market feed's, on the filing's own date."""

    metric: str = Field(description="nav | premium.")
    as_of: str
    official: float
    official_source: str
    market: float | None = Field(
        default=None, description="None when the market feed has no row for that session."
    )
    market_source: str
    agree: bool | None = Field(
        default=None,
        description="None when nothing was compared — not the same as agreeing.",
    )
    tolerance: float = Field(
        description="Allowed gap: relative for nav (0.01 = 1%), points for premium."
    )


class ClosedEnd(BaseModel):
    nav_symbol: str = Field(description="Yahoo's NAV line for the fund, e.g. XMUAX.")
    nav: SourcedFigure
    price: SourcedFigure
    premium: SourcedFigure = Field(
        description="Price ÷ NAV − 1 on one session: −0.05 is a 5% discount."
    )
    distribution_rate: SourcedFigure = Field(
        description="Annual distribution ÷ price. Can include return of capital."
    )
    expense_ratio: SourcedFigure
    net_assets: SourcedFigure
    total_assets: SourcedFigure
    leverage: SourcedFigure = Field(
        description="Liabilities ÷ total assets from the N-PORT balance sheet."
    )
    holdings_count: int | None = None
    holdings_as_of: str | None = None
    checks: list[SourceCheck] = Field(default_factory=list)


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
    ath: float | None = Field(
        default=None,
        description=(
            "All-time high in the pair's quote currency, from last night's scan; "
            "the 52-week high when the scan does not cover the coin (`ath_source`)."
        ),
    )
    ath_date: str | None = None
    ath_source: str | None = Field(
        default=None, description="`scan` (a true all-time high) | `52w` (the stand-in)."
    )
    fdv: float | None = Field(
        default=None, description="Fully diluted value: price times the eventual supply."
    )
    fdv_ratio: float | None = Field(
        default=None, description="FDV over market cap; 1.0 is everything already out."
    )
    dilution: str | None = Field(default=None, description="none | some | heavy.")
    max_supply: float | None = Field(
        default=None, description="Null for an uncapped coin."
    )
    total_supply: float | None = None
    issued_pct: float | None = Field(
        default=None, description="Circulating over max supply, 0..1."
    )
    rank: int | None = Field(default=None, description="Market-cap rank.")
    category: str | None = Field(
        default=None,
        description=(
            "store_of_value | smart_contract | layer2 | stablecoin | payments | "
            "exchange | defi | infrastructure | meme | gaming. Null when uncurated."
        ),
    )


class Banded(BaseModel):
    """A figure, the band it falls in and that band's tone."""

    value: float | None = None
    band: str | None = Field(default=None, description="An i18n suffix.")
    tone: str | None = Field(default=None, description="green | gray | orange | red.")


class HalvingPhase(BaseModel):
    last: str
    days_since: int
    next_est: str = Field(
        description="An estimate: block 1,050,000 lands with hash rate."
    )
    days_to_next: int
    progress: float = Field(description="0..1 of the way to the next halving.")


class StablecoinSupply(BaseModel):
    """All stablecoins' circulating supply: dry powder waiting at the door."""

    usd: float = Field(description="Summed circulating supply, US dollars.")
    change_30d: float | None = Field(default=None, description="A fraction.")
    change_90d: float | None = Field(default=None, description="A fraction.")


class CryptoOnchain(BaseModel):
    """What DefiLlama sees on the coin's chain or protocol."""

    kind: str = Field(description="chain | protocol.")
    name: str
    tvl: float = Field(description="Total value locked, US dollars.")
    tvl_change_30d: float | None = Field(default=None, description="A fraction.")
    fees_30d: float | None = Field(default=None, description="US dollars paid by users.")
    revenue_30d: float | None = Field(
        default=None, description="US dollars kept by the protocol or its holders."
    )


class ImpliedVol(BaseModel):
    """Deribit's DVOL: the volatility the options market prices for 30 days."""

    coin: str = Field(description="BTC | ETH — the index the figure is read from.")
    value: float = Field(description="Annualised, percent points (52.0 = 52%).")
    percentile: Banded | None = Field(
        default=None, description="Where it sits over the past year, 0..100."
    )
    low: float | None = None
    high: float | None = None
    week_ago: float | None = None


class CryptoCycle(BaseModel):
    """Where a coin and the market sit in the cycle — the stand-in for the
    analyst consensus a coin does not have."""

    ticker: str
    quote: str
    fear_greed: Banded | None = Field(
        default=None, description="The Crypto Fear & Greed Index today, 0..100."
    )
    fear_greed_week: float | None = Field(
        default=None, description="The index a week ago, for the direction."
    )
    fear_greed_history: list[tuple[str, int]] = Field(
        default_factory=list, description="The past 90 days, oldest first."
    )
    btc_dominance: float | None = Field(default=None, description="Percent, 0..100.")
    total_mcap: float | None = Field(
        default=None, description="The whole market's capitalisation, in `quote`."
    )
    vol30: float | None = Field(
        default=None, description="Annualised 30-day realised volatility."
    )
    mayer: Banded | None = Field(
        default=None, description="Price over its 200-day average."
    )
    ratio_200w: Banded | None = Field(
        default=None, description="Price over its 200-week average."
    )
    vs_btc_90d: float | None = Field(
        default=None,
        description=(
            "How much the coin beat (+) or lagged bitcoin over 90 days; null for bitcoin."
        ),
    )
    vs_nasdaq_90d: float | None = Field(
        default=None, description="Bitcoin's own 90 days against the Nasdaq 100 (QQQ)."
    )
    halving: HalvingPhase | None = None
    stablecoins: StablecoinSupply | None = None
    onchain: CryptoOnchain | None = Field(
        default=None, description="Only for a coin DefiLlama maps to a chain or protocol."
    )
    scan_date: str | None = Field(
        default=None, description="When the market figures were read."
    )


class CryptoPositioning(BaseModel):
    """The coin's perpetual swap: what leveraged longs pay, and how much is open."""

    ticker: str
    venue: str = Field(description="bybit | binance | okx.")
    symbol: str
    funding_8h: Banded | None = Field(
        default=None, description="Current funding per eight hours, a fraction."
    )
    funding_7d_8h: Banded | None = Field(
        default=None, description="The past week's mean, per eight hours."
    )
    annualized: float | None = Field(
        default=None, description="What a long pays over a year at the weekly mean."
    )
    oi_usd: float | None = Field(default=None, description="Open interest, US dollars.")
    oi_change_7d: float | None = Field(
        default=None,
        description="In contracts, so a price move does not read as positioning.",
    )
    implied_vol: ImpliedVol | None = Field(
        default=None,
        description="The coin's own DVOL for BTC and ETH, bitcoin's for the rest.",
    )
    as_of: str


class CoinHarvest(BaseModel):
    """Selling the whole coin today: the loss it books and the tax it saves."""

    loss: float = Field(description="Negative, in `currency`.")
    saving: float = Field(description="Tax saved this year, positive, in `currency`.")
    currency: str
    blocked: bool = Field(
        default=False,
        description="A repurchase inside the window would defer the loss.",
    )
    window: str | None = Field(
        default=None,
        description='The repurchase window as the engine labels it: "2m", "30d".',
    )
    clear_on: str | None = Field(
        default=None, description="First day a buy-back no longer defers the loss."
    )


class CryptoHolding(BaseModel):
    """The coin in this account's book — the line no market data source has."""

    ticker: str
    held: bool
    crypto_weight: float | None = Field(
        default=None, description="This coin's share of the book's crypto, 0..1."
    )
    crypto_share: float | None = Field(
        default=None, description="All crypto's share of the whole book, 0..1."
    )
    sizing: str | None = Field(
        default=None,
        description=(
            "under | within | over the 2-10% range a crypto sleeve is usually held at."
        ),
    )
    custody: list[str] = Field(
        default_factory=list, description="Brokers holding the coin, by display name."
    )
    harvest: CoinHarvest | None = Field(
        default=None, description="Only when the coin is held at a loss."
    )


class FundOverlap(BaseModel):
    symbol: str = Field(description="The book's symbol for the company.")
    name: str
    fund_weight: float = Field(description="Its share of the fund: 0.05 is 5%.")
    book_weight: float = Field(description="Its share of the book, held directly.")


class FundSectorRow(BaseModel):
    label: str
    book: float = Field(description="The book's share, funds looked through.")
    fund: float = Field(description="The fund's share.")
    without: float | None = Field(
        default=None,
        description="The book's share with this fund taken out; null when not held.",
    )


class FundFit(BaseModel):
    ticker: str
    base: str | None = None
    held: bool = False
    fund_share: float | None = Field(
        default=None, description="The fund's share of the book, when held."
    )
    overlap: list[FundOverlap] = Field(
        default_factory=list,
        description="The fund's disclosed top holdings the book also holds directly.",
    )
    overlap_weight: float = Field(
        default=0.0, description="What those holdings add up to inside the fund."
    )
    disclosed_weight: float = Field(
        default=0.0, description="What the disclosed holdings add up to at all."
    )
    sectors: list[FundSectorRow] = Field(default_factory=list)
    sector_cap: float | None = Field(
        default=None, description="The plan's cap on one sector, as a fraction."
    )
    trades: int = Field(default=0, description="The reader's own buys and sells of it.")
    spread: float | None = Field(
        default=None,
        description=(
            "What those fills paid against the day's mid, as a fraction of "
            "what they traded: 0.002 is 0.2%. Null when none could be measured."
        ),
    )
    commission: float | None = Field(
        default=None, description="Their commissions, as a fraction of what they traded."
    )
    jurisdiction: str | None = Field(
        default=None, description="The tax jurisdiction the account is taxed under."
    )
