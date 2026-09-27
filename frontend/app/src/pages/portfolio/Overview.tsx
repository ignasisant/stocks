/**
 * Overview — the book in six numbers, and where its return stood each month.
 *
 * Every tile comes off an endpoint another tab already reads, so this tab and
 * that one cannot disagree: value, injected and the annualised return are
 * `/performance` since inception, the tax is this year's row of `/tax`, the
 * dividends `/dividends`' booked year-to-date, and the fees `/fees` narrowed
 * to this year. Each loads on its own, so a slow Yahoo behind the dividend
 * estimate does not hold the ledger's own figures back.
 *
 * The chart is `/monthly`: the return since the first trade at each month's
 * close, weighted by how much money was in and for how long, with the TWR
 * beside it as the flow-free comparison.
 */

import { get } from "../../shell/api";
import { useApi, type Query } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import type {
  Dividends,
  Fees,
  Monthly,
  MonthlyPoint,
  Performance,
  TaxReport,
} from "./api";
import { ReturnLines } from "./charts";
import { moneyIn, percent } from "./format";
import { Caption, Card, Kpis, Signed, Table, type Column } from "./ui";

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
  const monthly = useApi(() => get<Monthly>("/portfolio/monthly", { base }), [base]);

  const gain =
    performance.state === "loaded" &&
    performance.data.value !== null &&
    performance.data.injected
      ? performance.data.value / performance.data.injected - 1
      : null;

  const date = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatMonth = (iso: string) => date.format(new Date(`${iso}T00:00:00`));

  const columns: Column<MonthlyPoint>[] = [
    {
      key: "month",
      label: t("portfolio.overview_month"),
      left: true,
      sort: (row) => row.month,
      cell: (row) => formatMonth(row.date),
    },
    {
      key: "injected",
      label: t("portfolio.series_injected"),
      sort: (row) => row.injected,
      cell: (row) => money(row.injected) ?? t("portfolio.na"),
    },
    {
      key: "value",
      label: t("portfolio.market_value"),
      sort: (row) => row.value,
      cell: (row) => money(row.value) ?? t("portfolio.na"),
    },
    {
      key: "pnl",
      label: t("portfolio.hist_pnl"),
      sort: (row) => row.pnl,
      cell: (row) => <Signed value={row.pnl} text={money(row.pnl, { signed: true })} />,
    },
    {
      key: "money_weighted",
      label: t("portfolio.series_money_weighted"),
      sort: (row) => row.money_weighted,
      cell: (row) => (
        <Signed value={row.money_weighted} text={pct(row.money_weighted)} />
      ),
    },
    {
      key: "twr",
      label: t("portfolio.series_portfolio_twr"),
      sort: (row) => row.twr,
      cell: (row) => <Signed value={row.twr} text={pct(row.twr)} />,
    },
  ];

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
      <Card title={t("portfolio.overview_monthly_title")}>
        <Loaded query={monthly} skeleton={<Skeleton rows={6} />}>
          {(data) =>
            data.months.length < 2 ? (
              <Caption>{t("portfolio.not_enough_history")}</Caption>
            ) : (
              <>
                <ReturnLines
                  dates={data.months.map((row) => row.date)}
                  format={(value) => percent(lang, value, { digits: 1 }) ?? ""}
                  formatDate={formatMonth}
                  series={[
                    {
                      label: t("portfolio.series_money_weighted"),
                      points: data.months.map((row) => row.money_weighted),
                    },
                    {
                      label: t("portfolio.series_portfolio_twr"),
                      points: data.months.map((row) => row.twr),
                      dashed: true,
                    },
                  ]}
                />
                <Caption>
                  {t("portfolio.overview_monthly_note")}
                  {data.missing.length
                    ? ` ${t("portfolio.hist_note_missing", {
                        tickers: data.missing.join(", "),
                      })}`
                    : ""}
                </Caption>
                <Table
                  columns={columns}
                  rows={data.months}
                  rowKey={(row) => row.month}
                  initial={{ key: "month", desc: true }}
                />
              </>
            )
          }
        </Loaded>
      </Card>
    </>
  );
}
