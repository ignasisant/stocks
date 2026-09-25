/**
 * Sparklines as inline SVG, because the shape is the half the numbers cannot
 * carry: a smooth drift and a spike with a round trip land on the identical
 * three-month delta, and only the line separates them.
 *
 * No chart library. These are polylines inside the row they belong to, drawn
 * from numbers the API already sent — a charting runtime with its own resize
 * observer would cost more than the whole page for sixty of these.
 *
 * Colour comes from a class, never from an attribute: the stylesheet holds the
 * `--ag-*` tokens and the markup holds geometry.
 */

const PAD = 2;

function path(values: number[], width: number, height: number, lo: number, hi: number) {
  const span = hi - lo || 1;
  const usable = height - 2 * PAD;
  return values
    .map((value, i) => {
      const x = (i / (values.length - 1)) * (width - 2) + 1;
      const y = PAD + (1 - (value - lo) / span) * usable;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/** The trend state's own direction, so the line and the pill beside it agree. */
function lineClass(state: string | null | undefined): string {
  if (state === "up" || state === "turning_up") return "sn-spark-up";
  if (state === "down" || state === "turning_down") return "sn-spark-down";
  return "sn-spark-flat";
}

/** One row's 90 sessions. Small on purpose: it answers "what shape", not "what level". */
export function Spark({
  values,
  state,
  width = 84,
  height = 22,
}: {
  values: number[];
  state?: string | null;
  width?: number;
  height?: number;
}) {
  // A series too short to have a shape gets a rule rather than a line: an
  // empty cell reads as a missing column, and a single point drawn as a line
  // would be a flat trend nobody measured.
  if (values.length < 2) {
    return <span className="sn-spark-rule" style={{ width }} aria-hidden="true" />;
  }
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  return (
    <svg
      className={`sn-spark ${lineClass(state)}`}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline points={path(values, width, height, lo, hi)} />
    </svg>
  );
}

/**
 * The composite's own path, on the meter's fixed 0-100 scale.
 *
 * Fixed range, not autoscaled: this line sits under a 0-100 meter and a reader
 * compares the two by eye, so an autoscaled version — where a 12-point wobble
 * fills the box — would contradict the pin it is drawn beside. The dashed
 * guides at 20 and 80 mark the outer bands.
 */
export function HeroSpark({
  values,
  width = 520,
  height = 56,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return null;
  const y = (level: number) =>
    PAD + (1 - Math.max(0, Math.min(100, level)) / 100) * (height - 2 * PAD);
  return (
    <svg
      className="sn-hero-spark"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {[20, 80].map((level) => (
        <line key={level} x1={0} x2={width} y1={y(level)} y2={y(level)} />
      ))}
      <polyline points={path(values, width, height, 0, 100)} />
    </svg>
  );
}
