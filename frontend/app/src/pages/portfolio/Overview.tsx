/**
 * Overview — the book in six numbers, and what its money did over a window.
 *
 * Every tile comes off an endpoint another tab already reads, so this tab and
 * that one cannot disagree: value, injected and the annualised return are
 * `/performance` since inception, the tax is this year's row of `/tax`, the
 * dividends `/dividends`' booked year-to-date, and the fees `/fees` narrowed
 * to this year. Each loads on its own, so a slow Yahoo behind the dividend
 * estimate does not hold the ledger's own figures back.
 *
 * The second card is `/monthly` over the window its selector picks, read in
 * euros before percentages: a bridge that adds up to today's value, the two
 * rates beside it with the timing of the trades put back into euros, then the
 * money and the rates on one date axis, each month's figures in its tooltip.
 * Under the since-inception lines, each month's own return stands as a bar:
 * there from the first month, when the annual lines wait for a year.
 */

import { useState } from "react";

import { get } from "../../shell/api";
import { useApi, type Query } from "../../shell/useApi";
import { Loaded, Refreshable, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { token } from "../../shell/theme";
import { Link } from "../../shell/router";
import { useBank, useCurrency } from "../../shell/session";
import { Kpi, KpiGrid, toneOf } from "../../ui/Kpi";
import {
  MONTHLY_WINDOWS,
  type Dividends,
  type Fees,
  type Monthly,
  type MonthlyWindow,
  type Summary,
  type TaxReport,
} from "./api";
import { BookAndRates } from "./charts";
import { Caption, Card, Kpis, MissingPrices, Segmented } from "./ui";
import { compactMoneyIn, moneyIn, percent } from "../../shell/format";

/** A tile's text while its call is out, and n/a once it has failed. */
function read<T>(query: Query<T>, pick: (data: T) => string | null): string | null {
  if (query.state === "loaded") return pick(query.data);
  return query.state === "loading" ? "…" : null;
}

export default function Overview() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);
  const year = new Date().getFullYear();
  const pct = (value: number | null, signed = true) => percent(value, { lang, signed });

  const performance = useApi(() => get("/portfolio/performance", { base }), [base]);
  const tax = useApi(() => get<TaxReport>("/portfolio/tax"), []);
  const dividends = useApi(
    () => get<Dividends>("/portfolio/dividends", { base }),
    [base],
  );
  const fees = useApi(() => get<Fees>("/portfolio/fees", { base, year }), [base, year]);

  const gain =
    performance.state === "loaded" &&
    performance.data.value !== null &&
    performance.data.injected
      ? performance.data.value / performance.data.injected - 1
      : null;

  const summary = useApi(() => get<Summary>("/portfolio/summary", { base }), [base]);
  const bank = useBank();
  const to = (tab: string, label: string) => (
    <Link page="portfolio" params={{ tab }} className="pf-go">
      {label} →
    </Link>
  );

  return (
    <>
      <Answer
        performance={performance}
        summary={summary}
        gain={gain}
        money={money}
        pct={pct}
      />
      <Card title={t("portfolio.overview_title", { ccy: base })}>
        <Kpis
          items={[
            {
              label: t("portfolio.overview_value"),
              value: read(performance, (data) => money(data.value)),
              chip:
                gain === null
                  ? null
                  : {
                      text: t("portfolio.chip_vs_injected", { pct: pct(gain) ?? "" }),
                      value: gain,
                    },
            },
            {
              label: t("portfolio.series_injected"),
              value: read(performance, (data) => money(data.injected)),
              help: t("portfolio.overview_injected_help"),
            },
            {
              label: t("portfolio.overview_annualised"),
              value: read(performance, (data) => pct(data.irr)),
              help: t(
                performance.state === "loaded" &&
                  performance.data.irr_annualised === false
                  ? "portfolio.overview_young_help"
                  : "portfolio.overview_annualised_help",
                {
                  twr:
                    performance.state === "loaded"
                      ? (pct(performance.data.twr_annualised) ?? t("portfolio.na"))
                      : "…",
                },
              ),
            },
            {
              label: t("portfolio.overview_tax", { year }),
              value: read(tax, (data) => {
                const row = data.years.find((one) => one.period === String(year));
                return moneyIn(lang, data.currency)(row ? row.estimated_tax : 0);
              }),
              help: t("portfolio.overview_tax_help"),
              note: to("tax", t("portfolio.tab_realized_tax")),
            },
            {
              label: t("portfolio.overview_dividends", { year }),
              value: read(dividends, (data) => money(data.booked_ytd)),
              note: to("dividends", t("portfolio.tab_dividends")),
            },
            {
              label: t("portfolio.overview_fees", { year }),
              value: read(fees, (data) => money(data.explicit)),
              help: t("portfolio.overview_fees_help"),
              note: to("fees", t("portfolio.tab_fees")),
            },
          ]}
        />
      </Card>
      <MonthlyCard />
      {/* Where the book's cash sits is not in the ledger; the bank is the one
          place that knows it, so the card is a door to it, for those who have
          one. */}
      {bank ? (
        <Card title={t("portfolio.cash_title")}>
          <p className="pf-caption">{t("portfolio.cash_body")}</p>
          <Link page="bank" className="ag-btn">
            {t("portfolio.cash_connect")}
          </Link>
        </Card>
      ) : null}
    </>
  );
}

/**
 * The answer first: what the book is worth and what it has made on what was
 * put in, then the two returns side by side, each saying what it measures.
 * The six tiles below stay as they were.
 */
function Answer({
  performance,
  summary,
  gain,
  money,
  pct,
}: {
  performance: Query<{
    value: number | null;
    injected: number | null;
    irr: number | null;
    irr_annualised: boolean;
    twr_annualised: number | null;
    twr_cumulative: number | null;
    twr_is_annual: boolean;
    start: string | null;
  }>;
  summary: Query<Summary>;
  gain: number | null;
  money: ReturnType<typeof moneyIn>;
  pct: (value: number | null, signed?: boolean) => string | null;
}) {
  const t = useT();
  const lang = useLang();
  if (performance.state !== "loaded" || performance.data.value === null) return null;
  const data = performance.data;
  const earned = data.injected ? data.value! - data.injected : null;
  const twr = data.twr_is_annual ? data.twr_annualised : data.twr_cumulative;
  // The two rates differ by what the dates of the deposits did, but only
  // where both are yearly: a young book's IRR is a run, its TWR another.
  const timing =
    data.irr_annualised && data.twr_is_annual && data.irr !== null && twr !== null
      ? data.irr - twr
      : null;
  const sold = summary.state === "loaded" ? summary.data.realized : null;
  const open = summary.state === "loaded" ? summary.data.pnl : null;
  const since = data.start
    ? new Intl.DateTimeFormat(lang, { month: "long", year: "numeric" }).format(
        new Date(`${data.start}T00:00:00`),
      )
    : null;
  return (
    <section className="pf-card pf-answer">
      <h2 className="pf-answer-h">
        {earned === null
          ? t("portfolio.answer_value", { value: money(data.value) ?? "" })
          : t("portfolio.answer_gain", {
              value: money(data.value) ?? "",
              gain: money(earned, { signed: true }) ?? "",
            })}
      </h2>
      {data.injected && gain !== null ? (
        <p className="pf-caption">
          {t("portfolio.answer_sub", {
            injected: money(data.injected) ?? "",
            since: since ?? "—",
          })}
          {sold !== null && open !== null
            ? ` ${t("portfolio.answer_split", {
                sold: money(sold, { signed: true }) ?? "",
                open: money(open, { signed: true }) ?? "",
              })}`
            : ""}
        </p>
      ) : null}
      <div className="pf-rets">
        <div>
          <small>{t("portfolio.ret_money")}</small>
          <b className={data.irr !== null && data.irr < 0 ? "pf-down" : "pf-up"}>
            {pct(data.irr) ?? t("portfolio.na")}
          </b>
          <span>
            {t(
              data.irr_annualised ? "portfolio.ret_irr_year" : "portfolio.ret_irr_run",
            )}
          </span>
        </div>
        <div>
          <small>{t("portfolio.ret_picks")}</small>
          <b className={twr !== null && twr < 0 ? "pf-down" : "pf-up"}>
            {pct(twr) ?? t("portfolio.na")}
          </b>
          <span>
            {t(data.twr_is_annual ? "portfolio.ret_twr_year" : "portfolio.ret_twr_run")}
          </span>
        </div>
      </div>
      {timing !== null ? (
        <p className="pf-caption">
          {t("portfolio.ret_gap", { pts: pct(timing) ?? "" })}{" "}
          {t(timing < 0 ? "portfolio.ret_gap_dear" : "portfolio.ret_gap_cheap")}
        </p>
      ) : null}
    </section>
  );
}

/**
 * The window's money, month by month.
 *
 * Its own component because the selector is its own: the six tiles above are
 * since inception whatever this card is showing. Read top to bottom, each row
 * answers the question the one before raises — how much is today's value made
 * of in this window (the bridge), what the dates of its trades were worth
 * (the timing tile, in euros too), and how the book's rates since its first
 * trade moved through it (the chart, whose tooltip carries each month's
 * figures). The window crops the chart and never rebases it: picking last
 * year zooms into the full chart rather than opening a book that day.
 */
type IndexHistory = { points: { date: string; in_index?: number | null }[] };

/** The index's level at each month-end the chart draws, carried forward over
    a gap and empty before the series opens. */
function indexAt(history: IndexHistory | null, dates: string[]): (number | null)[] {
  if (!history) return dates.map(() => null);
  const level = new Map<string, number>();
  for (const point of history.points) {
    if (point.in_index != null) level.set(point.date, point.in_index);
  }
  const days = [...level.keys()].sort();
  let at = 0;
  let last: number | null = null;
  return dates.map((date) => {
    while (at < days.length && days[at]! <= date) last = level.get(days[at++]!)!;
    return last;
  });
}

function MonthlyCard() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);
  const axisMoney = compactMoneyIn(lang, base);
  const [span, setSpan] = useState<MonthlyWindow>("inception");
  // The index with the book's own money, on until the reader takes it off.
  const [indexOn, setIndexOn] = useState(true);
  // From the book's first day whatever the window: a window that opens later
  // would forgive what the picks lost before it. Best-effort, and one call
  // for every window, so choosing one never re-fetches it.
  const shadow = useApi(
    () =>
      get<IndexHistory>("/portfolio/history", { base, window: "all", index: "true" }),
    [base],
  );

  // A window picked keeps the last chart up, dimmed, until the new one lands.
  const monthly = useApi(
    () => get<Monthly>("/portfolio/monthly", { base, window: span }),
    [base, span],
    { keep: true },
  );

  const date = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatMonth = (iso: string) => date.format(new Date(`${iso}T00:00:00`));
  const day = new Intl.DateTimeFormat(lang, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const formatDay = (iso: string) => day.format(new Date(`${iso}T00:00:00`));
  const long = new Intl.DateTimeFormat(lang, { month: "long", year: "numeric" });

  return (
    <Card title={t("portfolio.overview_monthly_title")}>
      <Segmented
        label={t("portfolio.return_window")}
        options={MONTHLY_WINDOWS}
        value={span}
        onChange={setSpan}
        format={(option) =>
          option === "inception" ? t("portfolio.from_start") : option.toUpperCase()
        }
      />
      <Loaded query={monthly} skeleton={<Skeleton shape="chart" />}>
        {(data) => {
          if (!data.months.length) {
            return <Caption>{t("portfolio.not_enough_history")}</Caption>;
          }
          // The lines are annual from the book's first birthday and, before
          // it, what the book made since its first trade — a few months
          // stretched to a year would exaggerate them. A window with any of
          // that first year in it drops "annual" from the legend, says in
          // each point's box which reading it is, and when they turn annual.
          const yearly = data.months.findIndex((row) => row.annual);
          const annual = yearly === 0;
          const moneyLabel = t(
            annual
              ? "portfolio.overview_monthly_irr"
              : "portfolio.overview_monthly_irr_plain",
          );
          const picksLabel = t(
            annual
              ? "portfolio.overview_monthly_twr"
              : "portfolio.overview_monthly_twr_plain",
          );
          const reading = (index: number) =>
            annual
              ? null
              : t(
                  data.months[index]?.annual
                    ? "portfolio.overview_monthly_tip_annual"
                    : "portfolio.overview_monthly_tip_run",
                );
          const yearOne = annual
            ? null
            : yearly > 0
              ? t("portfolio.overview_monthly_first_year", {
                  date: long.format(new Date(`${data.months[yearly]!.date}T00:00:00`)),
                })
              : t("portfolio.overview_monthly_young");
          // A window that opens on a real close starts from what the book was
          // worth there; the book's whole life starts from nothing, and a
          // "0 €" tile would be a term of the sum that says nothing.
          const opened = Boolean(data.opening) && data.start !== null;
          const signed = (value: number | null) => money(value, { signed: true });
          // Whole euros, and a float's −0.0000001 of a window with no trades
          // read as the zero it is — not a red "0 €".
          const timing = data.timing === null ? null : Math.round(data.timing) || 0;
          const steady =
            data.closing !== null && timing !== null ? data.closing - timing : null;

          const bridge = [
            ...(opened
              ? [
                  {
                    key: "opening",
                    label: t("portfolio.overview_bridge_opening", {
                      date: formatDay(data.start!),
                    }),
                    value: money(data.opening),
                  },
                ]
              : []),
            {
              key: "contributed",
              // The chart's dashed line is the injected total; a window's tile
              // is only what went in inside it, and says so.
              label: opened
                ? t("portfolio.overview_bridge_injected_window")
                : t("portfolio.series_injected"),
              value: opened ? signed(data.contributed) : money(data.contributed),
              note: t("portfolio.overview_bridge_contributed_note", {
                bought: money(data.bought) ?? t("portfolio.na"),
                sold: money(data.sold) ?? t("portfolio.na"),
              }),
              help: t("portfolio.overview_bridge_contributed_help"),
            },
            {
              key: "gain",
              label: opened
                ? t("portfolio.overview_bridge_gain_window")
                : t("portfolio.overview_bridge_gain"),
              value: signed(data.gain),
              tone: toneOf(data.gain),
              help: t("portfolio.overview_bridge_gain_help"),
            },
            {
              key: "closing",
              label: t("portfolio.overview_bridge_closing"),
              value: money(data.closing),
            },
          ];
          // The operator each term joins the sum with: the first stands alone,
          // the last is what it adds up to.
          const op = (index: number) =>
            index === 0 ? null : index === bridge.length - 1 ? "=" : "+";

          return (
            <Refreshable>
              <KpiGrid>
                {bridge.map((item, index) => (
                  <Kpi
                    key={item.key}
                    label={
                      <>
                        {op(index) ? <span className="pf-op">{op(index)}</span> : null}
                        {item.label}
                      </>
                    }
                    value={item.value ?? t("portfolio.na")}
                    valueTone={"tone" in item ? item.tone : null}
                    note={"note" in item ? item.note : null}
                    help={"help" in item ? item.help : null}
                  />
                ))}
                {/* Not a term of the sum — no operator — but the same window's
                    euros: what the dates of its trades were worth. */}
                <Kpi
                  label={t("portfolio.overview_timing")}
                  value={signed(timing) ?? t("portfolio.na")}
                  valueTone={toneOf(timing)}
                  note={
                    steady === null
                      ? null
                      : t("portfolio.overview_timing_note", {
                          amount: money(steady) ?? "",
                        })
                  }
                  help={t("portfolio.overview_timing_help")}
                />
              </KpiGrid>
              {shadow.state === "loaded" &&
              indexAt(
                shadow.data,
                data.months.map((row) => row.date),
              ).some((v) => v !== null) ? (
                <button
                  type="button"
                  className="pf-legend-key pf-chart-toggle"
                  aria-pressed={indexOn}
                  onClick={() => setIndexOn((on) => !on)}
                >
                  <span
                    className="pf-swatch"
                    style={{ background: token("series-4") }}
                  />
                  <span>{t("portfolio.overview_index_toggle")}</span>
                </button>
              ) : null}
              <BookAndRates
                points={data.months}
                index={
                  indexOn && shadow.state === "loaded"
                    ? {
                        label: t("portfolio.overview_index_toggle"),
                        points: indexAt(
                          shadow.data,
                          data.months.map((row) => row.date),
                        ),
                      }
                    : undefined
                }
                series={[
                  {
                    label: moneyLabel,
                    points: data.months.map((row) => row.money_weighted),
                    tipNote: reading,
                  },
                  {
                    label: picksLabel,
                    points: data.months.map((row) => row.time_weighted),
                    tipNote: reading,
                  },
                ]}
                bars={{
                  label: t("portfolio.overview_monthly_month"),
                  points: data.months.map((row) => row.month_return),
                  format: (value) =>
                    percent(value, { lang, digits: 1, signed: true }) ?? "",
                }}
                labels={{
                  invested: t("portfolio.series_injected"),
                  value: t("portfolio.hist_value"),
                  profit: t("portfolio.series_value_profit"),
                  loss: t("portfolio.series_value_loss"),
                  gain: t("portfolio.overview_bridge_gain"),
                }}
                money={(value, sign) => money(value, { signed: sign }) ?? ""}
                axisMoney={(value) => axisMoney(value) ?? ""}
                format={(value) => percent(value, { lang, digits: 1 }) ?? ""}
                formatDate={formatMonth}
              />
              {indexOn && shadow.state === "loaded" ? (
                <Caption>{t("portfolio.overview_index_note")}</Caption>
              ) : null}
              {yearOne ? <Caption>{yearOne}</Caption> : null}
              <Caption>
                {t("portfolio.overview_monthly_note")} {t("portfolio.span_hint")}
              </Caption>
              <MissingPrices tickers={data.missing} />
            </Refreshable>
          );
        }}
      </Loaded>
    </Card>
  );
}
