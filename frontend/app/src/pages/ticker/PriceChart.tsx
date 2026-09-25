/**
 * The price chart: the line or the candles, the moving averages over them, the
 * reader's own fills, and a marker on every dividend and results date.
 *
 * Plotted on the bar INDEX rather than on the timestamp. That is what closes
 * the weekend and overnight gaps — the same thing the API's `rangebreaks` do
 * for a Plotly axis — and it means a drag selects a span of bars, which is what
 * a reader is actually choosing.
 *
 * Two things here are the page's argument and not decoration. The event
 * markers carry their own line in the tooltip, because a spike beside an
 * earnings print is a different fact from a spike beside nothing. And the fills
 * are drawn on the reader's own chart, priced in today's shares — the server
 * scales them, since the ledger stores what was actually paid.
 */

import { useEffect, useMemo, useState } from "react";
import { chart as palette, token } from "../../shell/theme";
import { useLang } from "../../shell/i18n";
import { dividendLine, resultsLines, snap, type EventLine } from "./events";
import { latest, money, type Translate } from "./format";
import {
  averageRow,
  eventRows,
  fillRows,
  hoverTitle,
  placeFills,
  priceRows,
  type Fill,
} from "./hover";
import {
  Chart,
  Legend,
  Tooltip,
  YGrid,
  bounds,
  frame,
  plotHeight,
  plotWidth,
  scale,
  type TipLine,
} from "./plot";
import type { Bars, EarningsEvent, Trade } from "./types";

/** Fewer bars than this in a drag is a mis-click, not a window somebody picked. */
const MIN_SPAN = 3;

export type Window = { pct: number; from: string; to: string } | null;

/** A series split at its nulls, so a warm-up gap is a gap and not a straight line. */
function segments(values: (number | null)[], from: number, to: number): number[][] {
  const runs: number[][] = [];
  let run: number[] = [];
  for (let i = from; i <= to; i++) {
    const value = values[i];
    if (value === null || value === undefined) {
      if (run.length > 1) runs.push(run);
      run = [];
    } else {
      run.push(i);
    }
  }
  if (run.length > 1) runs.push(run);
  return runs;
}

/** An axis label for a bar: the date, or the clock when the window is intraday. */
function labeller(lang: string, intraday: boolean): (stamp: string) => string {
  const format = new Intl.DateTimeFormat(
    lang || undefined,
    intraday
      ? { hour: "2-digit", minute: "2-digit" }
      : { day: "numeric", month: "short", year: "2-digit" },
  );
  return (stamp: string) => {
    const at = Date.parse(stamp.replace(" ", "T"));
    return Number.isNaN(at) ? stamp.slice(0, 10) : format.format(new Date(at));
  };
}

export function PriceChart({
  bars,
  events,
  trades,
  avgCost,
  candles,
  mobile,
  onWindow,
  t,
}: {
  bars: Bars;
  events: EarningsEvent[];
  trades: Trade[];
  /** The blended entry, so a single lot can be read against the position. */
  avgCost: number | null;
  candles: boolean;
  mobile: boolean;
  /** The change across a window the reader dragged out, for the readout. */
  onWindow: (window: Window) => void;
  t: Translate;
}) {
  const lang = useLang();
  const colors = palette();
  const smaLong = token("sma-long", colors.textMuted);

  const n = bars.dates.length;
  const [zoom, setZoom] = useState<{ from: number; to: number } | null>(null);
  const [drag, setDrag] = useState<{ from: number; to: number } | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  // A new range is a new set of bars, and the window somebody dragged out of
  // the old ones does not survive it: keeping the zoom would apply yesterday's
  // bar indices to a different series, and keeping the readout would caption
  // the chart with a change it no longer shows.
  useEffect(() => {
    setZoom(null);
    setDrag(null);
    onWindow(null);
  }, [bars, onWindow]);

  const from = zoom ? Math.max(0, zoom.from) : 0;
  const to = zoom ? Math.min(n - 1, zoom.to) : n - 1;

  const close = bars.series.Close ?? [];
  const open = bars.series.Open ?? [];
  const high = bars.series.High ?? [];
  const low = bars.series.Low ?? [];
  const days = useMemo(
    () => bars.dates.map((stamp) => stamp.slice(0, 10)),
    [bars.dates],
  );
  const daily = bars.interval === "1d";
  /**
   * A range whose bars are shorter than a day is one where several of them
   * share a calendar date, so the axis has to say the clock instead.
   *
   * Matched on the trailing unit, not the leading digits: `analysis.history`
   * quotes minutes as "5m" and "30m", and a month would be "1mo" — a test that
   * read the number first would label a five-minute chart in days.
   */
  const intraday = /[mh]$/.test(bars.interval);

  const box = frame({
    height: mobile ? 280 : 340,
    left: 48,
    right: 14,
    // Room over the plot for the events' letter tags.
    top: 20,
    bottom: 26,
  });
  const inner = plotWidth(box);
  const band = inner / Math.max(1, to - from + 1);
  const xOf = (index: number) => box.left + (index - from + 0.5) * band;
  /**
   * Where an event's diamond sits: 1% over its bar's high, Streamlit's
   * `High * 1.01` — above the candle it annotates, never on it. The close on a
   * bar with no high, which a line chart's series can be.
   */
  const diamondY = (index: number) => (high[index] ?? close[index] ?? 0) * 1.01;

  // Every buy and sell dated inside the range, on the bar it belongs to —
  // Streamlit's `>= chart_start`, so an entry older than the window is off its
  // left edge rather than stacked onto the first candle.
  const fills = useMemo<Fill[]>(() => placeFills(trades, days), [trades, days]);

  const marks = useMemo(() => {
    const lines = new Map<number, EventLine[]>();
    const kinds = new Map<number, "dividend" | "results">();
    (bars.dividends ?? []).forEach((value, index) => {
      const day = days[index];
      if (!value || day === undefined) return;
      const at = close[index] ?? null;
      lines.set(index, [...(lines.get(index) ?? []), dividendLine(value, at, day, t)]);
      kinds.set(index, "dividend");
    });
    const first = days[0] ?? "";
    const last = days[days.length - 1] ?? "";
    for (const event of events) {
      if (event.date < first || event.date > last) continue;
      const index = snap(days, event.date);
      lines.set(index, [
        ...(lines.get(index) ?? []),
        ...resultsLines(event, close, index, daily, t),
      ]);
      kinds.set(index, "results");
    }
    return { lines, kinds };
  }, [bars.dividends, days, close, events, daily, t]);

  // The y range spans everything drawn in the window, as Plotly's autorange
  // does: the price, the averages, the fills (a lot bought below this year's
  // low still shows, at the price it was bought at) and the event diamonds a
  // step above their bar's high. Leaving the fills out is how a marker ends up
  // drawn off the plot, which reads as a fill that is not there.
  const range = useMemo(() => {
    const window = <T,>(series: (T | null | undefined)[]) => series.slice(from, to + 1);
    const price = candles
      ? [window(high), window(low), window(close)]
      : [window(close)];
    const overlays = ["SMA20", "SMA50", "SMA200"]
      .map((key) => bars.series[key])
      .filter((series): series is (number | null)[] => Boolean(series))
      .map((series) => window(series));
    const marked = fills
      .filter((fill) => fill.index >= from && fill.index <= to)
      .map((fill) => fill.trade.price);
    const diamonds = [...marks.kinds.keys()]
      .filter((index) => index >= from && index <= to)
      .map((index) => diamondY(index));
    return bounds([...price, ...overlays, marked, diamonds]);
  }, [bars.series, candles, close, high, low, from, to, fills, marks]);

  if (!range || n === 0) return null;

  const y = scale(range.lo, range.hi, box.height - box.bottom, box.top);
  const label = labeller(lang, intraday);
  // A 390px screen fits about three date labels; more of them overlap into an
  // unreadable smear.
  const axisLabels = mobile ? 3 : 6;

  /** Which bar a pointer at `x` is over. Clamped: a drag off the edge means the edge. */
  const indexAt = (x: number) =>
    Math.max(from, Math.min(to, from + Math.floor((x - box.left) / band)));

  const finish = (x: number) => {
    if (!drag) return;
    const end = indexAt(x);
    const lo = Math.min(drag.from, end);
    const hi = Math.max(drag.from, end);
    setDrag(null);
    if (hi - lo < MIN_SPAN) return;
    setZoom({ from: lo, to: hi });
    report(lo, hi);
  };

  const report = (lo: number, hi: number) => {
    let a = -1;
    let z = -1;
    for (let i = lo; i <= hi; i++) {
      const value = close[i];
      if (value === null || value === undefined) continue;
      if (a < 0) a = i;
      z = i;
    }
    const start = a < 0 ? null : close[a];
    const end = z < 0 ? null : close[z];
    // Null rather than zero whenever the window says nothing: fewer than two
    // priced bars in view, or a first price of zero. A gap is skipped rather
    // than read as a price — anchoring on one would invent a move.
    if (a < 0 || z === a || !start || end === null || end === undefined) {
      onWindow(null);
      return;
    }
    onWindow({
      pct: (end / start - 1) * 100,
      from: label(bars.dates[a] ?? ""),
      to: label(bars.dates[z] ?? ""),
    });
  };

  const reset = () => {
    setZoom(null);
    setDrag(null);
    onWindow(null);
  };

  // The area fade runs against an invisible baseline pinned at the window's
  // low. Filling to zero would drag the axis down and flatten a £200 stock's
  // whole year into the top inch of the card.
  const line = segments(close, from, to);
  const area = line
    .map((run) => {
      const head = run[0];
      const tail = run[run.length - 1];
      if (head === undefined || tail === undefined) return "";
      const path = run
        .map((i) => `${xOf(i).toFixed(1)},${y(close[i] as number).toFixed(1)}`)
        .join(" L ");
      return `M ${xOf(head).toFixed(1)},${(box.height - box.bottom).toFixed(1)} L ${path} L ${xOf(tail).toFixed(1)},${(box.height - box.bottom).toFixed(1)} Z`;
    })
    .join(" ");

  const overlays: [string, string, string][] = [
    ["SMA20", colors.smaFast, t("ticker.sma20_label")],
    ["SMA50", colors.smaSlow, "SMA50"],
    ["SMA200", smaLong, "SMA200"],
  ];
  const drawn = overlays.filter(([key]) =>
    bars.series[key]?.slice(from, to + 1).some((value) => value !== null),
  );

  const legend = [
    { label: t("ticker.price"), color: candles ? colors.candleUp : colors.brandAccent },
    ...drawn.map(([, color, name]) => ({ label: name, color })),
    ...(fills.some((fill) => fill.trade.action === "buy")
      ? [{ label: t("ticker.my_buys"), color: colors.textPrimary }]
      : []),
    ...(fills.some((fill) => fill.trade.action === "sell")
      ? [{ label: t("ticker.my_sells"), color: colors.down }]
      : []),
    // One entry per kind actually drawn, and each in the colour its verticals
    // are stroked with: a dividend marked "Results" is a worse legend than no
    // legend, and the two are drawn in different colours for that reason.
    ...([...marks.kinds.values()].includes("dividend")
      ? [{ label: t("ticker.ev_dividends"), color: colors.warn }]
      : []),
    ...([...marks.kinds.values()].includes("results")
      ? [{ label: t("ticker.ev_results"), color: colors.smaSlow }]
      : []),
  ];

  const tip = hover === null ? null : tooltip(hover);

  /**
   * Streamlit's unified box for one bar, row for row and in its trace order:
   * the price (and open/high/low on candles), SMA20, SMA50, SMA200 where they
   * have a value, the fills on that bar, then its dividend and results
   * diamonds. See `hover.ts` for what each row says.
   */
  function tooltip(index: number): { title: string; lines: TipLine[] } {
    const priceSwatch = candles ? colors.candleUp : colors.brandAccent;
    const lines: TipLine[] = priceRows(
      {
        close: close[index] ?? null,
        prev: index > 0 ? (close[index - 1] ?? null) : null,
        ohlc: candles
          ? {
              open: open[index] ?? null,
              high: high[index] ?? null,
              low: low[index] ?? null,
            }
          : null,
        swatch: priceSwatch,
      },
      t,
    );
    for (const [key, color, name] of overlays) {
      const value = averageRow(name, bars.series[key]?.[index] ?? null, color);
      if (value) lines.push(value);
    }
    // The return on a buy is to the range's LAST close, whatever window is
    // zoomed — Streamlit's `last`, the same figure the price metric prints.
    const lastClose = latest(close);
    for (const fill of fills.filter((one) => one.index === index)) {
      const buy = fill.trade.action === "buy";
      lines.push(
        ...fillRows(
          fill.trade,
          {
            last: lastClose,
            avgCost,
            swatch: buy ? colors.textPrimary : colors.down,
          },
          t,
        ),
      );
    }
    const kind = marks.kinds.get(index);
    if (kind) {
      lines.push(
        ...eventRows(
          marks.lines.get(index) ?? [],
          kind === "dividend" ? colors.warn : colors.smaSlow,
        ),
      );
    }
    return { title: hoverTitle(bars.dates[index] ?? "", intraday), lines };
  }

  return (
    <div className="tk-plot">
      <Chart
        frame={box}
        label={t("ticker.price")}
        className="tk-price"
        onPointer={(x) => setHover(indexAt(x))}
        onLeave={() => {
          setHover(null);
          setDrag(null);
        }}
        // A phone pins the window: a finger drag has to scroll the page.
        onDown={
          mobile ? undefined : (x) => setDrag({ from: indexAt(x), to: indexAt(x) })
        }
        onUp={mobile ? undefined : finish}
        onDouble={mobile ? undefined : reset}
      >
        <YGrid
          frame={box}
          lo={range.lo}
          hi={range.hi}
          format={(v) => money(v, v >= 100 ? 0 : 2)}
        />

        {/* Corporate events, as Streamlit draws them: a quiet dotted
            vertical, the kind's letter on top in its colour ("d" dividend,
            "r" results), and a small diamond over the bar's high whose row in
            the tooltip says what it was. */}
        {[...marks.kinds.entries()]
          .filter(([index]) => index >= from && index <= to)
          .map(([index, kind]) => {
            const color = kind === "dividend" ? colors.warn : colors.smaSlow;
            const cx = xOf(index);
            const cy = y(diamondY(index));
            return (
              <g key={`ev-${index}`}>
                <line
                  className="tk-event"
                  x1={cx}
                  x2={cx}
                  y1={box.top}
                  y2={box.height - box.bottom}
                  stroke={colors.eventLine}
                />
                <text
                  className="tk-event-tag"
                  x={cx}
                  y={box.top - 2}
                  textAnchor="middle"
                  fill={color}
                >
                  {kind === "dividend" ? "d" : "r"}
                </text>
                <path
                  d={`M ${cx} ${cy - 4} L ${cx + 4} ${cy} L ${cx} ${cy + 4} L ${cx - 4} ${cy} Z`}
                  fill={color}
                  stroke={colors.surfacePage}
                  strokeWidth={1}
                />
              </g>
            );
          })}

        {candles ? (
          <g>
            {Array.from({ length: to - from + 1 }, (_, offset) => {
              const index = from + offset;
              const o = open[index];
              const c = close[index];
              const h = high[index];
              const l = low[index];
              if (o == null || c == null || h == null || l == null) return null;
              const up = c >= o;
              const color = up ? colors.candleUp : colors.candleDown;
              const width = Math.max(1, band * 0.62);
              const top = y(Math.max(o, c));
              const height = Math.max(1, Math.abs(y(o) - y(c)));
              return (
                <g key={`c-${index}`}>
                  <line
                    x1={xOf(index)}
                    x2={xOf(index)}
                    y1={y(h)}
                    y2={y(l)}
                    stroke={color}
                    strokeWidth={1}
                  />
                  <rect
                    x={xOf(index) - width / 2}
                    y={top}
                    width={width}
                    height={height}
                    fill={color}
                  />
                </g>
              );
            })}
          </g>
        ) : (
          <g>
            <path d={area} fill={colors.accentArea} stroke="none" />
            {line.map((run) => {
              const head = run[0];
              return (
                <polyline
                  key={`p-${head}`}
                  className="tk-line"
                  points={run
                    .map(
                      (i) => `${xOf(i).toFixed(1)},${y(close[i] as number).toFixed(1)}`,
                    )
                    .join(" ")}
                  stroke={colors.brandAccent}
                  strokeWidth={2}
                />
              );
            })}
          </g>
        )}

        {drawn.map(([key, color]) => {
          const series = bars.series[key];
          if (!series) return null;
          return segments(series, from, to).map((run) => (
            <polyline
              key={`${key}-${run[0]}`}
              className="tk-line"
              points={run
                .map((i) => `${xOf(i).toFixed(1)},${y(series[i] as number).toFixed(1)}`)
                .join(" ")}
              stroke={color}
              strokeWidth={1.4}
            />
          ));
        })}

        {/* The reader's own fills: Streamlit's 12px triangles, buys up in the
            primary text colour and sells down in the loss colour, outlined in
            the canvas colour so they read against candles of either sign. */}
        {fills
          .filter((fill) => fill.index >= from && fill.index <= to)
          .map((fill, at) => {
            const cx = xOf(fill.index);
            const cy = y(fill.trade.price);
            const buy = fill.trade.action === "buy";
            const size = 6;
            const path = buy
              ? `M ${cx} ${cy - size} L ${cx + size} ${cy + size} L ${cx - size} ${cy + size} Z`
              : `M ${cx} ${cy + size} L ${cx + size} ${cy - size} L ${cx - size} ${cy - size} Z`;
            return (
              <path
                key={`f-${fill.index}-${at}`}
                d={path}
                fill={buy ? colors.textPrimary : colors.down}
                stroke={colors.surfacePage}
                strokeWidth={1.5}
              />
            );
          })}

        {/* The drag, while it is happening. */}
        {drag && hover !== null ? (
          <rect
            className="tk-brush"
            x={Math.min(xOf(drag.from), xOf(hover)) - band / 2}
            y={box.top}
            width={Math.max(band, Math.abs(xOf(hover) - xOf(drag.from)) + band)}
            height={plotHeight(box)}
          />
        ) : null}

        {hover !== null ? (
          <line
            className="tk-cross"
            x1={xOf(hover)}
            x2={xOf(hover)}
            y1={box.top}
            y2={box.height - box.bottom}
          />
        ) : null}

        {/* Three labels on a phone, where more of them smear together. */}
        <g className="tk-xlabels">
          {Array.from({ length: axisLabels }, (_, slot) => {
            const index =
              from + Math.round(((to - from) * slot) / Math.max(1, axisLabels - 1));
            const stamp = bars.dates[index];
            if (stamp === undefined) return null;
            return (
              <text
                key={`x-${index}`}
                x={Math.min(
                  box.width - box.right - 18,
                  Math.max(box.left + 18, xOf(index)),
                )}
                y={box.height - 6}
                textAnchor="middle"
              >
                {label(stamp)}
              </text>
            );
          })}
        </g>
      </Chart>

      {tip && hover !== null ? (
        <Tooltip frame={box} x={xOf(hover)} title={tip.title} lines={tip.lines} />
      ) : null}

      <Legend items={legend} />
    </div>
  );
}
