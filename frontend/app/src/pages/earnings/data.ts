/**
 * What `/api/v1/earnings` sends, and the pure arithmetic the two views share.
 *
 * Dates stay strings the whole way through. The API quotes a print as a plain
 * ISO day with no time and no zone; parsing one into a `Date` to compare it
 * against a cell is how a report lands on the wrong square for a reader east of
 * UTC. The grid therefore builds its cells as ISO keys and matches on them.
 *
 * The month arithmetic mirrors `stocks.data.earnings.add_months` /
 * `month_weeks` (stdlib `Calendar(firstweekday=0).monthdatescalendar`): weeks
 * run Monday-first and spill into the adjacent months, which is why a month can
 * draw four, five or six rows.
 */

export type CalendarEvent = {
  ticker: string;
  /** Reporting date, ISO. Null when the feed knows the name but not the day. */
  date: string | null;
  /** Days from today; 0 is a print due today. */
  days_until: number | null;
};

export type CalendarResult = {
  ticker: string;
  date: string;
  eps_estimate: number | null;
  reported_eps: number | null;
  surprise_pct: number | null;
  /** Null when there was nothing to compare — neutral, never a miss. */
  beat: boolean | null;
};

export type EarningsCalendar = {
  upcoming: CalendarEvent[];
  results: CalendarResult[];
  /** `portfolio`, `favorites`, then one per watchlist tag. Empty sets are gone. */
  groups: Record<string, string[]>;
  /** Watchlist names that never report: coins and funds. */
  skipped: string[];
};

/** A print this close is the one the page warns about up front. */
const IMMINENT_DAYS = 7;

export function isSoon(event: CalendarEvent): boolean {
  return event.days_until !== null && event.days_until <= IMMINENT_DAYS;
}

export type Day = {
  iso: string;
  day: number;
  /** False for the spill from the previous or next month — drawn dimmed. */
  inMonth: boolean;
  today: boolean;
};

function isoDay(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function today(now = new Date()): string {
  return isoDay(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

/** Shift a (year, month) by `delta` months, wrapping the year. Pure. */
export function addMonths(
  year: number,
  month: number,
  delta: number,
): [number, number] {
  const index = year * 12 + (month - 1) + delta;
  return [Math.floor(index / 12), (index % 12) + 1];
}

/** Weeks (Monday first) of days covering the month, adjacent spill included. */
export function monthWeeks(year: number, month: number, now: string): Day[][] {
  const first = new Date(year, month - 1, 1);
  // getDay() is Sunday-first; (day + 6) % 7 makes Monday 0, which is the
  // weekday order the header row and the Python grid both use.
  const cursor = new Date(year, month - 1, 1 - ((first.getDay() + 6) % 7));
  const last = new Date(year, month, 0);
  const weeks: Day[][] = [];
  do {
    const week: Day[] = [];
    for (let i = 0; i < 7; i += 1) {
      const key = isoDay(cursor.getFullYear(), cursor.getMonth() + 1, cursor.getDate());
      week.push({
        iso: key,
        day: cursor.getDate(),
        inMonth: cursor.getMonth() + 1 === month && cursor.getFullYear() === year,
        today: key === now,
      });
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  } while (cursor <= last);
  return weeks;
}

/** Index events or results by their ISO day; anything undated is dropped. */
export function byDate<T extends { date: string | null }>(
  items: T[],
): Map<string, T[]> {
  const grouped = new Map<string, T[]>();
  for (const item of items) {
    if (item.date === null) continue;
    const bucket = grouped.get(item.date);
    if (bucket) bucket.push(item);
    else grouped.set(item.date, [item]);
  }
  return grouped;
}

/**
 * The tickers the picked filters allow — a UNION, not an intersection.
 *
 * Picking Portfolio and Favorites asks for the names in either: a reader
 * narrowing by two groups is widening the net, and an intersection would hide
 * every favourite they do not own. Null means nothing is picked, which is
 * everything rather than nothing.
 */
export function allowed(
  groups: Record<string, string[]>,
  picked: string[],
): Set<string> | null {
  if (picked.length === 0) return null;
  const names = new Set<string>();
  for (const key of picked) for (const ticker of groups[key] ?? []) names.add(ticker);
  return names;
}

export function only<T extends { ticker: string }>(
  items: T[],
  names: Set<string> | null,
): T[] {
  return names === null ? items : items.filter((item) => names.has(item.ticker));
}
