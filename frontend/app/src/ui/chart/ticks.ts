/**
 * Value-axis ticks on round numbers, shared by every chart.
 *
 * The step is the 1-2-2.5-5 ladder scaled to the span, so a €12k book reads
 * 10k/11k/12k and not 11,843/12,261 — an axis labelled 0, 37, 74 is arithmetic
 * nobody reads off a chart. At most `count` steps fit across [lo, hi], and
 * every label lands inside it. A flat span answers with the one value it has;
 * a span that is not a number, with none.
 */
export function ticks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * power).find((m) => m >= raw) ?? 10 * power;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) {
    // Snap away float drift (0.30000000000000004, -0) before it reaches a label.
    out.push(Number((Math.round(v / step) * step).toPrecision(12)) || 0);
  }
  return out;
}
