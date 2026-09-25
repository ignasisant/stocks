/**
 * Fees — the commission the broker charged, and the spread it charged silently.
 *
 * They are never added into one number unless both are present. The commission
 * is a ledger fact; the spread is an estimate against the trade day's mid, and
 * it needs the day's bars. When those could not be fetched the API sends
 * `spread_measured: false` and every spread field null — which this tab shows
 * as "n/a". A zero there would claim the book executed at the midpoint, which
 * is the one number nobody measured.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import type { BrokerCost, Fees as FeesData } from "./api";
import { brokerName, decimal, moneyIn, percent } from "./format";
import { Caption, Card, Empty, Figure, Kpis, Signed, Table } from "./ui";
import type { Column } from "./ui";

export default function Fees() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);

  const query = useApi(() => get<FeesData>("/portfolio/fees", { base }), [base]);

  return (
    <Loaded query={query} skeleton={<Skeleton rows={8} />}>
      {(fees) => {
        if (!fees.brokers.length) {
          return (
            <Empty
              title={t("portfolio.empty_fees_title")}
              body={t("portfolio.empty_fees_body")}
              cta={{ label: t("common.cta_import"), page: "import" }}
            />
          );
        }

        // A standalone-charges column only where there are any: an all-zero
        // column is a column of noise.
        const anyOther = fees.brokers.some((broker) => broker.other_fees !== 0);
        const measured = fees.spread_measured;

        const columns: Column<BrokerCost>[] = [
          {
            key: "broker",
            label: t("portfolio.col_broker"),
            left: true,
            sort: (row) => row.broker,
            cell: (row) => brokerName(row.broker, t),
          },
          {
            key: "trades",
            label: t("portfolio.col_trades"),
            sort: (row) => row.trades,
            cell: (row) => row.trades,
          },
          {
            key: "volume",
            label: t("portfolio.col_volume"),
            sort: (row) => row.volume,
            cell: (row) => <Figure value={money(row.volume)} />,
          },
          {
            key: "commission",
            label: t("portfolio.col_commissions"),
            sort: (row) => row.commission,
            cell: (row) => <Figure value={money(row.commission, { digits: 2 })} />,
          },
          ...(anyOther
            ? [
                {
                  key: "other",
                  label: t("portfolio.col_other_fees"),
                  sort: (row: BrokerCost) => row.other_fees,
                  cell: (row: BrokerCost) => (
                    <Figure value={money(row.other_fees, { digits: 2 })} />
                  ),
                },
              ]
            : []),
          ...(measured
            ? [
                {
                  key: "spread",
                  label: t("portfolio.col_spread"),
                  sort: (row: BrokerCost) => row.spread,
                  // Signed: a negative spread means the execution beat the mid.
                  cell: (row: BrokerCost) => (
                    <Signed
                      value={row.spread === null ? null : -row.spread}
                      text={money(row.spread, { digits: 2 })}
                    />
                  ),
                },
                {
                  key: "spread_bps",
                  label: t("portfolio.col_spread_bps"),
                  sort: (row: BrokerCost) => row.spread_bps,
                  cell: (row: BrokerCost) => (
                    <Figure value={decimal(lang, row.spread_bps, 1)} />
                  ),
                },
              ]
            : []),
          {
            key: "total",
            label: t("portfolio.col_total_cost"),
            sort: (row) => row.total,
            cell: (row) => <Figure value={money(row.total, { digits: 2 })} />,
          },
          {
            key: "cost_pct",
            label: t("portfolio.col_cost_pct"),
            sort: (row) => row.cost_pct,
            cell: (row) => (
              <Figure value={percent(lang, row.cost_pct, { digits: 2 })} />
            ),
          },
        ];

        const measuredTrades = fees.brokers.reduce((sum, row) => sum + row.measured, 0);
        const skipped = fees.brokers.reduce((sum, row) => sum + row.skipped, 0);
        const outside = fees.brokers.reduce((sum, row) => sum + row.outside_range, 0);

        return (
          <Card title={t("portfolio.fees_title")}>
            <Kpis
              items={[
                {
                  label: t("portfolio.fees_explicit"),
                  value: money(fees.explicit, { digits: 2 }),
                  help: t("portfolio.fees_explicit_help"),
                },
                {
                  label: t("portfolio.fees_spread"),
                  value: money(fees.spread, { digits: 2 }),
                  help: t("portfolio.fees_spread_help"),
                },
                {
                  // "Fees plus estimated spread over volume" is not what an
                  // unmeasured pass computed — that figure is the commission
                  // alone — so it reads n/a rather than understating the cost.
                  label: t("portfolio.fees_pct_volume"),
                  value: measured ? percent(lang, fees.cost_pct, { digits: 2 }) : null,
                  help: t("portfolio.fees_pct_volume_help"),
                },
              ]}
            />
            <Table
              columns={columns}
              rows={fees.brokers}
              rowKey={(row) => row.broker}
              initial={{ key: "volume", desc: true }}
            />
            {measured && skipped ? (
              <Caption>
                {t("portfolio.fees_spread_coverage", {
                  measured: measuredTrades,
                  total: measuredTrades + skipped,
                })}
              </Caption>
            ) : null}
            {measured && outside > 0.005 ? (
              <Caption>
                {t("portfolio.fees_outside_range", {
                  val: money(outside, { digits: 2 }) ?? "",
                })}
              </Caption>
            ) : null}
            <Caption>{t("portfolio.fees_caption")}</Caption>
          </Card>
        );
      }}
    </Loaded>
  );
}
