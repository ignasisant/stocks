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

import { type CSSProperties, useState } from "react";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useDebounced } from "../../shell/useDebounced";
import { TickerCell, useTickerProfile } from "../../shell/tickers";
import { DenseRow, type DenseSpec, Responsive } from "../../ui/Rows";
import { ToggleChip, ToggleRow } from "../../ui/Toggle";
import { MAX_ADDED, SYMBOL } from "../review/format";
import { useLabels } from "./labels";
import { formatMetric, ordered, passes, type Screen, tinted } from "./metrics";
import { percentiles, tint } from "./rank";
import type { CohortRow, SectorCohort } from "./types";

/**
 * The width the table goes dense at, 40rem, and the one `Responsive` swaps the
 * table for its dense rows on — read off the main column rather than the
 * viewport, so an open chat drawer narrows this page the way a phone does.
 * Read once, for what the page opens with (the columns a phone starts on,
 * whether the controls start folded); the swap itself is `Responsive`.
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
 * The company's name, dim, beside or under its symbol, on both layouts.
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

/** A catalog string with `**bold**` spans in it. */
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

export function Cohort({
  data,
  held,
}: {
  data: SectorCohort;
  /** What the reader already owns, upper-cased: the cohort is the same for
   * every reader, and this is joined on top of it (see routes/sector.py). */
  held: ReadonlySet<string>;
}) {
  const t = useT();
  const labels = useLabels();
  const na = t("sector.na");

  const [narrow] = useState(narrowAtOpen);
  const [sort, setSort] = useState(data.sort);
  const [ascending, setAscending] = useState(data.ascending);
  const [columns, setColumns] = useState<string[]>(() =>
    narrow ? data.default_columns.slice(0, NARROW_COLUMNS) : data.default_columns,
  );
  // Folded on every width: the screens are one tap away as chips above the
  // table, and the rest (order, columns, thresholds) is a settings menu, not
  // the first thing under the heading. Controlled, with the toggle fed back:
  // every control inside it re-renders this component, and an `open` prop
  // nothing writes to would slam the menu shut on the next keystroke.
  const [open, setOpen] = useState(false);
  // Rows picked to carry to Sell or add, in the order they were picked.
  const [picked, setPicked] = useState<string[]>([]);
  const [on, setOn] = useState<Record<string, boolean>>({});
  // The column last toggled: its definition reads under the chips, because a
  // chip's `title` is a hover hint and a phone has no hover.
  const [lastMetric, setLastMetric] = useState<string | null>(null);
  const [thresholds, setThresholds] = useState<Record<string, string>>(() =>
    Object.fromEntries(SCREENS.map((screen) => [screen.metric, screen.value])),
  );
  // The table follows a threshold once the typing stops: "0." or "-" on the
  // way to "0.2" or "-5" is not a filter, and rows blinking out and back on
  // each keystroke read as the cohort changing.
  const settled = useDebounced(thresholds);

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

  const offered = SCREENS.filter((screen) => data.metric_keys.includes(screen.metric));
  const screens: Screen[] = offered
    .filter((screen) => on[screen.metric])
    .map((screen) => ({
      metric: screen.metric,
      kind: screen.kind,
      value: threshold(settled[screen.metric] ?? ""),
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

  // Each figure's standing in the whole cohort, not in the rows a screen
  // left: switching a screen on must not recolour the figures that stay.
  // The ranked-by metric too, column or not: a phone row's headline is it.
  const standing = new Map(
    [...new Set([...columns, sort])]
      .filter(tinted)
      .map((column) => [
        column,
        percentiles(data.rows, column, data.lower_is_better.includes(column)),
      ]),
  );
  const shade = (column: string, ticker: string) =>
    tint(standing.get(column)?.get(ticker));

  const choosable = (ticker: string) => SYMBOL.test(ticker.toUpperCase());
  const full = picked.length >= MAX_ADDED;
  const toggle = (ticker: string) =>
    setPicked((current) =>
      current.includes(ticker)
        ? current.filter((one) => one !== ticker)
        : current.length >= MAX_ADDED
          ? current
          : [...current, ticker],
    );
  const pick: Picking = { picked, full, choosable, toggle };

  return (
    <section className="ag-sec-card ag-sec-cohort">
      <h2 className="ag-sec-h2">{t("sector.table_title")}</h2>
      <p className="ag-sec-caption">
        {t("sector.cohort_caption", { n: data.rows.length, etf: data.etf })}
      </p>

      {/* The ready screens, one tap each; the threshold is in the chip, so
          what it applies is read before it is applied. */}
      <ToggleRow label={t("sector.screen")} className="ag-sec-chips ag-sec-screens">
        {offered.map((screen) => {
          const value = threshold(thresholds[screen.metric] ?? "");
          return (
            <ToggleChip
              key={screen.metric}
              title={labels.describe(screen.metric)}
              on={Boolean(on[screen.metric])}
              onClick={() =>
                setOn((current) => ({
                  ...current,
                  [screen.metric]: !current[screen.metric],
                }))
              }
            >
              {`${labels.metric(screen.metric)} ${screen.kind === "max" ? "≤" : "≥"} ${formatMetric(screen.metric, Number.isFinite(value) ? value : null, "…")}`}
            </ToggleChip>
          );
        })}
      </ToggleRow>

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
            const shown = columns.includes(key);
            return (
              <ToggleChip
                key={key}
                title={labels.describe(key)}
                on={shown}
                onClick={() => {
                  setLastMetric(key);
                  setColumns((current) =>
                    shown
                      ? current.filter((column) => column !== key)
                      : [...current, key],
                  );
                }}
              >
                {labels.metric(key)}
              </ToggleChip>
            );
          })}
        </ToggleRow>
        {lastMetric && labels.describe(lastMetric) ? (
          <p className="ag-sec-caption" aria-live="polite">
            <strong>{labels.metric(lastMetric)}</strong> — {labels.describe(lastMetric)}
          </p>
        ) : null}

        <p className="ag-sec-label">{t("sector.filters_caption")}</p>
        {/* Typing a threshold switches its screen on. */}
        <div className="ag-sec-line">
          {offered.map((screen) => (
            <label
              className={
                on[screen.metric] ? "ag-sec-filter ag-sec-filter-on" : "ag-sec-filter"
              }
              key={screen.metric}
              title={labels.describe(screen.metric)}
            >
              <span>
                {labels.metric(screen.metric)} {screen.kind === "max" ? "≤" : "≥"}
              </span>
              <input
                type="text"
                inputMode="decimal"
                value={thresholds[screen.metric] ?? screen.value}
                onChange={(event) => {
                  const text = event.target.value;
                  setThresholds((current) => ({ ...current, [screen.metric]: text }));
                  setOn((current) => ({ ...current, [screen.metric]: true }));
                }}
              />
            </label>
          ))}
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
            held={held}
            shade={shade}
            pick={pick}
          />
        }
        narrow={
          <PickRows
            rows={view}
            pick={pick}
            spec={{
              ticker: (row) => row.ticker,
              names: true,
              wrap: true,
              badge: (row) =>
                held.has(row.ticker.toUpperCase()) ? (
                  <span className="ag-sec-held">{t("sector.held_badge")}</span>
                ) : null,
              sub: (row) =>
                sub.map(
                  (column) =>
                    `${labels.metric(column)} ${formatMetric(column, row.metrics[column], na, row.currency)}`,
                ),
              // Shaded by its standing as the wide table shades its cell.
              value: (row) => {
                const color = shade(sort, row.ticker);
                const text = formatMetric(sort, row.metrics[sort], na, row.currency);
                return color ? (
                  <span className="ag-sec-heat" style={tintStyle(color)}>
                    {text}
                  </span>
                ) : (
                  text
                );
              },
              // What the headline figure is, under it: a bare "72.6%" on the
              // right of seventeen rows says nothing about which metric it is.
              delta: () => labels.metric(sort),
            }}
          />
        }
      />

      {/* The rows ticked, carried to Sell or add in one tap. Under the table
          so it can stick to the foot of the screen while the rows scroll
          (a bar above them would leave through the top); always mounted, so
          the count is announced as it changes. */}
      <div className="ag-sec-picked" aria-live="polite">
        {picked.length ? (
          <>
            <span>
              {full
                ? t("sector.picked_full", { n: picked.length, max: MAX_ADDED })
                : t("sector.picked", { n: picked.length })}
            </span>
            <Link
              page="review"
              params={{ add: picked.map((one) => one.toUpperCase()).join(",") }}
              className="ag-btn ag-sec-picked-go"
            >
              {t("sector.picked_to_review")}
            </Link>
            <button
              type="button"
              className="ag-sec-picked-clear"
              onClick={() => setPicked([])}
            >
              {t("sector.picked_clear")}
            </button>
          </>
        ) : (
          <span className="ag-sec-caption">{t("sector.picked_hint")}</span>
        )}
      </div>

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
  held,
  shade,
  pick,
}: {
  rows: CohortRow[];
  columns: string[];
  sort: string;
  ascending: boolean;
  onSort: (metric: string) => void;
  na: string;
  held: ReadonlySet<string>;
  /** A figure's background for its standing in the cohort, if it has one. */
  shade: (column: string, ticker: string) => string | undefined;
  pick: Picking;
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
                  <PickBox ticker={row.ticker} pick={pick} />
                  <TickerCell ticker={row.ticker}>
                    <b>{row.ticker}</b>
                  </TickerCell>
                  <CompanyName ticker={row.ticker} />
                  {held.has(row.ticker.toUpperCase()) ? (
                    <span className="ag-sec-held">{t("sector.held_badge")}</span>
                  ) : null}
                </span>
              </th>
              {columns.map((column) => (
                <td
                  key={column}
                  className={column === sort ? "ag-sec-ranked" : undefined}
                  style={tintStyle(shade(column, row.ticker))}
                >
                  {formatMetric(column, row.metrics[column], na, row.currency)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The rows ticked to carry to Sell or add, and how to tick one. */
type Picking = {
  picked: string[];
  /** At `MAX_ADDED`: the boxes not ticked are disabled rather than ignored. */
  full: boolean;
  choosable: (ticker: string) => boolean;
  toggle: (ticker: string) => void;
};

/** One row's tick box, its label the 44px target on a touch screen. */
function PickBox({ ticker, pick }: { ticker: string; pick: Picking }) {
  const t = useT();
  if (!pick.choosable(ticker)) return null;
  const on = pick.picked.includes(ticker);
  return (
    <label className="ag-sec-tick">
      <input
        type="checkbox"
        checked={on}
        disabled={!on && pick.full}
        onChange={() => pick.toggle(ticker)}
        aria-label={t("sector.pick_row", { ticker })}
      />
    </label>
  );
}

/**
 * The phone rendering: the shell's dense rows, each with its tick box beside
 * it rather than inside it — a dense row is a link, and a box inside a link
 * is a tap that both ticks and navigates.
 */
function PickRows({
  rows,
  pick,
  spec,
}: {
  rows: CohortRow[];
  pick: Picking;
  spec: DenseSpec<CohortRow>;
}) {
  return (
    <div className="ag-dense ag-sec-dense">
      {rows.map((row) => (
        <div key={row.ticker} className="ag-sec-dense-row">
          <PickBox ticker={row.ticker} pick={pick} />
          <DenseRow row={row} spec={spec} />
        </div>
      ))}
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

/** The cell's tint as a custom property the stylesheet paints as a layer. */
function tintStyle(color: string | undefined): CSSProperties | undefined {
  return color ? ({ "--sec-tint": color } as CSSProperties) : undefined;
}
