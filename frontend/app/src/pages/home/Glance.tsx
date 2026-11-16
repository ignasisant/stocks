/**
 * The daily-glance cut of the Portfolio page: the headline figures, the
 * today / 1 week / 1 month deltas, and the movers card.
 *
 * One query behind both cards (`useBook`, called by the page), on purpose:
 * they read the same price burst — if the prices are gone, neither card has
 * anything to say, and letting them fail apart would put a movers table beside
 * an empty glance.
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
import { Chip, Kpi, KpiGrid, chipFor } from "../../ui/Kpi";
import { DenseRows, Responsive } from "../../ui/Rows";
import { Card, CardQuery, CardTitle, Note } from "./ui";
import { plain, priceDigits } from "./format";
import { AverageTile, SPARK_WINDOW, SparkMore } from "./Spark";
import { Segmented } from "../../ui/Segmented";
import type {
  History,
  MarketStatus,
  Mover,
  Movers,
  Performance,
  Position,
  Positions,
  Summary,
  Transactions,
} from "./types";
import { money, percent } from "../../shell/format";
import { TickerCell } from "../../shell/tickers";
import { currencySymbol } from "../ticker/format";

/** The windows the card offers, and the labels its range selector uses. */
const WINDOWS = [
  { key: "day", label: "home.market_window_day", tile: "home.today" },
  { key: "week", label: "home.market_window_week", tile: "home.one_week" },
  { key: "month", label: "home.market_window_month", tile: "home.one_month" },
] as const;

type WindowKey = (typeof WINDOWS)[number]["key"];

export type Book = {
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

/**
 * The book behind the glance and the movers, fetched once for both.
 *
 * Called by the page rather than by either card, because each is a card of its
 * own now and may be hidden, moved or drawn alone. `enabled` false — a guest,
 * or both cards put away — answers null without a request.
 */
export function useBook(nonce: number, enabled: boolean): Query<Book | null> {
  return useApi<Book | null>(async () => {
    if (!enabled) return null;
    const [summary, performance, positions, day, week, month, market, history] =
      await Promise.all([
        get<Summary>("/portfolio/summary"),
        get("/portfolio/performance"),
        get("/portfolio/positions"),
        // Every name that moved, not the server's cut: the card draws them
        // all, and its filters and sorts never need another trip.
        get<Movers>("/movers", { window: "day", all: "true" }),
        get<Movers>("/movers", { window: "week", all: "true" }),
        get<Movers>("/movers", { window: "month", all: "true" }),
        // A table of exchange hours and a clock — no account, no fetch. It
        // only decides a caption, so it must never take the card down with it.
        get<MarketStatus>("/market/status").catch(() => null),
        get<History>("/portfolio/history", {
          window: SPARK_WINDOW,
          index: "true",
        }).catch(() => null),
      ]);
    return {
      summary,
      performance,
      positions,
      movers: { day, week, month },
      market,
      history,
    };
  }, [nonce, enabled]);
}

export function Glance({
  query,
  ledger,
}: {
  query: Query<Book | null>;
  ledger: Query<Transactions>;
}) {
  const t = useT();

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
      skeleton={<Skeleton shape="kpis" rows={4} />}
    >
      {(book) => {
        if (!book) return null;
        if (book.summary.positions === 0) {
          // Every position closed: the heading still goes up — the book has a
          // history — and so does the demo caption, because an example book
          // whose lots were all sold is still an example book.
          return everTraded ? (
            <section className="hm-section">
              <h2 className="hm-h2">{plain(t("home.portfolio_title"))}</h2>
              {book.summary.demo ? <Note>{t("home.demo_caption")}</Note> : null}
              <Note>{t("home.no_open_positions")}</Note>
            </section>
          ) : null;
        }
        return (
          <section className="hm-section">
            <h2 className="hm-h2">{plain(t("home.portfolio_title"))}</h2>
            <GlanceCard book={book} />
          </section>
        );
      }}
    </CardQuery>
  );
}

/**
 * The movers as a card of their own, over the same book as the glance.
 *
 * A failed book is the glance's to report when both are on the page; drawn
 * alone, this card says so under its own heading instead of vanishing.
 */
export function MoversSlot({
  query,
  alone,
}: {
  query: Query<Book | null>;
  /** The glance is not on the page to carry a failure. */
  alone: boolean;
}) {
  const t = useT();
  if (query.state === "failed" && !alone) return null;
  return (
    <CardQuery
      query={query}
      note={t("home.data_unavailable")}
      title={plain(t("home.movers_title"))}
      skeleton={<Skeleton shape="table" rows={4} />}
    >
      {(book) =>
        book && book.summary.positions > 0 ? (
          <MoversCard movers={book.movers} positions={book.positions.positions} />
        ) : null
      }
    </CardQuery>
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
  const paid = money(summary.cost, { currency, lang }) ?? na;
  // The row sets the value beside everything that went in, so a name with no
  // price stands in it at what it cost, as the value history carries it.
  // Leaving it out put a 28k "value today" beside 111k injected one
  // throttled morning. Its gain is unknown, so the unsold tile still skips it.
  const worth = summary.value + (summary.unpriced_cost ?? 0);
  const kept = summary.stale?.length ?? 0;
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
        {/* The worse of the two counts: the price pass can miss a name, and the
            basket can additionally lose one whose currency has no FX path. A
            book reported as whole while a third of it was left out is the same
            lie as a wrong total. */}
        {unpriced > 0 ? (
          <Note>
            {t("home.unpriced_note", { n: unpriced, total: summary.positions })}
          </Note>
        ) : null}
        {kept > 0 ? (
          <Note>{t("home.stale_note", { n: kept, total: summary.positions })}</Note>
        ) : null}
        <KpiGrid>
          {WINDOWS.map(({ key, tile }) => {
            // `basket: null` means the price history does not reach back over the
            // window. That is "we cannot say", not "the book was flat".
            const { basket, amount, base } = book.movers[key];
            const figure = percent(basket, { lang, digits: 2, signed: "always" });
            // Money leads and the percentage chips it. Printing the fraction in
            // both slots states one fact twice and leaves out the one a reader
            // came for: how much moved.
            const cash = money(amount, {
              currency: base || currency,
              lang,
              signed: "always",
            });
            // The day's breadth under its figure: a book down 0.7 % with 8
            // names up and 19 down is a different day from one held down by
            // a single name. Not before the US open: a premarket row reads
            // yesterday's session with the premarket on top, while this
            // figure counts the premarket alone, so the count would describe
            // another day than the one it sits under.
            const { gainers, losers } = book.movers.day;
            const early = [...gainers, ...losers].some((row) => row.premarket);
            const tally =
              key === "day" && !early && gainers.length + losers.length > 0 ? (
                <MoverTally up={gainers.length} down={losers.length} />
              ) : undefined;
            return (
              <Kpi
                key={key}
                label={t(tile)}
                value={cash ?? figure ?? na}
                chip={chipFor(basket, figure, key === "day" && stale)}
                note={tally}
              />
            );
          })}
          <AverageTile history={book.history} />
        </KpiGrid>
        <SparkMore history={book.history} />
      </Card>
      <Card>
        {/* Two rows that add up. The first is the money: what went in, what
            it is worth, and the gain between them — value less injected to the
            cent, both sides coming off the same ledger replay. The second
            splits that gain into its realised and unrealised halves, then
            says what it is a year, both ways. */}
        <KpiGrid>
          <Kpi
            label={t("portfolio.series_injected")}
            value={money(performance.injected, { currency, lang }) ?? na}
            help={t("portfolio.overview_injected_help")}
          />
          <Kpi
            label={t("home.market_value")}
            value={money(worth, { currency, lang }) ?? na}
            help={t("portfolio.market_value_help")}
          />
          {/* The chip is the gain over the money put in — the figure the
              Portfolio overview chips its value with. */}
          <Kpi
            label={t("home.total_gain")}
            value={money(total, { currency, lang, signed: "always" }) ?? na}
            // The sum itself, in the reader's figures: the one sentence that
            // makes "gain" mean "value less what went in".
            help={t("home.total_gain_help", {
              value: money(worth, { currency, lang }) ?? na,
              injected: money(performance.injected, { currency, lang }) ?? na,
              gain: money(total, { currency, lang, signed: "always" }) ?? na,
            })}
            chip={chipFor(
              total,
              percent(totalPct, { lang, signed: "always", digits: 1 }),
            )}
          />
        </KpiGrid>
        <KpiGrid>
          {/* The book's own FIFO result and deliberately not the tax report's:
              `/portfolio/tax` replays in the *jurisdiction's* currency under its
              own matching rule. A book that has never sold sends null ("no
              sale" is not "broke even"): the tile reads +0 and draws no chip. */}
          <Kpi
            label={t("home.realised_pl")}
            value={money(realized, { currency, lang, signed: "always" }) ?? na}
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
                      { lang, signed: "always", digits: 1 },
                    ),
                  )
            }
          />
          <Kpi
            label={t("home.unrealised_pl")}
            value={money(summary.pnl, { currency, lang, signed: "always" }) ?? na}
            chip={chipFor(
              summary.pnl_pct,
              percent(summary.pnl_pct, { lang, signed: "always", digits: 1 }),
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
            value={
              percent(performance.irr, { lang, signed: "always", digits: 1 }) ?? na
            }
            help={t("portfolio.mwr_help")}
            note={
              performance.irr_annualised === false
                ? t("home.young_note", { note: t("home.irr_note") })
                : t("home.irr_note")
            }
          />
          <Kpi
            label={t("home.twr_annualised")}
            value={
              percent(performance.twr_annualised, {
                lang,
                signed: "always",
                digits: 1,
              }) ?? na
            }
            help={t("portfolio.twr_return_help")}
            note={
              performance.twr_is_annual === false
                ? t("home.young_note", { note: t("home.twr_note") })
                : t("home.twr_note")
            }
          />
        </KpiGrid>
        {/* Every figure above is invented while the example book is loaded, and
            a reader who seeded it one session ago will not remember. The tiles
            are not dressed differently — they are the real component, showing a
            book that is not. */}
        {summary.demo ? <Note>{t("home.demo_caption")}</Note> : null}
      </Card>
    </>
  );
}

/** Which names the movers card lists: both sides, or one. */
const SIDES = [
  { key: "all", label: "home.movers_side_all" },
  { key: "up", label: "home.movers_side_up" },
  { key: "down", label: "home.movers_side_down" },
] as const;

type Side = (typeof SIDES)[number]["key"];

/** What the rows are ranked on: the money a name moved, or its percentage. */
export type SortBy = "money" | "pct";

/**
 * Every open position that moved over the selected window, up and down.
 *
 * All three windows come back with the page: picking a range is then a choice
 * between things already in hand, and the card's own gate needs all three
 * anyway — a flat day still deserves the card when the week moved.
 *
 * Nothing is cut. This is the card a reader checks through the day to see
 * what went up and what went down, so every name is on it, ranked on money by
 * default — a 6 % move on a 0.5 % position is not the day's story — with the
 * percentage one press away, and a side filter for "just the losers".
 */
function MoversCard({
  movers,
  positions,
}: {
  movers: Record<WindowKey, Movers>;
  positions: Position[];
}) {
  const t = useT();
  const currency = useCurrency();
  const [range, setRange] = useState<WindowKey>("day");
  const [side, setSide] = useState<Side>("all");
  const [sort, setSort] = useState<SortBy>("money");
  const moved = WINDOWS.some(
    ({ key }) => movers[key].gainers.length > 0 || movers[key].losers.length > 0,
  );
  if (!moved) return null;

  const held = new Map(positions.map((position) => [position.ticker, position]));
  const picked = movers[range];
  const { gainers, losers } = picked;
  const worth = (row: Mover) => moveMoney(row.pct, held.get(row.ticker)?.value);
  const shown = moverSides(picked, sort, worth);
  // The server leaves out a name whose move is exactly zero or unmeasurable
  // (no price, no FX path): "all" must not read as every position when it is
  // not.
  const still = Math.max(0, picked.positions - gainers.length - losers.length);
  const sides = [
    side !== "down" ? (
      <MoverTable
        key="up"
        label={t("home.gainers")}
        rows={shown.gainers}
        held={held}
        worth={worth}
        range={range}
      />
    ) : null,
    side !== "up" ? (
      <MoverTable
        key="down"
        label={t("home.losers")}
        rows={shown.losers}
        held={held}
        worth={worth}
        range={range}
      />
    ) : null,
  ];
  return (
    <Card>
      <div className="hm-card-head">
        <CardTitle>{plain(t("home.movers_title"))}</CardTitle>
        <Segmented
          label={t("home.movers_range")}
          items={WINDOWS.map(({ key, label }) => ({ id: key, label: t(label) }))}
          value={range}
          onPick={setRange}
        />
      </div>
      <MoverTally up={gainers.length} down={losers.length} />
      <div className="hm-mv-tools">
        <Segmented
          label={t("home.movers_side")}
          items={SIDES.map(({ key, label }) => ({ id: key, label: t(label) }))}
          value={side}
          onPick={setSide}
        />
        <Segmented
          label={t("home.movers_sort")}
          items={[
            {
              id: "money" as const,
              label:
                currencySymbol(picked.base || currency).trim() || t("home.col_amount"),
            },
            { id: "pct" as const, label: "%" },
          ]}
          value={sort}
          onPick={setSort}
        />
      </div>
      <div className={side === "all" ? "hm-split hm-split-tables" : "hm-mv-one"}>
        {sides}
      </div>
      {[...shown.gainers, ...shown.losers].some((row) => row.premarket) ? (
        <p className="hm-caption">{t("home.movers_premarket")}</p>
      ) : null}
      <p className="hm-caption">
        {[
          t("home.movers_money_note"),
          still > 0 ? t("home.movers_still", { n: still }) : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </Card>
  );
}

/**
 * How many names went up and how many down, over the whole book: 30 down and
 * 5 up is a different day from 5 down and 30 up, whatever the biggest did.
 * The bar is the same count at a glance; the text carries it.
 */
function MoverTally({ up, down }: { up: number; down: number }) {
  const t = useT();
  const total = up + down;
  return (
    <div className="hm-tally">
      <p className="hm-tally-text">
        <span className="hm-tally-up">{t("home.movers_up", { n: up })}</span>
        <span aria-hidden="true"> · </span>
        <span className="hm-tally-down">{t("home.movers_down", { n: down })}</span>
      </p>
      {total > 0 ? (
        <div className="hm-tally-bar" aria-hidden="true">
          {up > 0 ? (
            <span className="hm-tally-bar-up" style={{ flexGrow: up }} />
          ) : null}
          {down > 0 ? (
            <span className="hm-tally-bar-down" style={{ flexGrow: down }} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * What a name's move over the window is worth in money, at today's holding:
 * its value now less its value at the window's start, `value·pct/(1+pct)`.
 *
 * Today's quantities on purpose — the same basket the server ranks the names
 * on — so a name bought mid-week carries the week's move as if held all
 * week, and the rows do not add up to the book's own figure, which follows
 * the money as it came in. The card's caption says so. Null without a value.
 */
export function moveMoney(
  pct: number,
  value: number | null | undefined,
): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  if (!Number.isFinite(pct) || pct <= -1) return null;
  return (value * pct) / (1 + pct);
}

/**
 * The rows each side of the movers card draws, strongest first on both.
 *
 * Every name is drawn, so a side can run to thirty rows: the move worth
 * looking at opens each one, the biggest gain on the left and the worst loss
 * on the right (or at the top of each half, stacked on a phone), and the
 * flat names sink to the bottom. `sort` picks what "strongest" is: the
 * percentage, as the server ranks them, or the money the move was worth
 * (`worth`), a row without that figure last on its side.
 */
export function moverSides(
  movers: Pick<Movers, "gainers" | "losers">,
  sort: SortBy = "pct",
  worth: (row: Mover) => number | null = () => null,
): { gainers: Mover[]; losers: Mover[] } {
  if (sort === "pct")
    return { gainers: [...movers.gainers], losers: [...movers.losers] };
  // Biggest money first: the largest gain, or the largest loss (sign flipped).
  const rank = (rows: Mover[], sign: 1 | -1) =>
    rows
      .map((row) => ({ row, money: worth(row) }))
      .sort((a, b) => {
        if (a.money === null) return b.money === null ? 0 : 1;
        if (b.money === null) return -1;
        return sign * (b.money - a.money);
      })
      .map(({ row }) => row);
  return { gainers: rank(movers.gainers, 1), losers: rank(movers.losers, -1) };
}

/**
 * A mover's chip, by sign and greyed when its market is not quoting. A
 * premarket figure keeps its colour and gets a muted word beside it, the way
 * the ticker page names the session ("Precio · preapertura").
 */
function MoveChip({ row, text }: { row: Mover; text: string | null | undefined }) {
  const t = useT();
  const chip = <Chip chip={chipFor(row.pct, text, row.active === false)} />;
  if (!row.premarket) return chip;
  return (
    <span className="hm-move">
      {chip}
      <span className="hm-session">{t("home.movers_pre_tag")}</span>
    </span>
  );
}

/** The money a row moved, signed and coloured like its chip. */
function MoveMoney({
  row,
  amount,
  currency,
  lang,
  na,
}: {
  row: Mover;
  amount: number | null;
  currency: string;
  lang: string;
  na: string;
}) {
  const text = money(amount, { currency, lang, signed: "always" });
  if (text === null) return <>{na}</>;
  const tone = row.active === false ? "flat" : row.pct > 0 ? "up" : "down";
  return <span className={`hm-tone-${tone}`}>{text}</span>;
}

function MoverTable({
  label,
  rows,
  held,
  worth,
  range,
}: {
  label: string;
  /**
   * `active` is the day window's alone: false greys the figure, because
   * outside its market's session it is the last completed one — real, not
   * moving. A week is close-to-close by construction, nothing to dim.
   */
  rows: Mover[];
  held: Map<string, Position>;
  worth: (row: Mover) => number | null;
  range: WindowKey;
}) {
  const t = useT();
  const lang = useLang();
  const currency = useCurrency();
  const na = t("home.na");
  const caption = (
    <p className="hm-caption">
      {label}
      {rows.length > 0 ? ` · ${rows.length}` : ""}
    </p>
  );
  if (rows.length === 0) {
    return (
      <div>
        {caption}
        <Note>{t("home.none_moved")}</Note>
      </div>
    );
  }
  return (
    <div>
      {caption}
      <Responsive
        wide={
          <table className="hm-table">
            <thead>
              <tr>
                <th>{t("home.col_ticker")}</th>
                <th className="hm-num">{t("home.col_price")}</th>
                <th className="hm-num">
                  {t(range === "day" ? "home.col_day_pct" : "home.col_move_pct")}
                </th>
                <th className="hm-num">{t("home.col_amount")}</th>
                <th className="hm-num">{t("home.col_value")}</th>
                <th className="hm-num">{t("home.col_weight")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const position = held.get(row.ticker);
                const move = percent(row.pct, { lang, digits: 2, signed: "always" });
                return (
                  <tr key={row.ticker}>
                    <td>
                      {/* Symbol alone: six columns in half a card have no
                      room for a name. */}
                      <TickerCell
                        className="hm-ticker"
                        ticker={row.ticker}
                        name={false}
                      />
                    </td>
                    {/* In the currency the name trades in — a share price is
                    quoted by its own market, unlike the value beside it. */}
                    <td className="hm-num">
                      {money(position?.price, {
                        currency: position?.currency || currency,
                        lang,
                        digits: priceDigits(position?.price),
                      }) ?? na}
                    </td>
                    <td className="hm-num">
                      <MoveChip row={row} text={move} />
                    </td>
                    <td className="hm-num">
                      <MoveMoney
                        row={row}
                        amount={worth(row)}
                        currency={currency}
                        lang={lang}
                        na={na}
                      />
                    </td>
                    <td className="hm-num">
                      {money(position?.value, { currency, lang }) ?? na}
                    </td>
                    <td className="hm-num">
                      {percent(position?.weight, { lang, digits: 1 }) ?? na}
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
                <MoveChip
                  row={row}
                  text={percent(row.pct, { lang, digits: 2, signed: "always" })}
                />
              ),
              value: (row) => (
                <MoveMoney
                  row={row}
                  amount={worth(row)}
                  currency={currency}
                  lang={lang}
                  na={na}
                />
              ),
              delta: (row) => money(held.get(row.ticker)?.value, { currency, lang }),
              sub: (row) => {
                const position = held.get(row.ticker);
                return [
                  money(position?.price, {
                    currency: position?.currency || currency,
                    lang,
                    digits: priceDigits(position?.price),
                  }),
                  position?.weight != null
                    ? t("home.weight_short", {
                        pct: percent(position.weight, { lang, digits: 1 }) ?? "",
                      })
                    : null,
                ];
              },
            }}
          />
        }
      />
    </div>
  );
}
