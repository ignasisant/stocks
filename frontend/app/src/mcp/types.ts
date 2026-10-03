/**
 * What the connector's viewed tools put in `structuredContent` — the parts of
 * `connector/tools.py`'s payloads this view draws, and no more. Every figure
 * may be null, and null is not zero: it is a price the feed did not have.
 */

export type Position = {
  ticker: string;
  value: number | null;
  cost: number;
  pnl_pct: number | null;
  weight: number | null;
  /** Absolute, on the TopStocks origin, or null for initials. */
  logo?: string | null;
};

export type Overview = {
  kind: "overview";
  summary: {
    base: string;
    value: number;
    cost: number;
    pnl: number;
    pnl_pct: number | null;
    positions: number;
    unpriced: number;
    realized: number | null;
  };
  positions: Position[];
  positions_total: number;
  unpriced: number;
  stale_since?: string;
};

export type Point = {
  date: string;
  injected: number | null;
  value: number | null;
};

export type Performance = {
  kind: "performance";
  performance: {
    base: string;
    window: string;
    start: string | null;
    end: string | null;
    injected: number | null;
    value: number | null;
    twr_cumulative: number | null;
    twr_annualised: number | null;
    twr_max_drawdown: number | null;
    irr: number | null;
  };
  history: {
    start: string | null;
    end: string | null;
    points: Point[];
    missing: string[];
  };
  stale_since?: string;
};

/** The view's strings and the number formats, for the reader's language. */
export type Words = {
  t(key: string, slots?: Record<string, string | number>): string;
  locale: string;
  /** Back to TopStocks, through the host. */
  open(path: string): void;
};
