/**
 * The last five ledger rows — what this book did recently, not what it holds.
 *
 * Every amount is in the reporting currency at the trade date's ECB rate, as
 * the Streamlit strip prints it: `/portfolio/transactions` converts each row
 * server-side with the rate the ledger replay already fetched. A row the
 * server could not convert falls back to the currency it was booked in rather
 * than to today's rate — guessing a two-year-old buy at this morning's rate
 * would quietly misstate it.
 *
 * Dividends the shares were owed that no imported row answers for ride along
 * (`/portfolio/dividends/unbooked`, merged in `recent.ts`), badged as an
 * estimate — several of them as one row of logos and their sum, which opens
 * onto each payment. They come in on their own request: a throttled Yahoo
 * costs the strip its estimates and never the ledger rows, which draw first.
 */

import { Fragment, useState } from "react";
import { get } from "../../shell/api";
import { useApi, type Query } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useTickerProfile } from "../../shell/tickers";
import { Badge } from "../../ui/Badge";
import { DenseRow, DenseRows, Responsive } from "../../ui/Rows";
import { Card, CardTitle, TickerCell } from "./ui";
import { money, plain, shortDate } from "./format";
import { owedTotal, recentRows, type RecentRow } from "./recent";
import type {
  Transaction,
  Transactions,
  UnbookedDividend,
  UnbookedDividends,
} from "./types";

/** Rows the strip shows. */
const SHOWN = 5;

/**
 * Estimates asked for: every one the grouped row could sum. The server keeps
 * the whole list cached, so asking for more than the strip draws costs nothing.
 */
const OWED = 200;

/** Marks the grouped row draws before the rest of its names become "+N". */
const STACKED = 3;

/** Ledger verbs the import catalog has a word for; anything else prints raw. */
const ACTIONS = new Set([
  "buy",
  "sell",
  "dividend",
  "fee",
  "split",
  "capital",
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
    case "capital":
      return tx.price;
    case "fee":
      return tx.fee;
    default:
      return null;
  }
}

/** One plate of the stack: the name's mark, or an empty plate holding its place. */
function StackLogo({ ticker }: { ticker: string }) {
  const profile = useTickerProfile(ticker);
  return profile?.logo ? (
    <img className="hm-owed-logo" src={profile.logo} alt="" loading="lazy" />
  ) : (
    <span className="hm-owed-logo hm-owed-logo-none" />
  );
}

/**
 * The grouped row's names: the first three marks overlapped, then how many
 * more. Decoration only — the button it sits in says what it opens, and each
 * name gets its own linked cell once it does.
 */
function LogoStack({ tickers }: { tickers: string[] }) {
  const rest = tickers.length - STACKED;
  return (
    <span className="hm-owed-stack" aria-hidden="true">
      {tickers.slice(0, STACKED).map((ticker) => (
        <StackLogo key={ticker} ticker={ticker} />
      ))}
      {rest > 0 ? <span className="hm-owed-more">+{rest}</span> : null}
    </span>
  );
}

export function RecentTransactions({ query }: { query: Query<Transactions> }) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  const [open, setOpen] = useState(false);
  const owed = useApi<UnbookedDividends>(
    () => get<UnbookedDividends>("/portfolio/dividends/unbooked", { limit: OWED }),
    [],
  );

  return (
    <Loaded query={query} skeleton={<Skeleton rows={4} />}>
      {(data) => {
        const estimates = owed.state === "loaded" ? owed.data : null;
        const rows = recentRows(
          data.transactions.slice(0, SHOWN),
          estimates?.payments ?? [],
          SHOWN,
        );
        if (rows.length === 0) return null;
        const verb = (action: string) =>
          ACTIONS.has(action) ? t(`import.action_${action}`) : action;
        const kind = (row: RecentRow) =>
          row.kind === "owed"
            ? t("home.dividends")
            : verb(row.kind === "ledger" ? row.tx.action : "dividend");
        const badge = (row: RecentRow) =>
          row.kind === "ledger" ? null : (
            <Badge tone="brand" title={t("home.estimated_hint")}>
              {t("home.estimated")}
            </Badge>
          );
        const ticker = (row: RecentRow) =>
          row.kind === "ledger"
            ? row.tx.ticker
            : row.kind === "estimated"
              ? row.dividend.ticker
              : (row.dividends[0]?.ticker ?? "");
        const estimate = (p: UnbookedDividend) =>
          (estimates && p.amount != null
            ? money(p.amount, estimates.base, lang, { digits: 2 })
            : money(p.gross, p.currency, lang, { digits: 2 })) ?? na;
        const amount = (row: RecentRow) => {
          if (row.kind === "estimated") return estimate(row.dividend);
          if (row.kind === "owed") {
            return (
              (estimates &&
                money(owedTotal(row.dividends), estimates.base, lang, { digits: 2 })) ??
              na
            );
          }
          const tx = row.tx;
          return (
            (data.base && tx.amount != null
              ? money(tx.amount, data.base, lang, { digits: 2 })
              : money(amountOf(tx), tx.currency, lang, { digits: 2 })) ?? na
          );
        };
        const key = (row: RecentRow, index: number) =>
          row.kind === "ledger"
            ? String(row.tx.id ?? `${row.tx.date}-${row.tx.ticker}-${index}`)
            : row.kind === "estimated"
              ? `owed-${row.dividend.ticker}-${row.dividend.ex_date}`
              : `owed-${row.since}-${row.date}`;
        const span = (row: Extract<RecentRow, { kind: "owed" }>) =>
          row.since === row.date
            ? shortDate(row.date, lang)
            : `${shortDate(row.since, lang)} – ${shortDate(row.date, lang)}`;
        const names = (row: Extract<RecentRow, { kind: "owed" }>) => [
          ...new Set(row.dividends.map((p) => p.ticker)),
        ];
        const toggle = (row: Extract<RecentRow, { kind: "owed" }>) => ({
          "aria-expanded": open,
          "aria-label": open
            ? t("home.owed_hide")
            : t("home.owed_show", { n: row.dividends.length }),
          onClick: () => setOpen(!open),
        });
        const dense = {
          ticker,
          badge,
          value: amount,
          sub: (row: RecentRow) => [shortDate(row.date, lang), kind(row)],
        };
        return (
          <Card>
            <CardTitle>{plain(t("home.recent_transactions"))}</CardTitle>
            <Responsive
              wide={
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
                    {rows.map((row, index) =>
                      row.kind === "owed" ? (
                        <Fragment key={key(row, index)}>
                          <tr>
                            <td className="hm-tx-date">{span(row)}</td>
                            <td>
                              <span className="hm-tx-kind">
                                {kind(row)}
                                {badge(row)}
                              </span>
                            </td>
                            <td>
                              <button
                                type="button"
                                className="hm-owed-toggle"
                                {...toggle(row)}
                              >
                                <LogoStack tickers={names(row)} />
                                <span className="hm-owed-chev" aria-hidden="true" />
                              </button>
                            </td>
                            <td className="hm-num">{amount(row)}</td>
                          </tr>
                          {open
                            ? row.dividends.map((p) => (
                                <tr
                                  className="hm-owed-child"
                                  key={`${p.ticker}-${p.ex_date}`}
                                >
                                  <td className="hm-tx-date">
                                    {shortDate(p.ex_date, lang)}
                                  </td>
                                  <td>{verb("dividend")}</td>
                                  <td>
                                    <TickerCell ticker={p.ticker} name={false} />
                                  </td>
                                  <td className="hm-num">{estimate(p)}</td>
                                </tr>
                              ))
                            : null}
                        </Fragment>
                      ) : (
                        <tr key={key(row, index)}>
                          <td className="hm-tx-date">{shortDate(row.date, lang)}</td>
                          <td>
                            <span className="hm-tx-kind">
                              {kind(row)}
                              {badge(row)}
                            </span>
                          </td>
                          <td>
                            <TickerCell ticker={ticker(row)} name={false} />
                          </td>
                          <td className="hm-num">{amount(row)}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              }
              narrow={
                <div className="ag-dense">
                  {rows.map((row, index) =>
                    row.kind === "owed" ? (
                      <Fragment key={key(row, index)}>
                        <button
                          type="button"
                          className="ag-dense-row hm-owed-row"
                          {...toggle(row)}
                        >
                          <LogoStack tickers={names(row)} />
                          <div className="ag-dense-main">
                            <div className="ag-dense-l1">
                              <span className="ag-dense-sym">{kind(row)}</span>
                              {badge(row)}
                            </div>
                            <div className="ag-dense-l2">
                              {span(row)} ·{" "}
                              {t("home.owed_payments", { n: row.dividends.length })}
                            </div>
                          </div>
                          <div className="ag-dense-side">
                            <div className="ag-dense-l1">{amount(row)}</div>
                            <div className="ag-dense-l2">
                              <span className="hm-owed-chev" aria-hidden="true" />
                            </div>
                          </div>
                        </button>
                        {open ? (
                          <div className="hm-owed-children">
                            <DenseRows
                              rows={row.dividends}
                              rowKey={(p) => `${p.ticker}-${p.ex_date}`}
                              spec={{
                                ticker: (p) => p.ticker,
                                value: estimate,
                                sub: (p) => [shortDate(p.ex_date, lang)],
                              }}
                            />
                          </div>
                        ) : null}
                      </Fragment>
                    ) : (
                      <DenseRow key={key(row, index)} row={row} spec={dense} />
                    ),
                  )}
                </div>
              }
            />
            <Link page="import" className="hm-link">
              {t("home.link_import")}
            </Link>
          </Card>
        );
      }}
    </Loaded>
  );
}
