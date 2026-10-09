/**
 * The page's two filters: sector and weight in the book.
 *
 * Both ride the URL (`?sector=technology,healthcare&w=5`) so a filtered read
 * survives a reload and can be linked, and both are applied here, once, to
 * the rows every section draws — the plan, the cards, the map, the tables and
 * the question handed to the assistant all read the same subset.
 *
 * Sector is Yahoo's name, keyed the way Pulse keys it (`sectorKey`) so the
 * words are Pulse's `sentiment.sector_*`. A row with no sector is bucketed by
 * what it is: a fund or ETF under `funds`, a coin under `crypto`, anything
 * else under `unknown` — never dropped, or the filter would hide names.
 *
 * Weight bands apply to held rows only: an outside name has no weight, so a
 * band leaves the outside list to the sector filter alone.
 *
 * "Include" picks what is compared at all (`?in=held,fav,list:AI`): the book,
 * the watchlist's starred names, the whole watchlist, or one of its groups.
 * Picks add up — a name is in when any of them has it — and a ticker typed
 * into the box at the top is always in: it was asked for by name. With no
 * `?in=` the read opens on the book alone (the page is about what you hold);
 * `?in=all` is everything, and a book with nothing held opens on everything.
 */

import { sectorKey } from "../sentiment/format";
import type { Review, ReviewRow } from "./types";

/** Band key → [low, high) as a share of the book. */
const BANDS = {
  "10": [0.1, Infinity],
  "5": [0.05, 0.1],
  "1": [0.01, 0.05],
  "0": [0, 0.01],
} as const;

export type Band = keyof typeof BANDS;

export const BAND_ORDER: Band[] = ["10", "5", "1", "0"];

export type Filter = { sectors: string[]; band: Band | null; sources: string[] };

export const CLEAR: Filter = { sectors: [], band: null, sources: [] };

/** The fixed sources, in chip order; a watchlist group is `list:<name>`. */
const HELD = "held";
const FAV = "fav";
const WATCH = "watch";
const LIST = "list:";

const listSource = (name: string) => `${LIST}${name}`;
export const listName = (source: string) =>
  source.startsWith(LIST) ? source.slice(LIST.length) : null;

/** Every source a row belongs to. */
function sourcesOfRow(row: ReviewRow): string[] {
  const out: string[] = [];
  if (row.held) out.push(HELD);
  if (row.favorite) out.push(FAV);
  if (row.watched) out.push(WATCH);
  for (const name of row.lists ?? []) out.push(listSource(name));
  return out;
}

/** The bucket a row files under. */
export function bucket(row: ReviewRow): string {
  if (row.sector) return sectorKey(row.sector);
  if (row.kind === "crypto") return "crypto";
  if (row.kind && row.kind !== "stock") return "funds";
  return "unknown";
}

const list = (value: string | null) => [
  ...new Set(
    (value ?? "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean),
  ),
];

/** `?in=` for "everything"; no `?in=` at all is the book alone. */
const ALL = "all";

/** The include filter as it goes in the URL: nothing for the default. */
export function includeParam(sources: string[], held = true): string | undefined {
  if (sources.length === 0) return held ? ALL : undefined;
  if (held && sources.length === 1 && sources[0] === HELD) return undefined;
  return sources.join(",");
}

export function parseFilter(
  sector: string | null,
  w: string | null,
  include: string | null = null,
  held = true,
): Filter {
  const band = w && w in BANDS ? (w as Band) : null;
  if (include === null) {
    return { sectors: list(sector), band, sources: held ? [HELD] : [] };
  }
  const sources = list(include).filter(
    (source) =>
      source === HELD || source === FAV || source === WATCH || listName(source),
  );
  return { sectors: list(sector), band, sources };
}

export const isFiltered = (filter: Filter) =>
  filter.sectors.length > 0 || filter.band !== null || filter.sources.length > 0;

function inBand(row: ReviewRow, band: Band | null): boolean {
  if (band === null) return true;
  const [low, high] = BANDS[band];
  const weight = row.weight ?? 0;
  return weight >= low && weight < high;
}

/**
 * The review cut down to the filter, with the plan re-added from the rows
 * left — the server's plan is the same sum over every row
 * (`routes/review.py`), so the two agree when nothing is filtered.
 */
export function applyFilter(data: Review, filter: Filter): Review {
  if (!isFiltered(filter)) return data;
  const added = new Set(data.added.map((ticker) => ticker.toUpperCase()));
  const included = (row: ReviewRow) =>
    filter.sources.length === 0 ||
    added.has(row.ticker.toUpperCase()) ||
    sourcesOfRow(row).some((source) => filter.sources.includes(source));
  const sector = (row: ReviewRow) =>
    included(row) &&
    (filter.sectors.length === 0 || filter.sectors.includes(bucket(row)));
  const held = data.held.filter((row) => sector(row) && inBand(row, filter.band));
  const candidates = data.candidates.filter(sector);
  const moves = held.map((row) => row.delta).filter((d): d is number => d !== null);
  const taxes = held.map((row) => row.tax).filter((x): x is number => x !== null);
  return {
    ...data,
    held,
    candidates,
    plan: {
      ...data.plan,
      sells: moves.filter((d) => d < 0).reduce((a, b) => a - b, 0),
      buys: moves.filter((d) => d > 0).reduce((a, b) => a + b, 0),
      tax: taxes.length ? taxes.reduce((a, b) => a + b, 0) : null,
    },
  };
}

/**
 * The read without its coins, and the held coins on their own.
 *
 * The page judges businesses on their filings; a coin has none, so every coin
 * row read "unrated · no fundamentals" with n/a in every score — a table of
 * blanks, a "Crypto" sector chip leading to more of them, and outside coins
 * the page could never call buy or pass. They leave the read before anything
 * draws it; held coins keep one line saying what share of the book they are.
 */
export function splitCoins(data: Review): [Review, ReviewRow[]] {
  const coin = (row: ReviewRow) => row.kind === "crypto";
  if (![...data.held, ...data.candidates].some(coin)) return [data, []];
  const book = {
    ...data,
    held: data.held.filter((row) => !coin(row)),
    candidates: data.candidates.filter((row) => !coin(row)),
  };
  return [book, data.held.filter(coin)];
}

/** Every bucket in the read, biggest first, with how many names it holds. */
export function sectorsOf(
  data: Review,
): { key: string; name: string; count: number }[] {
  const seen = new Map<string, { key: string; name: string; count: number }>();
  for (const row of [...data.held, ...data.candidates]) {
    const key = bucket(row);
    const entry = seen.get(key) ?? { key, name: row.sector ?? key, count: 0 };
    entry.count += 1;
    seen.set(key, entry);
  }
  return [...seen.values()].sort(
    (a, b) => b.count - a.count || a.key.localeCompare(b.key),
  );
}

/**
 * The sources this read can be narrowed to, in chip order — the book, the
 * starred names, the whole watchlist, then each group A–Z — with how many
 * names each holds. A source with nothing in it gets no chip.
 */
export function sourcesOf(data: Review): { key: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const row of [...data.held, ...data.candidates]) {
    for (const source of sourcesOfRow(row)) {
      counts.set(source, (counts.get(source) ?? 0) + 1);
    }
  }
  const lists = [...counts.keys()]
    .filter((key) => listName(key) !== null)
    .sort((a, b) => a.localeCompare(b));
  return [HELD, FAV, WATCH, ...lists]
    .filter((key) => counts.has(key))
    .map((key) => ({ key, count: counts.get(key) ?? 0 }));
}

/** Lower case, accents off: "energía" finds "Energia" and the other way round. */
const fold = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();

/**
 * The rows a table's search box keeps: those whose ticker, symbol or any of
 * `words` (name, sector, verdict — in the reader's language) holds the text.
 */
export function findRows<R extends Pick<ReviewRow, "ticker" | "symbol">>(
  rows: R[],
  needle: string,
  words: (row: R) => (string | null | undefined)[],
): R[] {
  const want = fold(needle.trim());
  if (!want) return rows;
  return rows.filter((row) =>
    [row.ticker, row.symbol, ...words(row)].some(
      (text) => !!text && fold(text).includes(want),
    ),
  );
}
