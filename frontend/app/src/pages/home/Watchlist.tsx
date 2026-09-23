/**
 * The watchlist, collapsed into its groups: favourites first and open, then one
 * per tag, then whatever is neither.
 *
 * Names and prices are two reads, as the API intends — `/watchlist` is the
 * stored list and costs nothing, `/market/quotes` is the burst that can be
 * throttled. Keeping them apart is what lets the rows stand with "n/a" in the
 * price cells when Yahoo says no, instead of the group vanishing with them.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { Card, DeltaChip, Note, TickerCell, chipFor } from "./ui";
import { decimal, percent } from "./format";
import type { Quote, Quotes, Watchlist, WatchlistEntry } from "./types";

/** The quotes route answers at most this many symbols per request. */
const BATCH = 50;

export function WatchlistGroups({
  nonce,
  onRefresh,
}: {
  nonce: number;
  onRefresh: () => void;
}) {
  const query = useApi(() => get<Watchlist>("/watchlist"), []);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={5} />}>
      {(data) =>
        data.entries.length === 0 ? (
          <EmptyWatchlist />
        ) : (
          <Groups entries={data.entries} nonce={nonce} onRefresh={onRefresh} />
        )
      }
    </Loaded>
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
  const tickers = entries.map((entry) => entry.ticker);
  const key = tickers.join(",");
  const quotes = useApi(async () => {
    const batches: string[][] = [];
    for (let at = 0; at < tickers.length; at += BATCH) {
      batches.push(tickers.slice(at, at + BATCH));
    }
    const answers = await Promise.all(
      batches.map((batch) =>
        get<Quotes>("/market/quotes", { tickers: batch.join(",") }),
      ),
    );
    const found = new Map<string, Quote>();
    for (const answer of answers) {
      for (const quote of answer.quotes) found.set(quote.ticker.toUpperCase(), quote);
    }
    return found;
    // `key` is the dependency that stands for `tickers`: the array is rebuilt
    // on every render and would re-fetch forever, its joined form does not.
  }, [key, nonce]);
  const prices = quotes.state === "loaded" ? quotes.data : null;

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
        <Group label={t("home.favorites")} tickers={favorites} prices={prices} open />
      ) : null}
      {tagged.map((tag) => (
        <Group key={tag} label={tag} tickers={tags.get(tag) ?? []} prices={prices} />
      ))}
      {rest.length > 0 ? (
        <Group label={t("home.watchlist")} tickers={rest} prices={prices} />
      ) : null}
      <p className="hm-caption">{t("home.watchlist_caption")}</p>
      {/* The Streamlit button drops this page's price caches and reruns. The
          caches here are the API's own, keyed on a TTL nothing outside the
          process can clear — so this asks again, which is what gets fresh
          quotes once the short quote TTL has rolled over. */}
      <button type="button" className="ag-btn" onClick={onRefresh}>
        {t("home.refresh_prices")}
      </button>
    </section>
  );
}

function Group({
  label,
  tickers,
  prices,
  open,
}: {
  label: string;
  tickers: string[];
  prices: Map<string, Quote> | null;
  open?: boolean;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  return (
    <details className="hm-group" open={open}>
      <summary>{label}</summary>
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
            const quote = prices?.get(ticker.toUpperCase()) ?? null;
            const move = percent(quote?.pct, lang, { signed: true });
            return (
              <tr key={ticker}>
                <td>
                  <TickerCell ticker={ticker} />
                </td>
                <td className="hm-num">{decimal(quote?.price, lang) ?? na}</td>
                <td className="hm-num">
                  {move === null ? na : <DeltaChip chip={chipFor(quote?.pct, move)} />}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}
