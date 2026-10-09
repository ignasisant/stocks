/**
 * Every row, held and outside, for whoever wants the whole list.
 *
 * Wide, a table with the scores and the KPIs behind them; narrow, the shell's
 * dense rows (`ui/Rows.tsx`), verdict as the pill and the move on the right.
 * Every head carries its definition behind a "?", and every row opens its
 * details in a dialog — the rule behind its verdict, its reasons spelled out
 * and the numbers its scores came from.
 *
 * A list long enough to scroll gets a search box over it: symbol, company
 * name, sector or verdict, in the reader's words. It narrows this table only —
 * the page's filters are what cut the map and the plan.
 */

import { Fragment, type ReactNode, useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { TickerCell, cachedName } from "../../shell/tickers";
import { DenseRow, Responsive } from "../../ui/Rows";
import { Reasons } from "./Actions";
import { maybe } from "../sentiment/format";
import { DetailsButton, Head, VerdictChip, PnlChip } from "./Explain";
import { bucket, findRows } from "./filter";
import { metric, money, percent, score, verdictTone } from "./format";
import type { ReviewRow } from "./types";

/** Under this many rows the whole list is on screen: no box. */
export const FIND_MIN = 6;

/**
 * The words a search box matches a row by, beyond its symbol: the company's
 * name, its sector in Yahoo's and the app's spelling, and its verdict.
 */
export function useRowWords(): (row: ReviewRow) => (string | null | undefined)[] {
  const t = useT();
  return (row) => [
    cachedName(row.symbol) ?? cachedName(row.ticker),
    row.sector,
    maybe(t, `sentiment.sector_${bucket(row)}`),
    t(`review.verdict_${row.verdict}`),
  ];
}

/**
 * A table's search box and the rows it leaves. The box is the shell's search
 * field; the count and "nothing matches" line only show while it holds text.
 */
function useFind(rows: ReviewRow[]): { rows: ReviewRow[]; box: ReactNode } {
  const t = useT();
  const [needle, setNeedle] = useState("");
  const words = useRowWords();
  const found = findRows(rows, needle, words);
  if (rows.length < FIND_MIN) return { rows, box: null };
  const query = needle.trim();
  return {
    rows: found,
    box: (
      <div className="ag-rev-find">
        <input
          type="search"
          className="ag-search-field"
          aria-label={t("review.find")}
          placeholder={t("review.find_ph")}
          value={needle}
          onChange={(event) => setNeedle(event.target.value)}
        />
        {query ? (
          <p className="ag-rev-caption" aria-live="polite">
            {found.length
              ? t("review.filter_shown", { shown: found.length, total: rows.length })
              : t("review.find_none", { query })}
          </p>
        ) : null}
      </div>
    ),
  };
}

export function HeldTable({
  rows: all,
  base,
  taxCurrency,
}: {
  rows: ReviewRow[];
  base: string;
  taxCurrency: string;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const reason = (row: ReviewRow) =>
    row.reasons[0] ? t(`review.reason_${row.reasons[0]}`) : null;
  const find = useFind(all);
  const rows = find.rows;
  return (
    <>
      {find.box}
      {rows.length > 0 && (
        <Responsive
          wide={
            <div className="ag-rev-scroll">
              <table className="ag-rev-table">
                <thead>
                  <tr>
                    <th className="ag-rev-who-col">{t("review.col_name")}</th>
                    <Head label={t("review.col_verdict")} left />
                    <Head label={t("review.col_why")} left />
                    <Head
                      label={t("review.col_quality")}
                      help={t("review.col_quality_help")}
                    />
                    <Head
                      label={t("review.col_cheapness")}
                      help={t("review.col_cheapness_help")}
                    />
                    <Head
                      label={t("review.col_weight")}
                      help={t("review.col_weight_help")}
                    />
                    <Head
                      label={t("review.col_target")}
                      help={t("review.col_target_help")}
                    />
                    <Head
                      label={t("review.col_move")}
                      help={t("review.col_move_help")}
                    />
                    <Head label={t("review.col_tax")} help={t("review.col_tax_help")} />
                    <Head label={t("review.col_pnl")} help={t("review.col_pnl_help")} />
                    <th aria-hidden="true" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.ticker}>
                      <td className="ag-rev-who-col">
                        <TickerCell ticker={row.ticker} name={false} />
                      </td>
                      <td className="ag-rev-left">
                        <VerdictChip row={row} />
                      </td>
                      <td className="ag-rev-left ag-rev-why">
                        <Reasons reasons={row.reasons} limit={2} />
                      </td>
                      <td>{score(row.quality) ?? na}</td>
                      <td>{score(row.cheapness) ?? na}</td>
                      <td>{percent(row.weight, lang) ?? na}</td>
                      <td>{percent(row.target_weight, lang) ?? "—"}</td>
                      <td className={`ag-rev-tone-${verdictTone(row.verdict)}`}>
                        {money(row.delta, base, lang, true) ?? "—"}
                      </td>
                      <td>{money(row.tax, taxCurrency, lang) ?? "—"}</td>
                      <td>
                        <PnlChip row={row} />
                      </td>
                      <td className="ag-rev-fold-cell">
                        <DetailsButton row={row} variant="icon" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          }
          narrow={
            <div className="ag-dense">
              {rows.map((row) => (
                <Fragment key={row.ticker}>
                  <DenseRow
                    row={row}
                    spec={{
                      ticker: (r) => r.ticker,
                      badge: (r) => <VerdictChip row={r} />,
                      sub: (r) => [percent(r.weight, lang), reason(r)],
                      value: (r) => money(r.delta, base, lang, true),
                      delta: (r) =>
                        r.target_weight !== null
                          ? `→ ${percent(r.target_weight, lang)}`
                          : null,
                      wrap: true,
                    }}
                  />
                  <div className="ag-rev-more-row">
                    <DetailsButton row={row} />
                  </div>
                </Fragment>
              ))}
            </div>
          }
        />
      )}
    </>
  );
}

/** The KPIs an outside name is shown with: the ones its scores lean on. */
const OUTSIDE = ["pe_fwd", "fcf_yield", "roic", "op_margin"] as const;

export function CandidateTable({ rows: all }: { rows: ReviewRow[] }) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const find = useFind(all);
  const rows = find.rows;
  return (
    <>
      {find.box}
      {rows.length > 0 && (
        <Responsive
          wide={
            <div className="ag-rev-scroll">
              <table className="ag-rev-table">
                <thead>
                  <tr>
                    <th className="ag-rev-who-col">{t("review.col_name")}</th>
                    <Head label={t("review.col_verdict")} left />
                    <Head label={t("review.col_why")} left />
                    <Head
                      label={t("review.col_quality")}
                      help={t("review.col_quality_help")}
                    />
                    <Head
                      label={t("review.col_cheapness")}
                      help={t("review.col_cheapness_help")}
                    />
                    {OUTSIDE.map((key) => (
                      <Head
                        key={key}
                        label={t(`kpi.${key}.label`)}
                        help={t(`kpi.${key}.desc`).replaceAll("*", "")}
                      />
                    ))}
                    <th aria-hidden="true" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.ticker}>
                      <td className="ag-rev-who-col">
                        <TickerCell ticker={row.ticker} name={false} />
                      </td>
                      <td className="ag-rev-left">
                        <VerdictChip row={row} />
                        {row.buy_after ? (
                          <div className="ag-rev-caption">
                            {t("review.buy_after", { date: row.buy_after })}
                          </div>
                        ) : null}
                      </td>
                      <td className="ag-rev-left ag-rev-why">
                        <Reasons reasons={row.reasons} limit={2} />
                      </td>
                      <td>{score(row.quality) ?? na}</td>
                      <td>{score(row.cheapness) ?? na}</td>
                      {OUTSIDE.map((key) => (
                        <td key={key}>{metric(key, row.metrics[key], lang) ?? na}</td>
                      ))}
                      <td className="ag-rev-fold-cell">
                        <DetailsButton row={row} variant="icon" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          }
          narrow={
            <div className="ag-dense">
              {rows.map((row) => (
                <Fragment key={row.ticker}>
                  <DenseRow
                    row={row}
                    spec={{
                      ticker: (r) => r.ticker,
                      badge: (r) => <VerdictChip row={r} />,
                      names: true,
                      sub: (r) =>
                        r.reasons.slice(0, 2).map((code) => t(`review.reason_${code}`)),
                      value: (r) =>
                        r.quality !== null
                          ? `${t("review.col_quality")} ${score(r.quality)}`
                          : na,
                      delta: (r) =>
                        r.cheapness !== null
                          ? `${t("review.col_cheapness")} ${score(r.cheapness)}`
                          : null,
                      wrap: true,
                    }}
                  />
                  <div className="ag-rev-more-row">
                    <DetailsButton row={row} />
                  </div>
                </Fragment>
              ))}
            </div>
          }
        />
      )}
    </>
  );
}
