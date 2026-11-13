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
 *
 * The book's table is grouped by verdict in reading order — to sell, to trim,
 * to add to, then what holds — each group under a header that folds it. A
 * long book opens with its holds folded: they are most of it, and nothing to
 * do. A search unfolds every group. A book with no moves at all (no targets,
 * no money to move, no tax) loses those three columns of dashes.
 *
 * A wide table's rows share the page's focus (`focus.tsx`): the row under the
 * pointer lights its dot on the map and its move in the plan, and a name
 * pointed at there lights its row here while the rest fade.
 */

import { Fragment, type ReactNode, useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { TickerCell, cachedName } from "../../shell/tickers";
import { DenseRow, Responsive } from "../../ui/Rows";
import { Reasons } from "./Actions";
import { maybe } from "../sentiment/format";
import { DetailsButton, Head, VerdictChip, PnlChip } from "./Explain";
import { bucket, findRows } from "./filter";
import { useListFocus } from "./focus";
import { useHelp } from "./lines";
import { priceDigits } from "../home/format";
import { foreign, longDay, metric, score, verdictTone } from "./format";
import { money, percent } from "../../shell/format";
import {
  ReturnCells,
  ReturnHeads,
  WindowPicker,
  useReturnLine,
  useReturns,
} from "./returns";
import type { ReviewRow, Verdict } from "./types";
import { groupByVerdict, hasMoves } from "./verdicts";

/** One share's price as its own market quotes it, not in the page's money. */
function sharePrice(row: ReviewRow, lang: string): string | null {
  if (!row.currency) return null;
  return money(row.price, {
    currency: row.currency,
    lang,
    digits: priceDigits(row.price),
  });
}

/** The quote currency beside the name, only when it is not the page's. */
function Ccy({ row, base }: { row: ReviewRow; base: string }) {
  const t = useT();
  const code = foreign(row, base);
  if (!code) return null;
  return (
    <span className="ag-rev-ccy" title={t("review.ccy_tag_help", { currency: code })}>
      {code}
    </span>
  );
}

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
function useFind(rows: ReviewRow[]): {
  rows: ReviewRow[];
  box: ReactNode;
  query: string;
} {
  const t = useT();
  const [needle, setNeedle] = useState("");
  const words = useRowWords();
  const found = findRows(rows, needle, words);
  if (rows.length < FIND_MIN) return { rows, box: null, query: "" };
  const query = needle.trim();
  return {
    rows: found,
    query,
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

/** A return column's head, as `ReturnHeads` lays it. */
const head = (label: string, help: string) => <Head label={label} help={help} />;

/**
 * Which verdict groups start folded: the holds, in a book long enough to
 * search that has something else to read first. Never while the reader is
 * searching, or has picked verdicts out: those rows were asked for.
 */
export function foldedAtFirst(rows: ReviewRow[], picked: boolean): Set<Verdict> {
  const groups = groupByVerdict(rows);
  return !picked && rows.length >= FIND_MIN && groups.length > 1
    ? new Set<Verdict>(groups.some((one) => one.verdict === "hold") ? ["hold"] : [])
    : new Set();
}

/** A verdict group's header: its name and count, and the fold. */
function GroupToggle({
  verdict,
  count,
  open,
  onToggle,
}: {
  verdict: Verdict;
  count: number;
  open: boolean;
  onToggle: () => void;
}) {
  const t = useT();
  return (
    <button
      type="button"
      className="ag-rev-group-btn"
      aria-expanded={open}
      onClick={onToggle}
    >
      <span
        className={`ag-rev-vbar-dot ag-rev-vbar-${verdictTone(verdict)}`}
        aria-hidden="true"
      />
      {t(`review.verdict_${verdict}`)}
      <span className="ag-rev-group-n">{count}</span>
    </button>
  );
}

export function HeldTable({
  rows: all,
  base,
  taxCurrency,
  picked = false,
}: {
  rows: ReviewRow[];
  base: string;
  taxCurrency: string;
  /** Verdicts picked out above: every group they leave opens unfolded. */
  picked?: boolean;
}) {
  const t = useT();
  const lang = useLang();
  const help = useHelp();
  const na = t("review.na");
  const returned = useReturnLine();
  const reason = (row: ReviewRow) =>
    row.reasons[0] ? t(`review.reason_${row.reasons[0]}`) : null;
  const find = useFind(all);
  const groups = groupByVerdict(find.rows);
  // The reader's own folds, over the default; a search opens everything.
  const [folds, setFolds] = useState<Partial<Record<Verdict, boolean>>>({});
  const first = foldedAtFirst(all, picked);
  const isOpen = (verdict: Verdict) =>
    !!find.query || !(folds[verdict] ?? first.has(verdict));
  const toggle = (verdict: Verdict) =>
    setFolds({ ...folds, [verdict]: isOpen(verdict) });
  const rows = groups.flatMap((group) => (isOpen(group.verdict) ? group.rows : []));
  const moves = hasMoves(all);
  const returns = useReturns();
  // Name, verdict, why, two scores, weight, price, P&L, details; the three
  // moves; the three returns.
  const columns = 9 + (moves ? 3 : 0) + (returns ? 3 : 0);
  const focus = useListFocus(
    "held",
    rows.map((row) => row.ticker),
  );
  return (
    <>
      <div className="ag-rev-tools">
        {find.box}
        <WindowPicker />
      </div>
      {groups.length > 0 && (
        <Responsive
          wide={
            <div className="ag-rev-scroll">
              <table className={`ag-rev-table${focus.fading ? " ag-rev-fading" : ""}`}>
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
                    {moves ? (
                      <>
                        <Head
                          label={t("review.col_target")}
                          help={help("review.col_target_help")}
                        />
                        <Head
                          label={t("review.col_move")}
                          help={t("review.col_move_help")}
                        />
                        <Head
                          label={t("review.col_tax")}
                          help={t("review.col_tax_help")}
                        />
                      </>
                    ) : null}
                    <Head
                      label={t("review.col_price")}
                      help={t("review.col_price_help")}
                    />
                    <Head label={t("review.col_pnl")} help={t("review.col_pnl_help")} />
                    <ReturnHeads head={head} />
                    <th aria-hidden="true" />
                  </tr>
                </thead>
                {groups.map((group) => (
                  <tbody key={group.verdict}>
                    <tr className="ag-rev-group">
                      <th colSpan={columns} scope="rowgroup">
                        <GroupToggle
                          verdict={group.verdict}
                          count={group.rows.length}
                          open={isOpen(group.verdict)}
                          onToggle={() => toggle(group.verdict)}
                        />
                      </th>
                    </tr>
                    {isOpen(group.verdict)
                      ? group.rows.map((row) => (
                          <tr
                            key={row.ticker}
                            className={focus.on(row.ticker) ? "ag-rev-on" : undefined}
                            {...focus.bind(row.ticker)}
                          >
                            <td className="ag-rev-who-col">
                              <TickerCell ticker={row.ticker} name={false} />
                              <Ccy row={row} base={base} />
                            </td>
                            <td className="ag-rev-left">
                              <VerdictChip row={row} />
                            </td>
                            <td className="ag-rev-left ag-rev-why">
                              <Reasons reasons={row.reasons} limit={2} />
                            </td>
                            <td>{score(row.quality) ?? na}</td>
                            <td>{score(row.cheapness) ?? na}</td>
                            <td>{percent(row.weight, { lang }) ?? na}</td>
                            {moves ? (
                              <>
                                <td>{percent(row.target_weight, { lang }) ?? "—"}</td>
                                <td
                                  className={`ag-rev-tone-${verdictTone(row.verdict)}`}
                                >
                                  {money(row.delta, {
                                    currency: base,
                                    lang,
                                    signed: true,
                                  }) ?? "—"}
                                </td>
                                <td>
                                  {money(row.tax, { currency: taxCurrency, lang }) ??
                                    "—"}
                                </td>
                              </>
                            ) : null}
                            <td>{sharePrice(row, lang) ?? na}</td>
                            <td>
                              <PnlChip row={row} />
                            </td>
                            <ReturnCells symbol={row.symbol} na={na} />
                            <td className="ag-rev-fold-cell">
                              <DetailsButton
                                row={row}
                                variant="icon"
                                taxCurrency={taxCurrency}
                              />
                            </td>
                          </tr>
                        ))
                      : null}
                  </tbody>
                ))}
              </table>
            </div>
          }
          narrow={
            <div className="ag-dense">
              {groups.map((group) => (
                <Fragment key={group.verdict}>
                  <div className="ag-rev-group ag-rev-group-dense">
                    <GroupToggle
                      verdict={group.verdict}
                      count={group.rows.length}
                      open={isOpen(group.verdict)}
                      onToggle={() => toggle(group.verdict)}
                    />
                  </div>
                  {isOpen(group.verdict)
                    ? group.rows.map((row) => (
                        <div key={row.ticker} className="ag-rev-dense-item">
                          <DenseRow
                            row={row}
                            spec={{
                              ticker: (r) => r.ticker,
                              badge: (r) => <VerdictChip row={r} />,
                              sub: (r) => [
                                percent(r.weight, { lang }),
                                foreign(r, base),
                                returned(r.symbol),
                                reason(r),
                              ],
                              value: (r) =>
                                money(r.delta, { currency: base, lang, signed: true }),
                              delta: (r) =>
                                r.target_weight !== null
                                  ? `→ ${percent(r.target_weight, { lang })}`
                                  : null,
                              wrap: true,
                            }}
                          />
                          <DetailsButton
                            row={row}
                            variant="icon"
                            taxCurrency={taxCurrency}
                          />
                        </div>
                      ))
                    : null}
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
  const base = useCurrency();
  const na = t("review.na");
  const returned = useReturnLine();
  const find = useFind(all);
  const rows = find.rows;
  const focus = useListFocus(
    "outside",
    rows.map((row) => row.ticker),
  );
  return (
    <>
      <div className="ag-rev-tools">
        {find.box}
        <WindowPicker />
      </div>
      {rows.length > 0 && (
        <Responsive
          wide={
            <div className="ag-rev-scroll">
              <table className={`ag-rev-table${focus.fading ? " ag-rev-fading" : ""}`}>
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
                    <ReturnHeads head={head} />
                    <th aria-hidden="true" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.ticker}
                      className={focus.on(row.ticker) ? "ag-rev-on" : undefined}
                      {...focus.bind(row.ticker)}
                    >
                      <td className="ag-rev-who-col">
                        <TickerCell ticker={row.ticker} name={false} />
                        <Ccy row={row} base={base} />
                      </td>
                      <td className="ag-rev-left">
                        <VerdictChip row={row} />
                        {row.buy_after ? (
                          <div className="ag-rev-caption">
                            {t("review.buy_after", {
                              ticker: row.symbol,
                              date: longDay(row.buy_after, lang),
                            })}
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
                      <ReturnCells symbol={row.symbol} na={na} />
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
                <div key={row.ticker} className="ag-rev-dense-item">
                  <DenseRow
                    row={row}
                    spec={{
                      ticker: (r) => r.ticker,
                      badge: (r) => <VerdictChip row={r} />,
                      names: true,
                      sub: (r) => [
                        foreign(r, base),
                        returned(r.symbol),
                        ...r.reasons
                          .slice(0, 2)
                          .map((code) => t(`review.reason_${code}`)),
                      ],
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
                  <DetailsButton row={row} variant="icon" />
                </div>
              ))}
            </div>
          }
        />
      )}
    </>
  );
}
