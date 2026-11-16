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

import { useState, type PointerEvent } from "react";

import { useLang } from "../../shell/i18n";
import { indexAt } from "./logic";
import type { PulsePoint } from "./types";

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

/** The y positions the axis names. 50 is the neutral line and is drawn stronger. */
const LEVELS = [80, 50, 20];

/** "13 nov" for a point's ISO day, in the reader's language. */
function shortDay(iso: string, lang: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" }).format(
    new Date(y, m - 1, d),
  );
}

/**
 * The composite's own path, on the meter's fixed 0-100 scale, readable by hand.
 *
 * Fixed range, not autoscaled: this line sits under a 0-100 meter and a reader
 * compares the two by eye, so an autoscaled version — where a 12-point wobble
 * fills the box — would contradict the pin it is drawn beside. The 50 line is
 * the neutral middle and is the one drawn firm; 20 and 80 are the outer bands'
 * edges.
 *
 * Touching or hovering reads off the session under the pointer, in the
 * readout above the plot; at rest the readout is the latest session, so the
 * figure the page opens on is the one the headline says.
 */
export function HeroSpark({ points }: { points: PulsePoint[] }) {
  const lang = useLang();
  const [at, setAt] = useState<number | null>(null);
  if (points.length < 2) return null;
  const values = points.map((point) => point.score);
  const last = points.length - 1;
  const shown = points[at ?? last];
  const x = (index: number) => (index / last) * 100;
  const y = (level: number) => 100 - Math.max(0, Math.min(100, level));

  const move = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    setAt(indexAt(event.clientX - box.left, box.width, points.length));
  };

  return (
    <div className="sn-chart">
      <div className="sn-chart-read" aria-live="off">
        <span>{shown ? shortDay(shown.date, lang) : ""}</span>
        <b>{shown ? Math.round(shown.score) : ""}</b>
      </div>
      <div
        className="sn-chart-plot"
        onPointerMove={move}
        onPointerDown={move}
        onPointerLeave={() => setAt(null)}
        onPointerCancel={() => setAt(null)}
      >
        <svg
          className="sn-hero-spark"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {LEVELS.map((level) => (
            <line
              key={level}
              className={level === 50 ? "sn-hero-mid" : undefined}
              x1={0}
              x2={100}
              y1={y(level)}
              y2={y(level)}
            />
          ))}
          <polyline
            points={values
              .map((value, i) => `${x(i).toFixed(2)},${y(value).toFixed(2)}`)
              .join(" ")}
          />
        </svg>
        {LEVELS.map((level) => (
          <span className="sn-chart-y" key={level} style={{ top: `${y(level)}%` }}>
            {level}
          </span>
        ))}
        {at !== null && shown && (
          <>
            <span className="sn-chart-rule" style={{ left: `${x(at)}%` }} />
            <span
              className="sn-chart-dot"
              style={{ left: `${x(at)}%`, top: `${y(shown.score)}%` }}
            />
          </>
        )}
      </div>
    </div>
  );
}
