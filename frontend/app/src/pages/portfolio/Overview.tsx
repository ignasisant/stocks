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
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { Kpi, KpiGrid, toneOf } from "../../ui/Kpi";
import {
  MONTHLY_WINDOWS,
  type Dividends,
  type Fees,
  type Monthly,
  type MonthlyWindow,
  type Performance,
  type TaxReport,
} from "./api";
import { BookAndRates } from "./charts";
import { compactMoneyIn, moneyIn, percent } from "./format";
import { Caption, Card, Kpis, Segmented } from "./ui";

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
  const pct = (value: number | null, signed = true) => percent(lang, value, { signed });

  const performance = useApi(
    () => get<Performance>("/portfolio/performance", { base }),
    [base],
  );
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

  return (
    <>
      <Card title={t("portfolio.overview_title", { ccy: base })}>
        <Kpis
          items={[
            {
              label: t("portfolio.overview_value"),
              value: read(performance, (data) => money(data.value)),
              chip: gain === null ? null : { text: pct(gain) ?? "", value: gain },
            },
            {
              label: t("portfolio.series_injected"),
              value: read(performance, (data) => money(data.injected)),
              help: t("portfolio.overview_injected_help"),
            },
            {
              label: t("portfolio.overview_annualised"),
              value: read(performance, (data) => pct(data.irr)),
              help: t("portfolio.overview_annualised_help", {
                twr:
                  performance.state === "loaded"
                    ? (pct(performance.data.twr_annualised) ?? t("portfolio.na"))
                    : "…",
              }),
            },
            {
              label: t("portfolio.overview_tax", { year }),
              value: read(tax, (data) => {
                const row = data.years.find((one) => one.period === String(year));
                return moneyIn(lang, data.currency)(row ? row.estimated_tax : 0);
              }),
              help: t("portfolio.overview_tax_help"),
            },
            {
              label: t("portfolio.overview_dividends", { year }),
              value: read(dividends, (data) => money(data.booked_ytd)),
            },
            {
              label: t("portfolio.overview_fees", { year }),
              value: read(fees, (data) => money(data.explicit)),
              help: t("portfolio.overview_fees_help"),
            },
          ]}
        />
      </Card>
      <MonthlyCard />
    </>
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
function MonthlyCard() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);
  const axisMoney = compactMoneyIn(lang, base);
  const [span, setSpan] = useState<MonthlyWindow>("inception");

  const monthly = useApi(
    () => get<Monthly>("/portfolio/monthly", { base, window: span }),
    [base, span],
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
      <Loaded query={monthly} skeleton={<Skeleton rows={8} />}>
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
            <>
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
              <BookAndRates
                points={data.months}
                series={[
                  {
                    label: moneyLabel,
                    points: data.months.map((row) => row.money_weighted),
                    tipNote: reading,
                  },
                  {
                    label: picksLabel,
                    points: data.months.map((row) => row.time_weighted),
                    dashed: true,
                    tipNote: reading,
                  },
                ]}
                bars={{
                  label: t("portfolio.overview_monthly_month"),
                  points: data.months.map((row) => row.month_return),
                  format: (value) =>
                    percent(lang, value, { digits: 1, signed: true }) ?? "",
                }}
                labels={{
                  invested: t("portfolio.series_injected"),
                  profit: t("portfolio.series_value_profit"),
                  loss: t("portfolio.series_value_loss"),
                  gain: t("portfolio.overview_bridge_gain"),
                }}
                money={(value, sign) => money(value, { signed: sign }) ?? ""}
                axisMoney={(value) => axisMoney(value) ?? ""}
                format={(value) => percent(lang, value, { digits: 1 }) ?? ""}
                formatDate={formatMonth}
              />
              {yearOne ? <Caption>{yearOne}</Caption> : null}
              <Caption>
                {t("portfolio.overview_monthly_note")}
                {data.missing.length
                  ? ` ${t("portfolio.hist_note_missing", {
                      tickers: data.missing.join(", "),
                    })}`
                  : ""}
              </Caption>
            </>
          );
        }}
      </Loaded>
    </Card>
  );
}
