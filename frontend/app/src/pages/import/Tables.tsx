/**
 * The preview's tables: parsed rows, and the rows the parser left out.
 *
 * Columns keep their English names internally — the ledger, the parsers, the
 * CLI and every test agree on those words — and only the header text is
 * translated, exactly as the Streamlit page does it.
 *
 * Rejected rows do not link their symbol. They are rejected precisely because
 * something about them is malformed, and a ticker cell that links a malformed
 * symbol to a ticker page is a link to nothing.
 */

import { TickerCell } from "../../shell/tickers";
import type { Issue, Row, SkippedRow } from "./api";
import { useVocabulary } from "./text";

/** Every field a parsed row carries. */
const FULL = [
  "date",
  "ticker",
  "action",
  "quantity",
  "price",
  "fee",
  "currency",
  "note",
] as const;

/** The identifying fields, for the tables whose point is the issue column. */
const BRIEF = ["date", "ticker", "action", "quantity", "price"] as const;

type Field = (typeof FULL)[number];

/** Columns that hold a figure: right-aligned, and formatted to their own places. */
const PLACES: Partial<Record<Field, number>> = { quantity: 4, price: 2, fee: 2 };

/** Columns a phone drops. The identity of a row and what it did survive. */
const WIDE: Partial<Record<Field, boolean>> = { fee: true, currency: true, note: true };

export function RowTable({
  rows,
  brief = false,
  issues,
  link = true,
}: {
  rows: Row[];
  /** Only the identifying fields — for the warned and rejected tables. */
  brief?: boolean;
  /** Which issues to spell out in a trailing column, if any. */
  issues?: "warnings" | "errors";
  link?: boolean;
}) {
  const vocab = useVocabulary();
  const fields: readonly Field[] = brief ? BRIEF : FULL;

  const cell = (row: Row, field: Field) => {
    const places = PLACES[field];
    if (places !== undefined) return vocab.num(row[field] as number, places);
    if (field === "action") return vocab.action(row.action);
    if (field === "ticker") {
      if (!row.ticker) return "—";
      // The house rule, and one request for the whole table: a bare symbol is
      // never enough, and `TickerCell` collects every cell on the page into one
      // `/market/profiles` call rather than one per row.
      if (!link) return row.ticker;
      return <TickerCell ticker={row.ticker} />;
    }
    return row[field];
  };

  const wanted = (row: Row): Issue[] =>
    row.issues.filter((i) =>
      issues === "errors" ? i.severity === "error" : i.severity === "warning",
    );

  return (
    <div className="im-scroll">
      <table className="im-table">
        <thead>
          <tr>
            {fields.map((field) => (
              <th
                className={
                  (PLACES[field] !== undefined ? "im-num " : "") +
                  (WIDE[field] ? "im-wide" : "")
                }
                key={field}
                scope="col"
              >
                {vocab.column(field)}
              </th>
            ))}
            {issues && <th scope="col">{vocab.column(issues)}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.date}-${row.ticker}-${index}`}>
              {fields.map((field) => (
                <td
                  className={
                    (PLACES[field] !== undefined ? "im-num " : "") +
                    (WIDE[field] ? "im-wide" : "")
                  }
                  key={field}
                >
                  {cell(row, field)}
                </td>
              ))}
              {issues && <td className="im-issues">{vocab.issues(wanted(row))}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The rows the parser left out, as it described them.
 *
 * Their shape is the parser's (`{row, type, reason}` today), so the columns are
 * read off the data rather than fixed here: a parser that starts reporting one
 * more field should show it, not have it silently dropped.
 */
export function SkippedTable({ rows }: { rows: SkippedRow[] }) {
  const vocab = useVocabulary();
  const fields: string[] = [];
  for (const row of rows)
    for (const field of Object.keys(row))
      if (!fields.includes(field)) fields.push(field);

  return (
    <div className="im-scroll">
      <table className="im-table">
        <thead>
          <tr>
            {fields.map((field) => (
              <th key={field} scope="col">
                {vocab.column(field)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {fields.map((field) => (
                <td key={field}>
                  {row[field] === null ? "—" : String(row[field] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
