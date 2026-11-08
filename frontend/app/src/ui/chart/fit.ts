/**
 * The height a chart draws at, in pixels now that a unit is one.
 *
 * Drawn in a fixed viewBox, a chart shrank with its card — a phone's plot came
 * out at half its desktop height, a strip. At 1:1 the desktop height would be
 * all of a 360px screen, so a narrow plot takes a squarer shape instead: four
 * fifths of its width, no shorter than `min` and never past `max`.
 */
export function fitHeight(width: number, max: number, min = 240): number {
  return Math.round(Math.min(max, Math.max(min, width * 0.8)));
}
