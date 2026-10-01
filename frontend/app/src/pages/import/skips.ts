/**
 * The skipped rows, gathered by why they were left out.
 *
 * A statement skips the same thing over and over — two years of Revolut is
 * dozens of cash top-ups — and listed one card per row, the one return of
 * capital that needs a hand is the twenty-seventh card. Grouped by reason, it
 * is one line of its own above one line saying "26 cash movements".
 *
 * A reason the catalog names (`reason_key`) is a group whatever its size. One
 * it does not name is often unique to its row (`unreadable date '31/02'`), so
 * those that stand alone share one "other rows" group, each row keeping its
 * reason, rather than becoming a heading apiece — unless there is only one.
 */

import type { SkippedRow } from "./api";

/** The fields the view places itself; any other prints as "label value". */
const PLACED = new Set([
  "row",
  "type",
  "reason",
  "reason_key",
  "manual",
  "date",
  "ticker",
  "quantity",
  "amount",
  "currency",
]);

/** The group's stem for unnamed reasons that stand alone. */
export const OTHER = "import.skip_other";

export type SkipGroup = {
  /** Catalog stem; null when the parser's own `reason` is the heading. */
  stem: string | null;
  reason: string;
  /** Whether these rows leave the reader a step to take by hand. */
  manual: boolean;
  rows: SkippedRow[];
  /** The broker's own word for each kind of row, and how many, most first. */
  types: [string, number][];
  /** First and last day, when any row is dated. */
  span: [string, string] | null;
};

export const figure = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;

/** Fields a parser kept beyond the ones placed, with something in them. */
export function extras(row: SkippedRow): [string, string | number | boolean][] {
  return Object.entries(row).filter(
    (entry): entry is [string, string | number | boolean] =>
      !PLACED.has(entry[0]) &&
      entry[1] !== null &&
      entry[1] !== "" &&
      entry[1] !== 0 &&
      entry[1] !== false,
  );
}

/**
 * Whether a skip is about a row at all. "No parser recognised this file" is
 * about the file: its group's heading says everything a line under it could.
 */
export function located(row: SkippedRow): boolean {
  return Boolean(
    row.date ||
    row.ticker ||
    figure(row.amount) ||
    figure(row.quantity) ||
    extras(row).length,
  );
}

/** An unnamed reason split where the parsers split it — "what — why". */
export function splitReason(reason: string): [string, string] {
  const at = reason.indexOf(" — ");
  const head = at < 0 ? reason : reason.slice(0, at);
  return [
    head.charAt(0).toUpperCase() + head.slice(1),
    at < 0 ? "" : reason.slice(at + 3),
  ];
}

/**
 * Oldest first. A statement lists its rows by currency section, so the dollar
 * top-ups of December come after the euro ones of August otherwise. Undated
 * rows keep their place at the end.
 */
function chronological(rows: SkippedRow[]): SkippedRow[] {
  const day = (row: SkippedRow) =>
    row.date ? String(row.date).slice(0, 10) : "\uffff";
  return [...rows].sort((a, b) => day(a).localeCompare(day(b)));
}

function group(stem: string | null, reason: string, rows: SkippedRow[]): SkipGroup {
  const counts = new Map<string, number>();
  const days: string[] = [];
  for (const row of rows) {
    const type = String(row.type ?? "");
    if (type) counts.set(type, (counts.get(type) ?? 0) + 1);
    if (row.date) days.push(String(row.date).slice(0, 10));
  }
  days.sort();
  const first = days[0];
  const last = days[days.length - 1];
  return {
    stem,
    reason,
    manual: rows.some((row) => row.manual === true),
    rows: chronological(rows),
    types: [...counts].sort((a, b) => b[1] - a[1]),
    span: first && last ? [first, last] : null,
  };
}

/** By reason: a step by hand first, then the most rows, the strays last. */
export function groupSkips(rows: SkippedRow[]): SkipGroup[] {
  const byReason = new Map<string, { stem: string | null; rows: SkippedRow[] }>();
  for (const row of rows) {
    const reason = String(row.reason ?? "");
    const found = byReason.get(reason);
    if (found) found.rows.push(row);
    else byReason.set(reason, { stem: row.reason_key ?? null, rows: [row] });
  }
  const named: SkipGroup[] = [];
  const strays: SkippedRow[] = [];
  for (const [reason, found] of byReason) {
    if (!found.stem && found.rows.length === 1) strays.push(...found.rows);
    else named.push(group(found.stem, reason, found.rows));
  }
  named.sort(
    (a, b) => Number(b.manual) - Number(a.manual) || b.rows.length - a.rows.length,
  );
  const [only] = strays;
  if (only && strays.length === 1)
    named.push(group(null, String(only.reason ?? ""), strays));
  else if (strays.length) named.push(group(OTHER, "", strays));
  return named;
}
