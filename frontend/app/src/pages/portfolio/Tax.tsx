/**
 * Realized & tax — the book's closed sales under the account's own jurisdiction.
 *
 * `/portfolio/tax` takes no `?base=`, on purpose: the ledger is replayed *at*
 * the jurisdiction's currency and under its own share-matching rule rather
 * than converted afterwards. A US filer's basis is USD at each trade date,
 * which is two rates and not one; a UK replay pools shares, so its parcels are
 * not the FIFO ones the rest of this page reports. Every figure on this tab is
 * therefore quoted in `report.currency`, never in the reporting currency.
 *
 * Nothing here branches on a country code. Wording follows the same convention
 * the Python side uses — `portfolio.<code>_<name>` when that string exists,
 * else the neutral `portfolio.<name>` — so a new jurisdiction is a module and
 * some copy, never an edit to this file.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useTaxWords } from "./taxWords";
import { TickerCell as Cell } from "../../shell/tickers";
import type { TaxFlag, TaxPeriod, TaxReport, TaxSale } from "./api";
import {
  compactMoneyIn,
  jurisdictionLabel,
  moneyIn,
  percent,
  shares as formatShares,
} from "./format";
import { PeriodBars, type TipRow } from "./charts";
import {
  Caption,
  Card,
  Chip,
  Dropdown,
  Empty,
  Figure,
  Kpis,
  Segmented,
  Signed,
  Table,
  TickerCell,
  Warn,
} from "./ui";
import type { Column } from "./ui";

/**
 * Which sales belong to which fiscal year.
 *
 * The API ships the sales as one flat list and each period's parcel count
 * beside it, and both are in date order — so consecutive slices land each sale
 * in its own period exactly, including where the year does not start in
 * January (the UK's opens on 6 April, so filtering on `sell_date[:4]` would be
 * wrong). If the counts and the list ever disagree the split is abandoned
 * rather than guessed at, and every sale is shown.
 */
function salesByPeriod(
  periods: TaxPeriod[],
  sales: TaxSale[],
): Map<string, TaxSale[]> | null {
  const counted = periods.reduce((sum, period) => sum + period.sales, 0);
  if (counted !== sales.length) return null;
  const split = new Map<string, TaxSale[]>();
  let at = 0;
  for (const period of periods) {
    split.set(period.period, sales.slice(at, at + period.sales));
    at += period.sales;
  }
  return split;
}

/** How many sales of each name a period holds and what they made, largest
    result (either way) first — what a bar is made of. */
export function salesByTicker(sales: TaxSale[]) {
  const byTicker = new Map<string, { ticker: string; count: number; gain: number }>();
  for (const sale of sales) {
    const one = byTicker.get(sale.ticker) ?? { ticker: sale.ticker, count: 0, gain: 0 };
    one.count += 1;
    one.gain += sale.gain;
    byTicker.set(sale.ticker, one);
  }
  return [...byTicker.values()].sort((a, b) => Math.abs(b.gain) - Math.abs(a.gain));
}

/** One position's sales in a period, added up: the row of the grouped table. */
export type PositionSales = {
  ticker: string;
  sales: number;
  first_buy: string;
  last_buy: string;
  first_sell: string;
  last_sell: string;
  quantity: number;
  cost: number;
  proceeds: number;
  gain: number;
};

/** The sales folded into one row per name, in the order the names first sold. */
export function salesByPosition(sales: TaxSale[]): PositionSales[] {
  const byTicker = new Map<string, PositionSales>();
  for (const sale of sales) {
    const one = byTicker.get(sale.ticker);
    if (!one) {
      byTicker.set(sale.ticker, {
        ticker: sale.ticker,
        sales: 1,
        first_buy: sale.buy_date,
        last_buy: sale.buy_date,
        first_sell: sale.sell_date,
        last_sell: sale.sell_date,
        quantity: sale.quantity,
        cost: sale.cost,
        proceeds: sale.proceeds,
        gain: sale.gain,
      });
      continue;
    }
    one.sales += 1;
    if (sale.buy_date < one.first_buy) one.first_buy = sale.buy_date;
    if (sale.buy_date > one.last_buy) one.last_buy = sale.buy_date;
    if (sale.sell_date < one.first_sell) one.first_sell = sale.sell_date;
    if (sale.sell_date > one.last_sell) one.last_sell = sale.sell_date;
    one.quantity += sale.quantity;
    one.cost += sale.cost;
    one.proceeds += sale.proceeds;
    one.gain += sale.gain;
  }
  return [...byTicker.values()];
}

/** A first–last date pair, one date when they are the same day. */
const span = (first: string, last: string) =>
  first === last ? first : `${first} – ${last}`;

/** Names listed in a bar's hover box before the rest fold into "+n more". */
const TIP_SALES = 6;

export default function Tax() {
  const t = useT();
  const query = useApi(() => get<TaxReport>("/portfolio/tax"), []);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={10} />}>
      {(report) =>
        report.years.length ? (
          <Report report={report} />
        ) : (
          // No CTA: nothing to configure — this filer simply has not sold yet.
          <Empty
            title={t("portfolio.empty_realized_title")}
            body={t("portfolio.empty_realized_body")}
          />
        )
      }
    </Loaded>
  );
}

/** The selector value that means "every finished year, added up". */
const ALL_YEARS = "all";

function Report({ report }: { report: TaxReport }) {
  const t = useT();
  const lang = useLang();
  const words = useTaxWords(report.jurisdiction);
  const money = moneyIn(lang, report.currency);
  const axisMoney = compactMoneyIn(lang, report.currency);
  // How the jurisdiction writes a tax year — "2025/26" in the UK and
  // Australia — while `period` stays the key the selector and the sales split
  // run on.
  const labelOf = (period: string) =>
    report.years.find((one) => one.period === period)?.year_label || period;
  const yearLabel = (option: string) =>
    option === ALL_YEARS ? t("portfolio.all_years") : labelOf(option);
  const periods = report.years.map((year) => year.period);
  const latest = periods[periods.length - 1] ?? "";
  const [year, setYear] = useState(latest);
  // The aggregate sits after the years. It only exists for a book with more
  // than one — a single year is already all of them, and an option that
  // repeats the view below it does nothing.
  const options = report.all_years ? [...periods, ALL_YEARS] : periods;
  const [grain, setGrain] = useState<"year" | "month">(
    report.years.length > 1 ? "year" : "month",
  );
  // A month bar clicked in the monthly view narrows the sales below to it.
  // Any other way of choosing what the card shows lets it go again.
  const [month, setMonth] = useState<string | null>(null);
  // Every parcel as its own row, or one row per name — a name sold in five
  // lots reads as five lines otherwise.
  const [group, setGroup] = useState<"sale" | "position">("sale");
  const pickYear = (next: string) => {
    setYear(next);
    setMonth(null);
  };

  const selected =
    report.years.find((period) => period.period === year) ?? report.years[0];
  if (!selected) return null;

  // One shape for the card below, whether it is showing a tax year or the
  // history of all of them. The aggregate carries no `net_taxable` of its own
  // on purpose — brackets restart every year, so there is no such figure —
  // which is why the card reads its totals off the KPI list either way.
  const total = year === ALL_YEARS ? report.all_years : null;
  const shown = total
    ? {
        kpis: total.kpis,
        realized_gain: total.realized_gain,
        deductible_loss: total.deductible_loss,
      }
    : selected;

  const split = salesByPeriod(report.years, report.sales);
  const monthSales = month
    ? report.sales.filter((sale) => sale.sell_date.startsWith(month))
    : null;
  const sales =
    monthSales ??
    (total ? report.sales : (split?.get(selected.period) ?? report.sales));

  // The fiscal year a month falls in: the one whose sales hold it — the UK's
  // year straddles two calendar years — else the calendar year it names.
  const yearOf = (period: string) =>
    report.years.find((one) =>
      split?.get(one.period)?.some((sale) => sale.sell_date.startsWith(period)),
    )?.period ?? (periods.includes(period.slice(0, 4)) ? period.slice(0, 4) : year);
  const monthName = (period: string) => {
    const [y, m] = period.split("-").map(Number);
    if (!y || !m) return period;
    return new Intl.DateTimeFormat(lang, { month: "long", year: "numeric" }).format(
      new Date(y, m - 1, 1),
    );
  };
  const bars: TaxPeriod[] = grain === "year" ? report.years : report.months;
  const barSales =
    grain === "year" ? split : salesByPeriod(report.months, report.sales);

  // What a bar's box adds to its four figures: the tax that year, the losses
  // the anti-churn rule held back, how many sales — and which names they were.
  const barDetail = (period: TaxPeriod) => {
    const rows: TipRow[] = [];
    if (period.disallowed_loss > 0)
      rows.push({
        label: words.say("tip_deferred"),
        value: money(period.disallowed_loss) ?? "",
      });
    // Brackets apply to the whole year: a month has no tax of its own.
    if (grain === "year") {
      rows.push({
        label: words.say("estimated_tax"),
        value: money(period.estimated_tax) ?? "",
      });
      if (period.net_taxable > 0 && period.estimated_tax > 0)
        rows.push({
          label: t("portfolio.tip_effective_rate"),
          value:
            percent(lang, period.estimated_tax / period.net_taxable, { digits: 1 }) ??
            "",
        });
      if (period.carryforward_loss > 0)
        rows.push({
          label: words.say("carryforward_loss"),
          value: money(period.carryforward_loss) ?? "",
        });
    }
    rows.push({ label: t("portfolio.tip_sales"), value: String(period.sales) });
    const names = salesByTicker(barSales?.get(period.period) ?? []);
    const hint = grain === "year" ? period.period !== year : period.period !== month;
    if (!names.length && !hint) return { rows };
    return {
      rows,
      body: (
        <span className="pf-tip-holdings">
          {names.length ? (
            <span className="pf-tip-head pf-tip-span">
              {t("portfolio.tip_by_ticker")}
            </span>
          ) : null}
          {names.slice(0, TIP_SALES).map((one) => (
            <span className="pf-tip-holding" key={one.ticker}>
              <Cell
                ticker={one.ticker}
                name={false}
                className="pf-ticker pf-tip-tick"
              />
              <span className="pf-muted">
                {one.count === 1
                  ? t("portfolio.tip_sale_one")
                  : t("portfolio.tip_sale_count", { n: one.count })}
              </span>
              <span
                className={`pf-donut-figure ${one.gain >= 0 ? "pf-up" : "pf-down"}`}
              >
                {money(one.gain, { signed: true })}
              </span>
            </span>
          ))}
          {names.length > TIP_SALES ? (
            <span className="pf-muted">
              {t("portfolio.alloc_more", { n: names.length - TIP_SALES })}
            </span>
          ) : null}
          {hint ? (
            <span className="pf-tip-hint">
              {t(
                grain === "year"
                  ? "portfolio.tip_pick_year"
                  : "portfolio.tip_pick_month",
              )}
            </span>
          ) : null}
        </span>
      ),
    };
  };

  return (
    <>
      {report.years.length > 1 || report.months.length > 1 ? (
        <Card>
          <Segmented
            label={t("portfolio.realized_granularity")}
            options={["year", "month"] as const}
            value={grain}
            onChange={(next) => {
              setGrain(next);
              setMonth(null);
            }}
            format={(option) =>
              t(
                option === "year"
                  ? "portfolio.granularity_year"
                  : "portfolio.granularity_month",
              )
            }
          />
          <h2>
            {t(
              grain === "year"
                ? "portfolio.realized_by_year"
                : "portfolio.realized_by_month",
            )}
          </h2>
          <PeriodBars
            periods={bars}
            labels={{
              gains: words.say("chart_gains"),
              dividends: words.say("chart_dividends"),
              losses: words.say("chart_losses"),
              recovered: words.say("chart_recovered"),
              net: words.say("chart_net"),
            }}
            money={(value) => money(value) ?? ""}
            axisMoney={(value) => axisMoney(value) ?? ""}
            detail={barDetail}
            onPick={(period) => {
              if (grain === "year") return pickYear(period.period);
              setYear(yearOf(period.period));
              setMonth(period.period);
            }}
            picked={grain === "year" ? year : (month ?? undefined)}
          />
          <Caption>{words.say("realized_by_year_caption")}</Caption>
          {grain === "month" ? (
            <Caption>{words.say("realized_by_month_caption")}</Caption>
          ) : null}
        </Card>
      ) : null}

      <Card>
        <div className="pf-controls-bar">
          {/* Few fiscal years read faster as buttons than as a dropdown — up to
            four options counting "all years". */}
          {options.length <= 4 ? (
            <Segmented
              label={words.say("fiscal_year")}
              options={options}
              value={year}
              onChange={pickYear}
              format={yearLabel}
            />
          ) : (
            <Dropdown
              label={words.say("fiscal_year")}
              // Newest first, the way the dropdown opens on it; the all-years
              // entry stays at the bottom, after the years.
              options={[...periods]
                .reverse()
                .concat(report.all_years ? [ALL_YEARS] : [])}
              value={year}
              onChange={pickYear}
              format={yearLabel}
            />
          )}
          {sales.length ? (
            <Segmented
              label={t("portfolio.tax_group")}
              options={["sale", "position"] as const}
              value={group}
              onChange={setGroup}
              format={(option) =>
                t(
                  option === "sale"
                    ? "portfolio.tax_group_sale"
                    : "portfolio.tax_group_position",
                )
              }
            />
          ) : null}
        </div>
        <h2>
          {total
            ? words.say("all_years_header")
            : words.say("tax_header", { year: labelOf(selected.period) })}
        </h2>
        <Caption>{words.say(total ? "all_years_caption" : "tax_caption")}</Caption>
        {/* The browser named a country this app does not model, so everything
            on this tab is another country's law applied to this book. Say it
            here, where the wrong numbers are. */}
        {report.resolved === "unmodelled" ? (
          <Warn>
            {t("portfolio.tax_unmodelled", {
              region: browserRegion(),
              label: jurisdictionLabel(report.jurisdiction, t),
            })}
          </Warn>
        ) : null}
        <Kpis
          items={shown.kpis.map((kpi) => ({
            label: words.say(kpi.name),
            value: money(kpi.value),
            help: words.say(kpi.help),
          }))}
        />
        <Caption>
          {t("portfolio.realized_summary", {
            gain: money(shown.realized_gain) ?? "",
            loss: money(shown.deductible_loss) ?? "",
          })}
          {/* Every sentence the jurisdiction appends to the year — a deferred
              loss, an allowance used, a fund exemption nobody could apply —
              in its own wording, run on after the summary. The aggregate
              carries none: every note is about one year. */}
          {total
            ? null
            : selected.notes.map((note) => words.say(note.key, note.kwargs)).join("")}
          {total || report.jurisdiction !== "es"
            ? null
            : ` = ${money(selected.net_taxable) ?? ""}`}
        </Caption>
        {month ? (
          <div className="pf-filter" role="status">
            <span>
              {t("portfolio.tax_month_filter", {
                month: monthName(month),
                n: sales.length,
                result:
                  money(
                    sales.reduce((sum, sale) => sum + sale.gain, 0),
                    { signed: true },
                  ) ?? "",
              })}
            </span>
            <button
              type="button"
              className="ag-btn pf-zoom-reset"
              onClick={() => setMonth(null)}
            >
              {t("portfolio.tax_month_clear")}
            </button>
          </div>
        ) : null}
        {sales.length ? (
          group === "sale" ? (
            <SalesTable report={report} sales={sales} />
          ) : (
            <PositionsTable report={report} sales={sales} />
          )
        ) : null}
        {report.flags.map((flag) => (
          <Caption key={flag.name}>{flagCaption(flag, words, money)}</Caption>
        ))}
      </Card>
      <Caption>{words.say("planning_aid")}</Caption>
    </>
  );
}

function SalesTable({ report, sales }: { report: TaxReport; sales: TaxSale[] }) {
  const t = useT();
  const lang = useLang();
  const words = useTaxWords(report.jurisdiction);
  const money = moneyIn(lang, report.currency);

  // Under pooling a "cost" can be an average, so the rule that produced it
  // belongs next to it. FIFO is the default everywhere and the rest of this
  // page already says so, hence the column only where the replay did something
  // else — read off the data, never off a country code.
  const rules = new Set(sales.map((sale) => sale.matched));
  const showMatched = rules.size > 1 || !["fifo", "lifo"].includes(report.matching);

  const columns: Column<TaxSale>[] = [
    {
      key: "ticker",
      label: t("portfolio.col_position"),
      left: true,
      sort: (row) => row.ticker,
      cell: (row) => <TickerCell ticker={row.ticker} />,
    },
    {
      key: "buy",
      label: t("portfolio.col_bought"),
      left: true,
      sort: (row) => row.buy_date,
      cell: (row) => <span className="pf-muted">{row.buy_date}</span>,
    },
    {
      key: "sell",
      label: t("portfolio.col_sold"),
      left: true,
      sort: (row) => row.sell_date,
      cell: (row) => <span className="pf-muted">{row.sell_date}</span>,
    },
    // Holding period only where the rate turns on it (US short vs long term);
    // the API leaves `term` null everywhere else, so the column follows the
    // data rather than a country code.
    ...(sales.some((sale) => sale.term)
      ? [
          {
            key: "term",
            label: words.say("col_term"),
            left: true,
            sort: (row: TaxSale) => row.term,
            cell: (row: TaxSale) => (
              <span className="pf-muted">
                {row.term ? words.say(`term_${row.term}`) : ""}
              </span>
            ),
          },
        ]
      : []),
    ...(showMatched
      ? [
          {
            key: "matched",
            label: t("portfolio.col_matched"),
            left: true,
            sort: (row: TaxSale) => row.matched,
            cell: (row: TaxSale) => (
              <span className="pf-muted">{words.say(`match_${row.matched}`)}</span>
            ),
          },
        ]
      : []),
    {
      key: "qty",
      label: t("portfolio.col_shares"),
      sort: (row) => row.quantity,
      cell: (row) => <Figure value={formatShares(lang, row.quantity, true)} />,
    },
    {
      key: "cost",
      label: t("portfolio.cost_basis"),
      sort: (row) => row.cost,
      cell: (row) => <Figure value={money(row.cost, { digits: 2 })} />,
    },
    {
      key: "proceeds",
      label: t("portfolio.col_proceeds"),
      sort: (row) => row.proceeds,
      // A sale at nothing is a write-off (delisting, bankruptcy), not a
      // trade: say so beside the zero.
      cell: (row) => (
        <>
          <Figure value={money(row.proceeds, { digits: 2 })} />
          {row.proceeds <= 0 && row.cost > 0 ? (
            <span className="pf-muted"> {t("portfolio.sale_written_off")}</span>
          ) : null}
        </>
      ),
    },
    {
      key: "gain",
      label: t("portfolio.col_gain"),
      sort: (row) => row.gain,
      cell: (row) => {
        // Return on the cost of the shares this sale consumed — the reference
        // beside the nominal, exactly as the Positions table pairs them.
        const pct = row.cost ? row.gain / row.cost : null;
        return (
          <span className="pf-pair">
            <Signed
              value={row.gain}
              text={money(row.gain, { digits: 2, signed: true })}
            />
            {pct === null ? null : (
              <Chip value={pct} text={percent(lang, pct, { signed: true })} />
            )}
          </span>
        );
      },
    },
  ];

  return (
    <Table
      columns={columns}
      rows={sales}
      rowKey={(row, index) => `${row.ticker}-${row.sell_date}-${index}`}
      initial={{ key: "sell", desc: true }}
      dense={{
        ticker: (row) => row.ticker,
        badge: (row) =>
          row.cost ? (
            <Chip
              value={row.gain / row.cost}
              text={percent(lang, row.gain / row.cost, { signed: true })}
            />
          ) : null,
        value: (row) => <Figure value={money(row.proceeds, { digits: 2 })} />,
        delta: (row) => (
          <Signed
            value={row.gain}
            text={money(row.gain, { digits: 2, signed: true })}
          />
        ),
        sub: (row) => [
          `${t("portfolio.col_bought")} ${row.buy_date}`,
          `${t("portfolio.col_sold")} ${row.sell_date}`,
          `${t("portfolio.col_shares")} ${formatShares(lang, row.quantity, true) ?? ""}`,
        ],
        wrap: true,
      }}
    />
  );
}

/** The same sales, one row per name: what each position made in the period. */
function PositionsTable({ report, sales }: { report: TaxReport; sales: TaxSale[] }) {
  const t = useT();
  const lang = useLang();
  const money = moneyIn(lang, report.currency);
  const rows = salesByPosition(sales);
  const pctOf = (row: PositionSales) => (row.cost ? row.gain / row.cost : null);

  const columns: Column<PositionSales>[] = [
    {
      key: "ticker",
      label: t("portfolio.col_position"),
      left: true,
      sort: (row) => row.ticker,
      cell: (row) => <TickerCell ticker={row.ticker} />,
    },
    {
      key: "count",
      label: t("portfolio.col_sales"),
      sort: (row) => row.sales,
      cell: (row) => <Figure value={String(row.sales)} />,
    },
    {
      key: "buy",
      label: t("portfolio.col_bought"),
      left: true,
      sort: (row) => row.first_buy,
      cell: (row) => (
        <span className="pf-muted">{span(row.first_buy, row.last_buy)}</span>
      ),
    },
    {
      key: "sell",
      label: t("portfolio.col_sold"),
      left: true,
      sort: (row) => row.last_sell,
      cell: (row) => (
        <span className="pf-muted">{span(row.first_sell, row.last_sell)}</span>
      ),
    },
    {
      key: "qty",
      label: t("portfolio.col_shares"),
      sort: (row) => row.quantity,
      cell: (row) => <Figure value={formatShares(lang, row.quantity, true)} />,
    },
    {
      key: "cost",
      label: t("portfolio.cost_basis"),
      sort: (row) => row.cost,
      cell: (row) => <Figure value={money(row.cost, { digits: 2 })} />,
    },
    {
      key: "proceeds",
      label: t("portfolio.col_proceeds"),
      sort: (row) => row.proceeds,
      cell: (row) => <Figure value={money(row.proceeds, { digits: 2 })} />,
    },
    {
      key: "gain",
      label: t("portfolio.col_gain"),
      sort: (row) => row.gain,
      cell: (row) => {
        const pct = pctOf(row);
        return (
          <span className="pf-pair">
            <Signed
              value={row.gain}
              text={money(row.gain, { digits: 2, signed: true })}
            />
            {pct === null ? null : (
              <Chip value={pct} text={percent(lang, pct, { signed: true })} />
            )}
          </span>
        );
      },
    },
  ];

  return (
    <Table
      columns={columns}
      rows={rows}
      rowKey={(row) => row.ticker}
      initial={{ key: "gain", desc: true }}
      dense={{
        ticker: (row) => row.ticker,
        badge: (row) => {
          const pct = pctOf(row);
          return pct === null ? null : (
            <Chip value={pct} text={percent(lang, pct, { signed: true })} />
          );
        },
        value: (row) => <Figure value={money(row.proceeds, { digits: 2 })} />,
        delta: (row) => (
          <Signed
            value={row.gain}
            text={money(row.gain, { digits: 2, signed: true })}
          />
        ),
        sub: (row) => [
          row.sales === 1
            ? t("portfolio.tip_sale_one")
            : t("portfolio.tip_sale_count", { n: row.sales }),
          `${t("portfolio.col_sold")} ${span(row.first_sell, row.last_sell)}`,
          `${t("portfolio.col_shares")} ${formatShares(lang, row.quantity, true) ?? ""}`,
        ],
        wrap: true,
      }}
    />
  );
}

/**
 * One foreign-asset reporting line.
 *
 * The outer sentence is `flag_<name>` with the inner clause (`_reportable` or
 * `_ok`, carrying the total and the threshold) as its `message`. A flag nobody
 * worded falls back to the neutral `flag_default` set: shown generically beats
 * shown as a raw key.
 */
function flagCaption(
  flag: TaxFlag,
  words: ReturnType<typeof useTaxWords>,
  money: ReturnType<typeof moneyIn>,
): string {
  const name = words.has(`flag_${flag.name}`) ? `flag_${flag.name}` : "flag_default";
  const inner = words.say(flag.reportable ? `${name}_reportable` : `${name}_ok`, {
    val: money(flag.total_value) ?? "",
    threshold: money(flag.threshold) ?? "",
  });
  return words.say(name, { message: inner });
}

/** The region the browser claims, for the "we do not model this" warning. */
function browserRegion(): string {
  const parts = navigator.language.split("-");
  return (parts.length > 1 ? parts[parts.length - 1] : "")?.toUpperCase() ?? "";
}
