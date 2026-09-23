/**
 * What `/api/v1/sectors` and `/api/v1/sectors/{sector}` answer with.
 *
 * Mirrors `Sectors` / `SectorCohort` in `src/stocks/api/schemas.py`. Two
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
};

export type Sectors = { sectors: SectorSummary[] };

export type CohortRow = {
  ticker: string;
  /** Percentile rank inside this cohort, 0-1; null when unranked. */
  score: number | null;
  rank: number | null;
  metrics: Record<string, number | null>;
};

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
};
