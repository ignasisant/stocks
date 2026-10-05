/**
 * The page's three pictures, drawn as SVG and CSS from design tokens.
 *
 * This bundle has no charting library and is not getting one, so what a chart
 * keeps is mostly the reading: an allocation donut with its percentages on the
 * legend, a correlation grid on a diverging ramp with its −1…+1 scale under it,
 * the realized-result bars with the net as a diamond over them, and value axes
 * on all three. Two interactions: drag-to-zoom with a refitted axis on the
 * book's history, and a pointer anywhere across the plot reads the nearest day
 * (or bar) off one overlay, with a crosshair and a styled box (`ChartTip`).
 *
 * Colours come from `token()` — the `--ag-*` custom properties the server
 * inlines — so these follow both themes.
 */

import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { token } from "../../shell/theme";
import { TickerCell } from "../../shell/tickers";
import { useTabStrip } from "../../shell/useTabStrip";
import { useSpan } from "../../shell/useSpan";
import { useTouchHold } from "../../shell/useTouchHold";
import { useWidth } from "../../shell/useWidth";
import type { TaxPeriod } from "./api";

/**
 * The DS categorical ramp, in `ds.py`'s order (`CATEGORICAL_COLORS`) minus its
 * one unpublished hue: chart magenta is not in `tokens()`.
 */
const categorical = (): string[] => [
  token("brand-accent"),
  token("info"),
  token("purple-300"),
  token("warn"),
  token("warn-orange"),
  token("info-deep"),
  token("purple-400"),
];

/**
 * Three to five round values spanning [low, high] — the value axis's labels.
 *
 * The step is the 1-2-5 ladder scaled to the span, so a €12k book reads
 * 10k/11k/12k and not 11,843/12,261, and every label lands inside the plot.
 */
export function niceTicks(low: number, high: number, count = 4): number[] {
  const span = high - low;
  if (!(span > 0) || !Number.isFinite(span)) return [low];
  // The smallest ladder step that keeps the labels at or under count + 1.
  const raw = span / (count + 1);
  const power = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * power).find((m) => m >= raw) ?? 10 * power;
  const out: number[] = [];
  for (let v = Math.ceil(low / step) * step; v <= high + step * 1e-9; v += step) {
    // Snap away float drift (0.30000000000000004) before it reaches a label.
    out.push(Number((Math.round(v / step) * step).toPrecision(12)));
  }
  return out;
}

/** Under this measured width a plot is a phone's: no gutters, labels inside. */
const NARROW = 480;

/**
 * The height a chart draws at, in pixels now that a unit is one.
 *
 * Drawn in a fixed viewBox, a chart shrank with its card — a phone's plot came
 * out at half its desktop height, a strip. At 1:1 the desktop height would be
 * all of a 360px screen, so a narrow plot takes a squarer shape instead: four
 * fifths of its width, no shorter than `min` and never past `max`.
 */
export function plotHeightFor(width: number, max: number, min = 240): number {
  return Math.round(Math.min(max, Math.max(min, width * 0.8)));
}

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
function ValueAxis({
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
function Legend({ children }: { children: ReactNode }) {
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
function ChartTip({
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
  const left = (x / width) * 100;
  const box = useRef<HTMLDivElement>(null);
  // Measured on every render, after the pointer moved it: set on the element
  // rather than through state, so the measurement is never of its own nudge.
  // On `left` rather than a transform, which would still leave the untouched
  // box counted in the page's width.
  useLayoutEffect(() => {
    const tip = box.current;
    const plot = tip?.parentElement;
    if (!tip || !plot) return;
    tip.style.left = `${left}%`;
    const at = tip.getBoundingClientRect();
    const frame = plot.getBoundingClientRect();
    const over = at.right - frame.right;
    const under = frame.left - at.left;
    const nudge = over > 0 ? -over : under > 0 ? under : 0;
    if (nudge) tip.style.left = `calc(${left}% + ${nudge}px)`;
  });
  const classes = ["pf-tip"];
  // A box that follows only the pointer's x sits at the top of the plot, which
  // is where a finger scrubbing it is; the stylesheet lifts it out of the plot
  // on a touch screen. One placed both ways (a donut's) already dodges.
  if (top === undefined) classes.push("pf-tip-x");
  if (left > 55) classes.push("pf-tip-flip");
  if (up) classes.push("pf-tip-up");
  if (wide) classes.push("pf-tip-wide");
  if (className) classes.push(className);
  return (
    <div
      ref={box}
      className={classes.join(" ")}
      style={{ left: `${left}%`, ...(top === undefined ? {} : { top }) }}
      role="status"
    >
      <span className="pf-tip-title">{title}</span>
      {rows.map((row) => (
        <span className="pf-tip-row" key={row.label}>
          {row.color ? (
            <span
              className={
                row.mark === "dashed"
                  ? "pf-tip-swatch pf-swatch-dashed"
                  : row.mark === "line"
                    ? "pf-tip-swatch pf-swatch-line"
                    : "pf-tip-swatch"
              }
              style={{ background: row.color }}
            />
          ) : null}
          <span className="pf-muted">{row.label}</span>
          <strong>{row.value}</strong>
        </span>
      ))}
      {children}
    </div>
  );
}

/** Where a pointer sits on an SVG, in its viewBox's x units. */
function viewX(event: MouseEvent<Element>, svg: SVGSVGElement | null, width: number) {
  const box = svg?.getBoundingClientRect();
  if (!box || !box.width) return null;
  return ((event.clientX - box.left) / box.width) * width;
}

/** Where a pointer sits on an SVG, in viewBox y units (the box keeps its
    aspect, so one scale serves both axes). */
function viewY(event: PointerEvent<Element>, svg: SVGSVGElement | null, width: number) {
  const box = svg?.getBoundingClientRect();
  if (!box || !box.width) return null;
  return ((event.clientY - box.top) / box.width) * width;
}

/** The nearest of `count` evenly spaced points to viewBox x `at`. */
function nearest(at: number, left: number, plotW: number, count: number): number {
  const index = Math.round(((at - left) / plotW) * (count - 1));
  return Math.max(0, Math.min(count - 1, index));
}

/** The part of one holding inside a slice, in the reporting currency. */
type SliceHolding = { ticker: string; value: number; cost: number };

export type Slice = {
  label: string;
  weight: number;
  /** Market value of the slice's priced holdings; absent where none priced. */
  value?: number | null;
  /** Cost basis of the same rows as `value`, so the P/L is like-for-like. */
  cost?: number | null;
  /** What the slice is made of, largest value first. */
  holdings?: SliceHolding[];
};

/** What a donut needs to read its slices as money, not only as shares. */
export type SliceDetail = {
  money: (value: number, signed?: boolean) => string;
  /** A signed fraction — a P/L as a percentage. */
  change: (fraction: number) => string;
  labels: {
    value: string;
    invested: string;
    result: string;
    positions: string;
    /** "+3 more" under a hover box's cut list. */
    more: (count: number) => string;
    /** The hint that a click keeps the breakdown open. */
    pin: string;
    close: string;
  };
};

/** Holdings a hover box lists before it says how many more there are. */
const TIP_HOLDINGS = 4;

/**
 * The tail past the palette's hues as the one "Others" slice. Money only from
 * the parts that carried any, and holdings merged by ticker — a fund spread
 * over two tail sectors is still one holding.
 */
export function foldSlices(tail: Slice[], label: string): Slice {
  const priced = tail.filter((slice) => slice.value != null);
  const merged = new Map<string, SliceHolding>();
  for (const slice of tail) {
    for (const one of slice.holdings ?? []) {
      const seen = merged.get(one.ticker);
      merged.set(
        one.ticker,
        seen
          ? {
              ticker: one.ticker,
              value: seen.value + one.value,
              cost: seen.cost + one.cost,
            }
          : { ...one },
      );
    }
  }
  return {
    label,
    weight: tail.reduce((sum, slice) => sum + slice.weight, 0),
    value: priced.length
      ? priced.reduce((sum, slice) => sum + (slice.value ?? 0), 0)
      : null,
    cost: priced.length
      ? priced.reduce((sum, slice) => sum + (slice.cost ?? 0), 0)
      : null,
    holdings: [...merged.values()].sort((a, b) => b.value - a.value),
  };
}

/**
 * A slice's hover box: what it is worth, what went into it and the
 * difference, and how many holdings make it up. Pure, like `bookTip`, so the
 * wording is testable without a pointer. Empty for a slice nothing priced.
 */
export function sliceTip(slice: Slice, detail: SliceDetail): TipRow[] {
  if (slice.value == null) return [];
  const { money, change, labels } = detail;
  const rows: TipRow[] = [{ label: labels.value, value: money(slice.value) }];
  if (slice.cost != null) {
    const pnl = slice.value - slice.cost;
    rows.push(
      { label: labels.invested, value: money(slice.cost), color: token("text-muted") },
      {
        label: labels.result,
        value: `${money(pnl, true)}${slice.cost > 0 ? ` (${change(pnl / slice.cost)})` : ""}`,
        color: pnl >= 0 ? token("up") : token("down"),
      },
    );
  }
  if (slice.holdings?.length) {
    rows.push({ label: labels.positions, value: String(slice.holdings.length) });
  }
  return rows;
}

/** One holding's figures in a slice: its part's value and that part's P/L. */
function HoldingFigures({ one, detail }: { one: SliceHolding; detail: SliceDetail }) {
  const pnl = one.value - one.cost;
  return (
    <>
      <span className="pf-donut-figure">{detail.money(one.value)}</span>
      <span className={`pf-donut-figure ${pnl >= 0 ? "pf-up" : "pf-down"}`}>
        {one.cost > 0 ? detail.change(pnl / one.cost) : "—"}
      </span>
    </>
  );
}

/**
 * Allocation as a donut, percentages on the legend rather than the slices.
 *
 * Sliver slices under ~1% printed their labels on top of each other, which is
 * why the original moved them out too. More buckets than the palette has hues
 * folds the tail into one muted "Others" slice, never a cycled colour.
 *
 * The hole names one slice — the largest until the pointer picks another —
 * so the ring carries a label without crowding its slivers. With `detail`, a
 * slice under the pointer opens a box with its money: value, what went in,
 * the P/L between them and the holdings it is made of. A click (a tap, on a
 * phone, where there is no hover) keeps that breakdown open under the legend
 * with every holding as a link, which a box that follows the pointer cannot
 * offer. The legend rows answer the same way, and to the keyboard.
 */
export function Donut({
  title,
  slices,
  otherLabel,
  format,
  detail,
}: {
  title: string;
  slices: Slice[];
  otherLabel: string;
  format: (fraction: number) => string;
  detail?: SliceDetail;
}) {
  const plot = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [pointer, setPointer] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const colors = categorical();
  const total = slices.reduce((sum, slice) => sum + slice.weight, 0);
  if (!(total > 0)) return null;

  const sorted = [...slices].sort((a, b) => b.weight - a.weight);
  const shown =
    sorted.length > colors.length
      ? [
          ...sorted.slice(0, colors.length - 1),
          foldSlices(sorted.slice(colors.length - 1), otherLabel),
        ]
      : sorted;
  const palette =
    sorted.length > colors.length
      ? [...colors.slice(0, colors.length - 1), token("text-faint")]
      : colors;

  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  const find = (label: string | null) => shown.find((slice) => slice.label === label);
  const active = find(hover) ?? find(pinned);
  const focus = active ?? shown[0];
  const open = detail ? find(pinned) : undefined;
  const toggle = (label: string) => setPinned((now) => (now === label ? null : label));
  const track = (event: PointerEvent<HTMLDivElement>) => {
    // A finger has no hover: a tap pins the breakdown instead, and a box
    // that only lives while the finger is down would flash and vanish.
    if (event.pointerType === "touch") return;
    const box = plot.current?.getBoundingClientRect();
    if (!box) return;
    // Off the ring — in the hole or past its edge — nothing is under the
    // pointer, whichever slice it last crossed. In viewBox units: the stroke
    // spans 32.5…47.5 around the centre, a little more for the lifted one.
    const reach =
      (Math.hypot(
        event.clientX - box.left - box.width / 2,
        event.clientY - box.top - box.height / 2,
      ) /
        (box.width / 2)) *
      50;
    if (reach < 31 || reach > 49.5) setHover(null);
    setPointer({
      x: event.clientX - box.left,
      y: event.clientY - box.top,
      w: box.width,
      h: box.height,
    });
  };
  const tipped = hover !== null ? find(hover) : undefined;
  const tipRows = tipped && detail ? sliceTip(tipped, detail) : [];
  const tipHoldings = tipped?.holdings ?? [];

  return (
    <div className="pf-donut">
      <h3>{title}</h3>
      <div
        ref={plot}
        className="pf-donut-plot"
        onPointerMove={track}
        onPointerLeave={() => {
          setHover(null);
          setPointer(null);
        }}
      >
        <svg viewBox="0 0 100 100" role="img" aria-label={title}>
          {shown.map((slice, index) => {
            const fraction = slice.weight / total;
            const length = fraction * circumference;
            // A 1px surface gap so adjacent fills never touch, dropped when the
            // slice is too thin to spare it.
            const drawn = length > 2 ? length - 1 : length;
            const start = offset;
            offset += length;
            const on = active?.label === slice.label;
            return (
              <circle
                key={slice.label}
                className="pf-slice"
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                stroke={palette[index % palette.length] ?? token("text-faint")}
                strokeWidth={on ? 18 : 15}
                strokeOpacity={active && !on ? 0.35 : 1}
                strokeDasharray={`${drawn} ${circumference - drawn}`}
                strokeDashoffset={-start}
                transform="rotate(-90 50 50)"
                onPointerEnter={() => setHover(slice.label)}
                onClick={() => toggle(slice.label)}
              />
            );
          })}
        </svg>
        {focus ? (
          <div className="pf-donut-center" aria-hidden="true">
            <span className="pf-donut-center-label">{focus.label}</span>
            <strong>{format(focus.weight / total)}</strong>
            {detail && focus.value != null ? (
              <span className="pf-donut-center-money">{detail.money(focus.value)}</span>
            ) : null}
          </div>
        ) : null}
        {tipped && pointer ? (
          <ChartTip
            x={pointer.x}
            width={pointer.w}
            top={pointer.y > pointer.h * 0.55 ? pointer.y - 12 : pointer.y + 16}
            up={pointer.y > pointer.h * 0.55}
            wide={Boolean(detail)}
            title={`${tipped.label} · ${format(tipped.weight / total)}`}
            rows={tipRows}
          >
            {detail && tipHoldings.length ? (
              <span className="pf-tip-holdings">
                {tipHoldings.slice(0, TIP_HOLDINGS).map((one) => (
                  <span className="pf-tip-holding" key={one.ticker}>
                    <TickerCell
                      ticker={one.ticker}
                      name={false}
                      className="pf-ticker pf-tip-tick"
                    />
                    <HoldingFigures one={one} detail={detail} />
                  </span>
                ))}
                {tipHoldings.length > TIP_HOLDINGS ? (
                  <span className="pf-muted">
                    {detail.labels.more(tipHoldings.length - TIP_HOLDINGS)}
                  </span>
                ) : null}
                {pinned !== tipped.label ? (
                  <span className="pf-tip-hint">{detail.labels.pin}</span>
                ) : null}
              </span>
            ) : null}
          </ChartTip>
        ) : null}
      </div>
      <ul className="pf-legend">
        {shown.map((slice, index) => (
          <li key={slice.label}>
            <button
              type="button"
              className={
                active?.label === slice.label
                  ? "pf-legend-row pf-legend-btn pf-legend-on"
                  : "pf-legend-row pf-legend-btn"
              }
              aria-pressed={detail ? pinned === slice.label : undefined}
              onPointerEnter={() => setHover(slice.label)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(slice.label)}
              onBlur={() => setHover(null)}
              onClick={() => toggle(slice.label)}
            >
              <span
                className="pf-swatch"
                style={{ background: palette[index % palette.length] }}
              />
              <span>
                {slice.label} · {format(slice.weight / total)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {open && detail ? (
        <div className="pf-donut-detail">
          <div className="pf-donut-detail-head">
            <strong>{open.label}</strong>
            <button
              type="button"
              className="pf-donut-detail-close"
              aria-label={detail.labels.close}
              onClick={() => setPinned(null)}
            >
              ×
            </button>
          </div>
          <div className="pf-donut-detail-figures">
            {sliceTip(open, detail).map((row) => (
              <span className="pf-tip-row" key={row.label}>
                {row.color ? (
                  <span className="pf-tip-swatch" style={{ background: row.color }} />
                ) : null}
                <span className="pf-muted">{row.label}</span>
                <strong>{row.value}</strong>
              </span>
            ))}
          </div>
          {open.holdings?.length ? (
            <ul className="pf-donut-holdings">
              {open.holdings.map((one) => (
                <li key={one.ticker}>
                  <TickerCell ticker={one.ticker} name={false} className="pf-ticker" />
                  <HoldingFigures one={one} detail={detail} />
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The diverging ramp `ds.py` gives the correlation heatmap: strongly inverse
 * through uncorrelated to moving together. Blended with `color-mix` rather
 * than parsed, because some tokens are `rgba()` and some are hex.
 */
function correlationColor(value: number): string {
  const stops = [
    token("info-deep"),
    token("info"),
    token("border"),
    token("critical-fill"),
    token("down"),
  ];
  const clamped = Math.max(-1, Math.min(1, value));
  const position = ((clamped + 1) / 2) * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(position));
  const fraction = position - index;
  const low = stops[index] ?? token("border");
  const high = stops[index + 1] ?? token("border");
  return `color-mix(in srgb, ${high} ${(fraction * 100).toFixed(1)}%, ${low})`;
}

/** How strongly a pair moves together, in five words a reader can act on. */
export type CorrelationBand = "very_high" | "high" | "moderate" | "low" | "negative";

export function correlationBand(value: number): CorrelationBand {
  if (value >= 0.7) return "very_high";
  if (value >= 0.4) return "high";
  if (value >= 0.2) return "moderate";
  if (value > -0.2) return "low";
  return "negative";
}

type Pair = { name: string; value: number };

export type CorrelationStats = {
  /** Mean pairwise correlation, each pair weighted by both its weights. */
  average: number | null;
  /** The pair that moves most alike. */
  closest: { a: string; b: string; value: number } | null;
  /** The name least like the rest of the book. */
  diversifier: Pair | null;
  /** Per name: its weighted mean correlation with the others, and the other
      it is most and least like. */
  perName: Record<
    string,
    { average: number | null; peer: Pair | null; hedge: Pair | null }
  >;
};

/**
 * What the grid says, summed up: how alike the book is on average, which pair
 * is most alike, and which name diversifies the rest best. Weighted by the
 * book's weights — a pair of 0.5 % positions moving together is not the
 * book's risk — falling back to equal weights where none are known.
 */
export function correlationStats(
  matrix: Record<string, Record<string, number>>,
  weights: Record<string, number> = {},
): CorrelationStats {
  const names = Object.keys(matrix);
  const known = names.some((name) => (weights[name] ?? 0) > 0);
  const weight = (name: string) => (known ? (weights[name] ?? 0) : 1);
  let sum = 0;
  let mass = 0;
  let closest: CorrelationStats["closest"] = null;
  const perName: CorrelationStats["perName"] = {};
  for (const a of names) {
    let own = 0;
    let ownMass = 0;
    let peer: Pair | null = null;
    let hedge: Pair | null = null;
    for (const b of names) {
      const value = matrix[a]?.[b];
      if (a === b || value === undefined) continue;
      own += weight(b) * value;
      ownMass += weight(b);
      sum += weight(a) * weight(b) * value;
      mass += weight(a) * weight(b);
      if (!peer || value > peer.value) peer = { name: b, value };
      if (!hedge || value < hedge.value) hedge = { name: b, value };
      if (a < b && (!closest || value > closest.value)) closest = { a, b, value };
    }
    perName[a] = { average: ownMass ? own / ownMass : null, peer, hedge };
  }
  let diversifier: Pair | null = null;
  for (const name of names) {
    const average = perName[name]?.average;
    if (average == null || (known && !weight(name))) continue;
    if (!diversifier || average < diversifier.value)
      diversifier = { name, value: average };
  }
  return { average: mass ? sum / mass : null, closest, diversifier, perName };
}

type HeatFocus = { row: string; column: string; rect: DOMRect };

/**
 * Pairwise return correlation as a grid of squares.
 *
 * A pair the API had no overlap for is absent from the matrix rather than 0 —
 * an uncorrelated pair and an unmeasurable one are not the same reading — so
 * those cells are left blank instead of painted at the neutral stop.
 *
 * Hovering a cell (tapping, on a phone) lights its row and column and opens
 * `explain`'s reading of that pair beside it. The box is portalled to the
 * body: the grid scrolls sideways inside its card, which would clip it, and
 * the main column is a size container, which would anchor a fixed box to it.
 */
export function Heatmap({
  matrix,
  format,
  explain,
  scale,
}: {
  matrix: Record<string, Record<string, number>>;
  format: (value: number) => string;
  /** The reading of one cell; a name against itself when row = column. */
  explain?: (row: string, column: string) => ReactNode;
  /** Words under the colour ramp's two ends and its middle. */
  scale?: { low: string; mid: string; high: string };
}) {
  const [focus, setFocus] = useState<HeatFocus | null>(null);
  // A tapped cell stays read until the page scrolls under it.
  useEffect(() => {
    if (!focus) return;
    const clear = () => setFocus(null);
    window.addEventListener("scroll", clear, { capture: true, passive: true });
    return () => window.removeEventListener("scroll", clear, { capture: true });
  }, [focus]);
  const names = Object.keys(matrix);
  if (!names.length) return null;
  const open = (row: string, column: string, target: Element) =>
    setFocus({ row, column, rect: target.getBoundingClientRect() });
  const lit = (name: string) => focus?.row === name || focus?.column === name;
  return (
    <div className="pf-scroll">
      <div
        className={focus ? "pf-heat pf-heat-focus" : "pf-heat"}
        style={{
          gridTemplateColumns: `auto repeat(${names.length}, minmax(1.5rem, 1fr))`,
        }}
        onPointerLeave={(event) => {
          if (event.pointerType !== "touch") setFocus(null);
        }}
      >
        <span />
        {names.map((name) => (
          <span
            className={lit(name) ? "pf-heat-col pf-heat-lit" : "pf-heat-col"}
            key={`head-${name}`}
          >
            {name}
          </span>
        ))}
        {names.map((row) => (
          <Fragment key={row}>
            <span className={lit(row) ? "pf-heat-label pf-heat-lit" : "pf-heat-label"}>
              <TickerCell ticker={row} name={false} className="pf-ticker" />
            </span>
            {names.map((column) => {
              const value = matrix[row]?.[column];
              const on = focus?.row === row || focus?.column === column;
              return (
                <span
                  className={on ? "pf-heat-cell pf-heat-on" : "pf-heat-cell"}
                  key={`${row}-${column}`}
                  style={{
                    background:
                      value === undefined ? "transparent" : correlationColor(value),
                  }}
                  aria-label={
                    value === undefined
                      ? `${row} × ${column}`
                      : `${row} × ${column} — ${format(value)}`
                  }
                  onPointerEnter={(event) => {
                    if (event.pointerType !== "touch")
                      open(row, column, event.currentTarget);
                  }}
                  onClick={(event) => {
                    const same = focus?.row === row && focus?.column === column;
                    if (same) setFocus(null);
                    else open(row, column, event.currentTarget);
                  }}
                />
              );
            })}
          </Fragment>
        ))}
      </div>
      <HeatLegend format={format} scale={scale} />
      {focus && explain ? (
        <HeatTip rect={focus.rect}>{explain(focus.row, focus.column)}</HeatTip>
      ) : null}
    </div>
  );
}

/**
 * The reading beside a cell: right of it, else left, kept on screen. Where
 * nothing hovers a finger covers the cell and what is beside it, so the box
 * sits above the cell instead (below when there is no room), as the other
 * charts lift theirs.
 */
function HeatTip({ rect, children }: { rect: DOMRect; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const tip = box.current;
    if (!tip) return;
    const { width, height } = tip.getBoundingClientRect();
    const gap = 10;
    const room = window.innerWidth;
    const touch = !!window.matchMedia?.("(hover: none)").matches;
    let left = rect.right + gap;
    if (touch) left = rect.left + rect.width / 2 - width / 2;
    else if (left + width > room - 8) left = rect.left - gap - width;
    left = Math.max(8, Math.min(left, room - width - 8));
    let top = rect.top + rect.height / 2 - height / 2;
    if (touch) {
      top = rect.top - gap - height;
      if (top < 8) top = rect.bottom + gap;
    }
    top = Math.max(8, Math.min(top, window.innerHeight - height - 8));
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    tip.style.visibility = "visible";
  });
  return createPortal(
    <div ref={box} className="pf-tip pf-heat-tip" role="status">
      {children}
    </div>,
    document.body,
  );
}

/**
 * The colour scale under the grid, −1 to +1 — Plotly's colorbar, flattened.
 *
 * Without it the ramp is a guess: nothing on the grid says whether the deep
 * end is "moves together" or "moves apart". Drawn from the same
 * `correlationColor` the cells use, so the two cannot disagree. With `scale`
 * the ends and the middle are also said in words.
 */
function HeatLegend({
  format,
  scale,
}: {
  format: (value: number) => string;
  scale?: { low: string; mid: string; high: string };
}) {
  const stops = [-1, -0.5, 0, 0.5, 1];
  return (
    <div className="pf-heat-legend-wrap" aria-hidden="true">
      <div className="pf-heat-legend">
        <span>{format(-1)}</span>
        <span
          className="pf-heat-ramp"
          style={{
            background: `linear-gradient(to right, ${stops
              .map((v) => correlationColor(v))
              .join(", ")})`,
          }}
        />
        <span>{format(1)}</span>
      </div>
      {scale ? (
        <div className="pf-heat-words">
          <span>{scale.low}</span>
          <span>{scale.mid}</span>
          <span>{scale.high}</span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The realized result per period: gains stack up, deductible losses (and any
 * recovered from an earlier deferral) stack down, and the diamond marks the
 * net the brackets then tax.
 *
 * A value axis in the gutter, as Plotly draws one, so a bar's height reads as
 * an amount and not only as a shape; and one hover box per period — every
 * figure of that year or month together, wherever the pointer is in its slot,
 * not only over a bar thick enough to aim at. `detail` adds what the bars
 * cannot draw (the tax, the deferred losses, which sales made the result);
 * a tap opens the box on a phone, and with `onPick` a click hands the period
 * to whatever reads it in full, `picked` marking the one it shows.
 */
type PeriodBarsProps = {
  periods: TaxPeriod[];
  labels: { gains: string; losses: string; recovered: string; net: string };
  money: (value: number) => string;
  /** Compact formatter for the gutter; falls back to `money` when omitted. */
  axisMoney?: (value: number) => string;
  /** More of a period in its hover box: rows under the bars' own, then any body. */
  detail?: (period: TaxPeriod) => { rows?: TipRow[]; body?: ReactNode };
  onPick?: (period: TaxPeriod) => void;
  picked?: string;
};

export function PeriodBars(props: PeriodBarsProps) {
  // Split so the measured frame exists whenever the chart does: a hook that
  // measures a node mounted later (an empty list that fills) never sees it.
  return props.periods.length ? <PeriodBarsPlot {...props} /> : null;
}

function PeriodBarsPlot({
  periods,
  labels,
  money,
  axisMoney,
  detail,
  onPick,
  picked,
}: PeriodBarsProps) {
  const gutter = axisMoney ?? money;
  const [hover, setHover] = useState<number | null>(null);
  const [frame, width] = useWidth(BARS.fallback);
  const svg = useRef<SVGSVGElement>(null);
  useTouchHold(svg, hover !== null, setHover);

  const up = token("candle-up");
  const down = token("candle-down");
  const recoveredColor = token("warn-orange");
  const netColor = token("info");
  const axis = token("border");
  const text = token("text-muted");

  const anyRecovered = periods.some((period) => period.recovered_loss !== 0);
  const tops = periods.map((period) =>
    Math.max(period.realized_gain, period.net_taxable, 0),
  );
  const bottoms = periods.map((period) =>
    Math.max(period.deductible_loss + period.recovered_loss, -period.net_taxable, 0),
  );
  const maxUp = Math.max(...tops, 0);
  const maxDown = Math.max(...bottoms, 0);
  const span = maxUp + maxDown || 1;

  const narrow = width < NARROW;
  const height = plotHeightFor(width, BARS.height);
  const left = narrow ? NARROW_PAD : PLOT.left;
  const top = 8;
  const footer = 22;
  const plotW = width - left - PLOT.right;
  const plotH = height - footer - top;
  const scale = plotH / span;
  const zero = top + maxUp * scale;
  const y = (value: number) => zero - value * scale;
  const slot = plotW / periods.length;
  const bar = Math.min(46, slot * 0.6);
  // Thin the labels to what the width can print without two of them touching
  // — a monthly run is easily sixty periods long. Fourteen across a desktop
  // plot; fewer as the plot narrows.
  const step = Math.max(
    1,
    Math.ceil(periods.length / Math.max(2, Math.min(14, Math.floor(plotW / 46)))),
  );

  const legend: [string, string][] = [
    [labels.gains, up],
    [labels.losses, down],
    ...(anyRecovered
      ? ([[labels.recovered, recoveredColor]] as [string, string][])
      : []),
    [labels.net, netColor],
  ];

  const at = hover === null ? null : periods[hover];
  const pickedAt = periods.findIndex((period) => period.period === picked);
  const more = at && detail ? detail(at) : null;
  const slotAt = (event: MouseEvent<SVGSVGElement>) => {
    const x = viewX(event, svg.current, width);
    if (x === null) return null;
    return Math.max(0, Math.min(periods.length - 1, Math.floor((x - left) / slot)));
  };
  const point = (event: PointerEvent<SVGSVGElement>) => {
    const index = slotAt(event);
    if (index !== null) setHover(index);
  };

  return (
    <div className="pf-chart">
      <Legend>
        {legend.map(([label, color]) => (
          <li className="pf-legend-row" key={label}>
            <span className="pf-swatch" style={{ background: color }} />
            <span>{label}</span>
          </li>
        ))}
      </Legend>
      <div className="pf-plot pf-scrub" ref={frame}>
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          className={onPick ? "pf-bars-pick" : undefined}
          onPointerMove={point}
          onPointerDown={point}
          onPointerLeave={(event) => {
            // A tap ends in a leave: the box it opened stays until the next.
            if (event.pointerType !== "touch") setHover(null);
          }}
          onClick={(event) => {
            const index = slotAt(event);
            const period = index === null ? undefined : periods[index];
            if (period && onPick) onPick(period);
          }}
        >
          <ValueAxis
            ticks={niceTicks(-maxDown, maxUp, narrow ? 3 : 4).filter(
              (tick) => tick !== 0,
            )}
            y={y}
            left={left}
            right={width - PLOT.right}
            format={gutter}
            inside={narrow}
            top={top}
          />
          <AxisLabel
            text={gutter(0)}
            at={zero}
            left={left}
            right={width - PLOT.right}
            inside={narrow}
            top={top}
          />
          {/* The period read in full elsewhere keeps a faint slot, since a
              monthly axis prints only every few labels. */}
          {pickedAt < 0 || pickedAt === hover ? null : (
            <rect
              x={left + pickedAt * slot}
              y={top}
              width={slot}
              height={plotH}
              fill={token("surface-hover")}
              opacity={0.55}
              pointerEvents="none"
            />
          )}
          {hover === null ? null : (
            <rect
              x={left + hover * slot}
              y={top}
              width={slot}
              height={plotH}
              fill={token("surface-hover")}
              pointerEvents="none"
            />
          )}
          <line
            x1={left}
            y1={zero}
            x2={width - PLOT.right}
            y2={zero}
            stroke={axis}
            strokeWidth="1"
          />
          {periods.map((period, index) => {
            const centre = left + index * slot + slot / 2;
            const x = centre - bar / 2;
            const gain = period.realized_gain * scale;
            const loss = period.deductible_loss * scale;
            const recovered = period.recovered_loss * scale;
            const net = y(period.net_taxable);
            return (
              <g key={period.period} pointerEvents="none">
                {gain > 0 ? (
                  <rect x={x} y={zero - gain} width={bar} height={gain} fill={up} />
                ) : null}
                {loss > 0 ? (
                  <rect x={x} y={zero} width={bar} height={loss} fill={down} />
                ) : null}
                {recovered > 0 ? (
                  <rect
                    x={x}
                    y={zero + loss}
                    width={bar}
                    height={recovered}
                    fill={recoveredColor}
                  />
                ) : null}
                <path
                  d={`M ${centre} ${net - 5} L ${centre + 5} ${net} L ${centre} ${net + 5} L ${centre - 5} ${net} Z`}
                  fill={netColor}
                />
                {index % step === 0 ? (
                  <text
                    x={centre < 24 ? 0 : width - centre < 24 ? width : centre}
                    y={height - 6}
                    fill={period.period === picked ? token("text-primary") : text}
                    fontSize="11"
                    fontWeight={period.period === picked ? 700 : undefined}
                    // A label past the frame's edge hangs inward instead.
                    textAnchor={
                      centre < 24 ? "start" : width - centre < 24 ? "end" : "middle"
                    }
                  >
                    {period.period}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
        {at && hover !== null ? (
          <ChartTip
            x={left + hover * slot + slot / 2}
            width={width}
            title={at.period}
            rows={[
              { label: labels.gains, value: money(at.realized_gain), color: up },
              { label: labels.losses, value: money(at.deductible_loss), color: down },
              ...(anyRecovered
                ? [
                    {
                      label: labels.recovered,
                      value: money(at.recovered_loss),
                      color: recoveredColor,
                    },
                  ]
                : []),
              { label: labels.net, value: money(at.net_taxable), color: netColor },
              ...(more?.rows ?? []),
            ]}
            wide={Boolean(more?.body)}
          >
            {more?.body}
          </ChartTip>
        ) : null}
      </div>
    </div>
  );
}

export type ReturnSeries = {
  label: string;
  /** Cumulative return per date, aligned to `dates`; null where undefined. */
  points: (number | null)[];
  /** Dotted, for a line that is a hypothesis rather than a record. */
  dashed?: boolean;
  color?: string;
  /** The line the chart is about — the reader's own money. Drawn heavier and
      over the others, with a dot where it ends, so it leads before the legend
      is read; the rest step back a little. */
  focal?: boolean;
  /** A second reading shown in parentheses in the tooltip, e.g. a percentage
      beside an amount; null leaves the row as the bare figure. */
  tipNote?: (index: number, value: number) => string | null;
  /** Read in the tooltip (and dotted on hover) but not stroked or listed:
      the edge of a band already draws it. */
  tipOnly?: boolean;
};

/** A shaded range between two series — a forecast's spread. */
export type ReturnBand = {
  label: string;
  low: (number | null)[];
  high: (number | null)[];
  color: string;
};

/**
 * The euros behind return lines that all share one denominator: each line's
 * value on a day is that day's net money in times one plus its return. With it
 * the tooltip reads each line as money — worth, gain, and the gap to the first
 * line — rather than as a bare percentage.
 */
export type LineMoney = {
  /** Net money in per date, aligned to `dates`; null while nothing is in. */
  invested: (number | null)[];
  money: (value: number, signed?: boolean) => string;
  change: (fraction: number) => string;
  labels: { invested: string; value: string; gain: string; versus: string };
};

/** One line's money on one day, against the first line's. */
export function lineMoney(
  invested: number,
  value: number,
  first: number | null,
): { worth: number; gain: number; versus: number | null } {
  return {
    worth: invested * (1 + value),
    gain: invested * value,
    versus: first === null ? null : invested * (value - first),
  };
}

/** Where a plot sits in its frame: the left gutter holds the value axis, and
    `height` is the desktop one — a narrow plot is squarer (`plotHeightFor`).
    The frame is the measured width, so every figure here is in pixels. */
const PLOT = { height: 300, top: 8, right: 8, bottom: 24, left: 64 };

/** The margin of a narrow plot, whose value labels sit inside it. */
const NARROW_PAD = 8;

/** The realized-result bars: the width a render without layout sees, and
    their desktop height. */
const BARS = { fallback: 720, height: 240 };

/** The return chart's margins; its width is measured and its left gutter
    sized to the labels it holds. */
const RETURN = { fallback: 720, top: 10, right: 10, bottom: 24 };

/** Tall enough on a phone to follow a crossing, never a poster across a
    desktop row. */
const returnHeight = (width: number) =>
  width < NARROW
    ? plotHeightFor(width, 380)
    : Math.round(Math.min(380, Math.max(220, width * 0.4)));

/** The room 11px axis labels need — a digit is ~6.4px — plus their 6px gap. */
const gutterFor = (labels: string[]) =>
  Math.max(32, Math.ceil(Math.max(0, ...labels.map((one) => one.length)) * 6.4) + 10);

/** Month steps a date axis can label at, and the room a label of each needs. */
const MONTH_STEPS = [1, 3, 6, 12, 24, 60];
const TICK_ROOM = { month: 96, year: 56 };

/**
 * Calendar-aligned date ticks on an index axis: the first day of every n-th
 * month, n the smallest step whose labels sit far enough apart to read.
 *
 * Start, middle and end landed on whichever days those happened to be — "abr
 * 22 · jul 24 · oct 26" over four years — and left the years between
 * uncounted, which is what a reader counts by. `yearly` says the step is a
 * year or more, so each label can be the year alone (and need less room). A
 * window too short to hold two boundaries keeps start, middle and end.
 */
export function dateTicks(
  dates: string[],
  plotW: number,
): { indices: number[]; yearly: boolean } {
  const count = dates.length;
  const unit = plotW / Math.max(1, count - 1);
  const opens: { index: number; month: number }[] = [];
  for (let i = 1; i < count; i++) {
    const at = dates[i]!;
    if (at.slice(0, 7) === dates[i - 1]!.slice(0, 7)) continue;
    const [year = 0, month = 1] = at.split("-").map(Number);
    opens.push({ index: i, month: year * 12 + month - 1 });
  }
  for (const step of MONTH_STEPS) {
    const picked = opens.filter((one) => one.month % step === 0);
    if (picked.length < 2) break;
    const room = step >= 12 ? TICK_ROOM.year : TICK_ROOM.month;
    const apart = picked.every(
      (one, k) => k === 0 || (one.index - picked[k - 1]!.index) * unit >= room,
    );
    if (apart) return { indices: picked.map((one) => one.index), yearly: step >= 12 };
  }
  return { indices: [0, Math.floor(count / 2), count - 1], yearly: false };
}

/** A series' last drawn value: where its line ends. */
const lastValue = (points: (number | null)[]) => {
  for (let i = points.length - 1; i >= 0; i--) {
    const value = points[i];
    if (value !== null && value !== undefined) return value;
  }
  return null;
};

/**
 * Several cumulative-return lines on one axis, rebased to the window.
 *
 * What the account earned, what today's holdings would have earned over the
 * same window, and what each benchmark did. Percentages against a zero line —
 * the axis every one of them starts from — so the question "did I beat it" is
 * answered by which line is higher, not by reading two scales. The value axis
 * carries its percentages, so "how much higher" is readable too.
 *
 * Drawn at the width it is given rather than in a fixed viewBox: scaled up
 * across a desktop row, a 720-unit frame printed its 11px labels at 29px and
 * grew taller than the screen. Five lines that cross all year are spaghetti
 * until one leads, so a `focal` series is drawn heavier and on top, and the
 * legend picks any one out: hover or keyboard focus previews it, a click (or
 * tap) holds it, and every other line drops back. With `money` the pointer
 * singles out the line under it too, and each entry names that line's worth;
 * with `legendValues` it says where the line ends instead, so who finished
 * ahead reads without hovering at all. The plot itself takes focus: the arrow
 * keys walk the crosshair a day at a time.
 *
 * The basket's line is dotted on purpose: it is a backtest of holdings that
 * have not been held that way all along, and drawing it like a record would
 * make it read as one.
 */
export function ReturnLines({
  dates,
  series,
  format,
  tickFormat = format,
  formatDate,
  bands = [],
  marker,
  money,
  label,
  legendValues = false,
}: {
  dates: string[];
  series: ReturnSeries[];
  format: (value: number) => string;
  /** The value axis's labels, which need fewer decimals than a reading. */
  tickFormat?: (value: number) => string;
  formatDate: (iso: string) => string;
  /** Shaded ranges drawn under the lines, widest first. */
  bands?: ReturnBand[];
  /** A labelled vertical rule at one index — "today" between a record and a
      projection. */
  marker?: { index: number; label: string };
  /** The money behind the lines: a tooltip in euros, a legend that names
      each line's worth, and the line under the pointer singled out. */
  money?: LineMoney;
  /** What the plot shows, for a screen reader. */
  label?: string;
  /** Print each line's last value on its legend entry. */
  legendValues?: boolean;
}) {
  const [pointer, setHover] = useState<number | null>(null);
  const [peek, setPeek] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  // With money, the line nearest the pointer, when no legend entry picks one.
  const [near, setNear] = useState<string | null>(null);
  const [frame, width] = useWidth(RETURN.fallback);
  const svg = useRef<SVGSVGElement>(null);
  useTouchHold(svg, pointer !== null, setHover);
  const drawn = series.filter((one) => one.points.some((v) => v !== null));
  if (dates.length < 2 || !drawn.length) return null;
  // A shorter window can arrive under a pointer still resting on the old one.
  const hover = pointer !== null && pointer < dates.length ? pointer : null;
  const last = dates.length - 1;

  const values = [
    ...drawn.flatMap((one) => one.points),
    ...bands.flatMap((band) => [...band.low, ...band.high]),
  ].filter((v): v is number => v !== null);
  // Zero is always on the axis: a chart of returns that crops it hides whether
  // the line is above water, which is the first thing anybody reads off it.
  // A little air past an extreme, so a peak does not graze the frame — none
  // under a zero that is the floor.
  const floor = Math.min(0, ...values);
  const ceiling = Math.max(0, ...values);
  const air = (ceiling - floor) * 0.04;
  const low = floor < 0 ? floor - air : 0;
  const high = ceiling > 0 ? ceiling + air : 0;
  const span = high - low || 1;

  const height = returnHeight(width);
  const plotH = height - RETURN.top - RETURN.bottom;
  const narrow = width < NARROW;
  const yTicks = niceTicks(
    low,
    high,
    Math.max(3, Math.min(narrow ? 4 : 6, Math.round(plotH / 56))),
  );
  // A narrow plot has no gutter: its value labels sit inside, on their lines.
  const left = narrow ? NARROW_PAD : gutterFor([...yTicks, 0].map(tickFormat));
  const right = width - (narrow ? NARROW_PAD : RETURN.right);
  const plotW = right - left;
  const x = (index: number) => left + (index / last) * plotW;
  const y = (value: number) => RETURN.top + (1 - (value - low) / span) * plotH;

  const ramp = categorical();
  const colored = drawn.map((one, index) => ({
    ...one,
    color: one.color ?? ramp[index % ramp.length]!,
  }));
  const listed = colored.filter((one) => !one.tipOnly);
  const wanted = peek ?? pinned;
  // A held name can outlive its line when the window refetches without it.
  const picked = listed.some((one) => one.label === wanted) ? wanted : null;
  const active = picked ?? (money && hover !== null ? near : null);
  const led = listed.some((one) => one.focal);
  const opacity = (one: ReturnSeries) =>
    active !== null ? (one.label === active ? 1 : 0.2) : !led || one.focal ? 1 : 0.8;
  // Drawn last is drawn on top: the singled-out line, then the focal one.
  const rank = (one: ReturnSeries) => (one.label === active ? 2 : one.focal ? 1 : 0);
  const stacked = [...listed].sort((a, b) => rank(a) - rank(b));
  const ring = token("surface-card");

  /** Contiguous runs of drawn points, so a gap breaks the line instead of
      jumping across it. */
  const paths = (points: (number | null)[]) => {
    const out: string[] = [];
    let run: string[] = [];
    points.forEach((value, index) => {
      if (value === null) {
        if (run.length > 1) out.push(run.join("L"));
        run = [];
        return;
      }
      run.push(`${x(index)},${y(value)}`);
    });
    if (run.length > 1) out.push(run.join("L"));
    return out.map((one) => `M${one}`);
  };

  /** Each contiguous run where both edges exist, as one closed polygon. */
  const areas = (band: ReturnBand) => {
    const out: string[] = [];
    let run: number[] = [];
    const flush = () => {
      if (run.length > 1) {
        const top = run.map((i) => `${x(i)},${y(band.high[i]!)}`);
        const bottom = [...run].reverse().map((i) => `${x(i)},${y(band.low[i]!)}`);
        out.push(`M${[...top, ...bottom].join("L")}Z`);
      }
      run = [];
    };
    dates.forEach((_, i) => {
      if (band.low[i] == null || band.high[i] == null) flush();
      else run.push(i);
    });
    flush();
    return out;
  };

  const xTicks = dateTicks(dates, plotW);
  // A label near an edge hangs inward instead of past the frame.
  const anchor = (at: number) =>
    at - left < 24 ? "start" : right - at < 24 ? "end" : "middle";

  /** The stroked line nearest viewBox y `at` on day `index`, if close enough
      to be the one the pointer means. */
  const closest = (at: number | null, index: number): string | null => {
    if (at === null) return null;
    let best: string | null = null;
    let gap = 24;
    for (const one of colored) {
      const value = one.points[index];
      if (one.tipOnly || value == null) continue;
      const off = Math.abs(y(value) - at);
      if (off < gap) [best, gap] = [one.label, off];
    }
    return best;
  };
  const point = (event: PointerEvent<SVGSVGElement>) => {
    const at = viewX(event, svg.current, width);
    if (at === null) return;
    const index = nearest(at, left, plotW, dates.length);
    setHover(index);
    if (money) setNear(closest(viewY(event, svg.current, width), index));
  };
  // The day the legend's figures are read on: the pointer's, else the last
  // day with money in.
  let shown = hover;
  if (shown === null && money)
    for (let i = money.invested.length - 1; i >= 0 && shown === null; i--)
      if (money.invested[i] != null) shown = i;

  return (
    <div className="pf-chart">
      <Legend>
        {listed.map((one) => {
          const end = legendValues && !money ? lastValue(one.points) : null;
          const value = shown === null ? null : one.points[shown];
          const base = shown === null || !money ? null : money.invested[shown];
          return (
            <li key={one.label}>
              <button
                type="button"
                className="pf-legend-key"
                aria-pressed={pinned === one.label}
                data-dim={active !== null && active !== one.label ? "" : undefined}
                // A touch has no hover to preview with: the tap holds instead.
                onPointerEnter={(event) => {
                  if (event.pointerType === "mouse") setPeek(one.label);
                }}
                onPointerLeave={() => setPeek(null)}
                // Only keyboard focus previews: a click's focus would keep the
                // line picked after the click that let it go.
                onFocus={(event) => {
                  if (event.currentTarget.matches(":focus-visible")) setPeek(one.label);
                }}
                onBlur={() => setPeek(null)}
                onClick={() =>
                  setPinned((held) => (held === one.label ? null : one.label))
                }
              >
                <span
                  className={
                    one.dashed
                      ? "pf-swatch pf-swatch-dashed"
                      : "pf-swatch pf-swatch-line"
                  }
                  style={{ background: one.color }}
                />
                <span>{one.label}</span>
                {money && value != null && base != null ? (
                  <span className="pf-muted">
                    {money.money(lineMoney(base, value, null).worth)}
                  </span>
                ) : null}
                {end === null ? null : (
                  <strong className="pf-legend-value">{format(end)}</strong>
                )}
              </button>
            </li>
          );
        })}
        {bands.map((band) => (
          <li className="pf-legend-row" key={band.label}>
            <span className="pf-swatch" style={{ background: band.color }} />
            <span>{band.label}</span>
          </li>
        ))}
      </Legend>
      <div className="pf-plot pf-scrub" ref={frame}>
        <svg
          ref={svg}
          className="pf-return-plot"
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={label}
          tabIndex={0}
          onPointerMove={point}
          // A tap is a pointer that never moves: it answers too, on a phone.
          onPointerDown={point}
          // A finger lifting is a leave too; the tapped day stays read until
          // the next tap moves it.
          onPointerLeave={(event) => {
            if (event.pointerType === "touch") return;
            setHover(null);
            setNear(null);
          }}
          // The crosshair by keyboard: arrows step a day (with shift, ten),
          // Home and End jump to the edges, Escape puts it away.
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setHover(null);
              setNear(null);
              return;
            }
            const at = hover ?? last;
            const step = event.shiftKey ? 10 : 1;
            const next =
              event.key === "ArrowLeft"
                ? at - step
                : event.key === "ArrowRight"
                  ? at + step
                  : event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? last
                      : null;
            if (next === null) return;
            event.preventDefault();
            setHover(Math.max(0, Math.min(last, next)));
          }}
          onFocus={(event) => {
            if (event.currentTarget.matches(":focus-visible"))
              setHover((at) => at ?? last);
          }}
          onBlur={() => setHover(null)}
        >
          <ValueAxis
            ticks={yTicks.filter((tick) => tick !== 0)}
            y={y}
            left={left}
            right={right}
            format={tickFormat}
            inside={narrow}
            top={RETURN.top}
          />
          <line
            x1={left}
            x2={right}
            y1={y(0)}
            y2={y(0)}
            stroke={token("border")}
            strokeWidth="1"
          />
          <AxisLabel
            text={tickFormat(0)}
            at={y(0)}
            left={left}
            right={right}
            inside={narrow}
            top={RETURN.top}
          />
          {bands.map((band) =>
            areas(band).map((d, index) => (
              <path
                key={`${band.label}-${index}`}
                d={d}
                fill={band.color}
                stroke="none"
              />
            )),
          )}
          {marker && marker.index > 0 && marker.index < dates.length ? (
            <g pointerEvents="none">
              <line
                x1={x(marker.index)}
                x2={x(marker.index)}
                y1={RETURN.top}
                y2={RETURN.top + plotH}
                stroke={token("border")}
                strokeWidth="1"
              />
              <text
                x={x(marker.index) + 4}
                y={RETURN.top + 11}
                fill={token("text-muted")}
                fontSize="11"
              >
                {marker.label}
              </text>
            </g>
          ) : null}
          {stacked.map((one) =>
            paths(one.points).map((d, index) => (
              <path
                key={`${one.label}-${index}`}
                className="pf-line"
                data-series={one.label}
                d={d}
                fill="none"
                stroke={one.color}
                strokeWidth={one.label === active ? 2.5 : one.focal ? 2 : 1.5}
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={one.dashed ? "4 3" : undefined}
                style={{ strokeOpacity: opacity(one) }}
              />
            )),
          )}
          {/* Where the reader's own line ends, ringed in the card's surface so
            it stays one dot where the others run into it. */}
          {stacked.map((one) => {
            const end = one.points[last];
            return !one.focal || end === null || end === undefined ? null : (
              <circle
                key={`${one.label}-end`}
                className="pf-line"
                cx={x(last)}
                cy={y(end)}
                r="4"
                fill={one.color}
                stroke={ring}
                strokeWidth="2"
                style={{ opacity: opacity(one) }}
              />
            );
          })}
          {/* Plotly's `hovermode="x"`: the whole plot answers, nearest day by
            the pointer's x, with a crosshair and a dot on every line there. */}
          {hover === null ? null : (
            <g pointerEvents="none">
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={RETURN.top}
                y2={RETURN.top + plotH}
                stroke={token("text-faint")}
                strokeDasharray="2 2"
              />
              {colored.map((one) => {
                const value = one.points[hover];
                return value === null || value === undefined ? null : (
                  <circle
                    key={one.label}
                    cx={x(hover)}
                    cy={y(value)}
                    r="4"
                    fill={one.color}
                    stroke={ring}
                    strokeWidth="2"
                    opacity={opacity(one)}
                  />
                );
              })}
            </g>
          )}
          {xTicks.indices.map((index) => (
            <text
              key={index}
              x={x(index)}
              y={height - 6}
              fill={token("text-muted")}
              fontSize="11"
              textAnchor={anchor(x(index))}
            >
              {xTicks.yearly ? dates[index]!.slice(0, 4) : formatDate(dates[index]!)}
            </text>
          ))}
        </svg>
        {hover === null ? null : money && money.invested[hover] != null ? (
          <ChartTip
            x={x(hover)}
            width={width}
            title={formatDate(dates[hover]!)}
            rows={[
              {
                label: money.labels.invested,
                value: money.money(money.invested[hover]!),
              },
            ]}
            className="pf-tip-money"
          >
            <MoneyRows
              lines={colored}
              index={hover}
              invested={money.invested[hover]!}
              money={money}
              active={active}
            />
          </ChartTip>
        ) : (
          <ChartTip
            x={x(hover)}
            width={width}
            title={formatDate(dates[hover]!)}
            rows={colored.map((one) => {
              const value = one.points[hover];
              return {
                label: one.label,
                value:
                  value === null || value === undefined
                    ? "—"
                    : withNote(format(value), one.tipNote?.(hover, value)),
                color: one.color,
                mark: one.dashed ? "dashed" : "line",
              };
            })}
          />
        )}
      </div>
    </div>
  );
}

/** Each line on one day as money: worth, gain with its return, and the gap
    to the first line — the book — in euros. */
function MoneyRows({
  lines,
  index,
  invested,
  money,
  active,
}: {
  lines: (ReturnSeries & { color: string })[];
  index: number;
  invested: number;
  money: LineMoney;
  active: string | null;
}) {
  const first = lines[0]?.points[index] ?? null;
  return (
    <span className="pf-tip-lines">
      <span />
      <span className="pf-tip-head">{money.labels.value}</span>
      <span className="pf-tip-head">{money.labels.gain}</span>
      <span className="pf-tip-head">{money.labels.versus}</span>
      {lines.map((one, row) => {
        const value = one.points[index];
        const on = active === one.label ? " pf-tip-on" : "";
        if (value == null)
          return (
            <span className={`pf-tip-line${on}`} key={one.label}>
              <LineName one={one} />
              <span className="pf-tip-num">—</span>
              <span />
              <span />
            </span>
          );
        const figures = lineMoney(invested, value, row === 0 ? null : first);
        return (
          <span className={`pf-tip-line${on}`} key={one.label}>
            <LineName one={one} />
            <strong className="pf-tip-num">{money.money(figures.worth)}</strong>
            <span className={`pf-tip-num ${figures.gain < 0 ? "pf-down" : "pf-up"}`}>
              {money.money(figures.gain, true)} ({money.change(value)})
            </span>
            <span
              className={
                figures.versus === null
                  ? "pf-tip-num"
                  : `pf-tip-num ${figures.versus < 0 ? "pf-down" : "pf-up"}`
              }
            >
              {figures.versus === null ? "" : money.money(figures.versus, true)}
            </span>
          </span>
        );
      })}
    </span>
  );
}

function LineName({ one }: { one: ReturnSeries & { color: string } }) {
  return (
    <span className="pf-tip-name">
      <span className="pf-tip-swatch" style={{ background: one.color }} />
      <span>{one.label}</span>
    </span>
  );
}

function withNote(text: string, note: string | null | undefined): string {
  return note ? `${text} (${note})` : text;
}

/**
 * The gap between a value line and the money behind it, one polygon per
 * contiguous run of the same sign. A run is extended by one point on each side
 * so neighbouring bands meet instead of leaving a seam at the crossover. The
 * value line is cut on the same runs and coloured by them — green above what
 * went in, red below; the overlapping point keeps the two colours joined.
 */
function gainBands(
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

/** Fewest days a drag has to cover to count as a zoom rather than a click. */
const MIN_ZOOM_DAYS = 5;

type BookPoint = {
  date: string;
  injected: number | null;
  value: number | null;
  pnl_pct?: number | null;
};

/**
 * What the history's hover box says about one day — Plotly's template: the
 * value under the colour it is drawn in, the injected capital, and the P/L
 * between them as an amount and a percentage. Pure, so the wording is
 * testable without a pointer.
 */
export function bookTip(
  day: { value: number; injected: number; pnl_pct?: number | null },
  labels: { injected: string; profit: string; loss: string; pnl: string },
  money: (value: number, signed?: boolean) => string,
  percent: (value: number) => string,
): TipRow[] {
  const pnl = day.value - day.injected;
  const pct = day.pnl_pct ?? (day.injected ? pnl / day.injected : null);
  const gain = day.value >= day.injected;
  return [
    {
      label: gain ? labels.profit : labels.loss,
      value: money(day.value),
      color: gain ? token("up") : token("down"),
    },
    { label: labels.injected, value: money(day.injected), color: token("text-muted") },
    {
      label: labels.pnl,
      value: `${money(pnl, true)}${pct === null ? "" : ` (${percent(pct)})`}`,
    },
  ];
}

/**
 * What the history's box says between two days being compared: how much the
 * value moved, how much of that was money put in or taken out, and the rest —
 * what the market did to the book. Amounts only: a percentage over a span
 * that money flowed through would read the deposits as returns.
 */
export function bookSpanTip(
  from: { value: number; injected: number },
  to: { value: number; injected: number },
  labels: { value: string; injected: string; pnl: string },
  money: (value: number, signed?: boolean) => string,
): TipRow[] {
  const moved = to.value - from.value;
  const put = to.injected - from.injected;
  const gain = moved - put;
  return [
    {
      label: labels.value,
      value: money(moved, true),
      color: moved >= 0 ? token("up") : token("down"),
    },
    { label: labels.injected, value: money(put, true), color: token("text-muted") },
    { label: labels.pnl, value: money(gain, true) },
  ];
}

/**
 * Injected capital against market value, one point per day.
 *
 * A band runs between the two lines, green where the book is worth more than
 * what went into it and red where it is not. That band is the reading — the gap
 * is the profit, and its colour is the answer to "am I up?" before any number
 * is read.
 *
 * Built as one polygon per contiguous stretch of the same sign rather than as
 * one shape clipped twice: a fill that crosses the crossover point would paint
 * the wrong colour on one side of it, and the crossover is exactly the day a
 * reader is looking for.
 *
 * Drag across the plot to zoom into those days, with the value axis refitted to
 * them, since a €40k book's March wobble is invisible on an axis sized for its
 * whole life. Double-click, or the reset button, puts the window back. The
 * tooltip carries value, injected, and the P/L between them as an amount and a
 * percentage. Two fingers, or a secondary click with a mouse (`useSpan`),
 * compare two days instead (`bookSpanTip`).
 */
type BookHistoryProps = {
  points: BookPoint[];
  labels: {
    injected: string;
    /** The value line on its own, for the change between two days. */
    value: string;
    profit: string;
    loss: string;
    pnl: string;
    reset: string;
  };
  money: (value: number, signed?: boolean) => string;
  /** Compact formatter for the gutter; falls back to `money` when omitted. */
  axisMoney?: (value: number) => string;
  percent: (value: number) => string;
  formatDate: (iso: string) => string;
};

type BookDay = BookPoint & { injected: number; value: number };

export function BookHistory({ points, ...rest }: BookHistoryProps) {
  // Both legs present or the day is not comparable: a value without its
  // reference line cannot be shaded against anything. Split from the drawing
  // so the measured frame exists whenever the chart does.
  const all = points.filter(
    (point): point is BookDay => point.injected !== null && point.value !== null,
  );
  return all.length < 2 ? null : <BookHistoryPlot all={all} {...rest} />;
}

function BookHistoryPlot({
  all,
  labels,
  money,
  axisMoney,
  percent,
  formatDate,
}: Omit<BookHistoryProps, "points"> & { all: BookDay[] }) {
  const gutter = axisMoney ?? ((value: number) => money(value));
  const [frame, width] = useWidth(BARS.fallback);
  const [zoom, setZoom] = useState<{ from: number; to: number } | null>(null);
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  // Two visible days being compared (`useSpan`), in day order.
  const [measure, setMeasure] = useState<{ from: number; to: number } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drop = useCallback(() => {
    setHover(null);
    setMeasure(null);
  }, []);
  useTouchHold(svg, hover !== null || measure !== null, drop);
  // A new window from the server is a new series: yesterday's zoom indexes
  // into days that are no longer the same days.
  const first = all[0]?.date;
  const last = all[all.length - 1]?.date;
  useEffect(() => {
    setZoom(null);
    setDrag(null);
    setHover(null);
    setMeasure(null);
  }, [first, last, all.length]);

  const days = zoom ? all.slice(zoom.from, zoom.to + 1) : all;
  const narrow = width < NARROW;
  const height = plotHeightFor(width, PLOT.height);
  const left = narrow ? NARROW_PAD : PLOT.left;
  const plotW = width - left - PLOT.right;
  const plotH = height - PLOT.top - PLOT.bottom;

  const values = days.flatMap((day) => [day.injected, day.value]);
  const rawLow = Math.min(...values);
  const rawHigh = Math.max(...values);
  // A hair of headroom so the line never rides the frame, and a flat book does
  // not divide by zero.
  const pad = (rawHigh - rawLow) * 0.04 || Math.abs(rawHigh) * 0.04 || 1;
  const low = rawLow - pad;
  const high = rawHigh + pad;
  const span = high - low;
  const x = (index: number) => left + (index / (days.length - 1)) * plotW;
  const y = (value: number) => PLOT.top + (1 - (value - low) / span) * plotH;

  const line = (pick: (day: (typeof days)[number]) => number) =>
    days.map((day, index) => `${x(index)},${y(pick(day))}`).join(" ");

  const bands = gainBands(
    days.map((day) => ({ value: day.value, base: day.injected })),
    x,
    y,
  );

  const ticks = [0, Math.floor(days.length / 2), days.length - 1];
  const offsetOf = zoom ? zoom.from : 0;

  /** Where a pointer is on the SVG, in viewBox x. */
  const xAt = (event: MouseEvent<SVGSVGElement>) =>
    viewX(event, svg.current, width) ?? left;
  /** Which visible day a viewBox x is over. */
  const dayOf = (at: number) => nearest(at, left, plotW, days.length);
  const spanned = useSpan((pair) => {
    if (!pair) return setMeasure(null);
    const [a, b] = pair.map(dayOf) as [number, number];
    setHover(null);
    setMeasure({ from: Math.min(a, b), to: Math.max(a, b) });
  });

  const finish = () => {
    if (!drag) return;
    const lo = Math.min(drag.from, drag.to);
    const hi = Math.max(drag.from, drag.to);
    setDrag(null);
    if (hi - lo < MIN_ZOOM_DAYS) return;
    setZoom({ from: offsetOf + lo, to: offsetOf + hi });
  };

  const upColor = token("up");
  const downColor = token("down");
  const tipRows = (day: (typeof days)[number]) => bookTip(day, labels, money, percent);
  const hovered = hover === null ? null : days[hover];
  const anyGain = days.some((day) => day.value >= day.injected);
  const anyLoss = days.some((day) => day.value < day.injected);

  return (
    <div className="pf-chart">
      <div className="pf-chart-head">
        <Legend>
          <li className="pf-legend-row">
            <span className="pf-swatch" style={{ background: token("text-muted") }} />
            <span>{labels.injected}</span>
          </li>
          {/* Only the colours this window actually draws, as Plotly's legend
              leaves out a trace with no points. */}
          {anyGain ? (
            <li className="pf-legend-row">
              <span className="pf-swatch" style={{ background: upColor }} />
              <span>{labels.profit}</span>
            </li>
          ) : null}
          {anyLoss ? (
            <li className="pf-legend-row">
              <span className="pf-swatch" style={{ background: downColor }} />
              <span>{labels.loss}</span>
            </li>
          ) : null}
        </Legend>
        {zoom ? (
          <button
            className="ag-btn pf-zoom-reset"
            type="button"
            onClick={() => setZoom(null)}
          >
            {labels.reset}
          </button>
        ) : null}
      </div>
      <div className="pf-plot pf-scrub" ref={frame}>
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          className="pf-zoomable"
          onPointerDown={(event) => {
            if (spanned.down(event, xAt(event))) return;
            const at = dayOf(xAt(event));
            // A finger scrubs, it does not zoom: on a phone the drag that
            // drew a window was the only way to read a day, so every attempt
            // to read one ended zoomed into a sliver of it.
            if (event.pointerType === "touch") {
              setHover(at);
              return;
            }
            if (event.button !== 0) return;
            setDrag({ from: at, to: at });
          }}
          onPointerMove={(event) => {
            if (spanned.move(event, xAt(event))) return;
            const at = dayOf(xAt(event));
            setHover(at);
            if (drag) setDrag({ ...drag, to: at });
          }}
          onPointerUp={(event) => {
            if (spanned.up(event)) return;
            finish();
          }}
          // A finger lifting is a leave too: the day it read stays up until
          // the reader touches elsewhere (useTouchHold).
          onPointerLeave={(event) => {
            spanned.leave(event);
            if (event.pointerType !== "touch") setHover(null);
            finish();
          }}
          onPointerCancel={spanned.cancel}
          onContextMenu={(event) => spanned.menu?.(event, xAt(event))}
          onDoubleClick={() => setZoom(null)}
        >
          <ValueAxis
            ticks={niceTicks(low, high, narrow ? 3 : 4)}
            y={y}
            left={left}
            right={width - PLOT.right}
            format={gutter}
            inside={narrow}
            top={PLOT.top}
          />
          {bands.map((band, index) => (
            <path
              key={index}
              d={band.path}
              fill={band.gain ? token("profit-band") : token("loss-band")}
            />
          ))}
          <polyline
            points={line((day) => day.injected)}
            fill="none"
            stroke={token("text-muted")}
            strokeWidth="1.5"
            strokeDasharray="4 3"
          />
          {bands.map((band, index) => (
            <polyline
              key={`value-${index}`}
              points={band.value}
              fill="none"
              stroke={band.gain ? upColor : downColor}
              strokeWidth="2"
            />
          ))}
          {measure ? (
            <g className="pf-span" pointerEvents="none">
              {measure.to > measure.from ? (
                <rect
                  x={x(measure.from)}
                  y={PLOT.top}
                  width={x(measure.to) - x(measure.from)}
                  height={plotH}
                />
              ) : null}
              {[measure.from, measure.to].map((index, at) => (
                <line
                  key={at}
                  x1={x(index)}
                  x2={x(index)}
                  y1={PLOT.top}
                  y2={PLOT.top + plotH}
                />
              ))}
            </g>
          ) : null}
          {hovered && hover !== null && !measure ? (
            <g pointerEvents="none">
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={PLOT.top}
                y2={PLOT.top + plotH}
                stroke={token("text-faint")}
                strokeDasharray="2 2"
              />
              <circle
                cx={x(hover)}
                cy={y(hovered.value)}
                r="3"
                fill={hovered.value >= hovered.injected ? upColor : downColor}
              />
            </g>
          ) : null}
          {drag && drag.from !== drag.to ? (
            <rect
              x={x(Math.min(drag.from, drag.to))}
              y={PLOT.top}
              width={Math.abs(x(drag.to) - x(drag.from))}
              height={plotH}
              fill={token("surface-hover")}
              stroke={token("border")}
              pointerEvents="none"
            />
          ) : null}
          {ticks.map((index) => (
            <text
              key={index}
              x={Math.min(Math.max(x(index), left + 24), width - 24)}
              y={height - 6}
              textAnchor="middle"
              fontSize="11"
              fill={token("text-muted")}
            >
              {formatDate(days[index]!.date)}
            </text>
          ))}
        </svg>
        {measure && measure.to > measure.from ? (
          <ChartTip
            x={(x(measure.from) + x(measure.to)) / 2}
            width={width}
            title={`${formatDate(days[measure.from]!.date)} → ${formatDate(days[measure.to]!.date)}`}
            rows={bookSpanTip(days[measure.from]!, days[measure.to]!, labels, money)}
          />
        ) : hovered && hover !== null && !drag && !measure ? (
          <ChartTip
            x={x(hover)}
            width={width}
            title={formatDate(hovered.date)}
            rows={tipRows(hovered)}
          />
        ) : null}
      </div>
    </div>
  );
}

/** The two floors of the book-and-rates frame: money over rates with no gap
    between them, one date axis under both, money's gutter on the left and the
    rates' on the right. `money` and `rates` are the desktop heights, and the
    ratio a narrow frame keeps them in. `inset` keeps a rate line off the seam. */
const FLOORS = {
  left: 64,
  right: 52,
  top: 8,
  money: 200,
  rates: 130,
  inset: 8,
  bottom: 24,
};

type BookRatePoint = {
  date: string;
  value: number | null;
  /** What the book had put to work by this date — the base the gain is over. */
  invested: number | null;
};

/** A figure each point has of its own rather than one running since the
    first — a month's own return — drawn as bars from zero on the rates'
    floor, under the lines and on their axis. */
export type RateBars = {
  label: string;
  points: (number | null)[];
  /** Its formatter in the box, e.g. signed; falls back to the rates' own. */
  format?: (value: number) => string;
};

/** The box `BookAndRates` shows for one point: the money, then the bars'
    figure for that point, then each rate. */
export function bookRatesTip(
  index: number,
  point: { value: number; invested: number },
  {
    labels,
    money,
    format,
    series,
    bars,
  }: {
    labels: { invested: string; profit: string; loss: string; gain: string };
    money: (value: number, signed?: boolean) => string;
    format: (value: number) => string;
    series: (ReturnSeries & { color: string })[];
    bars?: RateBars;
  },
): TipRow[] {
  const up = point.value >= point.invested;
  const bar = bars?.points[index];
  return [
    {
      label: up ? labels.profit : labels.loss,
      value: money(point.value),
      color: up ? token("up") : token("down"),
    },
    {
      label: labels.invested,
      value: money(point.invested),
      color: token("text-muted"),
    },
    { label: labels.gain, value: money(point.value - point.invested, true) },
    ...(bars
      ? [
          {
            label: bars.label,
            value:
              bar === null || bar === undefined ? "—" : (bars.format ?? format)(bar),
            color:
              bar === null || bar === undefined
                ? undefined
                : bar >= 0
                  ? token("candle-up")
                  : token("candle-down"),
          },
        ]
      : []),
    ...series.map((one) => {
      const value = one.points[index];
      return {
        label: one.label,
        value:
          value === null || value === undefined
            ? "—"
            : withNote(format(value), one.tipNote?.(index, value)),
        color: one.color,
      };
    }),
  ];
}

/**
 * A window's euros and its rates on one date axis, answering to one pointer.
 *
 * The top floor is the book as `BookHistory` draws it — what was put to work
 * against what it is worth, the gap between them green or red — and the bottom
 * one the rates as `ReturnLines` draws them, read off the right-hand axis.
 * Stacked with no gap rather than overlaid on a second y-axis: overlaid, a
 * percentage line crosses the value line wherever the two scales happen to
 * put it, a meaningless point that reads as an event. Stacked, the same
 * vertical rules (each month in a short window, each January in a long one)
 * run through both floors, so a dip in the rates sits under the deposit and
 * the fall that caused it. The pointer reads the same month off both floors
 * into one box: value, money put in, the gain between them, and each rate.
 *
 * `bars`, when given, stand on the rates' floor under the lines, one per
 * point from zero: a figure that is that point's own (the month's return)
 * next to rates that run from the first trade, on the same percentage axis.
 */
type BookAndRatesProps = {
  points: BookRatePoint[];
  series: ReturnSeries[];
  bars?: RateBars;
  labels: {
    invested: string;
    /** The value line on its own, for the change between two points. */
    value: string;
    profit: string;
    loss: string;
    gain: string;
  };
  money: (value: number, signed?: boolean) => string;
  /** Compact formatter for the money gutter; falls back to `money`. */
  axisMoney?: (value: number) => string;
  /** The rates' formatter, for their gutter and the box. */
  format: (value: number) => string;
  formatDate: (iso: string) => string;
};

type BookRateDay = BookRatePoint & { value: number; invested: number };

export function BookAndRates({ points, ...rest }: BookAndRatesProps) {
  // Both legs or the month is not comparable, as on the history chart. Split
  // from the drawing so the measured frame exists whenever the chart does.
  const book = points.filter(
    (point): point is BookRateDay => point.value !== null && point.invested !== null,
  );
  if (book.length < 2 || book.length !== points.length) return null;
  return <BookAndRatesPlot book={book} {...rest} />;
}

function BookAndRatesPlot({
  book,
  series,
  bars,
  labels,
  money,
  axisMoney,
  format,
  formatDate,
}: Omit<BookAndRatesProps, "points"> & { book: BookRateDay[] }) {
  const [pointer, setHover] = useState<number | null>(null);
  // Two points being compared (`useSpan`), in date order.
  const [measure, setMeasure] = useState<{ from: number; to: number } | null>(null);
  const [frame, width] = useWidth(BARS.fallback);
  const svg = useRef<SVGSVGElement>(null);
  const drop = useCallback(() => {
    setHover(null);
    setMeasure(null);
  }, []);
  useTouchHold(svg, pointer !== null || measure !== null, drop);
  // A shorter window can arrive under a pointer still resting on the old one,
  // or under a comparison drawn on it.
  const hover = pointer !== null && pointer < book.length && !measure ? pointer : null;
  const compared = measure && measure.to < book.length ? measure : null;

  const narrow = width < NARROW;
  const left = narrow ? NARROW_PAD : FLOORS.left;
  const right = narrow ? NARROW_PAD : FLOORS.right;
  const plotW = width - left - right;
  const moneyTop = FLOORS.top;
  // The desktop floors' total, and a squarer one on a phone, split in the
  // desktop's own proportion.
  const floors = FLOORS.money + FLOORS.rates;
  const height = plotHeightFor(width, FLOORS.top + floors + FLOORS.bottom);
  const room = height - FLOORS.top - FLOORS.bottom;
  const moneyH = Math.round((room * FLOORS.money) / floors);
  const ratesH = room - moneyH;
  const ratesTop = moneyTop + moneyH;
  const bottom = ratesTop + ratesH;
  const x = (index: number) => left + (index / (book.length - 1)) * plotW;

  const levels = book.flatMap((point) => [point.value, point.invested]);
  const rawLow = Math.min(...levels);
  const rawHigh = Math.max(...levels);
  const pad = (rawHigh - rawLow) * 0.04 || Math.abs(rawHigh) * 0.04 || 1;
  const moneyLow = rawLow - pad;
  const moneySpan = rawHigh + pad - moneyLow;
  const yMoney = (value: number) =>
    moneyTop + (1 - (value - moneyLow) / moneySpan) * moneyH;

  const drawn = series.filter((one) => one.points.some((v) => v !== null));
  const barred = bars?.points.some((v) => v !== null) ? bars : undefined;
  const rates = [
    ...drawn.flatMap((one) => one.points),
    ...(barred?.points ?? []),
  ].filter((v): v is number => v !== null);
  // Zero stays on the rates' axis, as on every return chart here.
  const rateLow = Math.min(0, ...rates);
  const rateSpan = Math.max(0, ...rates) - rateLow || 1;
  const rateH = ratesH - 2 * FLOORS.inset;
  const yRate = (value: number) =>
    ratesTop + FLOORS.inset + (1 - (value - rateLow) / rateSpan) * rateH;

  const ramp = categorical();
  const colored = drawn.map((one, index) => ({
    ...one,
    color: one.color ?? ramp[index % ramp.length]!,
  }));
  /** Contiguous runs of a rate line, so a month without a rate breaks it. */
  const runs = (values: (number | null)[]) => {
    const out: string[] = [];
    let run: string[] = [];
    values.forEach((value, index) => {
      if (value === null) {
        if (run.length > 1) out.push(`M${run.join("L")}`);
        run = [];
        return;
      }
      run.push(`${x(index)},${yRate(value)}`);
    });
    if (run.length > 1) out.push(`M${run.join("L")}`);
    return out;
  };

  const bands = gainBands(
    book.map((point) => ({ value: point.value, base: point.invested })),
    x,
    yMoney,
  );
  const upColor = token("up");
  const downColor = token("down");
  const anyGain = book.some((point) => point.value >= point.invested);
  const anyLoss = book.some((point) => point.value < point.invested);
  const ticks = [0, Math.floor(book.length / 2), book.length - 1];
  // The rules both floors share: every month while there are few enough to
  // tell apart, each January once there are not.
  const rules = book
    .map((point, index) => ({ index, month: point.date.slice(5, 7) }))
    .filter(({ index, month }) =>
      book.length <= 13 ? index > 0 && index < book.length - 1 : month === "01",
    )
    .map(({ index }) => index);
  const hovered = hover === null ? null : book[hover]!;
  const track = (event: PointerEvent<SVGSVGElement>) => {
    const at = viewX(event, svg.current, width);
    if (at !== null) setHover(nearest(at, left, plotW, book.length));
  };
  /** Where a pointer is on the SVG, in viewBox x. */
  const xAt = (event: MouseEvent<SVGSVGElement>) =>
    viewX(event, svg.current, width) ?? left;
  const spanned = useSpan((pair) => {
    if (!pair) return setMeasure(null);
    const [a, b] = pair.map((at) => nearest(at, left, plotW, book.length)) as [
      number,
      number,
    ];
    setHover(null);
    setMeasure({ from: Math.min(a, b), to: Math.max(a, b) });
  });
  const leg = (point: (typeof book)[number]) => ({
    value: point.value,
    injected: point.invested,
  });

  const tipRows = (index: number, point: (typeof book)[number]): TipRow[] =>
    bookRatesTip(index, point, {
      labels,
      money,
      format,
      series: colored,
      bars: barred,
    });
  // A bar per point, centred on its date, thin enough that the first and the
  // last stay clear of the gutters' labels.
  const barUp = token("candle-up");
  const barDown = token("candle-down");
  const barW = Math.max(1, Math.min(10, (plotW / (book.length - 1)) * 0.6));

  return (
    <div className="pf-chart">
      <Legend>
        <li className="pf-legend-row">
          <span
            className="pf-swatch pf-swatch-dashed"
            style={{ background: token("text-muted") }}
          />
          <span>{labels.invested}</span>
        </li>
        {anyGain ? (
          <li className="pf-legend-row">
            <span className="pf-swatch" style={{ background: upColor }} />
            <span>{labels.profit}</span>
          </li>
        ) : null}
        {anyLoss ? (
          <li className="pf-legend-row">
            <span className="pf-swatch" style={{ background: downColor }} />
            <span>{labels.loss}</span>
          </li>
        ) : null}
        {barred ? (
          <li className="pf-legend-row">
            <span
              className="pf-swatch"
              style={{
                background: `linear-gradient(90deg, ${barUp} 50%, ${barDown} 50%)`,
              }}
            />
            <span>{barred.label}</span>
          </li>
        ) : null}
        {colored.map((one) => (
          <li className="pf-legend-row" key={one.label}>
            <span
              className={one.dashed ? "pf-swatch pf-swatch-dashed" : "pf-swatch"}
              style={{ background: one.color }}
            />
            <span>{one.label}</span>
          </li>
        ))}
      </Legend>
      <div className="pf-plot pf-scrub" ref={frame}>
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          onPointerMove={(event) => {
            if (!spanned.move(event, xAt(event))) track(event);
          }}
          // A tap is a pointer that never moves: it answers too, on a phone.
          onPointerDown={(event) => {
            if (!spanned.down(event, xAt(event))) track(event);
          }}
          onPointerUp={spanned.up}
          onPointerLeave={(event) => {
            spanned.leave(event);
            if (event.pointerType !== "touch") setHover(null);
          }}
          onPointerCancel={spanned.cancel}
          onContextMenu={(event) => spanned.menu?.(event, xAt(event))}
        >
          {rules.map((index) => (
            <line
              key={`rule-${index}`}
              x1={x(index)}
              x2={x(index)}
              y1={moneyTop}
              y2={bottom}
              stroke={token("rule-soft")}
              strokeWidth="1"
            />
          ))}
          <ValueAxis
            ticks={niceTicks(moneyLow, moneyLow + moneySpan, narrow ? 3 : 4)}
            y={yMoney}
            left={left}
            right={width - right}
            format={axisMoney ?? ((value) => money(value))}
            inside={narrow}
            top={moneyTop}
          />
          {bands.map((band, index) => (
            <path
              key={index}
              d={band.path}
              fill={band.gain ? token("profit-band") : token("loss-band")}
            />
          ))}
          <polyline
            points={book
              .map((point, i) => `${x(i)},${yMoney(point.invested)}`)
              .join(" ")}
            fill="none"
            stroke={token("text-muted")}
            strokeWidth="1.5"
            strokeDasharray="4 3"
          />
          {bands.map((band, index) => (
            <polyline
              key={`value-${index}`}
              points={band.value}
              fill="none"
              stroke={band.gain ? upColor : downColor}
              strokeWidth="2"
            />
          ))}

          {/* The seam: where money's floor ends and the rates' begins. */}
          <line
            x1={left}
            x2={width - right}
            y1={ratesTop}
            y2={ratesTop}
            stroke={token("border")}
            strokeWidth="1"
          />
          <ValueAxis
            ticks={niceTicks(rateLow, rateLow + rateSpan, narrow ? 2 : 3).filter(
              (tick) => tick !== 0,
            )}
            y={yRate}
            left={left}
            right={width - right}
            format={format}
            side="right"
            inside={narrow}
            top={ratesTop}
          />
          {barred?.points.map((value, index) =>
            value === null ? null : (
              <rect
                key={`bar-${index}`}
                className="pf-rate-bar"
                x={x(index) - barW / 2}
                y={Math.min(yRate(0), yRate(value))}
                width={barW}
                height={Math.max(1, Math.abs(yRate(value) - yRate(0)))}
                fill={value >= 0 ? barUp : barDown}
                fillOpacity={hover === null || hover === index ? 0.7 : 0.4}
              />
            ),
          )}
          <line
            x1={left}
            x2={width - right}
            y1={yRate(0)}
            y2={yRate(0)}
            stroke={token("border")}
            strokeWidth="1"
            strokeDasharray="2 3"
          />
          <AxisLabel
            text={format(0)}
            at={yRate(0)}
            left={left}
            right={width - right}
            side="right"
            inside={narrow}
            top={ratesTop}
          />
          {colored.map((one) =>
            runs(one.points).map((d, index) => (
              <path
                key={`${one.label}-${index}`}
                d={d}
                fill="none"
                stroke={one.color}
                strokeWidth="1.5"
                strokeDasharray={one.dashed ? "4 3" : undefined}
              />
            )),
          )}

          {compared ? (
            <g className="pf-span" pointerEvents="none">
              {compared.to > compared.from ? (
                <rect
                  x={x(compared.from)}
                  y={moneyTop}
                  width={x(compared.to) - x(compared.from)}
                  height={bottom - moneyTop}
                />
              ) : null}
              {[compared.from, compared.to].map((index, at) => (
                <line key={at} x1={x(index)} x2={x(index)} y1={moneyTop} y2={bottom} />
              ))}
            </g>
          ) : null}
          {hovered && hover !== null ? (
            <g pointerEvents="none">
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={moneyTop}
                y2={bottom}
                stroke={token("text-faint")}
                strokeDasharray="2 2"
              />
              <circle
                cx={x(hover)}
                cy={yMoney(hovered.value)}
                r="3"
                fill={hovered.value >= hovered.invested ? upColor : downColor}
              />
              {colored.map((one) => {
                const value = one.points[hover];
                return value === null || value === undefined ? null : (
                  <circle
                    key={one.label}
                    cx={x(hover)}
                    cy={yRate(value)}
                    r="3"
                    fill={one.color}
                  />
                );
              })}
            </g>
          ) : null}
          {ticks.map((index) => (
            <text
              key={index}
              x={x(index)}
              y={height - 6}
              fill={token("text-muted")}
              fontSize="11"
              textAnchor={
                index === 0 ? "start" : index === book.length - 1 ? "end" : "middle"
              }
            >
              {formatDate(book[index]!.date)}
            </text>
          ))}
        </svg>
        {compared && compared.to > compared.from ? (
          <ChartTip
            x={(x(compared.from) + x(compared.to)) / 2}
            width={width}
            title={`${formatDate(book[compared.from]!.date)} → ${formatDate(book[compared.to]!.date)}`}
            rows={bookSpanTip(
              leg(book[compared.from]!),
              leg(book[compared.to]!),
              { value: labels.value, injected: labels.invested, pnl: labels.gain },
              money,
            )}
          />
        ) : hovered && hover !== null ? (
          <ChartTip
            x={x(hover)}
            width={width}
            title={formatDate(hovered.date)}
            rows={tipRows(hover, hovered)}
          />
        ) : null}
      </div>
    </div>
  );
}
