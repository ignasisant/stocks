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
import type {
  Custodian,
  MarketStatus,
  Movers,
  Positions as PositionsData,
  Position,
  Summary,
} from "./api";
import { brokerName, moneyIn, percent, shares as formatShares } from "./format";
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

/**
 * What to print under the day tiles when the figure is not a live one.
 *
 * `/market/status` decides the state and hands back a stem; the sentence is
 * this page's own, the one `portfolio.py` prints under its delta row. Spelled
 * out rather than templated so the catalog keys stay greppable — the parity
 * test reads this file to decide whether the React page says what the
 * Streamlit one says.
 */
const MARKET_NOTES: Record<string, string> = {
  market_closed: "portfolio.market_closed_note",
  premarket: "portfolio.premarket_note",
  postmarket: "portfolio.postmarket_note",
};

/**
 * One position's custody as the Streamlit column words it: "Revolut", or
 * "Revolut 60% · ClickTrade 40%" when the shares sit at more than one broker.
 * `withShares: false` is the phone's shorter line under the ticker, where the
 * split would not fit and the name is the point.
 */
function custodyText(
  custody: Custodian[],
  t: (key: string) => string,
  lang: string,
  withShares = true,
): string {
  if (!custody.length) return t("portfolio.na");
  const name = (c: Custodian) => c.name || brokerName(c.broker, t);
  if (custody.length === 1 || !withShares) return custody.map(name).join(" · ");
  return custody
    .map((c) => `${name(c)} ${percent(lang, c.share, { digits: 0 }) ?? ""}`.trim())
    .join(" · ");
}

/** The realised result as a share of what those sales cost, or nothing. */
function realizedChip(summary: Summary, lang: string) {
  if (summary.realized === null || !summary.realized_cost) return null;
  const pct = summary.realized / summary.realized_cost;
  return { text: percent(lang, pct, { signed: true }) ?? "", value: pct };
}

/**
 * "Today" while the US regular session is shut, as `portfolio.py` takes it:
 * the per-row day moves summed, over the book's value before them.
 *
 * The basket's close-to-close is the wrong reading then — before the open it
 * compares yesterday's close with itself and prints a flat 0% while the
 * premarket quotes are already moving. Each row's `day` is the live pre- or
 * after-hours move, or the last completed session once those windows shut,
 * which is the figure the table beside the tile shows.
 */
function closedDay(rows: Position[], value: number) {
  const moved = rows.reduce((sum, row) => sum + (row.day ?? 0), 0);
  const before = value - moved;
  return { amount: moved, basket: before ? moved / before : 0 };
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
        // A clock and a table of exchange hours: it only decides a caption
        // and whether the day chip is greyed, so it never takes the card down.
        get<MarketStatus>("/market/status").catch(() => null),
        ...WINDOWS.map(([, window]) => get<Movers>("/movers", { base, window })),
      ]).then(([positions, summary, market, ...moves]) => ({
        positions,
        summary,
        market: market as MarketStatus | null,
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
      // On a phone the broker column is dropped and its custodians ride
      // under the symbol instead — names only, the split stays on desktop.
      cell: (row) => (
        <span className="pf-stack">
          <TickerCell ticker={row.ticker} />
          <span className="pf-sub pf-narrow-only">
            {custodyText(row.custody, t, lang, false)}
          </span>
        </span>
      ),
    },
    {
      key: "shares",
      label: t("portfolio.col_shares"),
      sort: (row) => row.shares,
      // Four decimals always, as the Streamlit table prints them: a whole
      // share and a fractional one line up in the column.
      cell: (row) => <Figure value={formatShares(lang, row.shares, true)} />,
    },
    {
      key: "currency",
      label: t("portfolio.col_currency"),
      left: true,
      sort: (row) => row.currency,
      cell: (row) => <span className="pf-muted">{row.currency}</span>,
    },
    {
      key: "broker",
      label: t("portfolio.col_broker"),
      left: true,
      className: "pf-wide-only",
      sort: (row) => custodyText(row.custody, t, lang),
      cell: (row) => (
        <span className="pf-muted">{custodyText(row.custody, t, lang)}</span>
      ),
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
      key: "day",
      label: t("portfolio.today"),
      sort: (row) => row.day,
      // Amount and percentage of today's move in one cell, as the Streamlit
      // table pairs them. A name with no live quote (its exchange is shut and
      // it is not in a US extended window) keeps its figures but greys them:
      // that is the last session's move, not today's.
      cell: (row) => (
        <span className={row.market_active ? "pf-pair" : "pf-pair pf-dim"}>
          <Signed value={row.day} text={money(row.day, { signed: true })} />
          {row.day_pct === null ? null : (
            <span className={`pf-chip pf-chip-${row.day_pct >= 0 ? "up" : "down"}`}>
              {percent(lang, row.day_pct, { signed: true })}
            </span>
          )}
        </span>
      ),
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
      {({ positions, summary, market, moves }) => {
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
                  // The closed side of the same book. A book that never sold
                  // reads +0 with no chip, as the Streamlit tile does: the
                  // four-tile row keeps its shape, and the missing chip is
                  // what says no result was taken (a 0% chip would claim one).
                  {
                    label: t("portfolio.realised_pl"),
                    value: money(summary.realized ?? 0, { signed: true }),
                    chip: realizedChip(summary, lang),
                    help: t("portfolio.realised_pl_help"),
                  },
                ]}
              />
            )}
            {/* What the book itself did over three spans, in money first. A
                window the price history does not reach back over reads n/a —
                a book that could not be measured did not sit still. */}
            {nonePriced ? null : (
              <Kpis
                items={WINDOWS.map(([label], index) => {
                  const move =
                    index === 0 && market !== null && !market.us_open
                      ? closedDay(positions.positions, summary.value)
                      : moves[index];
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
                            // Grey only while nothing trades at all: a pre- or
                            // after-hours quote is live data, and so is its move.
                            off:
                              index === 0 &&
                              market !== null &&
                              !market.us_open &&
                              !market.us_extended,
                          },
                  };
                })}
              />
            )}
            {!nonePriced && market?.note && MARKET_NOTES[market.note] ? (
              <Caption>{t(MARKET_NOTES[market.note]!)}</Caption>
            ) : null}
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
