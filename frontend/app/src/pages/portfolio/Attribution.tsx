/**
 * "What moved my portfolio": the Real performance window, taken apart.
 *
 * The TWR and the IRR say how much; this says why, in the reporting currency
 * and in bars that add up exactly to the closing value. It reads the window
 * the tab's selector already holds and the same value path the card above it
 * does — so the two cannot describe different days.
 */

import { get } from "../../shell/api";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import type { Attribution, AttributionMover, RiskPeriod } from "./api";
import { Waterfall, type WaterfallBar } from "./charts";
import { compactMoneyIn, moneyIn } from "./format";
import { Caption, Card, MissingPrices } from "./ui";

/** The bars in the order they add up; a step that is zero is not drawn. */
export function waterfallBars(
  data: Attribution,
  label: (key: string) => string,
  help: (key: string) => string,
): WaterfallBar[] {
  const steps: [string, number][] = [
    ["contributions", data.contributions],
    ["price", data.price],
    ["fx", data.fx],
    ["dividends", data.dividends],
    ["fees", data.fees],
    ["other", data.other],
  ];
  return [
    {
      key: "start",
      label: label("start"),
      kind: "total",
      amount: data.start_value ?? 0,
    },
    ...steps
      .filter(
        ([key, amount]) => amount !== 0 || key === "contributions" || key === "price",
      )
      .map(([key, amount]): WaterfallBar => ({
        key,
        label: label(key),
        kind: "step",
        amount,
        help: help(key),
      })),
    { key: "end", label: label("end"), kind: "total", amount: data.end_value ?? 0 },
  ];
}

function Movers({
  title,
  rows,
  money,
}: {
  title: string;
  rows: AttributionMover[];
  money: (value: number) => string;
}) {
  if (!rows.length) return null;
  return (
    <div className="pf-attr-list">
      <h3>{title}</h3>
      <ul>
        {rows.map((row) => (
          <li key={row.ticker}>
            <TickerCell ticker={row.ticker} name={false} className="pf-ticker" />
            <strong className={row.amount >= 0 ? "pf-up" : "pf-down"}>
              {money(row.amount)}
            </strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function AttributionCard({ period }: { period: RiskPeriod }) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);
  const axisMoney = compactMoneyIn(lang, base);
  const attribution = useApi(
    () => get<Attribution>("/portfolio/attribution", { base, window: period }),
    [base, period],
  );
  return (
    <Card title={t("portfolio.attr_title")} sub={t("portfolio.attr_sub")}>
      <Loaded query={attribution} skeleton={<Skeleton rows={4} />}>
        {(data) => {
          if (data.end_value === null)
            return <Caption>{t("portfolio.attr_empty")}</Caption>;
          const bars = waterfallBars(
            data,
            (key) => t(`portfolio.attr_${key}`),
            (key) => t(`portfolio.attr_${key}_help`),
          );
          const fmt = (value: number, signed = false) => money(value, { signed }) ?? "";
          return (
            <>
              <Waterfall
                bars={bars}
                money={fmt}
                axisMoney={(value) => axisMoney(value) ?? ""}
                summary={`${t("portfolio.attr_title")}: ${bars
                  .map((bar) => `${bar.label} ${fmt(bar.amount, bar.kind === "step")}`)
                  .join(", ")}`}
              />
              <div className="pf-attr-movers">
                <Movers
                  title={t("portfolio.attr_contributors")}
                  rows={data.contributors}
                  money={(v) => fmt(v, true)}
                />
                <Movers
                  title={t("portfolio.attr_detractors")}
                  rows={data.detractors}
                  money={(v) => fmt(v, true)}
                />
              </div>
              <Caption>{t("portfolio.attr_note")}</Caption>
              <MissingPrices tickers={data.missing} />
            </>
          );
        }}
      </Loaded>
    </Card>
  );
}
