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

import { useEffect, useState } from "react";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useLabels } from "./labels";
import { csv, formatMetric, ordered, passes, type Screen } from "./metrics";
import type { CohortRow, SectorCohort } from "./types";

/**
 * The same breakpoint the Streamlit tables switch on, and for the same reason:
 * a narrow desktop window and an iPad (which sends no "Mobi") both need the
 * dense rows, so this is viewport WIDTH and never the User-Agent.
 */
const NARROW = "(max-width: 640px)";

/** The three filters the screen offers, with the thresholds it opens on. */
const SCREENS: { metric: string; kind: "min" | "max"; value: string }[] = [
  { metric: "pe_ttm", kind: "max", value: "40" },
  { metric: "roic", kind: "min", value: "0.15" },
  { metric: "fcf_yield", kind: "min", value: "0.03" },
];

/** How many columns a phone opens with, before anyone adds more. */
const NARROW_COLUMNS = 4;

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches);
  useEffect(() => {
    const query = window.matchMedia(NARROW);
    const update = () => setNarrow(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return narrow;
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
  const narrow = useNarrow();
  const na = t("sector.na");

  const [sort, setSort] = useState(data.sort);
  const [ascending, setAscending] = useState(data.ascending);
  const [columns, setColumns] = useState<string[]>(() =>
    window.matchMedia(NARROW).matches
      ? data.default_columns.slice(0, NARROW_COLUMNS)
      : data.default_columns,
  );
  // Open on a wide screen, folded away on a phone — where the sidebar this
  // panel replaces starts collapsed anyway. Controlled, with the toggle fed
  // back: every control inside it re-renders this component, and an `open`
  // prop nothing writes to would slam the panel shut on the next keystroke.
  const [open, setOpen] = useState(() => !window.matchMedia(NARROW).matches);
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

  const screens: Screen[] = SCREENS.filter((screen) => on[screen.metric])
    .map((screen) => ({
      metric: screen.metric,
      kind: screen.kind,
      value: Number(thresholds[screen.metric]),
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

  // The ranked-by metric is the row's headline number on a phone; the rest go
  // in the dim line under the symbol.
  const lead = columns.includes(sort) ? sort : (columns[0] ?? "");
  const sub = columns.filter((column) => column !== lead);

  const download = () => {
    const blob = new Blob([csv(data.rows, data.metric_keys)], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${data.sector.toLowerCase().replaceAll(" ", "_")}.csv`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <section className="ag-sec-cohort">
      <h2 className="ag-sec-h2">{t("sector.table_title")}</h2>
      <p className="ag-sec-caption">
        {t("sector.cohort_caption", { n: data.rows.length, etf: data.etf })}
      </p>

      <details
        className="ag-sec-controls"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>{narrow ? t("sector.screen_filters") : t("sector.screen")}</summary>

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
        {labels.describe(sort) ? (
          <p className="ag-sec-caption">{labels.describe(sort)}</p>
        ) : null}

        <label className="ag-sec-check">
          <input
            type="checkbox"
            checked={ascending}
            onChange={(event) => setAscending(event.target.checked)}
          />
          <span>{t("sector.ascending")}</span>
        </label>

        <p className="ag-sec-label">{t("sector.columns")}</p>
        <div className="ag-sec-chips">
          {data.metric_keys.map((key) => {
            const picked = columns.includes(key);
            return (
              <button
                type="button"
                key={key}
                title={labels.describe(key)}
                aria-pressed={picked}
                className={picked ? "ag-sec-chip ag-sec-chip-on" : "ag-sec-chip"}
                onClick={() =>
                  setColumns((current) =>
                    picked
                      ? current.filter((column) => column !== key)
                      : [...current, key],
                  )
                }
              >
                {labels.metric(key)}
              </button>
            );
          })}
        </div>

        <hr className="ag-sec-rule" />
        <p className="ag-sec-caption">{t("sector.filters_caption")}</p>
        {SCREENS.filter((screen) => data.metric_keys.includes(screen.metric)).map(
          (screen) => (
            <div className="ag-sec-filter" key={screen.metric}>
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
              {on[screen.metric] ? (
                <input
                  type="number"
                  step="any"
                  aria-label={labels.metric(screen.metric)}
                  value={thresholds[screen.metric] ?? screen.value}
                  onChange={(event) =>
                    setThresholds((current) => ({
                      ...current,
                      [screen.metric]: event.target.value,
                    }))
                  }
                />
              ) : null}
            </div>
          ),
        )}
      </details>

      <p className="ag-sec-caption">
        <Marked
          text={t("sector.pass_caption", { n: view.length, total: data.rows.length })}
        />
      </p>

      <Table rows={view} columns={columns} na={na} />
      <Dense rows={view} lead={lead} sub={sub} na={na} />

      <button type="button" className="ag-btn ag-sec-download" onClick={download}>
        {t("sector.download_csv")}
      </button>

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

/** The wide rendering: one column per metric, one row per company. */
function Table({
  rows,
  columns,
  na,
}: {
  rows: CohortRow[];
  columns: string[];
  na: string;
}) {
  const t = useT();
  const labels = useLabels();
  return (
    <div className="ag-sec-desk">
      <table className="ag-sec-table">
        <thead>
          <tr>
            <th>{t("sector.col_ticker")}</th>
            {columns.map((column) => (
              <th key={column} title={labels.describe(column)}>
                {labels.metric(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.ticker}>
              <td>
                <Link page="ticker" params={{ ticker: row.ticker }}>
                  <b>{row.ticker}</b>
                </Link>
              </td>
              {columns.map((column) => (
                <td key={column}>{formatMetric(column, row.metrics[column], na)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The narrow rendering: one dense two-line row per company, so nothing pans
 * horizontally. The ranked-by figure carries the row; the other picked columns
 * ride the dim line under the symbol.
 */
function Dense({
  rows,
  lead,
  sub,
  na,
}: {
  rows: CohortRow[];
  lead: string;
  sub: string[];
  na: string;
}) {
  const labels = useLabels();
  return (
    <div className="ag-sec-mob">
      {rows.map((row) => (
        <Link
          className="ag-sec-row"
          key={row.ticker}
          page="ticker"
          params={{ ticker: row.ticker }}
        >
          <div className="ag-sec-main">
            <div className="ag-sec-l1">{row.ticker}</div>
            {sub.length ? (
              <div className="ag-sec-l2">
                {sub
                  .map(
                    (column) =>
                      `${labels.metric(column)} ${formatMetric(column, row.metrics[column], na)}`,
                  )
                  .join(" · ")}
              </div>
            ) : null}
          </div>
          {lead ? (
            <div className="ag-sec-side">
              <div className="ag-sec-l1">
                {formatMetric(lead, row.metrics[lead], na)}
              </div>
            </div>
          ) : null}
        </Link>
      ))}
    </div>
  );
}
