/**
 * What the venue picker sends and how it ranks what comes back.
 *
 * A code the search could not place imports unpriced. The reader names the
 * security, the server finds its lines on the code's currency's venues and
 * prices each on the days the code was traded, and only a line that closed
 * near those fills can be picked. The fills are the preview's own rows: the
 * statement never leaves this page again for it.
 */

import type { Row, VenueFill, VenueOption } from "./api";

/** Mirrors `max_length` of `VenueAsk.fills`. */
const MAX_FILLS = 500;

export type Traded = { currency: string; fills: VenueFill[] };

/**
 * The code's priced buys and sells, newest first, in the currency of its
 * latest one — the server samples its days from these. Null when there is no
 * priced trade to check a line against.
 */
export function tradedAs(rows: Row[], code: string): Traded | null {
  const own = rows
    .filter(
      (row) =>
        row.ticker === code &&
        (row.action === "buy" || row.action === "sell") &&
        row.price > 0,
    )
    .sort((a, b) => b.date.localeCompare(a.date));
  const latest = own[0];
  if (!latest) return null;
  return {
    currency: latest.currency,
    fills: own
      .filter((row) => row.currency === latest.currency)
      .slice(0, MAX_FILLS)
      .map((row) => ({ date: row.date.slice(0, 10), price: row.price })),
  };
}

export type Verdict = "agrees" | "differs" | "unknown";

export const verdict = (option: VenueOption): Verdict =>
  option.agrees === true ? "agrees" : option.agrees === false ? "differs" : "unknown";

const RANK: Record<Verdict, number> = { agrees: 0, unknown: 1, differs: 2 };

/** The lines that closed near the fills first, otherwise in the server's order
 *  (Yahoo's, with the German floors last). */
export const ranked = (options: VenueOption[]): VenueOption[] =>
  options
    .map((option, at) => ({ option, at }))
    .sort((a, b) => RANK[verdict(a.option)] - RANK[verdict(b.option)] || a.at - b.at)
    .map(({ option }) => option);
