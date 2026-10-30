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
import type { Projection } from "../portfolio/api";
import { describe } from "./errors";
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
  const off = mix
    ? BUCKETS.filter((bucket) => {
        const actual = plan.actual[bucket];
        return (
          actual !== undefined && Math.abs(actual - mix.targets[bucket]) > mix.band_pp
        );
      })
    : [];

  return (
    <>
      <Ask set={plan.set} />
      <div className="pr-body">
        <div className="pr-main">
          <Card title={t("profile.plan_mix_title")} sub={t("profile.plan_mix_sub")}>
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
          </Card>

          <Card title={t("profile.plan_cash_title")} sub={t("profile.plan_cash_sub")}>
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
        </div>

        <aside className="pr-rail">
          <Card>
            <div className="pr-sum">
              <span className="pr-sum-t">{t("profile.plan_sum_title")}</span>
              <Summary
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
              <Summary
                label={t("profile.plan_sum_next")}
                value={
                  plan.contribution && plan.next_contribution
                    ? `${calendarDay(plan.next_contribution)} · ${money(plan.contribution.amount)}`
                    : t("profile.iv_sum_none")
                }
              />
              <Summary
                label={t("profile.plan_reserve_title")}
                value={
                  plan.reserve
                    ? `${num(plan.reserve.min_pct ?? 0, 0)}–${num(
                        plan.reserve.max_pct ?? 100,
                        0,
                      )}%`
                    : t("profile.iv_sum_none")
                }
              />
              <Summary
                label={t("profile.plan_investable")}
                value={
                  plan.cash?.investable != null
                    ? money(plan.cash.investable)
                    : t("profile.iv_sum_none")
                }
                warn={Boolean(plan.cash_stale_days)}
              />
              <div className="pr-sum-rule" />
              <span className="pr-sum-note">{t("profile.plan_privacy")}</span>
            </div>
          </Card>
        </aside>
      </div>
    </>
  );
}

/**
 * "Build my plan with AI", above the form, as Review asks the AI from its
 * top row. It opens a new conversation with a request the chat's plan builder
 * hears (`chat/plan_builder.wants`): a card that asks only what the app does
 * not know and drafts a plan the reader saves from there. Once a plan is set
 * the press offers to redo it; the card says it replaces the stored one.
 */
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

function Summary({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="pr-sum-row">
      <span>{label}</span>
      <b className={warn ? "pl-warn" : undefined}>{value}</b>
    </div>
  );
}

/**
 * Today's share of the book as a fill, the target as a tick across it.
 * Decorative beside the caption that says the same in words.
 */
function MixBar({
  actual,
  target,
  caption,
}: {
  actual: number;
  target: number | null;
  caption: string;
}) {
  const clamp = (value: number) => Math.min(100, Math.max(0, value));
  return (
    <span className="pl-bar-wrap">
      <span className="pl-bar" aria-hidden="true">
        <span className="pl-bar-fill" style={{ width: `${clamp(actual)}%` }} />
        {target !== null && (
          <span className="pl-bar-target" style={{ left: `${clamp(target)}%` }} />
        )}
      </span>
      <span className="pl-bar-cap">{caption}</span>
    </span>
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
