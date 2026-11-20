/**
 * Every ledger row of this one holding: what went in, what came out, when,
 * at what price and through which broker.
 *
 * The page showed the position and the latest buy, and drew the fills on the
 * chart, but the rows themselves were on no screen: Home lists the last five
 * of the whole book, and a reader checking one fund's contributions against a
 * statement had to ask the chat for them.
 *
 * The rows are the ledger's as imported (`GET /portfolio/transactions`), not
 * the chart's fills: a fill is split-scaled and restated into the listing's
 * currency so it sits on the candles, while a reader reconciling wants the
 * quantity and price the statement printed. `exact` keeps a sibling listing
 * (`ASML` beside `ASML.AS`) out — the same rows the chart marks.
 *
 * Each row's amount is in the reporting currency at its trade date's rate,
 * converted server-side; a row with no rate prints in its own currency rather
 * than at today's.
 */

import { useState } from "react";
import type { Transaction, Transactions } from "../../api.gen";
import { calendarDay } from "../../shell/dates";
import { DASH, money, percent, shares } from "../../shell/format";
import { useLang, useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useApi } from "../../shell/useApi";
import { getTransactions } from "./data";
import type { Translate } from "./format";
import type { TickerPosition } from "./types";
import { Card, Empty, Metric, Metrics, Note, Scroll, useMobile } from "./ui";

/** Rows on show before the rest fold behind their count. */
export const FOLD_ROWS = 8;

/** Ledger verbs the import catalog has a word for; anything else prints raw. */
const VERBS = new Set([
  "buy",
  "sell",
  "dividend",
  "fee",
  "split",
  "capital",
  "transfer_in",
  "transfer_out",
]);

/** Note prefixes that are buckets rather than brands, so they are translated. */
const GENERIC = new Set(["manual", "unknown", "other"]);

/** The cash a row moved, in its own currency; null where none moved. */
export function nativeAmount(tx: Transaction): number | null {
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

/** The totals the card heads with, in the reporting currency. */
export type Totals = {
  /** Bought, fees included. */
  invested: number;
  /** Sold, fees taken off. */
  withdrawn: number;
  /** Dividends and returns of capital. */
  income: number;
  /** Rows the sums above had to leave out: no rate for their day. */
  unconverted: number;
};

export function totals(rows: Transaction[]): Totals {
  const out: Totals = { invested: 0, withdrawn: 0, income: 0, unconverted: 0 };
  for (const tx of rows) {
    const into =
      tx.action === "buy"
        ? "invested"
        : tx.action === "sell"
          ? "withdrawn"
          : tx.action === "dividend" || tx.action === "capital"
            ? "income"
            : null;
    if (!into) continue;
    if (tx.amount === null || !Number.isFinite(tx.amount)) out.unconverted += 1;
    else out[into] += tx.amount;
  }
  return out;
}

/** The broker a row came through: the note's first word, as `stocks.edits` reads it. */
export function brokerKey(note: string): string {
  return (note.trim().split(/\s+/)[0] ?? "").toLowerCase();
}

/** The listing's last price, in the major unit a ledger row is priced in. */
export type LastPrice = { price: number | null; currency: string | null };

/**
 * What each buy and sale did, as a fraction: a buy against the last price
 * (what it has made since), a sale against the average cost it closed (what it
 * realized). Keyed by the row's place in `rows`; a row with no answer has no
 * entry.
 *
 * Average cost, as the position card reads it, not the lots a tax method
 * matches: the page has one cost for the holding and this is it. A later split
 * scales an earlier price down to today's shares. A row in another currency
 * than the one compared against gets nothing rather than a gap that is the
 * exchange rate's, and once one has entered the average, so does every sale
 * after it.
 */
export function rowReturns(
  rows: Transaction[],
  last: LastPrice | null,
): Map<number, number> {
  const out = new Map<number, number>();
  const order = rows
    .map((tx, at) => ({ tx, at }))
    .sort((a, b) => a.tx.date.localeCompare(b.tx.date) || b.at - a.at);
  // Splits after each row: the factor that turns its price into today's.
  const after = new Map<number, number>();
  let factor = 1;
  for (const { tx, at } of [...order].reverse()) {
    after.set(at, factor);
    if (tx.action === "split" && tx.quantity > 0) factor *= tx.quantity;
  }
  let units = 0;
  let cost = 0;
  let currency: string | null = null;
  let mixed = false;
  for (const { tx, at } of order) {
    const ccy = tx.currency.toUpperCase();
    if (tx.action === "buy" && tx.quantity > 0) {
      const paid = tx.price / (after.get(at) ?? 1);
      if (last?.price && last.currency?.toUpperCase() === ccy && paid > 0)
        out.set(at, last.price / paid - 1);
      if (currency !== null && currency !== ccy) mixed = true;
      currency ??= ccy;
      units += tx.quantity;
      cost += tx.quantity * tx.price + tx.fee;
    } else if (tx.action === "split" && tx.quantity > 0) {
      units *= tx.quantity;
    } else if (tx.action === "capital") {
      cost = Math.max(0, cost - tx.price);
    } else if (tx.action === "sell" && tx.quantity > 0 && units > 0) {
      const avg = cost / units;
      if (!mixed && currency === ccy && avg > 0 && tx.price > 0)
        out.set(at, tx.price / avg - 1);
      const sold = Math.min(tx.quantity, units);
      cost -= avg * sold;
      units -= sold;
      if (units <= 1e-9) {
        units = 0;
        cost = 0;
        currency = null;
        mixed = false;
      }
    }
  }
  return out;
}

/**
 * The average price paid: the position's own when it is held (what the
 * position card shows), else every buy's, split-adjusted, when they share a
 * currency.
 */
export function averagePrice(
  rows: Transaction[],
  position: TickerPosition,
): { price: number; currency: string } | null {
  if (position.avg_cost_native && position.currency)
    return { price: position.avg_cost_native, currency: position.currency };
  let units = 0;
  let paid = 0;
  let currency: string | null = null;
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  for (const tx of sorted) {
    if (tx.action === "split" && tx.quantity > 0) units *= tx.quantity;
    if (tx.action !== "buy" || tx.quantity <= 0) continue;
    const ccy = tx.currency.toUpperCase();
    if (currency !== null && currency !== ccy) return null;
    currency = ccy;
    units += tx.quantity;
    paid += tx.quantity * tx.price + tx.fee;
  }
  return currency && units > 0 ? { price: paid / units, currency } : null;
}

export function TransactionsSection({
  ticker,
  base,
  position,
  units,
  last,
}: {
  ticker: string;
  base: string;
  /** The holding, for its brokers' names; a new one refetches the rows. */
  position: TickerPosition;
  /** Count in units — a coin — rather than shares. */
  units: boolean;
  /** The listing's last price, what each buy is measured against. */
  last: LastPrice | null;
}) {
  const t = useT();
  // Keyed on the position as well: an edit, an added trade or a repaired
  // split reloads it, and the rows under it must follow.
  const query = useApi(() => getTransactions(ticker, base), [ticker, base, position]);
  return (
    <Card title={t("ticker.tx_title")}>
      <Loaded query={query} skeleton={<Skeleton rows={4} />}>
        {(data) => (
          <Rows data={data} position={position} units={units} last={last} t={t} />
        )}
      </Loaded>
    </Card>
  );
}

function Rows({
  data,
  position,
  units,
  last,
  t,
}: {
  data: Transactions;
  position: TickerPosition;
  units: boolean;
  last: LastPrice | null;
  t: Translate;
}) {
  const lang = useLang();
  const mobile = useMobile();
  const rows = data.transactions;
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return <Empty>{t("ticker.tx_empty")}</Empty>;

  const base = data.base ?? undefined;
  const sum = totals(rows);
  const returns = rowReturns(rows, last);
  const average = averagePrice(rows, position);
  const shown = open ? rows : rows.slice(0, FOLD_ROWS);
  const verb = (action: string) => {
    const word = VERBS.has(action) ? t(`import.action_${action}`) : action;
    return word.charAt(0).toUpperCase() + word.slice(1);
  };
  const brands = new Map(position.custody.map((one) => [one.broker, one.name]));
  const broker = (tx: Transaction) => {
    const key = brokerKey(tx.note);
    if (!key || GENERIC.has(key)) return t(`portfolio.broker_${key || "unknown"}`);
    return (
      brands.get(key) || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    );
  };
  const quantity = (tx: Transaction) => {
    if (tx.action === "split") return tx.quantity ? `×${shares(tx.quantity)}` : DASH;
    if (tx.action === "dividend" || tx.action === "capital" || tx.action === "fee")
      return DASH;
    return shares(tx.quantity) ?? DASH;
  };
  // A dividend's or a return of capital's price column holds its total, which
  // the amount already says: a per-share price there would be a misreading.
  const price = (tx: Transaction) =>
    tx.action === "buy" || tx.action === "sell"
      ? (money(tx.price, { currency: tx.currency, digits: 2 }) ?? DASH)
      : DASH;
  const fee = (tx: Transaction) =>
    tx.fee ? (money(tx.fee, { currency: tx.currency, digits: 2 }) ?? DASH) : DASH;
  const amount = (tx: Transaction) =>
    (base && tx.amount !== null
      ? money(tx.amount, { currency: base, digits: 2 })
      : money(nativeAmount(tx), { currency: tx.currency, digits: 2 })) ?? DASH;
  const tone = (tx: Transaction) =>
    tx.action === "sell" ? "tk-tx-out" : tx.action === "buy" ? "tk-tx-in" : undefined;
  const key = (tx: Transaction, index: number) =>
    String(tx.id ?? `${tx.date}-${tx.action}-${index}`);
  const inBase = (value: number) => money(value, { currency: base, digits: 2 }) ?? DASH;
  const count = t(units ? "ticker.tx_col_units" : "ticker.tx_col_shares");
  const change = (index: number) => {
    const value = returns.get(index);
    return value === undefined ? DASH : (percent(value, { signed: true }) ?? DASH);
  };
  const changeTone = (index: number) => {
    const value = returns.get(index);
    if (value === undefined || value === 0) return "tk-tx-num";
    return value > 0 ? "tk-tx-num tk-is-green" : "tk-tx-num tk-is-red";
  };

  return (
    <>
      <Metrics>
        <Metric
          label={t("ticker.tx_invested")}
          value={inBase(sum.invested)}
          note={
            data.total === 1
              ? t("ticker.tx_count_one")
              : t("ticker.tx_count_n", { n: data.total })
          }
        />
        {average ? (
          <Metric
            label={t("ticker.tx_average")}
            value={
              money(average.price, { currency: average.currency, digits: 2 }) ?? DASH
            }
          />
        ) : null}
        {sum.withdrawn ? (
          <Metric label={t("ticker.tx_withdrawn")} value={inBase(sum.withdrawn)} />
        ) : null}
        {sum.income ? (
          <Metric label={t("ticker.tx_income")} value={inBase(sum.income)} />
        ) : null}
      </Metrics>
      {mobile ? (
        <div className="tk-stack tk-tx">
          {shown.map((tx, index) => (
            <div className="tk-stack-card" key={key(tx, index)}>
              <p className="tk-stack-title">
                <span className={tone(tx)}>{verb(tx.action)}</span>
                {" · "}
                {calendarDay(tx.date, lang)}
              </p>
              <Line label={count} value={quantity(tx)} />
              <Line label={t("ticker.tx_col_price")} value={price(tx)} />
              <Line
                label={t("ticker.tx_col_change")}
                value={change(index)}
                className={changeTone(index)}
              />
              <Line label={t("ticker.tx_col_fee")} value={fee(tx)} />
              <Line label={t("ticker.tx_col_amount")} value={amount(tx)} />
              <Line label={t("ticker.tx_col_broker")} value={broker(tx)} />
            </div>
          ))}
        </div>
      ) : (
        <Scroll>
          <table className="tk-table tk-tx">
            <thead>
              <tr>
                <th>{t("ticker.tx_col_date")}</th>
                <th>{t("ticker.tx_col_type")}</th>
                <th className="tk-tx-num">{count}</th>
                <th className="tk-tx-num">{t("ticker.tx_col_price")}</th>
                <th className="tk-tx-num">{t("ticker.tx_col_change")}</th>
                <th className="tk-tx-num">{t("ticker.tx_col_fee")}</th>
                {/* One currency down the column, so the header names it. */}
                <th className="tk-tx-num">
                  {base
                    ? `${t("ticker.tx_col_amount")} (${base})`
                    : t("ticker.tx_col_amount")}
                </th>
                <th>{t("ticker.tx_col_broker")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((tx, index) => (
                <tr key={key(tx, index)}>
                  <td>{calendarDay(tx.date, lang)}</td>
                  <td className={tone(tx)}>{verb(tx.action)}</td>
                  <td className="tk-tx-num">{quantity(tx)}</td>
                  <td className="tk-tx-num">{price(tx)}</td>
                  <td className={changeTone(index)}>{change(index)}</td>
                  <td className="tk-tx-num">{fee(tx)}</td>
                  <td className="tk-tx-num">{amount(tx)}</td>
                  <td>{broker(tx)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
      {rows.length > FOLD_ROWS ? (
        <button
          type="button"
          className="ag-btn tk-show-more"
          aria-expanded={open}
          onClick={() => setOpen((was) => !was)}
        >
          {open ? t("ticker.tx_hide") : t("ticker.tx_show", { n: rows.length })}
        </button>
      ) : null}
      {returns.size ? <Note>{t("ticker.tx_change_help")}</Note> : null}
      {data.total > rows.length ? (
        <Note>{t("ticker.tx_cut", { n: rows.length, total: data.total })}</Note>
      ) : null}
      {sum.unconverted ? (
        <Note>{t("ticker.tx_unconverted", { n: sum.unconverted })}</Note>
      ) : null}
    </>
  );
}

function Line({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <p className="tk-stack-line">
      <span>{label}</span>
      <span className={className}>{value}</span>
    </p>
  );
}
