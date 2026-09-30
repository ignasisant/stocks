/**
 * The page's three pictures, drawn as SVG and CSS from design tokens.
 *
 * The Streamlit page draws these in Plotly; this bundle has no Plotly and is
 * not getting one, so what survives is mostly the reading: an allocation donut
 * with its percentages on the legend, a correlation grid on the same diverging
 * ramp with its −1…+1 scale under it, the realized-result bars with the net as
 * a diamond over them, and value axes on all three. Plotly's two interactions
 * come across: drag-to-zoom with a refitted axis on the book's history, and
 * `hovermode="x"` — a pointer anywhere across the plot reads the nearest day
 * (or bar) off one overlay, with a crosshair and a styled box (`ChartTip`).
 *
 * Colours come from `token()` — the `--ag-*` custom properties the server
 * inlines — so these agree with the Streamlit charts and with both themes.
 */

import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent,
} from "react";
import { token } from "../../shell/theme";
import type { TaxPeriod } from "./api";

/**
 * The DS categorical ramp, in `ds.py`'s order and minus its one unpublished
 * hue (chart magenta is not in `tokens()`), so slice colours line up with the
 * Streamlit donuts for as far as the published palette goes.
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
 * Plotly picks these for the Streamlit charts; a hand-drawn chart has to. The
 * step is the 1-2-5 ladder scaled to the span, so a €12k book reads 10k/11k/12k
 * and not 11,843/12,261, and every label lands inside the plot.
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
}: {
  ticks: number[];
  y: (value: number) => number;
  left: number;
  right: number;
  format: (value: number) => string;
  side?: "left" | "right";
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
          <text
            x={side === "left" ? left - 6 : right + 6}
            y={y(tick) + 4}
            fill={token("text-muted")}
            fontSize="11"
            textAnchor={side === "left" ? "end" : "start"}
          >
            {format(tick)}
          </text>
        </g>
      ))}
    </g>
  );
}

/** One row of a chart's hover box: the series' swatch, its name, its figure. */
export type TipRow = { label: string; value: string; color?: string };

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
}: {
  /** Anchor, in viewBox units. */
  x: number;
  width: number;
  title: string;
  rows: TipRow[];
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
  return (
    <div
      ref={box}
      className={left > 55 ? "pf-tip pf-tip-flip" : "pf-tip"}
      style={{ left: `${left}%` }}
      role="status"
    >
      <span className="pf-tip-title">{title}</span>
      {rows.map((row) => (
        <span className="pf-tip-row" key={row.label}>
          {row.color ? (
            <span className="pf-tip-swatch" style={{ background: row.color }} />
          ) : null}
          <span className="pf-muted">{row.label}</span>
          <strong>{row.value}</strong>
        </span>
      ))}
    </div>
  );
}

/** Where a pointer sits on an SVG, in its viewBox's x units. */
function viewX(event: PointerEvent<Element>, svg: SVGSVGElement | null, width: number) {
  const box = svg?.getBoundingClientRect();
  if (!box || !box.width) return null;
  return ((event.clientX - box.left) / box.width) * width;
}

/** The nearest of `count` evenly spaced points to viewBox x `at`. */
function nearest(at: number, left: number, plotW: number, count: number): number {
  const index = Math.round(((at - left) / plotW) * (count - 1));
  return Math.max(0, Math.min(count - 1, index));
}

export type Slice = { label: string; weight: number };

/**
 * Allocation as a donut, percentages on the legend rather than the slices.
 *
 * Sliver slices under ~1% printed their labels on top of each other, which is
 * why the original moved them out too. More buckets than the palette has hues
 * folds the tail into one muted "Others" slice, never a cycled colour.
 */
export function Donut({
  title,
  slices,
  otherLabel,
  format,
}: {
  title: string;
  slices: Slice[];
  otherLabel: string;
  format: (fraction: number) => string;
}) {
  const colors = categorical();
  const total = slices.reduce((sum, slice) => sum + slice.weight, 0);
  if (!(total > 0)) return null;

  const sorted = [...slices].sort((a, b) => b.weight - a.weight);
  const shown =
    sorted.length > colors.length
      ? [
          ...sorted.slice(0, colors.length - 1),
          {
            label: otherLabel,
            weight: sorted
              .slice(colors.length - 1)
              .reduce((sum, slice) => sum + slice.weight, 0),
          },
        ]
      : sorted;
  const palette =
    sorted.length > colors.length
      ? [...colors.slice(0, colors.length - 1), token("text-faint")]
      : colors;

  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="pf-donut">
      <h3>{title}</h3>
      <svg viewBox="0 0 100 100" role="img" aria-label={title}>
        {shown.map((slice, index) => {
          const fraction = slice.weight / total;
          const length = fraction * circumference;
          // A 1px surface gap so adjacent fills never touch, dropped when the
          // slice is too thin to spare it.
          const drawn = length > 2 ? length - 1 : length;
          const start = offset;
          offset += length;
          return (
            <circle
              key={slice.label}
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke={palette[index % palette.length] ?? token("text-faint")}
              strokeWidth="15"
              strokeDasharray={`${drawn} ${circumference - drawn}`}
              strokeDashoffset={-start}
              transform="rotate(-90 50 50)"
            >
              <title>{`${slice.label} · ${format(fraction)}`}</title>
            </circle>
          );
        })}
      </svg>
      <ul className="pf-legend">
        {shown.map((slice, index) => (
          <li className="pf-legend-row" key={slice.label}>
            <span
              className="pf-swatch"
              style={{ background: palette[index % palette.length] }}
            />
            <span>
              {slice.label} · {format(slice.weight / total)}
            </span>
          </li>
        ))}
      </ul>
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

/**
 * Pairwise return correlation as a grid of squares.
 *
 * A pair the API had no overlap for is absent from the matrix rather than 0 —
 * an uncorrelated pair and an unmeasurable one are not the same reading — so
 * those cells are left blank instead of painted at the neutral stop.
 */
export function Heatmap({
  matrix,
  format,
}: {
  matrix: Record<string, Record<string, number>>;
  format: (value: number) => string;
}) {
  const names = Object.keys(matrix);
  if (!names.length) return null;
  return (
    <div className="pf-scroll">
      <div
        className="pf-heat"
        style={{
          gridTemplateColumns: `auto repeat(${names.length}, minmax(1.5rem, 1fr))`,
        }}
      >
        <span />
        {names.map((name) => (
          <span className="pf-heat-col" key={`head-${name}`}>
            {name}
          </span>
        ))}
        {names.map((row) => (
          <Fragment key={row}>
            <span className="pf-heat-label">{row}</span>
            {names.map((column) => {
              const value = matrix[row]?.[column];
              return (
                <span
                  className="pf-heat-cell"
                  key={`${row}-${column}`}
                  style={{
                    background:
                      value === undefined ? "transparent" : correlationColor(value),
                  }}
                  title={
                    value === undefined
                      ? `${row} × ${column}`
                      : `${row} × ${column} — ${format(value)}`
                  }
                />
              );
            })}
          </Fragment>
        ))}
      </div>
      <HeatLegend format={format} />
    </div>
  );
}

/**
 * The colour scale under the grid, −1 to +1 — Plotly's colorbar, flattened.
 *
 * Without it the ramp is a guess: nothing on the grid says whether the deep
 * end is "moves together" or "moves apart". Drawn from the same
 * `correlationColor` the cells use, so the two cannot disagree.
 */
function HeatLegend({ format }: { format: (value: number) => string }) {
  const stops = [-1, -0.5, 0, 0.5, 1];
  return (
    <div className="pf-heat-legend" aria-hidden="true">
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
 * not only over a bar thick enough to aim at.
 */
export function PeriodBars({
  periods,
  labels,
  money,
  axisMoney,
}: {
  periods: TaxPeriod[];
  labels: { gains: string; losses: string; recovered: string; net: string };
  money: (value: number) => string;
  /** Compact formatter for the gutter; falls back to `money` when omitted. */
  axisMoney?: (value: number) => string;
}) {
  const gutter = axisMoney ?? money;
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  if (!periods.length) return null;

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

  const width = 720;
  const height = 240;
  const left = PLOT.left;
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
  // — a monthly run is easily sixty periods long.
  const step = Math.max(1, Math.ceil(periods.length / 14));

  const legend: [string, string][] = [
    [labels.gains, up],
    [labels.losses, down],
    ...(anyRecovered
      ? ([[labels.recovered, recoveredColor]] as [string, string][])
      : []),
    [labels.net, netColor],
  ];

  const at = hover === null ? null : periods[hover];

  return (
    <div className="pf-chart">
      <ul className="pf-legend-inline">
        {legend.map(([label, color]) => (
          <li className="pf-legend-row" key={label}>
            <span className="pf-swatch" style={{ background: color }} />
            <span>{label}</span>
          </li>
        ))}
      </ul>
      <div className="pf-plot">
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          onPointerMove={(event) => {
            const x = viewX(event, svg.current, width);
            if (x === null) return;
            const index = Math.floor((x - left) / slot);
            setHover(Math.max(0, Math.min(periods.length - 1, index)));
          }}
          onPointerLeave={() => setHover(null)}
        >
          <ValueAxis
            ticks={niceTicks(-maxDown, maxUp).filter((tick) => tick !== 0)}
            y={y}
            left={left}
            right={width - PLOT.right}
            format={gutter}
          />
          <text x={left - 6} y={zero + 4} fill={text} fontSize="11" textAnchor="end">
            {gutter(0)}
          </text>
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
                    x={centre}
                    y={height - 6}
                    fill={text}
                    fontSize="11"
                    textAnchor="middle"
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
            ]}
          />
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

/** Where the plot sits inside the 720-wide viewBox; the left gutter holds the value axis. */
const PLOT = { width: 720, height: 300, top: 8, right: 8, bottom: 24, left: 64 };

/**
 * Several cumulative-return lines on one axis, rebased to the window.
 *
 * The comparison the Streamlit page draws in Plotly: what the account earned,
 * what today's holdings would have earned over the same window, and what each
 * benchmark did. Percentages against a zero line — the axis every one of them
 * starts from — so the question "did I beat it" is answered by which line is
 * higher, not by reading two scales. The value axis carries its percentages,
 * as Plotly's `%` axis does, so "how much higher" is readable too.
 *
 * The basket's line is dotted on purpose: it is a backtest of holdings that
 * have not been held that way all along, and drawing it like a record would
 * make it read as one.
 */
export function ReturnLines({
  dates,
  series,
  format,
  formatDate,
  bands = [],
  marker,
}: {
  dates: string[];
  series: ReturnSeries[];
  format: (value: number) => string;
  formatDate: (iso: string) => string;
  /** Shaded ranges drawn under the lines, widest first. */
  bands?: ReturnBand[];
  /** A labelled vertical rule at one index — "today" between a record and a
      projection. */
  marker?: { index: number; label: string };
}) {
  const [pointer, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drawn = series.filter((one) => one.points.some((v) => v !== null));
  if (dates.length < 2 || !drawn.length) return null;
  // A shorter window can arrive under a pointer still resting on the old one.
  const hover = pointer !== null && pointer < dates.length ? pointer : null;

  const { width, height } = PLOT;
  const plotW = width - PLOT.left - PLOT.right;
  const plotH = height - PLOT.top - PLOT.bottom;

  const values = [
    ...drawn.flatMap((one) => one.points),
    ...bands.flatMap((band) => [...band.low, ...band.high]),
  ].filter((v): v is number => v !== null);
  // Zero is always on the axis: a chart of returns that crops it hides whether
  // the line is above water, which is the first thing anybody reads off it.
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const span = high - low || 1;
  const x = (index: number) => PLOT.left + (index / (dates.length - 1)) * plotW;
  const y = (value: number) => PLOT.top + (1 - (value - low) / span) * plotH;

  const ramp = categorical();
  const colored = drawn.map((one, index) => ({
    ...one,
    color: one.color ?? ramp[index % ramp.length]!,
  }));

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

  const ticks = [0, Math.floor(dates.length / 2), dates.length - 1];

  return (
    <div className="pf-chart">
      <ul className="pf-legend-inline">
        {colored
          .filter((one) => !one.tipOnly)
          .map((one) => (
            <li className="pf-legend-row" key={one.label}>
              <span
                className={one.dashed ? "pf-swatch pf-swatch-dashed" : "pf-swatch"}
                style={{ background: one.color }}
              />
              <span>{one.label}</span>
            </li>
          ))}
        {bands.map((band) => (
          <li className="pf-legend-row" key={band.label}>
            <span className="pf-swatch" style={{ background: band.color }} />
            <span>{band.label}</span>
          </li>
        ))}
      </ul>
      <div className="pf-plot">
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          onPointerMove={(event) => {
            const at = viewX(event, svg.current, width);
            if (at !== null) setHover(nearest(at, PLOT.left, plotW, dates.length));
          }}
          onPointerLeave={() => setHover(null)}
        >
          <ValueAxis
            ticks={niceTicks(low, high).filter((tick) => tick !== 0)}
            y={y}
            left={PLOT.left}
            right={width - PLOT.right}
            format={format}
          />
          <line
            x1={PLOT.left}
            x2={width - PLOT.right}
            y1={y(0)}
            y2={y(0)}
            stroke={token("border")}
            strokeWidth="1"
          />
          <text
            x={PLOT.left - 6}
            y={y(0) + 4}
            fill={token("text-muted")}
            fontSize="11"
            textAnchor="end"
          >
            {format(0)}
          </text>
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
                y1={PLOT.top}
                y2={PLOT.top + plotH}
                stroke={token("border")}
                strokeWidth="1"
              />
              <text
                x={x(marker.index) + 4}
                y={PLOT.top + 11}
                fill={token("text-muted")}
                fontSize="11"
              >
                {marker.label}
              </text>
            </g>
          ) : null}
          {colored
            .filter((one) => !one.tipOnly)
            .map((one) =>
              paths(one.points).map((d, index) => (
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
          {/* Plotly's `hovermode="x"`: the whole plot answers, nearest day by
            the pointer's x, with a crosshair and a dot on every line there. */}
          {hover === null ? null : (
            <g pointerEvents="none">
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={PLOT.top}
                y2={PLOT.top + plotH}
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
                    r="3"
                    fill={one.color}
                  />
                );
              })}
            </g>
          )}
          {ticks.map((index) => (
            <text
              key={index}
              x={x(index)}
              y={height - 6}
              fill={token("text-muted")}
              fontSize="11"
              textAnchor={
                index === 0 ? "start" : index === dates.length - 1 ? "end" : "middle"
              }
            >
              {formatDate(dates[index]!)}
            </text>
          ))}
        </svg>
        {hover === null ? null : (
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
              };
            })}
          />
        )}
      </div>
    </div>
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
 * went in, red below — as the Streamlit trace is: the overlapping point keeps
 * the two colours joined.
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
 * Injected capital against market value, one point per day.
 *
 * The Streamlit page draws this in Plotly with a band between the two lines,
 * green where the book is worth more than what went into it and red where it
 * is not. That band is the reading — the gap is the profit, and its colour is
 * the answer to "am I up?" before any number is read.
 *
 * Built as one polygon per contiguous stretch of the same sign rather than as
 * one shape clipped twice: a fill that crosses the crossover point would paint
 * the wrong colour on one side of it, and the crossover is exactly the day a
 * reader is looking for.
 *
 * Plotly's two interactions come across. Drag across the plot to zoom into
 * those days, with the value axis refitted to them — the Streamlit page's
 * y-refit, since a €40k book's March wobble is invisible on an axis sized for
 * its whole life. Double-click, or the reset button, puts the window back.
 * The tooltip carries what Plotly's did: value, injected, and the P/L between
 * them as an amount and a percentage.
 */
export function BookHistory({
  points,
  labels,
  money,
  axisMoney,
  percent,
  formatDate,
}: {
  points: BookPoint[];
  labels: {
    injected: string;
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
}) {
  const gutter = axisMoney ?? ((value: number) => money(value));
  // Both legs present or the day is not comparable: a value without its
  // reference line cannot be shaded against anything.
  const all = points.filter(
    (point): point is BookPoint & { injected: number; value: number } =>
      point.injected !== null && point.value !== null,
  );
  const [zoom, setZoom] = useState<{ from: number; to: number } | null>(null);
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  // A new window from the server is a new series: yesterday's zoom indexes
  // into days that are no longer the same days.
  const first = all[0]?.date;
  const last = all[all.length - 1]?.date;
  useEffect(() => {
    setZoom(null);
    setDrag(null);
    setHover(null);
  }, [first, last, all.length]);

  if (all.length < 2) return null;

  const days = zoom ? all.slice(zoom.from, zoom.to + 1) : all;
  const { width, height } = PLOT;
  const plotW = width - PLOT.left - PLOT.right;
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
  const x = (index: number) => PLOT.left + (index / (days.length - 1)) * plotW;
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

  /** Which visible day a pointer is over, from its position on the SVG. */
  const dayAt = (event: PointerEvent<SVGSVGElement>) => {
    const at = viewX(event, svg.current, width);
    return at === null ? 0 : nearest(at, PLOT.left, plotW, days.length);
  };

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
        <ul className="pf-legend-inline">
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
        </ul>
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
      <div className="pf-plot">
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          className="pf-zoomable"
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            const at = dayAt(event);
            setDrag({ from: at, to: at });
          }}
          onPointerMove={(event) => {
            const at = dayAt(event);
            setHover(at);
            if (drag) setDrag({ ...drag, to: at });
          }}
          onPointerUp={finish}
          onPointerLeave={() => {
            setHover(null);
            finish();
          }}
          onDoubleClick={() => setZoom(null)}
        >
          <ValueAxis
            ticks={niceTicks(low, high)}
            y={y}
            left={PLOT.left}
            right={width - PLOT.right}
            format={gutter}
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
          {hovered && hover !== null ? (
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
              x={Math.min(Math.max(x(index), PLOT.left + 24), width - 24)}
              y={height - 6}
              textAnchor="middle"
              fontSize="11"
              fill={token("text-muted")}
            >
              {formatDate(days[index]!.date)}
            </text>
          ))}
        </svg>
        {hovered && hover !== null && !drag ? (
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

/** The two floors inside the 720-wide viewBox: money over rates with no gap
    between them, one date axis under both, money's gutter on the left and the
    rates' on the right. `inset` keeps a rate line off the seam. */
const FLOORS = {
  width: 720,
  left: 64,
  right: 52,
  top: 8,
  money: 200,
  rates: 130,
  inset: 8,
  bottom: 24,
};

export type BookRatePoint = {
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
export function BookAndRates({
  points,
  series,
  bars,
  labels,
  money,
  axisMoney,
  format,
  formatDate,
}: {
  points: BookRatePoint[];
  series: ReturnSeries[];
  bars?: RateBars;
  labels: { invested: string; profit: string; loss: string; gain: string };
  money: (value: number, signed?: boolean) => string;
  /** Compact formatter for the money gutter; falls back to `money`. */
  axisMoney?: (value: number) => string;
  /** The rates' formatter, for their gutter and the box. */
  format: (value: number) => string;
  formatDate: (iso: string) => string;
}) {
  const [pointer, setHover] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  // Both legs or the month is not comparable, as on the history chart.
  const book = points.filter(
    (point): point is BookRatePoint & { value: number; invested: number } =>
      point.value !== null && point.invested !== null,
  );
  if (book.length < 2 || book.length !== points.length) return null;
  // A shorter window can arrive under a pointer still resting on the old one.
  const hover = pointer !== null && pointer < book.length ? pointer : null;

  const { width, left, right } = FLOORS;
  const plotW = width - left - right;
  const moneyTop = FLOORS.top;
  const ratesTop = moneyTop + FLOORS.money;
  const bottom = ratesTop + FLOORS.rates;
  const height = bottom + FLOORS.bottom;
  const x = (index: number) => left + (index / (book.length - 1)) * plotW;

  const levels = book.flatMap((point) => [point.value, point.invested]);
  const rawLow = Math.min(...levels);
  const rawHigh = Math.max(...levels);
  const pad = (rawHigh - rawLow) * 0.04 || Math.abs(rawHigh) * 0.04 || 1;
  const moneyLow = rawLow - pad;
  const moneySpan = rawHigh + pad - moneyLow;
  const yMoney = (value: number) =>
    moneyTop + (1 - (value - moneyLow) / moneySpan) * FLOORS.money;

  const drawn = series.filter((one) => one.points.some((v) => v !== null));
  const barred = bars?.points.some((v) => v !== null) ? bars : undefined;
  const rates = [
    ...drawn.flatMap((one) => one.points),
    ...(barred?.points ?? []),
  ].filter((v): v is number => v !== null);
  // Zero stays on the rates' axis, as on every return chart here.
  const rateLow = Math.min(0, ...rates);
  const rateSpan = Math.max(0, ...rates) - rateLow || 1;
  const rateH = FLOORS.rates - 2 * FLOORS.inset;
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
      <ul className="pf-legend-inline">
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
      </ul>
      <div className="pf-plot">
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          onPointerMove={(event) => {
            const at = viewX(event, svg.current, width);
            if (at !== null) setHover(nearest(at, left, plotW, book.length));
          }}
          onPointerLeave={() => setHover(null)}
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
            ticks={niceTicks(moneyLow, moneyLow + moneySpan)}
            y={yMoney}
            left={left}
            right={width - right}
            format={axisMoney ?? ((value) => money(value))}
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
            ticks={niceTicks(rateLow, rateLow + rateSpan, 3).filter(
              (tick) => tick !== 0,
            )}
            y={yRate}
            left={left}
            right={width - right}
            format={format}
            side="right"
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
          <text
            x={width - right + 6}
            y={yRate(0) + 4}
            fill={token("text-muted")}
            fontSize="11"
            textAnchor="start"
          >
            {format(0)}
          </text>
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
        {hovered && hover !== null ? (
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
