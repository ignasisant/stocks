/**
 * The investor plan: the numbers the reader holds the book to.
 *
 * The profile next door says who the reader is; this says what they meant the
 * book to look like — a mix by kind of asset, caps on one name, one sector and
 * the speculative names, a contribution schedule, a cash reserve, and the cash
 * held outside the book that no import sees. Review
 * sizes its moves to it and the daily card measures the book against it
 * (`stocks.portfolio.plan`), so a figure here is a line those pages draw.
 *
 * Every block is optional and a blank field is the app's own line, shown as
 * the placeholder so the reader sees what they are replacing. No Save button,
 * as on every tab: each field commits when it is left. The one exception is
 * the mix, which is stored only once it adds up to the whole book — a mix
 * saved one target at a time would add up to 100 only by accident, so until
 * it does the card says how far off it is and nothing is sent.
 *
 * Under them the entry criteria (`stocks.portfolio.entry`), stored apart from
 * the plan: the lines every buy or add is held to, and a note in the reader's
 * words that only the assistant reads. Review warns when a move breaks one;
 * nothing here blocks a buy.
 */

import { useEffect, useId, useRef, useState } from "react";

import { get, send } from "../../shell/api";
import { askAssistant } from "../../shell/assistant";
import { calendarDay } from "../../shell/dates";
import { Icon } from "../../shell/Icon";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { formatter, num, numberLang } from "../../shell/numbers";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { MixBar } from "../../ui/MixBar";
import type { Projection } from "../portfolio/api";
import { describe } from "./errors";
import { Notes } from "./Investor";
import { Card, Failure, Row, Select } from "./ui";

/** `stocks.portfolio.plan.BUCKETS`, in the order the server offers them. */
const BUCKETS = ["stocks", "equity_funds", "bonds", "cash", "crypto"] as const;
type Bucket = (typeof BUCKETS)[number];

const EVERY = ["monthly", "quarterly"] as const;
type Every = (typeof EVERY)[number];

/** `MIX_SLACK_PP`: how far from 100 a mix may add up and still be whole. */
const SLACK_PP = 0.5;

/**
 * The app's own lines (`stocks.analysis.review`), what a blank field keeps.
 * The position line has no single figure — it follows how many names the
 * book holds — so its placeholder is a word, not a number.
 */
const APP_LINES = { sector: 40, speculative: 3, reserve_max: 20 };

type Mix = { targets: Record<Bucket, number>; band_pp: number };
type Limits = {
  max_position_pct: number | null;
  max_sector_pct: number | null;
  max_speculative_pct: number | null;
};
type Contribution = { amount: number; every: Every; day: number };
type Reserve = { min_pct: number | null; max_pct: number | null };
/**
 * Money outside any position, as the reader states it. `investable` joins
 * the cash bucket; `cushion` is never counted. `as_of` is the server's: it
 * dates the amounts whenever one changes, and ignores the one sent.
 */
type Cash = {
  investable: number | null;
  cushion: number | null;
  rate_pct: number | null;
  as_of?: string | null;
};

/** `PUT /plan` — the whole plan, replaced. */
type PlanWrite = {
  mix: Mix | null;
  limits: Limits;
  contribution: Contribution | null;
  reserve: Reserve | null;
  cash: Cash | null;
};

/** `GET /plan` — the plan as the app applies it, with today's mix beside it. */
export type InvestorPlan = PlanWrite & {
  set: boolean;
  /** Percent of the priced book per bucket; empty when nothing is priced. */
  actual: Partial<Record<Bucket, number>>;
  /** What `contribution.amount` is in: the account's reporting currency. */
  currency: string;
  next_contribution: string | null;
  /** Days since the cash was stated, once old enough to ask again. */
  cash_stale_days: number | null;
};

type Targets = Record<Bucket, number | null>;

export function Plan() {
  const query = useApi(() => get<InvestorPlan>("/plan"), []);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={10} />}>
      {(stored) => <PlanForm stored={stored} />}
    </Loaded>
  );
}

function draftOf(mix: Mix | null): Targets {
  return Object.fromEntries(
    BUCKETS.map((bucket) => [bucket, mix ? mix.targets[bucket] : null]),
  ) as Targets;
}

function total(targets: Targets): number {
  return BUCKETS.reduce((sum, bucket) => sum + (targets[bucket] ?? 0), 0);
}

export function PlanForm({ stored }: { stored: InvestorPlan }) {
  const t = useT();
  const [plan, setPlan] = useState(stored);
  // What the server last said it holds: where a refused write rolls back to.
  const saved = useRef(stored);
  const [failure, setFailure] = useState<string | null>(null);
  const [targets, setTargets] = useState<Targets>(() => draftOf(stored.mix));
  const [band, setBand] = useState(stored.mix?.band_pp ?? 5);
  // The entry checklist loads on its own; the index only counts its lines.
  const [lines, setLines] = useState<number | null>(null);
  const active = useActive(SECTIONS, lines !== null);

  function commit(next: PlanWrite) {
    setPlan({ ...plan, ...next });
    setFailure(null);
    send<InvestorPlan>("PUT", "/plan", next)
      .then((back) => {
        saved.current = back;
        setPlan(back);
        setTargets(draftOf(back.mix));
        setBand(back.mix?.band_pp ?? 5);
      })
      .catch((error: unknown) => {
        // Put back what the server still holds: a field left showing a figure
        // that was not stored is the one lie a form must not tell.
        setPlan(saved.current);
        setTargets(draftOf(saved.current.mix));
        setFailure(describe(error, t("common.offline")));
      });
  }

  const write = (patch: Partial<PlanWrite>): PlanWrite => ({
    mix: plan.mix,
    limits: plan.limits,
    contribution: plan.contribution,
    reserve: plan.reserve,
    cash: plan.cash,
    ...patch,
  });

  // The mix goes to the server only whole: every field blank clears it, a set
  // that adds up to 100 stores it, anything in between stays a draft.
  function draftMix(nextTargets: Targets, nextBand: number) {
    setTargets(nextTargets);
    setBand(nextBand);
    const filled = BUCKETS.filter((bucket) => nextTargets[bucket] !== null);
    if (!filled.length) {
      if (plan.mix) commit(write({ mix: null }));
      return;
    }
    if (Math.abs(total(nextTargets) - 100) > SLACK_PP) return;
    const whole = Object.fromEntries(
      BUCKETS.map((bucket) => [bucket, nextTargets[bucket] ?? 0]),
    ) as Record<Bucket, number>;
    commit(write({ mix: { targets: whole, band_pp: nextBand } }));
  }

  const sum = total(targets);
  const drafting =
    BUCKETS.some((bucket) => targets[bucket] !== null) &&
    Math.abs(sum - 100) > SLACK_PP;
  const priced = BUCKETS.some((bucket) => plan.actual[bucket] !== undefined);
  const money = (amount: number) =>
    formatter(numberLang(), {
      style: "currency",
      currency: plan.currency,
      maximumFractionDigits: 0,
    }).format(amount);

  const limit = (key: keyof Limits) => (value: number | null) =>
    value !== plan.limits[key] &&
    commit(write({ limits: { ...plan.limits, [key]: value } }));

  const contribution = (patch: Partial<Contribution>) => {
    const base = plan.contribution ?? { amount: 0, every: "monthly", day: 1 };
    commit(write({ contribution: { ...base, ...patch } }));
  };

  const reserve = (key: keyof Reserve) => (value: number | null) => {
    if (value === (plan.reserve?.[key] ?? null)) return;
    const next = { min_pct: null, max_pct: null, ...plan.reserve, [key]: value };
    if (next.min_pct !== null && next.max_pct !== null && next.min_pct > next.max_pct) {
      setFailure(t("profile.plan_reserve_order"));
      return;
    }
    const empty = next.min_pct === null && next.max_pct === null;
    commit(write({ reserve: empty ? null : next }));
  };

  const cash = (key: keyof Omit<Cash, "as_of">) => (value: number | null) => {
    if (value === (plan.cash?.[key] ?? null)) return;
    const next = {
      investable: plan.cash?.investable ?? null,
      cushion: plan.cash?.cushion ?? null,
      rate_pct: plan.cash?.rate_pct ?? null,
      [key]: value,
    };
    const empty = next.investable === null && next.cushion === null;
    commit(write({ cash: empty ? null : next }));
  };

  const mix = plan.mix;
  // A reserve is cash's own band and overrides the mix there, as the server
  // reads it (`plan.drift`).
  const outside = (value: number, bucket: Bucket, mix: Mix) =>
    bucket === "cash" && plan.reserve
      ? value < (plan.reserve.min_pct ?? -Infinity) ||
        value > (plan.reserve.max_pct ?? Infinity)
      : Math.abs(value - mix.targets[bucket]) > mix.band_pp;
  const off = mix
    ? BUCKETS.filter((bucket) => {
        const actual = plan.actual[bucket];
        return actual !== undefined && outside(actual, bucket, mix);
      })
    : [];
  // A cash target the reserve rules out: the reserve is what is measured.
  const clash = mix && plan.reserve ? outside(mix.targets.cash, "cash", mix) : false;
  const own = Object.values(plan.limits).filter((value) => value !== null).length;

  return (
    <>
      <Ask set={plan.set} />
      <div className="pr-body">
        <div className="pr-main">
          <Card
            id="plan-mix"
            title={t("profile.plan_mix_title")}
            sub={t("profile.plan_mix_sub")}
          >
            {BUCKETS.map((bucket) => (
              <Row
                key={bucket}
                label={t(`profile.plan_bucket_${bucket}`)}
                help={t(`profile.plan_bucket_${bucket}_help`)}
              >
                <span className="pl-mix">
                  <FigureField
                    label={t(`profile.plan_bucket_${bucket}`)}
                    value={targets[bucket]}
                    placeholder="—"
                    max={100}
                    onCommit={(value) =>
                      value !== targets[bucket] &&
                      draftMix({ ...targets, [bucket]: value }, band)
                    }
                  />
                  {priced && (
                    <MixBar
                      actual={plan.actual[bucket] ?? 0}
                      target={targets[bucket]}
                      caption={t("profile.plan_today", {
                        pct: num(plan.actual[bucket] ?? 0, 0),
                      })}
                    />
                  )}
                </span>
              </Row>
            ))}
            <Row label={t("profile.plan_band")} help={t("profile.plan_band_help")}>
              <FigureField
                label={t("profile.plan_band")}
                value={band}
                placeholder="5"
                min={0.5}
                max={50}
                suffix={t("profile.plan_points")}
                onCommit={(value) => draftMix(targets, value ?? 5)}
              />
            </Row>
            <p className={drafting ? "pl-sum pl-sum-off" : "pl-sum"} aria-live="polite">
              {drafting
                ? t("profile.plan_mix_off", {
                    sum: num(sum, 0),
                    left: num(100 - sum, 0),
                  })
                : plan.mix
                  ? t("profile.plan_mix_whole")
                  : t("profile.plan_mix_none")}
            </p>
          </Card>

          <Card
            id="plan-limits"
            title={t("profile.plan_limits_title")}
            sub={t("profile.plan_limits_sub")}
          >
            <Row
              label={t("profile.plan_max_position")}
              help={t("profile.plan_max_position_help")}
            >
              <FigureField
                label={t("profile.plan_max_position")}
                value={plan.limits.max_position_pct}
                placeholder={t("profile.plan_app_line")}
                max={100}
                above
                onCommit={limit("max_position_pct")}
              />
            </Row>
            <Row
              label={t("profile.plan_max_sector")}
              help={t("profile.plan_max_sector_help")}
            >
              <FigureField
                label={t("profile.plan_max_sector")}
                value={plan.limits.max_sector_pct}
                placeholder={String(APP_LINES.sector)}
                max={100}
                above
                onCommit={limit("max_sector_pct")}
              />
            </Row>
            <Row
              label={t("profile.plan_max_speculative")}
              help={t("profile.plan_max_speculative_help")}
            >
              <FigureField
                label={t("profile.plan_max_speculative")}
                value={plan.limits.max_speculative_pct}
                placeholder={String(APP_LINES.speculative)}
                max={100}
                above
                onCommit={limit("max_speculative_pct")}
              />
            </Row>
          </Card>

          <Card
            id="plan-contribution"
            title={t("profile.plan_contribution_title")}
            sub={t("profile.plan_contribution_sub")}
          >
            <Row
              label={t("profile.plan_amount")}
              help={t("profile.plan_amount_help", { currency: plan.currency })}
            >
              <FigureField
                label={t("profile.plan_amount")}
                value={plan.contribution?.amount ?? null}
                placeholder="—"
                max={10_000_000}
                above
                suffix={plan.currency}
                onCommit={(amount) => {
                  if (amount === (plan.contribution?.amount ?? null)) return;
                  if (amount === null) commit(write({ contribution: null }));
                  else contribution({ amount });
                }}
              />
            </Row>
            <Row label={t("profile.plan_every")}>
              <Select
                label={t("profile.plan_every")}
                value={plan.contribution?.every ?? "monthly"}
                options={EVERY}
                labelOf={(every) => t(`profile.plan_every_${every}`)}
                disabled={!plan.contribution}
                onPick={(every) =>
                  every !== plan.contribution?.every && contribution({ every })
                }
              />
            </Row>
            <Row label={t("profile.plan_day")} help={t("profile.plan_day_help")}>
              <FigureField
                label={t("profile.plan_day")}
                value={plan.contribution?.day ?? 1}
                placeholder="1"
                min={1}
                max={28}
                whole
                suffix=""
                disabled={!plan.contribution}
                onCommit={(day) =>
                  day !== null &&
                  day !== plan.contribution?.day &&
                  contribution({ day })
                }
              />
            </Row>
            {plan.contribution && (
              <Leads
                amount={plan.contribution.amount}
                every={plan.contribution.every}
                currency={plan.currency}
              />
            )}
          </Card>

          <Card
            id="plan-reserve"
            title={t("profile.plan_reserve_title")}
            sub={t("profile.plan_reserve_sub")}
          >
            <Row
              label={t("profile.plan_reserve_min")}
              help={t("profile.plan_reserve_min_help")}
            >
              <FigureField
                label={t("profile.plan_reserve_min")}
                value={plan.reserve?.min_pct ?? null}
                placeholder="0"
                max={100}
                onCommit={reserve("min_pct")}
              />
            </Row>
            <Row
              label={t("profile.plan_reserve_max")}
              help={t("profile.plan_reserve_max_help")}
            >
              <FigureField
                label={t("profile.plan_reserve_max")}
                value={plan.reserve?.max_pct ?? null}
                placeholder={String(APP_LINES.reserve_max)}
                max={100}
                onCommit={reserve("max_pct")}
              />
            </Row>
            {clash && mix && (
              <p className="pl-sum pl-sum-off" aria-live="polite">
                {t("profile.plan_reserve_clash", { target: num(mix.targets.cash, 0) })}
              </p>
            )}
          </Card>

          <Card
            id="plan-cash"
            title={t("profile.plan_cash_title")}
            sub={t("profile.plan_cash_sub")}
          >
            <Row
              label={t("profile.plan_investable")}
              help={t("profile.plan_investable_help", { currency: plan.currency })}
            >
              <FigureField
                label={t("profile.plan_investable")}
                value={plan.cash?.investable ?? null}
                placeholder="—"
                max={1e12}
                suffix={plan.currency}
                onCommit={cash("investable")}
              />
            </Row>
            <Row
              label={t("profile.plan_cushion")}
              help={t("profile.plan_cushion_help", { currency: plan.currency })}
            >
              <FigureField
                label={t("profile.plan_cushion")}
                value={plan.cash?.cushion ?? null}
                placeholder="—"
                max={1e12}
                suffix={plan.currency}
                onCommit={cash("cushion")}
              />
            </Row>
            <Row label={t("profile.plan_rate")} help={t("profile.plan_rate_help")}>
              <FigureField
                label={t("profile.plan_rate")}
                value={plan.cash?.rate_pct ?? null}
                placeholder="0"
                max={20}
                disabled={!plan.cash}
                onCommit={cash("rate_pct")}
              />
            </Row>
            {plan.cash?.as_of && (
              <p
                className={plan.cash_stale_days ? "pl-sum pl-sum-off" : "pl-sum"}
                aria-live="polite"
              >
                {plan.cash_stale_days
                  ? t("profile.plan_cash_stale", { days: num(plan.cash_stale_days, 0) })
                  : t("profile.plan_cash_as_of", {
                      date: calendarDay(plan.cash.as_of),
                    })}
              </p>
            )}
            <Failure message={failure} />
          </Card>

          <Entry onLines={setLines} />
        </div>

        <aside className="pr-rail pl-rail">
          <Card>
            <nav className="pr-sum" aria-label={t("profile.plan_idx_label")}>
              <span className="pr-sum-t">{t("profile.plan_sum_title")}</span>
              <ol className="pl-idx">
                <Section
                  id="plan-mix"
                  active={active}
                  label={t("profile.plan_mix_title")}
                  value={
                    !plan.mix
                      ? t("profile.iv_sum_none")
                      : !priced
                        ? t("profile.plan_sum_unpriced")
                        : off.length
                          ? off
                              .map((bucket) => t(`profile.plan_bucket_${bucket}`))
                              .join(", ")
                          : t("profile.plan_sum_inside")
                  }
                  warn={off.length > 0}
                />
                <Section
                  id="plan-limits"
                  active={active}
                  label={t("profile.plan_limits_title")}
                  value={
                    own === 0
                      ? t("profile.plan_idx_app")
                      : t(
                          own === 1
                            ? "profile.plan_idx_own_one"
                            : "profile.plan_idx_own",
                          {
                            n: own,
                          },
                        )
                  }
                />
                <Section
                  id="plan-contribution"
                  active={active}
                  label={t("profile.plan_contribution_title")}
                  value={
                    plan.contribution && plan.next_contribution
                      ? `${calendarDay(plan.next_contribution)} · ${money(plan.contribution.amount)}`
                      : t("profile.iv_sum_none")
                  }
                />
                <Section
                  id="plan-reserve"
                  active={active}
                  label={t("profile.plan_reserve_title")}
                  value={
                    plan.reserve
                      ? `${num(plan.reserve.min_pct ?? 0, 0)}–${num(
                          plan.reserve.max_pct ?? 100,
                          0,
                        )}%`
                      : t("profile.iv_sum_none")
                  }
                  warn={clash}
                />
                <Section
                  id="plan-cash"
                  active={active}
                  label={t("profile.plan_cash_title")}
                  value={
                    plan.cash?.investable != null
                      ? money(plan.cash.investable)
                      : t("profile.iv_sum_none")
                  }
                  warn={Boolean(plan.cash_stale_days)}
                />
                <Section
                  id="plan-entry"
                  active={active}
                  label={t("profile.entry_title")}
                  value={
                    lines === null
                      ? ""
                      : lines === 0
                        ? t("profile.iv_sum_none")
                        : t(
                            lines === 1 ? "profile.entry_idx_one" : "profile.entry_idx",
                            {
                              n: lines,
                            },
                          )
                  }
                />
              </ol>
              <div className="pr-sum-rule" />
              <span className="pr-sum-note">{t("profile.plan_privacy")}</span>
            </nav>
          </Card>
        </aside>
      </div>
    </>
  );
}

/**
 * `stocks.portfolio.entry.RULES`, in the order the server keeps them, with the
 * bounds `entry.clean` holds a level to: a percent may go below zero ("growing
 * at all", buying back shares), a multiple and a weight may not.
 */
const ENTRY_RULES: { rule: string; unit: "pct" | "x"; rules: FigureRules }[] = [
  { rule: "revenue_growth_min", unit: "pct", rules: { min: -100, max: 999 } },
  { rule: "op_margin_min", unit: "pct", rules: { min: -100, max: 999 } },
  { rule: "fcf_yield_min", unit: "pct", rules: { min: -100, max: 999 } },
  { rule: "roic_min", unit: "pct", rules: { min: -100, max: 999 } },
  { rule: "pe_fwd_max", unit: "x", rules: { min: 0, max: 500, above: true } },
  { rule: "net_debt_ebitda_max", unit: "x", rules: { min: 0, max: 500, above: true } },
  { rule: "dilution_max", unit: "pct", rules: { min: -100, max: 999 } },
  { rule: "dividend_yield_min", unit: "pct", rules: { min: -100, max: 999 } },
  { rule: "weight_max", unit: "pct", rules: { min: 0, max: 100, above: true } },
];

type EntryLine = { rule: string; level: number };
/** `GET /plan/entry` — the checklist; `PUT` takes it whole, without `set`. */
type EntryCriteria = { rules: EntryLine[]; note: string; set: boolean };

function Entry({ onLines }: { onLines: (count: number) => void }) {
  const query = useApi(() => get<EntryCriteria>("/plan/entry"), []);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={4} />}>
      {(stored) => <EntryForm stored={stored} onLines={onLines} />}
    </Loaded>
  );
}

/**
 * The checklist, one field per line: blank is no line. Each field and the
 * note commit when left, the whole checklist each time, as `PUT /plan/entry`
 * replaces it.
 */
export function EntryForm({
  stored,
  onLines,
}: {
  stored: EntryCriteria;
  onLines?: (count: number) => void;
}) {
  const t = useT();
  const [entry, setEntry] = useState(stored);
  const saved = useRef(stored);
  const [failure, setFailure] = useState<string | null>(null);
  const count = entry.rules.length;
  useEffect(() => onLines?.(count), [count, onLines]);
  const level = (rule: string) =>
    entry.rules.find((line) => line.rule === rule)?.level ?? null;

  function commit(rules: EntryLine[], note: string) {
    setEntry({ ...entry, rules, note });
    setFailure(null);
    send<EntryCriteria>("PUT", "/plan/entry", { rules, note })
      .then((back) => {
        saved.current = back;
        setEntry(back);
      })
      .catch((error: unknown) => {
        setEntry(saved.current);
        setFailure(describe(error, t("common.offline")));
      });
  }

  const line = (rule: string) => (value: number | null) => {
    if (value === level(rule)) return;
    const rules = ENTRY_RULES.flatMap(({ rule: key }) => {
      const kept = key === rule ? value : level(key);
      return kept === null ? [] : [{ rule: key, level: kept }];
    });
    commit(rules, entry.note);
  };

  return (
    <Card id="plan-entry" title={t("profile.entry_title")} sub={t("profile.entry_sub")}>
      <EntryAsk />
      {ENTRY_RULES.map(({ rule, unit, rules }) => (
        <Row
          key={rule}
          label={t(`profile.entry_${rule}`)}
          help={t(`profile.entry_${rule}_help`)}
        >
          <FigureField
            label={t(`profile.entry_${rule}`)}
            value={level(rule)}
            placeholder="—"
            suffix={unit === "pct" ? "%" : "×"}
            onCommit={line(rule)}
            {...rules}
          />
        </Row>
      ))}
      <Row label={t("profile.entry_note")} help={t("profile.entry_note_help")}>
        <Notes
          value={entry.note}
          label={t("profile.entry_note")}
          placeholder={t("profile.entry_note_placeholder")}
          onCommit={(note) => note !== entry.note && commit(entry.rules, note)}
        />
      </Row>
      <Failure message={failure} />
    </Card>
  );
}

/**
 * "Propose with AI", at the top of the checklist: a new conversation with a
 * request the chat's entry builder hears (`chat/entry_builder.wants`), which
 * drafts the lines from the profile and the plan's position cap into fields
 * the reader adjusts and saves there.
 */
function EntryAsk() {
  const t = useT();
  return (
    <div className="pl-ask pl-ask-entry">
      <p className="pl-ask-sub">{t("profile.entry_ask_sub")}</p>
      <button
        type="button"
        className="ag-btn ag-ai pl-ask-btn"
        onClick={() => askAssistant(t("profile.entry_ask_prompt"), { fresh: true })}
      >
        <Icon name="auto_awesome" size={18} />
        <span>{t("profile.entry_ask")}</span>
      </button>
    </div>
  );
}

/**
 * Where the contribution leads: the projection's central scenario and its
 * p10–p90 at the profile's horizon, on the plan's own inputs, with the way to
 * the tab that moves them. Nothing while it draws or when it cannot answer —
 * a line about the future is not worth a skeleton.
 */
function Leads({
  amount,
  every,
  currency,
}: {
  amount: number;
  every: Contribution["every"];
  currency: string;
}) {
  const t = useT();
  const query = useApi(
    () =>
      get<Projection>("/portfolio/projection", { base: currency, from_plan: "true" }),
    [amount, every, currency],
  );
  if (query.state !== "loaded") return null;
  const data = query.data;
  const [median, low, high] = [data.p50, data.p10, data.p90].map((points) =>
    points.at(-1),
  );
  if (median === undefined || low === undefined || high === undefined) return null;
  const money = (value: number) =>
    formatter(numberLang(), {
      style: "currency",
      currency: data.base,
      maximumFractionDigits: 0,
    }).format(value);
  return (
    <p className="pl-sum pl-leads">
      {t(data.years === 1 ? "profile.plan_leads_one" : "profile.plan_leads", {
        years: data.years,
        median: money(median),
        low: money(low),
        high: money(high),
      })}{" "}
      <Link page="portfolio" params={{ tab: "projection" }} className="pl-leads-link">
        {t("profile.plan_leads_link")}
      </Link>
    </p>
  );
}

/**
 * "Build my plan with AI", above the form, as Review asks the AI from its
 * top row. It opens a new conversation with a request the chat's plan builder
 * hears (`chat/plan_builder.wants`): a card that asks only what the app does
 * not know and drafts a plan the reader saves from there. Once a plan is set
 * the press offers to redo it; the card says it replaces the stored one.
 */
function Ask({ set }: { set: boolean }) {
  const t = useT();
  const label = t(set ? "profile.plan_ask_again" : "profile.plan_ask");
  return (
    <div className="pl-ask">
      <p className="pl-ask-sub">
        {t(set ? "profile.plan_ask_again_sub" : "profile.plan_ask_sub")}
      </p>
      <button
        type="button"
        className="ag-btn ag-ai pl-ask-btn"
        onClick={() => askAssistant(t("profile.plan_ask_prompt"), { fresh: true })}
      >
        <Icon name="auto_awesome" size={18} />
        <span>{label}</span>
      </button>
    </div>
  );
}

/** The cards the rail indexes, by `Card` id, top to bottom. */
const SECTIONS = [
  "plan-mix",
  "plan-limits",
  "plan-contribution",
  "plan-reserve",
  "plan-cash",
  "plan-entry",
] as const;

/**
 * The section being read: the card under a line a fifth of the way down the
 * window. A line and not a band, so the tail of the card above never wins
 * over the one just landed on; in the gap between two cards the mark stays
 * where it was. `ready` re-observes once a card that loads late (the entry
 * checklist) is on the page. Nothing without an observer — the index still
 * jumps, it just marks nothing.
 */
function useActive(ids: readonly string[], ready: boolean): string | null {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const crossing = new Map<string, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          crossing.set(entry.target.id, entry.isIntersecting);
        const under = ids.find((id) => crossing.get(id));
        if (under) setActive(under);
      },
      { rootMargin: "-20% 0px -79% 0px" },
    );
    for (const id of ids) {
      const card = document.getElementById(id);
      if (card) observer.observe(card);
    }
    return () => observer.disconnect();
  }, [ids, ready]);
  return active;
}

/**
 * One line of the index: the section and where it stands, pressed to land on
 * its card. The card takes focus so the keyboard carries on from there.
 */
function Section({
  id,
  active,
  label,
  value,
  warn,
}: {
  id: string;
  active: string | null;
  label: string;
  value: string;
  warn?: boolean;
}) {
  function jump() {
    const card = document.getElementById(id);
    if (!card) return;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView?.({ behavior: still ? "auto" : "smooth", block: "start" });
    card.focus({ preventScroll: true });
  }
  return (
    <li>
      <button
        type="button"
        className="pl-idx-row"
        aria-current={active === id ? "location" : undefined}
        onClick={jump}
      >
        <span className="pl-idx-l">{label}</span>
        <b className={warn ? "pl-idx-v pl-warn" : "pl-idx-v"}>{value}</b>
      </button>
    </li>
  );
}

/** The bounds a figure field holds its text to. */
export type FigureRules = {
  min?: number;
  max?: number;
  /** `min` itself is refused: a cap or an amount of 0 means nothing. */
  above?: boolean;
  whole?: boolean;
};

/** What a field's text says: a figure, blank (`null`), or why it is neither. */
export type Checked =
  | { ok: true; value: number | null }
  | { ok: false; error: "number" | "whole" | "range" | "above" };

/**
 * Reads a field's text against its bounds. A comma counts as the decimal
 * point, since half the readers type one.
 */
export function checkFigure(text: string, rules: FigureRules): Checked {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: true, value: null };
  const parsed = /^[-+]?(\d+([.,]\d*)?|[.,]\d+)$/.test(trimmed)
    ? Number(trimmed.replace(",", "."))
    : NaN;
  if (!Number.isFinite(parsed)) return { ok: false, error: "number" };
  if (rules.whole && !Number.isInteger(parsed)) return { ok: false, error: "whole" };
  const { min = 0, max = Infinity, above } = rules;
  const low = above ? parsed <= min : parsed < min;
  if (low || parsed > max) return { ok: false, error: above ? "above" : "range" };
  return { ok: true, value: parsed };
}

/**
 * A figure that may be left blank: committed when the field is left or Enter
 * is pressed, as the Preferences number fields are, but an emptied field is a
 * value of its own — `null`, the app's own line — rather than a typo to undo.
 * Text that is not a figure inside the bounds is never sent: the field keeps
 * it, marked, with the reason under it, until it is fixed or Escape restores
 * what is stored.
 */
function FigureField({
  value,
  onCommit,
  label,
  placeholder,
  min = 0,
  max,
  above,
  whole,
  suffix = "%",
  disabled,
}: {
  value: number | null;
  onCommit: (next: number | null) => void;
  label: string;
  placeholder: string;
  suffix?: string;
  disabled?: boolean;
} & FigureRules) {
  const t = useT();
  const id = useId();
  const shown = value === null ? "" : String(value);
  const [draft, setDraft] = useState(shown);
  // Shown once the field is left with a bad figure, then live until it is fixed.
  const [told, setTold] = useState(false);
  // A save came back, or was refused and rolled back: show what is stored.
  useEffect(() => {
    setDraft(shown);
    setTold(false);
  }, [shown]);

  const checked = checkFigure(draft, { min, max, above, whole });
  const bound = (figure: number | undefined) =>
    figure === undefined ? "" : num(figure, Number.isInteger(figure) ? 0 : 1);
  const error =
    told && !checked.ok
      ? t(`profile.plan_err_${checked.error}`, { min: bound(min), max: bound(max) })
      : null;

  const commit = () => {
    if (!checked.ok) {
      setTold(true);
      return;
    }
    setTold(false);
    if (checked.value !== value) onCommit(checked.value);
  };

  return (
    <span className="pl-field">
      <span className="pr-chips">
        <input
          className="pr-input pl-num"
          type="text"
          inputMode={whole ? "numeric" : "decimal"}
          autoComplete="off"
          enterKeyHint="done"
          aria-label={label}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? id : undefined}
          value={draft}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              setDraft(shown);
              setTold(false);
            }
          }}
        />
        {suffix && <span className="pr-hint">{suffix}</span>}
      </span>
      <span id={id} className="pl-err" aria-live="polite">
        {error}
      </span>
    </span>
  );
}
