/**
 * Held and favourite names sitting within 2% of a 52-week high or low.
 *
 * The scope is the server's (`stocks.api.home.extremes_scope`): the book's own
 * positions, whether or not they are on the watchlist, plus the starred names,
 * crypto left out. When that set is empty there is nothing to scan
 * and the card does not come at all, which is a different state from a scan
 * that found no name at an edge (`home.no_extremes`).
 *
 * `distance: null` means the price is at or beyond the extreme, which is a
 * different fact from being 0% away from it — the two get different words,
 * `home.at_52w_high` against `home.from_52w_high`.
 */

import { get } from "../../shell/api";
import { useApi, type Query } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { DenseRows, Responsive } from "../../ui/Rows";
import { CardQuery, Card, CardTitle, Note, TickerCell } from "./ui";
import { decimal, percent, plain, type Translate } from "./format";
import type { Extreme, Extremes } from "./types";

function where(extreme: Extreme, t: Translate, lang: string): string {
  const high = extreme.edge === "high";
  if (extreme.distance === null)
    return t(high ? "home.at_52w_high" : "home.at_52w_low");
  const gap = percent(extreme.distance, lang, { signed: true, digits: 1 }) ?? "";
  return t(high ? "home.from_52w_high" : "home.from_52w_low", { pct: gap });
}

/**
 * The scan, read by the page rather than by the card: the movers card beside
 * it draws as many rows as this one does (`moverRows`). `enabled` false — the
 * card put away — answers null without a request.
 */
export function useExtremes(nonce: number, enabled: boolean): Query<Extremes | null> {
  return useApi<Extremes | null>(
    () => (enabled ? get<Extremes>("/extremes") : Promise.resolve(null)),
    [nonce, enabled],
  );
}

/** Fewest and most rows a movers side draws, whatever the scan found. */
const MOVER_ROWS = { min: 3, max: 7 } as const;

/**
 * How many rows each movers side draws: the extremes card's own count, so the
 * two halves of the row end level, held between 3 and 7. A scan still in
 * flight, failed, hidden or empty leaves the floor.
 */
export function moverRows(query: Query<Extremes | null>): number {
  const count = query.state === "loaded" && query.data ? query.data.extremes.length : 0;
  return Math.min(MOVER_ROWS.max, Math.max(MOVER_ROWS.min, count));
}

export function ExtremesCard({ query }: { query: Query<Extremes | null> }) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");

  return (
    <CardQuery
      query={query}
      title={plain(t("home.extremes_52w"))}
      note={t("home.extremes_unavailable")}
      skeleton={<Skeleton rows={4} />}
    >
      {(data) =>
        !data || data.scanned === 0 ? null : (
          <Card>
            <CardTitle>{plain(t("home.extremes_52w"))}</CardTitle>
            {data.extremes.length === 0 ? (
              <Note>{t("home.no_extremes")}</Note>
            ) : (
              <Responsive
                wide={
                  <table className="hm-table">
                    <thead>
                      <tr>
                        <th>{t("home.col_ticker")}</th>
                        <th className="hm-num">{t("home.col_last_close")}</th>
                        <th>{t("home.col_52week")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.extremes.map((extreme) => (
                        <tr key={`${extreme.ticker}-${extreme.edge}`}>
                          {/* The name ellipsises here rather than wrapping the
                          row onto two lines in a narrow column. */}
                          <td className="hm-tick-cell">
                            <TickerCell ticker={extreme.ticker} />
                          </td>
                          <td className="hm-num">
                            {decimal(extreme.price, lang) ?? na}
                          </td>
                          <td className="hm-muted">{where(extreme, t, lang)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                }
                narrow={
                  <DenseRows
                    rows={data.extremes}
                    rowKey={(extreme) => `${extreme.ticker}-${extreme.edge}`}
                    spec={{
                      ticker: (extreme) => extreme.ticker,
                      value: (extreme) => decimal(extreme.price, lang) ?? na,
                      sub: (extreme) => [where(extreme, t, lang)],
                    }}
                  />
                }
              />
            )}
          </Card>
        )
      }
    </CardQuery>
  );
}
