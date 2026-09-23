/**
 * Who to compare this company against.
 *
 * Three sources, the same three the Streamlit page offers and in the same
 * order: names already on the watchlist, Yahoo's "people also follow"
 * suggestions, and a free symbol search for the competitor the account never
 * followed — which is routinely a foreign listing, and used to have to be known
 * by heart.
 *
 * Nothing is compared until something is picked. Each peer is a fundamentals
 * pull, so a table nobody asked for spends those requests on a guess; the app
 * starts empty for the same reason.
 */

import { useEffect, useMemo, useState } from "react";
import { useT } from "../../shell/i18n";
import { getPeers, searchTickers } from "./data";
import { Note } from "./ui";
import type { Peer, SearchMatch, WatchlistEntry } from "./types";

const DEBOUNCE_MS = 160;

export function PeerPicker({
  ticker,
  watchlist,
  peers,
  onPeers,
}: {
  ticker: string;
  watchlist: WatchlistEntry[];
  peers: string[];
  onPeers: (next: string[]) => void;
}) {
  const t = useT();
  const [related, setRelated] = useState<Peer[]>([]);
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchMatch[] | null>(null);

  // Coin pairs have none of the KPIs the table ranks, and the viewed name is
  // already its own first column.
  const pool = useMemo(
    () => watchlist.filter((entry) => entry.ticker !== ticker && !entry.is_crypto),
    [watchlist, ticker],
  );

  useEffect(() => {
    let live = true;
    setRelated([]);
    getPeers(ticker)
      .then((body) => live && setRelated(body.related))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ticker]);

  const trimmed = query.trim();
  useEffect(() => {
    if (!trimmed) {
      setHits(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      searchTickers(trimmed, 6)
        .then((body) => live && setHits(body.matches))
        .catch(() => live && setHits([]));
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [trimmed]);

  const add = (symbol: string) => {
    if (symbol === ticker || peers.includes(symbol)) return;
    onPeers([...peers, symbol]);
    setQuery("");
    setHits(null);
    setFilter("");
  };

  const listed = pool.filter((entry) => {
    if (peers.includes(entry.ticker)) return false;
    const needle = filter.trim().toUpperCase();
    if (!needle) return true;
    return entry.ticker.includes(needle) || entry.name.toUpperCase().includes(needle);
  });

  const offers = (hits ?? []).filter(
    (match) =>
      match.ticker !== ticker &&
      !peers.includes(match.ticker) &&
      match.kind !== "crypto",
  );

  return (
    <div className="tk-peers">
      {peers.length > 0 ? (
        <div className="tk-chips">
          {peers.map((peer) => (
            <button
              key={peer}
              type="button"
              className="tk-chip tk-chip-on"
              title={t("ticker.extra_drop")}
              onClick={() => onPeers(peers.filter((one) => one !== peer))}
            >
              {peer} <span aria-hidden="true">×</span>
            </button>
          ))}
        </div>
      ) : null}

      {pool.length > 0 ? (
        <div className="tk-peers-group">
          <label className="tk-peers-label" htmlFor="tk-peer-filter">
            {t("ticker.peers_watchlist")}
          </label>
          {/* Filtered rather than dumped: a long watchlist as a wall of chips is
              exactly what the app's searchable multiselect avoids. */}
          <input
            id="tk-peer-filter"
            className="tk-field"
            type="text"
            autoComplete="off"
            placeholder={t("ticker.peers_search")}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          <div className="tk-chips">
            {listed.slice(0, 12).map((entry) => (
              <button
                key={entry.ticker}
                type="button"
                className="tk-chip"
                onClick={() => add(entry.ticker)}
              >
                {entry.ticker}
                {entry.name && entry.name !== entry.ticker ? (
                  <span className="tk-chip-name">{entry.name}</span>
                ) : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {related.length > 0 ? (
        <div className="tk-peers-group">
          <span className="tk-peers-label" title={t("ticker.related_help")}>
            {t("ticker.related_tickers")}
          </span>
          <div className="tk-chips">
            {related
              .filter((peer) => !peers.includes(peer.ticker))
              .map((peer) => (
                <button
                  key={peer.ticker}
                  type="button"
                  className="tk-chip"
                  onClick={() => add(peer.ticker)}
                >
                  {peer.ticker}
                  {peer.name ? <span className="tk-chip-name">{peer.name}</span> : null}
                </button>
              ))}
          </div>
        </div>
      ) : null}

      <div className="tk-peers-group">
        <label className="tk-peers-label" htmlFor="tk-peer-search">
          {t("ticker.extra_peers")}
        </label>
        <input
          id="tk-peer-search"
          className="tk-field"
          type="text"
          autoComplete="off"
          placeholder={t("ticker.extra_search")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {offers.length > 0 ? (
          <div className="tk-chips">
            {offers.map((match) => (
              <button
                key={match.ticker}
                type="button"
                className="tk-chip"
                onClick={() => add(match.ticker)}
              >
                {match.ticker}
                {match.name ? <span className="tk-chip-name">{match.name}</span> : null}
              </button>
            ))}
          </div>
        ) : null}
        {trimmed !== "" && hits !== null && offers.length === 0 ? (
          <Note>{t("ticker.extra_none")}</Note>
        ) : null}
      </div>
    </div>
  );
}
