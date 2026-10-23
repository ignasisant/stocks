/**
 * The preview card: what the attached statement would write, before it does.
 *
 * Every line on it is a catalog key (`chat.import_*`), and the promise it
 * makes is the safety property of the whole feature: nothing reaches the
 * ledger until somebody has seen the rows and pressed the button. The tiers
 * are folded away rather than hidden — warnings and rejections are about rows
 * that are (or are not) going in, and a reader who wants to know why can open
 * them.
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

import { Surface } from "./a2ui";
import { createPortal } from "react-dom";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useT } from "../shell/i18n";
import { TickerCell } from "../shell/tickers";
import { Glyph } from "./icons";
import { Status } from "../ui/Status";
import type { ImportRow, Preview } from "./types";
import { calendarDay } from "../shell/dates";
import { useDialog } from "../shell/useDialog";

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
            <td>{calendarDay(row.date)}</td>
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

type Tab = "fresh" | "flagged" | "rejected" | "duplicates" | "skipped";

/**
 * The same statement at the width a table wants: tabs over the one dataset
 * (new, warnings, rejected, already held, skipped) and a table whose rows can
 * be ticked. The drawer's card shows the summary; this is where a long file is
 * actually read. Nothing here writes — it edits the card's selection, and the
 * card's own button (repeated in the footer) still does the writing.
 */
function Review({
  preview,
  off,
  picked,
  onToggleFresh,
  onToggleDupe,
  onAllFresh,
  onAllDupes,
  footer,
  onClose,
}: {
  preview: Preview;
  off: Set<number>;
  picked: Set<number>;
  onToggleFresh: (i: number) => void;
  onToggleDupe: (i: number) => void;
  onAllFresh: (on: boolean) => void;
  onAllDupes: (on: boolean) => void;
  footer: ReactNode;
  onClose: () => void;
}) {
  const t = useT();
  const uid = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useDialog(dialog, { initial: close });
  const tabs: { id: Tab; label: string; n: number }[] = (
    [
      { id: "fresh", label: "chat.import_tab_new", n: preview.fresh.length },
      { id: "flagged", label: "chat.import_tab_warnings", n: preview.flagged.length },
      { id: "rejected", label: "chat.import_tab_rejected", n: preview.rejected.length },
      { id: "duplicates", label: "chat.import_tab_held", n: preview.duplicates.length },
      { id: "skipped", label: "chat.import_tab_skipped", n: preview.skipped.length },
    ] as const
  ).filter((tab) => tab.n > 0 || tab.id === "fresh");
  const [tab, setTab] = useState<Tab>(tabs[0]!.id);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows =
    tab === "fresh"
      ? preview.fresh
      : tab === "flagged"
        ? preview.flagged
        : tab === "rejected"
          ? preview.rejected
          : tab === "duplicates"
            ? preview.duplicates
            : [];
  const choosable = tab === "fresh" || tab === "duplicates";
  const on = (i: number) => (tab === "fresh" ? !off.has(i) : picked.has(i));
  const all = rows.length > 0 && rows.every((_, i) => on(i));
  const flip = tab === "fresh" ? onToggleFresh : onToggleDupe;
  const verb = (action: string) => {
    const key = `import.action_${action}`;
    const label = t(key);
    return label === key ? action : label;
  };
  const move = (event: React.KeyboardEvent, at: number) => {
    const next =
      event.key === "ArrowRight" ? at + 1 : event.key === "ArrowLeft" ? at - 1 : null;
    if (next === null) return;
    event.preventDefault();
    const to = tabs[(next + tabs.length) % tabs.length]!;
    setTab(to.id);
    document.getElementById(`${uid}-${to.id}`)?.focus();
  };

  return createPortal(
    <div
      ref={dialog}
      className="ag-chat-review"
      role="dialog"
      aria-modal="true"
      aria-label={preview.filename}
      tabIndex={-1}
    >
      <header className="ag-chat-review-head">
        <p className="ag-chat-review-title">
          {t("chat.import_preview", {
            filename: preview.filename,
            label: preview.label,
          })}
        </p>
        <button type="button" className="ag-chat-btn" ref={close} onClick={onClose}>
          {t("chat.import_review_close")}
        </button>
      </header>
      <div className="ag-chat-review-tabs" role="tablist">
        {tabs.map((item, at) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`${uid}-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`${uid}-panel`}
            tabIndex={tab === item.id ? 0 : -1}
            className="ag-chat-review-tab"
            onClick={() => setTab(item.id)}
            onKeyDown={(event) => move(event, at)}
          >
            {t(item.label, { n: item.n })}
          </button>
        ))}
      </div>
      <div
        className="ag-chat-review-body"
        role="tabpanel"
        id={`${uid}-panel`}
        aria-labelledby={`${uid}-${tab}`}
      >
        {tab === "skipped" ? (
          <ul className="ag-chat-skipped">
            {preview.skipped.map((line, i) => (
              <li key={i}>
                <b>{line.row}</b> {line.reason}
              </li>
            ))}
          </ul>
        ) : (
          <table className="ag-chat-rows ag-chat-review-rows">
            <thead>
              <tr>
                {choosable && (
                  <th className="ag-chat-pick">
                    <input
                      type="checkbox"
                      checked={all}
                      aria-label={t("chat.import_select_all")}
                      onChange={(event) =>
                        (tab === "fresh" ? onAllFresh : onAllDupes)(
                          event.target.checked,
                        )
                      }
                    />
                  </th>
                )}
                <th>{t("import.col_date")}</th>
                <th>{t("import.col_ticker")}</th>
                <th>{t("import.col_action")}</th>
                <th className="ag-chat-num">{t("import.col_quantity")}</th>
                <th className="ag-chat-num">{t("import.col_price")}</th>
                <th className="ag-chat-num">{t("chat.import_col_fee")}</th>
                <th>{t("chat.import_col_note")}</th>
                {tab !== "fresh" && <th>{t("import.col_why")}</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={`${row.date}-${row.ticker}-${i}`}
                  data-off={choosable && !on(i) ? "" : undefined}
                >
                  {choosable && (
                    <td className="ag-chat-pick">
                      <input
                        type="checkbox"
                        checked={on(i)}
                        aria-label={t("chat.import_select_row", { n: i + 1 })}
                        onChange={() => flip(i)}
                      />
                    </td>
                  )}
                  <td>{calendarDay(row.date)}</td>
                  <td>
                    {tab === "rejected" ? (
                      row.ticker
                    ) : (
                      <TickerCell ticker={row.ticker} />
                    )}
                  </td>
                  <td>{verb(row.action)}</td>
                  <td className="ag-chat-num">{figure(row.quantity, 4)}</td>
                  <td className="ag-chat-num">
                    {figure(row.price, 2)} {row.currency}
                  </td>
                  <td className="ag-chat-num">
                    {row.fee === "" ? "" : figure(row.fee, 2)}
                  </td>
                  <td>{row.note}</td>
                  {tab !== "fresh" && <td>{row.why}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <footer className="ag-chat-review-foot">{footer}</footer>
    </div>,
    document.body,
  );
}

export function Attachment({
  preview,
  busy,
  importing = false,
  onImport,
  onDiscard,
  onRemap,
}: {
  preview: Preview;
  /** A statement is being read or written: both buttons wait. */
  busy: boolean;
  /** This card's rows are the ones being written. */
  importing?: boolean;
  onImport: (broker: string, fresh: ImportRow[], duplicates: ImportRow[]) => void;
  onDiscard: () => void;
  /** Read the file again with a corrected column mapping. */
  onRemap?: (mapping: Record<string, unknown>) => void;
}) {
  const t = useT();
  const uid = useId();
  const [broker, setBroker] = useState(preview.broker);
  const [typed, setTyped] = useState("");
  // What the reader ticked: the new rows left out, and the held-back ones let
  // back in. The drawer's card only ever flips the second as a whole; the
  // full-width review does it row by row.
  const [off, setOff] = useState<Set<number>>(new Set());
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [full, setFull] = useState(false);

  const dupes = preview.duplicates;
  const withDupes = dupes.length > 0 && picked.size === dupes.length;
  const origin = (broker === "other" && typed.trim() ? typed.trim() : broker).trim();
  const count = preview.fresh.length - off.size + picked.size;
  const flip = (set: Set<number>, i: number) => {
    const next = new Set(set);
    if (!next.delete(i)) next.add(i);
    return next;
  };
  const write = () =>
    onImport(
      origin,
      preview.fresh.filter((_, i) => !off.has(i)),
      dupes.filter((_, i) => picked.has(i)),
    );

  const brokerBlock = (
    <>
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
    </>
  );
  const acts = (
    <div className="ag-chat-import-acts">
      <button
        type="button"
        className="ag-chat-btn ag-chat-btn-on"
        disabled={busy || !origin || !count}
        onClick={write}
      >
        {t("chat.import_button", { n: count })}
      </button>
      <button type="button" className="ag-chat-btn" disabled={busy} onClick={onDiscard}>
        {t("chat.import_cancel")}
      </button>
    </div>
  );

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

      {/* How an export no parser owns was read, as the server's A2UI surface:
          open when it read nothing (that is the mapping to fix), folded when
          the rows above already look right. */}
      {preview.surface?.length ? (
        <details className="ag-chat-tier" open={preview.fresh.length === 0}>
          <summary>{t("chat.import_col_title")}</summary>
          <Surface
            messages={preview.surface}
            disabled={busy}
            onAction={(action) => {
              const mapping = action.context.mapping;
              if (action.name === "remap" && mapping && typeof mapping === "object") {
                onRemap?.(mapping as Record<string, unknown>);
              }
            }}
          />
        </details>
      ) : null}

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
              onChange={(event) =>
                setPicked(new Set(event.target.checked ? dupes.map((_, i) => i) : []))
              }
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

      {full ? null : brokerBlock}
      {acts}
      {preview.fresh.length + dupes.length + preview.flagged.length > 0 && (
        <button
          type="button"
          className="ag-chat-btn ag-chat-review-open"
          onClick={() => setFull(true)}
        >
          {t("chat.import_review")}
        </button>
      )}
      {full && (
        <Review
          preview={preview}
          off={off}
          picked={picked}
          onToggleFresh={(i) => setOff((set) => flip(set, i))}
          onToggleDupe={(i) => setPicked((set) => flip(set, i))}
          onAllFresh={(on) => setOff(new Set(on ? [] : preview.fresh.map((_, i) => i)))}
          onAllDupes={(on) => setPicked(new Set(on ? dupes.map((_, i) => i) : []))}
          footer={
            <>
              {brokerBlock}
              <p className="ag-chat-hint">
                {t("chat.import_selected", {
                  n: preview.fresh.length - off.size,
                  total: preview.fresh.length,
                })}
              </p>
              {acts}
            </>
          }
          onClose={() => setFull(false)}
        />
      )}
      {/* Beside the buttons that just went grey, which is where the eye is
          after pressing one: a batch of a few hundred rows is a few seconds
          of prices and dedupe, and nothing else on the card moves. */}
      {importing && <Status label={t("chat.work_importing", { n: count })} />}
    </section>
  );
}
