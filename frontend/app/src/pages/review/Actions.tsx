/**
 * The plan: what the read asks the reader to do, and what it costs.
 *
 * It answers the page's one question before anything else is read: the cash
 * the moves need (or free), drawn as two bars on one scale so the sales are
 * seen paying for the adds and the gap is what new money has to cover. The
 * sale's tax sits beside it, because a plan that frees cash and costs tax is
 * two numbers, not one.
 *
 * Under it the moves, one row each, split by direction: the sales and trims
 * that free cash, then the adds that spend it, each list led by its biggest
 * amount. A row is the whole decision on one line of sight — who, from which
 * weight to which, how much money, why, and what it costs in tax or when it
 * can be done; its details open in the dialog the tables' rows open. Holding
 * is not a move, so the quiet rows are the table's, not here.
 *
 * A plan that moves nothing is advice too, said as such: the book is fine as
 * it is today, and why — names a few points from a move, sales whose tax
 * would eat what they bring. The adds the sales cannot pay for are listed
 * apart, as what new money would buy, never as cash the plan spends.
 *
 * Folded, the plan is its headline: one sentence of what to do ("sell 2,
 * trim 1 and add to 3"), the figures, then every name to sell, to add to and
 * to buy with new money, one dense line each — who, from which weight to
 * which (drawn as a bar on one scale for the whole plan), how much, and what
 * it costs in tax. The full read (why, details, and the moves drawn against
 * the S&P 500 over the tables' window) unfolds below.
 *
 * With a contribution set in the reader's plan, one line says where the next
 * one goes: the first of what new money would buy, then the next ones.
 */

import { Suspense, lazy, useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { TickerCell } from "../../shell/tickers";
import { Help } from "../../ui/Kpi";
import { DetailsButton, VerdictChip } from "./Explain";
import { useListFocus } from "./focus";
import { useHelp } from "./lines";
import { useReturns } from "./returns";
import { planMoves, waitingMoves } from "./filter";
import { entryText, longDay, verdictTone } from "./format";
import type { EntryCheck, Review, ReviewInvestorPlan, ReviewRow } from "./types";
import { jurisdictionLabel } from "../portfolio/format";
import { money, percent } from "../../shell/format";

// The chart and its code wait for the full read: folded, the plan is figures.
const PlanChart = lazy(() => import("./PlanChart"));

export function Plan({ data, filtered = false }: { data: Review; filtered?: boolean }) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const plan = data.plan;
  const { out, into } = planMoves(data);
  const moves = [...out, ...into];
  const waiting = waitingMoves(data);
  const net = plan.buys - plan.sells;
  const scale = Math.max(plan.sells, plan.buys, 1);
  // Every weight bar in the plan on one scale, so a long bar is a big name.
  const span = weightSpan([...moves, ...waiting], data.total);
  const [open, setOpen] = useState(false);
  const brief = !open;
  const returns = useReturns();
  const focus = useListFocus(
    "plan",
    moves.map((row) => row.ticker),
  );

  return (
    <section className="ag-rev-card ag-rev-plan" aria-labelledby="ag-rev-plan-h">
      <h2 className="ag-rev-h2" id="ag-rev-plan-h">
        {t("review.plan_title")}
      </h2>
      {moves.length === 0 && filtered ? (
        <p className="ag-rev-caption">{t("review.moves_none")}</p>
      ) : moves.length === 0 ? (
        <>
          <Stay data={data} />
          <Next rows={waiting} upcoming={data.investor_plan} base={data.base} />
        </>
      ) : (
        <>
          <Headline data={data} out={out} into={into} />
          <Next rows={waiting} upcoming={data.investor_plan} base={data.base} />
          <div className="ag-rev-plan-sum">
            <div className="ag-rev-plan-fig">
              <span className="ag-rev-plan-label">
                {t(
                  net > 0
                    ? "review.plan_need"
                    : net < 0
                      ? "review.plan_free"
                      : "review.plan_even",
                )}
                <Help text={t("review.plan_net_help")} />
              </span>
              <b className="ag-rev-plan-value">
                {money(Math.abs(net), { currency: data.base, lang }) ?? na}
              </b>
              <span className="ag-rev-plan-tax">
                {t("review.plan_tax")}
                {plan.tax_currency && plan.tax_currency !== data.base
                  ? ` (${t("review.tax_in", { currency: plan.tax_currency })})`
                  : null}{" "}
                <b>{money(plan.tax, { currency: plan.tax_currency, lang }) ?? na}</b>
                <Help text={t("review.plan_tax_help", { code: data.jurisdiction })} />
              </span>
            </div>
            <dl className="ag-rev-flow">
              <Flow
                label={t("review.plan_sells")}
                help={t("review.plan_sells_help")}
                amount={plan.sells}
                other={plan.buys}
                scale={scale}
                tone="down"
                base={data.base}
              />
              <Flow
                label={t("review.plan_buys")}
                help={t("review.plan_buys_help")}
                amount={plan.buys}
                other={plan.sells}
                scale={scale}
                tone="up"
                base={data.base}
              />
            </dl>
          </div>
          {net < 0 ? (
            <p className="ag-rev-caption ag-rev-plan-note">
              {t("review.plan_unplaced", {
                amount: money(-net, { currency: data.base, lang }) ?? na,
              })}
            </p>
          ) : null}
          {data.tax_status && data.tax_status !== "chosen" ? (
            <p className="ag-rev-caption ag-rev-plan-note">
              {t("review.tax_assumed", {
                label: jurisdictionLabel(data.jurisdiction, t),
              })}{" "}
              <Link page="profile">{t("review.tax_assumed_link")}</Link>
            </p>
          ) : null}
          <div
            className={`ag-rev-plan-cols${brief ? " ag-rev-plan-brief" : ""}${focus.fading ? " ag-rev-fading" : ""}`}
          >
            <MoveList
              title={t("review.out_title")}
              rows={out}
              brief={brief}
              total={-plan.sells}
              base={data.base}
              taxCurrency={plan.tax_currency}
              focus={focus}
              span={span}
            />
            <MoveList
              title={t("review.in_title")}
              rows={into}
              brief={brief}
              total={plan.buys}
              base={data.base}
              taxCurrency={plan.tax_currency}
              focus={focus}
              span={span}
            />
            {brief && waiting.length > 0 ? (
              <Waiting
                rows={waiting}
                total={plan.new_money ?? 0}
                book={data.total}
                base={data.base}
                span={span}
                brief
              />
            ) : null}
          </div>
          {open && returns ? (
            <Suspense fallback={null}>
              <PlanChart out={out} into={into} base={data.base} span={returns.span} />
            </Suspense>
          ) : null}
        </>
      )}
      {waiting.length > 0 && (open || moves.length === 0) ? (
        <Waiting
          rows={waiting}
          total={plan.new_money ?? 0}
          book={data.total}
          base={data.base}
          span={span}
        />
      ) : null}
      {moves.length > 0 ? (
        <button
          type="button"
          className="ag-rev-plan-toggle"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {t(open ? "review.plan_less" : "review.plan_more")}
        </button>
      ) : null}
    </section>
  );
}

/**
 * The plan in one sentence: "Sell 2, trim 1 and add to 3", then how many
 * names stay as they are and how many of those are close to a move.
 */
function Headline({
  data,
  out,
  into,
}: {
  data: Review;
  out: ReviewRow[];
  into: ReviewRow[];
}) {
  const t = useT();
  const lang = useLang();
  const count = (rows: ReviewRow[], test: (row: ReviewRow) => boolean) =>
    rows.filter(test).length;
  const parts = (
    [
      ["sell", count(out, (row) => row.verdict === "sell")],
      ["trim", count(out, (row) => row.verdict !== "sell")],
      ["add", count(into, (row) => row.held)],
      ["buy", count(into, (row) => !row.held)],
    ] as const
  ).flatMap(([kind, n]) => (n ? [t(`review.head_${kind}`, { count: n })] : []));
  const said = new Intl.ListFormat(lang, { type: "conjunction" }).format(parts);
  const moving = new Set([...out, ...into].map((row) => row.ticker));
  const rest = data.held.filter((row) => !moving.has(row.ticker));
  const close = rest.filter((row) => row.reasons.includes("close_call")).length;
  return (
    <div className="ag-rev-plan-head">
      <p className="ag-rev-plan-say">
        {said.charAt(0).toLocaleUpperCase(lang) + said.slice(1)}
      </p>
      {rest.length > 0 ? (
        <p className="ag-rev-caption">
          {t("review.head_rest", { count: rest.length })}
          {close > 0 ? ` · ${t("review.head_close", { count: close })}` : null}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Where the next contribution goes, when the reader's plan sets one: the
 * first of what new money would buy, then the next two.
 */
function Next({
  rows,
  upcoming,
  base,
}: {
  rows: ReviewRow[];
  upcoming?: ReviewInvestorPlan;
  base: string;
}) {
  const t = useT();
  const lang = useLang();
  const day = upcoming?.next_contribution;
  const amount = upcoming?.contribution;
  const first = rows[0];
  if (!day || !amount || !first) return null;
  const then = rows.slice(1, 3).map((row) => row.symbol || row.ticker);
  return (
    <p className="ag-rev-plan-next">
      {t("review.next_contribution", {
        amount: money(amount, { currency: base, lang }) ?? t("review.na"),
        date: longDay(day, lang),
        first: first.symbol || first.ticker,
      })}
      {then.length
        ? ` ${t("review.next_then", {
            names: new Intl.ListFormat(lang, { type: "conjunction" }).format(then),
          })}`
        : null}
    </p>
  );
}

/** The widest weight any row in the plan goes from or to: the bars' 100 %. */
function weightSpan(rows: ReviewRow[], book: number | null): number {
  let top = 0;
  for (const row of rows) {
    const to =
      row.new_money && book
        ? (row.target_weight ?? row.weight ?? 0) + row.new_money / book
        : row.target_weight;
    top = Math.max(top, row.weight ?? 0, to ?? 0);
  }
  return top || 1;
}

/**
 * A name's weight now and where the move takes it, on the plan's one scale:
 * the part it keeps solid, the part that leaves or arrives in the move's
 * tone, and a tick at the mark. The figures beside it say the same.
 */
function WeightBar({
  from,
  to,
  span,
}: {
  from: number | null;
  to: number | null;
  span: number;
}) {
  if (to === null) return null;
  const now = Math.max(0, from ?? 0);
  const pct = (value: number) => `${Math.min(100, (value / span) * 100)}%`;
  const kept = Math.min(now, to);
  return (
    <span className="ag-rev-wbar" aria-hidden="true">
      <span className="ag-rev-wbar-kept" style={{ width: pct(kept) }} />
      <span
        className={`ag-rev-wbar-move ag-rev-wbar-${to < now ? "down" : "up"}`}
        style={{ left: pct(kept), width: pct(Math.abs(to - now)) }}
      />
      <span className="ag-rev-wbar-mark" style={{ left: pct(to) }} />
    </span>
  );
}

/**
 * Nothing to move: the advice is to stay, and the lines under it say what
 * kept the book still when something nearly moved.
 */
function Stay({ data }: { data: Review }) {
  const t = useT();
  const has = (code: string) => (row: ReviewRow) => row.reasons.includes(code);
  const close = data.held.filter(has("close_call")).length;
  const costly = data.held.filter(has("sale_costly")).length;
  return (
    <div className="ag-rev-plan-stay">
      <p className="ag-rev-plan-stay-title">{t("review.stay_title")}</p>
      <p className="ag-rev-caption">{t("review.stay_body")}</p>
      {close || costly ? (
        <ul className="ag-rev-plan-stay-why">
          {close ? <li>{t("review.stay_close", { count: close })}</li> : null}
          {costly ? <li>{t("review.stay_costly", { count: costly })}</li> : null}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * What new money would buy: the adds the sales do not reach, best case
 * first, each from its weight to its mark and the money that takes.
 */
function Waiting({
  rows,
  total,
  book,
  base,
  span,
  brief = false,
}: {
  rows: ReviewRow[];
  total: number;
  book: number | null;
  base: string;
  span: number;
  brief?: boolean;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  return (
    <div className={`ag-rev-mvs${brief ? "" : " ag-rev-wait"}`}>
      <h3 className="ag-rev-mvs-head">
        <span>
          {t("review.wait_title")} <span className="ag-rev-mvs-n">{rows.length}</span>
          <Help text={t("review.wait_help")} />
        </span>
        <span className="ag-rev-tone-up">
          {money(total, { currency: base, lang, signed: true })}
        </span>
      </h3>
      <ul className="ag-rev-mv-list">
        {rows.map((row) => {
          const from = row.target_weight ?? row.weight;
          const to = from !== null && book ? from + (row.new_money ?? 0) / book : null;
          return (
            <li key={row.ticker} className="ag-rev-mv ag-row-reach">
              <div className="ag-rev-mv-who">
                <TickerCell ticker={row.ticker} />
              </div>
              <span className="ag-rev-mv-weights">
                <span>
                  {percent(from, { lang }) ?? na}
                  <i aria-hidden="true">→</i>
                  {percent(to, { lang }) ?? na}
                </span>
                <WeightBar from={from} to={to} span={span} />
              </span>
              <b className="ag-rev-mv-money ag-rev-tone-up">
                {money(row.new_money ?? null, { currency: base, lang, signed: true }) ??
                  na}
              </b>
              {brief ? null : (
                <>
                  <div className="ag-rev-mv-why">
                    <Reasons
                      reasons={row.reasons.filter((code) => code !== "needs_new_money")}
                      limit={2}
                    />
                  </div>
                  <span className="ag-rev-mv-more">
                    <DetailsButton row={row} variant="icon" />
                  </span>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * One side of the plan as a bar on the scale both share. On the shorter side
 * the dashed rest of the bar is the gap the other side leaves: new cash when
 * the adds outrun the sales, cash left over when the sales outrun the adds.
 */
function Flow({
  label,
  help,
  amount,
  other,
  scale,
  tone,
  base,
}: {
  label: string;
  help: string;
  amount: number;
  other: number;
  scale: number;
  tone: "up" | "down";
  base: string;
}) {
  const lang = useLang();
  const fill = (amount / scale) * 100;
  const gap = other > amount ? ((other - amount) / scale) * 100 : 0;
  return (
    <div className="ag-rev-flow-row">
      <dt>
        {label}
        <Help text={help} />
      </dt>
      <dd className="ag-rev-flow-track" aria-hidden="true">
        <span
          className={`ag-rev-flow-fill ag-rev-flow-${tone}`}
          style={{ width: `${fill}%` }}
        />
        {gap > 0 ? (
          <span className="ag-rev-flow-gap" style={{ width: `${gap}%` }} />
        ) : null}
      </dd>
      <dd className="ag-rev-flow-amount">
        {money(amount, { currency: base, lang }) ?? "—"}
      </dd>
    </div>
  );
}

function MoveList({
  title,
  rows,
  brief,
  total,
  base,
  taxCurrency,
  focus,
  span,
}: {
  title: string;
  rows: ReviewRow[];
  brief: boolean;
  total: number;
  base: string;
  taxCurrency: string;
  focus: ReturnType<typeof useListFocus>;
  span: number;
}) {
  const lang = useLang();
  if (rows.length === 0) return null;
  const tone = total < 0 ? "down" : "up";
  return (
    <div className="ag-rev-mvs">
      <h3 className="ag-rev-mvs-head">
        <span>
          {title} <span className="ag-rev-mvs-n">{rows.length}</span>
        </span>
        <span className={`ag-rev-tone-${tone}`}>
          {money(total, { currency: base, lang, signed: true })}
        </span>
      </h3>
      <ul className="ag-rev-mv-list">
        {rows.map((row) => (
          <Move
            key={row.ticker}
            row={row}
            brief={brief}
            base={base}
            taxCurrency={taxCurrency}
            on={focus.on(row.ticker)}
            bind={focus.bind(row.ticker)}
            span={span}
          />
        ))}
      </ul>
    </div>
  );
}

function Move({
  row,
  brief,
  base,
  taxCurrency,
  on,
  bind,
  span,
}: {
  row: ReviewRow;
  brief: boolean;
  base: string;
  taxCurrency: string;
  on: boolean;
  bind: ReturnType<ReturnType<typeof useListFocus>["bind"]>;
  span: number;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const tone = verdictTone(row.verdict);
  const note =
    row.buy_after !== null ? (
      <span
        title={t("review.buy_after", {
          ticker: row.symbol,
          date: longDay(row.buy_after, lang),
        })}
      >
        {t("review.buy_after_short", { date: longDay(row.buy_after, lang) })}
      </span>
    ) : row.verdict === "add" || row.tax === null ? null : row.tax > 0 ? (
      <span
        title={t("review.move_tax", {
          amount: money(row.tax, { currency: taxCurrency, lang }) ?? na,
        })}
      >
        {t("review.move_tax_short", {
          amount: money(row.tax, { currency: taxCurrency, lang }) ?? na,
        })}
      </span>
    ) : (
      <span title={t("review.move_no_tax")}>{t("review.move_no_tax_short")}</span>
    );
  return (
    <li className={`ag-rev-mv${on ? " ag-rev-on" : ""}`} {...bind}>
      <div className="ag-rev-mv-who">
        <TickerCell ticker={row.ticker} />
        {/* "Sell" is the list's own title; a trim says so beside the name. */}
        {row.verdict === "trim" ? <VerdictChip row={row} /> : null}
      </div>
      <span className="ag-rev-mv-weights">
        <span>
          {row.held ? (percent(row.weight, { lang }) ?? na) : t("review.move_new")}
          <i aria-hidden="true">→</i>
          {percent(row.target_weight, { lang }) ?? na}
        </span>
        <WeightBar
          from={row.held ? row.weight : 0}
          to={row.target_weight}
          span={span}
        />
      </span>
      <b className={`ag-rev-mv-money ag-rev-tone-${tone}`}>
        {money(row.delta, { currency: base, lang, signed: true }) ?? na}
      </b>
      {/* What the move costs is part of the decision: shown folded too. */}
      {note ? <span className="ag-rev-mv-note">{note}</span> : null}
      {brief ? null : (
        <>
          <div className="ag-rev-mv-why">
            <Reasons reasons={row.reasons} limit={3} />
            <EntryBreaks lines={row.entry} />
          </div>
          <span className="ag-rev-mv-more">
            <DetailsButton row={row} variant="icon" taxCurrency={taxCurrency} />
          </span>
        </>
      )}
    </li>
  );
}

/**
 * The reader's own entry criteria a buy or an add breaks, said under its
 * reasons. A warning only: the verdict stays the review's, and a line the feed
 * could not read is not counted as broken.
 */
function EntryBreaks({ lines }: { lines?: EntryCheck[] }) {
  const t = useT();
  const lang = useLang();
  const broken = (lines ?? []).filter((line) => line.state === "fail");
  if (!broken.length) return null;
  return (
    <p className="ag-rev-entry" title={t("review.entry_help")}>
      {t("review.entry_breaks", {
        lines: broken.map((line) => entryText(line, t, lang)).join(" · "),
      })}
    </p>
  );
}

export function Reasons({ reasons, limit = 4 }: { reasons: string[]; limit?: number }) {
  const t = useT();
  const help = useHelp();
  if (reasons.length === 0) return null;
  return (
    <ul className="ag-rev-reasons">
      {reasons.slice(0, limit).map((code) => (
        <li key={code} title={help(`review.reason_${code}_help`)}>
          {t(`review.reason_${code}`)}
        </li>
      ))}
    </ul>
  );
}
