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
 * TWR and IRR share one figure — the TWR measures the selection and is
 * comparable against an index, the IRR (a chip beside it) measures what
 * the money did. Neither stands in for the other; the figure exists so a
 * reader sees both readings of the same window at once.
 *
 * Each card leads with its one figure (the yearly return, the simulated
 * swings) and the rest are facts under it, and each says in a line what it is:
 * the two cards share labels, so the scope has to be on the page, not only in
 * a tooltip.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { chart } from "../../shell/theme";
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
import { brokerName, compactMoneyIn, decimal, moneyIn, percent } from "./format";
import { Donut, ReturnLines, type LineMoney, type SliceDetail } from "./charts";
import { CorrelationCard } from "./Correlation";
import { Caption, Card, Chip, Empty, Hero, Lede, MissingPrices, Segmented } from "./ui";
import { maybe, sectorKey } from "../sentiment/format";

/** Allocation splits, in the order they are laid out. */
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
  const axisMoney = compactMoneyIn(lang, base);
  // Since inception by default: a window that reaches back before the first
  // trade scores years nobody held anything.
  const [period, setPeriod] = useState<RiskPeriod>("inception");
  // Today's holdings replayed over the past answer a second question — "is
  // what I hold now any good" — so their line waits to be asked for: shown
  // by default it was the one most often read as the account's own.
  const [basket, setBasket] = useState(false);
  // Same axis labels as the history chart next door, for the same reason: two
  // charts of the same book should not date themselves differently.
  const date = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatDate = (iso: string) => date.format(new Date(`${iso}T00:00:00`));
  // Two-digit years read "mar 24" as the 24th of March; where a date stands
  // alone, in a chip or a sentence, the year is written out.
  const longDate = new Intl.DateTimeFormat(lang, { month: "short", year: "numeric" });
  const formatMonth = (iso: string) => longDate.format(new Date(`${iso}T00:00:00`));
  const dayDate = new Intl.DateTimeFormat(lang, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const formatDay = (iso: string) => dayDate.format(new Date(`${iso}T00:00:00`));
  // What a slice's hover box and its pinned breakdown read its money with.
  const detail: SliceDetail = {
    money: (value, signed) => money(value, { signed }) ?? "",
    change: (fraction) => percent(lang, fraction, { signed: true }) ?? "",
    labels: {
      value: t("portfolio.alloc_value"),
      invested: t("portfolio.alloc_invested"),
      result: t("portfolio.alloc_result"),
      positions: t("portfolio.alloc_positions"),
      more: (count) => t("portfolio.alloc_more", { n: count }),
      pin: t("portfolio.alloc_pin_hint"),
      close: t("portfolio.alloc_close"),
      includes: (names) => t("portfolio.alloc_includes", { names }),
      note: t("portfolio.alloc_funds_note"),
    },
  };
  const lineMoney: Omit<LineMoney, "invested"> = {
    money: detail.money,
    change: detail.change,
    labels: {
      invested: t("portfolio.flow_tip_invested"),
      value: t("portfolio.alloc_value"),
      gain: t("portfolio.flow_tip_gain"),
      versus: t("portfolio.flow_tip_versus"),
    },
  };
  const palette = chart();
  // In the API's order (SPY, QQQ, EEM), so an index keeps its hue whichever
  // window is picked. Validated as a set against the card in both themes.
  const benchmarkColors = [
    palette.info,
    palette.warn,
    palette.warnOrange,
    palette.brandAccent,
  ];

  /** An index by the name a reader knows it by, the ticker when unnamed. */
  const benchName = (bench: string) =>
    maybe(t, `portfolio.bench_${bench.toLowerCase()}`) ?? bench;

  /** The chart's answer in one line: what the money made on the last day
      with money in, and how far that sits from the best index. */
  const flowLede = (curves: NonNullable<RiskData["curves"]>): string | null => {
    let day = -1;
    for (let i = curves.dates.length - 1; i >= 0 && day < 0; i--)
      if (curves.invested[i] != null && curves.portfolio[i] != null) day = i;
    if (day < 0) return null;
    const invested = curves.invested[day]!;
    const mine = curves.portfolio[day]!;
    const head = t("portfolio.flow_lede", {
      gain: money(invested * mine, { signed: true }) ?? "",
      pct: percent(lang, mine, { signed: true }) ?? "",
      invested: money(invested) ?? "",
    });
    let best: [string, number] | null = null;
    for (const [bench, points] of Object.entries(curves.benchmarks)) {
      const value = points[day];
      if (value != null && (best === null || value > best[1])) best = [bench, value];
    }
    if (best === null) return head;
    const gap = invested * (mine - best[1]);
    const tail = t(
      gap >= 0 ? "portfolio.flow_lede_ahead" : "portfolio.flow_lede_behind",
      {
        diff: money(Math.abs(gap)) ?? "",
        bench: benchName(best[0]),
      },
    );
    return `${head} ${tail}`;
  };

  // Two calls, one window. The selector sits above both cards and drives both:
  // the real-performance tiles are re-taken from the window's start (TWR, IRR
  // with the book's value on that day as the buy-in, volatility, drawdown), and
  // the basket is backtested over it. Two requests still, because they fail and
  // load independently — a slow price burst behind the basket must not hold the
  // ledger's own figures back.
  const performance = useApi(
    () => get<Performance>("/portfolio/performance", { base, window: period }),
    [base, period],
  );
  const risk = useApi(
    () => get<RiskData>("/portfolio/risk", { base, period }),
    [base, period],
  );

  return (
    <>
      <Segmented
        label={t("portfolio.return_window")}
        options={RISK_PERIODS}
        value={period}
        onChange={setPeriod}
        format={(option) =>
          option === "inception"
            ? t("portfolio.from_start")
            : t(`portfolio.period_${option}`)
        }
        // The window as dates, once the ledger has said which they are, and
        // which cards it moves: the allocation below is today's, whatever
        // the window.
        note={
          performance.state === "loaded" &&
          performance.data.start &&
          performance.data.end
            ? t("portfolio.period_span", {
                start: formatDay(performance.data.start),
                end: formatDay(performance.data.end),
              })
            : null
        }
      />

      <Card title={t("portfolio.real_perf")} sub={t("portfolio.real_perf_sub")}>
        <Loaded query={performance} skeleton={<Skeleton rows={4} />}>
          {(data) => (
            <>
              <Hero
                // Under a year of history the API hands back the cumulative
                // figure in `twr_annualised`; the label must not say "yearly".
                eyebrow={
                  data.twr_is_annual === false
                    ? t("portfolio.return_to_date")
                    : t("portfolio.annualised_return")
                }
                help={t("portfolio.twr_return_help")}
                value={percent(lang, data.twr_annualised, { signed: true })}
                // The IRR rides beside the TWR rather than in a figure of its
                // own: both are the window's return, just weighted
                // differently, and the mismatch between them (not either
                // alone) is what a reader is checking for. Under a year of
                // history it is a cumulative figure, and says so.
                sub={
                  data.irr === null ? null : (
                    <>
                      <Chip
                        value={data.irr}
                        text={`${t("portfolio.mwr_short")} ${
                          percent(lang, data.irr, { signed: true }) ?? ""
                        }`}
                      />
                      {data.irr_annualised === false ? (
                        <span>{t("portfolio.irr_not_annualised")}</span>
                      ) : null}
                    </>
                  )
                }
                facts={[
                  // The same two readings the simulated card below shows,
                  // taken over the flow-adjusted path instead of today's
                  // holdings at fixed weights — which is why they carry a
                  // different label and help. Reading one for the other is the
                  // mistake both exist to prevent.
                  {
                    label: t("portfolio.real_swings"),
                    value: percent(lang, data.twr_volatility),
                    help: t("portfolio.twr_vol_help"),
                  },
                  {
                    label: t("portfolio.real_drawdown"),
                    value: percent(lang, data.twr_max_drawdown),
                    // The number alone reads as "what the account lost", and
                    // on a TWR it is not: a fall on a €800 account of two
                    // coins counts as much as one on today's. When it ran and
                    // what was at stake is what makes it legible.
                    help:
                      data.twr_drawdown_peak && data.twr_drawdown_trough
                        ? t("portfolio.twr_dd_help_span", {
                            peak: formatMonth(data.twr_drawdown_peak),
                            trough: formatMonth(data.twr_drawdown_trough),
                            value:
                              money(data.twr_drawdown_peak_value) ?? t("portfolio.na"),
                          })
                        : t("portfolio.twr_dd_help"),
                    note:
                      data.twr_drawdown_peak && data.twr_drawdown_trough
                        ? t("portfolio.dd_span_chip", {
                            peak: formatMonth(data.twr_drawdown_peak),
                            trough: formatMonth(data.twr_drawdown_trough),
                          })
                        : null,
                  },
                  {
                    label: t("portfolio.market_value"),
                    value: (
                      <>
                        {money(data.value)}
                        {/* Measured against the window's buy-in, not the
                            all-time total: a figure under a window selector
                            has to obey it. */}
                        {data.value === null || data.injected_window == null ? null : (
                          <>
                            {" "}
                            <Chip
                              value={data.value - data.injected_window}
                              text={t("portfolio.gain_chip", {
                                gain:
                                  money(data.value - data.injected_window, {
                                    signed: true,
                                  }) ?? "",
                              })}
                            />
                          </>
                        )}
                      </>
                    ),
                    note:
                      data.injected_window == null
                        ? null
                        : t("portfolio.market_value_injected_help", {
                            injected: money(data.injected_window) ?? t("portfolio.na"),
                          }),
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
              <MissingPrices tickers={data.missing} />
            </>
          )}
        </Loaded>
      </Card>

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
              <Card
                title={t("portfolio.basket_risk")}
                sub={t("portfolio.basket_risk_sub")}
              >
                <Hero
                  eyebrow={t("portfolio.sim_swings")}
                  help={t("portfolio.basket_vol_help")}
                  value={percent(lang, data.volatility)}
                  facts={[
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
                      label: t("portfolio.sim_drawdown"),
                      value: percent(lang, data.max_drawdown),
                      help: t("portfolio.basket_dd_help"),
                    },
                  ]}
                />
                {betas ? (
                  <Caption>{t("portfolio.basket_beta_caption", { betas })}</Caption>
                ) : null}
              </Card>

              <Card title={t("portfolio.allocation")} sub={t("portfolio.alloc_sub")}>
                <div className="pf-donuts">
                  {SPLITS.map(([key, labelKey]) => {
                    const title = t(labelKey);
                    // The API's "Unknown" bucket (a fund's unclassified
                    // remainder, a holding with no sector) in the reader's
                    // words; the broker split has its own.
                    const slices = (data.allocation[key] ?? []).map((slice) =>
                      key !== "broker" && slice.label === "Unknown"
                        ? { ...slice, label: t("portfolio.alloc_unknown") }
                        : slice,
                    );
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
                        detail={detail}
                        slices={
                          key === "broker"
                            ? slices.map((slice) => ({
                                ...slice,
                                label: brokerName(slice.label, t),
                              }))
                            : key === "country"
                              ? slices.map((slice) =>
                                  slice.label === "Crypto"
                                    ? { ...slice, label: t("portfolio.alloc_crypto") }
                                    : slice,
                                )
                              : key === "sector"
                                ? slices.map((slice) => ({
                                    ...slice,
                                    label:
                                      maybe(
                                        t,
                                        `sentiment.sector_${sectorKey(slice.label)}`,
                                      ) ?? slice.label,
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

              {/* What the account's money became, against the same money —
                  same euros, same days — put into today's basket and into
                  each benchmark. Rebasing an index to the window's first day
                  would invest the whole book there at once, which it never
                  was. The basket is dotted because it is a backtest of a
                  shape the book has not always had. */}
              {data.curves ? (
                <Card title={t("portfolio.flow_matched_return")}>
                  <Lede>{flowLede(data.curves)}</Lede>
                  <ReturnLines
                    dates={data.curves.dates}
                    label={t("portfolio.flow_matched_return")}
                    format={(value) =>
                      percent(lang, value, { digits: 1, signed: true }) ?? ""
                    }
                    // Euros won or lost, the figure the legend prints: a
                    // percentage on the first months' few hundred euros drew
                    // swings that dwarfed years of the real book.
                    plot="gain"
                    tickFormat={(value) => axisMoney(value, { signed: true }) ?? ""}
                    formatDate={formatDate}
                    money={{
                      ...lineMoney,
                      invested: data.curves.invested,
                    }}
                    series={[
                      // The account in the ink the page's figures wear, as the
                      // system draws every real record; the basket a step back
                      // in secondary, and the benchmarks in the three hues
                      // that stay apart for every kind of colour vision.
                      {
                        label: t("portfolio.series_portfolio_actual"),
                        points: data.curves.portfolio,
                        color: palette.textPrimary,
                        focal: true,
                      },
                      ...(basket
                        ? [
                            {
                              label: t("portfolio.series_current_basket"),
                              points: data.curves.basket,
                              color: palette.textSecondary,
                              dashed: true,
                            },
                          ]
                        : []),
                      ...Object.entries(data.curves.benchmarks).map(
                        ([bench, points], index) => ({
                          label: benchName(bench),
                          points,
                          color: benchmarkColors[index] ?? palette.textMuted,
                        }),
                      ),
                    ]}
                  />
                  <button
                    type="button"
                    className="pf-legend-key pf-chart-toggle"
                    aria-pressed={basket}
                    onClick={() => setBasket((on) => !on)}
                  >
                    <span
                      className="pf-swatch pf-swatch-dashed"
                      style={{ background: palette.textSecondary }}
                    />
                    <span>{t("portfolio.flow_show_basket")}</span>
                  </button>
                  <Caption>{t("portfolio.flow_matched_note")}</Caption>
                  <MissingPrices tickers={data.missing} />
                </Card>
              ) : null}

              {/* A single name still gets the card, which says why there is
                  nothing to compare: it is where a reader looks for the answer. */}
              {Object.keys(data.correlation).length > 0 ? (
                <CorrelationCard data={data} />
              ) : null}
            </>
          );
        }}
      </Loaded>
    </>
  );
}
