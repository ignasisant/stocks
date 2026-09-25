/**
 * The last five ledger rows — what this book did recently, not what it holds.
 *
 * Every amount is in the reporting currency at the trade date's ECB rate, as
 * the Streamlit strip prints it: `/portfolio/transactions` converts each row
 * server-side with the rate the ledger replay already fetched. A row the
 * server could not convert falls back to the currency it was booked in rather
 * than to today's rate — guessing a two-year-old buy at this morning's rate
 * would quietly misstate it.
 */

import type { Query } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Card, CardTitle, TickerCell } from "./ui";
import { money, plain, shortDate } from "./format";
import type { Transaction, Transactions } from "./types";

/** Ledger verbs the import catalog has a word for; anything else prints raw. */
const ACTIONS = new Set([
  "buy",
  "sell",
  "dividend",
  "fee",
  "split",
  "transfer_in",
  "transfer_out",
]);

/**
 * The cash a row moved, in its own currency — the fallback for a row the
 * server could not convert.
 *
 * A split moves no cash and a transfer moves shares rather than money, so both
 * come back null and print as "n/a" — a zero there would read as a free trade.
 */
function amountOf(tx: Transaction): number | null {
  switch (tx.action) {
    case "buy":
      return tx.quantity * tx.price + tx.fee;
    case "sell":
      return tx.quantity * tx.price - tx.fee;
    case "dividend":
      return tx.price;
    case "fee":
      return tx.fee;
    default:
      return null;
  }
}

export function RecentTransactions({ query }: { query: Query<Transactions> }) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");

  return (
    <Loaded query={query} skeleton={<Skeleton rows={4} />}>
      {(data) => {
        const rows = data.transactions.slice(0, 5);
        if (rows.length === 0) return null;
        return (
          <Card>
            <CardTitle>{plain(t("home.recent_transactions"))}</CardTitle>
            <table className="hm-table">
              <thead>
                <tr>
                  <th>{t("home.col_date")}</th>
                  <th>{t("home.col_type")}</th>
                  <th>{t("home.col_ticker")}</th>
                  {/* The column is one currency, so the header names it —
                      Streamlit heads it with the code alone. */}
                  <th className="hm-num">
                    {data.base
                      ? `${t("home.col_amount")} (${data.base})`
                      : t("home.col_amount")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((tx, index) => (
                  <tr key={tx.id ?? `${tx.date}-${tx.ticker}-${index}`}>
                    <td>{shortDate(tx.date, lang)}</td>
                    <td>
                      {ACTIONS.has(tx.action)
                        ? t(`import.action_${tx.action}`)
                        : tx.action}
                    </td>
                    <td>
                      <TickerCell ticker={tx.ticker} name={false} />
                    </td>
                    <td className="hm-num">
                      {(data.base && tx.amount != null
                        ? money(tx.amount, data.base, lang, { digits: 2 })
                        : money(amountOf(tx), tx.currency, lang, { digits: 2 })) ?? na}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Link page="import" className="hm-link">
              {t("home.link_import")}
            </Link>
          </Card>
        );
      }}
    </Loaded>
  );
}
