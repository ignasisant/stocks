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

/**
 * Compact money — "$81.60B", "€1.24T" — the shape `earnings_ui._money` prints.
 *
 * `prefix` is the server's `currency_symbol`, not a code the client maps: the
 * two runtimes then agree on every currency, including the ones it leaves
 * bare (a yen statement prints as plain figures there, and so it does here).
 * Share counts go through the same function with no prefix.
 */
export function money(value: number | null | undefined, prefix = ""): string {
  if (value === null || value === undefined) return DASH;
  const sign = value < 0 ? "-" : "";
  const size = Math.abs(value);
  for (const [div, suffix] of [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ] as const) {
    if (size >= div) return `${sign}${prefix}${grouped(size / div, 2)}${suffix}`;
  }
  return `${sign}${prefix}${grouped(size, 0)}`;
}

function grouped(value: number, digits: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** A fraction as a level: 0.183 → "18.3%". */
export function pct(fraction: number | null | undefined, digits = 1): string {
  return fraction === null || fraction === undefined
    ? DASH
    : `${(fraction * 100).toFixed(digits)}%`;
}

/** A fraction as a change, always signed: 0.052 → "+5.2%". */
export function signedFrac(fraction: number | null | undefined, digits = 1): string {
  return fraction === null || fraction === undefined
    ? DASH
    : `${signedNum(fraction * 100, digits)}%`;
}

/** The short fiscal-quarter tag axes and tables use: "Jun 26". */
export function quarterLabel(iso: string, t: T): string {
  const [year, month] = parts(iso);
  return `${t(`earnings.mon_${month}`)} ${String(year % 100).padStart(2, "0")}`;
}
