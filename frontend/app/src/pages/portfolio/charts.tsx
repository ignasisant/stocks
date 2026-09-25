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

import { Fragment, useEffect, useRef, useState, type PointerEvent } from "react";
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

/** The value axis: faint gridlines with their labels, right-aligned in the gutter. */
function ValueAxis({
  ticks,
  y,
  left,
  right,
  format,
}: {
  ticks: number[];
  y: (value: number) => number;
  left: number;
  right: number;
  format: (value: number) => string;
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
            x={left - 6}
            y={y(tick) + 4}
            fill={token("text-muted")}
            fontSize="11"
            textAnchor="end"
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
 * flipped to the pointer's left past the middle so it never leaves the card.
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
  return (
    <div
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
}: {
  periods: TaxPeriod[];
  labels: { gains: string; losses: string; recovered: string; net: string };
  money: (value: number) => string;
}) {
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
            format={money}
          />
          <text x={left - 6} y={zero + 4} fill={text} fontSize="11" textAnchor="end">
            {money(0)}
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
}: {
  dates: string[];
  series: ReturnSeries[];
  format: (value: number) => string;
  formatDate: (iso: string) => string;
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

  const values = drawn.flatMap((one) =>
    one.points.filter((v): v is number => v !== null),
  );
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

  const ticks = [0, Math.floor(dates.length / 2), dates.length - 1];

  return (
    <div className="pf-chart">
      <ul className="pf-legend-inline">
        {colored.map((one) => (
          <li className="pf-legend-row" key={one.label}>
            <span className="pf-swatch" style={{ background: one.color }} />
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
          {colored.map((one) =>
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
                value: value === null || value === undefined ? "—" : format(value),
                color: one.color,
              };
            })}
          />
        )}
      </div>
    </div>
  );
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
  percent: (value: number) => string;
  formatDate: (iso: string) => string;
}) {
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

  // Contiguous runs of one sign, each closed into its own polygon. A run is
  // extended by one point on each side so neighbouring bands meet instead of
  // leaving a seam at the crossover. The value line is cut on the same runs
  // and coloured by them — green above what went in, red below — as the
  // Streamlit trace is: the overlapping point keeps the two colours joined.
  const bands: { gain: boolean; path: string; value: string }[] = [];
  let start = 0;
  for (let index = 1; index <= days.length; index += 1) {
    const ending = index === days.length;
    const gain = days[start]!.value >= days[start]!.injected;
    const same = !ending && days[index]!.value >= days[index]!.injected === gain;
    if (same) continue;
    const run = days.slice(start, Math.min(index + 1, days.length));
    const offset = start;
    const top = run.map((day, i) => `${x(offset + i)},${y(day.value)}`);
    const bottom = run.map((day, i) => `${x(offset + i)},${y(day.injected)}`).reverse();
    bands.push({
      gain,
      path: `M${top.join("L")}L${bottom.join("L")}Z`,
      value: top.join(" "),
    });
    start = ending ? start : index;
  }

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
            format={(value) => money(value)}
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
