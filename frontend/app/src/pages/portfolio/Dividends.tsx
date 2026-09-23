/**
 * Dividends — what the ledger was paid, and what the shares were entitled to.
 *
 * The two never merge into one number. A dividend is owed to whoever held the
 * share the day before it went ex, whether or not the import carried a row for
 * it, so the estimate is the only way to see a broker whose dividends never
 * import — but it is a guess, and a guess added to a receipt is neither. The
 * booked figure is the headline; the estimate rides beside it as a chip.
 *
 * `estimates_available: false` means the entitlement pass never ran, so every
 * estimate is null: the book may still pay, nobody could check. Those read
 * n/a, and never zero.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import type {
  DividendYear,
  Dividends as DividendsData,
  ForwardHolding,
  Positions,
} from "./api";
import { moneyIn, percent, shares as formatShares } from "./format";
import { Caption, Card, Empty, Figure, Info, Kpis, Table, TickerCell } from "./ui";
import type { Column } from "./ui";

export default function Dividends() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);

  // The positions come along for one figure only — yield on cost is the
  // estimate over what the open positions cost, commissions included.
  const query = useApi(
    () =>
      Promise.all([
        get<DividendsData>("/portfolio/dividends", { base }),
        get<Positions>("/portfolio/positions", { base }),
      ]).then(([dividends, positions]) => ({ dividends, positions })),
    [base],
  );

  const yearColumns: Column<DividendYear>[] = [
    {
      key: "year",
      label: t("portfolio.col_year"),
      left: true,
      sort: (row) => row.year,
      cell: (row) => row.year,
    },
    {
      key: "gross",
      label: t("portfolio.col_gross"),
      sort: (row) => row.gross,
      cell: (row) => <Figure value={money(row.gross)} />,
    },
    {
      key: "withheld",
      label: t("portfolio.col_withheld"),
      sort: (row) => row.withheld,
      cell: (row) => <Figure value={money(row.withheld)} />,
    },
    {
      key: "net",
      label: t("portfolio.col_net"),
      sort: (row) => row.net,
      cell: (row) => <Figure value={money(row.net)} />,
    },
    {
      key: "creditable",
      label: t("portfolio.col_creditable"),
      sort: (row) => row.creditable,
      cell: (row) => <Figure value={money(row.creditable)} />,
    },
    {
      key: "reclaimable",
      label: t("portfolio.col_reclaimable"),
      sort: (row) => row.reclaimable,
      cell: (row) => <Figure value={money(row.reclaimable)} />,
    },
  ];

  const estimateColumns: Column<DividendYear>[] = [
    {
      key: "year",
      label: t("portfolio.col_year"),
      left: true,
      sort: (row) => row.year,
      cell: (row) => row.year,
    },
    {
      key: "estimated",
      label: t("portfolio.col_estimated"),
      sort: (row) => row.estimated_gross,
      cell: (row) => <Figure value={money(row.estimated_gross)} />,
    },
    {
      key: "imported",
      label: t("portfolio.col_imported"),
      sort: (row) => row.gross,
      cell: (row) => <Figure value={money(row.gross)} />,
    },
    {
      key: "unrecorded",
      label: t("portfolio.col_unrecorded"),
      sort: (row) => row.unrecorded,
      cell: (row) => <Figure value={money(row.unrecorded)} />,
    },
  ];

  const forwardColumns: Column<ForwardHolding>[] = [
    {
      key: "ticker",
      label: t("portfolio.col_position"),
      left: true,
      sort: (row) => row.ticker,
      cell: (row) => <TickerCell ticker={row.ticker} />,
    },
    {
      key: "shares",
      label: t("portfolio.col_shares"),
      sort: (row) => row.shares,
      cell: (row) => <Figure value={formatShares(lang, row.shares)} />,
    },
    {
      key: "per_share",
      label: t("portfolio.col_per_share_ttm"),
      sort: (row) => row.per_share,
      // Per-share amounts stay in the name's own currency: averaging a US
      // quarterly dividend with a Spanish one into the reporting currency
      // would invent a number no company ever declared.
      cell: (row) => (
        <Figure value={moneyIn(lang, row.currency)(row.per_share, { digits: 2 })} />
      ),
    },
    {
      key: "payments",
      label: t("portfolio.col_payments_year"),
      sort: (row) => row.payments,
      cell: (row) => row.payments,
    },
    {
      key: "annual",
      label: t("portfolio.col_est_next12"),
      sort: (row) => row.gross_base,
      cell: (row) => <Figure value={money(row.gross_base)} />,
    },
  ];

  return (
    <Loaded query={query} skeleton={<Skeleton rows={8} />}>
      {({ dividends, positions }) => {
        // A year the estimate found but the ledger never booked still ships a
        // row, zeroed — it is how an import gap stays visible. Those belong in
        // the estimate table below, not in the one headed "recorded in your
        // ledger", so the ledger table keeps only the years with a receipt.
        const booked = dividends.years.filter(
          (year) => year.gross !== 0 || year.net !== 0 || year.withheld !== 0,
        );
        const estimated = dividends.years.filter(
          (year) => year.estimated_gross !== null,
        );
        if (!booked.length && !estimated.length && !dividends.forward.length) {
          return (
            <Empty
              title={t("portfolio.empty_dividends_title")}
              body={t("portfolio.empty_dividends_body")}
            />
          );
        }

        // The estimate beside a booked figure, only when it adds something: a
        // gap under a unit of currency is rounding, not an import gap.
        const chip = (estimate: number | null, bookedTotal: number) =>
          estimate !== null && estimate - bookedTotal >= 1
            ? {
                text: t("portfolio.div_kpi_est_chip", {
                  val: money(estimate) ?? "",
                }),
                value: null,
              }
            : null;

        const invested = positions.positions.reduce((sum, row) => sum + row.cost, 0);
        const forwardAnnual = dividends.forward_annual;

        return (
          <>
            <Kpis
              items={[
                {
                  label: t("portfolio.div_kpi_total"),
                  value: money(dividends.booked_total),
                  help: t("portfolio.div_kpi_total_help"),
                  chip: chip(dividends.estimated_total, dividends.booked_total),
                },
                {
                  label: t("portfolio.div_kpi_ytd"),
                  value: money(dividends.booked_ytd),
                  help: t("portfolio.div_kpi_ytd_help"),
                  chip: chip(dividends.estimated_ytd, dividends.booked_ytd),
                },
                {
                  label: t("portfolio.div_kpi_next"),
                  value: money(forwardAnnual),
                  help: t("portfolio.div_kpi_next_help"),
                },
              ]}
            />

            {booked.length ? (
              <Card title={t("portfolio.dividends_ledger_title")}>
                <Table
                  columns={yearColumns}
                  rows={booked}
                  rowKey={(row) => String(row.year)}
                  initial={{ key: "year", desc: true }}
                />
                <Caption>{t("portfolio.dividends_caption")}</Caption>
              </Card>
            ) : (
              // No dividend row was ever imported, yet the shares were paid:
              // say so before the estimates, so nothing below reads as a receipt.
              <Info>{t("portfolio.div_est_only")}</Info>
            )}

            {dividends.forward.length ? (
              <Card title={t("portfolio.div_forward_title")}>
                {/* No annual total here: it is the "Next year" tile above, and
                    the same number twice reads as two numbers. */}
                <Kpis
                  items={[
                    {
                      label: t("portfolio.div_monthly"),
                      value: money(forwardAnnual === null ? null : forwardAnnual / 12),
                      help: t("portfolio.div_monthly_help"),
                    },
                    {
                      label: t("portfolio.div_yield_on_cost"),
                      value:
                        invested && forwardAnnual !== null
                          ? percent(lang, forwardAnnual / invested, { digits: 2 })
                          : null,
                      help: t("portfolio.div_yield_on_cost_help"),
                    },
                  ]}
                />
                <Table
                  columns={forwardColumns}
                  rows={dividends.forward}
                  rowKey={(row) => row.ticker}
                  initial={{ key: "annual", desc: true }}
                />
                <Caption>{t("portfolio.div_forward_caption")}</Caption>
              </Card>
            ) : null}

            {estimated.length ? (
              <Card title={t("portfolio.div_history_title")}>
                <Table
                  columns={estimateColumns}
                  rows={estimated}
                  rowKey={(row) => String(row.year)}
                  initial={{ key: "year", desc: true }}
                />
                {(() => {
                  const missed = estimated.reduce(
                    (sum, year) => sum + (year.unrecorded ?? 0),
                    0,
                  );
                  return missed > 0.5 ? (
                    <Caption>
                      {t("portfolio.div_unrecorded_hint", { val: money(missed) ?? "" })}
                    </Caption>
                  ) : null;
                })()}
                <Caption>{t("portfolio.div_history_caption")}</Caption>
              </Card>
            ) : null}
          </>
        );
      }}
    </Loaded>
  );
}
