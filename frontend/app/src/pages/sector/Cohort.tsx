/**
 * The cohort itself: the screen controls, the seventeen-odd rows they produce,
 * and the raw numbers behind both.
 *
 * It comes last on the page on purpose — nobody scans a seventeen-row table
 * top to bottom, so it sits under the podium and the written read rather than
 * above them.
 *
 * Every control here works on rows already in hand. `/sectors/{sector}` sends
 * `metric_keys`, `default_columns` and `lower_is_better` with the rows exactly
 * so the table can redraw itself without asking again, and `lower_is_better`
 * is what decides a new sort's direction: sorted without it, a cheapness
 * ranking opens on the most expensive company in the sector.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { TickerCell, useTickerProfile } from "../../shell/tickers";
import { useLabels } from "./labels";
import { formatMetric, ordered, passes, type Screen } from "./metrics";
import type { CohortRow, SectorCohort } from "./types";
import { DenseRows, Responsive } from "../../ui/Rows";
import { ToggleChip, ToggleRow } from "../../ui/Toggle";

/**
 * The width the Streamlit tables switched at, 40rem, and the one `Responsive`
 * swaps the table for its dense rows on — read off the main column rather
 * than the viewport, so an open chat drawer narrows this page the way a phone
 * does. Read once, for what the page opens with (the columns a phone starts
 * on, whether the controls start folded); the swap itself is CSS.
 */
function narrowAtOpen(): boolean {
  const main = document.querySelector(".ag-main");
  if (!main) return window.innerWidth <= 640;
  // The container query measures the content box; clientWidth has the padding.
  const style = window.getComputedStyle(main);
  const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  return main.clientWidth - padding <= 640;
}

/** The three filters the screen offers, with the thresholds it opens on. */
const SCREENS: { metric: string; kind: "min" | "max"; value: string }[] = [
  { metric: "pe_ttm", kind: "max", value: "40" },
  { metric: "roic", kind: "min", value: "0.15" },
  { metric: "fcf_yield", kind: "min", value: "0.03" },
];

/** How many columns a phone opens with, before anyone adds more. */
const NARROW_COLUMNS = 4;

/**
 * The company's name, dim, beside or under its symbol — what the Streamlit
 * table prints on both layouts (`ticker_cell(name=True)`, `mobile_names`).
 * Read off the same batched `/market/profiles` lookup `TickerCell` fills, so
 * seventeen rows cost one request, and nothing at all until it lands.
 */
export function CompanyName({
  ticker,
  className,
}: {
  ticker: string;
  className?: string;
}) {
  const name = useTickerProfile(ticker)?.name;
  return name ? <span className={className ?? "ag-sec-name"}>{name}</span> : null;
}

/** A catalog string with `**bold**` spans in it, as the Streamlit caption has. */
function Marked({ text }: { text: string }) {
  return (
    <>
      {text
        .split("**")
        .map((chunk, index) =>
          index % 2 ? (
            <strong key={index}>{chunk}</strong>
          ) : (
            <span key={index}>{chunk}</span>
          ),
        )}
    </>
  );
}

export function Cohort({ data }: { data: SectorCohort }) {
  const t = useT();
  const labels = useLabels();
  const na = t("sector.na");

  const [narrow] = useState(narrowAtOpen);
  const [sort, setSort] = useState(data.sort);
  const [ascending, setAscending] = useState(data.ascending);
  const [columns, setColumns] = useState<string[]>(() =>
    narrow ? data.default_columns.slice(0, NARROW_COLUMNS) : data.default_columns,
  );
  // Open on a wide screen, folded away on a phone — where the sidebar this
  // panel replaces starts collapsed anyway. Controlled, with the toggle fed
  // back: every control inside it re-renders this component, and an `open`
  // prop nothing writes to would slam the panel shut on the next keystroke.
  const [open, setOpen] = useState(!narrow);
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [thresholds, setThresholds] = useState<Record<string, string>>(() =>
    Object.fromEntries(SCREENS.map((screen) => [screen.metric, screen.value])),
  );

  /**
   * Picking a metric picks its direction too, so the most attractive row is
   * always the first one. The reader can still invert it; they just never have
   * to, to see the answer they asked for.
   */
  const rankBy = (metric: string) => {
    setSort(metric);
    setAscending(data.lower_is_better.includes(metric));
  };

  /** A column head: a new metric ranks best-first; the ranked one flips. */
  const sortBy = (metric: string) =>
    metric === sort ? setAscending((current) => !current) : rankBy(metric);

  const screens: Screen[] = SCREENS.filter((screen) => on[screen.metric])
    .map((screen) => ({
      metric: screen.metric,
      kind: screen.kind,
      value: threshold(thresholds[screen.metric] ?? ""),
    }))
    .filter((screen) => Number.isFinite(screen.value));

  // Recomputed on every render rather than memoised: a cohort is seventeen
  // rows and a sort of seventeen rows is free, while a memo keyed on a filter
  // list is a stale table waiting to happen.
  const view = ordered(
    data.rows.filter((row) => passes(row, screens)),
    sort,
    ascending,
  );

  // The ranked-by metric is the row's headline number on a phone, picked as a
  // column or not — the rows are in its order, and a headline in any other
  // figure reads as a list sorted by nothing. The rest go in the dim line.
  const sub = columns.filter((column) => column !== sort);

  return (
    <section className="ag-sec-card ag-sec-cohort">
      <h2 className="ag-sec-h2">{t("sector.table_title")}</h2>
      <p className="ag-sec-caption">
        {t("sector.cohort_caption", { n: data.rows.length, etf: data.etf })}
      </p>

      <details
        className="ag-sec-controls"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>{t("sector.screen_filters")}</summary>

        <div className="ag-sec-line">
          <label className="ag-sec-field">
            <span>{t("sector.rank_by")}</span>
            <select value={sort} onChange={(event) => rankBy(event.target.value)}>
              {data.metric_keys.map((key) => (
                <option key={key} value={key}>
                  {labels.metric(key)}
                </option>
              ))}
            </select>
          </label>
          <label className="ag-sec-check">
            <input
              type="checkbox"
              checked={ascending}
              onChange={(event) => setAscending(event.target.checked)}
            />
            <span>{t("sector.ascending")}</span>
          </label>
        </div>
        {labels.describe(sort) ? (
          <p className="ag-sec-caption">{labels.describe(sort)}</p>
        ) : null}

        <p className="ag-sec-label">{t("sector.columns")}</p>
        <ToggleRow label={t("sector.columns")} className="ag-sec-chips">
          {data.metric_keys.map((key) => {
            const picked = columns.includes(key);
            return (
              <ToggleChip
                key={key}
                title={labels.describe(key)}
                on={picked}
                onClick={() =>
                  setColumns((current) =>
                    picked
                      ? current.filter((column) => column !== key)
                      : [...current, key],
                  )
                }
              >
                {labels.metric(key)}
              </ToggleChip>
            );
          })}
        </ToggleRow>

        <p className="ag-sec-label">{t("sector.filters_caption")}</p>
        {/* The threshold stays on screen while its filter is off, so the reader
            sees what ticking it would apply; typing a new one switches it on. */}
        <div className="ag-sec-line">
          {SCREENS.filter((screen) => data.metric_keys.includes(screen.metric)).map(
            (screen) => (
              <div
                className={
                  on[screen.metric] ? "ag-sec-filter ag-sec-filter-on" : "ag-sec-filter"
                }
                key={screen.metric}
              >
                <label className="ag-sec-check" title={labels.describe(screen.metric)}>
                  <input
                    type="checkbox"
                    checked={Boolean(on[screen.metric])}
                    onChange={(event) =>
                      setOn((current) => ({
                        ...current,
                        [screen.metric]: event.target.checked,
                      }))
                    }
                  />
                  <span>
                    {labels.metric(screen.metric)} {screen.kind === "max" ? "≤" : "≥"}
                  </span>
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  aria-label={labels.metric(screen.metric)}
                  value={thresholds[screen.metric] ?? screen.value}
                  onChange={(event) => {
                    const text = event.target.value;
                    setThresholds((current) => ({ ...current, [screen.metric]: text }));
                    setOn((current) => ({ ...current, [screen.metric]: true }));
                  }}
                />
              </div>
            ),
          )}
        </div>
      </details>

      <p className="ag-sec-caption">
        <Marked
          text={t("sector.pass_caption", { n: view.length, total: data.rows.length })}
        />
      </p>

      <Responsive
        wide={
          <Table
            rows={view}
            columns={columns}
            sort={sort}
            ascending={ascending}
            onSort={sortBy}
            na={na}
          />
        }
        narrow={
          <DenseRows
            rows={view}
            rowKey={(row) => row.ticker}
            spec={{
              ticker: (row) => row.ticker,
              names: true,
              wrap: true,
              sub: (row) =>
                sub.map(
                  (column) =>
                    `${labels.metric(column)} ${formatMetric(column, row.metrics[column], na)}`,
                ),
              value: (row) => formatMetric(sort, row.metrics[sort], na),
              // What the headline figure is, under it: a bare "72.6%" on the
              // right of seventeen rows says nothing about which metric it is.
              delta: () => labels.metric(sort),
            }}
          />
        }
      />

      <details className="ag-sec-help">
        <summary>{t("sector.metrics_help")}</summary>
        <dl>
          {data.metric_keys
            .filter((key) => labels.describe(key))
            .map((key) => (
              <div key={key}>
                <dt>{labels.metric(key)}</dt>
                <dd>{labels.describe(key)}</dd>
              </div>
            ))}
        </dl>
      </details>
    </section>
  );
}

/**
 * The wide rendering: one column per metric, one row per company.
 *
 * Every head is a button that ranks by its column — the same `sort` the "Rank
 * by" select writes, so the two can never disagree — and the ranked column is
 * marked in its head (`aria-sort` and the arrow) and set in weight down the
 * rows, so the eye finds the order it is reading. Figures sit right-aligned in
 * tabular digits so their decimals stack; the symbol column stays put while
 * the rest scroll under it on a column too narrow for all of them.
 */
function Table({
  rows,
  columns,
  sort,
  ascending,
  onSort,
  na,
}: {
  rows: CohortRow[];
  columns: string[];
  sort: string;
  ascending: boolean;
  onSort: (metric: string) => void;
  na: string;
}) {
  const t = useT();
  const labels = useLabels();
  return (
    <div className="ag-sec-scroll">
      <table className="ag-sec-table">
        <thead>
          <tr>
            <th scope="col" className="ag-sec-who-col">
              {t("sector.col_ticker")}
            </th>
            {columns.map((column) => {
              const ranked = column === sort;
              return (
                <th
                  key={column}
                  scope="col"
                  className={ranked ? "ag-sec-ranked" : undefined}
                  aria-sort={
                    ranked ? (ascending ? "ascending" : "descending") : undefined
                  }
                >
                  <button
                    type="button"
                    className="ag-sec-head"
                    title={labels.describe(column) || undefined}
                    onClick={() => onSort(column)}
                  >
                    {labels.metric(column)}
                    <span className="ag-sec-arrow" aria-hidden="true">
                      {ranked ? (ascending ? "▴" : "▾") : ""}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.ticker}>
              <th scope="row" className="ag-sec-who-col">
                <span className="ag-sec-who">
                  <TickerCell ticker={row.ticker}>
                    <b>{row.ticker}</b>
                  </TickerCell>
                  <CompanyName ticker={row.ticker} />
                </span>
              </th>
              {columns.map((column) => (
                <td
                  key={column}
                  className={column === sort ? "ag-sec-ranked" : undefined}
                >
                  {formatMetric(column, row.metrics[column], na)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A threshold as typed: "0,15" from a Spanish keyboard as well as "0.15". A
 * number input would swallow the comma into an empty value, and an empty
 * value is a filter that silently stops filtering.
 */
function threshold(text: string): number {
  const raw = text.trim().replace(",", ".");
  return raw === "" ? Number.NaN : Number(raw);
}
