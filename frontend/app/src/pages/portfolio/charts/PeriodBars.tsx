/**
 * The realized-result bars per period, with the net as a diamond.
 */

import {
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { token } from "../../../shell/theme";
import { Spoken, useScrub } from "../../../ui/chart/useScrub";
import { useWidth } from "../../../shell/useWidth";
import type { TaxPeriod } from "../api";
import {
  niceTicks,
  NARROW,
  plotHeightFor,
  AxisLabel,
  ValueAxis,
  Legend,
  type TipRow,
  ChartTip,
  stripLines,
  viewX,
  PLOT,
  NARROW_PAD,
  BARS,
} from "./frame";

/**
 * The realized result per period: gains (and dividends, where they share the
 * base) stack up, deductible losses (and any recovered from an earlier
 * deferral) stack down, and the diamond marks the net the brackets then tax.
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
  labels: {
    gains: string;
    losses: string;
    recovered: string;
    net: string;
    dividends?: string;
  };
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
  const walk = useScrub({
    plot: svg,
    at: hover,
    last: periods.length - 1,
    set: setHover,
    held: hover !== null,
    drop: setHover,
  });
  // On touch the first tap on a bar reads it and only a second, on the same
  // bar, picks it: one tap would otherwise open the box and navigate at once.
  const armed = useRef(false);

  const up = token("candle-up");
  const down = token("candle-down");
  const recoveredColor = token("warn-orange");
  // The Dividends tab's own bar colour, so the two read as one income.
  const dividendColor = token("brand-accent");
  const netColor = token("info");
  const axis = token("border");
  const text = token("text-muted");

  const anyRecovered = periods.some((period) => period.recovered_loss !== 0);
  // Absent from a jurisdiction that taxes dividends apart: no series, no key.
  const paid = (period: TaxPeriod) => period.dividends || 0;
  const anyDividends = periods.some((period) => paid(period) > 0);
  const tops = periods.map((period) =>
    Math.max(period.realized_gain + paid(period), period.net_taxable, 0),
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
    ...(anyDividends
      ? ([[labels.dividends ?? "", dividendColor]] as [string, string][])
      : []),
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
    if (index === null) return;
    walk.quiet();
    setHover(index);
  };
  const first = periods[0]!;
  const final = periods[periods.length - 1]!;
  const summary = `${labels.net}, ${first.period} ${money(first.net_taxable)} → ${final.period} ${money(final.net_taxable)}`;
  const spoken = at
    ? `${at.period}: ${labels.gains} ${money(at.realized_gain)}${
        anyDividends ? `, ${labels.dividends ?? ""} ${money(paid(at))}` : ""
      }, ${labels.losses} ${money(at.deductible_loss)}${
        anyRecovered ? `, ${labels.recovered} ${money(at.recovered_loss)}` : ""
      }, ${labels.net} ${money(at.net_taxable)}`
    : "";

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
      <div
        className="pf-plot pf-scrub"
        ref={frame}
        style={stripLines(3 + (anyDividends ? 1 : 0) + (anyRecovered ? 1 : 0))}
      >
        <svg
          ref={svg}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={summary}
          className={onPick ? "pf-return-plot pf-bars-pick" : "pf-return-plot"}
          {...walk.props}
          onPointerMove={point}
          onPointerDown={(event) => {
            armed.current = event.pointerType !== "touch" || slotAt(event) === hover;
            point(event);
          }}
          onPointerLeave={(event) => {
            // A tap ends in a leave: the box it opened stays until the next.
            if (event.pointerType !== "touch") setHover(null);
          }}
          onClick={(event) => {
            const index = slotAt(event);
            const period = index === null ? undefined : periods[index];
            if (period && onPick && armed.current) onPick(period);
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
          <g
            className="ag-redraw"
            key={`${first.period}|${final.period}|${periods.length}`}
          >
            {periods.map((period, index) => {
              const centre = left + index * slot + slot / 2;
              const x = centre - bar / 2;
              const gain = period.realized_gain * scale;
              const dividend = paid(period) * scale;
              const loss = period.deductible_loss * scale;
              const recovered = period.recovered_loss * scale;
              const net = y(period.net_taxable);
              return (
                <g key={period.period} pointerEvents="none">
                  {gain > 0 ? (
                    <rect x={x} y={zero - gain} width={bar} height={gain} fill={up} />
                  ) : null}
                  {dividend > 0 ? (
                    <rect
                      x={x}
                      y={zero - gain - dividend}
                      width={bar}
                      height={dividend}
                      fill={dividendColor}
                    />
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
          </g>
        </svg>
        <Spoken text={walk.keyed ? spoken : null} />
        {at && hover !== null ? (
          <ChartTip
            x={left + hover * slot + slot / 2}
            width={width}
            title={at.period}
            rows={[
              { label: labels.gains, value: money(at.realized_gain), color: up },
              ...(anyDividends
                ? [
                    {
                      label: labels.dividends ?? "",
                      value: money(paid(at)),
                      color: dividendColor,
                    },
                  ]
                : []),
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
