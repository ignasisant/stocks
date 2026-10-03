/**
 * The handful of shapes every tab on this page is built from.
 *
 * Bordered cards, TIKR-style KPI tiles with a "?" pill, and one table shared
 * by five tables. They exist because five tabs written five ways drift, and
 * this page is the one where a number formatted loosely turns into a tax
 * figure somebody files.
 */

import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link } from "../../shell/router";
import { useT } from "../../shell/i18n";
import { tone } from "./format";
import { Chip as Pill, Help, Kpi, KpiGrid, toneOf } from "../../ui/Kpi";
import { TickerCell as Cell } from "../../shell/tickers";
import { DenseRows, Responsive, StackCards, type DenseSpec } from "../../ui/Rows";

/**
 * The two emphases the catalogs use.
 *
 * A few strings were written for a Markdown renderer — `**{region}**` in the
 * unmodelled-jurisdiction warning, `*savings base*` in the Spanish tax caption
 * — and printed raw they would show their asterisks, so they are parsed here.
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

/** A signed figure as the app's pill, coloured by its own sign. */
export function Chip({
  value,
  text,
  off,
}: {
  value: number | null | undefined;
  /** Null draws nothing — a figure that could not be formatted has no pill. */
  text: string | null;
  off?: boolean;
}) {
  if (text === null) return null;
  // `off` greys a figure that is real but not live — the day change while
  // nothing is trading — without hiding it or dropping its sign.
  return <Pill chip={{ text, tone: off ? "flat" : toneOf(value) }} />;
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
    <KpiGrid>
      {items.map((item) => (
        <Kpi
          key={item.label}
          label={item.label}
          help={item.help}
          value={item.value === null ? t("portfolio.na") : item.value}
          chip={
            item.chip
              ? {
                  text: item.chip.text,
                  tone: item.chip.off ? "flat" : toneOf(item.chip.value),
                }
              : null
          }
        />
      ))}
    </KpiGrid>
  );
}

/**
 * The tab's one figure, and the few that explain it.
 *
 * A row of equal tiles says every number matters the same, and on a tab that
 * exists to answer one question that is never true. The focus is drawn at the
 * ticker hero's step; the facts beside it are one tier down, label over value,
 * with a muted note for the estimate or the share that qualifies each.
 */
export function Hero({
  eyebrow,
  value,
  sub,
  facts,
}: {
  eyebrow: string;
  /** Already formatted, or null when the figure could not be computed. */
  value: string | null;
  sub?: ReactNode;
  facts: FactItem[];
}) {
  const t = useT();
  return (
    <div className="pf-hero">
      <div className="pf-hero-focus">
        <span className="pf-hero-eyebrow">{eyebrow}</span>
        <span className="pf-hero-figure">{value ?? t("portfolio.na")}</span>
        {sub ? <span className="pf-hero-sub">{sub}</span> : null}
      </div>
      <dl className="pf-hero-facts">
        {facts.map((fact) => (
          <div key={fact.label} className="pf-hero-fact">
            <dt>
              <span>{fact.label}</span>
              <Help text={fact.help} />
            </dt>
            <dd>
              <span className="pf-hero-fact-value">
                {fact.value === null ? (
                  <span className="pf-muted">{t("portfolio.na")}</span>
                ) : (
                  fact.value
                )}
              </span>
              {fact.note ? (
                <span className="pf-hero-fact-note">{fact.note}</span>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export type FactItem = {
  label: string;
  /** Formatted text or a coloured figure; null reads "n/a". */
  value: ReactNode | null;
  note?: string | null;
  help?: string;
};

/**
 * A figure's share of its column, drawn beside it.
 *
 * `share` is 0–1 of the largest magnitude in the column, so the longest bar is
 * the biggest row and the eye finds concentration without reading digits.
 * `signed` centres the track on zero for a figure that can go either way — a
 * cost that beat the mid runs left, in the gain colour. Decorative: the figure
 * beside it carries the number, so the bar is hidden from assistive tech.
 */
export function ShareBar({
  share,
  signed,
  children,
}: {
  share: number | null;
  signed?: boolean;
  children: ReactNode;
}) {
  const size =
    share === null || !Number.isFinite(share) ? 0 : Math.min(Math.abs(share), 1);
  const side = signed && share !== null && share < 0 ? "pf-bar-neg" : "pf-bar-pos";
  return (
    <span className="pf-barcell">
      <span className={signed ? "pf-bar pf-bar-signed" : "pf-bar"} aria-hidden="true">
        <span
          className={`pf-bar-fill ${side}`}
          style={{ inlineSize: `${(signed ? size * 50 : size * 100).toFixed(1)}%` }}
        />
      </span>
      <span className="pf-barcell-figure">{children}</span>
    </span>
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
  dense,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  initial?: { key: string; desc?: boolean };
  /**
   * The phone's dense ticker row. Without one the phone gets a card per row,
   * headed by the first column, one line per other column.
   */
  dense?: DenseSpec<T>;
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

  const [head, ...rest] = columns;
  const narrow = dense ? (
    <DenseRows rows={ordered} rowKey={rowKey} spec={dense} />
  ) : (
    <StackCards
      rows={ordered}
      rowKey={rowKey}
      title={head?.cell}
      lines={rest.map((column) => ({ label: column.label, cell: column.cell }))}
    />
  );

  const wide = (
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
                <td key={column.key} className={column.left ? "pf-left" : undefined}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return <Responsive wide={wide} narrow={narrow} />;
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
 * a row.
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
        className="pf-dropdown"
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
 * Every empty state says why the tab is blank and, where there is one, points
 * at the single action that fills it — almost always the Import page, because
 * everything here derives from the ledger.
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
