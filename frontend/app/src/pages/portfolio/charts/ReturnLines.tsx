/**
 * Several cumulative-return lines on one date axis.
 */

import { useRef, useState, type PointerEvent } from "react";
import { series as seriesHues, seriesOther, token } from "../../../shell/theme";
import { EndLabels } from "../../ticker/plot";
import { Spoken, useScrub } from "../../../ui/chart/useScrub";
import { BASELINE_DASH, DOT, LINE } from "../../../ui/chart/marks";
import { useWidth } from "../../../shell/useWidth";
import {
  niceTicks,
  NARROW,
  plotHeightFor,
  AxisLabel,
  ValueAxis,
  Legend,
  ChartTip,
  stripLines,
  viewX,
  viewY,
  nearest,
  NARROW_PAD,
  lastValue,
  withNote,
} from "./frame";

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
  plot = "return",
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
  /** What the value axis measures. "gain" (needs `money`) plots each line as
      euros won or lost — net money in times its return — so a month with
      €800 in it moves the line by what €800 can move, where a percentage on
      that small a base dwarfed years of the real book. `tickFormat` then
      formats money; `format` still reads the returns. */
  plot?: "return" | "gain";
}) {
  const [pointer, setHover] = useState<number | null>(null);
  const [peek, setPeek] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  // With money, the line nearest the pointer, when no legend entry picks one.
  const [near, setNear] = useState<string | null>(null);
  const [frame, width] = useWidth(RETURN.fallback);
  const svg = useRef<SVGSVGElement>(null);
  const walk = useScrub({
    plot: svg,
    at: pointer,
    last: dates.length - 1,
    set: (index) => {
      setHover(index);
      if (index === null) setNear(null);
    },
    held: pointer !== null,
    drop: setHover,
  });
  const drawn = series.filter((one) => one.points.some((v) => v !== null));
  if (dates.length < 2 || !drawn.length) return null;
  // A shorter window can arrive under a pointer still resting on the old one.
  const hover = pointer !== null && pointer < dates.length ? pointer : null;
  const last = dates.length - 1;
  // Where each point sits on the value axis: its return, or with "gain" the
  // euros that return made on the day's net money in.
  const invested = plot === "gain" ? money?.invested : undefined;
  const placed = drawn.map((one) => ({
    ...one,
    at: invested
      ? one.points.map((value, index) => {
          const base = invested[index];
          return value == null || base == null ? null : base * value;
        })
      : one.points,
  }));

  const values = [
    ...placed.flatMap((one) => one.at),
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

  // Fixed slots, never cycled: a line past the fifth is muted, not a repeat.
  const ramp = seriesHues();
  const colored = placed.map((one, index) => ({
    ...one,
    color: one.color ?? ramp[index] ?? seriesOther(),
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
      const value = one.at[index];
      if (one.tipOnly || value == null) continue;
      const off = Math.abs(y(value) - at);
      if (off < gap) [best, gap] = [one.label, off];
    }
    return best;
  };
  const point = (event: PointerEvent<SVGSVGElement>) => {
    const at = viewX(event, svg.current, width);
    if (at === null) return;
    walk.quiet();
    const index = nearest(at, left, plotW, dates.length);
    setHover(index);
    if (money) setNear(closest(viewY(event, svg.current, width), index));
  };
  // The headline for a screen reader: what the plot shows, then where each
  // line ends — the figures the legend prints beside its names.
  const ends = listed
    .map((one) => {
      const end = lastValue(one.points);
      return end === null ? null : `${one.label} ${format(end)}`;
    })
    .filter((one) => one !== null)
    .join(", ");
  const summary = [label, ends].filter(Boolean).join(": ");
  // What a key step reads out: the day and every line's figure on it.
  const spoken =
    hover === null
      ? ""
      : `${formatDate(dates[hover]!)}: ${colored
          .map((one) => {
            const value = one.points[hover];
            return `${one.label} ${value == null ? "—" : format(value)}`;
          })
          .join(", ")}`;
  // Names on the lines' right ends, so telling them apart never rests on
  // matching a colour to the legend — while few enough to fit without a pile.
  const named = !narrow && listed.length + bands.length <= 4;
  const endNames = named
    ? [
        ...listed.flatMap((one) => {
          const end = lastValue(one.at);
          return end === null ? [] : [{ text: one.label, y: y(end), color: one.color }];
        }),
        ...bands.flatMap((band) => {
          for (let i = last; i >= 0; i--) {
            const hi = band.high[i];
            const lo = band.low[i];
            if (hi != null && lo != null)
              return [{ text: band.label, y: y((hi + lo) / 2), color: band.color }];
          }
          return [];
        }),
      ]
    : [];
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
                    {invested
                      ? money.money(lineMoney(base, value, null).gain, true)
                      : money.money(lineMoney(base, value, null).worth)}
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
      <div
        className="pf-plot pf-scrub"
        ref={frame}
        style={stripLines(money ? 1 : colored.length)}
      >
        <svg
          ref={svg}
          className="pf-return-plot"
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={summary || undefined}
          {...walk.props}
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
          <g className="ag-redraw" key={`${dates[0]}|${dates[last]}|${dates.length}`}>
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
                {/* Said on the date axis, where the reader looks for "when":
                  at its real x, between the year ticks rather than as one. */}
                <text
                  x={x(marker.index)}
                  y={height - 6}
                  fill={token("text-primary")}
                  fontSize="11"
                  fontWeight="600"
                  textAnchor={anchor(x(marker.index))}
                >
                  {marker.label}
                </text>
              </g>
            ) : null}
            {stacked.map((one) =>
              paths(one.at).map((d, index) => (
                <path
                  key={`${one.label}-${index}`}
                  className="pf-line"
                  data-series={one.label}
                  d={d}
                  fill="none"
                  stroke={one.color}
                  strokeWidth={
                    one.label === active
                      ? LINE.primary + LINE.lift
                      : one.focal
                        ? LINE.primary
                        : LINE.secondary
                  }
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  strokeDasharray={one.dashed ? BASELINE_DASH : undefined}
                  style={{ strokeOpacity: opacity(one) }}
                />
              )),
            )}
            {/* Where the reader's own line ends, ringed in the card's surface so
            it stays one dot where the others run into it. */}
            {stacked.map((one) => {
              const end = one.at[last];
              return !one.focal || end === null || end === undefined ? null : (
                <circle
                  key={`${one.label}-end`}
                  className="pf-line"
                  cx={x(last)}
                  cy={y(end)}
                  r={DOT.r}
                  fill={one.color}
                  stroke={ring}
                  strokeWidth={DOT.ring}
                  style={{ opacity: opacity(one) }}
                />
              );
            })}
            <EndLabels
              edge={{ right, top: RETURN.top + 10, bottom: RETURN.top + plotH - 4 }}
              items={endNames}
            />
          </g>
          {/* Plotly's `hovermode="x"`: the whole plot answers, nearest day by
            the pointer's x, with a crosshair and a dot on every line there. */}
          {hover === null ? null : (
            <g pointerEvents="none">
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={RETURN.top}
                y2={RETURN.top + plotH}
                className="ag-cross"
              />
              {colored.map((one) => {
                const value = one.at[hover];
                return value === null || value === undefined ? null : (
                  <circle
                    key={one.label}
                    cx={x(hover)}
                    cy={y(value)}
                    r={DOT.r}
                    fill={one.color}
                    stroke={ring}
                    strokeWidth={DOT.ring}
                    opacity={opacity(one)}
                  />
                );
              })}
            </g>
          )}
          {xTicks.indices
            // A year label under the marker's own word would print over it.
            .filter(
              (index) =>
                !marker ||
                marker.index <= 0 ||
                marker.index >= dates.length ||
                Math.abs(x(index) - x(marker.index)) >= TICK_ROOM.year * 0.75,
            )
            .map((index) => (
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
        <Spoken text={walk.keyed ? spoken : null} />
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
      <span className="ag-tip-sw" style={{ background: one.color }} />
      <span>{one.label}</span>
    </span>
  );
}
