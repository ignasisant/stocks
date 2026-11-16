/**
 * The plan: what the read asks the reader to do, and what it costs.
 *
 * Two cards. The answer first: the plan in one sentence ("sell 2, trim 1 and
 * add to 3"), where the next contribution goes, and three figures beside it —
 * what the sales free, what the adds spend, and the sale's tax, because a
 * plan that frees cash and costs tax is two numbers, not one. What the adds
 * still need, or what the sales leave without a home, is said under it.
 *
 * Then "what to move", beside the names close to a move (`beside`) and under
 * the verdict split (`between`): one row a move, split by direction — the
 * sales and trims that free cash, then the adds that spend it, each list led
 * by its biggest amount. A row is the whole decision on one line of sight —
 * who and why, from which weight to which (drawn as a bar on one scale for
 * the whole plan), how much money, and what it costs in tax or when it can
 * be done; its details open in the dialog the tables' rows open. Holding is
 * not a move, so the quiet rows are the table's, not here. The adds the
 * sales cannot pay for come last, as what new money would buy, never as cash
 * the plan spends. The moves drawn against the S&P 500 over the tables'
 * window unfold under the lists.
 *
 * A plan that moves nothing is advice too, said as such: the book is fine as
 * it is today, and why — names a few points from a move, sales whose tax
 * would eat what they bring.
 *
 * Both cards share one focus and one fold, so the plan stays one component.
 */

import { type ReactNode, Suspense, lazy, useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { Icon } from "../../shell/Icon";
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

export function Plan({
  data,
  filtered = false,
  between,
  beside,
}: {
  data: Review;
  filtered?: boolean;
  /** Drawn between the answer and the moves: the verdict split. */
  between?: ReactNode;
  /** Drawn beside the moves: the names close to a move. */
  beside?: ReactNode;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const plan = data.plan;
  const { out, into } = planMoves(data);
  const moves = [...out, ...into];
  const waiting = waitingMoves(data);
  // Under one unit is no gap: sales and adds that match to the cent would
  // otherwise print "0 € with nowhere to go".
  const gap = plan.buys - plan.sells;
  const net = Math.abs(gap) < 1 ? 0 : gap;
  // Every weight bar in the plan on one scale, so a long bar is a big name.
  const span = weightSpan([...moves, ...waiting], data.total);
  const [open, setOpen] = useState(false);
  const returns = useReturns();
  const focus = useListFocus(
    "plan",
    moves.map((row) => row.ticker),
  );

  const answer = (
    <section className="ag-rev-card ag-rev-answer" aria-labelledby="ag-rev-plan-h">
      <div className="ag-rev-answer-main">
        <h2 className="ag-rev-eyebrow" id="ag-rev-plan-h">
          {t("review.plan_title")} · {jurisdictionLabel(data.jurisdiction, t)}
        </h2>
        {moves.length === 0 && filtered ? (
          <p className="ag-rev-answer-say">{t("review.moves_none")}</p>
        ) : moves.length === 0 ? (
          <Stay data={data} />
        ) : (
          <Headline data={data} out={out} into={into} />
        )}
        <Next rows={waiting} upcoming={data.investor_plan} base={data.base} />
        {net > 0 && moves.length > 0 ? (
          <p className="ag-rev-caption ag-rev-plan-note">
            {t("review.plan_need")}:{" "}
            <b>{money(net, { currency: data.base, lang }) ?? na}</b>
            <Help text={t("review.plan_net_help")} />
          </p>
        ) : null}
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
      </div>
      {moves.length > 0 ? (
        <div className="ag-rev-kpis-box">
          <dl className="ag-rev-kpis">
            <Figure
              label={t("review.plan_sells")}
              help={t("review.plan_sells_help")}
              value={money(plan.sells ? -plan.sells : 0, {
                currency: data.base,
                lang,
                signed: true,
              })}
              tone={plan.sells ? "down" : undefined}
              sub={t("review.kpi_names", { count: out.length })}
            />
            <Figure
              label={t("review.plan_buys")}
              help={t("review.plan_buys_help")}
              value={money(plan.buys, { currency: data.base, lang, signed: true })}
              tone={plan.buys ? "up" : undefined}
              sub={t("review.kpi_names", { count: into.length })}
            />
            <Figure
              label={t("review.plan_tax")}
              help={t("review.plan_tax_help", { code: data.jurisdiction })}
              value={money(plan.tax, { currency: plan.tax_currency, lang })}
              sub={
                plan.tax_currency && plan.tax_currency !== data.base
                  ? t("review.tax_in", { currency: plan.tax_currency })
                  : undefined
              }
            />
          </dl>
        </div>
      ) : null}
    </section>
  );

  // The moves the sales pay for, then what new money would buy. With
  // neither, the card goes and the names near a move take the whole row.
  const list =
    moves.length > 0 || waiting.length > 0 ? (
      <section className="ag-rev-card ag-rev-moves" aria-labelledby="ag-rev-moves-h">
        <h2 className="ag-rev-h2" id="ag-rev-moves-h">
          {t("review.moves_title")}
        </h2>
        <div className={`ag-rev-plan-cols${focus.fading ? " ag-rev-fading" : ""}`}>
          <MoveList
            title={t("review.out_title")}
            mark="sell"
            rows={out}
            total={-plan.sells}
            base={data.base}
            taxCurrency={plan.tax_currency}
            focus={focus}
            span={span}
          />
          <MoveList
            title={t("review.in_title")}
            mark="add"
            rows={into}
            total={plan.buys}
            base={data.base}
            taxCurrency={plan.tax_currency}
            focus={focus}
            span={span}
          />
          {waiting.length > 0 ? (
            <Waiting
              rows={waiting}
              total={plan.new_money ?? 0}
              book={data.total}
              base={data.base}
              span={span}
            />
          ) : null}
        </div>
        {open && returns ? (
          <Suspense fallback={null}>
            <PlanChart out={out} into={into} base={data.base} span={returns.span} />
          </Suspense>
        ) : null}
        {moves.length > 0 && returns ? (
          <button
            type="button"
            className="ag-rev-plan-toggle"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            {t(open ? "review.plan_chart_hide" : "review.plan_chart_show")}
          </button>
        ) : null}
      </section>
    ) : null;

  return (
    <>
      {answer}
      {between}
      <div className="ag-rev-pair">
        {list}
        {beside}
      </div>
    </>
  );
}

/** One of the answer's figures: what it is, the amount, and a line under. */
function Figure({
  label,
  help,
  value,
  tone,
  sub,
}: {
  label: string;
  help: string;
  value: string | null;
  tone?: "up" | "down";
  sub?: string;
}) {
  const t = useT();
  return (
    <div className="ag-rev-kpi">
      <dt>
        {label}
        <Help text={help} />
      </dt>
      <dd className={`ag-rev-kpi-value${tone ? ` ag-rev-tone-${tone}` : ""}`}>
        {value ?? t("review.na")}
      </dd>
      {sub ? <dd className="ag-rev-kpi-sub">{sub}</dd> : null}
    </div>
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
      <p className="ag-rev-answer-say">
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
    <div className="ag-rev-plan-next">
      <span className="ag-rev-plan-next-ico" aria-hidden="true">
        <Icon name="calendar_month" size={16} />
      </span>
      <p>
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
    </div>
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
      <p className="ag-rev-answer-say">{t("review.stay_title")}</p>
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
}: {
  rows: ReviewRow[];
  total: number;
  book: number | null;
  base: string;
  span: number;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  return (
    <div className="ag-rev-mvs">
      <h3 className="ag-rev-mvs-head">
        <span className="ag-rev-mvs-title ag-rev-mark-buy">
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
              <div className="ag-rev-mv-why">
                <Reasons
                  reasons={row.reasons.filter((code) => code !== "needs_new_money")}
                  limit={2}
                />
              </div>
              <span className="ag-rev-mv-more">
                <DetailsButton row={row} variant="icon" />
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function MoveList({
  title,
  mark,
  rows,
  total,
  base,
  taxCurrency,
  focus,
  span,
}: {
  title: string;
  mark: "sell" | "add";
  rows: ReviewRow[];
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
        <span className={`ag-rev-mvs-title ag-rev-mark-${mark}`}>
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
  base,
  taxCurrency,
  on,
  bind,
  span,
}: {
  row: ReviewRow;
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
      <div className="ag-rev-mv-why">
        <Reasons reasons={row.reasons} limit={3} />
        <EntryBreaks lines={row.entry} />
      </div>
      <span className="ag-rev-mv-more">
        <DetailsButton row={row} variant="icon" taxCurrency={taxCurrency} />
      </span>
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
