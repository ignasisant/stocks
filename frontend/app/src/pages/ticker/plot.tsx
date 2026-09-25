/**
 * The drawing primitives every chart on this page shares: a frame, a scale,
 * nice axis ticks, a grid and a tooltip.
 *
 * These are SVG. The Streamlit page and the standalone `/ticker` document draw
 * the same charts in Plotly, and this shell has no Plotly in it — see
 * `Ticker.tsx` for why that is a decision and not an omission. What survives is
 * the reading rather than the interaction: every figure a Plotly hover box
 * carried is still on screen, in a tooltip this page draws itself, and the
 * price chart keeps the drag-to-zoom gesture the readout under it reports.
 *
 * Geometry lives in the markup and colour lives in `token()` — the `--ag-*`
 * custom properties the server inlines — so these agree with the Streamlit
 * charts and with both themes, and nothing here writes a colour by hand.
 */

import type { ReactNode } from "react";
import { useCallback, useRef } from "react";

/**
 * A chart's box, in viewBox units.
 *
 * The SVG is laid out at a fixed width and scaled to its container by CSS
 * (`width: 100%; height: auto`), so the rendered aspect ratio always matches
 * this one — which is what makes a pointer position convertible back into
 * these coordinates exactly.
 */
export type Frame = {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
};

export function frame(over: Partial<Frame> = {}): Frame {
  return {
    width: 760,
    height: 320,
    left: 52,
    right: 16,
    top: 12,
    bottom: 30,
    ...over,
  };
}

export const plotWidth = (f: Frame) => f.width - f.left - f.right;
export const plotHeight = (f: Frame) => f.height - f.top - f.bottom;

/** A linear scale from a data range onto a pixel range. */
export function scale(lo: number, hi: number, from: number, to: number) {
  const span = hi - lo || 1;
  return (value: number) => from + ((value - lo) / span) * (to - from);
}

/**
 * Axis ticks on round numbers, and never fewer than two.
 *
 * A 1-2-5 step, because an axis labelled 0, 37, 74 is arithmetic nobody reads
 * off a chart.
 */
export function ticks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi === lo) return [lo];
  const raw = (hi - lo) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step =
    magnitude * ([1, 2, 5, 10].find((mult) => magnitude * mult >= raw) ?? 10);
  const out: number[] = [];
  for (let at = Math.ceil(lo / step) * step; at <= hi + step / 1e6; at += step) {
    out.push(Math.abs(at) < step / 1e6 ? 0 : at);
  }
  return out;
}

/**
 * The bounds of a set of series, padded so the extremes are not on the edge.
 *
 * Nulls are skipped, never floored to zero: an indicator's warm-up must not
 * drag the axis down through the price it sits beside.
 */
export function bounds(
  series: (number | null | undefined)[][],
  options?: { pad?: number; zero?: boolean },
): { lo: number; hi: number } | null {
  const values = series
    .flat()
    .filter(
      (value): value is number =>
        value !== null && value !== undefined && Number.isFinite(value),
    );
  if (values.length === 0) return null;
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (options?.zero) {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  }
  if (lo === hi) {
    const nudge = Math.abs(lo) * 0.05 || 1;
    return { lo: lo - nudge, hi: hi + nudge };
  }
  const pad = (hi - lo) * (options?.pad ?? 0.06);
  return { lo: lo - pad, hi: hi + pad };
}

/**
 * The responsive SVG every chart draws into.
 *
 * `role="img"` with a label, because these carry figures: a screen reader that
 * is handed an unlabelled canvas is handed nothing.
 */
export function Chart({
  frame: f,
  label,
  children,
  onPointer,
  onLeave,
  onDown,
  onUp,
  onDouble,
  className,
}: {
  frame: Frame;
  label: string;
  children: ReactNode;
  /** The pointer position, already converted into viewBox units. */
  onPointer?: (x: number, y: number) => void;
  onLeave?: () => void;
  onDown?: (x: number) => void;
  onUp?: (x: number) => void;
  onDouble?: () => void;
  className?: string;
}) {
  const node = useRef<SVGSVGElement>(null);

  const at = useCallback(
    (event: { clientX: number; clientY: number }): [number, number] => {
      const box = node.current?.getBoundingClientRect();
      if (!box || box.width === 0) return [0, 0];
      const unit = box.width / f.width;
      return [(event.clientX - box.left) / unit, (event.clientY - box.top) / unit];
    },
    [f.width],
  );

  return (
    <svg
      ref={node}
      className={className ? `tk-svg ${className}` : "tk-svg"}
      viewBox={`0 0 ${f.width} ${f.height}`}
      role="img"
      aria-label={label}
      onPointerMove={
        onPointer &&
        ((event) => {
          const [x, y] = at(event);
          onPointer(x, y);
        })
      }
      onPointerLeave={onLeave}
      onPointerDown={
        onDown &&
        ((event) => {
          onDown(at(event)[0]);
        })
      }
      onPointerUp={
        onUp &&
        ((event) => {
          onUp(at(event)[0]);
        })
      }
      onDoubleClick={onDouble}
    >
      {children}
    </svg>
  );
}

/**
 * Horizontal gridlines with their labels. The only rules on these charts:
 * a vertical grid would compete with the event verticals that mean something.
 */
export function YGrid({
  frame: f,
  lo,
  hi,
  format,
  count = 4,
}: {
  frame: Frame;
  lo: number;
  hi: number;
  format: (value: number) => string;
  count?: number;
}) {
  const y = scale(lo, hi, f.height - f.bottom, f.top);
  return (
    <g className="tk-grid">
      {ticks(lo, hi, count).map((value) => (
        <g key={value}>
          <line x1={f.left} x2={f.width - f.right} y1={y(value)} y2={y(value)} />
          <text x={f.left - 8} y={y(value) + 4} textAnchor="end">
            {format(value)}
          </text>
        </g>
      ))}
    </g>
  );
}

/**
 * One line of a tooltip: what it is, what it reads, and how it reads.
 *
 * `parts`, where given, is how the line is set — a muted label, a bold value,
 * one coloured figure — and `swatch` the colour of the series it belongs to,
 * which is how Plotly's unified box ties a row to its trace. Both optional: a
 * bar chart's one-line tooltip needs neither.
 */
export type TipLine = {
  text: string;
  tone?: "up" | "down" | null;
  parts?: { text: string; bold?: boolean; tone?: "up" | "down" | "dim" }[];
  swatch?: string;
};

/**
 * The hover box.
 *
 * A div rather than SVG text: it has to wrap, it has to stay legible at every
 * container width, and inside the SVG it would be scaled with the chart.
 * Positioned as a percentage of the frame so it lands with the cursor whatever
 * the rendered size, and flipped to the left half once the cursor passes the
 * middle so it never leaves the card.
 */
export function Tooltip({
  frame: f,
  x,
  title,
  lines,
}: {
  frame: Frame;
  /** Anchor, in viewBox units. */
  x: number;
  title: string;
  lines: TipLine[];
}) {
  const left = (x / f.width) * 100;
  const flip = left > 55;
  return (
    <div
      className={flip ? "tk-tip tk-tip-flip" : "tk-tip"}
      style={{ left: `${left}%` }}
      role="status"
    >
      <span className="tk-tip-t">{title}</span>
      {lines.map((line, index) => (
        <span
          key={`${line.text}-${index}`}
          className={line.tone ? `tk-tip-l tk-is-${line.tone}` : "tk-tip-l"}
        >
          {line.swatch ? (
            <span className="tk-tip-sw" style={{ background: line.swatch }} />
          ) : null}
          {line.parts
            ? line.parts.map((part, at) => (
                <span
                  key={at}
                  className={
                    [part.bold ? "tk-tip-b" : "", part.tone ? `tk-is-${part.tone}` : ""]
                      .filter(Boolean)
                      .join(" ") || undefined
                  }
                >
                  {part.text}
                </span>
              ))
            : line.text}
        </span>
      ))}
    </div>
  );
}

/**
 * A legend: swatch, label, one row each.
 *
 * Under the chart rather than inside it. Plotly floats these over the plot and
 * they cover the series they name at narrow widths.
 */
export function Legend({
  items,
}: {
  items: { label: string; color: string; dashed?: boolean }[];
}) {
  return (
    <ul className="tk-legend">
      {items.map((item) => (
        <li key={item.label}>
          <span
            className={item.dashed ? "tk-swatch tk-swatch-dash" : "tk-swatch"}
            style={{ background: item.color }}
          />
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  );
}
