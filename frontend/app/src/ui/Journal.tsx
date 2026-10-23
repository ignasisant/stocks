/**
 * The decision journal, drawn: what the app proposed, on which figures, and
 * what became of it (`GET /journal`, `chat/journal.py`).
 *
 * Two places read it. Perfil's "Diario" tab lists the whole of it with
 * filters; a ticker page's header carries a small chip that opens one name's
 * entries in a side panel, so the page's own figures keep the main column.
 * Both draw the same rows from here.
 *
 * A proposal is the app's own words and the app's own numbers, and none is
 * editable — a record the reader could rewrite would stop being a record of
 * what was said. The one thing in it that is the reader's is an exit rule:
 * the line they drew for a holding, written through the assistant, which they
 * may retire (it stays, as retired) but not rewrite.
 * Entries that replaced each other are linked both ways, and a link scrolls
 * to the entry it names when that entry is in the list.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { get, send } from "../shell/api";
import { askAssistant } from "../shell/assistant";
import { useLang, useT } from "../shell/i18n";
import { Link } from "../shell/router";
import { useCurrency } from "../shell/session";
import { TickerCell } from "../shell/tickers";
import { useApi } from "../shell/useApi";
import { usePresence, useSwipeDismiss } from "../shell/useSheet";
import { Chip, type Tone } from "./Kpi";
import "./journal.css";
import { formatter } from "../shell/numbers";

export type JournalState =
  "open" | "followed" | "declined" | "lapsed" | "hit" | "retired";
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
  /** "chat" for a card answered, "ledger:<date>" for a trade that settled it. */
  settled?: string;
  /** The price read back: "then" (close on the first day shown), "d30" and
   * "d90" (% move since). Absent until a mark is due. */
  outcome?: Record<string, number>;
};

/** What became of the proposals, counted over the whole journal. */
export type JournalRecord = {
  proposed: number;
  open: number;
  followed: number;
  declined: number;
  lapsed: number;
  /** Moves whose price has been read back, and those that went their way. */
  marked?: number;
  its_way?: number;
  by_source: Record<string, Record<string, number>>;
};

export type Journal = {
  entries: JournalEntry[];
  total: number;
  states: Record<string, number>;
  record: JournalRecord;
};

/** The day a trade in the book settled the entry, or null. */
export function settledOn(entry: JournalEntry): string | null {
  const settled = entry.settled ?? "";
  return settled.startsWith("ledger:") ? settled.slice("ledger:".length) : null;
}

export const STATES: JournalState[] = [
  "open",
  "followed",
  "declined",
  "lapsed",
  "hit",
  "retired",
];

/** The exit rules a criterion entry can carry (`journal.CRITERION_RULES`). */
export const RULES = [
  "below",
  "drawdown_cost",
  "drawdown_high",
  "weight_above",
  "revenue_growth_below",
  "gross_margin_below",
  "operating_margin_below",
  "ceo_change",
  "guidance_cut",
  "dividend_cut",
];
export const SOURCES: JournalSource[] = ["daily", "review", "chat"];

export function getJournal(params: { ticker?: string } = {}): Promise<Journal> {
  return get<Journal>(
    "/journal",
    params.ticker ? { ticker: params.ticker } : undefined,
  );
}

/** Take down one exit rule; it stays in the journal as retired. */
export function retireRule(id: string): Promise<void> {
  return send<void>("DELETE", `/journal/criteria/${encodeURIComponent(id)}`);
}

/** Whether `entry` is an exit rule still standing (armed or already met). */
export function liveRule(entry: JournalEntry): boolean {
  return (
    entry.type === "criterion" && (entry.state === "open" || entry.state === "hit")
  );
}

/**
 * An exit rule in words: "a close at or below 95.00", "a 30 % loss on cost",
 * "an operating margin under 15 %, 2 quarters running", "a CEO change".
 * A price prints with two decimals, a percent with what it was given.
 */
export function ruleText(
  t: (key: string, vars?: Record<string, string | number>) => string,
  entry: JournalEntry,
  lang: string,
): string {
  const rule = String(entry.snapshot.rule ?? entry.action);
  const raw = entry.snapshot.level;
  const level =
    typeof raw === "number" && Number.isFinite(raw)
      ? formatter(lang, {
          minimumFractionDigits: rule === "below" ? 2 : 0,
          maximumFractionDigits: rule === "below" ? 2 : 1,
        }).format(raw)
      : String(raw ?? "");
  if (!RULES.includes(rule)) return `${rule} ${level}`;
  const words = t(`journal.crit_${rule}`, { level });
  const run = Number(entry.snapshot.quarters ?? 1);
  return run > 1 ? t("journal.crit_run", { rule: words, n: run }) : words;
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

/** The marks the price was read back at, in day order, signed as they print. */
export function priceMarks(
  entry: JournalEntry,
  lang: string,
): { days: number; shown: string }[] {
  const outcome = entry.outcome ?? {};
  return [30, 90].flatMap((days) => {
    const pct = outcome[`d${days}`];
    if (typeof pct !== "number" || !Number.isFinite(pct)) return [];
    const shown = formatter(lang, {
      maximumFractionDigits: 1,
      signDisplay: "exceptZero",
    }).format(pct);
    return [{ days, shown: `${shown} %` }];
  });
}

/** The passage an event rule was met on, with where it was read. */
export function MetOn({ entry }: { entry: JournalEntry }) {
  const t = useT();
  const quote = entry.snapshot.quote;
  if (entry.type !== "criterion" || typeof quote !== "string" || !quote) return null;
  const where = [entry.snapshot.source, entry.snapshot.source_day]
    .filter((part) => typeof part === "string" && part)
    .join(" · ");
  return (
    <div className="ag-jr-group">
      <h3 className="ag-jr-h">{t("journal.met_on")}</h3>
      <p className="ag-jr-quote">“{quote}”</p>
      {where ? <p className="ag-jr-sub">{where}</p> : null}
    </div>
  );
}

function PriceSince({ entry }: { entry: JournalEntry }) {
  const t = useT();
  const marks = priceMarks(entry, useLang());
  if (!marks.length) return null;
  return (
    <div className="ag-jr-group">
      <h3 className="ag-jr-h">{t("journal.since")}</h3>
      <dl className="ag-jr-facts">
        {marks.map(({ days, shown }) => (
          <div key={days} className="ag-jr-fact">
            <dt>{t("journal.since_days", { days })}</dt>
            <dd>{shown}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
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
  if (entry.type === "criterion") {
    // The level is already in the rule's words; what is left is where the
    // measure stood the day it was met — a price, or a percent of the rest —
    // or, for a fundamental rule not met yet, the last quarter it read.
    const format = entry.snapshot.rule === "below" ? "price" : "percent";
    const hit = figure(entry.snapshot.hit_value, format, lang, currency);
    if (hit !== null) return [["hit_value", hit] as const];
    const last = figure(entry.snapshot.value, "percent", lang, currency);
    return last === null ? [] : [["last_value", last] as const];
  }
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
  const lang = useLang();
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
          {(entry.type === "criterion" ? ruleText(t, entry, lang) : "") ||
            entry.line ||
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
          <MetOn entry={entry} />
          <PriceSince entry={entry} />
          {entry.evidence ? (
            <div className="ag-jr-group">
              <h3 className="ag-jr-h">
                {entry.type === "criterion"
                  ? t("journal.thesis")
                  : t("journal.evidence")}
              </h3>
              <p className="ag-jr-quote">{entry.evidence}</p>
            </div>
          ) : null}
          <p className="ag-jr-sub">
            {entry.last !== entry.day
              ? t("journal.span", { from: entry.day, to: entry.last })
              : entry.day}
            {" · "}
            {settledOn(entry)
              ? t("journal.settled_ledger", { date: settledOn(entry) ?? "" })
              : t(`journal.state_${entry.state}_help`)}
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
 * all while the journal is loading or failed. With nothing on this name the
 * chip shows only for a holding, as "Exit rules": the panel is where the
 * reader writes theirs, and a name they do not own has nothing to exit.
 */
export function JournalChip({
  ticker,
  held = false,
}: {
  ticker: string;
  held?: boolean;
}) {
  const t = useT();
  const query = useApi(() => getJournal({ ticker }), [ticker]);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const presence = usePresence(open);
  if (query.state !== "loaded" || (query.data.total === 0 && !held)) return null;
  return (
    <>
      <button
        type="button"
        className="ag-jr-chip"
        aria-haspopup="dialog"
        title={t("journal.chip_help", { ticker })}
        onClick={() => setOpen(true)}
      >
        {query.data.total
          ? t("journal.chip", { n: query.data.total })
          : t("journal.chip_none")}
      </button>
      {presence.mounted ? (
        <JournalPanel
          ticker={ticker}
          journal={query.data}
          onClose={close}
          onChange={query.reload}
          leaving={presence.leaving}
        />
      ) : null}
    </>
  );
}

/**
 * The reader's exit rules on this name, at the panel's head: each one in
 * words with its state and a way to retire it, and a way to write them with
 * the assistant — which drafts them as a card the reader approves, so a rule
 * is never saved that they did not see.
 */
export function RulesBlock({
  ticker,
  rules,
  onChange,
  onAsk,
}: {
  ticker: string;
  rules: JournalEntry[];
  onChange: () => void;
  onAsk: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const [busy, setBusy] = useState<string | null>(null);
  // Retiring asks twice: the first press turns the button into its
  // confirmation, beside a Cancel, so a stray tap never takes a rule down.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const retire = (id: string) => {
    setConfirming(null);
    setBusy(id);
    setFailed(false);
    retireRule(id)
      .then(onChange)
      .catch(() => setFailed(true))
      .finally(() => setBusy(null));
  };
  return (
    <section className="ag-jr-rules" aria-labelledby="ag-jr-rules-h">
      <h3 id="ag-jr-rules-h" className="ag-jr-h">
        {t("journal.criteria_title")}
      </h3>
      {rules.length ? (
        <ul className="ag-jr-rule-list">
          {rules.map((rule) => {
            const words = ruleText(t, rule, lang);
            return (
              <li key={rule.id} className="ag-jr-rule">
                <span className="ag-jr-rule-text">{words}</span>
                <StateBadge state={rule.state} />
                {confirming === rule.id ? (
                  <>
                    <button
                      type="button"
                      className="ag-jr-retire ag-jr-retire-confirm"
                      disabled={busy !== null}
                      aria-label={`${t("journal.criteria_confirm")}: ${words}`}
                      onClick={() => retire(rule.id)}
                    >
                      {t("journal.criteria_confirm")}
                    </button>
                    <button
                      type="button"
                      className="ag-jr-retire"
                      onClick={() => setConfirming(null)}
                    >
                      {t("journal.criteria_cancel")}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="ag-jr-retire"
                    disabled={busy !== null}
                    aria-label={`${t("journal.criteria_retire")}: ${words}`}
                    onClick={() => setConfirming(rule.id)}
                  >
                    {t("journal.criteria_retire")}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="ag-jr-rules-empty">{t("journal.criteria_empty")}</p>
      )}
      {failed ? (
        <p className="ag-jr-rules-error" role="alert">
          {t("journal.criteria_failed")}
        </p>
      ) : null}
      <button
        type="button"
        className="ag-jr-propose"
        onClick={() => {
          askAssistant(t("journal.criteria_prompt", { ticker }));
          onAsk();
        }}
      >
        {rules.length ? t("journal.criteria_edit") : t("journal.criteria_propose")}
      </button>
    </section>
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
  onChange,
  leaving,
}: {
  ticker: string;
  journal: Journal;
  onClose: () => void;
  onChange: () => void;
  leaving: boolean;
}) {
  const t = useT();
  const shut = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLElement>(null);
  // Thrown back off the edge it came in from, by a finger.
  useSwipeDismiss(sheet, "x", onClose);

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
      data-leaving={leaving ? "" : undefined}
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
        <div className="ag-jr-panel-body">
          <RulesBlock
            ticker={ticker}
            rules={journal.entries.filter(liveRule)}
            onChange={onChange}
            onAsk={onClose}
          />
          {/* A live rule is drawn above; a retired one stays a row below. */}
          <JournalList
            entries={journal.entries.filter((entry) => !liveRule(entry))}
            showTicker={false}
          />
        </div>
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
