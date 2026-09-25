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
};

export type AssetStats = {
  ticker: string;
  quote: string;
  market_cap: number | null;
  volume_24h: number | null;
  circulating_supply: number | null;
  high_52w: number | null;
  low_52w: number | null;
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

export type PriceEvents = { ticker: string; earnings: EarningsEvent[] };

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
  /** …formatted by the server, so both front ends round it the same way. */
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

type MoatPillar = {
  key: string;
  label: string;
  score: number | null;
  weight: number;
  detail: string;
};

export type Moat = {
  ticker: string;
  score: number | null;
  rating: string | null;
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
