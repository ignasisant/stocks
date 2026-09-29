/**
 * The last committed batch, and the two different things to do with it.
 *
 * Committed rows live in the ledger, so there is nothing to re-upload — *clear
 * last import* deletes the ids that commit inserted and no others, and
 * *dismiss* forgets the note while the rows stay exactly where they are. What
 * separates them is the ledger itself, which is why they are two buttons and
 * one caption rather than one button whose meaning has to be guessed.
 *
 * It sits in the rail and stays there while a new statement is previewed:
 * undoing the last batch moves the ledger that preview was validated against,
 * and the page re-reads the preview on every write for exactly that reason.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { Status } from "../../ui/Status";
import { dismissRecord, undoLast } from "./api";
import type { LastImport, LedgerRow, Platform } from "./api";
import { Fold } from "./Card";
import { Glyph } from "./Glyph";
import { opClass } from "./Tables";
import { useVocabulary } from "./text";

export function LastBatch({
  onDone,
  platforms,
  record,
}: {
  onDone: () => void;
  platforms: Platform[];
  record: LastImport;
}) {
  const t = useT();
  const vocab = useVocabulary();
  // Which of the two presses is in flight: both lock the card, but the line
  // under it says which one was taken.
  const [busy, setBusy] = useState<"undo" | "dismiss" | null>(null);
  const source =
    platforms.find((entry) => entry.key === record.platform)?.label ??
    record.platform ??
    "";
  const rows = vocab.tn("import.rows_count", record.rows);
  const meta =
    [source, rows, record.imported_at ? vocab.when(record.imported_at) : ""]
      .filter(Boolean)
      .join(" · ") + (record.wiped ? t("import.ledger_wiped_suffix") : "");
  // What the commit wrote and what is left are two counts, and they part
  // company as soon as a row is deleted by hand. The reader is told how many
  // left rather than shown a batch that quietly shrank.
  const gone = record.rows - record.still_here;

  const act = async (press: "undo" | "dismiss", call: () => Promise<unknown>) => {
    setBusy(press);
    try {
      await call();
    } catch {
      // Nothing was deleted. Re-reading the record below is the honest
      // answer either way: it says what is still there.
    } finally {
      setBusy(null);
      onDone();
    }
  };

  return (
    <Fold
      id="im-last"
      summary={[source, rows].filter(Boolean).join(" · ")}
      title={t("import.last_import")}
    >
      <div className="im-last-file">
        <span className="im-last-name" title={record.filename ?? undefined}>
          {record.filename}
        </span>
        <span className="im-fine">{meta}</span>
      </div>
      {gone > 0 && (
        <p className="im-note-warn">
          <Glyph name="info" />
          {vocab.tn("import.rows_gone", gone)}
        </p>
      )}
      {record.transactions.length > 0 && (
        <details className="im-disclosure">
          <summary>
            <Glyph name="right" />
            {vocab.tn("import.rows_still", record.still_here)}
          </summary>
          <Mini rows={record.transactions} />
        </details>
      )}
      <div className="im-stack">
        <button
          className="im-btn im-btn-danger-outline"
          disabled={busy !== null || record.still_here === 0}
          onClick={() => void act("undo", undoLast)}
          type="button"
        >
          {t("import.clear_last_import", { n: vocab.num(record.still_here, 0) })}
        </button>
        <button
          className="im-btn im-btn-text"
          disabled={busy !== null}
          onClick={() => void act("dismiss", dismissRecord)}
          type="button"
        >
          {t("import.dismiss_short")}
        </button>
      </div>
      {busy && (
        <Status
          label={
            busy === "undo"
              ? t("import.work_undoing", { n: vocab.num(record.still_here, 0) })
              : t("import.work_dismissing")
          }
        />
      )}
      <p className="im-fine im-faint">{t("import.last_help_short")}</p>
    </Fold>
  );
}

/**
 * The batch's rows at rail width: one line each — day, symbol, verb, amount.
 * A committed row has no parser issues left to report, and the eight-column
 * preview table would only pan sideways in 340 pixels.
 */
function Mini({ rows }: { rows: LedgerRow[] }) {
  const vocab = useVocabulary();
  return (
    <ul className="im-mini">
      {rows.map((row, index) => (
        <li key={row.id ?? `${row.date}-${row.ticker}-${index}`}>
          <span className="im-mini-date">{row.date}</span>
          <span className="im-mini-sym">
            {row.ticker ? <TickerCell name={false} ticker={row.ticker} /> : "—"}
          </span>
          <span className={opClass(row.action)}>{vocab.action(row.action)}</span>
          <span className="im-mini-fig">
            {vocab.num(row.quantity, 4)} × {vocab.num(row.price, 2)}
          </span>
        </li>
      ))}
    </ul>
  );
}
