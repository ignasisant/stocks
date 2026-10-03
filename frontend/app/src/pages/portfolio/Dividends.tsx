/**
 * Dividends — what the ledger was paid, and what the shares were entitled to.
 *
 * The two never merge into one number. A dividend is owed to whoever held the
 * share the day before it went ex, whether or not the import carried a row for
 * it, so the estimate is the only way to see a broker whose dividends never
 * import — but it is a guess, and a guess added to a receipt is neither. Each
 * booked figure carries its estimate as a note, and the year bars draw the two
 * side by side; neither is ever summed into the other.
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
import {
  Caption,
  Card,
  Empty,
  Figure,
  Hero,
  Info,
  ShareBar,
  Table,
  TickerCell,
  Warn,
} from "./ui";
import type { Column, FactItem } from "./ui";

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

  // A tax column only where the book has any of it: Revolut's CSV books
  // dividends net, so withheld, creditable and reclaimable are a wall of
  // zeros there — and net equals gross whenever nothing was withheld.
  const yearColumns = (rows: DividendYear[]): Column<DividendYear>[] => {
    const any = (read: (row: DividendYear) => number) =>
      rows.some((row) => Math.abs(read(row)) >= 0.005);
    const figure = (
      key: string,
      label: string,
      read: (row: DividendYear) => number,
    ): Column<DividendYear> => ({
      key,
      label: t(label),
      sort: read,
      cell: (row) => <Figure value={money(read(row))} />,
    });
    const withheld = any((row) => row.withheld);
    return [
      {
        key: "year",
        label: t("portfolio.col_year"),
        left: true,
        sort: (row) => row.year,
        cell: (row) => row.year,
      },
      figure("gross", "portfolio.col_gross", (row) => row.gross),
      ...(withheld
        ? [figure("withheld", "portfolio.col_withheld", (row) => row.withheld)]
        : []),
      ...(withheld ? [figure("net", "portfolio.col_net", (row) => row.net)] : []),
      ...(any((row) => row.creditable)
        ? [figure("creditable", "portfolio.col_creditable", (row) => row.creditable)]
        : []),
      ...(any((row) => row.reclaimable)
        ? [figure("reclaimable", "portfolio.col_reclaimable", (row) => row.reclaimable)]
        : []),
    ];
  };

  // The bar beside each payer is its share of the biggest one, so how much of
  // the income rides on a single name shows before any digit is read.
  const forwardColumns = (topPayer: number): Column<ForwardHolding>[] => [
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
      cell: (row) => (
        <ShareBar
          share={
            row.gross_base === null || !topPayer ? null : row.gross_base / topPayer
          }
        >
          <Figure value={money(row.gross_base)} />
        </ShareBar>
      ),
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
        // The entitlement pass never ran (Yahoo throttled or down), so every
        // estimate below is missing rather than zero. Said up front, as the
        // Streamlit tab warns, because an absent "Next year" or history card
        // would otherwise read as a book that pays nothing.
        const unavailable = dividends.estimates_available ? null : (
          <Warn>{t("portfolio.data_unavailable")}</Warn>
        );
        if (!booked.length && !estimated.length && !dividends.forward.length) {
          return (
            <>
              {unavailable}
              <Empty
                title={t("portfolio.empty_dividends_title")}
                body={t("portfolio.empty_dividends_body")}
              />
            </>
          );
        }

        const invested = positions.positions.reduce((sum, row) => sum + row.cost, 0);
        const forwardAnnual = dividends.forward_annual;
        const topPayer = Math.max(
          0,
          ...dividends.forward.map((row) => row.gross_base ?? 0),
        );

        // The estimate under a booked figure, only when it adds something: a
        // gap under a unit of currency is rounding, not an import gap.
        const estimateNote = (estimate: number | null, bookedTotal: number) =>
          estimate !== null && estimate - bookedTotal >= 1
            ? t("portfolio.div_kpi_est_chip", { val: money(estimate) ?? "" })
            : null;

        const bookedFacts: FactItem[] = [
          {
            label: t("portfolio.div_kpi_total"),
            value: money(dividends.booked_total),
            note: estimateNote(dividends.estimated_total, dividends.booked_total),
            help: t("portfolio.div_kpi_total_help"),
          },
          {
            label: t("portfolio.div_kpi_ytd"),
            value: money(dividends.booked_ytd),
            note: estimateNote(dividends.estimated_ytd, dividends.booked_ytd),
            help: t("portfolio.div_kpi_ytd_help"),
          },
        ];

        // What the book pays from here on is the question this tab answers,
        // so it leads — labelled an estimate in its own eyebrow. With nothing
        // held that pays forward, the receipts lead instead: "n/a" as the
        // headline would read as a book that never paid.
        const hero = dividends.forward.length ? (
          <Hero
            eyebrow={t("portfolio.div_forward_title")}
            value={money(forwardAnnual)}
            sub={t("portfolio.div_hero_sub")}
            facts={[
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
              ...bookedFacts,
            ]}
          />
        ) : (
          <Hero
            eyebrow={t("portfolio.div_kpi_total")}
            value={money(dividends.booked_total)}
            sub={estimateNote(dividends.estimated_total, dividends.booked_total)}
            facts={bookedFacts.slice(1)}
          />
        );

        // The ledger table earns its place when it says something the bars
        // do not: a tax column, or every booked year when nothing was
        // estimated to draw them against.
        const ledgerColumns = yearColumns(booked);
        const ledger =
          booked.length && (ledgerColumns.length > 2 || !estimated.length) ? (
            <Card title={t("portfolio.dividends_ledger_title")}>
              <Table
                columns={ledgerColumns}
                rows={booked}
                rowKey={(row) => String(row.year)}
                initial={{ key: "year" }}
              />
              <Caption>{t("portfolio.dividends_caption")}</Caption>
            </Card>
          ) : null;

        const missed = estimated.reduce((sum, year) => sum + (year.unrecorded ?? 0), 0);

        return (
          <>
            {unavailable}
            <Card>{hero}</Card>

            {booked.length ? null : (
              // No dividend row was ever imported, yet the shares were paid:
              // say so before the estimates, so nothing below reads as a receipt.
              <Info>{t("portfolio.div_est_only")}</Info>
            )}

            <div className="pf-div-grid">
              {dividends.forward.length ? (
                <Card title={t("portfolio.div_forward_by_holding")}>
                  <Table
                    columns={forwardColumns(topPayer)}
                    rows={dividends.forward}
                    rowKey={(row) => row.ticker}
                    initial={{ key: "annual", desc: true }}
                    dense={{
                      ticker: (row) => row.ticker,
                      value: (row) => <Figure value={money(row.gross_base)} />,
                      sub: (row) => [
                        `${t("portfolio.col_shares")} ${formatShares(lang, row.shares) ?? ""}`,
                        `${t("portfolio.col_per_share_ttm")} ${
                          moneyIn(lang, row.currency)(row.per_share, { digits: 2 }) ??
                          t("portfolio.na")
                        }`,
                        `${t("portfolio.col_payments_year")} ${row.payments}`,
                      ],
                      wrap: true,
                    }}
                  />
                  <Caption>{t("portfolio.div_forward_caption")}</Caption>
                </Card>
              ) : null}

              {estimated.length || ledger ? (
                <div className="pf-div-side">
                  {estimated.length ? (
                    <Card title={t("portfolio.div_history_title")}>
                      <YearBars rows={dividends.years} money={money} />
                      {missed > 0.5 ? (
                        <Caption>
                          {t("portfolio.div_unrecorded_hint", {
                            val: money(missed) ?? "",
                          })}
                        </Caption>
                      ) : null}
                      <Caption>{t("portfolio.div_history_caption")}</Caption>
                    </Card>
                  ) : null}
                  {ledger}
                </div>
              ) : null}
            </div>
          </>
        );
      }}
    </Loaded>
  );
}

/**
 * Booked against entitled, one bar per year.
 *
 * The track is what the shares were entitled to and the fill is what the book
 * recorded, on one scale across years, so an import gap is the empty end of a
 * bar rather than a subtraction left to the reader. The two figures stay
 * separate in the text beside it — the bar compares them, it never adds them.
 */
function YearBars({
  rows,
  money,
}: {
  rows: DividendYear[];
  money: ReturnType<typeof moneyIn>;
}) {
  const t = useT();
  const scale = Math.max(
    1e-9,
    ...rows.map((row) => Math.max(row.gross, row.estimated_gross ?? 0)),
  );
  const width = (value: number) =>
    `${((Math.max(value, 0) / scale) * 100).toFixed(1)}%`;
  const ordered = [...rows].sort((a, b) => b.year - a.year);
  return (
    <>
      <div className="pf-years-key" aria-hidden="true">
        <span>
          <i className="pf-years-swatch" />
          {t("portfolio.col_imported")}
        </span>
        <span>
          <i className="pf-years-swatch pf-years-swatch-track" />
          {t("portfolio.col_estimated")}
        </span>
      </div>
      <ul className="pf-years">
        {ordered.map((row) => {
          const estimate = row.estimated_gross;
          const gap = row.unrecorded ?? 0;
          return (
            <li key={row.year} className="pf-years-row">
              <span className="pf-years-label">{row.year}</span>
              <span className="pf-years-bar" aria-hidden="true">
                {estimate !== null ? (
                  <span
                    className="pf-years-track"
                    style={{ inlineSize: width(estimate) }}
                  />
                ) : null}
                <span
                  className="pf-years-fill"
                  style={{ inlineSize: width(row.gross) }}
                />
              </span>
              <span className="pf-years-figures">
                <span>
                  {estimate !== null
                    ? t("portfolio.div_year_of", {
                        booked: money(row.gross) ?? "",
                        estimated: money(estimate) ?? "",
                      })
                    : money(row.gross)}
                </span>
                {gap >= 1 ? (
                  <span className="pf-muted">
                    {t("portfolio.div_year_unrecorded", { val: money(gap) ?? "" })}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </>
  );
}
