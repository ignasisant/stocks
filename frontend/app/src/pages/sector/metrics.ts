/**
 * The cohort's numbers: what unit each one is in, how it prints, how it sorts
 * and how it filters.
 *
 * All of it offline, on rows the API already sent. `/sectors/{sector}` ships
 * `metric_keys`, `default_columns` and `lower_is_better` precisely so a table
 * can be re-sorted, re-columned and re-filtered without a second call, and a
 * re-sort that costs a round trip is a re-sort that blanks the screen it was
 * meant to reorder.
 */

import type { CohortRow } from "./types";

type Unit = "money" | "x" | "pct" | "score" | "ratio";

/**
 * The unit each metric is quoted in — a mirror of `KPI_SOURCES[key].unit` in
 * `stocks/analysis/fundamentals.py`.
 *
 * It is a copy and it should not be one. The cohort carries the raw numbers
 * and the catalog carries the labels, but nothing on the wire carries the
 * unit, so a client with 0.154 in hand has nowhere to learn that it prints as
 * "15.4%" rather than "0.2x". Adding `unit` to `KpiSourceRow`
 * (`/api/v1/kpi-sources`) would retire this table; until then it is here,
 * named, rather than smeared through the formatter as special cases.
 */
const UNITS: Record<string, Unit> = {
  price: "money",
  market_cap: "money",
  ev: "money",
  pe_ttm: "x",
  pe_fwd: "x",
  peg: "x",
  pb: "x",
  ev_ebitda: "x",
  ev_sales: "x",
  roe: "pct",
  roic: "pct",
  gross_margin: "pct",
  op_margin: "pct",
  net_margin: "pct",
  fcf: "money",
  fcf_yield: "pct",
  net_debt_ebitda: "x",
  cash_conversion: "x",
  revenue_cagr: "pct",
  net_income_cagr: "pct",
  fcf_cagr: "pct",
  share_dilution: "pct",
  moat: "score",
};

/**
 * Grouped to a fixed number of decimals, always in the en-US shape.
 *
 * Not the reader's locale, deliberately: every other figure in this app is
 * printed by Python's `format_value`, which groups `1,234.56` whichever
 * language the page is in. A table where the ROIC column follows the browser
 * and the column beside it follows the server is worse than one that is
 * consistently the app's own convention.
 */
function grouped(value: number, decimals: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

const SCALES: [number, string][] = [
  [1e12, "T"],
  [1e9, "B"],
  [1e6, "M"],
];

/**
 * One metric as the Streamlit page prints it, or `na` when it is null.
 *
 * Null is the whole point of the signature: a metric nobody could measure is
 * not a zero, and printing it as one would make the least measurable company
 * in the cohort look like the cheapest.
 */
export function formatMetric(
  key: string,
  value: number | null | undefined,
  na: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return na;
  switch (UNITS[key] ?? "ratio") {
    case "pct":
      return `${(value * 100).toFixed(1)}%`;
    case "x":
      return `${value.toFixed(1)}x`;
    case "score":
      return `${value.toFixed(0)}/100`;
    case "money": {
      for (const [divisor, suffix] of SCALES) {
        if (Math.abs(value) >= divisor)
          return `${grouped(value / divisor, 2)}${suffix}`;
      }
      return grouped(value, 2);
    }
    default:
      return String(value);
  }
}

/**
 * The cohort ordered by one metric, most attractive first.
 *
 * Rows with nothing to compare sink to the bottom whichever way the rest is
 * going — the same rule the API sorts by, and the reason a client must not
 * sort on `value ?? 0`: that puts "we could not measure this" at the top of a
 * cheapness ranking.
 */
export function ordered(
  rows: readonly CohortRow[],
  sort: string,
  ascending: boolean,
): CohortRow[] {
  return [...rows].sort((left, right) => {
    const a = left.metrics[sort] ?? null;
    const b = right.metrics[sort] ?? null;
    if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
    return ascending ? a - b : b - a;
  });
}

/** One screen constraint: keep rows at least (min) or at most (max) `value`. */
export type Screen = { metric: string; kind: "min" | "max"; value: number };

/**
 * Whether a row clears every filter. A row with no number for a filtered
 * metric drops out rather than passing by default — the same as the pandas
 * screen, where a NaN comparison is False.
 */
export function passes(row: CohortRow, screens: readonly Screen[]): boolean {
  return screens.every((screen) => {
    const value = row.metrics[screen.metric] ?? null;
    if (value === null) return false;
    return screen.kind === "min" ? value >= screen.value : value <= screen.value;
  });
}

/**
 * The whole cohort as raw numbers, exactly as the download button offers it:
 * every metric, unrounded and unformatted, with an empty cell where there was
 * nothing to measure. Anything a spreadsheet should re-derive itself is not
 * pre-chewed here.
 */
export function csv(rows: readonly CohortRow[], keys: readonly string[]): string {
  const lines = [["ticker", ...keys].join(",")];
  for (const row of rows) {
    const cells = keys.map((key) => {
      const value = row.metrics[key];
      return value === null || value === undefined ? "" : String(value);
    });
    lines.push([row.ticker, ...cells].join(","));
  }
  return `${lines.join("\n")}\n`;
}
