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
 * A line marked `index` is a growth index from 100, which has no price to
 * print — the tooltip gives it the change alone, under the name the server
 * sent. A line marked `money` is an amount: the reader's book, what it was
 * worth each day, and the same money in an index (`daily_book.versus`). The
 * tooltip prints the amounts, the money put in by then and the gap between
 * the two; a measured span, what each made net of that money.
 */

import { useMemo, useState } from "react";
import {
  Chart,
  EndLabels,
  Legend,
  Tooltip,
  YGrid,
  bounds,
  frame,
  plotWidth,
  scale,
  spoken,
  summary,
  ticks,
  type TipLine,
} from "../pages/ticker/plot";
import "../pages/ticker/ticker.css";
import { money } from "../pages/home/format";
import { useLang, useT } from "../shell/i18n";
import { chart as palette } from "../shell/theme";
import { useWidth } from "../shell/useWidth";
import { num } from "../shell/numbers";

export type Line = {
  symbol: string;
  currency?: string;
  dates: string[];
  values: number[];
  /** Shown in place of the symbol: the book is "Your portfolio". */
  label?: string;
  /** A growth index, not a price: only its change means anything. */
  index?: boolean;
  /** An amount each day, in `currency`: the book's value, or the same money
   * in an index. */
  money?: boolean;
  /** The book only: the money put in by each date, net of withdrawals. */
  injected?: number[];
  /** The same money in an index: the day it was first bought. */
  opens?: string;
};

const named = (line: Line) => line.label || line.symbol;

/** What the chart is drawn at before it has been measured, and on the server. */
const FALLBACK = 360;

const time = (stamp: string) =>
  Date.parse(stamp.length > 10 ? stamp : `${stamp}T00:00`);

/** A close in the account's language: 1,1249, 182,50, 95.120. */
export function price(value: number): string {
  const size = Math.abs(value);
  const digits = size < 10 ? 4 : size < 10_000 ? 2 : 0;
  return num(value, digits);
}

const change = (value: number, digits = 1) =>
  `${value >= 0 ? "+" : ""}${num(value * 100, digits)}%`;

/** An axis label: as few decimals as the step between gridlines needs. */
function axis(lo: number, hi: number, rebased: boolean) {
  const [a = 0, b = 1] = ticks(lo, hi, 4);
  const step = Math.abs(b - a) || 1;
  const digits = Math.max(0, Math.ceil(-Math.log10(rebased ? step * 100 : step)));
  return rebased
    ? (value: number) => change(value, digits)
    : (value: number) => num(value, digits);
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
  const t = useT();
  const lang = useLang();
  const [node, width] = useWidth(FALLBACK);
  const [hover, setHover] = useState<number | null>(null);
  // Two places being compared (`Chart`'s `onSpan`), in viewBox x, in order.
  const [span, setSpan] = useState<[number, number] | null>(null);
  const colors = palette();
  const hues = [colors.brandAccent, colors.info, colors.smaFast];
  // Purple, blue and gold part three lines for most eyes, not for all: the
  // second and third are dashed too, and each is named at its end.
  const dashes = [undefined, "6 3", "2 3"];

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
  // Amounts read in thousands on the axis; the tooltip has them in full.
  const format = lines.every((line) => line.money)
    ? (value: number) =>
        new Intl.NumberFormat(lang || undefined, {
          notation: "compact",
          maximumFractionDigits: 1,
        }).format(value)
    : axis(range.lo, range.hi, rebased);
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
  const cash = (amount: number | undefined, line: Line, signed = false) =>
    money(amount, line.currency || "EUR", lang, { signed }) ?? "";
  const toned = (amount: number) => (amount >= 0 ? ("up" as const) : ("down" as const));
  // The money the book had in, which the index line was bought with too.
  const flows = lines.find((line) => line.injected?.length)?.injected;
  const row = (
    label: string,
    text: string,
    extra?: Partial<TipLine>,
    tone?: "up" | "down",
  ) => ({
    text: `${label}  ${text}`,
    ...extra,
    parts: [
      { text: `${label}  `, tone: "dim" as const },
      { text, bold: true, ...(tone ? { tone } : {}) },
    ],
  });
  const tip: TipLine[] = picked
    ? lines.flatMap((line, at): TipLine[] => {
        const i = picked[at] as number;
        const value = line.raw[i] as number;
        const swatch = byTime ? hues[at % hues.length] : undefined;
        if (line.money) {
          const put = line.injected?.[i];
          return [
            row(named(line), cash(value, line), { swatch }),
            ...(put === undefined
              ? []
              : [row(t("home.chart_injected"), cash(put, line))]),
          ];
        }
        // Since the window opened, whichever axis the line is drawn on.
        const swing = value / (line.raw[0] as number) - 1;
        const tone = swing >= 0 ? ("up" as const) : ("down" as const);
        if (line.index)
          return [
            {
              text: `${named(line)}  ${change(swing)}`,
              swatch,
              parts: [
                { text: `${named(line)}  `, tone: "dim" as const },
                { text: change(swing), bold: true, tone },
              ],
            },
          ];
        return [
          {
            text: `${named(line)}  ${price(value)}`,
            swatch,
            parts: [
              { text: `${named(line)}  `, tone: "dim" as const },
              { text: price(value), bold: true },
              { text: `  ${change(swing)}`, tone },
            ],
          },
        ];
      })
    : [];
  // The book against the same money in the index: what the picks made.
  const [mine, theirs] = lines;
  if (picked && mine?.money && theirs?.money) {
    const gap =
      (mine.raw[picked[0] as number] as number) -
      (theirs.raw[picked[1] as number] as number);
    tip.push(row(t("home.chart_gap"), cash(gap, mine, true), {}, toned(gap)));
  }
  // Between two places: each line's nearest session at either end, and what
  // it did across them. A span of one place is a mouse anchor just dropped.
  const ends = span
    ? lines.map((_, at): [number, number] => [
        nearest(xs[at] as number[], span[0]),
        nearest(xs[at] as number[], span[1]),
      ])
    : null;
  const [from, to]: [number, number] = ends?.[0] ?? [0, 0];
  const measured = ends !== null && to > from ? ends : null;
  const spanTip: TipLine[] = measured
    ? lines.map((line, at) => {
        const [a, b] = measured[at] as [number, number];
        const start = line.raw[a] as number;
        const end = line.raw[b] as number;
        const swatch = byTime ? hues[at % hues.length] : undefined;
        if (line.money) {
          // Made, not moved: the money put in across the span is no gain.
          const put = flows ? (flows[b] ?? 0) - (flows[a] ?? 0) : 0;
          const made = end - start - put;
          return row(named(line), cash(made, line, true), { swatch }, toned(made));
        }
        const swing = start ? end / start - 1 : 0;
        const tone = swing >= 0 ? ("up" as const) : ("down" as const);
        const levels = line.index ? "" : `${price(start)} → ${price(end)}  `;
        return {
          text: `${named(line)}  ${levels}${change(swing)}`,
          swatch,
          parts: [
            { text: `${named(line)}  `, tone: "dim" as const },
            ...(levels ? [{ text: levels }] : []),
            { text: change(swing), bold: true, tone },
          ],
        };
      })
    : [];
  const clamp = (x: number) => Math.max(box.left, Math.min(box.left + inner, x));

  // Under ~300px the middle date crowds the two ends; the ends alone still
  // say what the window is.
  const xLabels = (inner < 300 ? [0, 1] : [0, 0.5, 1]).map((share) => {
    const i = Math.round((first.dates.length - 1) * share);
    return { x: (xs[0] as number[])[i] as number, stamp: first.dates[i] as string };
  });

  return (
    <div className="tk-plot ag-a2ui-chart" ref={node}>
      <Chart
        frame={box}
        label={summary(
          label,
          dates.long(first.dates[0] as string),
          dates.long(first.dates[first.dates.length - 1] as string),
          lines
            .map((line) => {
              const end = line.raw[line.raw.length - 1] as number;
              return `${named(line)} ${change(end / (line.raw[0] as number) - 1)}`;
            })
            .join(", "),
        )}
        walk={{
          at: picked ? lead : null,
          last: first.raw.length - 1,
          set: (i) => setHover(i === null ? null : ((xs[0] as number[])[i] as number)),
        }}
        readout={
          picked && !measured
            ? spoken(dates.long(first.dates[lead] as string), tip)
            : null
        }
        onPointer={(x) => setHover(clamp(x))}
        onLeave={() => {
          setHover(null);
          setSpan(null);
        }}
        onSpan={(pair) =>
          setSpan(
            pair && [
              clamp(Math.min(pair[0], pair[1])),
              clamp(Math.max(pair[0], pair[1])),
            ],
          )
        }
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
        <g
          className="ag-redraw"
          key={lines
            .map((line) => `${line.symbol}-${line.dates[0]}-${line.dates.length}`)
            .join("|")}
        >
          {area ? <path d={area} fill={colors.accentArea} stroke="none" /> : null}
          {lines.map((line, at) => (
            <polyline
              key={line.symbol}
              className="tk-line"
              points={points(at)}
              stroke={hues[at % hues.length]}
              strokeWidth={byTime ? 1.6 : 2}
              strokeDasharray={dashes[at % dashes.length]}
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
        </g>
        {byTime ? (
          <EndLabels
            frame={box}
            items={lines.map((line, at) => ({
              y: y(line.ys[line.ys.length - 1] as number),
              text: named(line),
              color: hues[at % hues.length] as string,
            }))}
          />
        ) : null}
        {ends ? (
          <g className="tk-span">
            {measured ? (
              <rect
                x={(xs[0] as number[])[from]}
                y={box.top}
                width={
                  ((xs[0] as number[])[to] as number) -
                  ((xs[0] as number[])[from] as number)
                }
                height={box.height - box.bottom - box.top}
              />
            ) : null}
            {[from, to].map((i, slot) => (
              <line
                key={slot}
                x1={(xs[0] as number[])[i]}
                x2={(xs[0] as number[])[i]}
                y1={box.top}
                y2={box.height - box.bottom}
              />
            ))}
          </g>
        ) : null}
        {picked && !measured ? (
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
              textAnchor={
                slot === 0 ? "start" : slot === xLabels.length - 1 ? "end" : "middle"
              }
            >
              {dates.short(stamp)}
            </text>
          ))}
        </g>
      </Chart>
      {measured ? (
        <Tooltip
          frame={box}
          x={
            (((xs[0] as number[])[from] as number) +
              ((xs[0] as number[])[to] as number)) /
            2
          }
          title={`${dates.long(first.dates[from] as string)} → ${dates.long(first.dates[to] as string)}`}
          lines={spanTip}
        />
      ) : picked ? (
        <Tooltip
          frame={box}
          x={(xs[0] as number[])[lead] as number}
          title={dates.long(first.dates[lead] as string)}
          lines={tip}
          more={tip.length > lines.length}
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
