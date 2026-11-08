/**
 * The frame every portfolio chart is drawn in: value axes, legend, hover box,
 * pointer maths and the plot margins they share.
 */

import type { CSSProperties, MouseEvent, PointerEvent, ReactNode } from "react";
import { token } from "../../../shell/theme";
import { useTabStrip } from "../../../shell/useTabStrip";
import { Tip, tipAt } from "../../../ui/chart/Tip";

/** Under this measured width a plot is a phone's: no gutters, labels inside. */
export const NARROW = 480;

/** One value-axis label. Beside the plot it sits in the gutter, vertically
    centred on its gridline; `inside`, on a narrow plot, it sits on the line
    instead — above it, in the plot's own space, haloed in the card's surface
    (`pf-halo`) so a line passing behind it stays readable. */
export function AxisLabel({
  text,
  at,
  left,
  right,
  side = "left",
  inside = false,
  top = 0,
}: {
  text: string;
  /** The gridline's y. */
  at: number;
  left: number;
  right: number;
  side?: "left" | "right";
  inside?: boolean;
  /** The plot's top edge, below which a label may not rise. */
  top?: number;
}) {
  const edge = side === "left" ? left : right;
  // A tick on the top edge would put its label over the card's padding: it
  // hangs under that line instead.
  const y = inside ? (at - 4 < top + 8 ? at + 12 : at - 4) : at + 4;
  const x = inside
    ? edge + (side === "left" ? 4 : -4)
    : edge + (side === "left" ? -6 : 6);
  return (
    <text
      x={x}
      y={y}
      fill={token("text-muted")}
      fontSize="11"
      textAnchor={(side === "left") === inside ? "start" : "end"}
      className={inside ? "pf-halo" : undefined}
    >
      {text}
    </text>
  );
}

/** The value axis: faint gridlines with their labels, right-aligned in the
    left gutter — or left-aligned in the right one, for a chart whose second
    floor reads off that side. */
export function ValueAxis({
  ticks,
  y,
  left,
  right,
  format,
  side = "left",
  inside = false,
  top,
}: {
  ticks: number[];
  y: (value: number) => number;
  left: number;
  right: number;
  format: (value: number) => string;
  side?: "left" | "right";
  inside?: boolean;
  top?: number;
}) {
  return (
    <g>
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            x1={left}
            x2={right}
            y1={y(tick)}
            y2={y(tick)}
            stroke={token("rule-soft")}
            strokeWidth="1"
          />
          <AxisLabel
            text={format(tick)}
            at={y(tick)}
            left={left}
            right={right}
            side={side}
            inside={inside}
            top={top}
          />
        </g>
      ))}
    </g>
  );
}

/** A chart's legend: one row that scrolls sideways on a phone, with a fade on
    the edge that still has entries past it, where it used to wrap into a
    block that took the plot's height. */
export function Legend({ children }: { children: ReactNode }) {
  const strip = useTabStrip("");
  return (
    <div className="pf-legend-strip ag-fade-x" ref={strip}>
      <ul className="pf-legend-inline">{children}</ul>
    </div>
  );
}

/** One row of a chart's hover box: the series' swatch, its name, its figure. */
export type TipRow = {
  label: string;
  value: string;
  color?: string;
  /** Keyed by a short stroke rather than a box: a line series' row. */
  mark?: "line" | "dashed";
};

/** A hover box as one plain sentence, for the live region a key step speaks. */
export function tipSaid(title: string, rows: TipRow[]): string {
  return `${title}: ${rows.map((row) => `${row.label} ${row.value}`).join(", ")}`;
}

/**
 * The hover box, Plotly's unified `hovermode="x"` label.
 *
 * A div over the SVG rather than SVG text: it has to stay legible at every
 * rendered width, and inside the viewBox it would scale with the chart. Placed
 * as a percentage of the frame so it tracks the pointer whatever the size, and
 * flipped to the pointer's left past the middle, then nudged back inside the
 * plot where it would still overhang it: on a phone a box 60% of the plot wide
 * anchored at its middle ran off the right edge and widened the page.
 * It replaced per-day `<title>` slices, which only answered on every n-th day
 * and — being the browser's tooltip — lagged a second behind the pointer.
 */
export function ChartTip({
  x,
  width,
  title,
  rows,
  top,
  up = false,
  wide = false,
  className,
  children,
}: {
  /** Anchor, in viewBox units. */
  x: number;
  width: number;
  title: string;
  rows: TipRow[];
  /** Pixels down the frame, for a box that follows the pointer both ways. */
  top?: number;
  /** Opens above `top` rather than below it, for a pointer low in the frame. */
  up?: boolean;
  /** Allowed the frame's whole width, for a box with more than a figure a row. */
  wide?: boolean;
  /** Anything past the rows — a donut slice's holdings. */
  children?: ReactNode;
  /** One more class on the box, for a layout of its own. */
  className?: string;
}) {
  // A box that follows only the pointer's x sits at the top of the plot, which
  // is where a finger scrubbing it is; the stylesheet lifts it out of the plot
  // on a touch screen. One placed both ways (a donut's) already dodges.
  const place = ["pf-tip", top === undefined ? "pf-tip-x" : "", className ?? ""];
  return (
    <Tip
      at={tipAt(x, width)}
      title={title}
      items={rows}
      top={top}
      up={up}
      wide={wide}
      className={place.filter(Boolean).join(" ")}
    >
      {children}
    </Tip>
  );
}

/**
 * The touch readout strip's reserved height, in lines (`pf-scrub` in
 * portfolio.css): the title shares the first line with a row, then two rows
 * a line. From the chart's row count, not the day's box, so it is set before
 * a finger lands and nothing moves when it does.
 */
export function stripLines(rows: number): CSSProperties {
  return { "--pf-strip-lines": Math.ceil((rows + 1) / 2) } as CSSProperties;
}

/** Where a pointer sits on an SVG, in its viewBox's x units. */
export function viewX(
  event: MouseEvent<Element>,
  svg: SVGSVGElement | null,
  width: number,
) {
  const box = svg?.getBoundingClientRect();
  if (!box || !box.width) return null;
  return ((event.clientX - box.left) / box.width) * width;
}

/** Where a pointer sits on an SVG, in viewBox y units (the box keeps its
    aspect, so one scale serves both axes). */
export function viewY(
  event: PointerEvent<Element>,
  svg: SVGSVGElement | null,
  width: number,
) {
  const box = svg?.getBoundingClientRect();
  if (!box || !box.width) return null;
  return ((event.clientY - box.top) / box.width) * width;
}

/** The nearest of `count` evenly spaced points to viewBox x `at`. */
export function nearest(
  at: number,
  left: number,
  plotW: number,
  count: number,
): number {
  const index = Math.round(((at - left) / plotW) * (count - 1));
  return Math.max(0, Math.min(count - 1, index));
}

/** Where a plot sits in its frame: the left gutter holds the value axis, and
    `height` is the desktop one — a narrow plot is squarer (`fitHeight`).
    The frame is the measured width, so every figure here is in pixels. */
export const PLOT = { height: 300, top: 8, right: 8, bottom: 24, left: 64 };

/** The margin of a narrow plot, whose value labels sit inside it. */
export const NARROW_PAD = 8;

/** The realized-result bars: the width a render without layout sees, and
    their desktop height. */
export const BARS = { fallback: 720, height: 240 };

/** A series' last drawn value: where its line ends. */
export const lastValue = (points: (number | null)[]) => {
  for (let i = points.length - 1; i >= 0; i--) {
    const value = points[i];
    if (value !== null && value !== undefined) return value;
  }
  return null;
};

export function withNote(text: string, note: string | null | undefined): string {
  return note ? `${text} (${note})` : text;
}

/**
 * The gap between a value line and the money behind it, one polygon per
 * contiguous run of the same sign. A run is extended by one point on each side
 * so neighbouring bands meet instead of leaving a seam at the crossover. The
 * value line is cut on the same runs and coloured by them — green above what
 * went in, red below; the overlapping point keeps the two colours joined.
 */
export function gainBands(
  points: { value: number; base: number }[],
  x: (index: number) => number,
  y: (value: number) => number,
): { gain: boolean; path: string; value: string }[] {
  const bands: { gain: boolean; path: string; value: string }[] = [];
  let start = 0;
  for (let index = 1; index <= points.length; index += 1) {
    const ending = index === points.length;
    const gain = points[start]!.value >= points[start]!.base;
    const same = !ending && points[index]!.value >= points[index]!.base === gain;
    if (same) continue;
    const run = points.slice(start, Math.min(index + 1, points.length));
    const offset = start;
    const top = run.map((point, i) => `${x(offset + i)},${y(point.value)}`);
    const bottom = run.map((point, i) => `${x(offset + i)},${y(point.base)}`).reverse();
    bands.push({
      gain,
      path: `M${top.join("L")}L${bottom.join("L")}Z`,
      value: top.join(" "),
    });
    start = ending ? start : index;
  }
  return bands;
}
