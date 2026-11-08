/**
 * How this page prints a figure, and what it prints when there is none.
 *
 * A null EPS, a null surprise and a null day count are all "nobody could say",
 * not zero: the feed publishes a date long before it publishes a number, and a
 * 0.00 beside an estimate reads as a company that earned nothing. So every
 * formatter here funnels null to a dash.
 */

import { DASH } from "../../shell/format";
import { numberLang } from "../../shell/numbers";

export type T = (key: string, slots?: Record<string, string | number>) => string;

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

/** "18 sep 2026" — a calendar day in the account's language (the `t` is kept for callers). */
export function longDate(iso: string, _t?: T): string {
  const [year, month, day] = parts(iso);
  return new Intl.DateTimeFormat(numberLang(), {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(year ?? 0, (month ?? 1) - 1, day ?? 1));
}

/**
 * Catalog copy that carries markdown, as plain text.
 *
 * Several earnings strings are stored with their emphasis in them —
 * `**Upcoming**`, `:gray[Reported Sep 18, 2026]`. React renders text, not
 * markdown, so those markers would print literally. Stripping them here keeps
 * the catalog as it is instead of a second set of keys that says the same
 * thing.
 */
export function plain(value: string): string {
  return value.replace(/\*\*/g, "").replace(/^:[a-z-]+\[(.*)\]$/, "$1");
}

/** The short fiscal-quarter tag axes and tables use: "Jun 26". */
export function quarterLabel(iso: string, t: T): string {
  const [year, month] = parts(iso);
  return `${t(`earnings.mon_${month}`)} ${String(year % 100).padStart(2, "0")}`;
}
