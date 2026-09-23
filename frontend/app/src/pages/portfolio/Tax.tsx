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
import type { TaxPeriod, TaxReport, TaxSale } from "./api";
import { flagOf, moneyIn, percent, shares as formatShares } from "./format";
import { PeriodBars } from "./charts";
import {
  Caption,
  Card,
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
 * The jurisdiction's own wording, most specific first — `web/tax_ui.key()`.
 *
 * A key the catalog is missing renders as the dotted key itself (the shell and
 * the Python side agree on that), which is what makes "does this string
 * exist?" answerable here without a second endpoint.
 */
function useTaxWords(code: string) {
  const t = useT();
  const resolve = (name: string): string | null => {
    const specific = `portfolio.${code.toLowerCase()}_${name}`;
    if (t(specific) !== specific) return specific;
    const neutral = `portfolio.${name}`;
    return t(neutral) !== neutral ? neutral : null;
  };
  return {
    has: (name: string) => resolve(name) !== null,
    // A name neither spelling covers renders as its own dotted key, which is
    // what the Python side does too: a blank is invisible in review, and a key
    // on screen is a bug report that writes itself.
    say: (name: string, slots?: Record<string, string | number>) =>
      t(resolve(name) ?? `portfolio.${name}`, slots),
  };
}

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
function salesByPeriod(report: TaxReport): Map<string, TaxSale[]> | null {
  const counted = report.years.reduce((sum, year) => sum + year.sales, 0);
  if (counted !== report.sales.length) return null;
  const split = new Map<string, TaxSale[]>();
  let at = 0;
  for (const year of report.years) {
    split.set(year.period, report.sales.slice(at, at + year.sales));
    at += year.sales;
  }
  return split;
}

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
  const yearLabel = (option: string) =>
    option === ALL_YEARS ? t("portfolio.all_years") : option;
  const periods = report.years.map((year) => year.period);
  const latest = periods[periods.length - 1] ?? "";
  const [year, setYear] = useState(latest);
  // The aggregate sits after the years, as the Streamlit selector puts it. It
  // only exists for a book with more than one — a single year is already all
  // of them, and an option that repeats the view below it does nothing.
  const options = report.all_years ? [...periods, ALL_YEARS] : periods;
  const [grain, setGrain] = useState<"year" | "month">(
    report.years.length > 1 ? "year" : "month",
  );

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

  const split = salesByPeriod(report);
  const sales = total ? report.sales : (split?.get(selected.period) ?? report.sales);
  const bars: TaxPeriod[] = grain === "year" ? report.years : report.months;

  return (
    <>
      {report.years.length > 1 || report.months.length > 1 ? (
        <Card>
          <Segmented
            label={t("portfolio.realized_granularity")}
            options={["year", "month"] as const}
            value={grain}
            onChange={setGrain}
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
              losses: words.say("chart_losses"),
              recovered: words.say("chart_recovered"),
              net: words.say("chart_net"),
            }}
            money={(value) => money(value) ?? ""}
          />
          <Caption>{words.say("realized_by_year_caption")}</Caption>
          {grain === "month" ? (
            <Caption>{words.say("realized_by_month_caption")}</Caption>
          ) : null}
        </Card>
      ) : null}

      <Card>
        {/* Few fiscal years read faster as buttons than as a dropdown. */}
        {options.length <= 3 ? (
          <Segmented
            label={words.say("fiscal_year")}
            options={options}
            value={year}
            onChange={setYear}
            format={yearLabel}
          />
        ) : (
          <Dropdown
            label={words.say("fiscal_year")}
            // Newest first, the way the dropdown opens on it; the all-years
            // entry stays at the bottom, after the years.
            options={[...periods].reverse().concat(report.all_years ? [ALL_YEARS] : [])}
            value={year}
            onChange={setYear}
            format={yearLabel}
          />
        )}
        <h2>
          {total
            ? words.say("all_years_header")
            : words.say("tax_header", { year: selected.period })}
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
          {/* Germany exempts 30% of a fund's result, and nothing was
              classified — the only note the API carries enough state to draw. */}
          {!report.funds_classified && words.has("funds_unclassified_note")
            ? words.say("funds_unclassified_note")
            : null}
        </Caption>
        {sales.length ? <SalesTable report={report} sales={sales} /> : null}
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
      cell: (row) => <Figure value={formatShares(lang, row.quantity)} />,
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
              <span className={`pf-chip pf-chip-${pct >= 0 ? "up" : "down"}`}>
                {percent(lang, pct, { signed: true })}
              </span>
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
    />
  );
}

/** The region the browser claims, for the "we do not model this" warning. */
function browserRegion(): string {
  const parts = navigator.language.split("-");
  return (parts.length > 1 ? parts[parts.length - 1] : "")?.toUpperCase() ?? "";
}

/** "🇪🇸 Spain — IRPF": the flag built from the code, the name from the catalog. */
function jurisdictionLabel(code: string, t: (key: string) => string): string {
  return `${flagOf(code)} ${t(`profile.tax_residence_${code.toLowerCase()}`)}`.trim();
}
