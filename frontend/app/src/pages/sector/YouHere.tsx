/**
 * "You in this sector": the reader's own names in this cohort, where each
 * ranks, which names outrank it and how much of the book it is.
 *
 * The podium answers "what is best here"; a holder's next question is "and
 * mine?", which the table answers only to someone who sorts seventeen rows
 * and finds their own. Placed by the same score as the podium, so #2 here is
 * the silver medal above.
 *
 * Not drawn for a guest (their book is the shared demo ledger, not theirs)
 * nor for a reader who holds none of the cohort: a card that says "nothing"
 * is a card in the way.
 */

import { percent } from "../../shell/format";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { TickerCell } from "../../shell/tickers";
import { CompanyName } from "./Cohort";
import { heldPlaces } from "./rank";
import type { CohortRow } from "./types";

export function YouHere({
  rows,
  held,
  sectorWeight,
}: {
  rows: CohortRow[];
  /** Upper-cased symbol to its weight in the book (a fraction of 1). */
  held: ReadonlyMap<string, number | null>;
  /** The whole sector's share of the book, from `/pulse/book`. */
  sectorWeight: number | null;
}) {
  const t = useT();
  const places = heldPlaces(rows, held);
  if (places.length === 0) return null;
  return (
    <section className="ag-sec-card">
      <h2 className="ag-sec-h2">{t("sector.you_title")}</h2>
      {sectorWeight ? (
        <p className="ag-sec-caption">
          {t("sector.you_caption", {
            pct: percent(sectorWeight, { digits: 0, tight: true }) ?? "",
          })}
        </p>
      ) : null}
      <ul className="ag-sec-you">
        {places.map((one) => (
          <li key={one.ticker} className="ag-sec-you-row">
            <span className="ag-sec-who">
              <TickerCell ticker={one.ticker}>
                <b>{one.ticker}</b>
              </TickerCell>
              <CompanyName ticker={one.ticker} />
            </span>
            <span className="ag-sec-you-place">
              {one.place === null
                ? t("sector.you_unranked")
                : t("sector.you_place", { n: one.place, of: one.of })}
            </span>
            {one.weight ? (
              <span className="ag-sec-you-weight">
                {t("sector.you_book", {
                  pct: percent(one.weight, { digits: 1, tight: true }) ?? "",
                })}
              </span>
            ) : null}
            <span className="ag-sec-you-ahead">
              {one.place === 1 ? (
                t("sector.you_leads")
              ) : one.ahead.length ? (
                <>
                  {t("sector.you_ahead")}{" "}
                  {one.ahead.map((ticker, index) => (
                    <span key={ticker}>
                      {index ? ", " : null}
                      <TickerCell ticker={ticker}>{ticker}</TickerCell>
                    </span>
                  ))}
                </>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="ag-sec-map-next">
        <Link page="review">{t("sector.see_review")}</Link>
      </p>
    </section>
  );
}
