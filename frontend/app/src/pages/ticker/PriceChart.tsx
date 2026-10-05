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
import { useWidth } from "../../shell/useWidth";
import {
  cycleLine,
  cycleTag,
  dividendLine,
  resultsLines,
  snap,
  type EventLine,
} from "./events";
import { latest, money, signed, signedPercent, type Translate } from "./format";
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
  YLabels,
  bounds,
  fitHeight,
  frame,
  plotHeight,
  plotWidth,
  scale,
  type TipLine,
} from "./plot";
import type { Marker, Overlay } from "./layout";
import type { Bars, CycleEvent, EarningsEvent, Trade } from "./types";

const ALL_OVERLAYS: readonly Overlay[] = ["SMA20", "SMA50", "SMA200"];
const ALL_MARKERS: readonly Marker[] = ["results", "dividends"];

/** What `render` has no layout to measure: the width a test or the server sees. */
const FALLBACK_WIDTH = 760;
/** The tallest the plot is drawn on a phone; `fitHeight` squares it up from its width. */
const PHONE_HEIGHT = 300;
/** Room an axis label needs along the x axis, date and gap together. */
const LABEL_SLOT = 120;

/** Fewer bars than this in a drag is a mis-click, not a window somebody picked. */
const MIN_SPAN = 3;

/** How far from a fill's triangle, in px, the pointer still reads that fill. */
const SNAP = 8;

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
function labeller(
  lang: string,
  intraday: boolean,
  short = false,
): (stamp: string) => string {
  const format = new Intl.DateTimeFormat(
    lang || undefined,
    intraday
      ? { hour: "2-digit", minute: "2-digit" }
      : short
        ? { month: "short", year: "2-digit" }
        : { day: "numeric", month: "short", year: "2-digit" },
  );
  return (stamp: string) => {
    const at = Date.parse(stamp.replace(" ", "T"));
    return Number.isNaN(at) ? stamp.slice(0, 10) : format.format(new Date(at));
  };
}

/** What a series did between two of its bars. */
export type Move = { a: number; z: number; start: number; end: number; pct: number };

/**
 * The move between the first and last priced bars of `lo..hi`. Null rather
 * than zero whenever the window says nothing: fewer than two priced bars in
 * it, or a first price of zero. A gap is skipped rather than read as a price
 * — anchoring on one would invent a move.
 */
export function moveBetween(
  close: readonly (number | null | undefined)[],
  lo: number,
  hi: number,
): Move | null {
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
  if (a < 0 || z === a || !start || end === null || end === undefined) return null;
  return { a, z, start, end, pct: (end / start - 1) * 100 };
}

export function PriceChart({
  bars,
  events,
  cycle = [],
  trades,
  avgCost,
  candles,
  overlays: shown = ALL_OVERLAYS,
  markers = ALL_MARKERS,
  mobile,
  onWindow,
  t,
}: {
  bars: Bars;
  events: EarningsEvent[];
  /** A coin's halvings, ETF approvals, the Merge — drawn when `markers` says. */
  cycle?: CycleEvent[];
  trades: Trade[];
  /** The blended entry, so a single lot can be read against the position. */
  avgCost: number | null;
  candles: boolean;
  /**
   * The averages this kind of asset is read by (`layout.ts`). A money-market
   * fund's price is a straight line: an average laid over it is a second
   * straight line that says nothing.
   */
  overlays?: readonly Overlay[];
  /** The corporate events worth a vertical on this kind of chart. */
  markers?: readonly Marker[];
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
  // Two bars being compared (`Chart`'s `onSpan`), in bar order.
  const [span, setSpan] = useState<{ a: number; b: number } | null>(null);
  const [wrap, width] = useWidth(FALLBACK_WIDTH);
  // What the reader switched off in the legend: overlay keys and marker kinds.
  // The 200-day average starts off on a phone, where three lines and the price
  // are more than a 350px plot can carry.
  const [hidden, setHidden] = useState<ReadonlySet<string>>(
    () => new Set(mobile ? ["SMA200"] : []),
  );
  const toggle = (key: string) =>
    setHidden((now) => {
      const next = new Set(now);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  // A new range is a new set of bars, and the window somebody dragged out of
  // the old ones does not survive it: keeping the zoom would apply yesterday's
  // bar indices to a different series, and keeping the readout would caption
  // the chart with a change it no longer shows.
  useEffect(() => {
    setZoom(null);
    setDrag(null);
    setSpan(null);
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

  // Drawn at the width the card really has, so a unit is a pixel and the
  // labels print at the size they say. On a phone the y labels move inside the
  // plot: a 48px gutter is a seventh of the screen.
  const box = frame({
    width,
    height: fitHeight(width, mobile ? PHONE_HEIGHT : 340),
    left: mobile ? 8 : 48,
    right: 14,
    // Room over the plot for the events' letter tags.
    top: 20,
    bottom: 26,
  });
  const inner = plotWidth(box);
  const band = inner / Math.max(1, to - from + 1);
  const xOf = (index: number) => box.left + (index - from + 0.5) * band;
  /**
   * Where an event's diamond sits: 1% over its bar's high — above the candle
   * it annotates, never on it. The close on a bar with no high, which a line
   * chart's series can be.
   */
  const diamondY = (index: number) => (high[index] ?? close[index] ?? 0) * 1.01;

  // Every buy and sell dated inside the range, on the bar it belongs to, so an
  // entry older than the window is off its left edge rather than stacked onto
  // the first candle.
  const fills = useMemo<Fill[]>(() => placeFills(trades, days), [trades, days]);

  const marks = useMemo(() => {
    const lines = new Map<number, EventLine[]>();
    const kinds = new Map<number, "dividend" | "results" | "cycle">();
    // The letter a cycle vertical carries: one event per bar is all a coin
    // has ever had, and the last one written wins if that ever changes.
    const tags = new Map<number, string>();
    (markers.includes("dividends") ? (bars.dividends ?? []) : []).forEach(
      (value, index) => {
        const day = days[index];
        if (!value || day === undefined) return;
        const at = close[index] ?? null;
        const exDate = daily || intraday ? day : null;
        lines.set(index, [
          ...(lines.get(index) ?? []),
          dividendLine(value, at, exDate, t),
        ]);
        kinds.set(index, "dividend");
      },
    );
    const first = days[0] ?? "";
    const last = days[days.length - 1] ?? "";
    for (const event of markers.includes("results") ? events : []) {
      if (event.date < first || event.date > last) continue;
      const index = snap(days, event.date);
      lines.set(index, [
        ...(lines.get(index) ?? []),
        ...resultsLines(event, close, index, daily, t),
      ]);
      kinds.set(index, "results");
    }
    for (const event of markers.includes("cycle") ? cycle : []) {
      if (event.date < first || event.date > last) continue;
      const line = cycleLine(event.kind, event.date, t);
      if (!line) continue;
      const index = snap(days, event.date);
      lines.set(index, [...(lines.get(index) ?? []), line]);
      kinds.set(index, "cycle");
      tags.set(index, cycleTag(event.kind));
    }
    return { lines, kinds, tags };
  }, [bars.dividends, days, close, events, cycle, markers, daily, intraday, t]);

  /** A bar's marker kind, unless the reader switched that kind off. */
  const kindAt = (index: number) => {
    const kind = marks.kinds.get(index);
    return kind && !hidden.has(kind) ? kind : undefined;
  };
  const visibleMarks = [...marks.kinds.entries()].filter(
    ([, kind]) => !hidden.has(kind),
  );

  const markColor = (kind: "dividend" | "results" | "cycle") =>
    kind === "dividend"
      ? colors.warn
      : kind === "cycle"
        ? colors.brandAccent
        : colors.smaSlow;

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
    const overlays = shown
      .filter((key) => !hidden.has(key))
      .map((key) => bars.series[key])
      .filter((series): series is (number | null)[] => Boolean(series))
      .map((series) => window(series));
    const marked = fills
      .filter((fill) => fill.index >= from && fill.index <= to)
      .map((fill) => fill.trade.price);
    const diamonds = [...marks.kinds.entries()]
      .filter(([index, kind]) => index >= from && index <= to && !hidden.has(kind))
      .map(([index]) => index)
      .map((index) => diamondY(index));
    return bounds([...price, ...overlays, marked, diamonds]);
  }, [bars.series, shown, hidden, candles, close, high, low, from, to, fills, marks]);

  if (!range || n === 0) return null;

  const y = scale(range.lo, range.hi, box.height - box.bottom, box.top);
  const label = labeller(lang, intraday);
  // Three labels over a phone's plot have no room for a day each: the month is
  // what tells them apart, so long as the window is wider than a month.
  const axisLabel = labeller(lang, intraday, mobile && n > 40);
  // A 390px screen fits about three date labels; more of them overlap into an
  // unreadable smear. Wider, as many as the plot has room for.
  const axisLabels = mobile
    ? 3
    : Math.max(2, Math.min(7, Math.floor(plotWidth(box) / LABEL_SLOT)));

  /** Which bar a pointer at `x` is over. Clamped: a drag off the edge means the edge. */
  const indexAt = (x: number) =>
    Math.max(from, Math.min(to, from + Math.floor((x - box.left) / band)));

  // A fill is a 12px triangle over a bar a pixel or two wide: pointing at the
  // triangle has to read the fill, not whichever bar is under its edge.
  const markerAt = (x: number) => {
    let best: number | null = null;
    for (const fill of fills) {
      if (fill.index < from || fill.index > to) continue;
      const gap = Math.abs(xOf(fill.index) - x);
      if (gap <= SNAP && (best === null || gap < Math.abs(xOf(best) - x))) {
        best = fill.index;
      }
    }
    return best ?? indexAt(x);
  };

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
    const move = moveBetween(close, lo, hi);
    onWindow(
      move && {
        pct: move.pct,
        from: label(bars.dates[move.a] ?? ""),
        to: label(bars.dates[move.z] ?? ""),
      },
    );
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

  const overlays = (
    [
      ["SMA20", colors.smaFast, t("ticker.sma20_label")],
      ["SMA50", colors.smaSlow, "SMA50"],
      ["SMA200", smaLong, "SMA200"],
    ] as [Overlay, string, string][]
  ).filter(([key]) => shown.includes(key));
  // Those with a value in view stay in the legend even when switched off, so
  // the reader can switch them back on.
  const present = overlays.filter(([key]) =>
    bars.series[key]?.slice(from, to + 1).some((value) => value !== null),
  );
  const drawn = present.filter(([key]) => !hidden.has(key));

  const legend = [
    { label: t("ticker.price"), color: candles ? colors.candleUp : colors.brandAccent },
    ...present.map(([key, color, name]) => ({ key, label: name, color })),
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
      ? [{ key: "dividend", label: t("ticker.ev_dividends"), color: colors.warn }]
      : []),
    ...([...marks.kinds.values()].includes("results")
      ? [{ key: "results", label: t("ticker.ev_results"), color: colors.smaSlow }]
      : []),
    ...([...marks.kinds.values()].includes("cycle")
      ? [{ key: "cycle", label: t("ticker.ev_cycle"), color: colors.brandAccent }]
      : []),
  ];

  // A span of one bar is a mouse anchor just dropped: until the pointer moves
  // off it there is nothing to compare, and the bar reads as usual.
  const measure = span && span.b > span.a ? moveBetween(close, span.a, span.b) : null;
  const tip = measure ? spanTip(measure) : hover === null ? null : tooltip(hover);

  /**
   * The hover box for one bar, row for row and in trace order: the price (and
   * open/high/low on candles), SMA20, SMA50, SMA200 where they have a value,
   * the fills on that bar, then its dividend and results diamonds. See
   * `hover.ts` for what each row says.
   */
  function tooltip(index: number): { title: string; lines: TipLine[]; more: boolean } {
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
    const averages: TipLine[] = [];
    for (const [key, color, name] of overlays) {
      const value = averageRow(name, bars.series[key]?.[index] ?? null, color);
      if (value) averages.push(value);
    }
    // On a phone the reading is a strip, and the averages are the rows the
    // legend's lines already tell: the fills and events go ahead of them.
    if (!mobile) lines.push(...averages);
    const plain = lines.length;
    // The return on a buy is to the range's LAST close, whatever window is
    // zoomed — the same figure the price metric prints.
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
    const kind = kindAt(index);
    if (kind) {
      lines.push(...eventRows(marks.lines.get(index) ?? [], markColor(kind)));
    }
    const more = lines.length > plain;
    if (mobile) lines.push(...averages);
    return { title: hoverTitle(bars.dates[index] ?? "", intraday), lines, more };
  }

  /** What moved between two bars: both closes, the change, how many sessions. */
  function spanTip(move: Move): {
    title: string;
    lines: TipLine[];
    more: boolean;
  } {
    // A coin under a unit needs the decimals a share price does not.
    const digits = Math.abs(move.start) < 1 ? 4 : 2;
    const delta = move.end - move.start;
    const tone = delta > 0 ? "up" : delta < 0 ? "down" : undefined;
    const title = `${hoverTitle(bars.dates[move.a] ?? "", intraday)} → ${hoverTitle(
      bars.dates[move.z] ?? "",
      intraday,
    )}`;
    return {
      title,
      more: false,
      // The change first: on a phone the reading is one strip, and what does
      // not fit its width is cut from the end.
      lines: [
        {
          text: `${signed(delta, digits)} ${signedPercent(move.pct / 100)}`,
          parts: [
            { text: `${t("ticker.span_change")} `, tone: "dim" },
            {
              text: `${signed(delta, digits)} ${signedPercent(move.pct / 100)}`,
              bold: true,
              tone,
            },
          ],
        },
        {
          text: `${money(move.start, digits)} → ${money(move.end, digits)}`,
          parts: [
            { text: `${t("ticker.price")} `, tone: "dim" },
            { text: `${money(move.start, digits)} → ${money(move.end, digits)}` },
          ],
        },
        {
          text: t("ticker.span_bars", { count: move.z - move.a }),
          parts: [
            { text: t("ticker.span_bars", { count: move.z - move.a }), tone: "dim" },
          ],
        },
      ],
    };
  }

  return (
    <div className="tk-plot" ref={wrap}>
      <Chart
        frame={box}
        label={t("ticker.price")}
        className="tk-price"
        onPointer={(x) => setHover(markerAt(x))}
        onLeave={() => {
          setHover(null);
          setDrag(null);
          setSpan(null);
        }}
        onSpan={(pair) =>
          setSpan(
            pair && {
              a: indexAt(Math.min(pair[0], pair[1])),
              b: indexAt(Math.max(pair[0], pair[1])),
            },
          )
        }
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
          format={(v) => money(v, range.hi >= 100 ? 0 : 2)}
          inside={mobile}
        />

        {/* Corporate events: a quiet dotted vertical, the kind's letter on top
            in its colour ("d" dividend, "r" results), and a small diamond over
            the bar's high whose row in the tooltip says what it was. On weekly
            or monthly bars only the diamond: forty years of quarterly dividends
            is a vertical every third candle, a curtain over the chart rather
            than a marker. */}
        {visibleMarks
          .filter(([index]) => index >= from && index <= to)
          .map(([index, kind]) => {
            const color = markColor(kind);
            const cx = xOf(index);
            const cy = y(diamondY(index));
            return (
              <g key={`ev-${index}`}>
                {/* A coin has a handful of cycle events in its whole life, so
                    they keep their vertical on weekly bars too — the long
                    ranges are where a halving is worth seeing. */}
                {daily || intraday || kind === "cycle" ? (
                  <>
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
                      {kind === "cycle"
                        ? (marks.tags.get(index) ?? "")
                        : kind === "dividend"
                          ? "d"
                          : "r"}
                    </text>
                  </>
                ) : null}
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

        {/* The reader's own fills: 12px triangles, buys up in the primary
            text colour and sells down in the loss colour, outlined in the
            canvas colour so they read against candles of either sign. */}
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

        {/* The two bars being compared, and the stretch between them. */}
        {span ? (
          <g className="tk-span">
            {span.b > span.a ? (
              <rect
                x={xOf(span.a)}
                y={box.top}
                width={xOf(span.b) - xOf(span.a)}
                height={plotHeight(box)}
              />
            ) : null}
            <line
              x1={xOf(span.a)}
              x2={xOf(span.a)}
              y1={box.top}
              y2={box.height - box.bottom}
            />
            <line
              x1={xOf(span.b)}
              x2={xOf(span.b)}
              y1={box.top}
              y2={box.height - box.bottom}
            />
          </g>
        ) : null}

        {hover !== null && !measure ? (
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
                // The end labels hang inward: centred on the plot's edge, a
                // date's outer half would be cut by the card.
                x={
                  slot === 0
                    ? box.left
                    : slot === axisLabels - 1
                      ? box.width - box.right
                      : xOf(index)
                }
                y={box.height - 6}
                textAnchor={
                  slot === 0 ? "start" : slot === axisLabels - 1 ? "end" : "middle"
                }
              >
                {axisLabel(stamp)}
              </text>
            );
          })}
        </g>
        <YLabels
          frame={box}
          lo={range.lo}
          hi={range.hi}
          format={(v) => money(v, range.hi >= 100 ? 0 : 2)}
          inside={mobile}
        />
      </Chart>

      {tip && (measure || hover !== null) ? (
        <Tooltip
          frame={box}
          x={measure ? (xOf(measure.a) + xOf(measure.z)) / 2 : xOf(hover ?? 0)}
          title={tip.title}
          lines={tip.lines}
          more={tip.more}
        />
      ) : null}

      <Legend items={legend} onToggle={toggle} hidden={hidden} />
      {/* How to measure, for the input this device has. */}
      <p className="tk-hint">
        <span className="tk-hint-touch">{t("ticker.span_hint_touch")}</span>
        <span className="tk-hint-mouse">{t("ticker.span_hint_mouse")}</span>
      </p>
    </div>
  );
}
