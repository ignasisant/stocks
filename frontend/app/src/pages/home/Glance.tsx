/**
 * The daily-glance cut of the Portfolio page: the headline figures, the
 * today / 1 week / 1 month deltas, and the movers card under them.
 *
 * One query behind both cards, on purpose: they read the same price burst — if
 * the prices are gone, neither card has anything to say, and letting them fail
 * apart would put a movers table under an empty glance.
 *
 * The headline figures are two rows that add up: injected + total gain =
 * value, then realised + unrealised = total gain beside the IRR and the TWR.
 * A cost / value / unrealised / realised row never said how much had been put
 * in. The delta tiles lead with money and chip the percentage.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi, type Query } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { Link } from "../../shell/router";
import { Chip, Kpi, KpiGrid, chipFor } from "../../ui/Kpi";
import { DenseRows, Responsive } from "../../ui/Rows";
import { Card, CardQuery, CardTitle, Note, TickerCell } from "./ui";
import { money, percent, plain } from "./format";
import { AverageTile, SPARK_WINDOW, Spark } from "./Spark";
import type {
  History,
  MarketStatus,
  Movers,
  Performance,
  Position,
  Positions,
  Summary,
  Transactions,
} from "./types";

/** The windows the card offers, and the labels its range selector uses. */
const WINDOWS = [
  { key: "day", label: "1d", tile: "home.today" },
  { key: "week", label: "1w", tile: "home.one_week" },
  { key: "month", label: "1m", tile: "home.one_month" },
] as const;

type WindowKey = (typeof WINDOWS)[number]["key"];

/**
 * What to print under the day figure when it is not a live one.
 *
 * `/market/status` decides the state and hands back a stem; the sentence stays
 * the page's own. Spelled out rather than built with a template literal so the
 * catalog keys are greppable.
 */
const MARKET_NOTES: Record<string, string> = {
  market_closed: "home.market_closed_note",
  premarket: "home.premarket_note",
  postmarket: "home.postmarket_note",
};

type Book = {
  summary: Summary;
  performance: Performance;
  positions: Positions;
  movers: Record<WindowKey, Movers>;
  /**
   * Whether the day figure is live. Null when the clock could not be read —
   * the figures are still worth showing, the caveat under them is not worth
   * failing the card for.
   */
  market: MarketStatus | null;
  /**
   * The chart's days and the 20-day mean's, in the same burst as `summary` so
   * the line ends on the value the tile prints — the server prices both off
   * one download, but only for requests that reach it inside the same one.
   * Null when it failed: the sparkline fails to nothing, never the card.
   */
  history: History | null;
};

export function Glance({
  nonce,
  ledger,
}: {
  nonce: number;
  ledger: Query<Transactions>;
}) {
  const t = useT();
  const query = useApi<Book>(async () => {
    const [summary, performance, positions, day, week, month, market, history] =
      await Promise.all([
        get<Summary>("/portfolio/summary"),
        get<Performance>("/portfolio/performance"),
        get<Positions>("/portfolio/positions"),
        get<Movers>("/movers", { window: "day" }),
        get<Movers>("/movers", { window: "week" }),
        get<Movers>("/movers", { window: "month" }),
        // A table of exchange hours and a clock — no account, no fetch. It
        // only decides a caption, so it must never take the card down with it.
        get<MarketStatus>("/market/status").catch(() => null),
        get<History>("/portfolio/history", { window: SPARK_WINDOW }).catch(() => null),
      ]);
    return {
      summary,
      performance,
      positions,
      movers: { day, week, month },
      market,
      history,
    };
  }, [nonce]);

  // The ledger read is shared with the recent-transactions strip; here it only
  // answers one question — whether a book with nothing open ever had anything
  // in it. A brand-new account gets the first-run cards, which another pass owns.
  const everTraded = ledger.state === "loaded" && ledger.data.total > 0;

  return (
    // No heading over the failure, deliberately: "Portfolio" goes up only once
    // the book is known to have something in it, and a query that failed has
    // not answered that.
    <CardQuery
      query={query}
      note={t("home.data_unavailable")}
      skeleton={<Skeleton rows={5} />}
    >
      {(book) => {
        if (book.summary.positions === 0) {
          // Every position closed: the heading still goes up — the book has a
          // history — and so does the demo caption, because an example book
          // whose lots were all sold is still an example book.
          return everTraded ? (
            <section className="hm-section">
              <h2 className="hm-h2">{plain(t("home.portfolio_title"))}</h2>
              {book.summary.demo ? <Note>{t("home.demo_caption")}</Note> : null}
              <Note>{t("home.no_open_positions")}</Note>
              <PortfolioLink />
            </section>
          ) : null;
        }
        return (
          <section className="hm-section">
            <h2 className="hm-h2">{plain(t("home.portfolio_title"))}</h2>
            <GlanceCard book={book} />
            <MoversCard movers={book.movers} positions={book.positions.positions} />
            <PortfolioLink />
          </section>
        );
      }}
    </CardQuery>
  );
}

function PortfolioLink() {
  const t = useT();
  return (
    <Link page="portfolio" className="hm-link">
      {t("home.link_full_portfolio")}
    </Link>
  );
}

function GlanceCard({ book }: { book: Book }) {
  const t = useT();
  const lang = useLang();
  const currency = useCurrency();
  const { summary, performance } = book;
  const na = t("home.na");

  // Not one position priced. The rows still carry their ledger cost, so
  // summing them against an empty market value would render an intact book at
  // a confident zero and chip it at -100% — a throttled quote burst reading as
  // a wiped-out portfolio. Say the prices are missing instead.
  if (summary.unpriced >= summary.positions) {
    return (
      <Card>
        <Note>{t("home.prices_unavailable")}</Note>
      </Card>
    );
  }

  const realized = summary.realized ?? 0;
  const paid = money(summary.cost, currency, lang) ?? na;
  const total = realized + summary.pnl;
  const totalPct =
    performance.injected && performance.injected > 0
      ? total / performance.injected
      : null;
  // Shut means shut: a pre/after-hours quote is live data and keeps its colour,
  // which is the distinction `/market/status` draws between `us_open` and
  // `us_extended`. `note` is null while the session is open — nothing to say.
  const note = book.market?.note ?? null;
  const stale = note === "market_closed";
  const unpriced = Math.max(summary.unpriced, book.movers.day.unpriced ?? 0);
  return (
    <>
      <Card>
        {/* Two rows that add up. The first is the money: what went in, what
            it is worth, and the gain between them — value less injected to the
            cent, both sides coming off the same ledger replay. The second
            splits that gain into its realised and unrealised halves, then
            says what it is a year, both ways. */}
        <KpiGrid>
          <Kpi
            label={t("portfolio.series_injected")}
            value={money(performance.injected, currency, lang) ?? na}
            help={t("portfolio.overview_injected_help")}
          />
          <Kpi
            label={t("home.market_value")}
            value={money(summary.value, currency, lang) ?? na}
            help={t("portfolio.market_value_help")}
          />
          {/* The chip is the gain over the money put in — the figure the
              Portfolio overview chips its value with. */}
          <Kpi
            label={t("home.total_gain")}
            value={money(total, currency, lang, { signed: true }) ?? na}
            // The sum itself, in the reader's figures: the one sentence that
            // makes "gain" mean "value less what went in".
            help={t("home.total_gain_help", {
              value: money(summary.value, currency, lang) ?? na,
              injected: money(performance.injected, currency, lang) ?? na,
              gain: money(total, currency, lang, { signed: true }) ?? na,
            })}
            chip={chipFor(total, percent(totalPct, lang, { signed: true, digits: 1 }))}
          />
        </KpiGrid>
        <KpiGrid>
          {/* The book's own FIFO result and deliberately not the tax report's:
              `/portfolio/tax` replays in the *jurisdiction's* currency under its
              own matching rule. A book that has never sold sends null ("no
              sale" is not "broke even"): the tile reads +0 and draws no chip. */}
          <Kpi
            label={t("home.realised_pl")}
            value={money(realized, currency, lang, { signed: true }) ?? na}
            help={t("home.realised_pl_help")}
            chip={
              summary.realized === null
                ? null
                : chipFor(
                    summary.realized,
                    percent(
                      summary.realized_cost
                        ? summary.realized / summary.realized_cost
                        : null,
                      lang,
                      { signed: true, digits: 1 },
                    ),
                  )
            }
          />
          <Kpi
            label={t("home.unrealised_pl")}
            value={money(summary.pnl, currency, lang, { signed: true }) ?? na}
            chip={chipFor(
              summary.pnl_pct,
              percent(summary.pnl_pct, lang, { signed: true, digits: 1 }),
            )}
            help={t("home.unrealised_pl_help", { paid })}
            // What the chip is measured on, as a phrase rather than a term:
            // "cost basis" was the one figure here nobody could place.
            note={t("home.unrealised_paid_note", { paid })}
          />
          {/* The pair that belongs together: the IRR leaves the timing of the
              money in, the TWR strips it out. Neither stands in for the other. */}
          <Kpi
            label={t("home.irr_annualised")}
            value={percent(performance.irr, lang, { signed: true, digits: 1 }) ?? na}
            help={t("portfolio.mwr_help")}
          />
          <Kpi
            label={t("home.twr_annualised")}
            value={
              percent(performance.twr_annualised, lang, { signed: true, digits: 1 }) ??
              na
            }
            help={t("portfolio.twr_return_help")}
          />
        </KpiGrid>
        {/* Every figure above is invented while the example book is loaded, and
            a reader who seeded it one session ago will not remember. The tiles
            are not dressed differently — they are the real component, showing a
            book that is not. */}
        {summary.demo ? <Note>{t("home.demo_caption")}</Note> : null}
      </Card>
      <Card>
        <Spark history={book.history} />
        {/* The worse of the two counts: the price pass can miss a name, and the
            basket can additionally lose one whose currency has no FX path. A
            book reported as whole while a third of it was left out is the same
            lie as a wrong total. */}
        {unpriced > 0 ? (
          <Note>
            {t("home.unpriced_note", { n: unpriced, total: summary.positions })}
          </Note>
        ) : null}
        <KpiGrid>
          {WINDOWS.map(({ key, tile }) => {
            // `basket: null` means the price history does not reach back over the
            // window. That is "we cannot say", not "the book was flat".
            const { basket, amount, base } = book.movers[key];
            const figure = percent(basket, lang, { signed: true });
            // Money leads and the percentage chips it. Printing the fraction in
            // both slots states one fact twice and leaves out the one a reader
            // came for: how much moved.
            const cash = money(amount, base || currency, lang, { signed: true });
            return (
              <Kpi
                key={key}
                label={t(tile)}
                value={cash ?? figure ?? na}
                chip={chipFor(basket, figure, key === "day" && stale)}
              />
            );
          })}
          <AverageTile history={book.history} />
        </KpiGrid>
        {/* Which session the day figure belongs to, when it is not this one.
            The server picks the state and the stem; the sentence stays ours. */}
        {note && MARKET_NOTES[note] ? <Note>{t(MARKET_NOTES[note])}</Note> : null}
      </Card>
    </>
  );
}

/**
 * The biggest moves among open positions over the selected window.
 *
 * All three windows come back with the page: picking a range is then a choice
 * between things already in hand, and the card's own gate needs all three
 * anyway — a flat day still deserves the card when the week moved.
 */
function MoversCard({
  movers,
  positions,
}: {
  movers: Record<WindowKey, Movers>;
  positions: Position[];
}) {
  const t = useT();
  const [range, setRange] = useState<WindowKey>("day");
  const moved = WINDOWS.some(
    ({ key }) => movers[key].gainers.length > 0 || movers[key].losers.length > 0,
  );
  if (!moved) return null;

  const held = new Map(positions.map((position) => [position.ticker, position]));
  const shown = movers[range];
  return (
    <Card>
      <div className="hm-card-head">
        <CardTitle>{plain(t("home.movers_title"))}</CardTitle>
        <div className="hm-segmented" role="group" aria-label={t("home.movers_range")}>
          {WINDOWS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={key === range ? "hm-seg hm-seg-on" : "hm-seg"}
              aria-pressed={key === range}
              onClick={() => setRange(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="hm-split">
        <MoverTable
          label={t("home.gainers")}
          rows={shown.gainers.slice(0, 3)}
          held={held}
        />
        <MoverTable
          label={t("home.losers")}
          rows={shown.losers.slice(0, 3)}
          held={held}
        />
      </div>
    </Card>
  );
}

function MoverTable({
  label,
  rows,
  held,
}: {
  label: string;
  /**
   * `active` is the day window's alone: false greys the figure, because
   * outside its market's session it is the last completed one — real, not
   * moving. A week is close-to-close by construction, nothing to dim.
   */
  rows: { ticker: string; pct: number; active?: boolean | null }[];
  held: Map<string, Position>;
}) {
  const t = useT();
  const lang = useLang();
  const currency = useCurrency();
  const na = t("home.na");
  if (rows.length === 0) {
    return (
      <div>
        <p className="hm-caption">{label}</p>
        <Note>{t("home.none_moved")}</Note>
      </div>
    );
  }
  return (
    <div>
      <p className="hm-caption">{label}</p>
      <Responsive
        wide={
          <table className="hm-table">
            <thead>
              <tr>
                <th>{t("home.col_ticker")}</th>
                <th className="hm-num">{t("home.col_price")}</th>
                <th className="hm-num">{t("home.col_day_pct")}</th>
                <th className="hm-num">{t("home.col_value")}</th>
                <th className="hm-num">{t("home.col_weight")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const position = held.get(row.ticker);
                const move = percent(row.pct, lang, { signed: true });
                return (
                  <tr key={row.ticker}>
                    <td>
                      {/* Symbol alone: five columns in half a card have no
                      room for a name. */}
                      <TickerCell ticker={row.ticker} name={false} />
                    </td>
                    {/* In the currency the name trades in — a share price is
                    quoted by its own market, unlike the value beside it. */}
                    <td className="hm-num">
                      {money(position?.price, position?.currency || currency, lang, {
                        digits: 2,
                      }) ?? na}
                    </td>
                    <td className="hm-num">
                      <Chip chip={chipFor(row.pct, move, row.active === false)} />
                    </td>
                    <td className="hm-num">
                      {money(position?.value, currency, lang) ?? na}
                    </td>
                    <td className="hm-num">
                      {percent(position?.weight, lang, { digits: 1 }) ?? na}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        }
        narrow={
          <DenseRows
            rows={rows}
            rowKey={(row) => row.ticker}
            spec={{
              ticker: (row) => row.ticker,
              badge: (row) => (
                <Chip
                  chip={chipFor(
                    row.pct,
                    percent(row.pct, lang, { signed: true }),
                    row.active === false,
                  )}
                />
              ),
              value: (row) => money(held.get(row.ticker)?.value, currency, lang) ?? na,
              sub: (row) => {
                const position = held.get(row.ticker);
                return [
                  money(position?.price, position?.currency || currency, lang, {
                    digits: 2,
                  }),
                  percent(position?.weight, lang, { digits: 1 }),
                ];
              },
            }}
          />
        }
      />
    </div>
  );
}
