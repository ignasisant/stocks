/**
 * The decision journal, drawn: what the app proposed, on which figures, and
 * what became of it (`GET /journal`, `chat/journal.py`).
 *
 * Two places read it. Perfil's "Diario" tab lists the whole of it with
 * filters; a ticker page's header carries a small chip that opens one name's
 * entries in a side panel, so the page's own figures keep the main column.
 * Both draw the same rows from here.
 *
 * Every entry is the app's own words and the app's own numbers. Nothing in
 * it is the reader's: no field asks why they bought, and none is editable — a
 * record the reader could rewrite would stop being a record of what was said.
 * Entries that replaced each other are linked both ways, and a link scrolls
 * to the entry it names when that entry is in the list.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { get } from "../shell/api";
import { useLang, useT } from "../shell/i18n";
import { Link } from "../shell/router";
import { useCurrency } from "../shell/session";
import { TickerCell } from "../shell/tickers";
import { useApi } from "../shell/useApi";
import { Chip, type Tone } from "./Kpi";
import "./journal.css";
import { formatter } from "../shell/numbers";

export type JournalState = "open" | "followed" | "declined" | "lapsed";
export type JournalSource = "daily" | "review" | "chat";

export type JournalEntry = {
  id: string;
  type: "proposal" | "criterion" | "event";
  source: JournalSource;
  action: string;
  subject: string;
  ticker: string;
  line: string;
  reasons: string[];
  snapshot: Record<string, number | string | boolean | null>;
  evidence: string;
  state: JournalState;
  day: string;
  last: string;
  times: number;
  links: string[];
  updated: string;
};

export type Journal = {
  entries: JournalEntry[];
  total: number;
  states: Record<string, number>;
};

export const STATES: JournalState[] = ["open", "followed", "declined", "lapsed"];
export const SOURCES: JournalSource[] = ["daily", "review", "chat"];

export function getJournal(params: { ticker?: string } = {}): Promise<Journal> {
  return get<Journal>(
    "/journal",
    params.ticker ? { ticker: params.ticker } : undefined,
  );
}

/** Sell red, buy green, the rest a caution: the colour of the move proposed. */
function actionTone(action: string): Tone {
  switch (action) {
    case "sell":
    case "unwatch":
      return "down";
    case "add":
    case "buy":
    case "rebuy":
    case "watch":
      return "up";
    case "alert":
    case "consider":
    case "review":
    case "stay":
      return "flat";
    default:
      return "warn";
  }
}

// ------------------------------------------------------------------ figures

type Format = "score" | "fraction" | "percent" | "pp" | "money" | "price" | "text";

/**
 * The snapshot keys worth a line, in the order they read, each with how it
 * prints. A key not listed is plumbing (`kind`, `currency`, `held`) and is
 * not drawn. `pnl_pct` is a fraction where the Review page wrote it and a
 * percentage where a card signal did — the source decides.
 */
const FACTS: [string, Format][] = [
  ["quality", "score"],
  ["cheapness", "score"],
  ["weight", "fraction"],
  ["target_weight", "fraction"],
  ["weight_pct", "percent"],
  ["pnl_pct", "percent"],
  ["value", "money"],
  ["loss", "money"],
  ["gain_ytd", "money"],
  ["offset", "money"],
  ["price", "price"],
  ["level", "price"],
  ["above", "price"],
  ["below", "price"],
  ["gap_pct", "percent"],
  ["own_pct", "percent"],
  ["index_pct", "percent"],
  ["tilt_pp", "pp"],
  ["sector", "text"],
  ["sell_date", "text"],
  ["clear_date", "text"],
];

function figure(
  value: number | string | boolean | null | undefined,
  format: Format,
  lang: string,
  currency: string,
): string | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "string") return value || null;
  if (!Number.isFinite(value)) return null;
  const num = (n: number, digits: number) =>
    formatter(lang, { maximumFractionDigits: digits }).format(n);
  switch (format) {
    case "score":
      return String(Math.round(value));
    case "fraction":
      return `${num(value * 100, 1)} %`;
    case "percent":
      return `${num(value, 1)} %`;
    case "pp":
      return `${value > 0 ? "+" : ""}${num(value, 1)} pp`;
    case "money":
      try {
        return formatter(lang, {
          style: "currency",
          currency,
          maximumFractionDigits: 0,
        }).format(value);
      } catch {
        return `${Math.round(value)} ${currency}`;
      }
    case "price":
      return num(value, 2);
    default:
      return String(value);
  }
}

/**
 * The snapshot's figures as they print, in `FACTS` order. The currency is the
 * one the figures were taken in when the snapshot says so, else the book's.
 */
export function factRows(
  entry: JournalEntry,
  lang: string,
  base: string,
): (readonly [string, string])[] {
  const currency =
    typeof entry.snapshot.currency === "string" && entry.snapshot.currency
      ? entry.snapshot.currency
      : base;
  return FACTS.flatMap(([key, format]) => {
    const fmt = key === "pnl_pct" && entry.source === "review" ? "fraction" : format;
    const shown = figure(entry.snapshot[key], fmt, lang, currency);
    return shown === null ? [] : [[key, shown] as const];
  });
}

function Figures({ entry }: { entry: JournalEntry }) {
  const t = useT();
  const rows = factRows(entry, useLang(), useCurrency());
  if (!rows.length) return null;
  return (
    <div className="ag-jr-group">
      <h3 className="ag-jr-h">{t("journal.figures")}</h3>
      <dl className="ag-jr-facts">
        {rows.map(([key, shown]) => (
          <div key={key} className="ag-jr-fact">
            <dt>{t(`journal.fact_${key}`)}</dt>
            <dd>{shown}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Whether `other` came first: the earlier entry is the one replaced. */
function older(other: JournalEntry, entry: JournalEntry): boolean {
  return other.day !== entry.day
    ? other.day < entry.day
    : other.updated < entry.updated;
}

/** A reason code in the words of the surface that gave it. */
function reasonLabel(t: ReturnType<typeof useT>, entry: JournalEntry, code: string) {
  if (entry.source === "review") return t(`review.reason_${code}`);
  if (entry.source === "daily") return t(`journal.kind_${code}`);
  return code;
}

// --------------------------------------------------------------------- rows

function StateBadge({ state }: { state: JournalState }) {
  const t = useT();
  return (
    <span
      className={`ag-jr-state ag-jr-state-${state}`}
      title={t(`journal.state_${state}_help`)}
    >
      {t(`journal.state_${state}`)}
    </span>
  );
}

function Row({
  entry,
  open,
  onToggle,
  byId,
  onJump,
  showTicker,
}: {
  entry: JournalEntry;
  open: boolean;
  onToggle: () => void;
  byId: Map<string, JournalEntry>;
  onJump: (id: string) => void;
  showTicker: boolean;
}) {
  const t = useT();
  const detail = `jr-${entry.id}-detail`;
  // Every row has one: "More" alone is a list of identical buttons.
  const name = `${open ? t("journal.less") : t("journal.more")}: ${t(
    `journal.action_${entry.action}`,
  )} ${entry.ticker} ${entry.day}`;
  const linked = entry.links
    .map((id) => byId.get(id))
    .filter((other): other is JournalEntry => Boolean(other));
  return (
    <li
      id={`jr-${entry.id}`}
      tabIndex={-1}
      className={open ? "ag-jr-row ag-jr-row-open" : "ag-jr-row"}
    >
      <span className="ag-jr-when">
        <span>{entry.day}</span>
        {entry.times > 1 ? (
          <span className="ag-jr-sub">{t("journal.shown", { n: entry.times })}</span>
        ) : null}
      </span>
      <span className="ag-jr-what">
        <Chip
          chip={{
            text: t(`journal.action_${entry.action}`),
            tone: actionTone(entry.action),
          }}
        />
        {showTicker && entry.ticker ? (
          <TickerCell ticker={entry.ticker} name={false} className="ag-jr-tick" />
        ) : null}
      </span>
      <span className="ag-jr-line">
        <span className="ag-jr-text">
          {entry.line ||
            entry.reasons.map((code) => reasonLabel(t, entry, code)).join(" · ") ||
            "—"}
        </span>
        <span className="ag-jr-sub">{t(`journal.source_${entry.source}`)}</span>
      </span>
      <span className="ag-jr-end">
        <StateBadge state={entry.state} />
        <button
          type="button"
          className="ag-jr-fold"
          aria-expanded={open}
          aria-controls={detail}
          aria-label={name}
          title={open ? t("journal.less") : t("journal.more")}
          onClick={onToggle}
        >
          <span className="ag-jr-chevron" aria-hidden="true" />
        </button>
      </span>
      {open ? (
        <div id={detail} className="ag-jr-detail">
          {/* Without a line of its own the row already reads its reasons. */}
          {entry.line && entry.reasons.length ? (
            <div className="ag-jr-group">
              <h3 className="ag-jr-h">{t("journal.reasons")}</h3>
              <ul className="ag-jr-reasons">
                {entry.reasons.map((code) => (
                  <li key={code}>{reasonLabel(t, entry, code)}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <Figures entry={entry} />
          {entry.evidence ? (
            <div className="ag-jr-group">
              <h3 className="ag-jr-h">{t("journal.evidence")}</h3>
              <p className="ag-jr-quote">{entry.evidence}</p>
            </div>
          ) : null}
          <p className="ag-jr-sub">
            {entry.last !== entry.day
              ? t("journal.span", { from: entry.day, to: entry.last })
              : entry.day}
            {" · "}
            {t(`journal.state_${entry.state}_help`)}
          </p>
          {linked.length ? (
            <ul className="ag-jr-links">
              {linked.map((other) => (
                <li key={other.id}>
                  <span className="ag-jr-sub">
                    {older(other, entry)
                      ? t("journal.replaces")
                      : t("journal.replaced_by")}
                  </span>
                  <button
                    type="button"
                    className="ag-jr-link"
                    onClick={() => onJump(other.id)}
                  >
                    {t(`journal.action_${other.action}`)} · {other.day}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * The rows, with their unfolded set and the links between them. A link to an
 * entry folded shut unfolds it and scrolls it into view.
 */
export function JournalList({
  entries,
  showTicker = true,
}: {
  entries: JournalEntry[];
  showTicker?: boolean;
}) {
  const byId = useMemo(() => new Map(entries.map((e) => [e.id, e])), [entries]);
  const [open, setOpen] = useState<Set<string>>(() => new Set());

  const toggle = useCallback((id: string) => {
    setOpen((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // The row is always in the list (only its detail folds), so the jump can
  // land at once. Focus goes with the eye: a keyboard reader who followed the
  // link is now on the entry it named, not still on the link.
  const onJump = useCallback((id: string) => {
    setOpen((was) => new Set(was).add(id));
    const row = document.getElementById(`jr-${id}`);
    if (!row) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    row.focus({ preventScroll: true });
    row.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
  }, []);

  return (
    <ol className="ag-jr-list">
      {entries.map((entry) => (
        <Row
          key={entry.id}
          entry={entry}
          open={open.has(entry.id)}
          onToggle={() => toggle(entry.id)}
          byId={byId}
          onJump={onJump}
          showTicker={showTicker}
        />
      ))}
    </ol>
  );
}

// -------------------------------------------------------- the ticker's chip

/**
 * "Diario · 3" in a ticker's header, and the side panel it opens. Nothing at
 * all while the journal is loading, failed, or has nothing on this name: a
 * chip that says "0" is a control with nothing behind it.
 */
export function JournalChip({ ticker }: { ticker: string }) {
  const t = useT();
  const query = useApi(() => getJournal({ ticker }), [ticker]);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  if (query.state !== "loaded" || query.data.total === 0) return null;
  return (
    <>
      <button
        type="button"
        className="ag-jr-chip"
        aria-haspopup="dialog"
        title={t("journal.chip_help", { ticker })}
        onClick={() => setOpen(true)}
      >
        {t("journal.chip", { n: query.data.total })}
      </button>
      {open ? (
        <JournalPanel ticker={ticker} journal={query.data} onClose={close} />
      ) : null}
    </>
  );
}

/**
 * The side panel, portalled to the body for the same reason the Review
 * dialog is: `.ag-main` is a size container, and a container is the
 * containing block of a `position: fixed` inside it. Esc, the backdrop and
 * Close all close; focus goes to Close and back to the chip after.
 */
function JournalPanel({
  ticker,
  journal,
  onClose,
}: {
  ticker: string;
  journal: Journal;
  onClose: () => void;
}) {
  const t = useT();
  const shut = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      // Modal means modal: Tab cycles inside the panel instead of walking off
      // into the page the veil covers.
      if (event.key !== "Tab" || !sheet.current) return;
      const stops = sheet.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (!first || !last) return;
      const here = document.activeElement;
      if (event.shiftKey && (here === first || !sheet.current.contains(here))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (here === last || !sheet.current.contains(here))) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    shut.current?.focus();
    return () => before?.focus?.();
  }, []);

  const title = t("journal.panel_title", { ticker });
  return createPortal(
    <div
      className="ag-jr-veil"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        ref={sheet}
        className="ag-jr-panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="ag-jr-panel-head">
          <h2 className="ag-jr-panel-title">{title}</h2>
          <button ref={shut} type="button" className="ag-jr-close" onClick={onClose}>
            {t("journal.close")}
          </button>
        </header>
        <JournalList entries={journal.entries} showTicker={false} />
        <footer className="ag-jr-panel-foot">
          {/* Leaving the page unmounts the panel with it. */}
          <Link page="profile" params={{ tab: "journal" }} className="ag-jr-all">
            {t("journal.all")}
          </Link>
        </footer>
      </aside>
    </div>,
    document.body,
  );
}
