/**
 * The book's money over its rates, on two floors of one frame.
 */

import {
  useCallback,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
} from "react";
import { series as seriesHues, seriesOther, token } from "../../../shell/theme";
import { EndLabels } from "../../ticker/plot";
import { useSpan } from "../../../shell/useSpan";
import { Spoken, useScrub } from "../../../ui/chart/useScrub";
import { BASELINE_DASH, LINE } from "../../../ui/chart/marks";
import { useWidth } from "../../../shell/useWidth";
import {
  niceTicks,
  NARROW,
  plotHeightFor,
  AxisLabel,
  ValueAxis,
  Legend,
  type TipRow,
  tipSaid,
  ChartTip,
  stripLines,
  viewX,
  nearest,
  NARROW_PAD,
  BARS,
  lastValue,
  withNote,
  gainBands,
} from "./frame";
import type { ReturnSeries } from "./ReturnLines";
import { bookSpanTip } from "./BookHistory";

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
  // A shorter window can arrive under a pointer still resting on the old one,
  // or under a comparison drawn on it.
  const hover = pointer !== null && pointer < book.length && !measure ? pointer : null;
  const walk = useScrub({
    plot: svg,
    at: hover,
    last: book.length - 1,
    set: setHover,
    held: pointer !== null || measure !== null,
    drop,
  });
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

  const ramp = seriesHues();
  const colored = drawn.map((one, index) => ({
    ...one,
    color: one.color ?? ramp[index] ?? seriesOther(),
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
    if (at === null) return;
    walk.quiet();
    setHover(nearest(at, left, plotW, book.length));
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
  const firstPoint = book[0]!;
  const lastPoint = book[book.length - 1]!;
  const summary = `${labels.value}, ${formatDate(firstPoint.date)} → ${formatDate(lastPoint.date)}: ${money(firstPoint.value)} → ${money(lastPoint.value)}; ${labels.invested} ${money(lastPoint.invested)}${colored
    .map((one) => {
      const end = lastValue(one.points);
      return end === null ? "" : `; ${one.label} ${format(end)}`;
    })
    .join("")}`;
  const spoken = hovered
    ? tipSaid(formatDate(hovered.date), tipRows(hover!, hovered))
    : "";
  // Names on the rate lines' ends, so they are told apart by more than
  // colour — inside the plot, since the right gutter holds the axis.
  const endNames =
    narrow || colored.length > 4
      ? []
      : colored.flatMap((one) => {
          const end = lastValue(one.points);
          let at = one.points.length - 1;
          while (at > 0 && one.points[at] === null) at--;
          return end === null
            ? []
            : [{ text: one.label, y: yRate(end), at, color: one.color }];
        });

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
      <div
        className="pf-plot pf-scrub"
        ref={frame}
        style={stripLines(3 + (barred ? 1 : 0) + colored.length)}
      >
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={summary}
          className="pf-return-plot"
          {...walk.props}
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
          <g
            className="ag-redraw"
            key={`${firstPoint.date}|${lastPoint.date}|${book.length}`}
          >
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
              strokeWidth={LINE.rule}
              strokeDasharray={BASELINE_DASH}
            />
            {bands.map((band, index) => (
              <polyline
                key={`value-${index}`}
                points={band.value}
                fill="none"
                stroke={band.gain ? upColor : downColor}
                strokeWidth={LINE.primary}
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
                  strokeWidth={LINE.secondary}
                  strokeDasharray={one.dashed ? BASELINE_DASH : undefined}
                />
              )),
            )}
            <EndLabels
              edge={{ right: 0, top: ratesTop + 10, bottom: bottom - 4 }}
              items={endNames.map((one) => ({ ...one, x: x(one.at) }))}
            />
          </g>

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
                className="ag-cross"
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
        <Spoken text={walk.keyed ? spoken : null} />
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
