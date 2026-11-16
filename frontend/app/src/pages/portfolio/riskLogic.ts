import type { Risk } from "./api";

export type IndexRow = {
  bench: string;
  /** What the same money would have made in the index, in the reporting currency. */
  gain: number;
  /** The index's return on that money, as a fraction. */
  pct: number;
  /** The book's gain minus the index's: positive when the book is ahead. */
  versus: number;
};

/**
 * Each index on the book's own money, read at the last day both lines exist.
 *
 * The curves are already same-money (the index bought with the book's deposits
 * on the same days), so the gain is the invested total times the index's return
 * and the gap to the book is on identical euros.
 */
export function indexRows(curves: NonNullable<Risk["curves"]>): IndexRow[] {
  let day = -1;
  for (let i = curves.dates.length - 1; i >= 0 && day < 0; i--)
    if (curves.invested[i] != null && curves.portfolio[i] != null) day = i;
  if (day < 0) return [];
  const invested = curves.invested[day]!;
  const mine = curves.portfolio[day]!;
  return Object.entries(curves.benchmarks)
    .flatMap(([bench, points]) => {
      const pct = points[day];
      return pct == null
        ? []
        : [{ bench, gain: invested * pct, pct, versus: invested * (mine - pct) }];
    })
    .sort((a, b) => b.pct - a.pct);
}

/** The `n` heaviest names and the correlations among them only. */
export function largest(data: Risk, n: number): Risk {
  const keep = Object.entries(data.weights)
    .sort(([, a], [, b]) => b - a)
    .slice(0, n)
    .map(([name]) => name);
  const set = new Set(keep);
  const pick = <T>(record: Record<string, T>) =>
    Object.fromEntries(Object.entries(record).filter(([name]) => set.has(name)));
  return {
    ...data,
    weights: pick(data.weights),
    names: pick(data.names),
    correlation: Object.fromEntries(
      Object.entries(data.correlation)
        .filter(([name]) => set.has(name))
        .map(([name, row]) => [name, pick(row)]),
    ),
  };
}
