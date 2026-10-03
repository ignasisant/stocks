/**
 * The watchlist, collapsed into its groups: favourites first and open, then one
 * per tag, then whatever is neither.
 *
 * Names and prices are two reads, as the API intends — `/watchlist` is the
 * stored list and costs nothing, `/home/closes` is the download that can be
 * throttled. Keeping them apart is what lets the rows stand with "n/a" in the
 * price cells when Yahoo says no, instead of the group vanishing with them.
 *
 * The figures are daily closes, not a live quote: the column says *last
 * close*, and the day % is close-to-close — re-read from the quote burst only
 * for a name whose own exchange is shut, where the newest bar can be a flat
 * premarket 0%. A name whose market is not quoting right now has its day
 * figure greyed: real, not moving.
 */

import type { ReactNode } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Pending, Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Chip, chipFor } from "../../ui/Kpi";
import { DenseRows, Responsive } from "../../ui/Rows";
import { Card, Note, TickerCell } from "./ui";
import { decimal, percent } from "./format";
import type { CloseRow, Closes, Watchlist, WatchlistEntry } from "./types";

export function WatchlistGroups({
  nonce,
  onRefresh,
  holdsPositions = false,
}: {
  nonce: number;
  onRefresh: () => void;
  /**
   * The book has positions. The refresh button is the escape hatch for stale
   * prices anywhere on the page — the glance and movers included — so it
   * stays for a book whose watchlist is empty.
   */
  holdsPositions?: boolean;
}) {
  const query = useApi(() => get<Watchlist>("/watchlist"), []);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={5} />}>
      {(data) =>
        data.entries.length === 0 ? (
          <>
            <EmptyWatchlist />
            {holdsPositions ? <RefreshButton onRefresh={onRefresh} /> : null}
          </>
        ) : (
          <Groups entries={data.entries} nonce={nonce} onRefresh={onRefresh} />
        )
      }
    </Loaded>
  );
}

/**
 * "Refresh prices". The page's handler drops the server's price caches before
 * it asks again (`POST /home/refresh`) — without that, asking again answers
 * from the very TTL caches the reader pressed the button to get past.
 */
function RefreshButton({ onRefresh }: { onRefresh: () => void }) {
  const t = useT();
  return (
    <button type="button" className="ag-btn hm-refresh" onClick={onRefresh}>
      {t("home.refresh_prices")}
    </button>
  );
}

function EmptyWatchlist() {
  const t = useT();
  return (
    <Card>
      <h3 className="hm-card-title">{t("home.empty_watchlist_title")}</h3>
      <Note>{t("home.empty_watchlist_body")}</Note>
      <Link page="profile" className="hm-link">
        {t("common.cta_add_tickers")}
      </Link>
    </Card>
  );
}

function Groups({
  entries,
  nonce,
  onRefresh,
}: {
  entries: WatchlistEntry[];
  nonce: number;
  onRefresh: () => void;
}) {
  const t = useT();
  // Keyed on the list itself: an edit elsewhere re-reads, a re-render does not.
  const key = entries.map((entry) => entry.ticker).join(",");
  const closes = useApi(async () => {
    const answer = await get<Closes>("/home/closes");
    return new Map(answer.rows.map((row) => [row.ticker.toUpperCase(), row]));
    // `key` stands for `entries`, whose array is rebuilt on every render and
    // would re-fetch forever; its joined form does not.
  }, [key, nonce]);
  const prices = closes.state === "loaded" ? closes.data : null;
  // The names are known before their prices are: rows draw at once, and
  // only the two figure cells wait — "n/a" is kept for a price that could
  // not be had, not for one still on its way.
  const loading = closes.state === "loading";

  const favorites = entries.filter((entry) => entry.favorite).map((e) => e.ticker);
  const tags = new Map<string, string[]>();
  for (const entry of entries) {
    for (const tag of entry.tags)
      tags.set(tag, [...(tags.get(tag) ?? []), entry.ticker]);
  }
  const rest = entries
    .filter((entry) => !entry.favorite && entry.tags.length === 0)
    .map((entry) => entry.ticker);
  const tagged = [...tags.keys()].sort((a, b) =>
    a.toUpperCase().localeCompare(b.toUpperCase()),
  );

  return (
    <section className="hm-section">
      {favorites.length > 0 ? (
        <Group
          label={t("home.favorites")}
          tickers={favorites}
          prices={prices}
          loading={loading}
          open
        />
      ) : null}
      {tagged.map((tag) => (
        <Group
          key={tag}
          label={tag}
          tickers={tags.get(tag) ?? []}
          prices={prices}
          loading={loading}
        />
      ))}
      {rest.length > 0 ? (
        <Group
          label={t("home.watchlist")}
          tickers={rest}
          prices={prices}
          loading={loading}
        />
      ) : null}
      <p className="hm-caption">{t("home.watchlist_caption")}</p>
      <RefreshButton onRefresh={onRefresh} />
    </section>
  );
}

function Group({
  label,
  tickers,
  prices,
  loading = false,
  open,
}: {
  label: string;
  tickers: string[];
  prices: Map<string, CloseRow> | null;
  loading?: boolean;
  open?: boolean;
}) {
  const t = useT();
  const lang = useLang();
  const na: ReactNode = loading ? <Pending /> : t("home.na");
  return (
    <details className="hm-group" open={open}>
      <summary>{label}</summary>
      <Responsive
        wide={
          <table className="hm-table">
            <thead>
              <tr>
                <th>{t("home.col_ticker")}</th>
                <th className="hm-num">{t("home.col_last_close")}</th>
                <th className="hm-num">{t("home.col_day_pct")}</th>
              </tr>
            </thead>
            <tbody>
              {tickers.map((ticker) => {
                const row = prices?.get(ticker.toUpperCase()) ?? null;
                const move = percent(row?.pct, lang, { signed: true });
                return (
                  <tr key={ticker}>
                    {/* Names ellipsise rather than wrap, as the extremes do. */}
                    <td className="hm-tick-cell">
                      <TickerCell ticker={ticker} />
                    </td>
                    <td className="hm-num">{decimal(row?.close, lang) ?? na}</td>
                    <td className="hm-num">
                      {move === null ? (
                        na
                      ) : (
                        <Chip chip={chipFor(row?.pct, move, row?.active === false)} />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        }
        narrow={
          <DenseRows
            rows={tickers}
            rowKey={(ticker) => ticker}
            spec={{
              ticker: (ticker) => ticker,
              names: true,
              value: (ticker) =>
                decimal(prices?.get(ticker.toUpperCase())?.close, lang) ?? na,
              delta: (ticker) => {
                const row = prices?.get(ticker.toUpperCase()) ?? null;
                const move = percent(row?.pct, lang, { signed: true });
                return move === null ? (
                  na
                ) : (
                  <Chip chip={chipFor(row?.pct, move, row?.active === false)} />
                );
              },
            }}
          />
        }
      />
    </details>
  );
}
