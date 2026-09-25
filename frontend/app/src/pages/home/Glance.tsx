/**
 * The daily-glance cut of the Portfolio page: the headline figures, the
 * today / 1 week / 1 month deltas, and the movers card under them.
 *
 * One query behind both cards, on purpose. The Streamlit page reserves the two
 * slots in the same breath because they read the same price burst — if the
 * prices are gone, neither card has anything to say, and letting them fail
 * apart would put a movers table under an empty glance.
 *
 * The realised P/L is the book's own FIFO figure and not the tax report's,
 * argued at the tile; beside it the row also carries the book's TWR and IRR,
 * which the Streamlit glance does not — kept, because they are the pair that
 * says how the money did. The delta tiles lead with money and chip the
 * percentage, as the Streamlit tiles do.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useApi, type Query } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { Link } from "../../shell/router";
import {
  Card,
  CardQuery,
  CardTitle,
  DeltaChip,
  Note,
  TickerCell,
  Tile,
  Tiles,
  chipFor,
} from "./ui";
import { money, percent, plain } from "./format";
import { Spark } from "./Spark";
import type {
  MarketStatus,
  Movers,
  Performance,
  Position,
  Positions,
  Summary,
  Transactions,
} from "./types";

/** The windows the card offers, and the labels the Streamlit selector uses. */
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
 * the page's own, and is the same one `home.py` prints under its delta row.
 * Spelled out rather than built with a template literal so the catalog keys are
 * greppable — `test_page_parity` reads this file to decide whether the React
 * page says what the Streamlit one says, and a key it cannot see is a gap it
 * cannot report.
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
    const [summary, performance, positions, day, week, month, market] =
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
      ]);
    return { summary, performance, positions, movers: { day, week, month }, market };
  }, [nonce]);

  // The ledger read is shared with the recent-transactions strip; here it only
  // answers one question — whether a book with nothing open ever had anything
  // in it. A brand-new account gets the first-run cards, which another pass owns.
  const everTraded = ledger.state === "loaded" && ledger.data.total > 0;

  return (
    // No heading over the failure, deliberately: the Streamlit page only prints
    // "Portfolio" once it knows the book has something in it, and a query that
    // failed has not answered that.
    <CardQuery
      query={query}
      note={t("home.data_unavailable")}
      skeleton={<Skeleton rows={5} />}
    >
      {(book) => {
        if (book.summary.positions === 0) {
          // Every position closed: the heading still goes up — the book has a
          // history, which is what `home.py` keys it on (`positions or
          // realized`) — and so does the demo caption, because an example
          // book whose lots were all sold is still an example book.
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
            <GlanceCard book={book} nonce={nonce} />
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

function GlanceCard({ book, nonce }: { book: Book; nonce: number }) {
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

  const gain = summary.pnl_pct;
  const gainChip = chipFor(gain, percent(gain, lang, { signed: true, digits: 1 }));
  // Shut means shut: a pre/after-hours quote is live data and keeps its colour,
  // which is the distinction `/market/status` draws between `us_open` and
  // `us_extended`. `note` is null while the session is open — nothing to say.
  const note = book.market?.note ?? null;
  const stale = note === "market_closed";
  const unpriced = Math.max(summary.unpriced, book.movers.day.unpriced ?? 0);
  return (
    <>
      <Card>
        <Tiles>
          <Tile
            label={t("home.cost_basis")}
            value={money(summary.cost, currency, lang) ?? na}
          />
          <Tile
            label={t("home.market_value")}
            value={money(summary.value, currency, lang) ?? na}
            chip={gainChip}
          />
          <Tile
            label={t("home.unrealised_pl")}
            value={money(summary.pnl, currency, lang, { signed: true }) ?? na}
            chip={gainChip}
          />
          {/* The realised side of the same book, and deliberately not the tax
              report's figure: `/portfolio/tax` replays in the *jurisdiction's*
              currency under its own share-matching rule and reports per tax
              year, while this label promises all-time FIFO gains in the
              account's reporting currency. `/portfolio/summary` carries this one
              off the same replay as its cost and value, so the tile and its hint
              agree.

              Always on the row, as `home.py` draws it: a book that has never
              sold reads +0 with no chip. The API sends null for that case — "no
              sale" and "broke even" are different facts — and the difference is
              kept where it matters, in the chip, which a zero cost basis cannot
              carry. */}
          <Tile
            label={t("home.realised_pl")}
            value={money(summary.realized ?? 0, currency, lang, { signed: true }) ?? na}
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
          {/* The two returns are the pair that belongs together: the TWR strips
              out when money went in, the IRR leaves it in. Neither stands in for
              the other, so both, never one. */}
          <Tile
            label={t("portfolio.annualised_return")}
            value={
              percent(performance.twr_annualised, lang, { signed: true, digits: 1 }) ?? na
            }
            help={t("portfolio.twr_return_help")}
          />
          <Tile
            label={t("portfolio.mwr")}
            value={percent(performance.irr, lang, { signed: true, digits: 1 }) ?? na}
            help={t("portfolio.mwr_help")}
          />
        </Tiles>
        {/* Every figure above is invented while the example book is loaded, and
            a reader who seeded it one session ago will not remember. The tiles
            are not dressed differently — they are the real component, showing a
            book that is not. */}
        {summary.demo ? <Note>{t("home.demo_caption")}</Note> : null}
      </Card>
      <Card>
        <Spark nonce={nonce} />
        {/* The worse of the two counts: the price pass can miss a name, and the
            basket can additionally lose one whose currency has no FX path. A
            book reported as whole while a third of it was left out is the same
            lie as a wrong total. */}
        {unpriced > 0 ? (
          <Note>
            {t("home.unpriced_note", { n: unpriced, total: summary.positions })}
          </Note>
        ) : null}
        <Tiles>
          {WINDOWS.map(({ key, tile }) => {
            // `basket: null` means the price history does not reach back over the
            // window. That is "we cannot say", not "the book was flat".
            const { basket, amount, base } = book.movers[key];
            const figure = percent(basket, lang, { signed: true });
            // Money leads and the percentage chips it, as the Streamlit tiles do.
            // Printing the fraction in both slots states one fact twice and
            // leaves out the one a reader came for: how much moved.
            const cash = money(amount, base || currency, lang, { signed: true });
            return (
              <Tile
                key={key}
                label={t(tile)}
                value={cash ?? figure ?? na}
                chip={chipFor(basket, figure, key === "day" && stale)}
              />
            );
          })}
        </Tiles>
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
 * All three windows come back with the page, as they do in Streamlit: picking
 * a range is then a choice between things already in hand, and the card's own
 * gate needs all three anyway — a flat day still deserves the card when the
 * week moved.
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
                  {/* Symbol alone, as `home.py` draws the movers (`names=False`):
                      five columns in half a card have no room for a name. */}
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
                  <DeltaChip chip={chipFor(row.pct, move, row.active === false)} />
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
    </div>
  );
}
