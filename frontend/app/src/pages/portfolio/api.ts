/**
 * The shapes `/api/v1/portfolio/*` actually sends, transcribed from
 * `src/stocks/api/schemas.py`.
 *
 * Every `| null` here is one the API means: a position nobody could price has
 * no value and no weight, a book with no span has no return, a spread nobody
 * could measure is not a spread of zero. They are typed as nullable so the
 * renderer cannot quietly treat them as numbers.
 */

export type Position = {
  ticker: string;
  shares: number;
  currency: string;
  /** Basis in the reporting currency. */
  cost: number;
  value: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  /** Share of the book by market value; null when the row did not price. */
  weight: number | null;
  /**
   * Today's move in the reporting currency and as a fraction. Off-hours this
   * is the pre/after-hours quote or the last completed session, never a stale
   * flat bar; null when no two prices could be compared.
   */
  day: number | null;
  day_pct: number | null;
  /** False when no live quote exists now — the day cells are dimmed. */
  market_active: boolean;
  /** Which broker accounts hold the shares, largest first. */
  custody: Custodian[];
};

/**
 * One broker holding part of a position. `name` is empty for the two generic
 * buckets (`manual`, `unknown`), which the client words from its catalog.
 */
export type Custodian = {
  broker: string;
  name: string;
  logo: string | null;
  shares: number;
  share: number;
};

export type Positions = {
  base: string;
  positions: Position[];
  unpriced: number;
};

export type Summary = {
  base: string;
  cost: number;
  value: number;
  pnl: number;
  pnl_pct: number | null;
  positions: number;
  /** Rows left out of cost and value alike, so the two stay like-for-like. */
  unpriced: number;
  /**
   * Closed sales, FIFO-matched, all-time. Null for a book that never sold —
   * no sale is not a result of zero. NOT the tax tab's figure, which replays
   * under the jurisdiction's own currency and matching rule.
   */
  realized: number | null;
  /** Basis of those sales, so the tile can carry a percentage. */
  realized_cost: number | null;
};

/**
 * The book's own move over one window, from `/movers`.
 *
 * `amount` leads and `basket` is the same statement as a fraction: a
 * percentage on its own says nothing about how much money moved. Both are null
 * when the price history does not cover the window — never 0, which would read
 * as a book that did not budge.
 */
export type Movers = {
  window: string;
  base: string;
  basket: number | null;
  amount: number | null;
};

export type Transactions = {
  total: number;
  /** These rows are the example book, not a real one. Say so wherever they show. */
  demo: boolean;
  transactions: {
    id: number | null;
    date: string;
    ticker: string;
    action: string;
    quantity: number;
    price: number;
    currency: string;
    fee: number;
    note: string;
  }[];
};

export type Performance = {
  base: string;
  /** The window every return below was re-taken over. */
  window: string;
  start: string | null;
  end: string | null;
  injected: number | null;
  value: number | null;
  twr_cumulative: number | null;
  twr_annualised: number | null;
  /** Of the flow-adjusted path, over the whole span — not today's basket. */
  twr_volatility: number | null;
  twr_max_drawdown: number | null;
  /** When the worst fall ran, and what the book was worth at its top — the
   *  TWR weighs every day alike, so a fall on a small early book needs saying. */
  twr_drawdown_peak: string | null;
  twr_drawdown_trough: string | null;
  twr_drawdown_peak_value: number | null;
  /** Days left out of every figure above, because their flow could not price. */
  dropped_days: string[];
  irr: number | null;
  /** Held names with no price series, carried at cost in `value`. */
  missing: string[];
};

type AllocationSlice = { label: string; weight: number };

export type Risk = {
  base: string;
  period: string;
  volatility: number | null;
  max_drawdown: number | null;
  effective_names: number | null;
  top5_weight: number | null;
  betas: Record<string, number>;
  weights: Record<string, number>;
  /** Keyed sector | country | currency | broker. */
  allocation: Record<string, AllocationSlice[]>;
  correlation: Record<string, Record<string, number>>;
  /** The flow-matched return lines over this window; null when nothing to draw. */
  curves: RiskCurves | null;
  /** Held names with no price series, carried at cost inside `portfolio`. */
  missing: string[];
  /** Days excluded from `portfolio` — an unpriceable flow, never a real loss. */
  dropped_days: string[];
};

/**
 * Return on the money put in over the risk window, the book against each
 * alternative, on one date axis.
 *
 * Every alternative is fed the book's own flows on their own dates — a buy
 * puts the same money in, a sale takes it out — so an index is credited with
 * the euros the book had at work, when it had them. Each line is value over
 * `invested`, minus one. Fractions, not percents.
 */
type RiskCurves = {
  dates: string[];
  /** Net money in each day (opening value + buys − sale proceeds). */
  invested: (number | null)[];
  /** What the account's own money became. */
  portfolio: (number | null)[];
  /** The same flows put into today's holdings at today's weights. */
  basket: (number | null)[];
  /** The same flows put into each benchmark. */
  benchmarks: Record<string, (number | null)[]>;
};

/** One headline figure: an i18n name, an amount, and an i18n help key. */
type TaxKpi = { name: string; value: number; help: string };

export type TaxPeriod = {
  /** ISO prefix: "2024" for a year, "2024-03" for a month. */
  period: string;
  realized_gain: number;
  realized_loss: number;
  disallowed_loss: number;
  recovered_loss: number;
  deductible_loss: number;
  net_taxable: number;
  estimated_tax: number;
  carryforward_loss: number;
  /** Matched parcels in the period — used to slice `TaxReport.sales`. */
  sales: number;
  kpis: TaxKpi[];
  /** How the jurisdiction writes the year ("2025/26"); empty for a month. */
  year_label: string;
  /** Sentences under the year's figures: catalog key + preformatted slots. */
  notes: TaxNote[];
};

type TaxNote = { key: string; kwargs: Record<string, string> };

/** A foreign-asset reporting threshold (Modelo 720, FBAR…) — a flag, not a verdict. */
export type TaxFlag = {
  name: string;
  reportable: boolean;
  total_value: number;
  threshold: number;
};

export type TaxSale = {
  ticker: string;
  buy_date: string;
  sell_date: string;
  quantity: number;
  cost: number;
  proceeds: number;
  gain: number;
  matched: string;
  /** "long" | "short" where the jurisdiction splits holding periods, else null. */
  term: string | null;
};

/**
 * Every finished tax year added together — a history, not a taxable base.
 *
 * Deliberately not a `TaxPeriod`: allowances reset and brackets restart, so
 * "net taxable over five years" is not a figure that exists. The totals ride
 * in `kpis`, each year's own, summed by key.
 */
type TaxAllYears = {
  years: number[];
  realized_gain: number;
  realized_loss: number;
  disallowed_loss: number;
  recovered_loss: number;
  deductible_loss: number;
  sales: number;
  kpis: TaxKpi[];
};

export type TaxReport = {
  jurisdiction: string;
  /** chosen | region | unmodelled | unknown. */
  resolved: string;
  /** The jurisdiction's currency, never `base`. */
  currency: string;
  matching: string;
  years: TaxPeriod[];
  /** Those years added up; null for a book with only one. */
  all_years: TaxAllYears | null;
  months: TaxPeriod[];
  sales: TaxSale[];
  funds_classified: boolean;
  /** Reporting thresholds against today's open book, in `currency`. */
  flags: TaxFlag[];
};

export type DividendYear = {
  year: number;
  gross: number;
  withheld: number;
  net: number;
  creditable: number;
  reclaimable: number;
  estimated_gross: number | null;
  unrecorded: number | null;
};

export type ForwardHolding = {
  ticker: string;
  shares: number;
  per_share: number;
  payments: number;
  currency: string;
  gross: number;
  gross_base: number | null;
  last_ex: string | null;
};

export type Dividends = {
  base: string;
  years: DividendYear[];
  booked_total: number;
  booked_ytd: number;
  estimated_total: number | null;
  estimated_ytd: number | null;
  forward_annual: number | null;
  forward: ForwardHolding[];
  /** False leaves every estimate null — the book may still pay, nobody checked. */
  estimates_available: boolean;
};

export type BrokerCost = {
  broker: string;
  trades: number;
  volume: number;
  commission: number;
  other_fees: number;
  spread: number | null;
  spread_bps: number | null;
  measured: number;
  skipped: number;
  outside_range: number;
  total: number | null;
  cost_pct: number | null;
};

export type Fees = {
  base: string;
  brokers: BrokerCost[];
  explicit: number;
  spread: number | null;
  volume: number;
  cost_pct: number | null;
  /**
   * Whether the trade-day bars came back at all. False means every spread
   * field is null because Yahoo was unreachable, NOT that the book traded at
   * the mid — so the spread reads "n/a" and never 0.
   */
  spread_measured: boolean;
};

/**
 * The windows the Allocation & risk tab offers — the Streamlit page's, in its
 * order, since inception first and the default. Both `/portfolio/risk` and
 * `/portfolio/performance` take them, so one selector drives both cards. The
 * API still accepts "max" for older clients; the page does not offer it,
 * because an IPO-to-date backtest describes the stock rather than the book.
 */
export const RISK_PERIODS = ["inception", "6mo", "1y", "2y", "5y"] as const;
export type RiskPeriod = (typeof RISK_PERIODS)[number];

/**
 * One day of the book, from `/portfolio/history`.
 *
 * Every figure is nullable and means it. `value` carries a name nobody could
 * price at its cost rather than dropping it, so the level stays comparable to
 * `injected` — `History.missing` is who that was. `twr` is rebased to the
 * requested window, which is why the window is a server parameter and not a
 * slice a client takes of a longer series.
 */
type HistoryPoint = {
  date: string;
  injected: number | null;
  value: number | null;
  pnl_pct: number | null;
  twr: number | null;
};

export type History = {
  base: string;
  window: string;
  start: string | null;
  end: string | null;
  points: HistoryPoint[];
  /** Held names with no usable price series, carried at cost inside `value`. */
  missing: string[];
  /** Days excluded from the TWR — an unrecorded split, never a real loss. */
  dropped_days: string[];
};

/**
 * `/market/status`, the part this page reads: whether the US session is open,
 * and which caveat stem (`market_closed` | `premarket` | `postmarket`) to print
 * under a day figure that is not live. The sentence stays this page's own.
 */
export type MarketStatus = {
  us_open: boolean;
  us_extended: string | null;
  note: string | null;
};

/** One month's close, from `/portfolio/monthly`. Returns are since the first trade. */
export type MonthlyPoint = {
  month: string;
  date: string;
  injected: number | null;
  value: number | null;
  pnl: number | null;
  /** Gain over the time-averaged capital: each deposit weighed by how long it was in. */
  money_weighted: number | null;
  twr: number | null;
};

export type Monthly = {
  base: string;
  months: MonthlyPoint[];
  missing: string[];
};

/** One block of the book as the projection moved it. */
type ProjectionSleeve = {
  key: "stocks" | "crypto";
  value: number;
  weight: number;
  /** Median compound annual return, as used. */
  growth: number;
  volatility: number;
  volatility_measured: boolean;
  /** Share of each monthly contribution. */
  share: number;
};

/**
 * A percentile fan for the book's value, month by month, from
 * `/portfolio/projection`. Not a forecast: every assumption it was drawn
 * under comes back with it, so the page can say what it drew.
 */
export type Projection = {
  base: string;
  years: number;
  start_value: number | null;
  sleeves: ProjectionSleeve[];
  /** Weekly stocks–crypto correlation used; null when unmeasured. */
  correlation: number | null;
  crypto_weight: number;
  monthly: number;
  /** Last 12 months' average net money put in — the hint beside `monthly`. */
  monthly_suggested: number;
  /** True when the future is in today's money. */
  real: boolean;
  inflation: number;
  target: number | null;
  /** Share of paths ending at or above `target`. */
  target_probability: number | null;
  dates: string[];
  p10: number[];
  p25: number[];
  p50: number[];
  p75: number[];
  p90: number[];
  /** Today's value plus contributions so far. */
  contributed: number[];
  /** Past month ends since the first trade, oldest first; today excluded. */
  history_dates: string[];
  history_value: (number | null)[];
  /** Net money put in by each past month end. */
  history_invested: (number | null)[];
};

/** Horizons the projection tab offers, in years. */
export const PROJECTION_YEARS = ["1", "3", "5", "10"] as const;
/**
 * Median compound growth for the stock sleeve, in percent. Three are named
 * after the index whose long-run record they approximate — nominal, total
 * return, rounded — so the reader picks a reference rather than a number.
 */
export const STOCK_PRESETS = { low: 4, mid: 6, world: 8, sp500: 10, ndx: 13 } as const;
/** Median compound growth for the crypto sleeve, in percent. */
export const CRYPTO_GROWTH = ["-20", "0", "10", "25"] as const;
/** Share of each contribution that goes to crypto: as today, or a fixed one. */
export const CRYPTO_SHARES = ["today", "0", "10", "25"] as const;
