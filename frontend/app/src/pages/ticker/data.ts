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
import type {
  AlertForm,
  AlertRule,
  AssetStats,
  Bars,
  Comparables,
  EntryFields,
  Financials,
  Fund,
  Insiders,
  Metrics,
  Moat,
  Peer,
  PriceEvents,
  Profile,
  Quote,
  SearchMatch,
  TickerPosition,
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

export const getQuote = (ticker: string) => get<Quote>(`${at(ticker)}/quote`);

export const getEvents = (ticker: string) => get<PriceEvents>(`${at(ticker)}/events`);

export const getProfile = (ticker: string) => get<Profile>(`${at(ticker)}/profile`);

/** `base` is the account's reporting currency: value and weight are quoted in it. */
export const getPosition = (ticker: string, base: string) =>
  get<TickerPosition>(`${at(ticker)}/position`, { base });

/** …and here it buys one tile: the market cap restated in the reader's money. */
export const getMetrics = (ticker: string, base: string) =>
  get<Metrics>(`${at(ticker)}/metrics`, { base });

export const getFinancials = (ticker: string) =>
  get<Financials>(`${at(ticker)}/financials`);

export const getValuation = (ticker: string) =>
  get<Valuation>(`${at(ticker)}/valuation`);

export const getMoat = (ticker: string) => get<Moat>(`${at(ticker)}/moat`);

export const getInsiders = (ticker: string) => get<Insiders>(`${at(ticker)}/insiders`);

export const getFund = (ticker: string) => get<Fund>(`${at(ticker)}/fund`);

export const getCrypto = (ticker: string) => get<AssetStats>(`${at(ticker)}/crypto`);

export const getPeers = (ticker: string) =>
  get<{ ticker: string; related: Peer[] }>(`${at(ticker)}/peers`);

/**
 * The comps table in one request, never one per name: the medals rank the
 * tickers against each other, so they only mean anything computed in a single
 * pass.
 */
export const getComparables = (tickers: string[]) =>
  get<Comparables>("/comparables", { tickers: tickers.join(",") });

export const getWatchlist = () => get<{ entries: WatchlistEntry[] }>("/watchlist");

export const getTags = () => get<{ tags: string[] }>("/watchlist/tags");

export const searchTickers = (q: string, limit = 12) =>
  get<{ query: string; matches: SearchMatch[] }>("/search", { q, limit });

/**
 * An upsert, like the Streamlit app: favouriting or tagging a symbol that is
 * only held — or only searched for — lists it. PATCH would 404 on exactly the
 * symbols somebody is most likely to be starring.
 */
export const follow = (ticker: string, fields: EntryFields) =>
  send<WatchlistEntry>("POST", "/watchlist", { ticker, ...fields });

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
