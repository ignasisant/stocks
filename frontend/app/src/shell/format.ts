/**
 * One way to print a figure, for every screen.
 *
 * A value the API could not compute is `null`, and every helper here hands it
 * back as `null` rather than substituting a zero: an unmeasurable return and a
 * return of zero are different claims. The caller decides what "nothing" reads
 * as on its page, either its own `*.na` catalog string or `DASH`.
 *
 * Options, not argument order: `money(v, { currency, signed })`,
 * `percent(v, { digits })`. `lang` defaults to the account's language
 * (`shell/numbers`), so a caller only passes it when it holds a different one.
 */

import { formatter, num, numberLang } from "./numbers";

/** What a figure that is not there prints as, for the pages that print one. */
export const DASH = "—";

type Maybe = number | null | undefined;

/**
 * How a figure carries its sign. `true` prints `+`/`-` and nothing on an exact
 * zero (`exceptZero`); `"always"` also prints `+0`, as a hand-built `+` did.
 */
type Signed = boolean | "always";

function signDisplay(signed: Signed | undefined): "always" | "exceptZero" | "auto" {
  return signed === "always" ? "always" : signed ? "exceptZero" : "auto";
}

export function isNum(value: Maybe): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export interface MoneyOptions {
  /** An ISO code; leave out for a bare grouped number. */
  currency?: string;
  lang?: string;
  digits?: number;
  signed?: Signed;
  /** Past a thousand, "12.5k €", "1.5M €" — for a chart axis. */
  compact?: boolean;
}

/**
 * An amount in a currency, in the reader's language ("1.234 €" / "€1,234").
 *
 * Not every currency string is the account's: a ledger row can carry a
 * broker's own code that `Intl` throws a RangeError on, and a throw inside
 * render blanks the page, so an unknown one falls back to the amount with its
 * code beside it.
 */
export function money(value: number, options?: MoneyOptions): string;
export function money(value: Maybe, options?: MoneyOptions): string | null;
export function money(value: Maybe, options: MoneyOptions = {}): string | null {
  if (!isNum(value)) return null;
  const { currency, lang = numberLang(), signed } = options;
  const compact = options.compact ? scaleDown(value) : null;
  const scaled = compact ? value / compact.scale : value;
  const digits = options.digits ?? (compact && !Number.isInteger(scaled) ? 1 : 0);
  const shape = {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: signDisplay(signed),
  };
  let text: string;
  if (!currency) {
    text = formatter(lang, shape).format(scaled);
  } else {
    try {
      text = formatter(lang, { style: "currency", currency, ...shape }).format(scaled);
    } catch {
      text = `${formatter(lang, shape).format(scaled)} ${currency}`;
      if (compact) return text.replace(/(\d)(\D*)$/, `$1${compact.suffix}$2`);
    }
  }
  // Splice the suffix right after the last digit, so the currency symbol's
  // side and the locale's decimal mark stay where Intl put them.
  return compact ? text.replace(/(\d)(\D*)$/, `$1${compact.suffix}$2`) : text;
}

function scaleDown(value: number): { scale: number; suffix: string } | null {
  const abs = Math.abs(value);
  if (abs >= 1e9) return { scale: 1e9, suffix: "B" };
  if (abs >= 1e6) return { scale: 1e6, suffix: "M" };
  if (abs >= 1e3) return { scale: 1e3, suffix: "k" };
  return null;
}

export interface PercentOptions {
  lang?: string;
  digits?: number;
  signed?: Signed;
  /**
   * The tables' reading, "12,3%" with no space; the default is whatever the
   * language's own `Intl` percent is ("12,3 %" in Spanish).
   */
  tight?: boolean;
  /** `value` is already in percentage points, not a fraction. */
  points?: boolean;
}

/** A fraction as a percentage: 0.1234 to "12.3%". */
export function percent(value: number, options?: PercentOptions): string;
export function percent(value: Maybe, options?: PercentOptions): string | null;
export function percent(value: Maybe, options: PercentOptions = {}): string | null {
  if (!isNum(value)) return null;
  const { lang = numberLang(), digits = 1, signed, tight, points } = options;
  const shape = {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: signDisplay(signed),
  };
  if (tight || points) {
    return `${formatter(lang, shape).format(points ? value : value * 100)}%`;
  }
  return formatter(lang, { style: "percent", ...shape }).format(value);
}

/** A grouped number at a fixed number of decimals. */
type DecimalOptions = { lang?: string; digits?: number; signed?: Signed };

export function decimal(value: number, options?: DecimalOptions): string;
export function decimal(value: Maybe, options?: DecimalOptions): string | null;
export function decimal(value: Maybe, options: DecimalOptions = {}): string | null {
  if (!isNum(value)) return null;
  const { lang = numberLang(), digits = 2, signed } = options;
  return formatter(lang, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: signDisplay(signed),
  }).format(value);
}

/**
 * Share counts: enough decimals for a fractional share, none for a whole one.
 *
 * The ledger holds 0.0031 of a name as readily as 12 of another, and "12.0000"
 * beside it is noise. `fixed` is the ledger tables' reading instead, four
 * decimals always, so the figures line up down the column.
 */
export function shares(
  value: Maybe,
  options: { lang?: string; fixed?: boolean } = {},
): string | null {
  if (!isNum(value)) return null;
  const { lang = numberLang(), fixed = false } = options;
  return formatter(lang, {
    minimumFractionDigits: fixed ? 4 : 0,
    maximumFractionDigits: 4,
  }).format(value);
}

/**
 * Compact money, "$81.60B" / "-€1.2M" / "€950": the sign ahead of the mark,
 * `digits` decimals on a suffix and none under a thousand.
 *
 * `prefix` is whatever mark the caller spells the currency with (the server's
 * `currency_symbol`, or `currencySymbol`), so a currency printed bare stays
 * bare. Share counts go through the same function with no prefix.
 */
export function compact(
  value: Maybe,
  options: { prefix?: string; digits?: number } = {},
): string | null {
  if (!isNum(value)) return null;
  const { prefix = "", digits = 2 } = options;
  const sign = value < 0 ? "-" : "";
  const size = Math.abs(value);
  for (const [limit, unit] of UNITS) {
    if (size >= limit) return `${sign}${prefix}${num(size / limit, digits)}${unit}`;
  }
  return `${sign}${prefix}${num(size, 0)}`;
}

/** Thousands to trillions, largest first. */
export const UNITS = [
  [1e12, "T"],
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
] as const;

/**
 * A formatter bound to one currency and language: the reporting one, a tax
 * replay's, or a dividend's own.
 */
export type Money = (
  value: Maybe,
  options?: { digits?: number; signed?: Signed },
) => string | null;

export function moneyIn(lang: string, currency: string): Money {
  return (value, options) => money(value, { lang, currency, ...options });
}

/** `moneyIn`, shorthand past a thousand. */
export function compactMoneyIn(lang: string, currency: string): Money {
  return (value, options) =>
    money(value, { lang, currency, compact: true, ...options });
}
