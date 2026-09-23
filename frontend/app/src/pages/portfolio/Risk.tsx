/**
 * Allocation & risk — two cards that answer two different questions, and the
 * reason they are never merged.
 *
 * "Real performance" is what the book actually did: the ledger's own TWR and
 * the IRR of the owner's cash flows. "Current basket risk" is today's
 * holdings backtested at fixed weights — a profile of what is held now, not a
 * performance figure. The two disagree by exactly as much as the book has
 * changed shape, and showing one in place of the other is the mistake this
 * layout is arranged to prevent.
 *
 * TWR and IRR get a tile each for the same reason: the TWR measures the
 * selection and is comparable against an index, the IRR measures what the
 * money did. Neither stands in for the other.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import {
  RISK_PERIODS,
  type Performance,
  type Risk as RiskData,
  type RiskPeriod,
} from "./api";
import { brokerName, decimal, moneyIn, percent } from "./format";
import { Donut, Heatmap, ReturnLines } from "./charts";
import { Caption, Card, Empty, Kpis, Segmented } from "./ui";

/** Allocation splits, in the order the Streamlit page lays them out. */
const SPLITS: [string, string][] = [
  ["sector", "portfolio.alloc_sector"],
  ["country", "portfolio.alloc_geography"],
  ["currency", "portfolio.alloc_currency"],
  ["broker", "portfolio.alloc_broker"],
];

export default function Risk() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);
  const [period, setPeriod] = useState<RiskPeriod>("1y");
  // Same axis labels as the history chart next door, for the same reason: two
  // charts of the same book should not date themselves differently.
  const date = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatDate = (iso: string) => date.format(new Date(`${iso}T00:00:00`));

  // Two calls, because only one of them depends on the window: changing the
  // period must not throw away the performance card and refetch the ledger.
  const performance = useApi(
    () => get<Performance>("/portfolio/performance", { base }),
    [base],
  );
  const risk = useApi(
    () => get<RiskData>("/portfolio/risk", { base, period }),
    [base, period],
  );

  return (
    <>
      <Card title={t("portfolio.real_perf")}>
        <Loaded query={performance} skeleton={<Skeleton rows={4} />}>
          {(data) => (
            <>
              <Kpis
                items={[
                  {
                    label: t("portfolio.annualised_return"),
                    value: percent(lang, data.twr_annualised, { signed: true }),
                    help: t("portfolio.twr_return_help"),
                  },
                  {
                    label: t("portfolio.mwr"),
                    value: percent(lang, data.irr, { signed: true }),
                    help: t("portfolio.mwr_help"),
                  },
                  // The same two readings the basket card below shows, taken
                  // over the flow-adjusted path instead of today's holdings at
                  // fixed weights — which is why they carry a different help
                  // and sit in a different card. Reading one for the other is
                  // the mistake both helps exist to prevent.
                  {
                    label: t("portfolio.annualised_vol"),
                    value: percent(lang, data.twr_volatility),
                    help: t("portfolio.twr_vol_help"),
                  },
                  {
                    label: t("portfolio.max_drawdown"),
                    value: percent(lang, data.twr_max_drawdown),
                    help: t("portfolio.twr_dd_help"),
                  },
                  {
                    label: t("portfolio.series_injected"),
                    value: money(data.injected),
                    help: t("portfolio.hist_note_injected"),
                  },
                  {
                    label: t("portfolio.market_value"),
                    value: money(data.value),
                  },
                ]}
              />
              <Caption>{t("portfolio.real_perf_note")}</Caption>
              {data.dropped_days.length ? (
                <Caption>
                  {t("portfolio.twr_note_skipped", {
                    days: data.dropped_days.join(", "),
                  })}
                </Caption>
              ) : null}
              {data.missing.length ? (
                <Caption>
                  {t("portfolio.twr_note_missing", {
                    tickers: data.missing.join(", "),
                  })}
                </Caption>
              ) : null}
            </>
          )}
        </Loaded>
      </Card>

      <Segmented
        label={t("portfolio.return_window")}
        options={RISK_PERIODS}
        value={period}
        onChange={setPeriod}
        format={(option) => (option === "max" ? t("portfolio.range_all") : option)}
      />

      <Loaded query={risk} skeleton={<Skeleton rows={10} />}>
        {(data) => {
          if (!Object.keys(data.weights).length) {
            return (
              <Empty
                title={t("portfolio.empty_risk_title")}
                body={t("portfolio.empty_risk_body")}
                cta={{ label: t("common.cta_import"), page: "import" }}
              />
            );
          }
          const betas = Object.entries(data.betas)
            .map(([bench, value]) => `β ${bench} ${decimal(lang, value) ?? ""}`)
            .join(" · ");
          return (
            <>
              <Card title={t("portfolio.basket_risk")}>
                <Kpis
                  items={[
                    {
                      label: t("portfolio.annualised_vol"),
                      value: percent(lang, data.volatility),
                      help: t("portfolio.basket_vol_help"),
                    },
                    {
                      label: t("portfolio.effective_names"),
                      value: decimal(lang, data.effective_names, 1),
                      help: t("portfolio.effective_names_help"),
                    },
                    {
                      label: t("portfolio.top5"),
                      value: percent(lang, data.top5_weight, { digits: 0 }),
                      help: t("portfolio.top5_help"),
                    },
                    {
                      label: t("portfolio.max_drawdown"),
                      value: percent(lang, data.max_drawdown),
                      help: t("portfolio.basket_dd_help"),
                    },
                  ]}
                />
                {betas ? (
                  <Caption>{t("portfolio.basket_beta_caption", { betas })}</Caption>
                ) : null}
              </Card>

              <Card title={t("portfolio.allocation")}>
                <div className="pf-donuts">
                  {SPLITS.map(([key, labelKey]) => {
                    const title = t(labelKey);
                    const slices = data.allocation[key] ?? [];
                    // Custody only joins when the book actually spans brokers,
                    // so the API omits it for a single-broker book rather than
                    // shipping a 100% slice that says nothing.
                    if (!slices.length) {
                      if (key === "broker") return null;
                      return (
                        <p className="pf-caption" key={key}>
                          {t("portfolio.no_alloc_data", { kind: title.toLowerCase() })}
                        </p>
                      );
                    }
                    return (
                      <Donut
                        key={key}
                        title={title}
                        otherLabel={t("portfolio.alloc_other")}
                        format={(fraction) => percent(lang, fraction) ?? ""}
                        slices={
                          key === "broker"
                            ? slices.map((slice) => ({
                                label: brokerName(slice.label, t),
                                weight: slice.weight,
                              }))
                            : slices
                        }
                      />
                    );
                  })}
                </div>
                {data.allocation["broker"]?.length ? (
                  <Caption>{t("portfolio.alloc_broker_caption")}</Caption>
                ) : null}
              </Card>

              {/* What the account earned, what today's holdings would have
                  earned over the same window, and each benchmark — one axis,
                  one zero, all rebased to the window's first day. The basket
                  is dotted because it is a backtest of a shape the book has
                  not always had, and a solid line would read as a record. */}
              {data.curves ? (
                <Card title={t("portfolio.cumulative_return")}>
                  <ReturnLines
                    dates={data.curves.dates}
                    format={(value) => percent(lang, value, { digits: 1 }) ?? ""}
                    formatDate={formatDate}
                    series={[
                      {
                        label: t("portfolio.series_portfolio_twr"),
                        points: data.curves.portfolio,
                      },
                      {
                        label: t("portfolio.series_current_basket"),
                        points: data.curves.basket,
                        dashed: true,
                      },
                      ...Object.entries(data.curves.benchmarks).map(
                        ([bench, points]) => ({ label: bench, points }),
                      ),
                    ]}
                  />
                  <Caption>{t("portfolio.twr_note")}</Caption>
                  {data.dropped_days.length ? (
                    <Caption>
                      {t("portfolio.twr_note_skipped", {
                        days: data.dropped_days.join(", "),
                      })}
                    </Caption>
                  ) : null}
                  {data.missing.length ? (
                    <Caption>
                      {t("portfolio.twr_note_missing", {
                        tickers: data.missing.join(", "),
                      })}
                    </Caption>
                  ) : null}
                </Card>
              ) : null}

              {Object.keys(data.correlation).length > 1 ? (
                <Card title={t("portfolio.return_correlation")}>
                  <Heatmap
                    matrix={data.correlation}
                    format={(value) => decimal(lang, value) ?? ""}
                  />
                </Card>
              ) : null}
            </>
          );
        }}
      </Loaded>
    </>
  );
}
