/**
 * The glance card's chart: what the book is worth, as a phone broker draws it.
 *
 * One line with a wash under it, the figure over it following the finger, the
 * window's high and low on the line itself and the range under it. Two
 * references stay, because they are what make the figure mean something: what
 * went in, and the same money in the S&P 500 since the book's first day
 * (`benchLine`) — above the value line, the index would have done better.
 * The scale starts at zero, so a dip is drawn at its size.
 *
 * A held finger slid along, two fingers, a mouse drag (as the ticker chart
 * brushes), or a secondary click (`useSpan`) compare two days: how much the
 * value moved, how much of it was money put in, and the rest — what the
 * market did. Amounts only, since money flowed through the span.
 *
 * Fails to nothing. When the price span cannot be built the sparkline drops
 * out and the rest of the card stays: a glance card that renders an error
 * where a picture goes is worse than one that is simply a little shorter.
 */

import { useCallback, useId, useRef, useState } from "react";
import { useT, useLang } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { seriesColors, token } from "../../shell/theme";
import { useSpan } from "../../shell/useSpan";
import { BASELINE_DASH, LINE } from "../../ui/chart/marks";
import { Tip } from "../../ui/chart/Tip";
import { Spoken, useScrub } from "../../ui/chart/useScrub";
import { monthDay } from "./format";
import { Kpi, chipFor } from "../../ui/Kpi";
import { Segmented } from "../../ui/Segmented";
import type { History } from "./types";
import { money, percent } from "../../shell/format";

const WIDTH = 320;
const HEIGHT = 56;

/** Trailing sessions the average tile folds in — a calendar month of trading. */
const SMA_WINDOW = 20;

/**
 * The windows the selector offers, in the order they widen, and how many
 * calendar days back from the series' last day each one reaches. `all` is the
 * whole history, from the book's first day.
 *
 * It opens on `all`: the S&P line is the same money bought on the book's own
 * days, and a window that opens later forgives whatever the picks lost before
 * it (CLAUDE.md, "Index comparisons start where the book starts"). A window as
 * long as the book itself is hidden — it would draw `all` again under another
 * name. The spans are `_HISTORY_SPANS` in `api/routes/portfolio/returns.py`,
 * counted from the same end, so a slice here is the window the server would
 * have cut.
 */
const RANGES = {
  "1w": 7,
  "1m": 30,
  "6m": 182,
  "1y": 365,
  "2y": 730,
  all: Infinity,
} as const;

type Range = keyof typeof RANGES;

/** The window the glance fetches: the whole book, which every range slices. */
export const SPARK_WINDOW = "all";

/** The ranges worth offering for a book whose history runs `span` days. */
export function offered(span: number): Range[] {
  return (Object.keys(RANGES) as Range[]).filter(
    (key) => key === "all" || RANGES[key] < span,
  );
}

/** Calendar days from the history's first point to its last. */
function spanOf(history: History): number {
  const first = history.points[0];
  const last = history.points[history.points.length - 1];
  if (!first || !last) return 0;
  return (Date.parse(last.date) - Date.parse(first.date)) / 86_400_000;
}

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
  if (range === "all") return history.points;
  const from = new Date(`${last.date}T00:00:00Z`);
  from.setUTCDate(from.getUTCDate() - RANGES[range]);
  const cutoff = from.toISOString().slice(0, 10);
  return history.points.filter((point) => point.date >= cutoff);
}

/**
 * The same money in the S&P 500 over `days`, or null.
 *
 * The server races it from the book's first day (`in_index`), so like the
 * level lines it is absolute and survives slicing: a window is a stretch of
 * one race, and the gap where the window opens is what came before it. Null
 * unless every day has it — a line that stops halfway reads as the index
 * falling to nothing.
 */
export function benchLine(days: { inIndex: number | null }[]): number[] | null {
  if (days.length < 2) return null;
  const out: number[] = [];
  for (const day of days) {
    if (day.inIndex === null) return null;
    out.push(day.inIndex);
  }
  return out;
}

function Spark({ history }: { history: History | null }) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const [range, setRange] = useState<Range>("all");
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  // Two days being compared, in day order. The span's units are day indices:
  // the wrap's handlers read the day before handing it on.
  const [measure, setMeasure] = useState<{ from: number; to: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  // An id fit for `url(#…)`: React's carries characters a fragment trips on.
  const wash = `hm-wash-${useId().replace(/[^\w-]/g, "")}`;
  // Where a mouse drag started, as the ticker chart brushes: the stretch reads
  // live while the button is down and goes away when it lifts.
  const dragFrom = useRef<number | null>(null);
  const drop = useCallback(() => {
    setHoverIndex(null);
    setMeasure(null);
  }, []);
  const spanned = useSpan((pair) => {
    if (!pair) return setMeasure(null);
    setHoverIndex(null);
    setMeasure({ from: Math.min(...pair), to: Math.max(...pair) });
  });
  // Both legs or the day is not comparable: a value with no reference line has
  // nothing to be shaded against. Built before the early returns because the
  // key walk below is a hook and needs the day count.
  const days: {
    date: string;
    injected: number;
    value: number;
    inIndex: number | null;
  }[] = [];
  for (const point of history ? slice(history, range) : []) {
    if (point.injected !== null && point.value !== null) {
      days.push({
        date: point.date,
        injected: point.injected,
        value: point.value,
        inIndex: point.in_index ?? null,
      });
    }
  }
  const bench = benchLine(days);
  const walk = useScrub({
    plot: wrap,
    at: hoverIndex,
    last: days.length - 1,
    set: (index) => {
      setMeasure(null);
      setHoverIndex(index);
    },
    held: hoverIndex !== null || measure !== null,
    drop,
  });
  // The history failed, or has not landed: the plot's box stays reserved, so
  // the card is the height it will be and nothing below it shifts when the
  // series arrives. No selector — every range is a slice of the same array.
  const placeholder = (
    <div className="hm-spark-plot">
      <div className="hm-spark-wrap hm-spark-empty" aria-hidden="true" />
    </div>
  );
  if (!history) return placeholder;
  const selector = (
    <Segmented
      className="hm-segmented"
      label={t("home.chart_value")}
      items={offered(spanOf(history)).map((key) => ({
        id: key,
        label: t(`home.chart_range_${key}`),
      }))}
      value={range}
      onPick={(key) => {
        setRange(key);
        setMeasure(null);
      }}
    />
  );
  // The selector outlives a short window: one with too few points to draw must
  // still let somebody pick a wider one, or the card traps them there.
  if (days.length < 2) {
    return (
      <>
        {placeholder}
        <div className="hm-spark-foot">{selector}</div>
      </>
    );
  }

  const levels = [
    ...days.flatMap((day) => [day.injected, day.value]),
    ...(bench ?? []),
  ];
  const benchColor = seriesColors(["SPY"]).SPY!;
  // The scale starts at zero: fitted to the window's own extremes, a 5 % dip
  // filled the plot's height and read like the book halving. The headroom
  // over the top is the peak's label, which sits above its point.
  const floor = Math.min(0, ...levels);
  const ceiling = Math.max(...levels) * 1.15;
  const span = ceiling - floor || 1;
  const x = (index: number) => (index / (days.length - 1)) * WIDTH;
  const y = (value: number) => (1 - (value - floor) / span) * (HEIGHT - 2) + 1;

  const line = (pick: (day: (typeof days)[number]) => number) =>
    days.map((day, index) => `${x(index)},${y(pick(day))}`).join(" ");

  // The extremes of the value line itself, not of whichever series happens to
  // be higher: "period max" is a claim about what the book was worth.
  const values = days.map((day) => day.value);
  const maxValue = Math.max(...values);
  const maxIndex = values.indexOf(maxValue);
  const minValue = Math.min(...values);
  const minIndex = values.indexOf(minValue);

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
  const signed = (value: number) =>
    money(value, { currency: base, lang, signed: "always" });

  /** What the label says between the two days being compared. */
  const spanRows = (fromAt: number, toAt: number) => {
    const from = days[fromAt]!;
    const to = days[toAt]!;
    const moved = to.value - from.value;
    const put = to.injected - from.injected;
    return [
      {
        label: t("home.chart_value"),
        value: signed(moved),
        color: moved >= 0 ? token("up") : token("down"),
      },
      { label: t("home.chart_injected"), value: signed(put) },
      { label: t("home.chart_market"), value: signed(moved - put) },
      // What the same flows made in the index over the same days: the row to
      // read "Mercado" against.
      ...(bench
        ? [
            {
              label: t("home.chart_index"),
              value: signed(bench[toAt]! - bench[fromAt]! - put),
              color: benchColor,
            },
          ]
        : []),
    ];
  };
  const indexAt = (event: { clientX: number }) => dayAt(event.clientX) ?? 0;

  /** A gap as "+€1,200 (+8.4%)": the amount, and its share of what went in. */
  const gap = (day: (typeof days)[number]) => {
    const pct = day.injected
      ? percent((day.value - day.injected) / day.injected, {
          lang,
          digits: 2,
          signed: "always",
        })
      : null;
    return `${signed(day.value - day.injected)}${pct ? ` (${pct})` : ""}`;
  };
  const end = days[days.length - 1]!;
  const rangeLabel = t(
    range === "all" ? "home.chart_since_start" : `home.chart_range_${range}`,
  );
  const summary = t("home.chart_summary", {
    value: money(end.value, { currency: base, lang }) ?? "",
    gap: gap(end),
    injected: money(end.injected, { currency: base, lang }) ?? "",
    range: rangeLabel,
  });
  const sentence = hovered
    ? t("home.chart_spoken", {
        date: monthDay(hovered.date, t) ?? hovered.date,
        value: money(hovered.value, { currency: base, lang }) ?? "",
        injected: money(hovered.injected, { currency: base, lang }) ?? "",
        gap: gap(hovered),
      })
    : null;

  // The head reads the day under the finger, or the last one: the figure
  // follows the scrub, as a phone's broker app does, instead of a box over
  // the line. The change is what the market did since the window opened —
  // the value's move less the money put in — so a deposit is not a gain —
  // and the money put in is the window's too, not every euro since the start.
  const focusAt = hovered && hoverIndex !== null ? hoverIndex : days.length - 1;
  const focus = days[focusAt]!;
  const first = days[0]!;
  const put = focus.injected - first.injected;
  const change = focus.value - first.value - put;
  const when = hovered ? (monthDay(hovered.date, t) ?? hovered.date) : rangeLabel;

  /**
   * A point drawn as a zero-length line with round caps. A `<circle>` in this
   * stretched svg squashes to an ellipse; a non-scaling stroke is the same
   * width both ways, so the cap is a true disc whatever the card's width.
   */
  const dot = (index: number, level: number, color: string, size: number) => (
    <line
      x1={x(index)}
      x2={x(index)}
      y1={y(level)}
      y2={y(level)}
      stroke={color}
      strokeWidth={size}
      strokeLinecap="round"
      vectorEffect="non-scaling-stroke"
      pointerEvents="none"
    />
  );

  /** An extreme's figure by its point, kept inside the plot at either end. */
  const mark = (index: number, level: number, side: "over" | "under") => {
    const left = (x(index) / WIDTH) * 100;
    const edge = left < 15 ? "start" : left > 85 ? "end" : "mid";
    return (
      <span
        className={`hm-spark-mark hm-spark-mark-${side} hm-spark-mark-${edge}`}
        style={{ left: `${left}%`, top: `${(y(level) / HEIGHT) * 100}%` }}
      >
        {money(level, { currency: base, lang })}
      </span>
    );
  };

  return (
    <>
      {/* The figure, what the market did over the window, and the two
          references with their levels on the same day. The keys stay: the
          grey line is what went in, the dashed one the same money in the
          index, and neither may be told apart by colour alone. */}
      <div className="hm-spark-head">
        <p className="hm-spark-figure">
          {money(focus.value, { currency: base, lang })}
        </p>
        <p className="hm-spark-change">
          <span style={{ color: change >= 0 ? token("up") : token("down") }}>
            {signed(change)}
          </span>
          <span className="hm-spark-when"> · {when}</span>
        </p>
        <ul className="hm-spark-legend">
          <li>
            <span className="hm-spark-key hm-spark-injected" />
            {t("home.chart_injected")}
            <strong className="hm-spark-legend-figure">{signed(put)}</strong>
          </li>
          {bench ? (
            <li title={t("home.chart_index_note")}>
              <span
                className="hm-spark-key hm-spark-index"
                style={{ borderColor: benchColor }}
              />
              {t("home.chart_index")}
              <strong className="hm-spark-legend-figure">
                {money(bench[focusAt]!, { currency: base, lang })}
              </strong>
            </li>
          ) : null}
        </ul>
      </div>
      <div className="hm-spark-plot">
        {/* The wrap, not the svg, tracks the pointer: its rendered box is what
          a clientX has to be read against, and it is what the floating tip
          below is positioned inside. */}
        <div
          className="hm-spark-wrap"
          ref={wrap}
          role="group"
          aria-label={t("home.chart_value")}
          {...walk.props}
          onPointerMove={(event) => {
            walk.quiet();
            if (spanned.move(event, indexAt(event))) return;
            const at = indexAt(event);
            if (dragFrom.current !== null && at !== dragFrom.current) {
              setHoverIndex(null);
              setMeasure({
                from: Math.min(dragFrom.current, at),
                to: Math.max(dragFrom.current, at),
              });
              return;
            }
            if (dragFrom.current !== null) setMeasure(null);
            setHoverIndex(dayAt(event.clientX));
          }}
          // A tap is a pointer that never moves: it reads the day too.
          onPointerDown={(event) => {
            walk.quiet();
            if (spanned.down(event, indexAt(event))) return;
            // A drag keeps the pointer past the plot's edge. A finger is held
            // by the browser already, and must stay free to scroll the page.
            if (event.pointerType !== "touch" && event.button === 0) {
              dragFrom.current = indexAt(event);
              event.currentTarget.setPointerCapture?.(event.pointerId);
            }
            setHoverIndex(dayAt(event.clientX));
          }}
          onPointerUp={(event) => {
            if (spanned.up(event)) return;
            if (dragFrom.current === null) return;
            dragFrom.current = null;
            setMeasure(null);
            setHoverIndex(dayAt(event.clientX));
          }}
          // A finger lifting is a leave too; the day stays up until the reader
          // touches elsewhere, the only moment the hand is off the plot.
          onPointerLeave={(event) => {
            spanned.leave(event);
            if (event.pointerType === "touch") return;
            if (dragFrom.current !== null) {
              dragFrom.current = null;
              setMeasure(null);
            }
            setHoverIndex(null);
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
            aria-label={summary}
          >
            <defs>
              {/* The value's wash: the line's own colour, fading to nothing
                  at the floor, so the area reads as volume and not as a band. */}
              <linearGradient id={wash} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor={token("brand-accent")} stopOpacity="0.32" />
                <stop offset="1" stopColor={token("brand-accent")} stopOpacity="0" />
              </linearGradient>
            </defs>
            <g className="ag-redraw" key={range}>
              <path
                d={`M${x(0)},${y(floor)}L${days.map((day, index) => `${x(index)},${y(day.value)}`).join("L")}L${x(days.length - 1)},${y(floor)}Z`}
                fill={`url(#${wash})`}
              />
              <polyline
                points={line((day) => day.injected)}
                fill="none"
                stroke={token("text-muted")}
                strokeWidth={LINE.rule}
                vectorEffect="non-scaling-stroke"
              />
              {bench ? (
                <polyline
                  points={bench
                    .map((level, index) => `${x(index)},${y(level)}`)
                    .join(" ")}
                  fill="none"
                  stroke={benchColor}
                  strokeWidth={LINE.overlay}
                  strokeDasharray={BASELINE_DASH}
                  vectorEffect="non-scaling-stroke"
                />
              ) : null}
              <polyline
                points={line((day) => day.value)}
                fill="none"
                stroke={token("brand-accent")}
                strokeWidth={LINE.compact}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
              {hovered
                ? null
                : dot(days.length - 1, end.value, token("brand-accent"), 7)}
            </g>
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
              <>
                <line
                  x1={x(hoverIndex)}
                  x2={x(hoverIndex)}
                  y1={0}
                  y2={HEIGHT}
                  className="ag-cross"
                  vectorEffect="non-scaling-stroke"
                  pointerEvents="none"
                />
                {dot(hoverIndex, hovered.injected, token("text-muted"), 5)}
                {bench ? dot(hoverIndex, bench[hoverIndex]!, benchColor, 5) : null}
                {dot(hoverIndex, hovered.value, token("brand-accent"), 7)}
              </>
            ) : null}
          </svg>
          {/* The window's high and low, on the line rather than on an axis:
            the size of the swing without a scale to read it off. */}
          <div className="hm-spark-marks" aria-hidden="true">
            {mark(maxIndex, maxValue, "over")}
            {minIndex !== maxIndex ? mark(minIndex, minValue, "under") : null}
          </div>
          {/* Two days compared get the box: three amounts do not fit the
            head's one figure. */}
          {compared ? (
            <Tip
              at={(x((compared.from + compared.to) / 2) / WIDTH) * 100}
              title={[compared.from, compared.to]
                .map((index) => monthDay(days[index]!.date, t) ?? days[index]!.date)
                .join(" → ")}
              items={spanRows(compared.from, compared.to).map((row) => ({
                ...row,
                value: row.value ?? "—",
              }))}
              className="hm-spark-tip"
            />
          ) : null}
          <Spoken text={walk.keyed ? sentence : null} />
        </div>
      </div>
      <div className="hm-spark-foot">{selector}</div>
    </>
  );
}

const MORE_KEY = "ag.more.home-chart";

/**
 * The sparkline behind a "show more", below the tiles.
 *
 * The tiles answer the visit; the chart is for the reader who wants the
 * shape behind them. Closed by default; opened, it stays open on the next
 * visit (this browser only — a convenience, not state). Closed, it is not
 * drawn.
 */
export function SparkMore({ history }: { history: History | null }) {
  const t = useT();
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(MORE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggle = () => {
    const next = !open;
    setOpen(next);
    try {
      if (next) localStorage.setItem(MORE_KEY, "1");
      else localStorage.removeItem(MORE_KEY);
    } catch {
      /* private window, blocked storage — the chart just forgets */
    }
  };
  return (
    <>
      {open ? (
        <div id="hm-spark-more">
          <Spark history={history} />
        </div>
      ) : null}
      <button
        type="button"
        className="hm-more"
        aria-expanded={open}
        aria-controls="hm-spark-more"
        onClick={toggle}
      >
        {open ? t("home.chart_less") : t("home.chart_more")}
      </button>
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
  const figure =
    gap === null ? null : percent(gap, { lang, digits: 2, signed: "always" });
  return (
    <Kpi
      label={t("home.sma20_tile")}
      value={money(mean, { currency: base, lang }) ?? "—"}
      chip={chipFor(gap, figure)}
      help={t("home.sma20_help")}
    />
  );
}
