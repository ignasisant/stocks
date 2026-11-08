/**
 * The book's history: value over the money put in, with drag-to-measure.
 */

import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { token } from "../../../shell/theme";
import { useSpan } from "../../../shell/useSpan";
import { Spoken, useScrub } from "../../../ui/chart/useScrub";
import { BASELINE_DASH, LINE } from "../../../ui/chart/marks";
import { useWidth } from "../../../shell/useWidth";
import {
  NARROW,
  ValueAxis,
  Legend,
  type TipRow,
  tipSaid,
  ChartTip,
  stripLines,
  viewX,
  nearest,
  PLOT,
  NARROW_PAD,
  BARS,
  gainBands,
} from "./frame";
import { fitHeight } from "../../../ui/chart/fit";
import { ticks as valueTicks } from "../../../ui/chart/ticks";

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
 * The tooltip carries value, injected, and the P/L between them as an amount
 * and a percentage. A mouse dragged across the plot compares the day it went
 * down on with the day under it (`bookSpanTip`), as do two fingers or a
 * secondary click (`useSpan`). It does not zoom: the range picker above
 * already narrows the window, with the axis refitted to it.
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
  };
  money: (value: number, signed?: boolean) => string;
  /** Compact formatter for the gutter; falls back to `money` when omitted. */
  axisMoney?: (value: number) => string;
  percent: (value: number) => string;
  formatDate: (iso: string) => string;
  /**
   * One day in full, for the hover box and a comparison's ends; falls back to
   * `formatDate`. A month-and-year tick is enough to place the axis, not to
   * say which two days a comparison ran between.
   */
  formatDay?: (iso: string) => string;
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
  formatDay = formatDate,
}: Omit<BookHistoryProps, "points"> & { all: BookDay[] }) {
  const gutter = axisMoney ?? ((value: number) => money(value));
  const [frame, width] = useWidth(BARS.fallback);
  // The day a mouse drag went down on; the comparison runs from it to the pointer.
  const [anchor, setAnchor] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  // Two days being compared (a drag or `useSpan`), in day order.
  const [measure, setMeasure] = useState<{ from: number; to: number } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drop = useCallback(() => {
    setHover(null);
    setMeasure(null);
  }, []);
  // A new window from the server is a new series: a comparison indexes into
  // days that are no longer the same days.
  const first = all[0]?.date;
  const last = all[all.length - 1]?.date;
  useEffect(() => {
    setAnchor(null);
    setHover(null);
    setMeasure(null);
  }, [first, last, all.length]);

  const days = all;
  const walk = useScrub({
    plot: svg,
    at: hover,
    last: days.length - 1,
    set: setHover,
    held: hover !== null || measure !== null,
    drop,
  });
  const narrow = width < NARROW;
  const height = fitHeight(width, PLOT.height);
  const left = narrow ? NARROW_PAD : PLOT.left;
  const plotW = width - left - PLOT.right;
  const plotH = height - PLOT.top - PLOT.bottom;

  // In a short window the money put in can sit far below everything the value
  // did: fitted together, the value's month is squeezed into the top third
  // and the band is a solid block under it, so every range looks the same.
  // Past one value-span away it leaves the axis — a plain line, no fill,
  // since an area needs the baseline it is measured from on screen — and its
  // amount moves into the legend, arrowed the way it went.
  const worthLow = Math.min(...days.map((day) => day.value));
  const worthHigh = Math.max(...days.map((day) => day.value));
  const reach = worthHigh - worthLow;
  const offAxis =
    Math.min(...days.map((day) => day.injected)) > worthHigh + reach
      ? "above"
      : Math.max(...days.map((day) => day.injected)) < worthLow - reach
        ? "below"
        : null;
  const values = offAxis
    ? [worthLow, worthHigh]
    : days.flatMap((day) => [day.injected, day.value]);
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

  /** Where a pointer is on the SVG, in viewBox x. */
  const xAt = (event: MouseEvent<SVGSVGElement>) =>
    viewX(event, svg.current, width) ?? left;
  /** Which day a viewBox x is over. */
  const dayOf = (at: number) => nearest(at, left, plotW, days.length);
  const spanned = useSpan((pair) => {
    if (!pair) return setMeasure(null);
    const [a, b] = pair.map(dayOf) as [number, number];
    setHover(null);
    setMeasure({ from: Math.min(a, b), to: Math.max(a, b) });
  });

  const stretch = (from: number, to: number) =>
    setMeasure(
      from === to ? null : { from: Math.min(from, to), to: Math.max(from, to) },
    );

  const upColor = token("up");
  const downColor = token("down");
  const tipRows = (day: (typeof days)[number]) => bookTip(day, labels, money, percent);
  const hovered = hover === null ? null : days[hover];
  const firstDay = days[0]!;
  const lastDay = days[days.length - 1]!;
  const summary = `${labels.value}, ${formatDay(firstDay.date)} → ${formatDay(lastDay.date)}: ${money(firstDay.value)} → ${money(lastDay.value)}; ${labels.injected} ${money(lastDay.injected)}`;
  const spoken = hovered ? tipSaid(formatDay(hovered.date), tipRows(hovered)) : "";
  const anyGain = days.some((day) => day.value >= day.injected);
  const anyLoss = days.some((day) => day.value < day.injected);

  return (
    <div className="pf-chart">
      <div className="pf-chart-head">
        <Legend>
          <li className="pf-legend-row">
            <span className="pf-swatch" style={{ background: token("text-muted") }} />
            <span>
              {offAxis
                ? `${labels.injected} ${gutter(lastDay.injected)} ${offAxis === "below" ? "↓" : "↑"}`
                : labels.injected}
            </span>
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
      </div>
      <div className="pf-plot pf-scrub" ref={frame} style={stripLines(3)}>
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={summary}
          className="pf-zoomable pf-return-plot"
          {...walk.props}
          onPointerDown={(event) => {
            walk.quiet();
            if (spanned.down(event, xAt(event))) return;
            const at = dayOf(xAt(event));
            // A finger scrubs; its comparison is the hold-and-slide `useSpan`
            // already read above.
            if (event.pointerType === "touch") {
              setHover(at);
              return;
            }
            if (event.button !== 0) return;
            // Captured, so a drag that wanders off the plot keeps tracking
            // (to the edge day, since `dayOf` clamps) and ends where the
            // button is let go, not where the pointer happened to leave.
            event.currentTarget.setPointerCapture?.(event.pointerId);
            setAnchor(at);
            setHover(null);
            setMeasure(null);
          }}
          onPointerMove={(event) => {
            if (spanned.move(event, xAt(event))) return;
            walk.quiet();
            const at = dayOf(xAt(event));
            if (anchor !== null) return stretch(anchor, at);
            setHover(at);
          }}
          // Letting go keeps the comparison up to be read; the next press
          // or the pointer leaving puts it away.
          onPointerUp={(event) => {
            if (spanned.up(event)) return;
            setAnchor(null);
          }}
          // A finger lifting is a leave too: the day it read stays up until
          // the reader touches elsewhere (useTouchHold).
          onPointerLeave={(event) => {
            // A drag in progress is held by the capture; leaving is not its end.
            if (
              anchor !== null &&
              event.currentTarget.hasPointerCapture?.(event.pointerId)
            )
              return;
            spanned.leave(event);
            if (event.pointerType === "touch") return;
            setHover(null);
            setAnchor(null);
            setMeasure(null);
          }}
          onPointerCancel={spanned.cancel}
          onContextMenu={(event) => spanned.menu?.(event, xAt(event))}
        >
          <ValueAxis
            ticks={valueTicks(low, high, narrow ? 4 : 5)}
            y={y}
            left={left}
            right={width - PLOT.right}
            format={gutter}
            inside={narrow}
            top={PLOT.top}
          />
          <g className="ag-redraw" key={`${first}|${last}|${all.length}`}>
            {offAxis ? null : (
              <>
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
                  strokeWidth={LINE.rule}
                  strokeDasharray={BASELINE_DASH}
                />
              </>
            )}
            {bands.map((band, index) => (
              <polyline
                key={`value-${index}`}
                points={band.value}
                fill="none"
                stroke={band.gain ? upColor : downColor}
                strokeWidth={LINE.primary}
              />
            ))}
          </g>
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
                className="ag-cross"
              />
              <circle
                cx={x(hover)}
                cy={y(hovered.value)}
                r="3"
                fill={hovered.value >= hovered.injected ? upColor : downColor}
              />
            </g>
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
        <Spoken text={walk.keyed ? spoken : null} />
        {measure && measure.to > measure.from ? (
          <ChartTip
            x={(x(measure.from) + x(measure.to)) / 2}
            width={width}
            title={`${formatDay(days[measure.from]!.date)} → ${formatDay(days[measure.to]!.date)}`}
            rows={bookSpanTip(days[measure.from]!, days[measure.to]!, labels, money)}
          />
        ) : hovered && hover !== null && !measure ? (
          <ChartTip
            x={x(hover)}
            width={width}
            title={formatDay(hovered.date)}
            rows={tipRows(hovered)}
          />
        ) : null}
      </div>
    </div>
  );
}
