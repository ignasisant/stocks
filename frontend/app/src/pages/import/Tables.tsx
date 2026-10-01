/**
 * The preview's tables of parsed rows. What the parser left out is `Skipped`.
 *
 * Columns keep their English names internally — the ledger, the parsers, the
 * CLI and every test agree on those words — and only the header text is
 * translated, exactly as the Streamlit page does it.
 *
 * Rejected rows do not link their symbol. They are rejected precisely because
 * something about them is malformed, and a ticker cell that links a malformed
 * symbol to a ticker page is a link to nothing.
 *
 * A statement is hundreds of rows, so the full table scrolls inside its own
 * frame (`tall`) with its header pinned, and the confirm bar above it never
 * leaves the screen. A phone gets two-line cards instead, fifty at a time.
 *
 * The full list says how each trade has done (`Row.gain`, worked out by the
 * server): a buy against today's price, a sale against the cost it realized.
 * The brief tables leave it out — their point is the issue, not the result.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { Responsive } from "../../ui/Rows";
import type { Issue, Row } from "./api";
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
  "gain",
  "note",
] as const;

/** The identifying fields, for the tables whose point is the issue column. */
const BRIEF = ["date", "ticker", "action", "quantity", "price"] as const;

type Field = (typeof FULL)[number];

/** Columns that hold a figure: right-aligned, and formatted to their own places. */
const PLACES: Partial<Record<Field, number>> = { quantity: 4, price: 2, fee: 2 };

/** Right-aligned too: the figures, and the gain beside them. */
const numeric = (field: Field) => PLACES[field] !== undefined || field === "gain";

/** Cards a phone draws before asking for more. */
const PAGE = 50;

/** A verb's colour: bought green, sold red, moved in the brand's own. */
export function opClass(action: string): string {
  if (action === "buy") return "im-op im-op-buy";
  if (action === "sell") return "im-op im-op-sell";
  if (action.startsWith("transfer")) return "im-op im-op-move";
  return "im-op";
}

/** Where a column's cell takes its look from. */
const CELL: Partial<Record<Field, string>> = {
  date: "im-date",
  ticker: "im-tick-cell",
  currency: "im-cur",
  note: "im-note-cell",
};

export function RowTable({
  rows,
  brief = false,
  issues,
  link = true,
  tone,
  tall = false,
}: {
  rows: Row[];
  /** Only the identifying fields — for the warned and rejected tables. */
  brief?: boolean;
  /** Which issues to spell out in a trailing column, if any. */
  issues?: "warnings" | "errors";
  link?: boolean;
  /** The tier's tint: its frame, its header, the colour of its message. */
  tone?: "bad" | "warn";
  /** Scroll inside a frame of its own, header pinned, rather than grow the page. */
  tall?: boolean;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const [shown, setShown] = useState(PAGE);
  const fields: readonly Field[] = brief ? BRIEF : FULL;

  const symbol = (row: Row) => {
    if (!row.ticker) return "—";
    // The house rule, and one request for the whole table: a bare symbol is
    // never enough, and `TickerCell` collects every cell on the page into one
    // `/market/profiles` call rather than one per row.
    if (!link) return row.ticker;
    return <TickerCell className="im-tick" ticker={row.ticker} />;
  };

  const cell = (row: Row, field: Field) => {
    const places = PLACES[field];
    if (places !== undefined) return vocab.num(row[field] as number, places);
    if (field === "action")
      return <span className={opClass(row.action)}>{vocab.action(row.action)}</span>;
    if (field === "ticker") return symbol(row);
    if (field === "gain") return <Gain row={row} />;
    return row[field];
  };

  const wanted = (row: Row): Issue[] =>
    row.issues.filter((i) =>
      issues === "errors" ? i.severity === "error" : i.severity === "warning",
    );

  const wide = (
    <div className={tone ? `im-grid im-grid-${tone}` : "im-grid"}>
      <div className={tall ? "im-scroll im-scroll-tall" : "im-scroll"}>
        <table className="im-table">
          <thead>
            <tr>
              {fields.map((field) => (
                <th
                  className={
                    numeric(field)
                      ? "im-num"
                      : field === "note"
                        ? "im-note-cell"
                        : undefined
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
                  <td className={numeric(field) ? "im-num" : CELL[field]} key={field}>
                    {cell(row, field)}
                  </td>
                ))}
                {issues && <td className="im-issues">{vocab.issues(wanted(row))}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  // Only the full list pages: a rejected or warned row is one to read, and
  // hiding the fifty-first behind a button would hide the one that mattered.
  const visible = tall ? rows.slice(0, shown) : rows;
  const left = rows.length - visible.length;
  const tag =
    tone === "bad"
      ? t("import.tag_rejected")
      : tone === "warn"
        ? t("import.tag_warned")
        : null;

  const narrow = (
    <div className={tone ? `im-rcards im-rcards-${tone}` : "im-rcards im-rcards-plain"}>
      <ul>
        {visible.map((row, index) => (
          <li className="im-rcard" key={`${row.date}-${row.ticker}-${index}`}>
            <div className="im-rcard-top">
              {tag ? <span className={`im-tag im-tag-${tone}`}>{tag}</span> : null}
              <span className="im-rcard-sym">{symbol(row)}</span>
              <span className={opClass(row.action)}>{vocab.action(row.action)}</span>
              <span className="im-rcard-date">{row.date}</span>
            </div>
            <div className="im-rcard-sub">
              <span>
                {vocab.num(row.quantity, PLACES.quantity!)} ×{" "}
                {vocab.num(row.price, PLACES.price!)} · {row.currency}
                {!brief && row.fee
                  ? ` · ${t("import.fee_short", { fee: vocab.num(row.fee, PLACES.fee!) })}`
                  : null}
              </span>
              {!brief && <Gain row={row} />}
            </div>
            {issues && <p className="im-rcard-msg">{vocab.issues(wanted(row))}</p>}
          </li>
        ))}
      </ul>
      {left > 0 && (
        <button
          className="im-more"
          onClick={() => setShown((count) => count + PAGE)}
          type="button"
        >
          {t("import.show_more", {
            n: vocab.num(Math.min(PAGE, left), 0),
            left: vocab.num(left, 0),
          })}
        </button>
      )}
    </div>
  );

  return <Responsive wide={wide} narrow={narrow} />;
}

/**
 * A row's gain, signed and in its sign's colour; nothing when it has none.
 * The title says what it was measured against, which differs by verb.
 */
function Gain({ row }: { row: Row }) {
  const t = useT();
  const vocab = useVocabulary();
  if (row.gain == null || !Number.isFinite(row.gain)) return null;
  const tone = row.gain > 0 ? " im-gain-up" : row.gain < 0 ? " im-gain-down" : "";
  return (
    <span
      className={`im-gain${tone}`}
      title={t(row.action === "sell" ? "import.gain_sell" : "import.gain_buy")}
    >
      {vocab.pct(row.gain)}
    </span>
  );
}
