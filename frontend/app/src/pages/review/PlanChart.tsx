/**
 * The plan's moves over the window the tables read: what it sells against
 * what it adds to, beside the S&P 500, each line the total return of one unit
 * of the page's currency put in on the window's first day.
 *
 * Context for the plan, not its reason: the verdicts are read off quality and
 * price today, and a name that ran is not a name that will. So the chart sits
 * in the full read only, under the moves it draws.
 *
 * The S&P 500 is the comparison's subject, so the axis is its sessions and
 * one move with no history leaves a gap rather than an empty chart. Three of
 * each side at most, biggest first: past six lines the legend outgrows the
 * plot. Sales draw in the warm hues, adds in the cool ones, SPY in the blue
 * every other page draws it in.
 */

import { useLang, useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { chart } from "../../shell/theme";
import { useApi } from "../../shell/useApi";
import { ReturnLines, type ReturnSeries } from "../portfolio/charts";
import { getCompare } from "../ticker/data";
import { signedPercent } from "../ticker/format";
import type { Comparison } from "../ticker/types";
import { INDEX, type ReturnWindow } from "./returns";
import type { ReviewRow } from "./types";
import "../portfolio/portfolio.css";

/** Lines per side — three sales and three adds fill `MAX_OTHERS`. */
export const PER_SIDE = 3;

/** The names drawn: the biggest moves of each side, once each, never SPY. */
export function drawnMoves(out: ReviewRow[], into: ReviewRow[]) {
  const seen = new Set<string>([INDEX]);
  const pick = (rows: ReviewRow[]) => {
    const kept: string[] = [];
    for (const row of rows) {
      const name = row.symbol.toUpperCase();
      if (kept.length >= PER_SIDE || seen.has(name)) continue;
      seen.add(name);
      kept.push(name);
    }
    return kept;
  };
  const sells = pick(out);
  const adds = pick(into);
  return { sells, adds, left: out.length + into.length - sells.length - adds.length };
}

export default function PlanChart({
  out,
  into,
  base,
  span,
}: {
  out: ReviewRow[];
  into: ReviewRow[];
  base: string;
  span: ReturnWindow;
}) {
  const t = useT();
  const lang = useLang();
  const { sells, adds, left } = drawnMoves(out, into);
  const names = [...sells, ...adds];
  const query = useApi(
    () => getCompare(INDEX, span, base, names),
    [span, base, names.join(",")],
  );

  const date = new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" });
  const yearly = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatDate = (iso: string) =>
    (span === "1m" || span === "6m" ? date : yearly).format(
      new Date(`${iso}T00:00:00`),
    );

  if (names.length === 0) return null;
  return (
    <div className="ag-rev-plan-chart">
      <h3 className="ag-rev-mvs-head">
        <span>
          {t("review.plan_chart_title", { span: t(`ticker.period_${span}`) })}
        </span>
      </h3>
      <p className="ag-rev-caption">{t("review.plan_chart_note", { base })}</p>
      <Loaded query={query} skeleton={<Skeleton rows={5} />}>
        {(data) => (
          <Lines data={data} sells={sells} adds={adds} formatDate={formatDate} />
        )}
      </Loaded>
      {left > 0 ? (
        <p className="ag-rev-caption">{t("review.plan_chart_more", { count: left })}</p>
      ) : null}
    </div>
  );
}

function Lines({
  data,
  sells,
  adds,
  formatDate,
}: {
  data: Comparison;
  sells: string[];
  adds: string[];
  formatDate: (iso: string) => string;
}) {
  const t = useT();
  const palette = chart();
  if (data.dates.length < 2) {
    return <p className="ag-rev-caption">{t("review.plan_chart_empty")}</p>;
  }
  const warm = [palette.candleDown, palette.warnOrange, palette.warn];
  const cool = [palette.candleUp, palette.brandAccent, palette.smaLong];
  const series: ReturnSeries[] = data.lines.map((line) => {
    const sold = sells.indexOf(line.ticker);
    const added = adds.indexOf(line.ticker);
    if (line.role === "subject") {
      return {
        label: t("portfolio.bench_spy"),
        points: line.points,
        color: palette.info,
      };
    }
    return sold >= 0
      ? {
          label: t("review.plan_chart_out", { ticker: line.ticker }),
          points: line.points,
          color: warm[sold],
        }
      : {
          label: t("review.plan_chart_in", { ticker: line.ticker }),
          points: line.points,
          color: cool[Math.max(added, 0)],
        };
  });
  return (
    <>
      <ReturnLines
        dates={data.dates}
        series={series}
        label={t("review.plan_chart_title", { span: data.range })}
        format={(value) => signedPercent(value, 1)}
        tickFormat={(value) => signedPercent(value, 0)}
        formatDate={formatDate}
        legendValues
      />
      {data.missing.length > 0 ? (
        <p className="ag-rev-caption">
          {t("ticker.compare_missing", { names: data.missing.join(", ") })}
        </p>
      ) : null}
    </>
  );
}
