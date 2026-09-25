/**
 * The preview card: what the attached statement would write, before it does.
 *
 * Everything on it is the same offer the Streamlit drawer makes, key for key
 * (`chat.import_*`), because the promise is the safety property of the whole
 * feature: nothing reaches the ledger until somebody has seen the rows and
 * pressed the button. The tiers are folded away rather than hidden — warnings
 * and rejections are about rows that are (or are not) going in, and a reader
 * who wants to know why can open them.
 *
 * The duplicates are the one tier that is *not* about to be written, so when
 * there is nothing else they open by themselves: the count in the note above
 * only makes sense next to the rows it is talking about. Their checkbox is the
 * escape hatch for the honest repeat — two identical fills, a broker that
 * really did pay the same dividend twice.
 *
 * A file no parser owned names no broker, and the picker holds the import
 * until one is chosen: the fees and custody views read the book by it, so a
 * batch that lands unattributed is tedious to repair afterwards. The roster is
 * the brokers this app has parsers for, and it takes a typed name too, because
 * naming the real one beats filing the batch under "other".
 */

import { useId, useState } from "react";
import { useT } from "../shell/i18n";
import { TickerCell } from "../shell/tickers";
import { Glyph } from "./icons";
import type { ImportRow, Preview } from "./types";

/** Money and share counts, in the reader's own locale. */
function figure(value: number | string, digits: number): string {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : String(value);
}

/**
 * The preview grid.
 *
 * `rich` is off for the rejected tier: those symbols are malformed by
 * definition, so there is no company to resolve a logo or a page from and a
 * link that 404s is worse than plain text.
 */
function Rows({
  rows,
  why,
  rich = true,
}: {
  rows: ImportRow[];
  why?: boolean;
  rich?: boolean;
}) {
  const t = useT();
  // The ledger stores one vocabulary — `buy`, `split` — and this is the one
  // screen where a reader meets it (`web/tx_text`). An unnamed verb passes
  // through rather than rendering as its own key.
  const verb = (action: string) => {
    const key = `import.action_${action}`;
    const label = t(key);
    return label === key ? action : label;
  };
  return (
    <table className="ag-chat-rows">
      <thead>
        <tr>
          <th>{t("import.col_date")}</th>
          <th>{t("import.col_ticker")}</th>
          <th>{t("import.col_action")}</th>
          <th className="ag-chat-num">{t("import.col_quantity")}</th>
          <th className="ag-chat-num">{t("import.col_price")}</th>
          {why && <th>{t("import.col_why")}</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={`${row.date}-${row.ticker}-${i}`}>
            <td>{row.date}</td>
            <td>
              {/* Every ticker on screen is a logo and a link to its page — in
                  a chat bubble as anywhere else in the app. */}
              {rich ? <TickerCell ticker={row.ticker} /> : row.ticker}
            </td>
            <td>{verb(row.action)}</td>
            <td className="ag-chat-num">{figure(row.quantity, 4)}</td>
            <td className="ag-chat-num">
              {figure(row.price, 2)} {row.currency}
            </td>
            {why && <td>{row.why}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Tier({
  label,
  rows,
  open,
  rich,
}: {
  label: string;
  rows: ImportRow[];
  open?: boolean;
  rich?: boolean;
}) {
  if (!rows.length) return null;
  return (
    <details className="ag-chat-tier" open={open}>
      <summary>{label}</summary>
      <Rows rows={rows} why rich={rich} />
    </details>
  );
}

export function Attachment({
  preview,
  busy,
  onImport,
  onDiscard,
}: {
  preview: Preview;
  busy: boolean;
  onImport: (broker: string, duplicates: ImportRow[]) => void;
  onDiscard: () => void;
}) {
  const t = useT();
  const uid = useId();
  const [broker, setBroker] = useState(preview.broker);
  const [typed, setTyped] = useState("");
  const [withDupes, setWithDupes] = useState(false);

  const dupes = preview.duplicates;
  const origin = (broker === "other" && typed.trim() ? typed.trim() : broker).trim();
  const count = preview.fresh.length + (withDupes ? dupes.length : 0);

  return (
    <section className="ag-chat-import" aria-label={preview.filename}>
      <p className="ag-chat-import-head">
        <Glyph name="attach" size={14} />
        {t("chat.import_preview", {
          filename: preview.filename,
          label: preview.label,
        })}
      </p>

      {preview.fresh.length > 0 && <Rows rows={preview.fresh} />}

      <Tier
        label={t("chat.import_warnings", { n: preview.flagged.length })}
        rows={preview.flagged}
      />
      <Tier
        label={t("chat.import_rejected", { n: preview.rejected.length })}
        rows={preview.rejected}
        rich={false}
      />

      {dupes.length > 0 && (
        <details className="ag-chat-tier" open={!preview.fresh.length}>
          <summary>{t("chat.import_duplicates", { n: dupes.length })}</summary>
          <Rows rows={dupes} why />
          <label className="ag-chat-check">
            <input
              type="checkbox"
              checked={withDupes}
              onChange={(event) => setWithDupes(event.target.checked)}
            />
            {t("chat.import_duplicates_anyway")}
          </label>
        </details>
      )}

      {preview.skipped.length > 0 && (
        <details className="ag-chat-tier">
          <summary>{t("chat.import_skipped", { n: preview.skipped.length })}</summary>
          <ul className="ag-chat-skipped">
            {preview.skipped.map((line, i) => (
              <li key={i}>
                <b>{line.row}</b> {line.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      {preview.needs_broker ? (
        <div className="ag-chat-broker">
          <label htmlFor={`${uid}-broker`}>{t("chat.import_broker")}</label>
          <select
            id={`${uid}-broker`}
            value={broker}
            onChange={(event) => setBroker(event.target.value)}
          >
            <option value="">{t("chat.import_broker_pick")}</option>
            {preview.brokers.map((b) => (
              <option key={b.key} value={b.key}>
                {b.label}
              </option>
            ))}
          </select>
          {/* The roster only holds brokers with a parser, so "other" takes the
              real name rather than filing the batch under a shrug. */}
          {broker === "other" && (
            <input
              type="text"
              value={typed}
              aria-label={t("chat.import_broker")}
              placeholder={t("chat.import_broker_pick")}
              onChange={(event) => setTyped(event.target.value)}
            />
          )}
          <p className="ag-chat-hint">{t("chat.import_broker_help")}</p>
        </div>
      ) : (
        preview.broker && (
          <p className="ag-chat-hint">
            {t("chat.import_broker_known", {
              // The roster carries the display names; the row carries the key.
              broker:
                preview.brokers.find((b) => b.key === preview.broker)?.label ??
                preview.broker,
            })}
          </p>
        )
      )}

      <div className="ag-chat-import-acts">
        <button
          type="button"
          className="ag-chat-btn ag-chat-btn-on"
          disabled={busy || !origin || !count}
          onClick={() => onImport(origin, withDupes ? dupes : [])}
        >
          {t("chat.import_button", { n: count })}
        </button>
        <button
          type="button"
          className="ag-chat-btn"
          disabled={busy}
          onClick={onDiscard}
        >
          {t("chat.import_cancel")}
        </button>
      </div>
    </section>
  );
}
