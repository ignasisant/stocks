/**
 * Numbers into strings, with one rule running through all of it: a value the
 * API sent as `null` comes back as `null` here too, never as "0" and never as
 * a formatted zero. The caller renders `t("portfolio.na")` in its place.
 *
 * Amounts go through `Intl.NumberFormat` in the account's own language, so a
 * Spanish reader gets "1.234 €" and an English one "€1,234" — the Streamlit
 * page prefixes a symbol by hand, which is the one thing here that is not a
 * transcription of it.
 */

type Maybe = number | null | undefined;

const usable = (value: Maybe): value is number =>
  value !== null && value !== undefined && Number.isFinite(value);

export type Money = (
  value: Maybe,
  options?: { digits?: number; signed?: boolean },
) => string | null;

/**
 * A formatter bound to one currency — the reporting one, a tax replay's, or a
 * dividend's own.
 *
 * Not every currency string on this page is the account's: the forward
 * dividend table quotes each per-share amount in the company's own currency,
 * straight from Yahoo. `Intl` throws a RangeError on anything that is not a
 * well-formed code, and a throw inside render blanks the page — so an
 * unrecognised one falls back to the amount with its code beside it rather
 * than taking the tab down.
 */
export function moneyIn(lang: string, currency: string): Money {
  return (value, options) => {
    if (!usable(value)) return null;
    const digits = options?.digits ?? 0;
    const shape = {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      signDisplay: (options?.signed ? "exceptZero" : "auto") as "exceptZero" | "auto",
    };
    try {
      return new Intl.NumberFormat(lang, {
        style: "currency",
        currency,
        ...shape,
      }).format(value);
    } catch {
      return `${new Intl.NumberFormat(lang, shape).format(value)} ${currency}`;
    }
  };
}

/** A fraction as a percentage: 0.1234 -> "12.3%". */
export function percent(
  lang: string,
  value: Maybe,
  options?: { digits?: number; signed?: boolean },
): string | null {
  if (!usable(value)) return null;
  const digits = options?.digits ?? 1;
  return new Intl.NumberFormat(lang, {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: options?.signed ? "exceptZero" : "auto",
  }).format(value);
}

export function decimal(lang: string, value: Maybe, digits = 2): string | null {
  if (!usable(value)) return null;
  return new Intl.NumberFormat(lang, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/**
 * Share counts: enough decimals for a fractional share, none for a whole one.
 *
 * The ledger holds 0.0031 of a name as readily as 12 of another, and in a
 * list of payers "12.0000" beside it is noise. `fixed` is the ledger tables'
 * reading instead — positions and tax parcels, which the Streamlit page prints
 * at four decimals always, so the figures line up down the column.
 */
export function shares(lang: string, value: Maybe, fixed = false): string | null {
  if (!usable(value)) return null;
  return new Intl.NumberFormat(lang, {
    minimumFractionDigits: fixed ? 4 : 0,
    maximumFractionDigits: fixed || !Number.isInteger(value) ? 4 : 0,
  }).format(value);
}

/** Sign of a figure, for the colour a P/L cell takes. `null` is neither. */
export function tone(value: Maybe): "up" | "down" | "flat" {
  if (!usable(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

/**
 * The flag for a jurisdiction code, built from the code rather than a table —
 * exactly as `web/tax_ui.flag_emoji` does it, including the one code that is
 * not ISO 3166-1 alpha-2.
 */
export function flagOf(code: string): string {
  const alpha2 = code.toUpperCase() === "UK" ? "GB" : code.toUpperCase();
  if (alpha2.length !== 2 || !/^[A-Z]{2}$/.test(alpha2)) return "";
  return [...alpha2]
    .map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65))
    .join("");
}

/** Display names for a ledger broker prefix — `portfolio/platforms.py`. */
const BROKER_NAMES: Record<string, string> = {
  revolut: "Revolut",
  trading212: "Trading 212",
  degiro: "DEGIRO",
  ibkr: "IBKR",
  clicktrade: "ClickTrade",
  saxo: "Saxo",
};

/**
 * "clicktrade" -> "ClickTrade". The two generic buckets — a hand-entered row
 * and a holding no note attributes — are localized instead; everything else is
 * a brand name, which is the same word in both languages.
 */
export function brokerName(key: string, t: (k: string) => string): string {
  if (key === "manual") return t("portfolio.broker_manual");
  if (key === "unknown" || key === "") return t("portfolio.broker_unknown");
  return (
    BROKER_NAMES[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}
