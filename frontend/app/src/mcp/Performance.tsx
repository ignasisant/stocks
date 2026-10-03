/**
 * `portfolio_performance`: what the selection did, what the money did, and
 * the book's value against what was put in.
 *
 * Both returns, side by side and labelled for what they measure — TWR is the
 * picks with the deposits taken out, IRR is the reader's actual money — since
 * they routinely disagree and either one alone invites the wrong reading.
 */

import { Kpi, KpiGrid, toneOf } from "../ui/Kpi";
import { money, percent, shortDay } from "./format";
import type { Performance as Data, Point, Words } from "./types";

const W = 600;
const H = 180;

/** An SVG path through the non-null values, scaled into `[lo, hi]`. */
export function path(
  points: Point[],
  pick: (p: Point) => number | null,
  lo: number,
  hi: number,
): string {
  const span = hi - lo || 1;
  const step = points.length > 1 ? W / (points.length - 1) : 0;
  let d = "";
  let pen = false;
  points.forEach((point, i) => {
    const v = pick(point);
    if (v === null || !Number.isFinite(v)) {
      pen = false;
      return;
    }
    const x = (i * step).toFixed(1);
    const y = (H - ((v - lo) / span) * H).toFixed(1);
    d += `${pen ? "L" : "M"}${x} ${y}`;
    pen = true;
  });
  return d;
}

/** Lowest and highest of both lines, so they share one axis. */
export function bounds(points: Point[]): [number, number] | null {
  const all = points
    .flatMap((p) => [p.value, p.injected])
    .filter((v): v is number => v !== null && Number.isFinite(v));
  if (!all.length) return null;
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.05 || 1;
  return [lo - pad, hi + pad];
}

function Chart({ data, words }: { data: Data; words: Words }) {
  const points = data.history.points;
  const range = bounds(points);
  if (!range || points.length < 2) return null;
  const [lo, hi] = range;
  const base = data.performance.base;
  return (
    <figure className="v-chart">
      <div className="v-axis-y">
        <span>{money(hi, base, words.locale)}</span>
        <span>{money(lo, base, words.locale)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        <path
          d={path(points, (p) => p.injected, lo, hi)}
          className="v-line v-line-in"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={path(points, (p) => p.value, lo, hi)}
          className="v-line v-line-val"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="v-axis-x">
        <span>{shortDay(data.history.start, words.locale)}</span>
        <span>{shortDay(data.history.end, words.locale)}</span>
      </div>
      <figcaption className="v-keys">
        <span>
          <i className="v-key-val" />
          {words.t("connector.view_value")}
        </span>
        <span>
          <i className="v-key-in" />
          {words.t("connector.view_injected")}
        </span>
      </figcaption>
    </figure>
  );
}

export function Performance({ data, words }: { data: Data; words: Words }) {
  const { t, locale } = words;
  const p = data.performance;
  if (p.value === null && data.history.points.length === 0) {
    return <p className="v-empty">{t("connector.view_empty")}</p>;
  }
  const figures: [string, number | null][] = [
    ["connector.view_twr", p.twr_cumulative],
    ["connector.view_twr_annual", p.twr_annualised],
    ["connector.view_irr", p.irr],
    ["connector.view_drawdown", p.twr_max_drawdown],
  ];
  const missing = data.history.missing;

  return (
    <>
      <KpiGrid>
        <Kpi
          label={t("connector.view_value")}
          value={money(p.value, p.base, locale)}
          note={`${t("connector.view_injected")} ${money(p.injected, p.base, locale)}`}
        />
        {figures.map(([key, value]) => (
          <Kpi
            key={key}
            label={t(key)}
            value={percent(value, locale)}
            valueTone={toneOf(value)}
          />
        ))}
      </KpiGrid>
      <Chart data={data} words={words} />
      {missing.length > 0 && (
        <p className="v-note">
          {t("connector.view_missing_note", { names: missing.join(", ") })}
        </p>
      )}
    </>
  );
}
