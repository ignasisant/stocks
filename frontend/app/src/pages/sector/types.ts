/**
 * What `/api/v1/sectors` and `/api/v1/sectors/{sector}` answer with.
 *
 * Mirrors `Sectors` / `SectorCohort` in `src/stocks/schemas/`. Two
 * nullables carry meaning rather than absence and are typed so they cannot be
 * quietly coerced: `as_of: null` is "never scanned" — not "does not exist" —
 * and a `metrics` value of null is "nobody could measure it", which on a
 * cheapness ranking is the opposite of zero.
 */

export type SectorSummary = {
  sector: string;
  /** The ETF whose basket seeds the cohort. */
  etf: string;
  as_of: string | null;
  cohort: number;
  podium: string[];
  /** Best three on technical momentum — a separate ranking from `podium`. */
  tech_podium: string[];
};

export type Sectors = { sectors: SectorSummary[] };

/** Where the Review page would put the name, read as a new buy. */
type CohortJudged = {
  verdict: "buy" | "watch" | "pass" | "bet" | "unrated";
  reasons: string[];
  quality: number | null;
  cheapness: number | null;
  /** The KPIs the Review page shows, keyed as its `metrics`. */
  metrics: Record<string, number | null>;
};

export type CohortRow = {
  ticker: string;
  /** Listing currency of the money metrics; null when the scan has none. */
  currency?: string | null;
  /** Percentile rank inside this cohort, 0-1; null when unranked. */
  score: number | null;
  rank: number | null;
  metrics: Record<string, number | null>;
  /** On fundamentals rows only; an older server leaves it out. */
  judged?: CohortJudged | null;
  /** Off the market cap in dollars; null is "unknown", never "small". */
  size?: Size | null;
  /** A small or mid cap growing fast, listed beside the cohort: unscored. */
  growth?: boolean;
};

export type Size = "large" | "mid" | "small";

export type SectorCohort = {
  sector: string;
  etf: string;
  as_of: string | null;
  /** Metric the rows arrived ordered by — the page's own default. */
  sort: string;
  ascending: boolean;
  podium: string[];
  rows: CohortRow[];
  /** Every metric a row can carry, in order. The column list, not a guess. */
  metric_keys: string[];
  default_columns: string[];
  /** Metrics where the smaller number is the better one. */
  lower_is_better: string[];
  /** Best three on technical momentum. */
  tech_podium: string[];
  /** One row per cohort ticker with an OHLC history, keyed by the technical
   * metrics (trend_pct, rsi14, macd_hist, pct_from_high, roc_63, vol_ratio)
   * rather than `metric_keys`. */
  tech_rows: CohortRow[];
};

/**
 * The two fields of `/pulse/book` this page reads: the reader's weight per
 * sector (fractions of 1, keyed as `info["sector"]` spells it, the same names
 * as `SectorSummary.sector`) and why the replay could not be priced, if not.
 */
export type BookSectors = {
  sector_weights: Record<string, number>;
  /** Per sector, the funds that put the book there and the share of the book
   * each one carries (a fund's look-through). An older server leaves it out. */
  sector_funds?: Record<string, Record<string, number>>;
  unavailable: string | null;
};

/**
 * `/sectors/{sector}/funds`: the curated vehicles that buy the whole sector.
 * Mirrors `SectorFunds` in `src/stocks/schemas/sectors.py`. Weights are
 * fractions of the fund, read off the ten lines Yahoo discloses: every overlap
 * is a floor, and a podium weight of null is "not among its ten largest",
 * never zero.
 */
export type FundLine = {
  ticker: string;
  name: string;
  weight: number;
  role: "podium" | "cohort" | "other";
};

export type SectorFund = {
  ticker: string;
  kind: "etf" | "fund";
  scope: "world" | "us" | "europe";
  /** A part of the sector only ("banks"); null is all of it. */
  only?: string | null;
  name: string;
  currency: string | null;
  family: string | null;
  /** TER, a fraction a year. */
  expense_ratio: number | null;
  purity: number;
  /** The disclosed lines (up to ten), largest first, each with what it is
   * to this page: a podium name, another ranked company, or neither. */
  lines: FundLine[];
  top3: number;
  top10: number;
  cohort_weight: number;
  podium: { ticker: string; weight: number | null }[];
  fetched: string | null;
};

export type SectorFunds = { sector: string; funds: SectorFund[] };

/** `/sectors/{sector}/funds/returns`: the reader's half, in their currency.
 * Moves are percentage points (12.3 = +12.3 %). */
export type FundReturn = {
  ticker: string;
  y1: number | null;
  since: number | null;
  /** The first close, when it is later than the book's first day. */
  opens: string | null;
};

export type SectorFundReturns = {
  sector: string;
  currency: string;
  /** The book's first day; null for a guest or an empty book. */
  since: string | null;
  /** A switch between mutual funds carries no tax where the reader files. */
  transfer_free: boolean;
  returns: FundReturn[];
};
