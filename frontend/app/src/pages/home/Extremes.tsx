/**
 * Watchlist names sitting within 2% of a 52-week high or low.
 *
 * `distance: null` means the price is at or beyond the extreme, which is a
 * different fact from being 0% away from it — the two get different words,
 * `home.at_52w_high` against `home.from_52w_high`.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
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

export function ExtremesCard({ nonce }: { nonce: number }) {
  const t = useT();
  const lang = useLang();
  const query = useApi(() => get<Extremes>("/extremes"), [nonce]);
  const na = t("home.na");

  return (
    <CardQuery
      query={query}
      title={plain(t("home.extremes_52w"))}
      note={t("home.extremes_unavailable")}
      skeleton={<Skeleton rows={4} />}
    >
      {(data) => (
        <Card>
          <CardTitle>{plain(t("home.extremes_52w"))}</CardTitle>
          {data.extremes.length === 0 ? (
            <Note>{t("home.no_extremes")}</Note>
          ) : (
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
                    <td>
                      <TickerCell ticker={extreme.ticker} />
                    </td>
                    <td className="hm-num">{decimal(extreme.price, lang) ?? na}</td>
                    <td className="hm-muted">{where(extreme, t, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </CardQuery>
  );
}
