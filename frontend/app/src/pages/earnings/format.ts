/**
 * How this page prints a figure, and what it prints when there is none.
 *
 * A null EPS, a null surprise and a null day count are all "nobody could say",
 * not zero: the feed publishes a date long before it publishes a number, and a
 * 0.00 beside an estimate reads as a company that earned nothing. So every
 * formatter here funnels null to a dash.
 */

export type T = (key: string, slots?: Record<string, string | number>) => string;

/** Not a figure — the em dash the Streamlit page prints for the same gap. */
const DASH = "—";

export function eps(value: number | null): string {
  return value === null ? DASH : value.toFixed(2);
}

/** A signed number with no unit — what `earnings.surprise_vs_est` slots in. */
export function signedNum(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

/** Always signed: a surprise printed without its sign reads as a level. */
export function signedPct(value: number | null, digits = 1): string {
  return value === null ? DASH : `${signedNum(value, digits)}%`;
}

export function days(value: number | null): string {
  return value === null ? DASH : String(value);
}

/** The green/red/neutral class a signed figure gets, neutral when unknown. */
export function tone(value: number | null | undefined): string {
  if (value === null || value === undefined) return "earn-flat";
  return value >= 0 ? "earn-up" : "earn-down";
}

function parts(iso: string): [number, number, number] {
  const [year, month, day] = iso.split("-");
  return [Number(year), Number(month), Number(day)];
}

/** "Sep 18, 2026" — the shape `earnings_ui._long_date` prints, via the same keys. */
export function longDate(iso: string, t: T): string {
  const [year, month, day] = parts(iso);
  return `${t(`earnings.mon_${month}`)} ${String(day).padStart(2, "0")}, ${year}`;
}

/**
 * Catalog copy written for Streamlit's markdown, as plain text.
 *
 * Several earnings strings are stored with their emphasis in them —
 * `**Upcoming**`, `:gray[Reported Sep 18, 2026]` — because the Python page
 * hands them straight to `st.markdown`. React renders text, not markdown, so
 * those markers would print literally. Stripping them here keeps one catalog
 * for both front ends instead of a second set of keys that says the same thing.
 */
export function plain(value: string): string {
  return value.replace(/\*\*/g, "").replace(/^:[a-z-]+\[(.*)\]$/, "$1");
}
