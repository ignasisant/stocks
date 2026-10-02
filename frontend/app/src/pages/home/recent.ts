/**
 * The recent-transactions strip's rows: the ledger's newest, with the
 * dividends the shares were owed and no statement booked slotted in by date.
 *
 * A statement exported in July leaves the book's August dividends out of the
 * ledger, yet who held what the day before each ex-date is already known —
 * so those payments are listed too, marked as the estimates they are. They
 * are never folded into a ledger row: a guess beside a receipt reads as two
 * facts, a guess added into one is neither.
 *
 * Several of them share one row. A quarter of dividends across a dozen names
 * would otherwise push every trade off a five-row strip, and the trades are
 * what the strip is for; the row opens onto the payments it sums.
 */

import type { Transaction, UnbookedDividend } from "./types";

export type RecentRow =
  | { kind: "ledger"; date: string; tx: Transaction }
  | { kind: "estimated"; date: string; dividend: UnbookedDividend }
  /** Two or more estimates, newest first; `date` is the newest, `since` the oldest. */
  | { kind: "owed"; date: string; since: string; dividends: UnbookedDividend[] };

const newestFirst = (a: { date: string }, b: { date: string }) =>
  a.date < b.date ? 1 : a.date > b.date ? -1 : 0;

/**
 * Newest first, `count` at most; on one day the ledger's row goes first.
 *
 * The estimates that join are the ones inside the span the strip shows — on or
 * after the oldest ledger row left beside them — so a year-old gap in some
 * other broker's import does not ride along as "recent". One slot is theirs:
 * one estimate reads as its own row, two or more as one `owed` row.
 */
export function recentRows(
  ledger: Transaction[],
  estimated: UnbookedDividend[],
  count: number,
): RecentRow[] {
  const kept = ledger.slice(0, Math.max(0, count - 1));
  const cutoff = kept.at(-1)?.date ?? "";
  const recent = estimated
    .filter((dividend) => dividend.ex_date >= cutoff)
    .sort((a, b) => newestFirst({ date: a.ex_date }, { date: b.ex_date }));
  const rows: RecentRow[] = (recent.length ? kept : ledger).map((tx) => ({
    kind: "ledger" as const,
    date: tx.date,
    tx,
  }));
  const newest = recent[0];
  const oldest = recent.at(-1);
  if (newest && oldest) {
    rows.push(
      recent.length === 1
        ? { kind: "estimated", date: newest.ex_date, dividend: newest }
        : {
            kind: "owed",
            date: newest.ex_date,
            since: oldest.ex_date,
            dividends: recent,
          },
    );
  }
  // Stable, so the ledger keeps its own (date, id) order and wins every tie.
  return rows.sort(newestFirst).slice(0, count);
}

/**
 * The group's total in `base`, or null when any payment in it has no rate:
 * a sum short one name would read as the whole of it.
 */
export function owedTotal(dividends: UnbookedDividend[]): number | null {
  let total = 0;
  for (const dividend of dividends) {
    if (dividend.amount == null) return null;
    total += dividend.amount;
  }
  return total;
}
