import { numberLang } from "./numbers";

/**
 * An API calendar day as "12 oct 2026" (en: "12 Oct 2026"): the one way the
 * UI prints a date, so a table never mixes "2026-10-12" with "Oct 12, 2026".
 *
 * Built field by field, not `new Date(iso)`, which reads a bare date as UTC
 * and slides it a day west of Greenwich. Anything that is not a date (a
 * dash, a free-text note) comes back as it was.
 */
export function calendarDay(
  iso: string | null | undefined,
  lang: string = numberLang(),
): string {
  if (!iso) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  if (Number.isNaN(date.getTime())) return iso;
  // British English orders day before month, like Spanish; en-US would not.
  const locale = lang.toLowerCase().startsWith("en") ? "en-GB" : lang;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}
