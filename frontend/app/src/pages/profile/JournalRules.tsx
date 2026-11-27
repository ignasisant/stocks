/**
 * Perfil → Diario, "Your rules by holding": what the book holds today, heaviest
 * first, each name with its exit and buy rules (`GET /journal/coverage`).
 *
 * The tiles count what is still to do — rules met and waiting on a decision,
 * names with no rule or without the thesis or price exit their kind needs,
 * rules due a second look, names with no buy zone — and each filters the list.
 * A row opens on its rules and what to do with each: sell or add on one that
 * was met, rework one that went stale, retire (with an Undo). Writing goes
 * through the assistant, which drafts a card the reader approves, so the
 * drafting buttons only open the chat with the right question.
 */

import { type ReactNode, useState } from "react";
import type { Coverage, CoverageRow, CoverageRule } from "../../api.gen";
import { get } from "../../shell/api";
import { askAssistant, tickerTopic } from "../../shell/assistant";
import { calendarDay } from "../../shell/dates";
import { useLang, useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { formatter } from "../../shell/numbers";
import { Link } from "../../shell/router";
import { TickerCell, useTickerProfile } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { Glyph } from "../../ui/Glyph";
import { Kpi, KpiGrid } from "../../ui/Kpi";
import { RetireNotes, rulesSubject, ruleText, useRetire } from "../../ui/Journal";
import { Inline } from "./ui";
import "./journalRules.css";

type Say = (key: string, vars?: Record<string, string | number>) => string;
type Family = CoverageRule["family"];
type Status = CoverageRow["status"];
type Filter = "all" | "hit" | "none" | "gap" | "review" | "no_buy";

const FAMILIES: Family[] = ["thesis", "price", "fundamental", "event", "buy"];
/** The bar's order: done first, then what asks for the reader. */
const BAR: Status[] = ["ok", "review", "hit", "gap", "none"];
const DAY_MS = 86_400_000;

const flagged = (rule: CoverageRule) => rule.state === "open" && rule.flag !== null;
/** No exit rule at all; buy rules alone do not cover a holding. */
const bare = (row: CoverageRow) => !row.rules.some((rule) => rule.side === "exit");
/** Read from what is missing, not the status: a met rule outranks a gap there. */
const short = (row: CoverageRow) => row.missing.length > 0;

const FILTERS: Record<Exclude<Filter, "all">, (row: CoverageRow) => boolean> = {
  hit: (row) => row.status === "hit",
  none: bare,
  gap: (row) => !bare(row) && short(row),
  review: (row) => row.rules.some(flagged),
  no_buy: (row) => !row.rules.some((rule) => rule.side === "buy"),
};

/** "a", "a and b", "a, b and c". */
function listed(t: Say, words: string[]): string {
  if (words.length < 2) return words.join("");
  return t("journal.cov_and", {
    a: words.slice(0, -1).join(", "),
    b: words[words.length - 1] ?? "",
  });
}

/** The question a missing family is drafted with; each one opens the rules form. */
export function draftKey(row: CoverageRow): string {
  const thesis = row.missing.includes("thesis");
  const price = row.missing.includes("price");
  if (bare(row) || (thesis && price)) return "journal.criteria_prompt";
  if (thesis) return "journal.thesis_prompt";
  if (price) return "journal.price_prompt";
  return "journal.entry_prompt";
}

/** What a holding still lacks, its exit families first and the buy zone after. */
function wants(row: CoverageRow): Family[] {
  const buy = row.rules.some((rule) => rule.side === "buy");
  return [...row.missing, ...(buy ? [] : (["buy"] as Family[]))];
}

function ruleWords(t: Say, rule: CoverageRule, lang: string): string {
  return ruleText(
    t,
    {
      action: rule.rule,
      snapshot: {
        rule: rule.rule,
        level: rule.level,
        quarters: rule.quarters,
        pillars: rule.pillars,
      },
    },
    lang,
  );
}

export function JournalRules({ saved }: { saved: unknown }) {
  const t = useT();
  const query = useApi(() => get("/journal/coverage"), [saved]);
  return (
    <section className="jc" aria-labelledby="jc-h">
      <div className="pr-cardbody jc-lede">
        <h3 id="jc-h" className="pr-subhead">
          {t("journal.cov_title")}
        </h3>
        <p className="pr-hint">{t("journal.cov_intro")}</p>
      </div>
      <Loaded
        query={query}
        skeleton={
          <div className="pr-cardbody">
            <Skeleton rows={5} />
          </div>
        }
      >
        {(coverage) => (
          <RulesBoard
            coverage={coverage}
            reload={query.state === "loaded" ? query.reload : () => {}}
          />
        )}
      </Loaded>
    </section>
  );
}

export function RulesBoard({
  coverage,
  reload,
}: {
  coverage: Coverage;
  reload: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<string | null>(null);
  const { gone, retire, notes } = useRetire(reload);
  const rows = coverage.rows.map((row) => ({
    ...row,
    rules: row.rules.filter((rule) => !gone.includes(rule.id)),
  }));
  const heaviest = rows.find(short);
  const profile = useTickerProfile(heaviest?.ticker ?? "");

  if (!rows.length) {
    return (
      <div className="pr-cardbody">
        <p className="pr-hint">{t("journal.cov_empty")}</p>
      </div>
    );
  }

  const total = rows.reduce((sum, row) => sum + (row.weight ?? 0), 0);
  const pct = (part: number) => (total ? Math.round((part / total) * 100) : 0);
  const weightOf = (some: CoverageRow[]) =>
    some.reduce((sum, row) => sum + (row.weight ?? 0), 0);
  const count = (key: Exclude<Filter, "all">) => rows.filter(FILTERS[key]).length;
  const covered = rows.filter((row) => !short(row) && !bare(row));
  const coveredPct = Math.round(coverage.summary.covered * 100);
  const hitRules = rows.reduce(
    (sum, row) => sum + row.rules.filter((rule) => rule.state === "hit").length,
    0,
  );
  const reviewRules = rows.reduce(
    (sum, row) => sum + row.rules.filter(flagged).length,
    0,
  );
  const need = rows.filter(short);

  const pick = (key: Filter) =>
    setFilter((now) => (now === key && key !== "all" ? "all" : key));
  const tile = (
    key: Exclude<Filter, "all">,
    value: number,
    note: string,
    tone: "warn" | "down" | null,
  ) => (
    <Kpi
      label={t(`journal.cov_${key}`)}
      value={value}
      valueTone={value && tone ? tone : undefined}
      note={note}
      pressed={filter === key}
      onPress={() => pick(key)}
    />
  );

  const segments = BAR.map((status) => ({
    status,
    rows: rows.filter((row) => row.status === status && row.weight),
  })).filter((seg) => seg.rows.length);
  const status = (key: Status) => t(`journal.cov_status_${key}`);
  const shown = filter === "all" ? rows : rows.filter(FILTERS[filter]);

  return (
    <div className="pr-cardbody jc-board">
      <div role="group" aria-label={t("journal.cov_filter_group")}>
        <KpiGrid>
          <Kpi
            label={t("journal.cov_covered")}
            value={`${coveredPct} %`}
            valueTone={coveredPct < 80 ? "warn" : "up"}
            note={t("journal.cov_covered_note", {
              n: covered.length,
              total: rows.length,
            })}
          />
          {tile("hit", hitRules, t("journal.cov_hit_note"), "warn")}
          {tile(
            "none",
            count("none"),
            t("journal.cov_none_note", {
              pct: pct(weightOf(rows.filter(FILTERS.none))),
            }),
            "down",
          )}
          {tile("gap", count("gap"), t("journal.cov_gap_note"), "down")}
          {tile(
            "review",
            reviewRules,
            t("journal.cov_review_note", { n: count("review"), total: rows.length }),
            "warn",
          )}
          {tile(
            "no_buy",
            count("no_buy"),
            t("journal.cov_no_buy_note", { total: rows.length }),
            null,
          )}
        </KpiGrid>
      </div>
      <p className="ag-sr">{t("journal.cov_covered_help")}</p>

      {segments.length ? (
        <>
          <div
            className="jc-bar"
            role="img"
            aria-label={segments
              .map((seg) => `${status(seg.status)} ${pct(weightOf(seg.rows))} %`)
              .join(", ")}
          >
            {segments.flatMap((seg) =>
              seg.rows.map((row) => (
                <i
                  key={row.ticker}
                  data-status={seg.status}
                  style={{ flexGrow: row.weight ?? 0 }}
                />
              )),
            )}
          </div>
          <ul className="jc-legend" aria-hidden="true">
            {segments.map((seg) => (
              <li key={seg.status} data-status={seg.status}>
                {status(seg.status)} <b>{pct(weightOf(seg.rows))} %</b>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {heaviest ? (
        <div className="jc-next">
          <p>
            <Inline
              text={t("journal.cov_next_note", {
                n: need.length,
                pct: pct(weightOf(need)),
              })}
            />
          </p>
          <button
            type="button"
            className="pr-btn pr-btn-p jc-cta"
            onClick={() =>
              askAssistant(
                t(draftKey(heaviest), {
                  ticker: rulesSubject(heaviest.ticker, profile?.name ?? ""),
                }),
                { topic: tickerTopic(heaviest.ticker) },
              )
            }
          >
            <Glyph name="spark" size={14} />
            {t("journal.cov_next", { ticker: heaviest.ticker })}
          </button>
        </div>
      ) : null}

      <RetireNotes {...notes} />

      <div className="jc-head">
        <p className="pr-hint" aria-live="polite">
          {filter === "all"
            ? t("journal.cov_count", { n: rows.length })
            : t("journal.cov_count_filtered", {
                filter: t(`journal.cov_${filter}`),
                n: shown.length,
                total: rows.length,
              })}
        </p>
        {filter === "all" ? null : (
          <button type="button" className="jc-link" onClick={() => setFilter("all")}>
            {t("journal.cov_show_all")}
          </button>
        )}
      </div>

      <ul className="jc-list">
        <li className="jc-cols" aria-hidden="true">
          <span>{t("journal.cov_col_name")}</span>
          <span>{t("journal.cov_col_weight")}</span>
          {FAMILIES.map((family) => (
            <span key={family}>{t(`journal.cov_fam_${family}`)}</span>
          ))}
          <span>{t("journal.cov_col_status")}</span>
        </li>
        {shown.map((row) => (
          <Holding
            key={row.ticker}
            row={row}
            open={open === row.ticker}
            onToggle={() => setOpen((now) => (now === row.ticker ? null : row.ticker))}
            onRetire={(rule) => retire(rule.id, ruleWords(t, rule, lang))}
          />
        ))}
      </ul>
    </div>
  );
}

/** One family's cell: what its kind asks of it and how its rules read. */
function Cell({ row, family }: { row: CoverageRow; family: Family }) {
  const t = useT();
  const label = t(`journal.cov_fam_${family}`);
  const own = row.rules.filter((rule) => rule.family === family);
  const [kind, text]: [string, ReactNode] = !row.applies.includes(family)
    ? ["na", t("journal.cov_cell_na")]
    : !own.length
      ? row.missing.includes(family)
        ? ["miss", t("journal.cov_cell_missing")]
        : [
            "off",
            <span key="off" title={t("journal.cov_cell_none")}>
              —
            </span>,
          ]
      : own.some((rule) => rule.state === "hit")
        ? ["hit", t("journal.cov_cell_hit")]
        : own.some(flagged)
          ? ["review", t("journal.cov_cell_review")]
          : [
              "ok",
              <>
                <Glyph name="check" size={12} />
                <span className="ag-sr">{t("journal.cov_cell_ok")}</span>
                {own.length > 1 ? own.length : null}
              </>,
            ];
  return (
    <span className="jc-cell" data-cell={kind}>
      <i>{label}</i>
      <b>{text}</b>
    </span>
  );
}

export function Holding({
  row,
  open,
  onToggle,
  onRetire,
}: {
  row: CoverageRow;
  open: boolean;
  onToggle: () => void;
  onRetire: (rule: CoverageRule) => void;
}) {
  const t = useT();
  const lang = useLang();
  const profile = useTickerProfile(row.ticker);
  const subject = rulesSubject(row.ticker, profile?.name ?? "");
  const ask = (text: string) => askAssistant(text, { topic: tickerTopic(row.ticker) });
  const famWord = (family: Family) =>
    t(`journal.cov_fam_${family}`).toLocaleLowerCase();
  const label =
    row.status === "gap"
      ? t("journal.cov_lacks", { what: listed(t, row.missing.map(famWord)) })
      : t(`journal.cov_status_${row.status}`);
  const share =
    row.weight === null
      ? "—"
      : row.weight > 0 && row.weight < 0.0005
        ? `< ${formatter(lang, { maximumFractionDigits: 1 }).format(0.1)}`
        : formatter(lang, { maximumFractionDigits: 1 }).format(row.weight * 100);
  const weight = row.weight === null ? share : `${share} %`;
  const detail = `jc-d-${row.ticker}`;
  const want = wants(row);

  const flagText = (rule: CoverageRule) => {
    if (rule.flag === "drift") return t("journal.cov_flag_drift");
    if (rule.flag === "cap") return t("journal.cov_flag_cap", { weight: share });
    if (rule.flag === "old") {
      const days = (Date.now() - Date.parse(rule.since)) / DAY_MS;
      return t("journal.cov_flag_old", { n: Math.max(1, Math.round(days / 30)) });
    }
    return "";
  };

  const ruleRow = (rule: CoverageRule) => {
    const words = ruleWords(t, rule, lang);
    const hit = rule.state === "hit";
    const flag = flagged(rule) ? flagText(rule) : "";
    const read = hit
      ? rule.family === "thesis" || rule.family === "event"
        ? t("journal.cov_rule_maybe")
        : t("journal.cov_rule_hit")
      : flag
        ? t("journal.cov_rule_review")
        : t("journal.cov_rule_watch");
    const rework = () =>
      ask(
        t("journal.rule_prompt", { ticker: subject, rule: words, now: flag || read }),
      );
    return (
      <li
        key={rule.id}
        className="jc-rule"
        data-read={hit ? "hit" : flag ? "review" : "watch"}
      >
        <span className="jc-rule-fam">{t(`journal.cov_fam_${rule.family}`)}</span>
        <span className="jc-rule-what">
          <span className="jc-rule-text">{words}</span>
          <small>
            {t("journal.cov_since", { day: calendarDay(rule.since, lang) })}
            {hit && rule.pillar
              ? ` · ${t("journal.pillar_hit", { pillar: rule.pillar })}`
              : ""}
          </small>
          {hit && rule.quote ? <q className="jc-rule-quote">{rule.quote}</q> : null}
          {flag ? <span className="jc-flag">{flag}</span> : null}
        </span>
        <span className="jc-rule-read">{read}</span>
        <span className="jc-rule-acts">
          {hit ? (
            <Link page="review" className="ag-jr-btn ag-jr-btn-accent">
              {rule.side === "buy" ? t("journal.cov_add") : t("journal.cov_sell")}
            </Link>
          ) : null}
          {hit || flag ? (
            <button
              type="button"
              className={hit ? "ag-jr-btn" : "ag-jr-btn ag-jr-btn-accent"}
              onClick={rework}
            >
              {hit
                ? t("journal.cov_rewrite")
                : rule.flag === "old"
                  ? t("journal.cov_recheck")
                  : t("journal.cov_adjust")}
            </button>
          ) : null}
          <button
            type="button"
            className="ag-jr-btn"
            aria-label={`${t("journal.criteria_retire")}: ${words}`}
            onClick={() => onRetire(rule)}
          >
            {t("journal.criteria_retire")}
          </button>
        </span>
      </li>
    );
  };

  return (
    <li className="jc-row" data-status={row.status} data-open={open || undefined}>
      <TickerCell ticker={row.ticker} className="jc-tick" name={false}>
        <span className="ag-tick-sym">{profile?.symbol || row.ticker}</span>
        {profile?.name && profile.name.toUpperCase() !== row.ticker.toUpperCase() ? (
          <span className="ag-tick-name">{profile.name}</span>
        ) : null}
      </TickerCell>
      <span className="jc-weight">{weight}</span>
      <span className="jc-cells">
        {FAMILIES.map((family) => (
          <Cell key={family} row={row} family={family} />
        ))}
      </span>
      <button
        type="button"
        className="jc-toggle"
        aria-expanded={open}
        aria-controls={open ? detail : undefined}
        aria-label={t("journal.cov_toggle", { ticker: row.ticker, status: label })}
        onClick={onToggle}
      >
        <span className="jc-status" data-status={row.status}>
          {label}
        </span>
        <Glyph name="down" size={16} />
      </button>
      {open ? (
        <div id={detail} className="jc-detail">
          {want.length ? (
            <div className="jc-want">
              <p>
                {t(bare(row) ? "journal.cov_want_empty" : "journal.cov_want", {
                  what: listed(
                    t,
                    want.map((family) => t(`journal.cov_want_${family}`)),
                  ),
                })}
              </p>
              <button
                type="button"
                className="pr-btn pr-btn-p jc-cta"
                onClick={() => ask(t(draftKey(row), { ticker: subject }))}
              >
                <Glyph name="spark" size={14} />
                {t("journal.cov_draft")}
              </button>
            </div>
          ) : null}
          {row.rules.length ? (
            <ul className="jc-rules">{row.rules.map(ruleRow)}</ul>
          ) : null}
          <p className="jc-foot">
            {row.retired ? (
              <span>{t("journal.cov_retired", { n: row.retired })}</span>
            ) : null}
            <button
              type="button"
              className="jc-link"
              onClick={() => ask(t("journal.criteria_prompt", { ticker: subject }))}
            >
              {t("journal.cov_add_rule")}
            </button>
          </p>
        </div>
      ) : null}
    </li>
  );
}
