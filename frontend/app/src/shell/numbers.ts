/**
 * One way to print a number, for every screen that has no `lang` in hand.
 *
 * The account's language is published once, by `Translations`, and read here:
 * a price on the ticker page, a cohort metric on the sector page and a mover on
 * Home are spelled by the same Intl rules ("1.234,56" in Spanish, "1,234.56"
 * in English), never by a hardcoded C locale. Grouping is always on: es-ES
 * Intl leaves four-digit numbers bare ("9411") and groups five ("27.246"),
 * which reads as two conventions in one table.
 */

let current = "en";

/** Set by `Translations` as the catalog's language changes. */
export function setNumberLang(lang: string): void {
  current = lang || "en";
}

export function numberLang(): string {
  return current;
}

const cache = new Map<string, Intl.NumberFormat>();

/** An `Intl.NumberFormat` with grouping forced on, cached per shape. */
export function formatter(
  lang: string,
  options: Intl.NumberFormatOptions,
): Intl.NumberFormat {
  const key = `${lang}|${JSON.stringify(options)}`;
  let format = cache.get(key);
  if (!format) {
    format = new Intl.NumberFormat(lang, {
      ...options,
      useGrouping: "always",
    } as unknown as Intl.NumberFormatOptions);
    cache.set(key, format);
  }
  return format;
}

/** `value` to a fixed number of decimals, grouped, in the account's language. */
export function num(value: number, digits = 2, lang = current): string {
  return formatter(lang, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** As `num`, with the sign always printed ("+1,29", "-0,40", "+0,00"). */
function signedNum(value: number, digits = 2, lang = current): string {
  return `${value >= 0 ? "+" : ""}${num(value, digits, lang)}`;
}

/** A fraction as a percentage: 0.1234 to "12,3%" (no space, as the tables set it). */
export function pctNum(value: number, digits = 1, lang = current): string {
  return `${num(value * 100, digits, lang)}%`;
}

/** …and always signed: 0.0129 to "+1,29%". */
export function signedPct(value: number, digits = 1, lang = current): string {
  return `${signedNum(value * 100, digits, lang)}%`;
}
