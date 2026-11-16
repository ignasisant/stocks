/**
 * The readings this page derives rather than receives — and nothing else.
 *
 * Two rules govern what is allowed in here. A derivation may only rearrange
 * figures the API already published, and it must fail exactly where the server
 * would have failed. Anything that would need a price series the endpoints do
 * not send is not a derivation, it is a second implementation of the market
 * data, and it belongs in `stocks.api.routes.pulse` instead.
 *
 * Both functions below are pure so the arithmetic can be tested without a
 * render: a quadrant read off the wrong sign and a sector called "leading"
 * because its benchmark was missing would both draw perfectly.
 */

import type { TrendBlock, TrendRow } from "./types";

/** The 10-year yield and the 2s10s slope, as FRED ids — the quadrant's two axes. */
const YIELD_ID = "DGS10";
const SLOPE_ID = "T10Y2Y";

/** How many of the reader's own sectors the leading/lagging note names. */
const TOP_SECTORS = 3;

export type Quadrant = {
  /** bear_steepening | bear_flattening | bull_steepening | bull_flattening */
  key: string;
  /** The 10-year's own quarter move, in basis points, exactly as sent. */
  yields: number;
  /** The 2s10s slope's quarter move, in basis points, exactly as sent. */
  slope: number;
};

/**
 * Which of the four rates regimes the last quarter describes.
 *
 * Mirrors `stocks.analysis.sentiment.rate_quadrant`, and can afford to: that
 * function is the sign of two 63-session differences, and the rates block
 * already carries both of them as its `quarter` change — in basis points,
 * because a percent change of a percentage rate reads like a price move and is
 * not one. So this reads two published numbers and names the pair; it does not
 * recompute anything from a series.
 *
 * It fails where the server fails, too. `changes` omits a horizon the series is
 * too short to span, which is the same condition under which `rate_quadrant`
 * answers "unknown" — and an absent horizon is the one case where a quadrant
 * would be a guess. That is the block's own rule: a level with no history is
 * no reading.
 */
export function quadrant(rates: TrendBlock | null | undefined): Quadrant | null {
  // Only the block that quotes its moves in basis points can be read this way.
  // A block whose unit changed under us would still have a `quarter` number,
  // and it would mean something else.
  if (!rates || rates.unit !== "basis_points") return null;
  const yields = rates.rows.find((row) => row.key === YIELD_ID)?.changes.quarter;
  const slope = rates.rows.find((row) => row.key === SLOPE_ID)?.changes.quarter;
  if (yields === undefined || slope === undefined) return null;
  const direction = yields > 0 ? "bear" : "bull";
  const shape = slope > 0 ? "steepening" : "flattening";
  return { key: `${direction}_${shape}`, yields, slope };
}

/**
 * The reader's largest sectors, split by whether they beat the index this month.
 *
 * The largest three are chosen from the BOOK's own sector split first, and only
 * then filtered to the ones with an excess return. The order matters: the
 * rotation block only carries sectors a SPDR fund tracks, so choosing from it
 * would skip an "Unknown" or a crypto sleeve that is one of the reader's three
 * largest and promote a smaller holding into a list that claims to be the top
 * three. A top sector with no fund, or too new to have a month, drops out of
 * the sentence instead.
 *
 * `changes.month` is the sector's excess return over the index — the server's
 * own comparison, not one made here. Without a book split (a server too old
 * to send one) the rotation rows' own weights stand in, which is the same
 * answer whenever the book holds nothing outside the eleven funded sectors.
 */
export function topSectors(
  rotation: TrendBlock | null | undefined,
  weights?: Record<string, number> | null,
): {
  leading: TrendRow[];
  lagging: TrendRow[];
} {
  const rows = rotation?.rows ?? [];
  const book: [string, number][] =
    weights && Object.keys(weights).length > 0
      ? Object.entries(weights)
      : rows.flatMap((row): [string, number][] =>
          row.weight === null ? [] : [[row.name, row.weight]],
        );
  const top = book
    .filter(([, weight]) => weight > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, TOP_SECTORS)
    .flatMap(([name]) => rows.filter((row) => row.name === name));
  return {
    leading: top.filter((row) => (row.changes.month ?? 0) > 0),
    lagging: top.filter(
      (row) => row.changes.month !== undefined && row.changes.month <= 0,
    ),
  };
}

/**
 * The composite's five bands, in scale order, with their lower edges.
 *
 * Mirrors `stocks.analysis.sentiment.REGIME_BANDS` (a band spans from its edge
 * to the next one). The API sends the band a score is in but not where the
 * bands start, and the meter has to draw all five, so the edges live here too.
 */
export const BANDS: readonly { key: string; from: number }[] = [
  { key: "stress", from: 0 },
  { key: "caution", from: 20 },
  { key: "neutral", from: 40 },
  { key: "appetite", from: 60 },
  { key: "euphoria", from: 80 },
];

/** A band's share of the 0-100 scale, in points. */
export function bandSpan(index: number): number {
  const next = BANDS[index + 1];
  const here = BANDS[index];
  return (next ? next.from : 100) - (here ? here.from : 0);
}

/**
 * Buckets a book can hold that no sector fund tracks. They are not sectors, and
 * a tilt row for them reads as "you are 2% overweight in crypto against the
 * S&P", which is a comparison with something the index does not hold.
 */
const NO_SECTOR = new Set(["Unknown", "Crypto", "Funds"]);

/**
 * The sector tilt split for drawing: the real sectors, largest overweight
 * first, and the share of the book that sits outside any sector.
 *
 * `unsectored` is the sum of those buckets' tilt. The benchmark holds none of
 * them, so their tilt is their weight and the figure reads as "this much of
 * your book is not compared". Null when there is none, so the caption is not
 * drawn for a book made only of sectors.
 */
export function splitTilt(tilt: Record<string, number>): {
  rows: [string, number][];
  unsectored: number | null;
} {
  const rows: [string, number][] = [];
  let unsectored = 0;
  for (const [name, value] of Object.entries(tilt)) {
    if (NO_SECTOR.has(name)) unsectored += value;
    else rows.push([name, value]);
  }
  rows.sort((a, b) => b[1] - a[1]);
  return { rows, unsectored: unsectored > 0 ? unsectored : null };
}

/**
 * Which side of the 50 line a component sits on, and how far, as percentages of
 * the track: appetite grows right from the middle, tension grows left.
 */
export function fromMiddle(score: number): {
  side: "appetite" | "tension";
  width: number;
} {
  const clamped = Math.max(0, Math.min(100, score));
  return clamped >= 50
    ? { side: "appetite", width: clamped - 50 }
    : { side: "tension", width: 50 - clamped };
}

/** The point of a chart under a pointer: its index in the series, clamped. */
export function indexAt(x: number, width: number, count: number): number {
  if (count <= 1 || width <= 0) return 0;
  return Math.max(0, Math.min(count - 1, Math.round((x / width) * (count - 1))));
}
