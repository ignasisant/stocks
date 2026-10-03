/**
 * A price chart in the drawer: what the A2UI `Chart` component draws.
 *
 * The closes are the server's (`stocks/chat/charts.py`, off the Ticker page's
 * own download), never a model's: asked for a chart, a model with nothing to
 * draw with draws one anyway, in ASCII, from figures it half-remembers. Here it
 * is told the chart is drawn and quotes the same figures this line runs
 * through.
 *
 * It borrows the Ticker page's primitives (`pages/ticker/plot.tsx`) — the
 * scale, the grid, the tooltip — but not its fixed 760-unit frame: scaled down
 * into a 380px drawer, that frame's 11px labels would print at five. The frame
 * here is the width the chart actually has, measured, so a label is the size
 * it says.
 *
 * One series is drawn by session, as the Ticker page draws it: a weekend is
 * not a flat stretch of line. Two or three are drawn by time and rebased to
 * the change since the window opened — a share and an exchange rate have no
 * axis in common, and a coin that trades on Saturdays must not slide out of
 * step with a stock that does not.
 *
 * A line marked `index` is the reader's own book: its time-weighted return as
 * a growth index from 100, which has no price to print — the tooltip gives it
 * the change alone, under the name the server sent.
 */

import { useMemo, useState } from "react";
import {
  Chart,
  Legend,
  Tooltip,
  YGrid,
  bounds,
  frame,
  plotWidth,
  scale,
  ticks,
  type TipLine,
} from "../pages/ticker/plot";
import "../pages/ticker/ticker.css";
import { useLang } from "../shell/i18n";
import { chart as palette } from "../shell/theme";
import { useWidth } from "../shell/useWidth";

export type Line = {
  symbol: string;
  currency?: string;
  dates: string[];
  values: number[];
  /** Shown in place of the symbol: the book is "Your portfolio". */
  label?: string;
  /** A growth index, not a price: only its change means anything. */
  index?: boolean;
};

const named = (line: Line) => line.label || line.symbol;

/** What the chart is drawn at before it has been measured, and on the server. */
const FALLBACK = 360;

const time = (stamp: string) =>
  Date.parse(stamp.length > 10 ? stamp : `${stamp}T00:00`);

/** A close as the server's figures print it: 1.1249, 182.50, 95,120. */
export function price(value: number): string {
  const size = Math.abs(value);
  const digits = size < 10 ? 4 : size < 10_000 ? 2 : 0;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

const change = (value: number, digits = 1) =>
  `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;

/** An axis label: as few decimals as the step between gridlines needs. */
function axis(lo: number, hi: number, rebased: boolean) {
  const [a = 0, b = 1] = ticks(lo, hi, 4);
  const step = Math.abs(b - a) || 1;
  const digits = Math.max(0, Math.ceil(-Math.log10(rebased ? step * 100 : step)));
  return rebased
    ? (value: number) => change(value, digits)
    : (value: number) =>
        value.toLocaleString("en-US", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        });
}

function dater(lang: string, first: string, last: string) {
  const span = time(last) - time(first);
  const day = 86_400_000;
  const intraday = first.length > 10;
  const options: Intl.DateTimeFormatOptions =
    intraday && span <= 1.5 * day
      ? { hour: "2-digit", minute: "2-digit" }
      : span > 400 * day
        ? { month: "short", year: "2-digit" }
        : { day: "numeric", month: "short" };
  const short = new Intl.DateTimeFormat(lang || undefined, options);
  const long = new Intl.DateTimeFormat(lang || undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(intraday ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
  const at = (stamp: string) => new Date(time(stamp));
  return {
    short: (stamp: string) => short.format(at(stamp)),
    long: (stamp: string) => long.format(at(stamp)),
  };
}

/** The index in `xs` nearest `x`; `xs` ascending. */
function nearest(xs: number[], x: number): number {
  let lo = 0;
  let hi = xs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((xs[mid] as number) < x) lo = mid;
    else hi = mid;
  }
  return Math.abs((xs[hi] as number) - x) < Math.abs((xs[lo] as number) - x) ? hi : lo;
}

export function LineChart({
  series,
  rebased,
  label,
}: {
  series: Line[];
  /** Drawn as the change since the first close, which several lines need. */
  rebased: boolean;
  label: string;
}) {
  const lang = useLang();
  const [node, width] = useWidth(FALLBACK);
  const [hover, setHover] = useState<number | null>(null);
  const colors = palette();
  const hues = [colors.brandAccent, colors.info, colors.smaFast];

  const lines = useMemo(
    () =>
      series
        .map((line) => {
          const n = Math.min(line.dates.length, line.values.length);
          const dates = line.dates.slice(0, n);
          const raw = line.values.slice(0, n).map(Number);
          const base = raw[0] || 1;
          return {
            ...line,
            dates,
            raw,
            ys: rebased ? raw.map((value) => value / base - 1) : raw,
            ts: dates.map(time),
          };
        })
        .filter((line) => line.raw.length >= 2),
    [series, rebased],
  );
  const range = useMemo(() => bounds(lines.map((line) => line.ys)), [lines]);
  const first = lines[0];
  if (!first || !range) return null;

  const box = frame({
    width,
    height: Math.round(Math.min(260, Math.max(160, width * 0.55))),
    left: rebased ? 44 : 50,
    right: 8,
    top: 8,
    bottom: 22,
  });
  const inner = plotWidth(box);
  const byTime = lines.length > 1;
  const t0 = Math.min(...lines.map((line) => line.ts[0] as number));
  const t1 = Math.max(...lines.map((line) => line.ts[line.ts.length - 1] as number));
  const xTime = scale(t0, t1, box.left, box.left + inner);
  const xIndex = scale(0, first.raw.length - 1, box.left, box.left + inner);
  const xs = lines.map((line) =>
    byTime ? line.ts.map(xTime) : line.ts.map((_, i) => xIndex(i)),
  );
  const y = scale(range.lo, range.hi, box.height - box.bottom, box.top);
  const format = axis(range.lo, range.hi, rebased);
  const dates = dater(
    lang,
    first.dates[0] as string,
    first.dates[first.dates.length - 1] as string,
  );

  const points = (at: number) => {
    const line = lines[at];
    const across = xs[at];
    if (!line || !across) return "";
    return line.ys
      .map((v, i) => `${(across[i] as number).toFixed(1)},${y(v).toFixed(1)}`)
      .join(" ");
  };
  const bottom = (box.height - box.bottom).toFixed(1);
  const area = byTime
    ? ""
    : `M${box.left},${bottom} L${points(0).replace(/ /g, " L")} L${(box.left + inner).toFixed(1)},${bottom} Z`;

  // Under the pointer: the nearest session of each line.
  const picked =
    hover === null ? null : lines.map((_, at) => nearest(xs[at] as number[], hover));
  const lead = picked?.[0] ?? 0;
  const tip: TipLine[] = picked
    ? lines.map((line, at) => {
        const i = picked[at] as number;
        const value = line.raw[i] as number;
        // Since the window opened, whichever axis the line is drawn on.
        const swing = value / (line.raw[0] as number) - 1;
        const tone = swing >= 0 ? ("up" as const) : ("down" as const);
        if (line.index)
          return {
            text: `${named(line)}  ${change(swing)}`,
            swatch: byTime ? hues[at % hues.length] : undefined,
            parts: [
              { text: `${named(line)}  `, tone: "dim" as const },
              { text: change(swing), bold: true, tone },
            ],
          };
        return {
          text: `${named(line)}  ${price(value)}`,
          swatch: byTime ? hues[at % hues.length] : undefined,
          parts: [
            { text: `${named(line)}  `, tone: "dim" as const },
            { text: price(value), bold: true },
            { text: `  ${change(swing)}`, tone },
          ],
        };
      })
    : [];
  const xLabels = [0, 0.5, 1].map((share) => {
    const i = Math.round((first.dates.length - 1) * share);
    return { x: (xs[0] as number[])[i] as number, stamp: first.dates[i] as string };
  });

  return (
    <div className="tk-plot ag-a2ui-chart" ref={node}>
      <Chart
        frame={box}
        label={`${label}: ${lines.map(named).join(", ")}`}
        onPointer={(x) => setHover(Math.max(box.left, Math.min(box.left + inner, x)))}
        onLeave={() => setHover(null)}
      >
        <YGrid frame={box} lo={range.lo} hi={range.hi} format={format} count={4} />
        {rebased && range.lo < 0 && range.hi > 0 ? (
          <line
            className="tk-event"
            x1={box.left}
            x2={box.left + inner}
            y1={y(0)}
            y2={y(0)}
            stroke={colors.textMuted}
          />
        ) : null}
        {area ? <path d={area} fill={colors.accentArea} stroke="none" /> : null}
        {lines.map((line, at) => (
          <polyline
            key={line.symbol}
            className="tk-line"
            points={points(at)}
            stroke={hues[at % hues.length]}
            strokeWidth={byTime ? 1.6 : 2}
          />
        ))}
        {lines.map((line, at) => {
          const end = line.ys.length - 1;
          return (
            <circle
              key={`end-${line.symbol}`}
              cx={(xs[at] as number[])[end]}
              cy={y(line.ys[end] as number)}
              r={3}
              fill={hues[at % hues.length]}
            />
          );
        })}
        {picked ? (
          <g>
            <line
              className="tk-cross"
              x1={(xs[0] as number[])[lead]}
              x2={(xs[0] as number[])[lead]}
              y1={box.top}
              y2={box.height - box.bottom}
            />
            {lines.map((line, at) => {
              const i = picked[at] as number;
              return (
                <circle
                  key={`at-${line.symbol}`}
                  cx={(xs[at] as number[])[i]}
                  cy={y(line.ys[i] as number)}
                  r={3.5}
                  fill={colors.surfacePage}
                  stroke={hues[at % hues.length]}
                  strokeWidth={2}
                />
              );
            })}
          </g>
        ) : null}
        <g className="tk-xlabels">
          {xLabels.map(({ x, stamp }, slot) => (
            <text
              key={stamp}
              x={x}
              y={box.height - 6}
              textAnchor={slot === 0 ? "start" : slot === 2 ? "end" : "middle"}
            >
              {dates.short(stamp)}
            </text>
          ))}
        </g>
      </Chart>
      {picked ? (
        <Tooltip
          frame={box}
          x={(xs[0] as number[])[lead] as number}
          title={dates.long(first.dates[lead] as string)}
          lines={tip}
        />
      ) : null}
      {byTime ? (
        <Legend
          items={lines.map((line, at) => ({
            label: named(line),
            color: hues[at % hues.length] as string,
          }))}
        />
      ) : null}
    </div>
  );
}
