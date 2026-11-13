/**
 * The podium side by side: one row per metric that separates the three, the
 * leader of each row marked.
 *
 * The written read says who is best and why in words; this is the same claim
 * in figures, so a reader can check it line by line. Built from the cohort
 * rows already in hand, so it stands whether or not the read was written.
 */

import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { useLabels } from "./labels";
import { formatMetric } from "./metrics";
import { leaders } from "./rank";
import type { SectorCohort } from "./types";

/** Quality, price, growth and debt: two of each kind a buyer weighs. */
const COMPARED = [
  "roic",
  "op_margin",
  "pe_ttm",
  "fcf_yield",
  "revenue_cagr",
  "net_debt_ebitda",
];

export function TopThree({ data }: { data: SectorCohort }) {
  const t = useT();
  const labels = useLabels();
  const na = t("sector.na");
  const tickers = data.podium.slice(0, 3);
  const keys = COMPARED.filter((key) => data.metric_keys.includes(key));
  if (tickers.length < 2 || keys.length === 0) return null;
  const best = leaders(data.rows, tickers, keys, data.lower_is_better);
  const row = (ticker: string) =>
    data.rows.find((one) => one.ticker === ticker.toUpperCase());

  return (
    <div className="ag-sec-scroll ag-sec-top3">
      <table className="ag-sec-table">
        <caption className="ag-sec-caption">{t("sector.top3_caption")}</caption>
        <thead>
          <tr>
            <th scope="col" className="ag-sec-who-col">
              <span className="ag-sec-sr">{t("sector.top3_metric")}</span>
            </th>
            {tickers.map((ticker) => (
              <th key={ticker} scope="col" className="ag-sec-top3-head">
                <TickerCell ticker={ticker}>{ticker}</TickerCell>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key}>
              <th
                scope="row"
                className="ag-sec-who-col"
                title={labels.describe(key) || undefined}
              >
                {labels.metric(key)}
              </th>
              {tickers.map((ticker) => {
                const one = row(ticker);
                const leads = best.get(key)?.has(one?.ticker ?? "") ?? false;
                return (
                  <td key={ticker} className={leads ? "ag-sec-lead" : undefined}>
                    {formatMetric(key, one?.metrics[key], na, one?.currency)}
                    {leads ? (
                      <span className="ag-sec-sr"> {t("sector.top3_best")}</span>
                    ) : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
