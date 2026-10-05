/**
 * The glance card's sparkline: what went in against what it is worth.
 *
 * The same pair of lines the Portfolio page charts in full, at a size that
 * answers one question — is the gap opening or closing — without asking anyone
 * to read an axis. The band between them carries the sign, which is the whole
 * reading at this size: green means the book is worth more than what was put
 * into it.
 *
 * Two fingers, or a secondary click with a mouse (`useSpan`), compare two days:
 * how much the value moved, how much of it was money put in, and the rest —
 * what the market did. Amounts only, since money flowed through the span.
 *
 * Fails to nothing. When the price span cannot be built the sparkline drops
 * out and the rest of the card stays: a glance card that renders an error
 * where a picture goes is worse than one that is simply a little shorter.
 */

import { useCallback, useRef, useState } from "react";
import { useT, useLang } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { token } from "../../shell/theme";
import { useSpan } from "../../shell/useSpan";
import { useTouchHold } from "../../shell/useTouchHold";
import { money, monthDay, percent } from "./format";
import { Kpi, chipFor } from "../../ui/Kpi";
import type { History } from "./types";

const WIDTH = 320;
const HEIGHT = 56;

/** Trailing sessions the average tile folds in — a calendar month of trading. */
const SMA_WINDOW = 20;

/**
 * The windows the selector offers, in the order they widen, and how many
 * calendar days back from the series' last day each one reaches.
 *
 * The labels are the keys, except the week and the month, which read as words
 * ("Semana", "Mes") like the market card's selector does. It opens on `1y`: a year is the view the home card is for, and `all` is the
 * wrong one for a book that took a transfer, because one step dwarfs every
 * month of market movement around it. The spans are `_HISTORY_SPANS` in
 * `api/routes/portfolio.py`, counted from the same end, so a slice here is the
 * window the server would have cut.
 */
const RANGES = {
  "1w": 7,
  "1m": 30,
  "6m": 182,
  "1y": 365,
  "2y": 730,
  "5y": 1825,
} as const;

type Range = keyof typeof RANGES;

/** The windows labelled by a word, and the word. */
const WORDS = {
  "1w": "home.market_window_week",
  "1m": "home.market_window_month",
} as const;

/** The window the glance fetches: the widest the selector offers. */
export const SPARK_WINDOW: Range = "5y";

/**
 * The points of `history` inside `range`, counted back from its last day.
 *
 * Sliced here rather than refetched per range, and that is the point: the
 * history arrives in the same burst as the tiles above it (`Glance`), so the
 * line ends on the "Valor hoy" printed over it. A refetch on every click
 * read whatever download the server held by then — fifteen minutes later, a
 * different one — and the period's max sat under the tile's value. Only the
 * level lines are drawn, and they are absolute: unlike the return index, which
 * the server rebases per window, they survive slicing.
 */
export function slice(history: History, range: Range): History["points"] {
  const last = history.points[history.points.length - 1];
  if (!last) return [];
  const from = new Date(`${last.date}T00:00:00Z`);
  from.setUTCDate(from.getUTCDate() - RANGES[range]);
  const cutoff = from.toISOString().slice(0, 10);
  return history.points.filter((point) => point.date >= cutoff);
}

export function Spark({ history }: { history: History | null }) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const [range, setRange] = useState<Range>("1y");
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  // Two days being compared, in day order. The span's units are day indices:
  // the wrap's handlers read the day before handing it on.
  const [measure, setMeasure] = useState<{ from: number; to: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const drop = useCallback(() => {
    setHoverIndex(null);
    setMeasure(null);
  }, []);
  useTouchHold(wrap, hoverIndex !== null || measure !== null, drop);
  const spanned = useSpan((pair) => {
    if (!pair) return setMeasure(null);
    setHoverIndex(null);
    setMeasure({ from: Math.min(...pair), to: Math.max(...pair) });
  });
  // The history failed with the tiles still standing: no picture, and no
  // selector either — every range is a slice of the same missing array.
  if (!history) return null;
  const selector = (
    <div className="hm-segmented" role="group" aria-label={t("home.chart_value")}>
      {(Object.keys(RANGES) as Range[]).map((key) => (
        <button
          key={key}
          type="button"
          className={key === range ? "hm-seg hm-seg-on" : "hm-seg"}
          aria-pressed={key === range}
          onClick={() => {
            setRange(key);
            setMeasure(null);
          }}
        >
          {key in WORDS ? t(WORDS[key as keyof typeof WORDS]) : key}
        </button>
      ))}
    </div>
  );
  // Both legs or the day is not comparable: a value with no reference line has
  // nothing to be shaded against.
  const days: { date: string; injected: number; value: number }[] = [];
  for (const point of slice(history, range)) {
    if (point.injected !== null && point.value !== null) {
      days.push({ date: point.date, injected: point.injected, value: point.value });
    }
  }
  // The selector outlives a short window: one with too few points to draw must
  // still let somebody pick a wider one, or the card traps them there.
  if (days.length < 2) return <div className="hm-spark-head">{selector}</div>;

  const levels = days.flatMap((day) => [day.injected, day.value]);
  const floor = Math.min(...levels);
  const span = Math.max(...levels) - floor || Math.abs(floor) || 1;
  const x = (index: number) => (index / (days.length - 1)) * WIDTH;
  const y = (value: number) => (1 - (value - floor) / span) * (HEIGHT - 2) + 1;

  const line = (pick: (day: (typeof days)[number]) => number) =>
    days.map((day, index) => `${x(index)},${y(pick(day))}`).join(" ");

  // One polygon per run of the same sign, so the colour changes exactly where
  // the two lines cross rather than across the whole shape.
  const bands: { gain: boolean; path: string }[] = [];
  let start = 0;
  for (let index = 1; index <= days.length; index += 1) {
    const ending = index === days.length;
    const gain = days[start]!.value >= days[start]!.injected;
    if (!ending && days[index]!.value >= days[index]!.injected === gain) continue;
    const run = days.slice(start, Math.min(index + 1, days.length));
    const top = run.map((day, i) => `${x(start + i)},${y(day.value)}`);
    const bottom = run.map((day, i) => `${x(start + i)},${y(day.injected)}`).reverse();
    bands.push({ gain, path: `M${top.join("L")}L${bottom.join("L")}Z` });
    if (!ending) start = index;
  }

  const high = money(Math.max(...levels), base, lang);
  const low = money(floor, base, lang);

  // The peak of the value line itself, not of whichever of the two series
  // happens to be higher — "period max" is a claim about what the book was
  // worth, not about what went into it.
  const maxValue = Math.max(...days.map((day) => day.value));
  const maxIndex = days.findIndex((day) => day.value === maxValue);

  /**
   * What the hover label says about one day, in this order: worth (colored by
   * gain or loss), what went in, and the gap between them as an amount and a
   * percent.
   */
  const tipRows = (day: (typeof days)[number]) => {
    const gain = day.value >= day.injected;
    const pnl = day.value - day.injected;
    const pct = day.injected
      ? percent(pnl / day.injected, lang, { signed: true })
      : null;
    return [
      {
        label: t("home.chart_value"),
        value: money(day.value, base, lang),
        color: gain ? token("up") : token("down"),
      },
      { label: t("home.chart_injected"), value: money(day.injected, base, lang) },
      {
        label: "",
        value: `${money(pnl, base, lang, { signed: true })}${pct ? ` (${pct})` : ""}`,
      },
    ];
  };

  /** Which day a pointer sits over, from its position over the plot. */
  const dayAt = (clientX: number) => {
    const box = wrap.current?.getBoundingClientRect();
    if (!box || !box.width) return null;
    const fraction = (clientX - box.left) / box.width;
    return Math.max(
      0,
      Math.min(days.length - 1, Math.round(fraction * (days.length - 1))),
    );
  };

  // A comparison drawn on a window since narrowed points past its days.
  const compared =
    measure && measure.to < days.length && measure.to > measure.from ? measure : null;
  const hovered = hoverIndex === null || measure ? null : days[hoverIndex];
  const tipAt = compared ? (compared.from + compared.to) / 2 : hoverIndex;
  const tipLeft = tipAt === null ? 0 : (x(tipAt) / WIDTH) * 100;
  const tipTitle = compared
    ? [compared.from, compared.to]
        .map((index) => monthDay(days[index]!.date, t) ?? days[index]!.date)
        .join(" → ")
    : hovered
      ? (monthDay(hovered.date, t) ?? hovered.date)
      : null;

  /** What the label says between the two days being compared. */
  const spanRows = (from: (typeof days)[number], to: (typeof days)[number]) => {
    const moved = to.value - from.value;
    const put = to.injected - from.injected;
    const signed = (value: number) => money(value, base, lang, { signed: true });
    return [
      {
        label: t("home.chart_value"),
        value: signed(moved),
        color: moved >= 0 ? token("up") : token("down"),
      },
      { label: t("home.chart_injected"), value: signed(put) },
      { label: t("home.chart_market"), value: signed(moved - put) },
    ];
  };
  const rows = compared
    ? spanRows(days[compared.from]!, days[compared.to]!)
    : hovered
      ? tipRows(hovered)
      : null;
  const indexAt = (event: { clientX: number }) => dayAt(event.clientX) ?? 0;

  return (
    <>
      {/* One toolbar: the key on the left, the window on the right. Stacked,
          the selector floated over an empty row and the key sat alone under
          it — two rows of chrome for one line of controls. Two lines with no
          key are a picture of nothing in particular: the dashed one is what
          went in, the solid one what it is worth, and the band between them
          is the answer the card exists to give. */}
      <div className="hm-spark-head">
        <ul className="hm-spark-legend">
          <li>
            <span className="hm-spark-key hm-spark-injected" />
            {t("home.chart_injected")}
          </li>
          <li>
            <span className="hm-spark-key hm-spark-value" />
            {t("home.chart_value")}
          </li>
          <li>
            <span className="hm-spark-key hm-spark-max" />
            {t("home.chart_period_max")}
            <strong className="hm-spark-legend-figure">
              {money(maxValue, base, lang)}
            </strong>
          </li>
        </ul>
        {selector}
      </div>
      {/* The plot and its scale side by side: the two extremes at the top and
          bottom of the plot's right edge, where a y axis puts its ticks —
          underneath it, next to each other, they read as the x axis. */}
      <div className="hm-spark-plot">
        {/* The wrap, not the svg, tracks the pointer: its rendered box is what
          a clientX has to be read against, and it is what the floating tip
          below is positioned inside. */}
        <div
          className="hm-spark-wrap"
          ref={wrap}
          onPointerMove={(event) => {
            if (spanned.move(event, indexAt(event))) return;
            setHoverIndex(dayAt(event.clientX));
          }}
          // A tap is a pointer that never moves: it reads the day too.
          onPointerDown={(event) => {
            if (spanned.down(event, indexAt(event))) return;
            setHoverIndex(dayAt(event.clientX));
          }}
          onPointerUp={spanned.up}
          // A finger lifting is a leave too; the day stays up until the reader
          // touches elsewhere, the only moment the hand is off the plot.
          onPointerLeave={(event) => {
            spanned.leave(event);
            if (event.pointerType !== "touch") setHoverIndex(null);
          }}
          onPointerCancel={spanned.cancel}
          onContextMenu={(event) => spanned.menu?.(event, indexAt(event))}
        >
          {/* Stretched, not letterboxed: the viewBox is only a coordinate system
            here, and `none` lets it fill whatever width the card has at the
            fixed CSS height. The strokes opt out of the stretch
            (`non-scaling-stroke`), so a line is as thick on a wide card as a
            narrow one and its dashes do not smear sideways. */}
          <svg
            className="hm-spark"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={t("portfolio.injected_vs_value")}
          >
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
              strokeWidth="1"
              strokeDasharray="3 2"
              vectorEffect="non-scaling-stroke"
            />
            <polyline
              points={line((day) => day.value)}
              fill="none"
              stroke={token("brand-accent")}
              strokeWidth="1.5"
              vectorEffect="non-scaling-stroke"
            />
            <line
              x1={0}
              x2={WIDTH}
              y1={y(maxValue)}
              y2={y(maxValue)}
              stroke={token("text-faint")}
              strokeDasharray="2 2"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={x(maxIndex)}
              cy={y(maxValue)}
              r="2"
              fill={token("text-faint")}
            />
            {measure && measure.to < days.length ? (
              <g className="hm-spark-span" pointerEvents="none">
                {compared ? (
                  <rect
                    x={x(compared.from)}
                    y={0}
                    width={x(compared.to) - x(compared.from)}
                    height={HEIGHT}
                  />
                ) : null}
                {[measure.from, measure.to].map((index, at) => (
                  <line
                    key={at}
                    x1={x(index)}
                    x2={x(index)}
                    y1={0}
                    y2={HEIGHT}
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
              </g>
            ) : null}
            {hovered && hoverIndex !== null ? (
              <line
                x1={x(hoverIndex)}
                x2={x(hoverIndex)}
                y1={0}
                y2={HEIGHT}
                stroke={token("text-faint")}
                strokeDasharray="2 2"
                vectorEffect="non-scaling-stroke"
                pointerEvents="none"
              />
            ) : null}
          </svg>
          {/* The hover label, as a positioned box rather than the browser's
            native `<title>` — which only answered on the day under the
            cursor's own thin column, after its own OS delay. */}
          {rows && tipTitle ? (
            <div
              className={
                tipLeft > 55 ? "hm-spark-tip hm-spark-tip-flip" : "hm-spark-tip"
              }
              style={{ left: `${tipLeft}%` }}
              role="status"
            >
              <span className="hm-spark-tip-title">{tipTitle}</span>
              {rows.map((row, index) => (
                <span className="hm-spark-tip-row" key={index}>
                  {row.color ? (
                    <span
                      className="hm-spark-tip-swatch"
                      style={{ background: row.color }}
                    />
                  ) : null}
                  {row.label ? <span>{row.label}</span> : null}
                  <strong>{row.value}</strong>
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {/* The two ends of the scale, pinned to the window's own extremes:
          without them the line has a shape and no size, and a reader cannot
          tell a €200 swing from a €20k one. */}
        <div className="hm-spark-scale">
          <span>{high}</span>
          <span>{low}</span>
        </div>
      </div>
    </>
  );
}

/**
 * The book against its own 20-session mean, as a tile rather than a third line.
 *
 * On the sparkline the average hugged the value line at every window short
 * enough to read, and the question it answers — is the book above or below
 * where it has been sitting — is a number, not a shape. Read off the glance's
 * whole history, not the chart's slice: the chart's window is the reader's
 * choice, and at `1w` it holds five sessions, which cannot average twenty. The
 * same array as the chart and the tiles, so the gap is measured from the value
 * the "Valor hoy" tile prints.
 *
 * Nothing until there are twenty valued sessions: a mean of fewer is a
 * different figure under the same label.
 */
export function AverageTile({ history }: { history: History | null }) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  if (!history) return null;
  const values = history.points
    .map((point) => point.value)
    .filter((value): value is number => value !== null);
  if (values.length < SMA_WINDOW) return null;
  const mean =
    values.slice(-SMA_WINDOW).reduce((sum, value) => sum + value, 0) / SMA_WINDOW;
  const last = values[values.length - 1]!;
  const gap = mean ? (last - mean) / mean : null;
  const figure = gap === null ? null : percent(gap, lang, { signed: true });
  return (
    <Kpi
      label={t("home.sma20_tile")}
      value={money(mean, base, lang) ?? "—"}
      chip={chipFor(gap, figure)}
      help={t("home.sma20_help")}
    />
  );
}
