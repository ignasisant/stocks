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
  start: string | null;
  end: string | null;
  injected: number | null;
  value: number | null;
  twr_cumulative: number | null;
  twr_annualised: number | null;
  /** Of the flow-adjusted path, over the whole span — not today's basket. */
  twr_volatility: number | null;
  twr_max_drawdown: number | null;
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
  /** The three cumulative lines over this window; null when nothing to draw. */
  curves: RiskCurves | null;
  /** Held names with no price series, carried at cost inside `portfolio`. */
  missing: string[];
  /** Days excluded from `portfolio` — an unpriceable flow, never a real loss. */
  dropped_days: string[];
};

/**
 * Cumulative return over the risk window, three ways, on one date axis.
 *
 * Fractions, not percents, like everything else this API sends. Every series
 * is rebased to the window's first day — three lines from three different
 * zeros compare nothing.
 */
type RiskCurves = {
  dates: string[];
  /** What the account earned: flow-adjusted, so deposits are not performance. */
  portfolio: (number | null)[];
  /** What today's holdings would have earned over the same window. */
  basket: (number | null)[];
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

/** Windows `/portfolio/risk` accepts; anything else is refused with a 422. */
export const RISK_PERIODS = ["6mo", "1y", "2y", "5y", "max"] as const;
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
