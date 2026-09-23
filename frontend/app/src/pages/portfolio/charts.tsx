/**
 * The page's three pictures, drawn as SVG and CSS from design tokens.
 *
 * The Streamlit page draws these in Plotly; this bundle has no Plotly and is
 * not getting one, so what survives is the reading and not the interaction:
 * an allocation donut with its percentages on the legend, a correlation grid
 * on the same diverging ramp, and the realized-result bars with the net as a
 * diamond over them. Hover text rides the SVG `<title>`, so every figure a
 * tooltip used to carry is still reachable, just not styled.
 *
 * Colours come from `token()` — the `--ag-*` custom properties the server
 * inlines — so these agree with the Streamlit charts and with both themes.
 */

import { Fragment } from "react";
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
  if (names.length < 2) return null;
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
    </div>
  );
}

/**
 * The realized result per period: gains stack up, deductible losses (and any
 * recovered from an earlier deferral) stack down, and the diamond marks the
 * net the brackets then tax.
 *
 * Kept deliberately plain — no axis ticks, no grid. The figures live in the
 * KPI tiles and the table under this chart; what the picture is for is the
 * shape of the years against each other.
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
  const footer = 22;
  const plot = height - footer;
  const scale = plot / span;
  const zero = maxUp * scale;
  const slot = width / periods.length;
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
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img">
        <line x1="0" y1={zero} x2={width} y2={zero} stroke={axis} strokeWidth="1" />
        {periods.map((period, index) => {
          const centre = index * slot + slot / 2;
          const left = centre - bar / 2;
          const gain = period.realized_gain * scale;
          const loss = period.deductible_loss * scale;
          const recovered = period.recovered_loss * scale;
          const net = zero - period.net_taxable * scale;
          return (
            <g key={period.period}>
              {gain > 0 ? (
                <rect x={left} y={zero - gain} width={bar} height={gain} fill={up}>
                  <title>{`${period.period} · ${labels.gains} ${money(period.realized_gain)}`}</title>
                </rect>
              ) : null}
              {loss > 0 ? (
                <rect x={left} y={zero} width={bar} height={loss} fill={down}>
                  <title>{`${period.period} · ${labels.losses} ${money(period.deductible_loss)}`}</title>
                </rect>
              ) : null}
              {recovered > 0 ? (
                <rect
                  x={left}
                  y={zero + loss}
                  width={bar}
                  height={recovered}
                  fill={recoveredColor}
                >
                  <title>{`${period.period} · ${labels.recovered} ${money(period.recovered_loss)}`}</title>
                </rect>
              ) : null}
              <path
                d={`M ${centre} ${net - 5} L ${centre + 5} ${net} L ${centre} ${net + 5} L ${centre - 5} ${net} Z`}
                fill={netColor}
              >
                <title>{`${period.period} · ${labels.net} ${money(period.net_taxable)}`}</title>
              </path>
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
    </div>
  );
}

/**
 * Injected capital against market value, one point per day.
 *
 * The Streamlit page draws this in Plotly with a band between the two lines,
 * green where the book is worth more than what went into it and red where it
 * is not. That band is the reading — the gap is the profit, and its colour is
 * the answer to "am I up?" before any number is read — so it survives the port
 * even though the hover, the spike line and the zoom do not.
 *
 * Built as one polygon per contiguous stretch of the same sign rather than as
 * one shape clipped twice: a fill that crosses the crossover point would paint
 * the wrong colour on one side of it, and the crossover is exactly the day a
 * reader is looking for.
 */
export type ReturnSeries = {
  label: string;
  /** Cumulative return per date, aligned to `dates`; null where undefined. */
  points: (number | null)[];
  /** Dotted, for a line that is a hypothesis rather than a record. */
  dashed?: boolean;
  color?: string;
};

/**
 * Several cumulative-return lines on one axis, rebased to the window.
 *
 * The comparison the Streamlit page draws in Plotly: what the account earned,
 * what today's holdings would have earned over the same window, and what each
 * benchmark did. Percentages against a zero line — the axis every one of them
 * starts from — so the question "did I beat it" is answered by which line is
 * higher, not by reading two scales.
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
  const drawn = series.filter((one) => one.points.some((v) => v !== null));
  if (dates.length < 2 || !drawn.length) return null;

  const width = 720;
  const height = 300;
  const pad = { top: 8, right: 8, bottom: 24, left: 8 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const values = drawn.flatMap((one) =>
    one.points.filter((v): v is number => v !== null),
  );
  // Zero is always on the axis: a chart of returns that crops it hides whether
  // the line is above water, which is the first thing anybody reads off it.
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const span = high - low || 1;
  const x = (index: number) => pad.left + (index / (dates.length - 1)) * plotW;
  const y = (value: number) => pad.top + (1 - (value - low) / span) * plotH;

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

  const step = Math.max(1, Math.ceil(dates.length / 120));
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
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img">
        <line
          x1={pad.left}
          x2={width - pad.right}
          y1={y(0)}
          y2={y(0)}
          stroke={token("border")}
          strokeWidth="1"
        />
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
        {/* Thinned hit slices, as BookHistory draws them: what a reader wants
            is "where was everything around here", not one exact day. */}
        {dates.map((date, index) =>
          index % step ? null : (
            <rect
              key={date}
              x={x(index) - plotW / dates.length / 2}
              y={pad.top}
              width={plotW / dates.length}
              height={plotH}
              fill="transparent"
            >
              <title>
                {[
                  formatDate(date),
                  ...colored.map((one) => {
                    const value = one.points[index];
                    return `${one.label} ${value === null || value === undefined ? "—" : format(value)}`;
                  }),
                ].join(" · ")}
              </title>
            </rect>
          ),
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
    </div>
  );
}

export function BookHistory({
  points,
  labels,
  money,
  formatDate,
}: {
  points: { date: string; injected: number | null; value: number | null }[];
  labels: { injected: string; profit: string; loss: string };
  money: (value: number) => string;
  formatDate: (iso: string) => string;
}) {
  // Both legs present or the day is not comparable: a value without its
  // reference line cannot be shaded against anything.
  const days = points.filter(
    (point): point is { date: string; injected: number; value: number } =>
      point.injected !== null && point.value !== null,
  );
  if (days.length < 2) return null;

  const width = 720;
  const height = 300;
  const pad = { top: 8, right: 8, bottom: 24, left: 8 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const values = days.flatMap((day) => [day.injected, day.value]);
  const low = Math.min(...values);
  const high = Math.max(...values);
  // A flat book would divide by zero; a hair of span keeps it a line rather
  // than a NaN.
  const span = high - low || Math.abs(high) || 1;
  const x = (index: number) => pad.left + (index / (days.length - 1)) * plotW;
  const y = (value: number) => pad.top + (1 - (value - low) / span) * plotH;

  const line = (pick: (day: (typeof days)[number]) => number) =>
    days.map((day, index) => `${x(index)},${y(pick(day))}`).join(" ");

  // Contiguous runs of one sign, each closed into its own polygon. A run is
  // extended by one point on each side so neighbouring bands meet instead of
  // leaving a seam at the crossover.
  const bands: { gain: boolean; path: string }[] = [];
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
    bands.push({ gain, path: `M${top.join("L")}L${bottom.join("L")}Z` });
    start = ending ? start : index;
  }

  // Thinned hit slices rather than one per day: a year is 365 points, and the
  // tooltip a reader wants is "what was it around here", not "on exactly this
  // day".
  const step = Math.max(1, Math.ceil(days.length / 120));
  const ticks = [0, Math.floor(days.length / 2), days.length - 1];

  return (
    <div className="pf-chart">
      <ul className="pf-legend-inline">
        <li className="pf-legend-row">
          <span className="pf-swatch" style={{ background: token("text-muted") }} />
          <span>{labels.injected}</span>
        </li>
        <li className="pf-legend-row">
          <span className="pf-swatch" style={{ background: token("profit-band") }} />
          <span>{labels.profit}</span>
        </li>
        <li className="pf-legend-row">
          <span className="pf-swatch" style={{ background: token("loss-band") }} />
          <span>{labels.loss}</span>
        </li>
      </ul>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img">
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
        <polyline
          points={line((day) => day.value)}
          fill="none"
          stroke={token("brand-accent")}
          strokeWidth="2"
        />
        {days.map((day, index) =>
          index % step ? null : (
            <rect
              key={day.date}
              x={x(index) - plotW / days.length / 2}
              y={pad.top}
              width={Math.max(2, plotW / days.length)}
              height={plotH}
              fill="transparent"
            >
              <title>{`${formatDate(day.date)} · ${money(day.value)} / ${money(day.injected)}`}</title>
            </rect>
          ),
        )}
        {ticks.map((index) => (
          <text
            key={index}
            x={Math.min(Math.max(x(index), 24), width - 24)}
            y={height - 6}
            textAnchor="middle"
            fontSize="11"
            fill={token("text-muted")}
          >
            {formatDate(days[index]!.date)}
          </text>
        ))}
      </svg>
    </div>
  );
}
