/**
 * The preview card: what the attached statement would write, before it does.
 *
 * Every line on it is a catalog key (`chat.import_*`), and the promise it
 * makes is the safety property of the whole feature: nothing reaches the
 * ledger until somebody has seen the rows and pressed the button — which is
 * why the card says so in words, beside the button.
 *
 * Three shapes of the one selection:
 *
 * - In the drawer, a summary: how many rows are ready, how many carry a
 *   warning, how many the book already holds, and the first few rows. A
 *   statement is read at the width a table wants, not in a 420px column.
 * - Wide, the same panel taken to the full window (never a modal over the
 *   page): tabs over the tiers, rows that can be ticked, and a summary of
 *   what the ticked rows add up to. Back puts the drawer's width back.
 * - On a phone, where there is no wide, a list a thumb can work: one row per
 *   operation with its checkbox, the warned ones marked and opening to their
 *   reason and a currency fix — the one slip a reader can repair from here.
 *
 * Warnings are about rows that *are* going in (`fresh`); the server sends them
 * again in `flagged` with the reason, matched back here by their fields. The
 * duplicates are the one tier that is not about to be written; their checkbox
 * is the escape hatch for the honest repeat — two identical fills, a broker
 * that really did pay the same dividend twice.
 *
 * A file no parser owned names no broker, and the picker holds the import
 * until one is chosen: the fees and custody views read the book by it, so a
 * batch that lands unattributed is tedious to repair afterwards. The roster is
 * the brokers this app has parsers for, and it takes a typed name too, because
 * naming the real one beats filing the batch under "other".
 */

import { Surface } from "./a2ui";
import { createPortal } from "react-dom";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useT } from "../shell/i18n";
import { TickerCell } from "../shell/tickers";
import { Glyph } from "./icons";
import { Status } from "../ui/Status";
import type { ImportRow, Preview } from "./types";
import { calendarDay } from "../shell/dates";
import { useDialog } from "../shell/useDialog";
import { usePhone } from "./phone";
import { borrowWidth } from "./width";

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

/** Shares are whole more often than not; a fraction keeps its digits. */
function units(value: number): string {
  return Number.isInteger(value)
    ? figure(value, 0)
    : value.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

/** What a row moves: the fill for a trade, the amount for a payout. */
function total(row: ImportRow): number {
  return row.quantity ? Math.abs(row.quantity * row.price) : Math.abs(row.price);
}

/** The fields a warned row is matched back to its `fresh` twin by. */
function same(row: ImportRow): string {
  return [row.date, row.ticker, row.action, row.quantity, row.price].join("|");
}

/** A verb that opens a line: "Compra NVDA ×4", not "compra NVDA ×4". */
function lead(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Currencies a slip is fixed to: the file's own, and the usual ones. */
const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "GBX", "CAD", "JPY", "HKD"];

/**
 * The ledger stores one vocabulary — `buy`, `split` — and this is the one
 * screen where a reader meets it (`web/tx_text`). An unnamed verb passes
 * through rather than rendering as its own key.
 */
function useVerb() {
  const t = useT();
  return (action: string) => {
    const key = `import.action_${action}`;
    const label = t(key);
    return label === key ? action : label;
  };
}

/** The selection's counts, as the canvas draws them: three small figures. */
function Counts({
  ready,
  flagged,
  held,
  rejected,
}: {
  ready: number;
  flagged: number;
  held: number;
  rejected: number;
}) {
  const t = useT();
  const items = [
    { key: "chat.import_count_ready", n: ready, tone: undefined },
    {
      key: "chat.import_count_flagged",
      n: flagged,
      tone: flagged ? "warn" : undefined,
    },
    { key: "chat.import_count_held", n: held, tone: undefined },
    ...(rejected
      ? [{ key: "chat.import_count_rejected", n: rejected, tone: undefined }]
      : []),
  ];
  return (
    <dl className="ag-chat-counts">
      {items.map((item) => (
        <div key={item.key} data-tone={item.tone} data-zero={item.n ? undefined : ""}>
          <dt>{t(item.key)}</dt>
          <dd>{item.n}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A warned row's reason, and the currency it can be moved to. */
function Fix({
  why,
  currency,
  choices,
  onCurrency,
}: {
  why: string;
  currency: string;
  choices: string[];
  onCurrency: (currency: string) => void;
}) {
  const t = useT();
  const id = useId();
  return (
    <div className="ag-chat-fix">
      <p>{why}</p>
      <label htmlFor={id}>{t("chat.import_col_currency")}</label>
      <select
        id={id}
        value={currency}
        onChange={(event) => onCurrency(event.target.value)}
      >
        {choices.map((code) => (
          <option key={code} value={code}>
            {code}
          </option>
        ))}
      </select>
    </div>
  );
}

type Line = {
  /** Index into `fresh` or `duplicates`, whichever `held` says. */
  i: number;
  row: ImportRow;
  held: boolean;
  why: string;
};

/** One operation, sized for a thumb: checkbox, what it is, what it moves. */
function Op({
  line,
  on,
  onToggle,
  choices,
  onCurrency,
}: {
  line: Line;
  on: boolean;
  onToggle: () => void;
  choices: string[];
  onCurrency: (currency: string) => void;
}) {
  const t = useT();
  const verb = useVerb();
  const [open, setOpen] = useState(false);
  const { row, held, why } = line;
  const warned = !held && !!why;
  return (
    <li className="ag-chat-op" data-off={on ? undefined : ""}>
      <label className="ag-chat-op-pick">
        <input
          type="checkbox"
          checked={on}
          aria-label={t("chat.import_select_row", { n: line.i + 1 })}
          onChange={onToggle}
        />
      </label>
      <div className="ag-chat-op-text">
        <span className="ag-chat-op-title">
          {lead(verb(row.action))} <TickerCell ticker={row.ticker} />
          {row.quantity ? ` ×${units(row.quantity)}` : ""}
        </span>
        <span className="ag-chat-op-sub">
          {calendarDay(row.date)} · {figure(row.price, 2)} {row.currency}
          {held ? ` · ${t("chat.import_in_book")}` : ""}
        </span>
      </div>
      <span className="ag-chat-op-amt">
        {figure(total(row), 2)} {row.currency}
      </span>
      {warned && (
        <button
          type="button"
          className="ag-chat-op-mark"
          aria-expanded={open}
          aria-label={t("chat.import_warned")}
          onClick={() => setOpen((was) => !was)}
        >
          !
        </button>
      )}
      {warned && open && (
        <Fix
          why={why}
          currency={row.currency}
          choices={choices}
          onCurrency={onCurrency}
        />
      )}
    </li>
  );
}

type Tab = "ready" | "flagged" | "rejected" | "duplicates" | "skipped";

/**
 * The statement at the width a table wants, inside the panel: tabs over the
 * one dataset and rows that can be ticked, with what the ticked rows add up
 * to beside them. Nothing here writes — it edits the card's selection, and
 * the buttons under the summary are the card's own.
 */
function Wide({
  preview,
  lines,
  on,
  onToggle,
  onAll,
  choices,
  onCurrency,
  side,
  onClose,
}: {
  preview: Preview;
  lines: Record<"ready" | "flagged" | "duplicates", Line[]>;
  on: (line: Line) => boolean;
  onToggle: (line: Line) => void;
  onAll: (lines: Line[], on: boolean) => void;
  choices: string[];
  onCurrency: (line: Line, currency: string) => void;
  side: ReactNode;
  onClose: () => void;
}) {
  const t = useT();
  const verb = useVerb();
  const uid = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  useDialog(dialog, { initial: back });
  const tabs: { id: Tab; label: string; n: number }[] = (
    [
      { id: "ready", label: "chat.import_tab_new", n: lines.ready.length },
      { id: "flagged", label: "chat.import_tab_warnings", n: lines.flagged.length },
      { id: "rejected", label: "chat.import_tab_rejected", n: preview.rejected.length },
      { id: "duplicates", label: "chat.import_tab_held", n: lines.duplicates.length },
      { id: "skipped", label: "chat.import_tab_skipped", n: preview.skipped.length },
    ] as const
  ).filter((tab) => tab.n > 0 || tab.id === "ready");
  const [tab, setTab] = useState<Tab>(
    tabs.find((item) => item.n > 0 && item.id !== "skipped")?.id ?? "ready",
  );
  // Back, not shut: Escape here leaves the drawer open where it was. Caught on
  // the way down so the drawer's own Escape never hears it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [onClose]);

  const rows: Line[] =
    tab === "rejected"
      ? preview.rejected.map((row, i) => ({ i, row, held: false, why: row.why }))
      : tab === "skipped"
        ? []
        : lines[tab];
  const choosable = tab !== "rejected";
  const all = rows.length > 0 && rows.every(on);
  const move = (event: React.KeyboardEvent, at: number) => {
    const next =
      event.key === "ArrowRight" ? at + 1 : event.key === "ArrowLeft" ? at - 1 : null;
    if (next === null) return;
    event.preventDefault();
    const to = tabs[(next + tabs.length) % tabs.length]!;
    setTab(to.id);
    document.getElementById(`${uid}-${to.id}`)?.focus();
  };

  return (
    <div
      ref={dialog}
      className="ag-chat-wide"
      role="dialog"
      aria-modal="true"
      aria-label={preview.filename}
      tabIndex={-1}
    >
      <header className="ag-chat-wide-head">
        <button type="button" className="ag-chat-btn" ref={back} onClick={onClose}>
          <Glyph name="back" size={14} />
          {t("chat.import_review_close")}
        </button>
        <p className="ag-chat-wide-title">
          <Glyph name="attach" size={14} />
          {t("chat.import_preview", {
            filename: preview.filename,
            label: preview.label,
          })}
        </p>
      </header>
      <div className="ag-chat-wide-body">
        <div className="ag-chat-wide-main">
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
                          onChange={(event) => onAll(rows, event.target.checked)}
                        />
                      </th>
                    )}
                    <th>{t("import.col_date")}</th>
                    <th>{t("chat.import_col_operation")}</th>
                    <th className="ag-chat-num">{t("chat.import_col_units")}</th>
                    <th className="ag-chat-num">{t("import.col_price")}</th>
                    <th className="ag-chat-num">{t("chat.import_col_total")}</th>
                    {tab !== "ready" && <th>{t("import.col_why")}</th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((line) => {
                    const { row } = line;
                    const warned = !line.held && tab !== "rejected" && !!line.why;
                    return (
                      <tr
                        key={`${line.held}-${line.i}`}
                        data-off={choosable && !on(line) ? "" : undefined}
                      >
                        {choosable && (
                          <td className="ag-chat-pick">
                            <input
                              type="checkbox"
                              checked={on(line)}
                              aria-label={t("chat.import_select_row", {
                                n: line.i + 1,
                              })}
                              onChange={() => onToggle(line)}
                            />
                          </td>
                        )}
                        <td>{calendarDay(row.date)}</td>
                        <td>
                          <span className="ag-chat-wide-op">
                            {warned && (
                              <span
                                className="ag-chat-mark"
                                title={t("chat.import_warned")}
                              >
                                !
                              </span>
                            )}
                            {verb(row.action)}{" "}
                            {/* Rejected symbols are malformed by definition: no
                                company to resolve a logo or a page from. */}
                            {tab === "rejected" ? (
                              row.ticker
                            ) : (
                              <TickerCell ticker={row.ticker} />
                            )}
                          </span>
                        </td>
                        <td className="ag-chat-num">{units(row.quantity)}</td>
                        <td className="ag-chat-num">
                          {figure(row.price, 2)} {row.currency}
                        </td>
                        <td className="ag-chat-num">
                          {figure(total(row), 2)} {row.currency}
                        </td>
                        {tab !== "ready" && (
                          <td className="ag-chat-why">
                            {warned ? (
                              <Fix
                                why={line.why}
                                currency={row.currency}
                                choices={choices}
                                onCurrency={(currency) => onCurrency(line, currency)}
                              />
                            ) : (
                              line.why
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
        <aside className="ag-chat-wide-side">{side}</aside>
      </div>
    </div>
  );
}

/** What the ticked rows add up to, before any of them is written. */
function Summary({ rows }: { rows: ImportRow[] }) {
  const t = useT();
  const tickers = new Set(rows.map((row) => row.ticker)).size;
  const days = rows.map((row) => row.date).sort();
  // Buys less sells, per currency: the cash the batch says went into the
  // market. Payouts and corporate actions move no purchase money.
  const net = new Map<string, number>();
  for (const row of rows) {
    const sign = row.action === "buy" ? 1 : row.action === "sell" ? -1 : 0;
    if (!sign) continue;
    net.set(row.currency, (net.get(row.currency) ?? 0) + sign * total(row));
  }
  return (
    <section className="ag-chat-sum" aria-label={t("chat.import_summary")}>
      <h3>{t("chat.import_summary")}</h3>
      <dl>
        <div>
          <dt>{t("chat.import_sum_ops")}</dt>
          <dd>{rows.length}</dd>
        </div>
        <div>
          <dt>{t("chat.import_sum_tickers")}</dt>
          <dd>{tickers}</dd>
        </div>
        {days.length > 0 && (
          <div>
            <dt>{t("chat.import_sum_range")}</dt>
            <dd>
              {calendarDay(days[0]!)} – {calendarDay(days[days.length - 1]!)}
            </dd>
          </div>
        )}
        {[...net].map(([currency, amount]) => (
          <div key={currency}>
            <dt>{t("chat.import_sum_net", { currency })}</dt>
            <dd>
              {amount < 0 ? "−" : ""}
              {figure(Math.abs(amount), 2)} {currency}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Attachment({
  preview,
  busy,
  importing = false,
  wide = false,
  onImport,
  onDiscard,
  onRemap,
}: {
  preview: Preview;
  /** A statement is being read or written: both buttons wait. */
  busy: boolean;
  /** This card's rows are the ones being written. */
  importing?: boolean;
  /** Open wide as it lands: the file was dropped on a desktop panel. */
  wide?: boolean;
  onImport: (broker: string, fresh: ImportRow[], duplicates: ImportRow[]) => void;
  onDiscard: () => void;
  /** Read the file again with a corrected column mapping. */
  onRemap?: (mapping: Record<string, unknown>) => void;
}) {
  const t = useT();
  const uid = useId();
  const phone = usePhone();
  const card = useRef<HTMLElement>(null);
  const [broker, setBroker] = useState(preview.broker);
  const [typed, setTyped] = useState("");
  // What the reader ticked: the new rows left out, and the held-back ones let
  // back in — plus the currency a warned row was moved to.
  const [off, setOff] = useState<Set<number>>(new Set());
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [fixed, setFixed] = useState<Record<number, string>>({});
  const [full, setFull] = useState(wide);
  const [host, setHost] = useState<HTMLElement | null>(null);

  const dupes = preview.duplicates;
  const fresh = useMemo(
    () =>
      preview.fresh.map((row, i) => (fixed[i] ? { ...row, currency: fixed[i]! } : row)),
    [preview.fresh, fixed],
  );
  const lines = useMemo(() => {
    const why = new Map(preview.flagged.map((row) => [same(row), row.why]));
    const all = preview.fresh.map((row, i) => ({
      i,
      row: fresh[i]!,
      held: false,
      why: why.get(same(row)) ?? "",
    }));
    return {
      ready: all.filter((line) => !line.why),
      flagged: all.filter((line) => line.why),
      duplicates: dupes.map((row, i) => ({ i, row, held: true, why: row.why })),
    };
  }, [preview.fresh, preview.flagged, fresh, dupes]);
  const choices = useMemo(
    () => [...new Set([...preview.fresh.map((row) => row.currency), ...CURRENCIES])],
    [preview.fresh],
  );
  const origin = (broker === "other" && typed.trim() ? typed.trim() : broker).trim();
  const chosen = [
    ...fresh.filter((_, i) => !off.has(i)),
    ...dupes.filter((_, i) => picked.has(i)),
  ];
  const count = chosen.length;
  const flip = (set: Set<number>, i: number) => {
    const next = new Set(set);
    if (!next.delete(i)) next.add(i);
    return next;
  };
  const on = (line: Line) => (line.held ? picked.has(line.i) : !off.has(line.i));
  const toggle = (line: Line) =>
    line.held
      ? setPicked((set) => flip(set, line.i))
      : setOff((set) => flip(set, line.i));
  const setAll = (group: Line[], to: boolean) => {
    const held = group.filter((line) => line.held).map((line) => line.i);
    const mine = group.filter((line) => !line.held).map((line) => line.i);
    if (held.length)
      setPicked((set) => {
        const next = new Set(set);
        for (const i of held) to ? next.add(i) : next.delete(i);
        return next;
      });
    if (mine.length)
      setOff((set) => {
        const next = new Set(set);
        for (const i of mine) to ? next.delete(i) : next.add(i);
        return next;
      });
  };
  const recurrency = (line: Line, currency: string) =>
    setFixed((was) => ({ ...was, [line.i]: currency }));
  const write = () =>
    onImport(
      origin,
      fresh.filter((_, i) => !off.has(i)),
      dupes.filter((_, i) => picked.has(i)),
    );

  // Wide is the panel itself at the window's width, borrowed for as long as
  // the review is open: the reader's own width is not overwritten, and back
  // puts it where it was. Never on a phone, where the panel is the screen.
  const open = full && !phone;
  useEffect(() => {
    if (!open) return;
    setHost(card.current?.closest<HTMLElement>(".ag-chat-panel") ?? null);
    return borrowWidth("100vw");
  }, [open]);
  const shut = useMemo(() => () => setFull(false), []);

  const rowCount = preview.fresh.length + dupes.length + preview.rejected.length;
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
  const acts = (long: boolean) => (
    <div className="ag-chat-import-acts">
      <button
        type="button"
        className="ag-chat-btn ag-chat-btn-on"
        disabled={busy || !origin || !count}
        onClick={write}
      >
        {t(long ? "chat.import_button_long" : "chat.import_button", { n: count })}
      </button>
      <button type="button" className="ag-chat-btn" disabled={busy} onClick={onDiscard}>
        {t(long ? "chat.import_cancel_file" : "chat.import_cancel")}
      </button>
    </div>
  );
  const safe = <p className="ag-chat-hint">{t("chat.import_safe")}</p>;
  const warnLine = lines.flagged.length > 0 && (
    <p className="ag-chat-import-warn">
      {t("chat.import_warn_line", { n: lines.flagged.length })}
    </p>
  );
  const verb = useVerb();

  return (
    <section ref={card} className="ag-chat-import" aria-label={preview.filename}>
      <div className="ag-chat-import-head">
        <p>
          <Glyph name="attach" size={14} />
          {t("chat.import_preview", {
            filename: preview.filename,
            label: preview.label,
          })}
        </p>
        {!phone && rowCount > 0 && (
          <button type="button" className="ag-chat-btn" onClick={() => setFull(true)}>
            <Glyph name="fullscreen" size={14} />
            {t("chat.import_review")}
          </button>
        )}
      </div>

      <Counts
        ready={lines.ready.length}
        flagged={lines.flagged.length}
        held={dupes.length}
        rejected={preview.rejected.length}
      />

      {phone ? (
        <ul className="ag-chat-ops">
          {[...lines.flagged, ...lines.ready, ...lines.duplicates].map((line) => (
            <Op
              key={`${line.held}-${line.i}`}
              line={line}
              on={on(line)}
              onToggle={() => toggle(line)}
              choices={choices}
              onCurrency={(currency) => recurrency(line, currency)}
            />
          ))}
        </ul>
      ) : (
        fresh.length > 0 && (
          <table className="ag-chat-rows ag-chat-sample">
            <thead>
              <tr>
                <th>{t("import.col_date")}</th>
                <th>{t("chat.import_col_operation")}</th>
                <th className="ag-chat-num">{t("chat.import_col_total")}</th>
              </tr>
            </thead>
            <tbody>
              {fresh.slice(0, 3).map((row, i) => (
                <tr key={`${row.date}-${row.ticker}-${i}`}>
                  <td>{calendarDay(row.date)}</td>
                  <td>
                    {/* Every ticker on screen is a logo and a link to its page —
                        in a chat bubble as anywhere else in the app. */}
                    {verb(row.action)} <TickerCell ticker={row.ticker} />
                  </td>
                  <td className="ag-chat-num">
                    {figure(total(row), 2)} {row.currency}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}

      {warnLine}

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

      {phone && preview.rejected.length > 0 && (
        <details className="ag-chat-tier">
          <summary>{t("chat.import_rejected", { n: preview.rejected.length })}</summary>
          <ul className="ag-chat-skipped">
            {preview.rejected.map((row, i) => (
              <li key={i}>
                <b>{row.ticker}</b> {row.why}
              </li>
            ))}
          </ul>
        </details>
      )}
      {phone && preview.skipped.length > 0 && (
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

      {!phone && rowCount > 3 && (
        <button
          type="button"
          className="ag-chat-link ag-chat-review-open"
          onClick={() => setFull(true)}
        >
          {t("chat.import_see_all", { n: rowCount })}
        </button>
      )}

      {open ? null : brokerBlock}
      {safe}
      {acts(false)}
      {open &&
        host &&
        createPortal(
          <Wide
            preview={preview}
            lines={lines}
            on={on}
            onToggle={toggle}
            onAll={setAll}
            choices={choices}
            onCurrency={recurrency}
            onClose={shut}
            side={
              <>
                <Summary rows={chosen} />
                {brokerBlock}
                {acts(true)}
                {safe}
              </>
            }
          />,
          host,
        )}
      {/* Beside the buttons that just went grey, which is where the eye is
          after pressing one: a batch of a few hundred rows is a few seconds
          of prices and dedupe, and nothing else on the card moves. */}
      {importing && <Status label={t("chat.work_importing", { n: count })} />}
    </section>
  );
}
