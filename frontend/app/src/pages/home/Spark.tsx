/**
 * The glance card's sparkline: what went in against what it is worth.
 *
 * The same pair of lines the Portfolio page charts in full, at a size that
 * answers one question — is the gap opening or closing — without asking anyone
 * to read an axis. The band between them carries the sign, which is the whole
 * reading at this size: green means the book is worth more than what was put
 * into it.
 *
 * Fails to nothing. The Streamlit page drops this sparkline and keeps the rest
 * of the card when the price span cannot be built, and so does this: a glance
 * card that renders an error where a picture goes is worse than one that is
 * simply a little shorter.
 */

import { useRef, useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { useT, useLang } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { token } from "../../shell/theme";
import { money, monthDay, percent } from "./format";
import type { History } from "./types";

const WIDTH = 320;
const HEIGHT = 56;

/** Trailing days averaged into the SMA20 overlay — a calendar month of trading. */
const SMA_WINDOW = 20;

/**
 * The windows the selector offers, in the order they widen.
 *
 * The same six the Streamlit card shows, under the same literal labels (no
 * i18n — "1w" is "1w" in every catalog the app has), and the same default:
 * `all` is the wrong opening view for a book that took a transfer, because one
 * step dwarfs every month of market movement around it. The clipping is the
 * server's (`/portfolio/history`), which also rebases the return index to the
 * window — slicing a fetched `all` locally would draw a one-month chart
 * starting at last year's number.
 */
const RANGES = ["1w", "1m", "6m", "1y", "2y", "5y"] as const;

type Range = (typeof RANGES)[number];

export function Spark({ nonce }: { nonce: number }) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const [range, setRange] = useState<Range>("1m");
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const query = useApi(
    () => get<History>("/portfolio/history", { base, window: range }),
    [base, nonce, range],
  );
  const selector = (
    <div className="hm-segmented" role="group" aria-label={t("home.chart_value")}>
      {RANGES.map((key) => (
        <button
          key={key}
          type="button"
          className={key === range ? "hm-seg hm-seg-on" : "hm-seg"}
          aria-pressed={key === range}
          onClick={() => setRange(key)}
        >
          {key}
        </button>
      ))}
    </div>
  );
  // The selector outlives the query: a window with too few points to draw must
  // still let somebody pick a wider one, or the card traps them there.
  if (query.state !== "loaded") return <div className="hm-spark-head">{selector}</div>;

  // Both legs or the day is not comparable: a value with no reference line has
  // nothing to be shaded against.
  const days: { date: string; injected: number; value: number }[] = [];
  for (const point of query.data.points) {
    if (point.injected !== null && point.value !== null) {
      days.push({ date: point.date, injected: point.injected, value: point.value });
    }
  }
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

  // Trailing mean of the value line — undefined until the window has 20 days
  // behind it, same warm-up gap the ticker chart's own SMA20 draws.
  const sma20: (number | null)[] = days.map((_, index) => {
    if (index < SMA_WINDOW - 1) return null;
    let sum = 0;
    for (let i = index - SMA_WINDOW + 1; i <= index; i += 1) sum += days[i]!.value;
    return sum / SMA_WINDOW;
  });
  const smaPoints = sma20
    .map((value, index) => (value === null ? null : `${x(index)},${y(value)}`))
    .filter((point): point is string => point !== null)
    .join(" ");

  // The peak of the value line itself, not of whichever of the two series
  // happens to be higher — "period max" is a claim about what the book was
  // worth, not about what went into it.
  const maxValue = Math.max(...days.map((day) => day.value));
  const maxIndex = days.findIndex((day) => day.value === maxValue);

  /**
   * What Streamlit's unified hover label says about one day
   * (`home.spark_hover_tmpl`), in the same order: worth (colored by gain or
   * loss), what went in, and the gap between them as an amount and a percent.
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

  const hovered = hoverIndex === null ? null : days[hoverIndex];
  const tipLeft = hoverIndex === null ? 0 : (x(hoverIndex) / WIDTH) * 100;

  return (
    <>
      <div className="hm-spark-head">{selector}</div>
      {/* Two lines with no legend is a picture of nothing in particular: the
          dashed one is what went in, the solid one what it is worth, and the
          band between them is the answer the card exists to give. */}
      <ul className="hm-spark-legend">
        <li>
          <span className="hm-spark-key hm-spark-injected" />
          {t("home.chart_injected")}
        </li>
        <li>
          <span className="hm-spark-key hm-spark-value" />
          {t("home.chart_value")}
        </li>
        {smaPoints ? (
          <li>
            <span className="hm-spark-key hm-spark-sma" />
            {t("home.chart_sma20")}
          </li>
        ) : null}
        <li>
          <span className="hm-spark-key hm-spark-max" />
          {t("home.chart_period_max")}: {money(maxValue, base, lang)}
        </li>
      </ul>
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
          onPointerMove={(event) => setHoverIndex(dayAt(event.clientX))}
          onPointerLeave={() => setHoverIndex(null)}
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
            {smaPoints ? (
              <polyline
                points={smaPoints}
                fill="none"
                stroke={token("sma-fast")}
                strokeWidth="1"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
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
            <circle cx={x(maxIndex)} cy={y(maxValue)} r="2" fill={token("text-faint")} />
            {hoverIndex !== null ? (
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
          {/* Streamlit's unified hover label (`home.spark_hover_tmpl`), as a
            positioned box rather than the browser's native `<title>` — which
            only answered on the day under the cursor's own thin column, after
            its own OS delay. */}
          {hovered ? (
            <div
              className={
                tipLeft > 55 ? "hm-spark-tip hm-spark-tip-flip" : "hm-spark-tip"
              }
              style={{ left: `${tipLeft}%` }}
              role="status"
            >
              <span className="hm-spark-tip-title">
                {monthDay(hovered.date, t) ?? hovered.date}
              </span>
              {tipRows(hovered).map((row, index) => (
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
        {/* The two ends of the scale, pinned to the window's own extremes as the
          Streamlit chart's ticks are: without them the line has a shape and no
          size, and a reader cannot tell a €200 swing from a €20k one. */}
        <div className="hm-spark-scale">
          <span>{high}</span>
          <span>{low}</span>
        </div>
      </div>
    </>
  );
}
