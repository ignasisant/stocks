/**
 * The watchlist card's reading, apart from its drawing: which group is open,
 * in what order, what needs a look first, and which columns have anything to
 * say. Pure, so the rules are tested without a page.
 */

import type { CloseRow, WatchlistEntry } from "./types";

/**
 * A day move this many times the name's usual daily swing is flagged "odd":
 * a split the feed missed, a bad previous close or real news — either way,
 * worth a look before trusting it. Mirrors `views.home.ODD_MOVE_Z`.
 */
const ODD_MOVE = 5;
/** Earnings this close get a line in «Ahora»; further out, only the column. */
const EARNINGS_SOON_DAYS = 7;
/** The column shows a date this far out at most: further is not news yet. */
const EARNINGS_COLUMN_DAYS = 30;
/** «Ahora» shows this many lines before «Ver N más». */
export const NOW_MAX = 4;

export type Earnings = { date: string; days: number };

export type WatchRow = {
  entry: WatchlistEntry;
  /** Null while the closes load, or for a name the download missed. */
  close: CloseRow | null;
  earnings: Earnings | null;
};

export type GroupId = "fav" | "rest" | "all" | `tag:${string}`;
export type Group = { id: GroupId; tag: string | null; count: number };

export function inGroup(rows: WatchRow[], id: GroupId): WatchRow[] {
  if (id === "all") return rows;
  if (id === "fav") return rows.filter((row) => row.entry.favorite);
  if (id === "rest")
    return rows.filter((row) => !row.entry.favorite && row.entry.tags.length === 0);
  const tag = id.slice(4);
  return rows.filter((row) => row.entry.tags.includes(tag));
}

/**
 * Favourites, each tag alphabetically, the untagged rest, then everything.
 * Empty groups drop out; a list with no favourites and no tags has only
 * «Todos», and the card then draws no chips at all.
 */
export function groups(rows: WatchRow[]): Group[] {
  const tags = [...new Set(rows.flatMap((row) => row.entry.tags))].sort((a, b) =>
    a.toUpperCase().localeCompare(b.toUpperCase()),
  );
  const ids: GroupId[] = ["fav", ...tags.map((tag) => `tag:${tag}` as const), "rest"];
  const named = ids
    .map((id) => ({
      id,
      tag: id.startsWith("tag:") ? id.slice(4) : null,
      count: inGroup(rows, id).length,
    }))
    .filter((group) => group.count > 0);
  // The rest alone is the whole list again.
  const split = named.filter((group) => group.id !== "rest").length > 0;
  return [...(split ? named : []), { id: "all", tag: null, count: rows.length }];
}

/** The group a card opens on: favourites when there are any. */
export function openGroup(list: Group[], picked: GroupId | null): GroupId {
  if (picked && list.some((group) => group.id === picked)) return picked;
  return list[0]?.id ?? "all";
}

export type SortId = "day" | "month" | "zone" | "own";

/** Met, part met, near, far, no rule. */
function zoneRank(close: CloseRow | null): number {
  const zone = close?.zone;
  if (!zone) return 4;
  if (zone.state === "met") return zone.met < zone.rules ? 1 : 0;
  return zone.state === "near" ? 2 : 3;
}

/** Best first; a row with nothing to sort by goes last, in the list's order. */
export function sortRows(rows: WatchRow[], by: SortId): WatchRow[] {
  if (by === "own") return rows;
  const key = (row: WatchRow): number | null => {
    if (by === "day") return row.close?.pct ?? null;
    if (by === "month") return row.close?.month_pct ?? null;
    return -zoneRank(row.close);
  };
  return [...rows].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    if (x === null || y === null) return x === null ? (y === null ? 0 : 1) : -1;
    return y - x;
  });
}

export function isOdd(close: CloseRow | null): boolean {
  return (close?.move_size ?? 0) >= ODD_MOVE;
}

type NowKind = "met" | "odd" | "part" | "earn" | "near";
export type NowItem = { kind: NowKind; row: WatchRow };

/**
 * What needs a look today, across the whole list rather than the open group:
 * a buy zone reached first, then a move far outside the name's usual swing,
 * a rule partly met, results within the week, a zone getting close.
 */
export function nowItems(rows: WatchRow[]): NowItem[] {
  const pick = (kind: NowKind, test: (row: WatchRow) => boolean) =>
    rows.filter(test).map((row) => ({ kind, row }));
  return [
    ...pick("met", (row) => zoneRank(row.close) === 0),
    ...pick("odd", (row) => isOdd(row.close)),
    ...pick("part", (row) => zoneRank(row.close) === 1),
    ...pick(
      "earn",
      (row) => row.earnings !== null && row.earnings.days <= EARNINGS_SOON_DAYS,
    ),
    ...pick("near", (row) => zoneRank(row.close) === 2),
  ];
}

export type Tally = { up: number; down: number; median: number | null };

/** How the open group moved today: names up, names down, the middle move. */
export function tally(rows: WatchRow[]): Tally {
  const moves = rows
    .map((row) => row.close?.pct)
    .filter((pct): pct is number => typeof pct === "number")
    .sort((a, b) => a - b);
  const mid = Math.floor(moves.length / 2);
  const upper = moves[mid];
  const lower = moves[mid - 1];
  const median =
    upper === undefined
      ? null
      : moves.length % 2 || lower === undefined
        ? upper
        : (lower + upper) / 2;
  return {
    up: moves.filter((pct) => pct > 0).length,
    down: moves.filter((pct) => pct < 0).length,
    median,
  };
}

/** A column with nothing in it for this group is not drawn. */
export function columns(rows: WatchRow[]): { zone: boolean; earnings: boolean } {
  return {
    zone: rows.some((row) => row.close?.zone),
    earnings: rows.some((row) => row.earnings !== null),
  };
}

/**
 * Each name's next results from `/earnings`, within the column's horizon.
 * The calendar is keyed as the watchlist is; case is the only drift.
 */
export function earningsByTicker(
  upcoming: { ticker: string; date: string | null; days_until: number | null }[],
): Map<string, Earnings> {
  const out = new Map<string, Earnings>();
  for (const event of upcoming) {
    const days = event.days_until;
    if (!event.date || days === null || days < 0 || days > EARNINGS_COLUMN_DAYS)
      continue;
    const key = event.ticker.toUpperCase();
    const seen = out.get(key);
    if (!seen || days < seen.days) out.set(key, { date: event.date, days });
  }
  return out;
}
