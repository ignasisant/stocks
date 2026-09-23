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
 * Both halves come from the rotation block: `weight` is this account's own
 * allocation to the sector and `changes.month` is that sector's excess return
 * over the index, which is the server's own comparison and not one made here.
 *
 * The largest three are chosen first and filtered second, deliberately: a
 * sector too new to have a month of history drops out of the sentence rather
 * than promoting a smaller holding into a list that claims to be the top three.
 */
export function topSectors(rotation: TrendBlock | null | undefined): {
  leading: TrendRow[];
  lagging: TrendRow[];
} {
  const held = (rotation?.rows ?? []).filter(
    (row) => row.weight !== null && row.weight > 0,
  );
  const top = [...held]
    .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0))
    .slice(0, TOP_SECTORS);
  return {
    leading: top.filter((row) => (row.changes.month ?? 0) > 0),
    lagging: top.filter(
      (row) => row.changes.month !== undefined && row.changes.month <= 0,
    ),
  };
}
