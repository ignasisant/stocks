/**
 * The verdicts as the page sorts, counts and picks them, and how far a hold
 * sits from the move it nearly is.
 *
 * The score lines mirror `stocks.analysis.review` (`GOOD`, `CHEAP`, `POOR`,
 * `SELL_BELOW`, `ADD_MARGIN`): the map draws the first two, and a name the
 * server marked `close_call` is measured against the others. Kept here, in
 * one place, so a change on the server is one edit on this side.
 */

import type { ReviewRow, Verdict } from "./types";

/** Quality from here up is a good business. */
export const GOOD = 60;
/** Price score from here up is a good price. */
export const CHEAP = 50;
/** Both scores under this hold a sale once proposed… */
const POOR = 40;
/** …and both under this start one. */
const SELL_BELOW = 35;
/** An add or a buy starts this far past `GOOD` and `CHEAP`. */
const ADD_MARGIN = 5;

/** Reading order: what to do first, then what stays, then what is outside. */
const VERDICT_ORDER: Verdict[] = [
  "sell",
  "trim",
  "add",
  "hold",
  "core",
  "cash",
  "buy",
  "watch",
  "bet",
  "pass",
  "unrated",
];

const KNOWN = new Set<string>(VERDICT_ORDER);

/** `?v=` as a list of verdicts in reading order, unknown words dropped. */
export function parseVerdicts(raw: string | null): Verdict[] {
  const asked = new Set((raw ?? "").split(",").map((part) => part.trim()));
  return VERDICT_ORDER.filter((verdict) => asked.has(verdict) && KNOWN.has(verdict));
}

/** A verdict list back into `?v=`; empty is no parameter at all. */
export function verdictParam(picked: Verdict[]): string | undefined {
  return picked.length ? picked.join(",") : undefined;
}

/** Each verdict present with how many rows carry it, in reading order. */
export function verdictCounts(
  rows: ReviewRow[],
): { verdict: Verdict; count: number }[] {
  const counts = new Map<Verdict, number>();
  for (const row of rows) counts.set(row.verdict, (counts.get(row.verdict) ?? 0) + 1);
  return VERDICT_ORDER.flatMap((verdict) => {
    const count = counts.get(verdict) ?? 0;
    return count ? [{ verdict, count }] : [];
  });
}

/** The rows with a picked verdict; every row when nothing is picked. */
export function pickVerdicts(rows: ReviewRow[], picked: Verdict[]): ReviewRow[] {
  if (picked.length === 0) return rows;
  const on = new Set(picked);
  return rows.filter((row) => on.has(row.verdict));
}

/** The rows grouped by verdict in reading order, each group in the server's order. */
export function groupByVerdict(
  rows: ReviewRow[],
): { verdict: Verdict; rows: ReviewRow[] }[] {
  return VERDICT_ORDER.flatMap((verdict) => {
    const group = rows.filter((row) => row.verdict === verdict);
    return group.length ? [{ verdict, rows: group }] : [];
  });
}

/**
 * Whether any row has a move to show: a target, money to move or a tax.
 * Without one, the target, move and tax columns are a column of dashes each.
 */
export function hasMoves(rows: ReviewRow[]): boolean {
  return rows.some(
    (row) =>
      row.target_weight !== null ||
      (row.delta !== null && row.delta !== 0) ||
      (row.tax !== null && row.tax !== 0),
  );
}

/** Which move a close call is near. */
type CloseSide = "sell" | "add" | "buy";

export type CloseCall = {
  row: ReviewRow;
  /** Null when the scores do not say which line it is near. */
  side: CloseSide | null;
  /** Whole points of score still to cross, at least 1; null without a side. */
  points: number | null;
  /** The score that has furthest to go, and the line it has to cross. */
  axis: "quality" | "cheapness" | null;
  line: number | null;
};

/**
 * How far a hold (or a watch) the server marked `close_call` sits from the
 * move it nearly is, read off the same lines the server drew it with:
 *
 * - held, both scores under `POOR`: a sale starts once both drop under
 *   `SELL_BELOW`, so the distance is the higher score's to that line;
 * - held, a clean name over `GOOD` and `CHEAP`: an add starts `ADD_MARGIN`
 *   past both, so it is the larger shortfall; outside the book the same
 *   shortfall is the distance to a buy.
 *
 * Anything else (a server whose rules moved on, a name with no scores) keeps
 * its tag with no distance, rather than one guessed.
 */
export function closeCall(row: ReviewRow): CloseCall | null {
  if (!row.reasons.includes("close_call")) return null;
  const none: CloseCall = { row, side: null, points: null, axis: null, line: null };
  const q = row.quality;
  const c = row.cheapness;
  if (q === null || c === null) return none;
  if (row.held && q < POOR && c < POOR) {
    const axis = q >= c ? "quality" : "cheapness";
    return {
      row,
      side: "sell",
      // Both have to go under the line, so the higher one decides: from 36
      // that is two points (to 34), from 35 one.
      points: Math.floor(Math.max(q, c) - SELL_BELOW) + 1,
      axis,
      line: SELL_BELOW,
    };
  }
  // Outside the book every close call is near a buy, the only move there.
  if (!row.held || (q >= GOOD && c >= CHEAP)) {
    const short = { quality: GOOD + ADD_MARGIN - q, cheapness: CHEAP + ADD_MARGIN - c };
    const axis = short.quality >= short.cheapness ? "quality" : "cheapness";
    const points = Math.ceil(short[axis]);
    // Over both lines and still held back: by something other than the
    // scores (a warning, the weight), which a distance would misstate.
    if (points <= 0) return none;
    return {
      row,
      side: row.held ? "add" : "buy",
      points,
      axis,
      line: axis === "quality" ? GOOD + ADD_MARGIN : CHEAP + ADD_MARGIN,
    };
  }
  return none;
}

/** Every close call in `rows`, the nearest first; the ones with no distance last. */
export function closeCalls(rows: ReviewRow[]): CloseCall[] {
  return rows
    .map(closeCall)
    .filter((call): call is CloseCall => call !== null)
    .sort((a, b) => (a.points ?? Infinity) - (b.points ?? Infinity));
}
