/**
 * "You in this sector": the reader's own names in this cohort, where each
 * ranks, which names outrank it and how much of the book it is.
 *
 * The podium answers "what is best here"; a holder's next question is "and
 * mine?", which the table answers only to someone who sorts seventeen rows
 * and finds their own. Placed by the same score as the podium, so #2 here is
 * the silver medal above.
 *
 * The book can also be in the sector without owning a single name of it:
 * through a fund's look-through (a world ETF is a fifth technology). That
 * part gets its own line, from `/pulse/book`'s `sector_funds`, and is enough
 * on its own to draw the card — it is the exposure a reader least knows of.
 *
 * Not drawn for a guest (their book is the shared demo ledger, not theirs)
 * nor for a reader who holds none of the cohort and no fund in the sector: a
 * card that says "nothing" is a card in the way.
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
  viaFunds = null,
}: {
  rows: CohortRow[];
  /** Upper-cased symbol to its weight in the book (a fraction of 1). */
  held: ReadonlyMap<string, number | null>;
  /** The whole sector's share of the book, from `/pulse/book`. */
  sectorWeight: number | null;
  /** Fund symbol to the share of the book it puts in this sector. */
  viaFunds?: Readonly<Record<string, number>> | null;
}) {
  const t = useT();
  const places = heldPlaces(rows, held);
  const funds = Object.entries(viaFunds ?? {})
    .filter(([, share]) => share >= 0.0005)
    .sort((a, b) => b[1] - a[1]);
  const viaTotal = funds.reduce((sum, [, share]) => sum + share, 0);
  if (places.length === 0 && funds.length === 0) return null;
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
      {funds.length ? (
        <p className="ag-sec-you-funds">
          {t("sector.you_funds", {
            pct: percent(viaTotal, { digits: 1, tight: true }) ?? "",
          })}{" "}
          {funds.map(([ticker, share], index) => (
            <span key={ticker}>
              {index ? ", " : null}
              {/* A Morningstar code (0P…) says nothing on its own: the fund's
                  name goes after it. A listed ETF's symbol is enough. */}
              {ticker.startsWith("0P") ? (
                <TickerCell ticker={ticker} />
              ) : (
                <TickerCell ticker={ticker} name={false}>
                  {ticker}
                </TickerCell>
              )}{" "}
              {percent(share, { digits: 1, tight: true })}
            </span>
          ))}
        </p>
      ) : null}
      {places.length ? (
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
      ) : null}
      <p className="ag-sec-map-next">
        <Link page="review">{t("sector.see_review")}</Link>
      </p>
    </section>
  );
}
