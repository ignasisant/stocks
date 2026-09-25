/**
 * Domain tables this screen needs and the API does not serve.
 *
 * Every value here mirrors a Python constant, named in the comment above it.
 * None of it is prose — codes, currency marks and endonyms — so nothing in this
 * file belongs in a catalog.
 *
 * The tax jurisdictions used to be here too, transcribed from
 * `stocks.portfolio.tax`. They are `GET /jurisdictions` now: adding a country
 * is one module under that package plus its catalog copy, and a table copied
 * into the front end drops the new one the day it ships — silently, because
 * nobody reports a country they cannot see. What is left below is what no route
 * serves.
 */

/** `stocks.config.CURRENCIES` — what the app can reckon in. */
export const CURRENCIES = [
  "EUR",
  "USD",
  "GBP",
  "CHF",
  "SEK",
  "NOK",
  "DKK",
  "PLN",
  "CZK",
  "CAD",
  "AUD",
] as const;

/**
 * The five in daily use lead the chip row; the rest sit behind a disclosure.
 * Eleven chips in a row was the widest control on the Streamlit page and the
 * reason its settings column had no room for a rail (canvas 1a).
 */
export const TOP_CURRENCIES = ["EUR", "USD", "GBP", "CHF", "SEK"] as const;

/**
 * `stocks.config.CURRENCY_SYMBOL`, as a chip wants it: the mark alone.
 * CURRENCY_SYMBOL spells the franc and the krona out ("CHF 12") because it
 * prefixes amounts; on a chip that would print the code twice.
 */
const MARKS: Record<string, string> = {
  EUR: "€",
  USD: "$",
  GBP: "£",
  CHF: "₣",
  SEK: "kr",
  NOK: "kr",
  DKK: "kr",
  PLN: "zł",
  CZK: "Kč",
  CAD: "CA$",
  AUD: "A$",
};

/** "€ EUR" — the currency's own mark ahead of its code. */
export function currencyLabel(code: string): string {
  const mark = MARKS[code];
  return mark && mark !== code ? `${mark} ${code}` : code;
}

/**
 * `stocks.web.i18n.LANGUAGES`. Endonyms: a language names itself the same way
 * in every catalog, which is why the Streamlit page does not translate them
 * either.
 */
export const LANGUAGES: Record<string, string> = { en: "English", es: "Español" };

/**
 * `stocks.portfolio.tax.de.CHURCH_TAX_RATES` — stored as fractions.
 *
 * Still here because no route serves it: `/jurisdictions` says *that* Germany
 * asks for a church-tax rate (`settings_fields`), not which three it accepts.
 */
export const CHURCH_RATES = [0.0, 0.08, 0.09] as const;

/** One row of `GET /jurisdictions` — `routes.reference.Jurisdiction`. */
export type Jurisdiction = {
  code: string;
  /** Catalog key naming the country — the name is translated, the flag is not. */
  label_key: string;
  flag: string;
  /** The currency the cost basis is replayed in, not the reporting currency. */
  currency: string;
  /** Share-identification rule; `profile.tax_match_<matching>` names it. */
  matching: string;
  /** (month, day) the tax year opens on. */
  year_start: [number, number];
  /** Statuses its brackets distinguish; empty when the scale ignores it. */
  filing_statuses: string[];
  /** Which bracket inputs this country reads, in the order to offer them. */
  settings_fields: string[];
  carryforward_years: number | null;
  repurchase_window: string | null;
  splits_holding_period: boolean;
  pools_shares: boolean;
};

/** `GET /jurisdictions`: the table, and the code an unset account files under. */
export type Jurisdictions = {
  jurisdictions: Jurisdiction[];
  /** `stocks.portfolio.tax.DEFAULT_CODE` — read, never assumed to be Spain. */
  default: string;
};

function lookup(table: Jurisdictions, code: string | null | undefined) {
  const wanted = String(code ?? "")
    .replace("_", "-")
    .split("-")[0]
    ?.toUpperCase();
  return table.jurisdictions.find((entry) => entry.code === wanted) ?? null;
}

/**
 * Which country's rules apply, including when the setting is "auto".
 *
 * `tax.prefs.resolve`: the preference, else the browser's region when it is one
 * of ours, else the table's own default. The region comes off
 * `navigator.language` exactly as the Streamlit page reads it off
 * `st.context.locale` — and, as there, a region we do not model (an "en-GB"
 * browser: GB is not UK) lands on the default.
 *
 * Null only for a table with no jurisdictions at all, which is a broken API
 * rather than a state to word: the caller draws nothing.
 */
export function activeJurisdiction(
  table: Jurisdictions,
  stored: string | null,
): Jurisdiction | null {
  if (stored) return lookup(table, stored) ?? lookup(table, table.default);
  const parts = String(navigator.language ?? "")
    .replace("_", "-")
    .split("-");
  const region = parts.length > 1 && parts[1]?.length === 2 ? parts[1]! : "";
  return lookup(table, region) ?? lookup(table, table.default);
}
