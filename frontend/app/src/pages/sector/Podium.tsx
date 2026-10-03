/**
 * The best three of this cohort — the reason to open the page, so it opens it.
 *
 * What the medal claims, and what it does not: best three *of this cohort*, on
 * valuation and quality only. No momentum, no analyst targets, no margin of
 * safety. The caption under it says so, because a numbered badge invites the
 * opposite reading, and it is not decoration to be trimmed.
 *
 * Three places in one card rather than three cards: a bordered tile inside a
 * bordered card is the "cards inside cards" shape that makes a dense page
 * unreadable, and the rule between the columns separates them for free.
 */

import { useT } from "../../shell/i18n";
import { useLabels } from "./labels";
import { formatMetric } from "./metrics";
import type { CohortRow } from "./types";
import { TickerCell } from "../../shell/tickers";
import { CompanyName } from "./Cohort";

/**
 * ROIC and P/E rather than the whole KPI row: the score is a mean of eighteen,
 * and quoting all of them under a headline number explains nothing. These two
 * say "compounds well" and "costs this much", which is the trade the reader is
 * actually making between the three.
 */
export const FUNDAMENTAL_WHY = ["roic", "pe_ttm"];

/**
 * 3-month return and distance from the 52-week high: how much it has already
 * moved, and how much room is left before it would be making a new one.
 */
export const TECHNICAL_WHY = ["roc_63", "pct_from_high"];

/**
 * One "best three of this cohort" card. Two placements on the page — one
 * scored on valuation and quality (`comp_scores`), one on technical momentum
 * (`technical_scores`) — share this component rather than forking it:
 * same medal/score/why-line shape, different title, copy and metric keys.
 *
 * Three places in one card rather than three cards: a bordered tile inside a
 * bordered card is the "cards inside cards" shape that makes a dense page
 * unreadable, and the rule between the columns separates them for free.
 */
export function Podium({
  title,
  emptyText,
  helpText,
  why,
  podium,
  rows,
}: {
  title: string;
  emptyText: string;
  helpText: string;
  /** The two metric keys that carry a place — see FUNDAMENTAL_WHY/TECHNICAL_WHY. */
  why: readonly string[];
  podium: string[];
  rows: CohortRow[];
}) {
  const t = useT();
  const labels = useLabels();
  const na = t("sector.na");

  return (
    <section className="ag-sec-card">
      <h2 className="ag-sec-h2">{title}</h2>
      {podium.length === 0 ? (
        <p className="ag-sec-caption">{emptyText}</p>
      ) : (
        <div className="ag-sec-podium">
          {podium.map((ticker, index) => {
            const row = rows.find(
              (candidate) => candidate.ticker === ticker.toUpperCase(),
            );
            const score = row?.score;
            return (
              <div className="ag-sec-place" key={ticker}>
                <div className="ag-sec-pod">
                  <span
                    className={
                      index === 0 ? "ag-sec-pod-n ag-sec-pod-1" : "ag-sec-pod-n"
                    }
                  >
                    {index + 1}
                  </span>
                  <TickerCell className="ag-sec-sym" ticker={ticker}>
                    {ticker}
                  </TickerCell>
                </div>
                {/* The name under the symbol: three medals over bare symbols
                    ask the reader to know every listing in the sector by
                    heart. */}
                <CompanyName ticker={ticker} className="ag-sec-pod-name" />
                <div className="ag-sec-score">
                  {typeof score === "number" ? Math.round(score * 100) : na}
                  <span>/100</span>
                </div>
                <div className="ag-sec-why">
                  {why.map((key, place) => (
                    <span key={key}>
                      {place > 0 ? <i>·</i> : null}
                      {`${labels.metric(key)} ${formatMetric(key, row?.metrics[key], na)}`}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {/* How the ranking is built, only when there is one: under the empty
          card it would explain a ranking "relative to this cohort of 0". */}
      {podium.length > 0 && <p className="ag-sec-caption">{helpText}</p>}
    </section>
  );
}
