/**
 * The marks every chart draws the same way.
 *
 * Portfolio, ticker, Hoy and Home each picked their own stroke widths, dot
 * sizes and crosshair; the palette was shared, the marks were not. These are
 * the numbers (the colours come from `chart()` / `token()`, never a literal),
 * so a line is as heavy on one screen as on the next.
 */

export const LINE = {
  /** The line the chart is about: a price, the book, the single series. */
  primary: 2.25,
  /** One of several, or a compared series. */
  secondary: 1.5,
  /** An indicator under the main line (the SMAs). */
  overlay: 1.25,
  /** A reference rule: zero, the money put in, an event. */
  rule: 1,
  /** A sparkline a few lines tall, where 2.25 would be a bar. */
  compact: 1.75,
  /** A line lifted by hover or focus is this much heavier. */
  lift: 0.5,
} as const;

/** The dash of a baseline (money in, a benchmark): same on every chart. */
export const BASELINE_DASH = "4 3";

/** The dot on a line's last point or the point under the crosshair. */
export const DOT = {
  r: 3.5,
  /** The ring in the card's colour that keeps it one dot where lines meet. */
  ring: 1.5,
} as const;

/** Where a line's area fade starts and ends, as opacity. */
export const AREA = { top: 0.14, bottom: 0 } as const;

/** A bar's widest, the round on its data end, and the card-coloured gap
 *  between two bars side by side. */
export const BAR = { max: 24, round: 4, gap: 2 } as const;

/**
 * A bar from its baseline to its value, as a path: square where it stands on
 * the baseline, rounded at the data end, either side of zero. A bar too short
 * for the round takes what height it has.
 */
export function barPath(x: number, width: number, base: number, end: number): string {
  const r = Math.min(BAR.round, width / 2, Math.abs(base - end));
  const s = end <= base ? 1 : -1;
  return [
    `M${x},${base}`,
    `V${end + s * r}`,
    `Q${x},${end} ${x + r},${end}`,
    `H${x + width - r}`,
    `Q${x + width},${end} ${x + width},${end + s * r}`,
    `V${base}Z`,
  ].join("");
}
