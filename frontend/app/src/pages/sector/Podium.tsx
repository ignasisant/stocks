/**
 * The best three of this cohort — the reason to open the page, so it opens it.
 *
 * One card, two lenses: valuation and quality (`podium`, `rows`) or technical
 * momentum (`tech_podium`, `tech_rows`). Two stacked cards asked the reader to
 * compare six names across a scroll; a switch keeps one question on screen.
 *
 * What the medal claims, and what it does not: best three *of this cohort*.
 * The caption under it says so, because a numbered badge invites the opposite
 * reading, and it is not decoration to be trimmed.
 *
 * Each place ends in what to do with it. A name the reader holds says so and
 * points to Sell or add, where its verdict is read with their weight; any
 * other carries the Review page's verdict on it as a new buy and opens it
 * there in one tap.
 *
 * Three places in one card rather than three cards: a bordered tile inside a
 * bordered card is the "cards inside cards" shape that makes a dense page
 * unreadable, and the rule between the columns separates them for free.
 */

import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { TickerCell } from "../../shell/tickers";
import { Segmented } from "../../ui/Segmented";
import { verdictTone } from "../review/format";
import { CompanyName } from "./Cohort";
import { useLabels } from "./labels";
import { formatMetric } from "./metrics";
import type { CohortRow, SectorCohort } from "./types";

/**
 * ROIC and P/E rather than the whole KPI row: the score is a mean of eighteen,
 * and quoting all of them under a headline number explains nothing. These two
 * say "compounds well" and "costs this much", which is the trade the reader is
 * actually making between the three.
 */
const FUNDAMENTAL_WHY = ["roic", "pe_ttm"];

/**
 * 3-month return and distance from the 52-week high: how much it has already
 * moved, and how much room is left before it would be making a new one.
 */
const TECHNICAL_WHY = ["roc_63", "pct_from_high"];

export type Lens = "fund" | "tech";

export function Podium({
  data,
  lens,
  onLens,
  held,
}: {
  data: SectorCohort;
  lens: Lens;
  onLens: (lens: Lens) => void;
  /** The reader's holdings, upper-cased. */
  held: ReadonlySet<string>;
}) {
  const t = useT();
  const labels = useLabels();
  const na = t("sector.na");
  const tech = lens === "tech";
  const podium = tech ? data.tech_podium : data.podium;
  const rows = tech ? data.tech_rows : data.rows;
  const why = tech ? TECHNICAL_WHY : FUNDAMENTAL_WHY;

  return (
    <section className="ag-sec-card">
      <div className="ag-sec-card-head">
        <h2 className="ag-sec-h2">
          {t(tech ? "sector.tech_podium_title" : "sector.podium_title")}
        </h2>
        <Segmented<Lens>
          label={t("sector.lens")}
          value={lens}
          onPick={onLens}
          items={[
            { id: "fund", label: t("sector.lens_fund") },
            { id: "tech", label: t("sector.lens_tech") },
          ]}
        />
      </div>
      {podium.length === 0 ? (
        <p className="ag-sec-caption">
          {t(tech ? "sector.no_tech_podium" : "sector.no_podium")}
        </p>
      ) : (
        <ol className="ag-sec-podium">
          {podium.map((ticker, index) => (
            <Place
              key={ticker}
              ticker={ticker}
              index={index}
              row={find(rows, ticker)}
              // The verdict is the fundamentals' own: a momentum row has none.
              judged={find(data.rows, ticker)?.judged ?? null}
              why={why}
              held={held.has(ticker.toUpperCase())}
              na={na}
              labels={labels}
            />
          ))}
        </ol>
      )}
      {/* How the ranking is built, only when there is one: under the empty
          card it would explain a ranking "relative to this cohort of 0". */}
      {podium.length > 0 && (
        <p className="ag-sec-caption">
          {tech
            ? t("sector.tech_podium_help", { cohort: data.tech_rows.length })
            : t("sector.podium_help", { cohort: data.rows.length })}
        </p>
      )}
    </section>
  );
}

function find(rows: readonly CohortRow[], ticker: string): CohortRow | undefined {
  return rows.find((candidate) => candidate.ticker === ticker.toUpperCase());
}

function Place({
  ticker,
  index,
  row,
  judged,
  why,
  held,
  na,
  labels,
}: {
  ticker: string;
  index: number;
  row: CohortRow | undefined;
  judged: CohortRow["judged"];
  why: readonly string[];
  held: boolean;
  na: string;
  labels: ReturnType<typeof useLabels>;
}) {
  const t = useT();
  const score = typeof row?.score === "number" ? Math.round(row.score * 100) : null;
  const verdict = judged && judged.verdict !== "unrated" ? judged.verdict : null;
  return (
    <li className="ag-sec-place">
      <div className="ag-sec-pod">
        <span className={index === 0 ? "ag-sec-pod-n ag-sec-pod-1" : "ag-sec-pod-n"}>
          {index + 1}
        </span>
        <TickerCell className="ag-sec-sym" ticker={ticker}>
          {ticker}
        </TickerCell>
        {held ? <span className="ag-sec-held">{t("sector.held_badge")}</span> : null}
      </div>
      {/* The name under the symbol: three medals over bare symbols ask the
          reader to know every listing in the sector by heart. */}
      <CompanyName ticker={ticker} className="ag-sec-pod-name" />
      <div className="ag-sec-score">
        {score ?? na}
        <span>/100</span>
      </div>
      {/* The score is a percentile in this cohort, so it reads as a bar the
          three can be compared on, not as a grade out of a hundred. */}
      {score !== null ? (
        <span className="ag-sec-bar" aria-hidden="true">
          <span style={{ inlineSize: `${score}%` }} />
        </span>
      ) : null}
      <div className="ag-sec-why">
        {why.map((key, place) => (
          <span key={key}>
            {place > 0 ? <i>·</i> : null}
            {`${labels.metric(key)} ${formatMetric(key, row?.metrics[key], na, row?.currency)}`}
          </span>
        ))}
      </div>
      <div className="ag-sec-act">
        {held ? (
          <Link page="review" className="ag-sec-act-link">
            {t("sector.see_review")}
          </Link>
        ) : (
          <>
            {verdict ? (
              <span className={`ag-chip ag-chip-${verdictTone(verdict)}`}>
                {t("sector.as_new_buy", { verdict: t(`review.verdict_${verdict}`) })}
              </span>
            ) : null}
            <Link page="review" params={{ add: ticker }} className="ag-sec-act-link">
              {t("sector.weigh")}
            </Link>
          </>
        )}
      </div>
    </li>
  );
}
