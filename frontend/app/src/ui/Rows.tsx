/**
 * The phone rendering of a table, in two shapes.
 *
 * A grid of six figures on a 390px screen either pans sideways or squeezes
 * every column to three characters, so below the main column's narrow width a
 * table is drawn again as one of these:
 *
 *   - `DenseRows`, for a list of tickers: one two-line row per name,
 *     Revolut-style, the whole row a link to the ticker's page.
 *
 *       [logo]  TICKER  (+54%)             €6,345
 *               Company · 9%                +1.2%
 *
 *   - `StackCards`, for everything else: one small card per row, one
 *     "label — value" line per column.
 *
 * `Responsive` ships both renderings and a container query on `ag-main` picks
 * one by the room the page actually has — so the chat drawer opening on a
 * laptop narrows a table the same way a phone does, with no resize listener.
 */

import type { ReactNode } from "react";
import { Link } from "../shell/router";
import { useTickerProfile } from "../shell/tickers";
import "./ui.css";

/** Both renderings of one table; the width of `ag-main` decides which shows. */
export function Responsive({ wide, narrow }: { wide: ReactNode; narrow: ReactNode }) {
  return (
    <>
      <div className="ag-resp-wide">{wide}</div>
      <div className="ag-resp-narrow">{narrow}</div>
    </>
  );
}

/** Where a table's columns land on a dense row. Every slot but `ticker` is optional. */
export type DenseSpec<T> = {
  ticker: (row: T) => string;
  /** A pill beside the symbol: a percentage there always reads in full. */
  badge?: (row: T) => ReactNode;
  /** The dim line under the symbol, joined with " · "; empty items drop out. */
  sub?: (row: T) => ReactNode[];
  /** The right-hand headline figure. */
  value?: (row: T) => ReactNode;
  /** The right-hand second line, under `value`. */
  delta?: (row: T) => ReactNode;
  /** Put the company's name first on the dim line. */
  names?: boolean;
  /** Let the dim line wrap instead of ellipsizing — for rows with a lot to say. */
  wrap?: boolean;
};

const present = (node: ReactNode) =>
  node !== null && node !== undefined && node !== false && node !== "";

/** One row of `DenseRows`, for a list that slots rows of its own between them. */
export function DenseRow<T>({ row, spec }: { row: T; spec: DenseSpec<T> }) {
  const ticker = spec.ticker(row);
  const profile = useTickerProfile(ticker);
  const symbol = profile?.symbol || ticker;
  const company = profile?.name || "";
  const sub = [
    spec.names && company && company.toUpperCase() !== symbol.toUpperCase()
      ? company
      : null,
    ...(spec.sub?.(row) ?? []),
  ].filter(present);
  const badge = spec.badge?.(row);
  const value = spec.value?.(row);
  const delta = spec.delta?.(row);
  return (
    <Link
      className="ag-dense-row"
      page="ticker"
      params={{ ticker }}
      title={company || undefined}
    >
      {profile?.logo ? (
        <img className="ag-dense-logo" src={profile.logo} alt="" loading="lazy" />
      ) : (
        <span className="ag-dense-logo ag-dense-logo-none" />
      )}
      <div className="ag-dense-main">
        <div className="ag-dense-l1">
          <span className="ag-dense-sym">{symbol}</span>
          {present(badge) ? badge : null}
        </div>
        {sub.length ? (
          <div className={spec.wrap ? "ag-dense-l2 ag-dense-wrap" : "ag-dense-l2"}>
            {sub.map((item, index) => (
              <span key={index}>
                {index ? " · " : null}
                {item}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      {present(value) || present(delta) ? (
        <div className="ag-dense-side">
          {present(value) ? <div className="ag-dense-l1">{value}</div> : null}
          {present(delta) ? <div className="ag-dense-l2">{delta}</div> : null}
        </div>
      ) : null}
    </Link>
  );
}

export function DenseRows<T>({
  rows,
  rowKey,
  spec,
}: {
  rows: T[];
  rowKey: (row: T, index: number) => string;
  spec: DenseSpec<T>;
}) {
  return (
    <div className="ag-dense">
      {rows.map((row, index) => (
        <DenseRow key={rowKey(row, index)} row={row} spec={spec} />
      ))}
    </div>
  );
}

/** One "label — value" line of a card. A null or empty value drops the line. */
export type StackLine<T> = { label: ReactNode; cell: (row: T) => ReactNode };

/**
 * One card per row. Missing cells are dropped rather than printed as "n/a":
 * on a phone a short card beats a complete one.
 */
export function StackCards<T>({
  rows,
  rowKey,
  title,
  lines,
}: {
  rows: T[];
  rowKey: (row: T, index: number) => string;
  /** What heads each card; its column is left out of the lines. */
  title?: (row: T) => ReactNode;
  lines: StackLine<T>[];
}) {
  return (
    <div className="ag-stack">
      {rows.map((row, index) => {
        const head = title?.(row);
        return (
          <div className="ag-stack-card" key={rowKey(row, index)}>
            {present(head) ? <div className="ag-stack-title">{head}</div> : null}
            {lines.map((line, at) => {
              const value = line.cell(row);
              if (!present(value)) return null;
              return (
                <div className="ag-stack-kv" key={at}>
                  <span className="ag-stack-k">{line.label}</span>
                  <span className="ag-stack-v">{value}</span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
