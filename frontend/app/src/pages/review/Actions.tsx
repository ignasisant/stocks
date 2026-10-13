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
 */

import { useLang, useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { Help } from "../../ui/Kpi";
import { DetailsButton, VerdictChip } from "./Explain";
import { useListFocus } from "./focus";
import { ACTIONS, longDay, money, percent, verdictTone } from "./format";
import type { Review, ReviewRow } from "./types";

export function Plan({ data }: { data: Review }) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const plan = data.plan;
  const moves = data.held.filter((row) => ACTIONS.includes(row.verdict));
  const out = moves
    .filter((row) => row.verdict !== "add")
    .sort((a, b) => (a.delta ?? 0) - (b.delta ?? 0));
  const into = moves
    .filter((row) => row.verdict === "add")
    .sort((a, b) => (b.delta ?? 0) - (a.delta ?? 0));
  const net = plan.buys - plan.sells;
  const scale = Math.max(plan.sells, plan.buys, 1);
  const focus = useListFocus(
    "plan",
    moves.map((row) => row.ticker),
  );

  return (
    <section className="ag-rev-card ag-rev-plan" aria-labelledby="ag-rev-plan-h">
      <h2 className="ag-rev-h2" id="ag-rev-plan-h">
        {t("review.plan_title")}
      </h2>
      {moves.length === 0 ? (
        <p className="ag-rev-caption">{t("review.moves_none")}</p>
      ) : (
        <>
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
                {money(Math.abs(net), data.base, lang) ?? na}
              </b>
              <span className="ag-rev-plan-tax">
                {t("review.plan_tax")}{" "}
                <b>{money(plan.tax, plan.tax_currency, lang) ?? na}</b>
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
                amount: money(-net, data.base, lang) ?? na,
              })}
            </p>
          ) : null}
          <div className={`ag-rev-plan-cols${focus.fading ? " ag-rev-fading" : ""}`}>
            <MoveList
              title={t("review.out_title")}
              rows={out}
              total={-plan.sells}
              base={data.base}
              taxCurrency={plan.tax_currency}
              focus={focus}
            />
            <MoveList
              title={t("review.in_title")}
              rows={into}
              total={plan.buys}
              base={data.base}
              taxCurrency={plan.tax_currency}
              focus={focus}
            />
          </div>
        </>
      )}
    </section>
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
      <dd className="ag-rev-flow-amount">{money(amount, base, lang) ?? "—"}</dd>
    </div>
  );
}

function MoveList({
  title,
  rows,
  total,
  base,
  taxCurrency,
  focus,
}: {
  title: string;
  rows: ReviewRow[];
  total: number;
  base: string;
  taxCurrency: string;
  focus: ReturnType<typeof useListFocus>;
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
        <span className={`ag-rev-tone-${tone}`}>{money(total, base, lang, true)}</span>
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
}: {
  row: ReviewRow;
  base: string;
  taxCurrency: string;
  on: boolean;
  bind: ReturnType<ReturnType<typeof useListFocus>["bind"]>;
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
          amount: money(row.tax, taxCurrency, lang) ?? na,
        })}
      >
        {t("review.move_tax_short", {
          amount: money(row.tax, taxCurrency, lang) ?? na,
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
        {percent(row.weight, lang) ?? na}
        <i aria-hidden="true">→</i>
        {percent(row.target_weight, lang) ?? na}
      </span>
      <b className={`ag-rev-mv-money ag-rev-tone-${tone}`}>
        {money(row.delta, base, lang, true) ?? na}
      </b>
      <div className="ag-rev-mv-why">
        <Reasons reasons={row.reasons} limit={3} />
      </div>
      {note ? <span className="ag-rev-mv-note">{note}</span> : null}
      <span className="ag-rev-mv-more">
        <DetailsButton row={row} variant="icon" taxCurrency={taxCurrency} />
      </span>
    </li>
  );
}

export function Reasons({ reasons, limit = 4 }: { reasons: string[]; limit?: number }) {
  const t = useT();
  if (reasons.length === 0) return null;
  return (
    <ul className="ag-rev-reasons">
      {reasons.slice(0, limit).map((code) => (
        <li key={code} title={t(`review.reason_${code}_help`)}>
          {t(`review.reason_${code}`)}
        </li>
      ))}
    </ul>
  );
}
