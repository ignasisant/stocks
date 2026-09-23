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

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { useT, useLang } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { token } from "../../shell/theme";
import { money, monthDay, percent } from "./format";
import type { History } from "./types";

const WIDTH = 320;
const HEIGHT = 56;

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
  /** The day as one line: when, what it was worth, what went in, and the gap. */
  const hover = (day: (typeof days)[number]) => {
    const pnl = day.value - day.injected;
    const pct = day.injected
      ? percent(pnl / day.injected, lang, { signed: true })
      : null;
    const gap = `${money(pnl, base, lang, { signed: true })}${pct ? ` (${pct})` : ""}`;
    return [
      monthDay(day.date, t) ?? day.date,
      `${t("home.chart_value")} ${money(day.value, base, lang)}`,
      `${t("home.chart_injected")} ${money(day.injected, base, lang)}`,
      gap,
    ].join(" · ");
  };
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
      </ul>
      <svg
        className="hm-spark"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width="100%"
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
        />
        <polyline
          points={line((day) => day.value)}
          fill="none"
          stroke={token("brand-accent")}
          strokeWidth="1.5"
        />
        {/* One invisible column per day, each carrying a native <title>. The
            Streamlit chart states the same three things in a Plotly
            hovertemplate (`home.spark_hover_tmpl`); a browser tooltip makes
            the claim without a tooltip library, a hover state or a re-render,
            which at this size is the whole budget. */}
        {days.map((day, index) => (
          <rect
            key={day.date}
            x={index === 0 ? 0 : x(index) - WIDTH / (days.length - 1) / 2}
            y={0}
            width={WIDTH / (days.length - 1)}
            height={HEIGHT}
            fill="transparent"
          >
            <title>{hover(day)}</title>
          </rect>
        ))}
      </svg>
      {/* The two ends of the scale, pinned to the window's own extremes as the
          Streamlit chart's ticks are: without them the line has a shape and no
          size, and a reader cannot tell a €200 swing from a €20k one. */}
      <div className="hm-spark-scale">
        <span>{high}</span>
        <span>{low}</span>
      </div>
    </>
  );
}
