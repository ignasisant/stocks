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

/** A filing date the account's tax residence imposes. */
export type TaxDeadline = {
  /** Catalog stem: `earnings.tax_<key>` names it, `…_body` explains it. */
  key: string;
  date: string;
  /** Negative once it has passed. */
  days_until: number;
  /** The tax year it concerns, as the jurisdiction writes it: "2025/26". */
  year: string;
  /** The day varies (by département, by canton): printed as "around". */
  approximate: boolean;
  /** Due within the next 30 days — the page leads with it. */
  remind: boolean;
};

export type EarningsCalendar = {
  upcoming: CalendarEvent[];
  results: CalendarResult[];
  /** `portfolio`, `favorites`, then one per watchlist tag. Empty sets are gone. */
  groups: Record<string, string[]>;
  /** Watchlist names that never report: coins and funds. */
  skipped: string[];
  /** The tax residence the deadlines below are for. */
  jurisdiction: string | null;
  tax_deadlines: TaxDeadline[];
};

/**
 * What `/api/v1/earnings/{symbol}/result` sends: one past print, broken down.
 *
 * Ratios are fractions (0.183 is 18.3%), as `stocks.data.earnings` computes
 * them; `price_reaction` alone is a percentage, like `surprise_pct`. Every
 * comparison the tiles print (YoY, bps, TTM, the GAAP gap) arrives computed,
 * so this dialog and the Streamlit one cannot disagree about a number.
 */
export type QuarterFigures = {
  /** Fiscal quarter end, ISO — not the report date. */
  end: string;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  pretax_income: number | null;
  tax_provision: number | null;
  rnd: number | null;
  diluted_eps: number | null;
  diluted_shares: number | null;
  gross_margin: number | null;
  operating_margin: number | null;
  net_margin: number | null;
  rnd_intensity: number | null;
  tax_rate: number | null;
  revenue_yoy: number | null;
  revenue_qoq: number | null;
};

export type QuarterBreakdown = {
  quarter: QuarterFigures;
  revenue_ttm: number | null;
  net_income_yoy: number | null;
  /** Up is dilution — the bad direction. */
  shares_yoy: number | null;
  gross_margin_bps: number | null;
  operating_margin_bps: number | null;
  net_margin_bps: number | null;
};

/** Sell-side consensus for one period — never company guidance. */
export type ConsensusPeriod = {
  /** "0q", "+1q", "0y" or "+1y". */
  period: string;
  eps_avg: number | null;
  eps_low: number | null;
  eps_high: number | null;
  eps_growth: number | null;
  eps_analysts: number | null;
  rev_avg: number | null;
  rev_low: number | null;
  rev_high: number | null;
  rev_growth: number | null;
  rev_analysts: number | null;
  currency: string | null;
  currency_prefix: string;
};

export type ResultDetailData = {
  ticker: string;
  name: string;
  logo: string | null;
  date: string;
  /** Null when the feed has no figures for that date. */
  result: CalendarResult | null;
  price_reaction: number | null;
  /** Filed and matched / statements exist but not this quarter's / none at all. */
  quarter_state: "matched" | "pending" | "none";
  currency: string | null;
  currency_prefix: string;
  breakdown: QuarterBreakdown | null;
  /** Newest first, up to five. */
  trend: QuarterFigures[];
  eps_gaap_gap: number | null;
  /** Every print the feed carries for the name, newest first. */
  history: CalendarResult[];
  outlook: ConsensusPeriod | null;
  outlook_periods: ConsensusPeriod[];
  /** The breakdown fetch failed this time; the headline still stands. */
  unavailable: boolean;
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
