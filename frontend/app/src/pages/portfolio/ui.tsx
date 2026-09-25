/**
 * The handful of shapes every tab on this page is built from.
 *
 * The Streamlit original draws bordered containers, TIKR-style KPI tiles with
 * a "?" pill, and one HTML table helper shared by five tables. These are the
 * same four things, and they exist here for the same reason: five tabs written
 * five ways drift, and this page is the one where a number formatted loosely
 * turns into a tax figure somebody files.
 */

import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link } from "../../shell/router";
import { useT } from "../../shell/i18n";
import { tone } from "./format";
import { TickerCell as Cell } from "../../shell/tickers";

/**
 * The two emphases the catalogs use, which Streamlit got for free.
 *
 * A few strings were written for a Markdown renderer — `**{region}**` in the
 * unmodelled-jurisdiction warning, `*savings base*` in the Spanish tax caption
 * — and printed raw they would show their asterisks. Editing the catalogs to
 * suit this front end would break the Streamlit one, so they are parsed here.
 */
function Markup({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return (
    <>
      {parts.map((part, index) => {
        if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
          return <strong key={index}>{part.slice(2, -2)}</strong>;
        }
        if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) {
          return <em key={index}>{part.slice(1, -1)}</em>;
        }
        return <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}

/** A translated sentence handed straight to a block: emphasis included. */
const said = (children: ReactNode) =>
  typeof children === "string" ? <Markup text={children} /> : children;

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="pf-card">
      {title ? <h2>{title}</h2> : null}
      {children}
    </section>
  );
}

export function Caption({ children }: { children: ReactNode }) {
  return <p className="pf-caption">{said(children)}</p>;
}

export function Warn({ children }: { children: ReactNode }) {
  return <p className="pf-warn">{said(children)}</p>;
}

export function Info({ children }: { children: ReactNode }) {
  return <p className="pf-info">{said(children)}</p>;
}

/** A ticker is always a way into its own page — never a bare string. */
export function TickerCell({ ticker }: { ticker: string }) {
  return <Cell ticker={ticker} className="pf-ticker" />;
}

function Chip({
  value,
  text,
  off,
}: {
  value: number | null | undefined;
  text: string;
  off?: boolean;
}) {
  // `off` greys a figure that is real but not live — the day change while
  // nothing is trading — without hiding it or dropping its sign.
  return (
    <span className={`pf-chip pf-chip-${off ? "flat" : tone(value)}`}>{text}</span>
  );
}

/** A figure that could not be computed reads "n/a" — never 0, never a dash
 *  dressed up as a number. */
export function Figure({ value }: { value: string | null }) {
  const t = useT();
  if (value === null) return <span className="pf-muted">{t("portfolio.na")}</span>;
  return <>{value}</>;
}

/** A signed money or percentage cell, coloured by its own sign. */
export function Signed({ value, text }: { value: number | null; text: string | null }) {
  const t = useT();
  if (text === null) return <span className="pf-muted">{t("portfolio.na")}</span>;
  const which = tone(value);
  return <span className={which === "flat" ? undefined : `pf-${which}`}>{text}</span>;
}

export type KpiItem = {
  label: string;
  /** Already formatted, or null when the figure could not be computed. */
  value: string | null;
  help?: string;
  chip?: { text: string; value: number | null; off?: boolean } | null;
};

export function Kpis({ items }: { items: KpiItem[] }) {
  const t = useT();
  return (
    // The count drives the wrap (portfolio.css): four tiles go 2+2, never 3+1.
    <div className="pf-kpis" data-n={items.length}>
      {items.map((item) => (
        <div className="pf-kpi" key={item.label}>
          <div className="pf-kpi-label">
            <span>{item.label}</span>
            {item.help ? (
              <span className="pf-help" title={item.help} aria-label={item.help}>
                ?
              </span>
            ) : null}
          </div>
          <div className="pf-kpi-line">
            <span className="pf-kpi-value">
              {item.value === null ? t("portfolio.na") : item.value}
            </span>
            {item.chip ? (
              <Chip value={item.chip.value} text={item.chip.text} off={item.chip.off} />
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

export type Column<T> = {
  key: string;
  label: string;
  /** Text columns read left, figures read right. */
  left?: boolean;
  /** Omit to make the column unsortable. `null` always sorts last. */
  sort?: (row: T) => number | string | null;
  cell: (row: T) => ReactNode;
  /**
   * Extra class on the column's header and cells — `pf-wide-only` drops a
   * column on a phone whose content already rides another cell there.
   */
  className?: string;
};

/**
 * One sortable table for all five tabs.
 *
 * `null` sorts last in both directions on purpose: an unpriced position or an
 * unmeasured spread is not the smallest value, it is the absence of one, and
 * floating it to the top of an ascending sort would read as "cheapest".
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  initial,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  initial?: { key: string; desc?: boolean };
}) {
  const [sort, setSort] = useState(initial ?? null);

  const ordered = useMemo(() => {
    const column = columns.find((c) => c.key === sort?.key);
    if (!column?.sort) return rows;
    const read = column.sort;
    const sign = sort?.desc ? -1 : 1;
    return [...rows].sort((a, b) => {
      const left = read(a);
      const right = read(b);
      if (left === null && right === null) return 0;
      if (left === null) return 1;
      if (right === null) return -1;
      if (typeof left === "string" || typeof right === "string") {
        return sign * String(left).localeCompare(String(right));
      }
      return sign * (left - right);
    });
  }, [columns, rows, sort]);

  const toggle = (key: string) =>
    setSort((current) =>
      current?.key === key ? { key, desc: !current.desc } : { key, desc: true },
    );

  return (
    <div className="pf-scroll">
      <table className="pf-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={[
                  column.left ? "pf-left" : "",
                  column.sort ? "pf-sortable" : "",
                  column.className ?? "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={column.sort ? () => toggle(column.key) : undefined}
                aria-sort={
                  sort?.key === column.key
                    ? sort.desc
                      ? "descending"
                      : "ascending"
                    : undefined
                }
              >
                {column.label}
                {sort?.key === column.key ? (
                  <span className="pf-sort-mark">{sort.desc ? "▾" : "▴"}</span>
                ) : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ordered.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={
                    [column.left ? "pf-left" : "", column.className ?? ""]
                      .filter(Boolean)
                      .join(" ") || undefined
                  }
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  format,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  format?: (option: T) => string;
}) {
  return (
    <div className="pf-controls">
      <span className="pf-control-label">{label}</span>
      <div className="pf-seg" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={option}
            type="button"
            className={option === value ? "pf-seg-on" : undefined}
            aria-pressed={option === value}
            onClick={() => onChange(option)}
          >
            {format ? format(option) : option}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The same choice as a dropdown, for when there are too many of them to sit in
 * a row — the Streamlit page switches at four fiscal years for the same reason.
 */
export function Dropdown<T extends string>({
  label,
  options,
  value,
  onChange,
  format,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  format?: (option: T) => string;
}) {
  return (
    <div className="pf-controls">
      <span className="pf-control-label">{label}</span>
      <select
        className="pf-select"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {format ? format(option) : option}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Nothing to show, and what to do about it.
 *
 * Every empty state on the Streamlit page says why the tab is blank and, where
 * there is one, points at the single action that fills it — almost always the
 * Import page, because everything here derives from the ledger.
 */
export function Empty({
  title,
  body,
  cta,
}: {
  title: string;
  body: string;
  cta?: { label: string; page: string };
}) {
  return (
    <div className="pf-empty">
      <h2>{title}</h2>
      <p>{body}</p>
      {cta ? (
        <Link className="ag-btn" page={cta.page}>
          {cta.label}
        </Link>
      ) : null}
    </div>
  );
}
