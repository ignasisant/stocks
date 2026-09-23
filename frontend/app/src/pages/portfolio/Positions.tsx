/**
 * Positions — what is held, what it cost, and what it is worth today.
 *
 * The two totals come from `/portfolio/summary` rather than being added up
 * here, and that matters: both sums are taken over the same rows, so a name
 * the price pass missed is out of the cost basis as well as out of the market
 * value. Summing the whole book's basis against a partial value renders an
 * intact book at -60%, which is the bug this endpoint exists to prevent.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import type { Movers, Positions as PositionsData, Position, Summary } from "./api";
import { moneyIn, percent, shares as formatShares } from "./format";
import { Caption, Card, Empty, Figure, Kpis, Signed, Table, TickerCell } from "./ui";
import type { Column } from "./ui";
import History from "./History";

/**
 * The three spans the book's own move is quoted over, and the label each one
 * carries. Not horizons in days: `/movers` names its own windows, and the day
 * one is close-to-close on the basket rather than a live intraday figure.
 */
const WINDOWS = [
  ["portfolio.today", "day"],
  ["portfolio.one_week", "week"],
  ["portfolio.one_month", "month"],
] as const;

/** The realised result as a share of what those sales cost, or nothing. */
function realizedChip(summary: Summary) {
  if (summary.realized === null || !summary.realized_cost) return null;
  const pct = summary.realized / summary.realized_cost;
  return { text: `${pct >= 0 ? "+" : ""}${(pct * 100).toFixed(1)}%`, value: pct };
}

function Positions() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);

  // Three windows, three calls, because `/movers` answers one at a time — and
  // all three read the same cached basket the Home page already asked for, so
  // the cost is three round trips rather than three price bursts. The Streamlit
  // page takes them off one `basket_history` frame; the arithmetic is the same.
  const query = useApi(
    () =>
      Promise.all([
        get<PositionsData>("/portfolio/positions", { base }),
        get<Summary>("/portfolio/summary", { base }),
        ...WINDOWS.map(([, window]) => get<Movers>("/movers", { base, window })),
      ]).then(([positions, summary, ...moves]) => ({
        positions,
        summary,
        moves: moves as Movers[],
      })),
    [base],
  );

  const columns: Column<Position>[] = [
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
      key: "currency",
      label: t("portfolio.col_currency"),
      left: true,
      sort: (row) => row.currency,
      cell: (row) => <span className="pf-muted">{row.currency}</span>,
    },
    {
      key: "cost",
      label: t("portfolio.cost_basis"),
      sort: (row) => row.cost,
      cell: (row) => <Figure value={money(row.cost)} />,
    },
    {
      key: "value",
      label: t("portfolio.market_value"),
      sort: (row) => row.value,
      cell: (row) => <Figure value={money(row.value)} />,
    },
    {
      key: "weight",
      label: t("portfolio.col_weight"),
      sort: (row) => row.weight,
      cell: (row) => <Figure value={percent(lang, row.weight)} />,
    },
    {
      key: "pnl",
      label: t("portfolio.col_total_pl"),
      sort: (row) => row.pnl,
      // Amount and percentage of the same move belong in one cell: the
      // nominal is the headline, the percentage the reference.
      cell: (row) => (
        <span className="pf-pair">
          <Signed value={row.pnl} text={money(row.pnl, { signed: true })} />
          {row.pnl_pct === null ? null : (
            <span className={`pf-chip pf-chip-${row.pnl_pct >= 0 ? "up" : "down"}`}>
              {percent(lang, row.pnl_pct, { signed: true })}
            </span>
          )}
        </span>
      ),
    },
  ];

  return (
    <Loaded query={query} skeleton={<Skeleton rows={8} />}>
      {({ positions, summary, moves }) => {
        if (!positions.positions.length) {
          return (
            <Empty
              title={t("portfolio.empty_positions_title")}
              body={t("portfolio.empty_positions_body")}
              cta={{ label: t("common.cta_import"), page: "import" }}
            />
          );
        }
        // Open positions, not one of them priced. The tiles below would sum an
        // absent market value to a confident zero and chip it at -100% — a
        // throttled quote burst reading as a wiped-out book.
        const nonePriced = positions.positions.every((row) => row.value === null);
        return (
          <Card title={t("portfolio.open_positions_pl", { ccy: base })}>
            {nonePriced ? (
              <Caption>{t("portfolio.prices_unavailable")}</Caption>
            ) : (
              <Kpis
                items={[
                  { label: t("portfolio.cost_basis"), value: money(summary.cost) },
                  {
                    label: t("portfolio.market_value"),
                    value: money(summary.value),
                    chip:
                      summary.pnl_pct === null
                        ? null
                        : {
                            text:
                              percent(lang, summary.pnl_pct, { signed: true }) ?? "",
                            value: summary.pnl_pct,
                          },
                  },
                  {
                    label: t("portfolio.unrealised_pl"),
                    value: money(summary.pnl, { signed: true }),
                    chip:
                      summary.pnl_pct === null
                        ? null
                        : {
                            text:
                              percent(lang, summary.pnl_pct, { signed: true }) ?? "",
                            value: summary.pnl_pct,
                          },
                  },
                  // The closed side of the same book. Absent, not zero, for a
                  // book that has never sold: the tile would otherwise claim a
                  // result nobody has taken.
                  ...(summary.realized === null
                    ? []
                    : [
                        {
                          label: t("portfolio.realised_pl"),
                          value: money(summary.realized, { signed: true }),
                          chip: realizedChip(summary),
                          help: t("portfolio.realised_pl_help"),
                        },
                      ]),
                ]}
              />
            )}
            {/* What the book itself did over three spans, in money first. A
                window the price history does not reach back over reads n/a —
                a book that could not be measured did not sit still. */}
            {nonePriced ? null : (
              <Kpis
                items={WINDOWS.map(([label], index) => {
                  const move = moves[index];
                  return {
                    label: t(label),
                    value:
                      move?.amount === null || move === undefined
                        ? t("portfolio.na")
                        : (money(move.amount, { signed: true }) ?? t("portfolio.na")),
                    chip:
                      move?.basket === null || move === undefined
                        ? null
                        : {
                            text:
                              percent(lang, move.basket, {
                                signed: true,
                                digits: 2,
                              }) ?? "",
                            value: move.basket,
                          },
                  };
                })}
              />
            )}
            {/* Say what the tiles above leave out: the rows read n/a in the
                table, but the totals would look complete. Pointless when there
                are no tiles — the line above already says why. */}
            {summary.unpriced && !nonePriced ? (
              <Caption>
                {t("portfolio.unpriced_note", {
                  n: summary.unpriced,
                  total: summary.positions,
                })}
              </Caption>
            ) : null}
            <Table
              columns={columns}
              rows={positions.positions}
              rowKey={(row) => row.ticker}
              initial={{ key: "weight", desc: true }}
            />
            <Caption>{t("portfolio.positions_caption")}</Caption>
          </Card>
        );
      }}
    </Loaded>
  );
}

/**
 * The tab, not just the table: the history chart is a second fetch and a slow
 * one, so it mounts beside the table rather than inside its query — a cold
 * price cache must not hold the positions back.
 */
export default function PositionsTab() {
  return (
    <>
      <Positions />
      <History />
    </>
  );
}
