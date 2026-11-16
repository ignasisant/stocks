/**
 * The counts the page says aloud, kept out of the components so they can be
 * tested: the preview's bar, what a confirm changes, and what a commit did.
 *
 * Nothing here asks the server. `newPositions` is a comparison against the
 * tickers the book holds now (`/portfolio/positions?priced=false`, read from
 * the ledger alone), so it is only as exact as the two spellings agreeing: a
 * statement that names a share by its ISIN while the book holds it by symbol
 * reads as new here until the importer's own healing has run.
 */

import type { Issue, Move, Row } from "./api";

type BarTone = "ok" | "warn" | "bad" | "skip";

export type Segment = {
  id: string;
  tone: BarTone;
  label: string;
  n: number;
  share: number;
};

/** The preview's tiers as one bar. Warned rows are a subset of the importable
 *  ones, so they are carved out of it rather than counted twice. */
export function barSegments(
  counts: {
    importable: number;
    warned: number;
    rejected: number;
    duplicates: number;
    skipped: number;
  },
  labels: Record<
    "importable" | "warned" | "rejected" | "duplicates" | "skipped",
    string
  >,
): Segment[] {
  const clean = Math.max(0, counts.importable - counts.warned);
  const parts: Omit<Segment, "share">[] = [
    { id: "im-importable", tone: "ok", label: labels.importable, n: clean },
    { id: "im-warned", tone: "warn", label: labels.warned, n: counts.warned },
    { id: "im-rejected", tone: "bad", label: labels.rejected, n: counts.rejected },
    {
      id: "im-duplicates",
      tone: "skip",
      label: labels.duplicates,
      n: counts.duplicates,
    },
    { id: "im-skipped", tone: "skip", label: labels.skipped, n: counts.skipped },
  ];
  const shown = parts.filter((part) => part.n > 0);
  const total = shown.reduce((sum, part) => sum + part.n, 0);
  return shown.map((part) => ({ ...part, share: total > 0 ? part.n / total : 0 }));
}

const upper = (ticker: string) => ticker.trim().toUpperCase();

/** Tickers bought in `rows` that the book does not hold now, each once. */
export function newPositions(rows: Row[], held: ReadonlySet<string>): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    if (row.action !== "buy") continue;
    const ticker = upper(row.ticker);
    if (ticker && !held.has(ticker)) seen.add(ticker);
  }
  return [...seen];
}

/** The book's open tickers, folded the way `newPositions` compares them. */
export const heldSet = (tickers: string[]): Set<string> => new Set(tickers.map(upper));

export type Kinds = { buys: number; sells: number; dividends: number; other: number };

const refusedKey = (row: Row) =>
  `${row.date}|${upper(row.ticker)}|${row.action}|${row.quantity}`;

/** What a commit booked, by kind: the rows sent minus those it refused. */
export function kindsOf(sent: Row[], refused: Row[]): Kinds {
  const out = new Map<string, number>();
  for (const row of refused)
    out.set(refusedKey(row), (out.get(refusedKey(row)) ?? 0) + 1);
  const kinds: Kinds = { buys: 0, sells: 0, dividends: 0, other: 0 };
  for (const row of sent) {
    const key = refusedKey(row);
    const left = out.get(key) ?? 0;
    if (left > 0) {
      out.set(key, left - 1);
      continue;
    }
    if (row.action === "buy") kinds.buys += 1;
    else if (row.action === "sell") kinds.sells += 1;
    else if (row.action === "dividend") kinds.dividends += 1;
    else kinds.other += 1;
  }
  return kinds;
}

/** The columns a row's issues of one severity point at, for the table to mark. */
export function culprits(issues: Issue[], severity: "error" | "warning"): Set<string> {
  return new Set(
    issues
      .filter((issue) => issue.severity === severity && issue.field)
      .map((i) => i.field),
  );
}

/**
 * The proposals that change the book most first. A move is worth the gain that
 * was never made (`phantom_gain`), whatever its sign; one the server could not
 * put a figure on goes last. The sort is stable, so equals keep the scan's order.
 * Amounts are in each move's own currency: the order is by size of the figure.
 */
export function byImpact(moves: Move[]): Move[] {
  const size = (move: Move) =>
    move.phantom_gain === null ? -1 : Math.abs(move.phantom_gain);
  return [...moves].sort((a, b) => size(b) - size(a));
}
