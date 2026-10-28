/**
 * Held and favourite names sitting within 2% of a 52-week high or low.
 *
 * The scope is the server's (`stocks.api.home.extremes_scope`): the book's own
 * positions, whether or not they are on the watchlist, plus the starred names,
 * crypto left out. When that set is empty there is nothing to scan
 * and the card does not come at all, which is a different state from a scan
 * that found no name at an edge (`home.no_extremes`).
 *
 * The rows come in two runs, highs then lows, each under its own heading the
 * way the movers card beside it splits gains from losses. The heading says
 * which edge, so a row only says how far: `distance: null` is at or beyond
 * the extreme, which is a different fact from being 0% away from it — a word
 * (`home.at_high`) against a signed percentage.
 */

import { get } from "../../shell/api";
import { useApi, type Query } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { DenseRows, Responsive } from "../../ui/Rows";
import { CardQuery, Card, CardTitle, Note, TickerCell } from "./ui";
import { decimal, money, percent, plain, priceDigits, type Translate } from "./format";
import type { Extreme, Extremes } from "./types";
import type { Book } from "./Glance";

function gap(extreme: Extreme, t: Translate, lang: string): string {
  // Within a hundredth of a percent prints as "-0,0%": that is the edge.
  if (extreme.distance === null || Math.abs(extreme.distance) < 0.0005)
    return t(extreme.edge === "high" ? "home.at_high" : "home.at_low");
  return percent(extreme.distance, lang, { signed: true, digits: 1 }) ?? "";
}

/** The two runs the card draws, highs first; an empty run drops out. */
const RUNS = [
  { edge: "high", label: "home.extremes_highs" },
  { edge: "low", label: "home.extremes_lows" },
] as const;

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

/** The scan's rows split by edge, in `RUNS` order, empty runs left out. */
function runs(extremes: Extreme[]) {
  return RUNS.map((run) => ({
    ...run,
    rows: extremes.filter((extreme) => extreme.edge === run.edge),
  })).filter((run) => run.rows.length > 0);
}

export function ExtremesCard({
  query,
  book,
}: {
  query: Query<Extremes | null>;
  /** The book's positions, for the currency a held name's quote is in. */
  book?: Query<Book | null>;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  const currencies = new Map(
    (book?.state === "loaded" ? (book.data?.positions.positions ?? []) : []).map(
      (position) => [position.ticker, position.currency],
    ),
  );
  // The quote's own currency when the book knows it; a name it does not hold
  // keeps the bare figure rather than a guessed symbol.
  const price = (extreme: Extreme) => {
    const currency = currencies.get(extreme.ticker);
    return (
      (currency
        ? money(extreme.price, currency, lang, { digits: priceDigits(extreme.price) })
        : decimal(extreme.price, lang, priceDigits(extreme.price))) ?? na
    );
  };

  return (
    <CardQuery
      query={query}
      title={plain(t("home.extremes_52w"))}
      note={t("home.extremes_unavailable")}
      skeleton={<Skeleton shape="table" rows={4} />}
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
                        <th className="hm-num">{t("home.col_from_edge")}</th>
                      </tr>
                    </thead>
                    {runs(data.extremes).map(({ edge, label, rows }) => (
                      <tbody key={edge}>
                        <tr className="hm-run-head">
                          <th scope="rowgroup" colSpan={3}>
                            {t(label)}
                          </th>
                        </tr>
                        {rows.map((extreme) => (
                          <tr key={extreme.ticker}>
                            {/* The name ellipsises here rather than wrapping the
                            row onto two lines in a narrow column. */}
                            <td className="hm-tick-cell">
                              <TickerCell ticker={extreme.ticker} />
                            </td>
                            <td className="hm-num">{price(extreme)}</td>
                            <td className="hm-num hm-muted">{gap(extreme, t, lang)}</td>
                          </tr>
                        ))}
                      </tbody>
                    ))}
                  </table>
                }
                narrow={runs(data.extremes).map(({ edge, label, rows }) => (
                  <div key={edge} className="hm-run">
                    <p className="hm-caption">{t(label)}</p>
                    <DenseRows
                      rows={rows}
                      rowKey={(extreme) => extreme.ticker}
                      spec={{
                        ticker: (extreme) => extreme.ticker,
                        names: true,
                        value: price,
                        delta: (extreme) => (
                          <span className="hm-muted">{gap(extreme, t, lang)}</span>
                        ),
                      }}
                    />
                  </div>
                ))}
              />
            )}
          </Card>
        )
      }
    </CardQuery>
  );
}
