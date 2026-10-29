/**
 * Every call this page makes, in one place, over the shell's client.
 *
 * Nothing here opens a `fetch`: `shell/api` owns the base path, the cookie and
 * the 401-means-signed-out rule, and a page that reached past it would be the
 * second place those decisions live.
 *
 * The routes are per-section on purpose. One of them is a throttled Yahoo pull
 * away from nothing, and the page shows the sections that answered rather than
 * an error over the whole thing — so each gets its own query and its own
 * failure.
 */

import { get, send } from "../../shell/api";
import { findTickers, forgetSearches } from "../../shell/findTickers";
import type {
  AlertForm,
  AlertRule,
  Analysts,
  OptionsView,
  AssetStats,
  Bars,
  Comparables,
  Comparison,
  CryptoCycle,
  CryptoHolding,
  CryptoPositioning,
  EntryFields,
  Financials,
  Fund,
  Insiders,
  Shorts,
  Metrics,
  Dcf,
  Moat,
  Peer,
  PriceEvents,
  Profile,
  Quote,
  SearchMatch,
  TickerPosition,
  TickerSplits,
  TickerSplitsApplied,
  Trend,
  Valuation,
  WatchlistEntry,
} from "./types";

/**
 * The path for a symbol.
 *
 * Encoded, always: a ledger keeps whatever the broker wrote, and `BRK.B`,
 * `MIPS.ST` and a bare ISIN all reach this page as the label somebody stored.
 */
const at = (ticker: string) => `/ticker/${encodeURIComponent(ticker)}`;

export const getBars = (ticker: string, range: string) =>
  get<Bars>(`${at(ticker)}/bars`, { range });

/**
 * The subject beside `others`, each rebased to the window's first day in
 * `base`. `others` left out draws the three indices; an empty list draws the
 * subject alone.
 */
export const getCompare = (
  ticker: string,
  range: string,
  base: string,
  others?: string[],
) => get<Comparison>(`${at(ticker)}/compare`, { range, base, with: others?.join(",") });

/** `base` buys the one converted figure: `price_base`, in the reader's money. */
export const getQuote = (ticker: string, base: string) =>
  get<Quote>(`${at(ticker)}/quote`, { base });

/** Once per symbol, not per range: it reads its own two years of daily bars. */
export const getTrend = (ticker: string) => get<Trend>(`${at(ticker)}/trend`);

export const getEvents = (ticker: string) => get<PriceEvents>(`${at(ticker)}/events`);

export const getProfile = (ticker: string) => get<Profile>(`${at(ticker)}/profile`);

/** `base` is the account's reporting currency: value and weight are quoted in it. */
export const getPosition = (ticker: string, base: string) =>
  get<TickerPosition>(`${at(ticker)}/position`, { base });

/** Forward splits the book lacks for this name. Writes nothing. */
export const getSplits = (ticker: string) => get<TickerSplits>(`${at(ticker)}/splits`);

/** Write the named splits as one undoable edit; the server re-scans first. */
export const applySplits = (ticker: string, dates: string[]) =>
  send<TickerSplitsApplied>("POST", `${at(ticker)}/splits`, { dates });

/** Take back an edit by its journal id — what `applySplits` answered with. */
export const undoChange = (changeId: number) =>
  send<unknown>("DELETE", `/portfolio/changes/${changeId}`);

/** …and here it buys one tile: the market cap restated in the reader's money. */
export const getMetrics = (ticker: string, base: string) =>
  get<Metrics>(`${at(ticker)}/metrics`, { base });

export const getFinancials = (ticker: string) =>
  get<Financials>(`${at(ticker)}/financials`);

export const getValuation = (ticker: string) =>
  get<Valuation>(`${at(ticker)}/valuation`);

export const getDcf = (ticker: string) => get<Dcf>(`${at(ticker)}/dcf`);

export const getMoat = (ticker: string) => get<Moat>(`${at(ticker)}/moat`);

export const getShorts = (ticker: string) => get<Shorts>(`${at(ticker)}/shorts`);
export const getInsiders = (ticker: string) => get<Insiders>(`${at(ticker)}/insiders`);

/** Rating split, price targets and EPS revisions — all of it consensus. */
export const getAnalysts = (ticker: string) => get<Analysts>(`${at(ticker)}/analysts`);

/** Implied volatility and the put/call mix; `listed: false` for most non-US names. */
export const getOptions = (ticker: string) => get<OptionsView>(`${at(ticker)}/options`);

export const getFund = (ticker: string) => get<Fund>(`${at(ticker)}/fund`);

export const getCrypto = (ticker: string) => get<AssetStats>(`${at(ticker)}/crypto`);

/** Sentiment, Mayer, 200-week, halving: the nightly scan plus the coin's closes. */
export const getCryptoCycle = (ticker: string) =>
  get<CryptoCycle>(`${at(ticker)}/crypto/cycle`);

/** null — not an error — when no venue lists the coin's perpetual. */
export const getCryptoPositioning = (ticker: string) =>
  get<CryptoPositioning | null>(`${at(ticker)}/crypto/positioning`);

/** The reader's coin against their crypto sleeve, in `base`. */
export const getCryptoHolding = (ticker: string, base: string) =>
  get<CryptoHolding>(`${at(ticker)}/crypto/holding`, { base });

export const getPeers = (ticker: string) =>
  get<{ ticker: string; related: Peer[] }>(`${at(ticker)}/peers`);

/**
 * The comps table in one request, never one per name: the medals rank the
 * tickers against each other, so they only mean anything computed in a single
 * pass.
 */
export const getComparables = (tickers: string[]) =>
  get<Comparables>("/comparables", { tickers: tickers.join(",") });

/** Sector per ticker (memo only, "" when unknown), in the route's 50-name chunks. */
export async function getSectors(tickers: string[]): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (let at = 0; at < tickers.length; at += 50) {
    const body = await get<{ profiles: { ticker: string; sector?: string | null }[] }>(
      "/market/profiles",
      { tickers: tickers.slice(at, at + 50).join(",") },
    );
    for (const row of body.profiles) out[row.ticker.toUpperCase()] = row.sector ?? "";
  }
  return out;
}

/** The last company the account opened, or null — newest first on the wire. */
export const getLastViewed = () =>
  get<{ tickers: string[] }>("/search/recent").then((body) => body.tickers[0] ?? null);

export const getWatchlist = () => get<{ entries: WatchlistEntry[] }>("/watchlist");

export const getTags = () => get<{ tags: string[] }>("/watchlist/tags");

export const searchTickers = (q: string, limit = 12) =>
  findTickers<SearchMatch>(q, { limit });

/**
 * An upsert: favouriting or tagging a symbol that is only held — or only
 * searched for — lists it. PATCH would 404 on exactly the
 * symbols somebody is most likely to be starring.
 */
export const follow = (ticker: string, fields: EntryFields) => {
  // A star or a group changes the ticker's own-list row in every search box.
  forgetSearches();
  return send<WatchlistEntry>("POST", "/watchlist", { ticker, ...fields });
};

export const getAlerts = (ticker: string) =>
  get<{ ticker: string; alerts: AlertRule[] }>(
    `/watchlist/${encodeURIComponent(ticker)}/alerts`,
  );

/**
 * The whole set, every time: the rules carry no ids, so "change the second
 * one" is not a request the server could honour.
 */
export const setAlerts = (ticker: string, alerts: AlertRule[]) =>
  send<{ ticker: string; alerts: AlertRule[] }>(
    "PUT",
    `/watchlist/${encodeURIComponent(ticker)}/alerts`,
    { alerts },
  );

export const getAlertTypes = () => get<{ forms: AlertForm[] }>("/alert-types");
