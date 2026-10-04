/**
 * The reader's brief: what the daily card tells them each day, written on the
 * card it shapes.
 *
 * One text, a line per thing — "the biggest moves in my portfolio", "next
 * week's events", "what insiders at my companies did", "review my exit
 * criteria". The card answers it line by line, a section each, in place of
 * its default sections (`/daily/brief`, `chat/daily.py`). The chat files the
 * same brief when asked ("cada mañana dime…"); this is where it is read whole
 * and rewritten.
 *
 * Every save is read back with what the card will look at for it: the server
 * plans the words into fetches there and then (indices, whose results, which
 * symbols, events, insiders, exits, headlines, 8-Ks, big investors), and the
 * editor says so under the box.
 * That line is how a reader finds out what "mírame la bolsa" was understood
 * as before the first card, not after it. A plan the keyword rules made
 * because no model answered says that too.
 *
 * Templates add a line rather than save: the reader sees the words that will
 * be kept and can make them theirs first. Every wait draws a status line (a
 * save may call a model for a few seconds).
 */

import { useEffect, useId, useRef, useState } from "react";
import { ApiError, get, send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Status } from "../../ui/Status";
import { Glyph } from "../../chat/icons";
import { TickerCell } from "./ui";
import type { Translate } from "./format";
import "./brief.css";

export type BriefPlan = {
  markets: string[];
  earnings: "book" | "named" | "large" | null;
  symbols: string[];
  topics: string[];
  by: "model" | "rules";
};

export type Brief = {
  /** Empty with none: the card is the default one. */
  text: string;
  plan: BriefPlan | null;
  /** Memory off: the brief is kept but the card reads none of it. */
  enabled: boolean;
  max_chars: number;
  max_lines: number;
};

/** The market groups a plan names, in the reader's language. */
const GROUPS: Record<string, string> = {
  core: "home.routine_group_core",
  us: "home.routine_group_us",
  europe: "home.routine_group_europe",
  spain: "home.routine_group_spain",
  asia: "home.routine_group_asia",
  rates: "home.routine_group_rates",
  commodities: "home.routine_group_commodities",
  crypto: "home.routine_group_crypto",
};

const EARNINGS: Record<NonNullable<BriefPlan["earnings"]>, string> = {
  book: "home.routine_earn_book",
  named: "home.routine_earn_named",
  large: "home.routine_earn_large",
};

const TOPICS: Record<string, string> = {
  events: "home.routine_topic_events",
  insiders: "home.routine_topic_insiders",
  exits: "home.routine_topic_exits",
  news: "home.routine_topic_news",
  filings: "home.routine_topic_filings",
  holders: "home.routine_topic_holders",
};

/** Starting points: a chip label, and the line it adds to the brief. */
export const TEMPLATES: { id: string; label: string; line: string }[] = [
  "moves",
  "events",
  "results",
  "insiders",
  "news",
  "filings",
  "holders",
  "exits",
  "proposal",
  "indices",
  "macro",
].map((id) => ({
  id,
  label: `home.routine_tpl_${id}`,
  line: `home.routine_tpl_${id}_text`,
}));

/**
 * What a plan looks at, as words: the market groups, whose results, then the
 * topics. Symbols are drawn apart, as ticker cells. Empty when the plan
 * fetches nothing of its own — the card answers from the reader's book.
 */
export function planWords(plan: BriefPlan, t: Translate): string[] {
  const out = plan.markets.flatMap((g) => (GROUPS[g] ? [t(GROUPS[g])] : []));
  if (plan.earnings) out.push(t(EARNINGS[plan.earnings]));
  out.push(...plan.topics.flatMap((c) => (TOPICS[c] ? [t(TOPICS[c])] : [])));
  return out;
}

/** The sentence a refused save earns. */
export function failureKey(failure: unknown): string {
  if (failure instanceof ApiError) {
    if (failure.status === 409 && failure.detail.startsWith("home."))
      return failure.detail;
    if (failure.status === 422) return "home.brief_unfit";
    if (failure.status === 429) return "home.brief_busy";
  }
  return "home.brief_error";
}

/** The lines a brief has: what the card makes a section of. */
export function linesIn(text: string): number {
  return text.split("\n").filter((line) => line.trim()).length;
}

/**
 * A template's line onto the brief: a line of its own after what is there,
 * and nothing when the brief already says it.
 */
export function withLine(current: string, line: string): string {
  const said = current.replace(/\s+$/, "");
  if (!said.trim()) return line;
  if (said.split("\n").some((have) => have.trim() === line)) return said;
  return `${said}\n${line}`;
}

function Plan({ plan }: { plan: BriefPlan }) {
  const t = useT();
  const words = planWords(plan, t);
  const empty = !words.length && !plan.symbols.length;
  return (
    <div className="hm-br-plan">
      <span>
        {empty
          ? t("home.brief_plan_book")
          : t("home.brief_plan", { what: words.join(" · ") })}
      </span>
      {plan.symbols.length > 0 ? (
        <span className="hm-br-symbols">
          {plan.symbols.map((symbol) => (
            <TickerCell key={symbol} ticker={symbol} name={false} />
          ))}
        </span>
      ) : null}
      {plan.by === "rules" && !empty ? (
        <span className="hm-br-plan-rules">{t("home.brief_plan_rules")}</span>
      ) : null}
    </div>
  );
}

/** Past this share of the ceiling the box counts what is left. */
const COUNT_FROM = 0.8;

/**
 * The editor, in the card's place. `onClose(changed)` tells the card whether
 * the brief changed, so it can write the card for it there and then.
 */
export function BriefEditor({ onClose }: { onClose: (changed: boolean) => void }) {
  const t = useT();
  const [read, setRead] = useState<Brief | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [draft, setDraft] = useState("");
  const [working, setWorking] = useState<"saving" | "resetting" | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);
  const [understood, setUnderstood] = useState(false);
  const [asking, setAsking] = useState(false);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const titleId = useId();
  const countId = useId();
  const errorId = useId();

  useEffect(() => {
    let alive = true;
    get<Brief>("/daily/brief").then(
      (got) => {
        if (!alive) return;
        setRead(got);
        setDraft(got.text);
      },
      () => alive && setLoadFailed(true),
    );
    return () => {
      alive = false;
    };
  }, []);

  const said = draft.trim();
  const lines = linesIn(draft);
  const tooMany = read ? lines > read.max_lines : false;
  const unchanged = read ? said === read.text.trim() : true;

  const save = async () => {
    if (!read || !said || tooMany || working) return;
    if (unchanged) {
      onClose(changed);
      return;
    }
    setWorking("saving");
    setFailed(null);
    try {
      const saved = await send<Brief>("PUT", "/daily/brief", { text: said });
      setRead(saved);
      setDraft(saved.text);
      setChanged(true);
      setUnderstood(true);
    } catch (failure) {
      setFailed(failureKey(failure));
    } finally {
      setWorking(null);
    }
  };

  const reset = async () => {
    setAsking(false);
    setWorking("resetting");
    setFailed(null);
    try {
      await send("DELETE", "/daily/brief");
      onClose(true);
    } catch {
      setFailed("home.brief_error");
      setWorking(null);
    }
  };

  const counting = read ? draft.length >= read.max_chars * COUNT_FROM : false;
  const described = [counting ? countId : "", failed ? errorId : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <section className="hm-br" aria-labelledby={titleId}>
      <div className="hm-br-head">
        <h3 id={titleId} className="hm-br-title">
          {t("home.brief_title")}
        </h3>
        <button
          type="button"
          className="hm-icon-btn"
          title={t("home.brief_close")}
          aria-label={t("home.brief_close")}
          onClick={() => onClose(changed)}
        >
          <Glyph name="close" size={16} />
        </button>
      </div>
      <p className="hm-note">{t("home.brief_explain")}</p>
      {!read && !loadFailed ? <Status label={t("home.brief_loading")} /> : null}
      {loadFailed ? <p className="hm-note">{t("home.brief_load_error")}</p> : null}
      {read ? (
        <form
          className="hm-br-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          {/* Off is not empty: the brief is kept and simply not read. */}
          {!read.enabled ? (
            <p className="hm-note hm-br-off">{t("home.brief_off")}</p>
          ) : null}
          <div className="hm-br-field">
            <textarea
              ref={box}
              className="hm-br-box"
              value={draft}
              maxLength={read.max_chars}
              rows={4}
              aria-label={t("home.brief_label")}
              aria-describedby={described || undefined}
              aria-invalid={failed || tooMany ? true : undefined}
              placeholder={t("home.brief_placeholder")}
              autoFocus
              onChange={(event) => {
                setDraft(event.target.value);
                setUnderstood(false);
              }}
              onKeyDown={(event) => {
                // Enter alone is a new line: the brief is a list.
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            {counting || tooMany ? (
              <span id={countId} className="hm-br-count" aria-live="polite">
                {tooMany
                  ? t("home.brief_too_many", { max: read.max_lines })
                  : t("home.brief_chars", { n: draft.length, max: read.max_chars })}
              </span>
            ) : null}
          </div>
          <div className="hm-br-templates">
            <span className="hm-caption">{t("home.brief_templates")}</span>
            {TEMPLATES.map((tpl) => (
              <button
                key={tpl.id}
                type="button"
                className="hm-br-chip"
                onClick={() => {
                  setDraft((was) => withLine(was, t(tpl.line)));
                  setUnderstood(false);
                  box.current?.focus();
                }}
              >
                {t(tpl.label)}
              </button>
            ))}
          </div>
          {read.plan && unchanged ? (
            <div className="hm-br-read">
              {understood ? (
                <p className="hm-br-got">{t("home.brief_understood")}</p>
              ) : null}
              <Plan plan={read.plan} />
            </div>
          ) : null}
          {working === "saving" ? (
            <Status label={t("home.brief_saving")} />
          ) : working === "resetting" ? (
            <Status label={t("home.brief_resetting")} />
          ) : asking ? (
            <div
              className="hm-br-ask"
              role="group"
              aria-label={t("home.brief_reset_ask")}
            >
              <span className="hm-caption">{t("home.brief_reset_ask")}</span>
              <button
                type="button"
                className="ag-btn hm-br-danger"
                autoFocus
                onClick={() => void reset()}
              >
                {t("home.brief_reset_yes")}
              </button>
              <button type="button" className="ag-btn" onClick={() => setAsking(false)}>
                {t("home.brief_cancel")}
              </button>
            </div>
          ) : (
            <div className="hm-br-acts">
              <button
                type="submit"
                className="ag-btn hm-br-primary"
                disabled={!said || tooMany}
              >
                {unchanged && read.text ? t("home.brief_done") : t("home.brief_save")}
              </button>
              {read.text ? (
                <button
                  type="button"
                  className="ag-btn hm-br-quiet"
                  onClick={() => setAsking(true)}
                >
                  {t("home.brief_reset")}
                </button>
              ) : null}
            </div>
          )}
          {failed ? (
            <p id={errorId} className="hm-note hm-br-failed" role="alert">
              {t(failed, { max: read.max_lines })}
            </p>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}
