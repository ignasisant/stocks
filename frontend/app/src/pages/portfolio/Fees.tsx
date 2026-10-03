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
import { Caption, Card, Empty, Figure, Hero, ShareBar, Signed, Table } from "./ui";
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
        const costScale = Math.max(
          0,
          ...fees.brokers.map((row) => Math.abs(row.cost_pct ?? 0)),
        );
        const trades = fees.brokers.reduce((sum, row) => sum + row.trades, 0);

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
            // The one column that compares brokers fairly, so it gets the bar:
            // centred on zero, a broker that beat the mid runs left in green.
            cell: (row) => (
              <ShareBar
                signed
                share={
                  row.cost_pct === null || !costScale ? null : row.cost_pct / costScale
                }
              >
                <Signed
                  value={row.cost_pct === null ? null : -row.cost_pct}
                  text={percent(lang, row.cost_pct, { digits: 2 })}
                />
              </ShareBar>
            ),
          },
        ];

        const measuredTrades = fees.brokers.reduce((sum, row) => sum + row.measured, 0);
        const skipped = fees.brokers.reduce((sum, row) => sum + row.skipped, 0);
        const outside = fees.brokers.reduce((sum, row) => sum + row.outside_range, 0);

        return (
          <>
            <Card>
              {/* What trading cost, all in, leads — commission plus the spread
                paid against the day's mid. Unmeasured, that sum would be the
                commission dressed as the whole bill, so the commission leads
                under its own name and the spread reads n/a. */}
              <Hero
                eyebrow={
                  measured ? t("portfolio.fees_hero") : t("portfolio.fees_explicit")
                }
                value={money(
                  measured ? fees.explicit + (fees.spread ?? 0) : fees.explicit,
                  {
                    digits: 2,
                  },
                )}
                sub={
                  measured
                    ? t("portfolio.fees_hero_sub", {
                        pct: percent(lang, fees.cost_pct, { digits: 2 }) ?? "",
                        volume: money(fees.volume) ?? "",
                      })
                    : t("portfolio.fees_hero_sub_unmeasured", {
                        volume: money(fees.volume) ?? "",
                      })
                }
                facts={[
                  {
                    label: t("portfolio.fees_explicit"),
                    value: money(fees.explicit, { digits: 2 }),
                    help: t("portfolio.fees_explicit_help"),
                  },
                  {
                    label: t("portfolio.fees_spread"),
                    // Signed: a negative spread is executions that beat the mid.
                    value: (
                      <Signed
                        value={fees.spread === null ? null : -fees.spread}
                        text={money(fees.spread, { digits: 2 })}
                      />
                    ),
                    note:
                      fees.spread !== null && fees.spread < 0
                        ? t("portfolio.fees_spread_beat")
                        : null,
                    help: t("portfolio.fees_spread_help"),
                  },
                  { label: t("portfolio.col_trades"), value: String(trades) },
                ]}
              />
            </Card>
            <Card title={t("portfolio.fees_title")}>
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
          </>
        );
      }}
    </Loaded>
  );
}
