/**
 * The "what moved it" waterfall.
 */

import { useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { token } from "../../../shell/theme";
import { Spoken, useScrub } from "../../../ui/chart/useScrub";
import { useWidth } from "../../../shell/useWidth";
import {
  niceTicks,
  NARROW,
  plotHeightFor,
  AxisLabel,
  ValueAxis,
  ChartTip,
  stripLines,
  viewX,
  PLOT,
  NARROW_PAD,
  BARS,
} from "./frame";

/** One bar of the "what moved it" waterfall. */
export type WaterfallBar = {
  key: string;
  label: string;
  /** A total stands on the axis; a step floats from the running total. */
  kind: "total" | "step";
  amount: number;
  /** The words under the figure in the hover box. */
  help?: string;
};

/**
 * The window's change in value, bar by bar: the opening value, each thing
 * that moved it, the closing value. Every step floats from where the one
 * before ended, so the last float lands exactly on the closing total — the
 * chart is the sum, drawn.
 *
 * Colours: totals in the info blue, money the owner put in in the brand
 * accent (it is not a result), and every other step green or red by sign.
 * A pointer or a finger on a slot reads that bar in a hover box, as the other
 * Portfolio charts do; arrow keys walk the bars.
 *
 * Narrow, the bars lie down: seven category names under seven 40px slots
 * overprint each other, so a phone gets one row per bar (name, floating span,
 * figure) on the same scale — the design system's "category labels never
 * squeeze" rule.
 */
export function Waterfall({
  bars,
  money,
  axisMoney,
  summary,
}: {
  bars: WaterfallBar[];
  money: (value: number, signed?: boolean) => string;
  axisMoney?: (value: number) => string;
  summary: string;
}) {
  return bars.length ? (
    <WaterfallPlot bars={bars} money={money} axisMoney={axisMoney} summary={summary} />
  ) : null;
}

function WaterfallPlot({
  bars,
  money,
  axisMoney,
  summary,
}: {
  bars: WaterfallBar[];
  money: (value: number, signed?: boolean) => string;
  axisMoney?: (value: number) => string;
  summary: string;
}) {
  const gutter = axisMoney ?? ((v: number) => money(v));
  const [hover, setHover] = useState<number | null>(null);
  const [frame, width] = useWidth(BARS.fallback);
  const svg = useRef<SVGSVGElement>(null);
  const walk = useScrub({
    plot: svg,
    at: hover,
    last: bars.length - 1,
    set: setHover,
    held: hover !== null,
    drop: setHover,
  });

  const up = token("candle-up");
  const down = token("candle-down");
  const total = token("info");
  const put = token("brand-accent");
  const text = token("text-muted");

  // Where each bar floats: totals from zero, steps from the running total.
  let running = 0;
  const spans = bars.map((bar) => {
    const from = bar.kind === "total" ? 0 : running;
    const to = bar.kind === "total" ? bar.amount : running + bar.amount;
    running = to;
    return { from, to };
  });
  const low = Math.min(0, ...spans.map((s) => Math.min(s.from, s.to)));
  const high = Math.max(0, ...spans.map((s) => Math.max(s.from, s.to)));
  const range = high - low || 1;

  const narrow = width < NARROW;
  const height = plotHeightFor(width, BARS.height);
  const left = narrow ? NARROW_PAD : PLOT.left;
  const top = 8;
  const footer = narrow ? 34 : 22;
  const plotW = width - left - PLOT.right;
  const plotH = height - footer - top;
  const y = (value: number) => top + ((high - value) / range) * plotH;
  const slot = plotW / bars.length;
  const bar = Math.min(64, slot * 0.62);
  const colour = (b: WaterfallBar) =>
    b.kind === "total"
      ? total
      : b.key === "contributions"
        ? put
        : b.amount >= 0
          ? up
          : down;

  const slotAt = (event: MouseEvent<SVGSVGElement>) => {
    const x = viewX(event, svg.current, width);
    if (x === null) return null;
    return Math.max(0, Math.min(bars.length - 1, Math.floor((x - left) / slot)));
  };
  const point = (event: PointerEvent<SVGSVGElement>) => {
    const index = slotAt(event);
    if (index === null) return;
    walk.quiet();
    setHover(index);
  };
  const at = hover === null ? null : bars[hover];
  const spoken = at ? `${at.label} ${money(at.amount, at.kind === "step")}` : "";

  if (narrow && bars.length > LIE_DOWN_FROM) {
    const share = (value: number) => `${((value - low) / range) * 100}%`;
    return (
      <div className="pf-chart pf-waterfall" ref={frame}>
        <ol className="pf-fall-rows" aria-label={summary}>
          {bars.map((b, index) => {
            const span = spans[index]!;
            const from = Math.min(span.from, span.to);
            return (
              <li
                key={b.key}
                className={b.kind === "total" ? "pf-fall-total" : undefined}
                title={b.help}
              >
                <span className="pf-fall-label">{b.label}</span>
                <span className="pf-fall-track" aria-hidden="true">
                  {low < 0 ? (
                    <i className="pf-fall-zero" style={{ left: share(0) }} />
                  ) : null}
                  <i
                    className="pf-fall-bar"
                    style={{
                      left: share(from),
                      width: share(low + Math.abs(span.to - span.from)),
                      background: colour(b),
                    }}
                  />
                </span>
                <span className="pf-fall-value">
                  {b.kind === "step" ? money(b.amount, true) : money(b.amount)}
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }

  return (
    <div className="pf-chart pf-waterfall">
      <div className="pf-plot pf-scrub" ref={frame} style={stripLines(1)}>
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={summary}
          className="pf-return-plot"
          {...walk.props}
          onPointerMove={point}
          onPointerDown={point}
          onPointerLeave={(event) => {
            if (event.pointerType !== "touch") setHover(null);
          }}
        >
          <ValueAxis
            ticks={niceTicks(low, high, narrow ? 3 : 4).filter((tick) => tick !== 0)}
            y={y}
            left={left}
            right={width - PLOT.right}
            format={gutter}
            inside={narrow}
            top={top}
          />
          <AxisLabel
            text={gutter(0)}
            at={y(0)}
            left={left}
            right={width - PLOT.right}
            inside={narrow}
            top={top}
          />
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
            x2={width - PLOT.right}
            y1={y(0)}
            y2={y(0)}
            stroke={token("border")}
            strokeWidth="1"
          />
          <g className="ag-redraw" key={bars.map((b) => b.amount).join("|")}>
            {bars.map((b, index) => {
              const centre = left + index * slot + slot / 2;
              const span = spans[index]!;
              const next = spans[index + 1];
              const edge = Math.min(y(span.from), y(span.to));
              const tall = Math.max(Math.abs(y(span.from) - y(span.to)), 1.5);
              return (
                <g key={b.key} pointerEvents="none">
                  <rect
                    x={centre - bar / 2}
                    y={edge}
                    width={bar}
                    height={tall}
                    fill={colour(b)}
                    rx="2"
                  />
                  {next ? (
                    <line
                      x1={centre + bar / 2}
                      x2={centre + slot - bar / 2}
                      y1={y(span.to)}
                      y2={y(span.to)}
                      stroke={token("border")}
                      strokeDasharray="2 3"
                    />
                  ) : null}
                  <text
                    x={centre}
                    y={height - (narrow ? 20 : 8)}
                    fill={text}
                    fontSize="11"
                    textAnchor="middle"
                  >
                    {b.label}
                  </text>
                  {narrow ? (
                    <text
                      x={centre}
                      y={height - 6}
                      fill={token("text-primary")}
                      fontSize="11"
                      textAnchor="middle"
                    >
                      {gutter(b.amount)}
                    </text>
                  ) : (
                    <text
                      x={centre}
                      y={Math.max(top + 10, edge - 5)}
                      fill={token("text-primary")}
                      fontSize="11"
                      fontWeight={600}
                      textAnchor="middle"
                    >
                      {b.kind === "step" ? money(b.amount, true) : money(b.amount)}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
        <Spoken text={walk.keyed ? spoken : null} />
        {at && hover !== null ? (
          <ChartTip
            x={left + hover * slot + slot / 2}
            width={width}
            title={at.label}
            rows={[
              {
                label: at.help ?? at.label,
                value: money(at.amount, at.kind === "step"),
                color: colour(at),
              },
            ]}
          />
        ) : null}
      </div>
    </div>
  );
}

/** Past this many bars a narrow waterfall draws rows instead of columns. */
const LIE_DOWN_FROM = 4;
