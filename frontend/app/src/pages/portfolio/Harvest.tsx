/**
 * "Before the year closes": the open positions under their cost whose sale
 * would lower this year's bill, off the same engine as the chat's harvest
 * skill. A lazy second request — it needs today's prices for every holding,
 * which the realized report above never does — and it never takes the tab down.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { useLang, useT } from "../../shell/i18n";
import { useGuest } from "../../shell/session";
import { moneyIn, shares as formatShares } from "../../shell/format";
import { TickerCell } from "../../shell/tickers";
import { Skeleton } from "../../shell/Layout";
import { Caption, Card, Figure } from "./ui";

export type HarvestCandidate = {
  ticker: string;
  shares: number;
  loss: number;
  saving: number;
  blocked: number;
  free: boolean;
};

export type HarvestData = {
  candidates: HarvestCandidate[];
  gains: number;
  losses: number;
  tax: number;
  tax_all: number;
  carry: number;
  saving: number;
  currency: string;
  year: string;
  window: string;
  clear: string;
};

/** Candidates that would change the bill, biggest saving first. */
export function worthSelling(data: HarvestData): HarvestCandidate[] {
  return [...data.candidates].sort((a, b) => b.saving - a.saving);
}

export default function Harvest() {
  const t = useT();
  const lang = useLang();
  // The demo book has no tax year of its own and the route refuses a guest,
  // so a guest gets no card rather than a 401 on every visit.
  const guest = useGuest();
  const query = useApi(
    () =>
      guest ? Promise.resolve(null) : get<HarvestData | null>("/portfolio/tax/harvest"),
    [guest],
  );
  if (query.state === "loading") return <Skeleton rows={3} />;
  if (query.state !== "loaded" || !query.data) return null;
  const data = query.data;
  const rows = worthSelling(data);
  if (!rows.length) return null;
  const money = moneyIn(lang, data.currency);
  return (
    <Card title={t("portfolio.harvest_title")} sub={t("portfolio.harvest_sub")}>
      <p className="pf-answer-line">
        {t("portfolio.harvest_answer", {
          saving: money(Math.max(data.saving, 0)) ?? "",
          n: rows.length,
        })}
      </p>
      <ul className="pf-harvest">
        {rows.map((row) => (
          <li key={row.ticker}>
            <TickerCell ticker={row.ticker} name={false} className="pf-ticker" />
            <span className="pf-muted">{formatShares(row.shares, { lang })}</span>
            <Figure value={money(row.loss, { signed: true })} />
            <span className="pf-muted">
              {row.blocked > 0
                ? t("portfolio.harvest_blocked", { value: money(row.blocked) ?? "" })
                : row.free
                  ? t("portfolio.harvest_free")
                  : t("portfolio.harvest_saves", {
                      value: money(Math.max(row.saving, 0)) ?? "",
                    })}
            </span>
          </li>
        ))}
      </ul>
      <Caption>
        {t("portfolio.harvest_note")}
        {data.window && data.clear
          ? ` ${t("portfolio.harvest_window", { date: data.clear })}`
          : ""}
      </Caption>
    </Card>
  );
}
