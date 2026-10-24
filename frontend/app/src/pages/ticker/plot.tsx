/**
 * The drawing primitives every chart on this page shares: a frame, a scale,
 * nice axis ticks, a grid and a tooltip.
 *
 * These are SVG — see `Ticker.tsx` for why there is no charting library. What
 * a chart keeps is the reading rather than the interaction: every figure is on
 * screen, in a tooltip this page draws itself, and the price chart keeps the
 * drag-to-zoom gesture the readout under it reports.
 *
 * Geometry lives in the markup and colour lives in `token()` — the `--ag-*`
 * custom properties the server inlines — so these follow both themes, and
 * nothing here writes a colour by hand.
 */

import type { ReactNode } from "react";
import { useCallback, useRef, useState } from "react";
import { type Span, useSpan } from "../../shell/useSpan";
import { Tip, tipAt } from "../../ui/chart/Tip";
import { Spoken, useScrub } from "../../ui/chart/useScrub";

/**
 * A chart's box, in viewBox units.
 *
 * A chart passes the width its container actually has (`shell/useWidth`), so
 * one unit is one pixel: an 11px label prints at 11px on a phone as on a
 * desktop. The 760 default is only what a render without layout sees. CSS
 * still sizes the SVG (`width: 100%; height: auto`), so the rendered aspect
 * ratio always matches this one — which is what makes a pointer position
 * convertible back into these coordinates exactly.
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

/**
 * How tall a chart is drawn at a measured width: `max` wherever there is room,
 * and no shorter than `min` on a phone. Drawn at the real width a chart is no
 * longer shrunk by the scale, but a desktop height on a 360px screen would be
 * all of it — so a narrow chart keeps a squarer shape instead.
 */
export function fitHeight(width: number, max: number, min = 240): number {
  return Math.round(Math.min(max, Math.max(min, width * 0.8)));
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

export type { Span } from "../../shell/useSpan";

/**
 * The responsive SVG every chart draws into.
 *
 * `role="img"` with a label, because these carry figures: a screen reader that
 * is handed an unlabelled canvas is handed nothing. The label is a summary —
 * what, over when, and where it went — not just the chart's name.
 *
 * With `walk`, the plot takes focus and the arrow keys move the readout
 * (`shell/useKeyWalk`); `readout` is that reading as one sentence, spoken only
 * when a key moved it.
 *
 * A mouse drag (the price chart's zoom) captures the pointer, so a drag that
 * leaves the plot keeps reporting until the button lifts instead of dying at
 * the edge; positions past it arrive outside the frame and a chart clamps.
 *
 * `onSpan` is the measuring gesture (`shell/useSpan`): two fingers, or a
 * secondary click and the pointer. A chart that passes none keeps the
 * browser's context menu.
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
  onSpan,
  walk,
  readout = null,
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
  /** Two places being compared, or null once the comparison is put away. */
  onSpan?: (span: Span | null) => void;
  /** The readout's index, the last one, and how to move it. */
  walk?: { at: number | null; last: number; set: (index: number | null) => void };
  readout?: string | null;
  className?: string;
}) {
  const node = useRef<SVGSVGElement>(null);
  // A finger's last reading, left up after the lift until a touch elsewhere.
  const [held, setHeld] = useState(false);
  const drop = useCallback(() => {
    setHeld(false);
    onLeave?.();
  }, [onLeave]);
  const span = useSpan(onSpan);
  const keys = useScrub({
    plot: node,
    held,
    drop,
    ...(walk ?? { at: null, last: -1, set: () => {} }),
  });

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
    <>
      <svg
        ref={node}
        className={className ? `tk-svg ${className}` : "tk-svg"}
        viewBox={`0 0 ${f.width} ${f.height}`}
        role="img"
        aria-label={label}
        {...(walk ? keys.props : {})}
        onPointerMove={(event) => {
          keys.quiet();
          const [x, y] = at(event);
          if (span.move(event, x)) return;
          onPointer?.(x, y);
        }}
        // A finger lifting is a leave too; the bar it read stays up until the
        // reader touches elsewhere, since only then is the hand off the chart.
        onPointerLeave={(event) => {
          span.leave(event);
          if (event.pointerType === "touch") {
            if (onPointer || onSpan) setHeld(true);
            return;
          }
          onLeave?.();
        }}
        onPointerCancel={span.cancel}
        onPointerDown={(event) => {
          keys.quiet();
          const [x, y] = at(event);
          if (span.down(event, x)) return;
          // A tap is a pointer that never moves: it reads the bar too.
          if (event.pointerType === "touch") onPointer?.(x, y);
          // The secondary button is the measuring click, never a drag.
          else if (event.button !== 0) return;
          // A drag keeps the pointer past the plot's edge. A finger is held by
          // the browser already, and must stay free to scroll the page.
          else if (onDown) event.currentTarget.setPointerCapture?.(event.pointerId);
          onDown?.(x);
        }}
        onPointerUp={(event) => {
          if (span.up(event)) return;
          if (event.pointerType !== "touch" && event.button !== 0) return;
          onUp?.(at(event)[0]);
        }}
        onContextMenu={span.menu && ((event) => span.menu?.(event, at(event)[0]))}
        onDoubleClick={onDouble}
      >
        {children}
      </svg>
      {walk ? <Spoken text={keys.keyed ? readout : null} /> : null}
    </>
  );
}

/**
 * A chart's name for a screen reader: what it is and the stretch it covers,
 * then whatever headline the chart has (its change, its extremes). Dashes and
 * arrows rather than words, so it reads the same in every language.
 */
export function summary(
  title: string,
  from: string,
  to: string,
  headline = "",
): string {
  const span =
    from && to && from !== to ? `, ${from} – ${to}` : from ? `, ${from}` : "";
  return `${title}${span}${headline ? `: ${headline}` : ""}`;
}

/** A tooltip as one sentence, for the readout `Chart` speaks. */
export function spoken(title: string, lines: TipLine[]): string {
  return [title, ...lines.map((line) => line.text)].filter(Boolean).join(", ");
}

/**
 * Decimals for a price axis: enough that two ticks never print the same
 * figure. Read from the tick step, not the top of the range — a narrow window
 * over 100 steps by 0.5, and whole numbers there print "101 101".
 */
export function tickDigits(lo: number, hi: number, count = 4): number {
  const [a, b] = ticks(lo, hi, count);
  const step = a !== undefined && b !== undefined ? Math.abs(b - a) : 1;
  const fine = step < 1 ? Math.ceil(-Math.log10(step) - 1e-9) : 0;
  return Math.max(hi >= 100 ? 0 : 2, fine);
}

/**
 * Where to set the labels that name lines at their right ends, so no two
 * overlap: each as near its line's last value as `gap` allows, inside
 * `top..bottom`. Input order is kept in the output.
 */
function spreadLabels(
  ys: number[],
  gap: number,
  top: number,
  bottom: number,
): number[] {
  const order = ys.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y);
  const out = order.map((one) => one.y);
  for (let i = 0; i < out.length; i++) {
    out[i] = Math.max(out[i]!, top, i > 0 ? out[i - 1]! + gap : -Infinity);
  }
  for (let i = out.length - 1; i >= 0; i--) {
    out[i] = Math.min(
      out[i]!,
      bottom,
      i < out.length - 1 ? out[i + 1]! - gap : Infinity,
    );
  }
  const placed: number[] = new Array(ys.length);
  order.forEach((one, at) => (placed[one.index] = out[at]!));
  return placed;
}

/**
 * Names on the lines themselves, at their right ends — so telling the lines
 * apart never rests on matching a colour to a legend swatch. Haloed in the
 * card colour, since they sit over the plot.
 */
export function EndLabels({
  frame: f,
  edge,
  items,
}: {
  /** The chart's frame: labels sit at its right edge, inside its plot. */
  frame?: Frame;
  /** Or the edge and vertical room by hand, for a chart with no `Frame`. */
  edge?: { right: number; top: number; bottom: number };
  /** Each line's last drawn y (viewBox units), its name, its colour, and an x of its own. */
  items: { y: number; text: string; color: string; x?: number }[];
}) {
  if (items.length === 0) return null;
  const room =
    edge ??
    (f
      ? {
          right: f.width - f.right - 2,
          top: f.top + 9,
          bottom: f.height - f.bottom - 3,
        }
      : null);
  if (!room) return null;
  const ys = spreadLabels(
    items.map((item) => item.y - 5),
    12,
    room.top,
    room.bottom,
  );
  return (
    <g className="ag-end" aria-hidden="true">
      {items.map((item, index) => (
        <text
          key={item.text}
          x={item.x ?? room.right}
          y={ys[index]}
          textAnchor="end"
          fill={item.color}
        >
          {item.text}
        </text>
      ))}
    </g>
  );
}

/**
 * One of the reader's own fills: a disc in the trade's hue with a triangle
 * cut out of it pointing the trade's way, up bought and down sold, ringed in
 * the page colour. The ring is what keeps a red sell legible on a falling red
 * line, and the direction tells buy from sell to a reader who cannot tell the
 * hues apart. The one under the pointer grows and wears a halo, so a reading
 * in the tooltip points back at the mark it describes.
 */
export function FillMark({
  x,
  y,
  buy,
  color,
  ring,
  active = false,
}: {
  x: number;
  y: number;
  buy: boolean;
  color: string;
  /** The page colour: the disc's outline and the triangle cut out of it. */
  ring: string;
  active?: boolean;
}) {
  const r = active ? 9.5 : 8;
  const g = r * 0.48;
  const tip = buy ? -g : g;
  const base = buy ? g * 0.62 : -g * 0.62;
  const glyph = `M ${x} ${y + tip} L ${x + g} ${y + base} L ${x - g} ${y + base} Z`;
  return (
    <g aria-hidden="true">
      {active ? <circle cx={x} cy={y} r={r + 5} fill={color} opacity={0.22} /> : null}
      <circle cx={x} cy={y} r={r} fill={color} stroke={ring} strokeWidth={2} />
      <path
        d={glyph}
        fill={ring}
        stroke={ring}
        strokeWidth={1}
        strokeLinejoin="round"
      />
    </g>
  );
}

type GridProps = {
  frame: Frame;
  lo: number;
  hi: number;
  format: (value: number) => string;
  count?: number;
  /**
   * Set each label just above its gridline, inside the plot, instead of in a
   * gutter to its left. On a phone the gutter is a seventh of the width; the
   * labels sit over the series instead, haloed in the card colour so both
   * stay legible — drawn by `YLabels`, last, since in SVG whatever is drawn
   * later covers what came before.
   */
  inside?: boolean;
};

/**
 * Horizontal gridlines with their labels. The only rules on these charts:
 * a vertical grid would compete with the event verticals that mean something.
 * With `inside`, only the lines: the chart closes with `YLabels`.
 */
export function YGrid({
  frame: f,
  lo,
  hi,
  format,
  count = 4,
  inside = false,
}: GridProps) {
  const y = scale(lo, hi, f.height - f.bottom, f.top);
  return (
    <g className="tk-grid">
      {ticks(lo, hi, count).map((value) => (
        <g key={value}>
          <line x1={f.left} x2={f.width - f.right} y1={y(value)} y2={y(value)} />
          {inside ? null : (
            <text x={f.left - 8} y={y(value) + 4} textAnchor="end">
              {format(value)}
            </text>
          )}
        </g>
      ))}
    </g>
  );
}

/** The labels of an `inside` grid, over the series. Nothing in a gutter. */
export function YLabels({
  frame: f,
  lo,
  hi,
  format,
  count = 4,
  inside = false,
}: GridProps) {
  if (!inside) return null;
  const y = scale(lo, hi, f.height - f.bottom, f.top);
  return (
    <g className="tk-grid tk-grid-in" aria-hidden="true">
      {ticks(lo, hi, count).map((value) => (
        <text key={value} x={f.left + 2} y={y(value) - 4} textAnchor="start">
          {format(value)}
        </text>
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
 * middle so it never leaves the card. Where nothing hovers it is not a box at
 * all but a readout strip over the plot (`ticker.css`).
 *
 * Not a live region: it is rewritten on every pointer move. What a screen
 * reader hears is `Chart`'s `readout`, spoken only when a key moved it.
 */
export function Tooltip({
  frame: f,
  x,
  title,
  lines,
  more = false,
}: {
  frame: Frame;
  /** Anchor, in viewBox units. */
  x: number;
  title: string;
  lines: TipLine[];
  /**
   * The bar carries more than its prices — a fill, an event. On a phone the
   * reading is a one-line strip; this lets it grow down over the plot rather
   * than cut the rows the reader pointed at it for.
   */
  more?: boolean;
}) {
  return (
    <Tip
      at={tipAt(x, f.width)}
      title={title}
      items={lines.map(({ swatch, ...line }) => ({ ...line, color: swatch }))}
      className={more ? "tk-tip tk-tip-more" : "tk-tip"}
    />
  );
}

/**
 * A legend: swatch, label, one row each.
 *
 * Under the chart rather than inside it. Plotly floats these over the plot and
 * they cover the series they name at narrow widths. One row that scrolls
 * sideways rather than a wrapped block: on a phone a second line of legend is
 * a second line of chart the reader has to get past.
 *
 * With `onToggle`, an item that carries a `key` is a button that hides or
 * shows the series it names (`hidden` holds the keys switched off); without
 * it the legend is a plain list. `onFocus` hears which keyed entry the
 * pointer or the keyboard is on (null once it leaves), so the chart can draw
 * that series up.
 */
export function Legend({
  items,
  onToggle,
  onFocus,
  hidden,
}: {
  items: {
    label: string;
    color: string;
    dashed?: boolean;
    /** A marker series' swatch: its triangle, pointing the way it is drawn, or its diamond. */
    mark?: "up" | "down" | "diamond";
    key?: string;
  }[];
  onToggle?: (key: string) => void;
  onFocus?: (key: string | null) => void;
  hidden?: ReadonlySet<string>;
}) {
  // Nothing to press means nothing a keyboard can reach to scroll it: wrap.
  return (
    <ul className={onToggle ? "tk-legend" : "tk-legend tk-legend-wrap"}>
      {items.map((item) => {
        const swatch = (
          <span
            className={
              item.dashed
                ? "tk-swatch tk-swatch-dash"
                : item.mark
                  ? `tk-swatch tk-swatch-mark tk-swatch-${item.mark}`
                  : "tk-swatch"
            }
            style={{ background: item.color }}
          />
        );
        const key = item.key;
        if (!onToggle || key === undefined) {
          return (
            <li key={item.label}>
              {swatch}
              <span>{item.label}</span>
            </li>
          );
        }
        const off = hidden?.has(key) ?? false;
        return (
          <li key={item.label}>
            <button
              type="button"
              className={off ? "tk-legend-btn tk-legend-off" : "tk-legend-btn"}
              aria-pressed={!off}
              onClick={() => onToggle(key)}
              onPointerEnter={() => onFocus?.(key)}
              onPointerLeave={() => onFocus?.(null)}
              onFocus={() => onFocus?.(key)}
              onBlur={() => onFocus?.(null)}
            >
              {swatch}
              <span>{item.label}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
