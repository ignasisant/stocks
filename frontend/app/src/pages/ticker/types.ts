/**
 * The shapes `/api/v1/ticker/*` and the handful of routes beside it actually
 * send, transcribed from `src/stocks/api/schemas.py`.
 *
 * Every `| null` here is one the API means. A position nobody could price has
 * no value, an indicator still warming up has no reading, a company no
 * regulator publishes insider filings for has no source — and none of those is
 * a zero. They are typed nullable so no renderer can quietly print one as a
 * figure.
 */

export type Bars = {
  ticker: string;
  range: string;
  /** Bar size the range downloads at, e.g. `1d`. Decides what a gap means. */
  interval: string;
  /** Exchange-local wall time, no zone — the axis the page draws. */
  dates: string[];
  /** Column per series, aligned to `dates`. Null is absent, not zero. */
  series: Record<string, (number | null)[]>;
  dividends: (number | null)[];
  /** The domain's band on the latest RSI(14); null while it warms up. */
  rsi_verdict: string | null;
  rsi_tone: string | null;
  /**
   * Plotly-shaped axis breaks hiding closed-market time. This page plots on a
   * bar INDEX rather than a timestamp, which removes the same gaps without
   * them, so the field is carried and unused rather than silently dropped.
   */
  rangebreaks: Record<string, unknown>[];
  /** The listing's first trading day (`YYYY-MM-DD`); null when unknown. */
  listed?: string | null;
  /**
   * The range labels worth offering, in display order: a window longer than
   * the listing's whole history is left out, since it draws what "max" does.
   */
  ranges?: string[];
};

export type Quote = {
  ticker: string;
  price: number | null;
  /** Day move, as a fraction. */
  pct: number | null;
  /** "pre", "post", or null for the regular session. */
  session: string | null;
  as_of: string | null;
  /** Inside the regular session the bars already track the live price. */
  market_open: boolean | null;
  /** The listing's own quote currency, minor units included (GBp). */
  currency: string | null;
  /** `price` restated in `base`, when the two differ and a rate was had. */
  price_base: number | null;
  fx_rate: number | null;
  fx_as_of: string | null;
  /** The reporting currency asked for. */
  base: string | null;
};

export type Trade = {
  date: string;
  /** buy | sell. */
  action: string;
  /** Already split-adjusted, so a pre-split buy plots where it belongs. */
  price: number;
  quantity: number;
};

export type Custodian = {
  /** Ledger note prefix. `manual` and `unknown` are buckets, not brands. */
  broker: string;
  /** Empty for those two buckets, whose names are translated, not branded. */
  name: string;
  logo: string | null;
  shares: number;
  /** Its fraction of the open position, 0..1. */
  share: number;
};

export type TickerPosition = {
  ticker: string;
  held: boolean;
  shares: number | null;
  currency: string | null;
  cost_native: number | null;
  avg_cost_native: number | null;
  base: string | null;
  /** Null means the price pass had nothing — never that it is worth zero. */
  value: number | null;
  weight: number | null;
  /** Every buy and sell, oldest first; present even when the position closed. */
  trades: Trade[];
  brokers: Record<string, number>;
  custody: Custodian[];
};

/** A forward split this name's ledger lacks, with the price that gave it away. */
export type TickerSplit = {
  date: string;
  /** Shares out per share in — 20 for a 20-for-1. */
  ratio: number;
  held_before: number;
  held_after: number;
  /** The pre-split buy price, as the statement printed it, and its day. */
  priced_at: number;
  priced_on: string;
  /** Yahoo's split-adjusted close that day. */
  market_close: number;
  currency: string;
  /** Written once and undone by the reader: never written again unasked. */
  declined: boolean;
};

export type TickerSplits = {
  ticker: string;
  splits: TickerSplit[];
  /** Yahoo was refusing us: an empty list means "could not tell". */
  throttled: boolean;
};

export type TickerSplitsApplied = {
  ticker: string;
  /** The journal entry; deleting `/portfolio/changes/{id}` undoes it. */
  change_id: number;
  splits: TickerSplit[];
};

export type Profile = {
  /** As stored: the label the ledger and every link keep. */
  ticker: string;
  /** What it resolves to. An ISIN-keyed holding reads as its ticker. */
  symbol: string;
  /** "" when no source knows one — print the symbol, never invent. */
  name: string;
  logo: string | null;
  is_crypto: boolean;
  is_fund: boolean;
  /**
   * What kind of thing this is — `stocks.data.asset_kind` — and so which
   * layout the page draws. null for a future or a currency pair, and absent
   * from an older server: both read as the booleans above.
   */
  asset?: string | null;
};

export type AssetStats = {
  ticker: string;
  quote: string;
  market_cap: number | null;
  volume_24h: number | null;
  circulating_supply: number | null;
  high_52w: number | null;
  low_52w: number | null;
  /** All-time high in the pair's quote; the 52-week high when the scan has none. */
  ath?: number | null;
  ath_date?: string | null;
  /** "scan" (CoinGecko's peak) or "52w" (only the past year's). */
  ath_source?: "scan" | "52w" | null;
  fdv?: number | null;
  fdv_ratio?: number | null;
  /** none | some | heavy — the fdv_ratio's band. */
  dilution?: string | null;
  max_supply?: number | null;
  total_supply?: number | null;
  /** Circulating over the hard cap, 0..1; null for an uncapped coin. */
  issued_pct?: number | null;
  rank?: number | null;
  /** A key of `ticker.crypto_cat_*`, or null — never a guess. */
  category?: string | null;
};

/** A figure, its band key (an i18n suffix) and its tone. */
export type Banded = { value: number | null; band: string | null; tone: string | null };

type HalvingPhase = {
  last: string;
  days_since: number;
  next_est: string;
  days_to_next: number;
  progress: number;
};

export type CryptoCycle = {
  ticker: string;
  quote: string;
  fear_greed: Banded | null;
  fear_greed_week: number | null;
  /** The past 90 days, oldest first, as [day, 0..100]. */
  fear_greed_history: [string, number][];
  btc_dominance: number | null;
  total_mcap: number | null;
  vol30: number | null;
  mayer: Banded | null;
  ratio_200w: Banded | null;
  vs_btc_90d: number | null;
  vs_nasdaq_90d: number | null;
  halving: HalvingPhase | null;
  scan_date: string | null;
};

export type CryptoPositioning = {
  ticker: string;
  venue: string;
  symbol: string;
  funding_8h: Banded | null;
  funding_7d_8h: Banded | null;
  annualized: number | null;
  oi_usd: number | null;
  oi_change_7d: number | null;
  as_of: string;
};

type CoinHarvest = {
  loss: number;
  saving: number | null;
  currency: string;
  blocked: boolean;
  window: string | null;
  clear_on: string | null;
};

export type CryptoHolding = {
  ticker: string;
  held: boolean;
  crypto_weight: number | null;
  crypto_share: number | null;
  sizing: "under" | "within" | "over" | null;
  custody: string[];
  harvest: CoinHarvest | null;
};

export type KpiSourceRow = {
  key: string;
  label: string;
  /** pct | x | money | score | ratio — how the raw number reads. */
  unit: string;
  /** fact | consensus | derived. */
  level: string;
  loader: string;
  verify: string;
  note: string;
  desc: string;
};

export type EarningsEvent = {
  date: string;
  eps_estimate: number | null;
  /** Null for a date that has not reported yet. */
  reported_eps: number | null;
  surprise_pct: number | null;
  beat: boolean | null;
};

/** A dated moment in a coin's history: halving, ETF approval, the Merge. */
export type CycleEvent = { date: string; kind: string };

export type PriceEvents = {
  ticker: string;
  earnings: EarningsEvent[];
  /** A coin's cycle events; absent from an older server. */
  cycle?: CycleEvent[];
};

type Kpi = {
  key: string;
  label: string;
  value: number | string | null;
  /** Ready to print, units baked in; "n/a" when absent. */
  formatted: string;
  unit: string;
  /** fact | consensus | derived — print it, it is not decoration. */
  level: string;
  verdict: string | null;
  /** green | orange | red | gray. Colour by this, never by the label. */
  verdict_tone: string | null;
  desc: string;
};

type MetricTile = {
  key: string;
  /** An i18n KEY, not a string: the API has no language. */
  label_key: string;
  help_key: string | null;
};

export type Metrics = {
  ticker: string;
  currency: string | null;
  quote_type: string | null;
  /** All 23 of them — a reference table, not a screen. */
  kpis: Kpi[];
  /** The handful the page actually draws, in order. */
  grid: MetricTile[];
  /** Market cap in the reader's own money; only computed with `?base=`. */
  market_cap_base: number | null;
  /** …formatted by the server, so the client never rounds it. */
  market_cap_base_formatted: string | null;
  fx_rate: number | null;
  fx_as_of: string | null;
  base: string | null;
};

type AnnualRow = {
  year: string;
  revenue: number | null;
  net_income: number | null;
  eps: number | null;
};

type ProjectedRow = {
  period: string;
  revenue: number | null;
  revenue_low: number | null;
  revenue_high: number | null;
  eps: number | null;
  eps_low: number | null;
  eps_high: number | null;
  /**
   * Carried forward on a growth rate past the last published estimate — a
   * guess, not a poll. The low/high range is null once this is true.
   */
  revenue_extrapolated: boolean;
  eps_extrapolated: boolean;
};

type QuarterlyEps = { period: string; eps: number | null };

export type Financials = {
  ticker: string;
  currency: string | null;
  annual: AnnualRow[];
  quarterly_eps: QuarterlyEps[];
  /** Consensus, not fact. Drawn apart from the reported years, never merged. */
  projection: ProjectedRow[];
  estimate_currency: string | null;
};

type ValuationWindow = {
  window: string;
  /** Its span in calendar days — what trims the series to what is shown. */
  days: number;
  mean: number | null;
  median: number | null;
  low: number | null;
  high: number | null;
  percentile: number | null;
  premium: number | null;
};

export type Valuation = {
  ticker: string;
  /** Which filing feed backed it; null when neither had the quarters. */
  source: string | null;
  current: number | null;
  /** Today's P/E on the grid's pe_ttm bands, and that band's tone. */
  current_verdict: string | null;
  current_tone: string | null;
  dates: string[];
  pe: (number | null)[];
  windows: ValuationWindow[];
};

export type MoatPillar = {
  key: string;
  /** English; the fallback when the catalog lacks `label_key`. */
  label: string;
  label_key: string;
  score: number | null;
  /** The moat band's colour at this score (green | orange | red). */
  tone: string | null;
  weight: number;
  /** English; the fallback when the catalog lacks `detail_key`. */
  detail: string;
  detail_key: string;
  /** Fills `detail_key`: fractions as fractions, counts as counts. */
  facts: Record<string, number>;
};

export type Moat = {
  ticker: string;
  score: number | null;
  rating: string | null;
  rating_key: string | null;
  /** The band's tone (green | orange | red); null with no score. */
  rating_tone: string | null;
  years: number;
  pillars: MoatPillar[];
};

type InsiderTrade = {
  date: string | null;
  insider: string;
  role: string;
  code: string;
  /** The code in English words — the fallback when the catalog lacks it. */
  label: string;
  /** Signed: negative for a disposal. */
  shares: number;
  price: number | null;
  /** Signed notional; null with no price. Never summed across currencies. */
  value: number | null;
  /** A real purchase or sale (P/S), not a grant or an option exercise. */
  is_open_market: boolean;
  currency: string | null;
};

type InsiderSummary = {
  window_days: number;
  buy_count: number;
  sell_count: number;
  buy_shares: number;
  sell_shares: number;
  buy_value: number;
  sell_value: number;
  buyers: number;
  sellers: number;
  net_value: number;
  /** Two or more distinct insiders buying, outweighing the sells. */
  cluster_buy: boolean;
};

export type Insiders = {
  ticker: string;
  /** null means nobody publishes for this name — not that nothing happened. */
  source: string | null;
  summary: InsiderSummary | null;
  trades: InsiderTrade[];
  /**
   * Whether the SEC map knows the symbol; null when the lookup failed. It is
   * what tells "a US filer whose insiders have not traded" from "a foreign
   * issuer that never files Form 4".
   */
  sec_filer: boolean | null;
};

/** One month of the sell-side split. */
export type AnalystMonth = {
  /** "YYYY-MM". */
  month: string;
  strong_buy: number;
  buy: number;
  hold: number;
  sell: number;
  strong_sell: number;
  total: number;
  /** 1 (strong buy) .. 5 (strong sell). */
  mean: number | null;
};

/** 12-month price targets, in the quote's currency. Consensus, never fact. */
type AnalystTargets = {
  low: number | null;
  median: number | null;
  mean: number | null;
  high: number | null;
  /** Fractions: 0.12 is a target 12% above the price. */
  upside_mean: number | null;
  upside_median: number | null;
  /** (high - low) / mean. */
  dispersion: number | null;
};

export type EpsRevisionRow = {
  /** "0y" current FY, "+1y" next FY. */
  period: string;
  current: number | null;
  /** Fractions over the old figure's magnitude. */
  change_7d: number | null;
  change_30d: number | null;
  change_90d: number | null;
  up_7d: number | null;
  up_30d: number | null;
  down_7d: number | null;
  down_30d: number | null;
};

export type Analysts = {
  ticker: string;
  currency: string | null;
  price: number | null;
  /** Ratings in the latest month; 0 when nobody covers the name. */
  analysts: number;
  /** False under `min_coverage`: one or two opinions are not a consensus. */
  covered: boolean;
  min_coverage: number;
  rating: string | null;
  rating_mean: number | null;
  /** Oldest month first. */
  months: AnalystMonth[];
  targets: AnalystTargets | null;
  revisions: EpsRevisionRow[];
};

type FundHolding = { symbol: string; name: string; weight: number };

export type Fund = {
  ticker: string;
  is_fund: boolean;
  name: string;
  quote_type: string | null;
  currency: string | null;
  category: string | null;
  family: string | null;
  expense_ratio: number | null;
  aum: number | null;
  dividend_yield: number | null;
  turnover: number | null;
  description: string;
  legal_type: string | null;
  bond_duration: number | null;
  /** Over half in bonds: duration replaces the top-ten tile. */
  is_bond_fund: boolean;
  holdings: FundHolding[];
  /** What those holdings add up to — a floor on concentration, not the book. */
  disclosed_weight: number;
  /** [[label, fraction], …] */
  sectors: [string, number][];
  asset_classes: [string, number][];
  /** Set for a listed closed-end fund, which Yahoo files as an ordinary share. */
  closed_end?: ClosedEnd | null;
  /** Set for a money-market fund: what it yields, against the rate it tracks. */
  cash?: CashYield | null;
};

/**
 * A money-market fund's yield and the central-bank rate beside it.
 *
 * Off its own adjusted closes (`source: "price"`) for an accumulating fund;
 * off a year of payouts (`"distribution"`) for one whose NAV is pinned at 1,
 * which has no three-month figure. Fractions throughout.
 */
type CashYield = {
  yield_3m: number | null;
  yield_1y: number | null;
  as_of: string | null;
  source: "price" | "distribution";
  /** ecb | fed — null when the fund's currency has no bank mapped. */
  bank: string | null;
  policy_rate: number | null;
  policy_as_of: string | null;
};

/** Where a closed-end fund figure was read: yahoo | yahoo_nav | edgar_xbrl | edgar_nport. */
export type FigureSource = string;

export type SourcedFigure = {
  value: number | null;
  /** null when no source had the figure. */
  source: FigureSource | null;
  as_of: string | null;
  /** Sources asked that had nothing — why a tile is empty, or unchecked. */
  tried: FigureSource[];
};

/** A figure filed with the SEC against Yahoo's for the same session. */
export type SourceCheck = {
  metric: "nav" | "premium" | string;
  as_of: string;
  official: number;
  official_source: FigureSource;
  /** null when Yahoo has no row for that session. */
  market: number | null;
  market_source: FigureSource;
  /** null when nothing was compared — not the same as agreeing. */
  agree: boolean | null;
  tolerance: number;
};

export type ClosedEnd = {
  nav_symbol: string;
  nav: SourcedFigure;
  price: SourcedFigure;
  /** Price ÷ NAV − 1: −0.05 is a 5% discount. */
  premium: SourcedFigure;
  distribution_rate: SourcedFigure;
  expense_ratio: SourcedFigure;
  net_assets: SourcedFigure;
  total_assets: SourcedFigure;
  leverage: SourcedFigure;
  holdings_count: number | null;
  holdings_as_of: string | null;
  checks: SourceCheck[];
};

export type Comparables = {
  tickers: string[];
  labels: string[];
  rows: Record<string, string[]>;
  medals: Record<string, string>;
};

export type Peer = { ticker: string; name: string };

export type WatchlistEntry = {
  ticker: string;
  name: string;
  favorite: boolean;
  tags: string[];
  /** A coin pair. The comps table ranks on KPIs a coin has none of. */
  is_crypto: boolean;
};

export type SearchMatch = {
  ticker: string;
  name: string;
  /** watch | crypto | fund | sec | world | analyze — the tier that answered. */
  kind: string;
  /** favorite | held | "" — own-list rows only. */
  mark: string;
  /** Venue, worldwide rows only: what tells MIPS.ST apart from MIPS. */
  exchange: string;
  /** An asset kind, "fund" for one not yet narrowed, or null to draw no pill. */
  asset?: string | null;
};

/**
 * One rule on a watchlist entry. Which fields it uses depends on its type —
 * see `AlertForm`, which is the table that says so.
 */
export type AlertRule = {
  type: string;
  price?: number | null;
  pct?: number | null;
  level?: number | null;
  window?: number | null;
};

/**
 * How one alert type is entered: which number it asks for, and what to
 * prefill. Served rather than hardcoded so a new type reaches this page.
 */
export type AlertForm = {
  type: string;
  field: "price" | "pct" | "level" | null;
  default: number | null;
  window: number | null;
};

/** The fields a watchlist write may carry. Only the ones sent are applied. */
export type EntryFields = { favorite?: boolean; tags?: string[]; name?: string };
