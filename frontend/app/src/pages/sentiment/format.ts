/**
 * Numbers, units and the one colour rule this page exists to keep.
 *
 * Two things here are not formatting preferences:
 *
 * * A figure the API could not compute is `null` and renders as `n/a`. Never a
 *   zero — an unmeasurable beta and a beta of zero are different claims.
 * * A change is coloured by `welcome × sign(change)`, never by sign alone. A
 *   widening credit spread and a falling index are both bad news, and a page
 *   that paints on sign paints half of itself backwards.
 *
 * Everything is formatted the way the Streamlit page formats it — C locale,
 * dot decimals, comma groups — because these numbers sit beside the same
 * figures on the pages that have not migrated yet, and two spellings of the
 * same yield on two screens is worse than one that ignores the locale.
 */

/** What a figure that could not be computed reads as. Never `0`, never a dash. */
export const NA = "n/a";

const GROUPS = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function known(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

export function fixed(value: number | null, digits: number, suffix = ""): string {
  return known(value) ? `${value.toFixed(digits)}${suffix}` : NA;
}

/** A signed level — `+0.42`, `-33bp`. The sign is the number's own, not a verdict. */
export function signed(value: number | null, digits: number, suffix = ""): string {
  if (!known(value)) return NA;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

/** A fraction as a signed percentage: `0.0123` to `+1.2%`. */
export function percent(value: number | null, digits = 1): string {
  if (!known(value)) return NA;
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

/** A fraction as an unsigned share: `0.71` to `71%`. */
export function share(value: number | null, digits = 0): string {
  return known(value) ? `${(value * 100).toFixed(digits)}%` : NA;
}

/** An index level: grouped, no decimals. */
export function grouped(value: number | null): string {
  return known(value) ? GROUPS.format(value) : NA;
}

/**
 * A price whose scale we do not know in advance.
 *
 * The cross-asset block runs from EUR/USD at 1.08 to bitcoin at 60,000, and
 * the API sends no per-row format, so the decimals follow the magnitude: four
 * on a currency pair, two on a barrel of oil, none on a coin.
 */
export function adaptive(value: number | null): string {
  if (!known(value)) return NA;
  const size = Math.abs(value);
  if (size >= 1000) return GROUPS.format(value);
  return value.toFixed(size >= 2 ? 2 : 4);
}

/**
 * One change cell, in the unit its block declared.
 *
 * `basis_points` arrives already multiplied — the API quotes a rate move in
 * basis points because "+7.4%" on a 4.79% yield reads like a price move and is
 * not one. `points` is a percentage-point move in a rate that is itself a
 * percentage, which is why it is neither of the other two.
 */
export function changeText(unit: string, value: number): string {
  if (unit === "basis_points") return signed(value, 0, "bp");
  if (unit === "points") return signed(value, 1, "pp");
  return percent(value, 1);
}

/**
 * Whether this move is the welcome one: +1 good, -1 bad, 0 no verdict.
 *
 * `welcome` says which DIRECTION is the good news for this series; the sign of
 * the change says which way it went. Only the product of the two is a verdict,
 * and a row with `welcome === 0` — a policy rate, the dollar — has none.
 */
export function tone(change: number, welcome: number): number {
  if (welcome === 0 || change === 0 || !Number.isFinite(change)) return 0;
  return change > 0 ? Math.sign(welcome) : -Math.sign(welcome);
}

/** The class that paints a tone. Colours live in the stylesheet, as tokens. */
export function toneClass(value: number): string {
  return value > 0 ? "sn-good" : value < 0 ? "sn-bad" : "sn-flat";
}

/**
 * A ticker as an i18n key fragment: `^GSPC` to `gspc`, `GC=F` to `gc_f`.
 *
 * The catalogs key their per-row explanations this way (`sentiment.tip_index_gspc`),
 * so this has to match `sentiment.py::_slug` character for character.
 */
export function slug(ticker: string): string {
  return ticker
    .toLowerCase()
    .replace(/^\^+/, "")
    .replace(/[^a-z0-9]/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** A sector name as the catalogs spell it: `Financial Services` to `financial_services`. */
export function sectorKey(name: string): string {
  return name.toLowerCase().replaceAll(" ", "_");
}

/**
 * `t(key)`, or nothing when the catalogs have no entry for it.
 *
 * `useT` returns the key itself for a miss, which is the right default for a
 * hardcoded key — a dotted key on screen is a bug report that writes itself —
 * and the wrong one for keys built from upstream data, where Yahoo inventing a
 * new sector spelling tomorrow must print that spelling and not
 * `sentiment.sector_whatever`.
 */
export function maybe(
  t: (key: string, slots?: Record<string, string | number>) => string,
  key: string,
): string | undefined {
  const text = t(key);
  return text === key ? undefined : text;
}
