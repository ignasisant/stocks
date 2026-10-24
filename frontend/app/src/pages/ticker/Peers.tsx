/**
 * Who to compare this company against.
 *
 * Four sources, in this order: names already on the watchlist, the sector
 * screen's same-industry rivals, the same-industry names Yahoo readers also
 * watch (two rows, so co-viewed never reads as "competes with"), and a free
 * symbol search for the competitor
 * the account never followed — which is routinely a foreign listing, and used
 * to have to be known by heart.
 *
 * Nothing is compared until something is picked. Each peer is a fundamentals
 * pull, so a table nobody asked for spends those requests on a guess.
 */

import { useEffect, useMemo, useState } from "react";
import { useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { getPeers, getSectors, searchTickers } from "./data";
import { Note } from "./ui";
import type { Peer, SearchMatch, WatchlistEntry } from "./types";
import { ToggleChip } from "../../ui/Toggle";

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

  // Only the company's own sector is offered from the list, so a book of
  // thirty names does not put a crypto miner next to Apple. Names the memo has
  // no sector for are left out, and "all" brings the whole list back.
  const [sectors, setSectors] = useState<Record<string, string> | null>(null);
  const [all, setAll] = useState(false);
  const poolKey = pool.map((entry) => entry.ticker).join(",");
  useEffect(() => {
    let live = true;
    setSectors(null);
    setAll(false);
    getSectors([ticker, ...poolKey.split(",").filter(Boolean)])
      .then((found) => live && setSectors(found))
      .catch(() => live && setSectors({}));
    return () => {
      live = false;
    };
  }, [ticker, poolKey]);
  const own = sectors?.[ticker.toUpperCase()] ?? "";
  const narrowed = !all && own !== "";

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
    if (narrowed && sectors?.[entry.ticker.toUpperCase()] !== own) return false;
    const needle = filter.trim().toUpperCase();
    if (!needle) return true;
    return entry.ticker.includes(needle) || entry.name.toUpperCase().includes(needle);
  });

  // The server's suggestions minus anything the watchlist group already offers.
  // The same name as a chip in two groups reads as two different things to
  // compare, and the watchlist copy is the one that carries the reader's own
  // name for it.
  const inPool = new Set(pool.map((entry) => entry.ticker.toUpperCase()));
  const suggested = related.filter(
    (peer) => !inPool.has(peer.ticker.toUpperCase()) && !peers.includes(peer.ticker),
  );

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
            <ToggleChip
              key={peer}
              on
              title={t("ticker.extra_drop")}
              onClick={() => onPeers(peers.filter((one) => one !== peer))}
            >
              <ChipMark ticker={peer} />
              {peer} <span aria-hidden="true">×</span>
            </ToggleChip>
          ))}
        </div>
      ) : null}

      {pool.length > 0 ? (
        <div className="tk-peers-group">
          <label className="tk-peers-label" htmlFor="tk-peer-filter">
            {narrowed
              ? t("ticker.peers_sector", { sector: own })
              : t("ticker.peers_watchlist")}
          </label>
          {own !== "" ? (
            <ToggleChip on={all} onClick={() => setAll(!all)}>
              {t("ticker.peers_all")}
            </ToggleChip>
          ) : null}
          {/* Every name on the list, with the filter to narrow it; a long list
              scrolls inside its own box rather than pushing the comparison
              table off the screen. */}
          <input
            id="tk-peer-filter"
            className="tk-field"
            type="text"
            autoComplete="off"
            placeholder={t("ticker.peers_search")}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          <div className="tk-chips tk-chips-scroll">
            {listed.length === 0 ? (
              <span className="tk-chip-name">{t("ticker.peers_none")}</span>
            ) : null}
            {listed.map((entry) => (
              <ToggleChip
                key={entry.ticker}
                on={false}
                onClick={() => add(entry.ticker)}
              >
                <ChipMark ticker={entry.ticker} />
                {entry.ticker}
                {entry.name && entry.name !== entry.ticker ? (
                  <span className="tk-chip-name">{entry.name}</span>
                ) : null}
              </ToggleChip>
            ))}
          </div>
        </div>
      ) : null}

      <Suggested
        label={t("ticker.related_rivals")}
        help={t("ticker.related_rivals_help")}
        peers={suggested.filter((peer) => peer.source !== "watched")}
        onAdd={add}
      />
      <Suggested
        label={t("ticker.related_watched")}
        help={t("ticker.related_watched_help")}
        peers={suggested.filter((peer) => peer.source === "watched")}
        onAdd={add}
      />

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
              <ToggleChip
                key={match.ticker}
                on={false}
                onClick={() => add(match.ticker)}
              >
                <ChipMark ticker={match.ticker} />
                {match.ticker}
                {match.name ? <span className="tk-chip-name">{match.name}</span> : null}
              </ToggleChip>
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

/** One labelled row of suggested peers; nothing when the row is empty. */
function Suggested({
  label,
  help,
  peers,
  onAdd,
}: {
  label: string;
  help: string;
  peers: Peer[];
  onAdd: (ticker: string) => void;
}) {
  if (peers.length === 0) return null;
  return (
    <div className="tk-peers-group">
      <span className="tk-peers-label" title={help}>
        {label}
      </span>
      <div className="tk-chips">
        {peers.map((peer) => (
          <ToggleChip key={peer.ticker} on={false} onClick={() => onAdd(peer.ticker)}>
            <ChipMark ticker={peer.ticker} />
            {peer.ticker}
            {peer.name ? <span className="tk-chip-name">{peer.name}</span> : null}
          </ToggleChip>
        ))}
      </div>
    </div>
  );
}

/**
 * The company's mark on a picker chip — the house rule's logo half.
 *
 * Only the logo: the chip is itself the control (it picks or drops a peer), so
 * a link nested in it would be a button inside a button. The way into each
 * company's page is its column in the comparison table, one click after the
 * pick. The marks come from the same batched `/market/profiles` lookup every
 * ticker cell uses, so a forty-name watchlist costs one request, not forty.
 */
export function ChipMark({ ticker }: { ticker: string }) {
  const profile = useTickerProfile(ticker);
  return profile?.logo ? (
    <img className="tk-chip-logo" src={profile.logo} alt="" loading="lazy" />
  ) : null;
}
