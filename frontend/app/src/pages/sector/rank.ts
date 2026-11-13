/**
 * The page's arithmetic on rows already in hand: where a figure stands inside
 * its cohort, where the reader's own names rank, which of the top three leads
 * each metric, and how old a scan is.
 *
 * Pure and offline, so it is tested without a screen (`rank.test.ts`).
 */

import type { CohortRow } from "./types";

/**
 * Each row's standing on one metric inside the cohort, 0 (worst) to 1 (best),
 * by ticker. Ties share the mean of their places; a row with no number has no
 * standing rather than the worst one, and fewer than two numbers rank nobody.
 */
export function percentiles(
  rows: readonly CohortRow[],
  key: string,
  lowerIsBetter: boolean,
): Map<string, number> {
  const known = rows
    .map((row) => ({ ticker: row.ticker, value: row.metrics[key] ?? null }))
    .filter(
      (entry): entry is { ticker: string; value: number } =>
        entry.value !== null && Number.isFinite(entry.value),
    )
    .sort((a, b) => (lowerIsBetter ? b.value - a.value : a.value - b.value));
  const out = new Map<string, number>();
  if (known.length < 2) return out;
  const last = known.length - 1;
  let start = 0;
  while (start < known.length) {
    let end = start;
    while (end + 1 < known.length && known[end + 1]!.value === known[start]!.value)
      end++;
    const place = (start + end) / 2 / last;
    for (let i = start; i <= end; i++) out.set(known[i]!.ticker, place);
    start = end + 1;
  }
  return out;
}

/** How strong the tint at either end of the cohort is, in percent of the ink. */
const TINT_MAX = 22;
/** The middle of the cohort is not a signal: left untinted. */
const TINT_FLOOR = 4;

/**
 * A cell's background for its standing: the better end in `--ag-up`, the
 * worse in `--ag-down`, stronger towards the extremes, nothing in the middle
 * or for a figure with no standing.
 */
export function tint(standing: number | undefined): string | undefined {
  if (standing === undefined) return undefined;
  const strength = Math.round(Math.abs(standing - 0.5) * 2 * TINT_MAX);
  if (strength < TINT_FLOOR) return undefined;
  const ink = standing >= 0.5 ? "--ag-up" : "--ag-down";
  return `color-mix(in srgb, var(${ink}) ${strength}%, transparent)`;
}

export type HeldPlace = {
  ticker: string;
  /** 1-based, by score; null when the row is unranked. */
  place: number | null;
  /** How many rows carry a score. */
  of: number;
  /** The best names ranked above it, best first, at most `AHEAD_SHOWN`. */
  ahead: string[];
  weight: number | null;
};

const AHEAD_SHOWN = 3;

/**
 * The reader's names that are in this cohort, best placed first, each with
 * the names that outrank it.
 */
export function heldPlaces(
  rows: readonly CohortRow[],
  held: ReadonlyMap<string, number | null>,
): HeldPlace[] {
  const ranked = rows
    .filter((row) => typeof row.score === "number")
    .sort((a, b) => (b.score as number) - (a.score as number));
  const out: HeldPlace[] = [];
  for (const row of rows) {
    const symbol = row.ticker.toUpperCase();
    if (!held.has(symbol)) continue;
    const index = ranked.findIndex((one) => one.ticker === row.ticker);
    out.push({
      ticker: row.ticker,
      place: index < 0 ? null : index + 1,
      of: ranked.length,
      ahead:
        index < 0
          ? []
          : ranked.slice(0, Math.min(index, AHEAD_SHOWN)).map((one) => one.ticker),
      weight: held.get(symbol) ?? null,
    });
  }
  return out.sort((a, b) => (a.place ?? Infinity) - (b.place ?? Infinity));
}

/**
 * Which of `tickers` leads each metric: the best figure among them, ties all
 * leading, nobody when fewer than two have a number to compare.
 */
export function leaders(
  rows: readonly CohortRow[],
  tickers: readonly string[],
  keys: readonly string[],
  lowerIsBetter: readonly string[],
): Map<string, Set<string>> {
  const picked = tickers
    .map((ticker) => rows.find((row) => row.ticker === ticker.toUpperCase()))
    .filter((row): row is CohortRow => row !== undefined);
  const out = new Map<string, Set<string>>();
  for (const key of keys) {
    const known = picked.filter((row) => Number.isFinite(row.metrics[key] ?? NaN));
    if (known.length < 2) continue;
    const values = known.map((row) => row.metrics[key] as number);
    const best = lowerIsBetter.includes(key)
      ? Math.min(...values)
      : Math.max(...values);
    out.set(
      key,
      new Set(
        known.filter((row) => row.metrics[key] === best).map((row) => row.ticker),
      ),
    );
  }
  return out;
}

/** Older than this, a scan is flagged and the rescan offered up front. */
export const STALE_DAYS = 7;

/**
 * Whole days between a scan's date and `now`, by calendar day in UTC; null
 * for a sector never scanned. `as_of` may be a date or a datetime: its day is
 * what counts.
 */
export function ageDays(asOf: string | null, now: Date): number | null {
  if (!asOf) return null;
  const day = Date.parse(`${asOf.slice(0, 10)}T00:00:00Z`);
  if (!Number.isFinite(day)) return null;
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.max(0, Math.round((today - day) / 86_400_000));
}

/** The reader's weight in a sector, matched without regard to case. */
export function sectorWeight(
  weights: Readonly<Record<string, number>> | null | undefined,
  sector: string,
): number | null {
  if (!weights) return null;
  const wanted = sector.toLowerCase();
  for (const [name, weight] of Object.entries(weights)) {
    if (name.toLowerCase() === wanted && Number.isFinite(weight)) return weight;
  }
  return null;
}
