/**
 * Numbers into strings, and the two rules that are not preferences.
 *
 * A figure the API could not compute is `null` and renders as an em dash.
 * Never a zero: an unmeasurable return and a return of zero are different
 * claims, and printing both as `0` is the failure the whole API sends nulls to
 * prevent.
 *
 * And growth is measured against the MAGNITUDE of the base, because a plain
 * `cur / prev - 1` reports a loss deepening from -56M to -187M as +233%.
 */

/** What an uncomputable figure reads as. Never `0`. */
export const DASH = "—";

import type { Bars } from "./types";

type Maybe = number | null | undefined;

export function known(value: Maybe): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

/**
 * A price or an amount, in the C locale the Streamlit page prints.
 *
 * Deliberately not `Intl` keyed on the reader's language: these figures sit
 * beside the same prices on the pages that have not migrated yet, and two
 * spellings of one share price across two screens is worse than one that
 * ignores the locale.
 */
export function money(value: Maybe, digits = 2): string {
  if (!known(value)) return DASH;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Always signed. A change printed without its sign is a level. */
export function signed(value: Maybe, digits = 2): string {
  if (!known(value)) return DASH;
  return `${value >= 0 ? "+" : ""}${money(value, digits)}`;
}

/** A fraction as a percentage: 0.1234 -> "12.3%". */
export function percent(value: Maybe, digits = 1): string {
  return known(value) ? `${(value * 100).toFixed(digits)}%` : DASH;
}

/** 391_000_000_000 as "391B", with an optional currency after it. */
export function compact(value: Maybe, suffix = ""): string {
  if (!known(value)) return DASH;
  const sign = value < 0 ? "-" : "";
  const size = Math.abs(value);
  const tail = suffix ? ` ${suffix}` : "";
  for (const [limit, unit] of [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ] as const) {
    if (size >= limit) return `${sign}${(size / limit).toPrecision(3)}${unit}${tail}`;
  }
  return `${sign}${size.toPrecision(3)}${tail}`;
}

/**
 * `config.CURRENCY_SYMBOL`, verbatim: the mark a money figure is prefixed with.
 *
 * The Nordic crowns and the franc keep their code with a space, as the Python
 * table does, because three currencies all writing "kr" cannot be told apart
 * in a tile. A currency the table does not list prints its code the same way
 * rather than a wrong mark, and no currency at all prints nothing.
 */
const SYMBOLS: Record<string, string> = {
  EUR: "€",
  USD: "$",
  GBP: "£",
  CHF: "CHF ",
  SEK: "SEK ",
  NOK: "NOK ",
  DKK: "DKK ",
  PLN: "zł",
  CZK: "Kč",
  CAD: "CA$",
  AUD: "A$",
  AED: "AED ",
};

export function currencySymbol(currency: string | null | undefined): string {
  if (!currency) return "";
  const code = currency.toUpperCase();
  return SYMBOLS[code] ?? `${code} `;
}

/**
 * `stocks.formatting.compact_money`: "$394.3B", "-$1.2M", "€950".
 *
 * One decimal on a suffix and the sign ahead of the mark, so a market cap, an
 * AUM and an insider net read here exactly as they do on the Streamlit page —
 * and never `toPrecision(3)`, which prints "1.49T" beside Streamlit's "1.5T".
 */
export function compactMoney(
  value: Maybe,
  currency: string | null | undefined,
): string {
  if (!known(value)) return DASH;
  const sym = currencySymbol(currency);
  const sign = value < 0 ? "-" : "";
  const size = Math.abs(value);
  for (const [limit, unit] of [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ] as const) {
    if (size >= limit) return `${sign}${sym}${(size / limit).toFixed(1)}${unit}`;
  }
  return `${sign}${sym}${Math.round(size).toLocaleString("en-US")}`;
}

/**
 * The mark an insider figure is prefixed with — `config.CURRENCY_SYMBOL` for
 * the only two currencies an insider feed arrives in (Form 4 is USD, BaFin
 * EUR), and the code with a space for anything else rather than a wrong mark.
 */
function mark(currency: string | null): string {
  if (currency === "USD" || currency === null) return "$";
  if (currency === "EUR") return "€";
  return `${currency} `;
}

/**
 * An insider trade's price as Streamlit's table prints it — "$330.19" — and
 * blank when the filing carries none: a grant has no price, and a dash in
 * every grant row reads as thirty missing figures.
 */
export function insiderPrice(value: Maybe, currency: string | null): string {
  return known(value) ? `${mark(currency)}${money(value, 2)}` : "";
}

/**
 * …and its signed notional, whole units: "$-474,813", "$+12,000". The sign
 * sits after the mark because that is Streamlit's `{sym}{:+,.0f}`, and the two
 * tables should read alike. Blank with no notional.
 */
export function insiderValue(value: Maybe, currency: string | null): string {
  return known(value) ? `${mark(currency)}${signed(value, 0)}` : "";
}

/**
 * Growth measured against the magnitude of the base. Null when there is no
 * usable one — a growth rate out of zero is not a large number, it is none.
 */
export function yoy(cur: Maybe, prev: Maybe): number | null {
  if (!known(cur) || !known(prev) || prev === 0) return null;
  return ((cur - prev) / Math.abs(prev)) * 100;
}

/**
 * Year-over-year growth for every bar of a results series whose first
 * `reported` values were filed and the rest are forecast.
 *
 * Streamlit's rule, bar for bar: a reported year is measured against the year
 * right before it — a gap stays a gap, so the year after a missing one has no
 * label — while the first forecast bar is measured against the last reported
 * year that *has* a value, and each later forecast against the one before it.
 * The forecast tail is what a reader checks "is consensus expecting growth"
 * against, so it has to anchor on the filing, not on a hole.
 */
export function barGrowth(
  values: (number | null)[],
  reported: number,
): (number | null)[] {
  let anchor: number | null = null;
  return values.map((value, index) => {
    if (index < reported) {
      const out = index > 0 ? yoy(value, values[index - 1]) : null;
      if (known(value)) anchor = value;
      return out;
    }
    const out = yoy(value, anchor);
    if (known(value)) anchor = value;
    return out;
  });
}

/** A growth figure as a bar label, blank when there is none to show. */
export function growthLabel(value: number | null): string {
  return value === null ? "" : `${value >= 0 ? "+" : ""}${value.toFixed(0)}%`;
}

export type Translate = (
  key: string,
  values?: Record<string, string | number>,
) => string;

/**
 * A series' legend: what it ended at and how fast it got there —
 * "Revenue · 391B latest · +8%/yr CAGR".
 *
 * The legend is the only place on a results chart with room for a rate, and a
 * reader comparing two companies wants the rate before the level. CAGR is left
 * out when the span crosses zero: a growth rate between a loss and a profit is
 * arithmetic, not information.
 */
export function legend(label: string, values: (number | null)[], t: Translate): string {
  const points = values.filter((value): value is number => value !== null);
  const last = points[points.length - 1];
  const first = points[0];
  if (last === undefined || first === undefined) return label;
  const parts = [t("ticker.legend_latest", { label, val: compact(last) })];
  if (points.length > 1 && first > 0 && last > 0) {
    const rate = ((last / first) ** (1 / (points.length - 1)) - 1) * 100;
    parts.push(
      t("ticker.legend_cagr", { pct: `${rate >= 0 ? "+" : ""}${rate.toFixed(0)}` }),
    );
  }
  return parts.join(" · ");
}

/**
 * The string for `key`, or `alternative` when the catalogs have no entry.
 *
 * `t` degrades to the key itself, which is right on screen for a hardcoded key
 * — visible and greppable — and wrong for keys the API names: a KPI tile whose
 * string nobody has written yet should read "Enterprise value" rather than
 * "ticker.kpi_ev".
 */
export function orElse(t: Translate, key: string, alternative: string): string {
  const value = t(key);
  return value === key ? alternative : value;
}

/**
 * The last non-null value of a series — the latest close, the latest reading.
 *
 * A trailing run of nulls is an indicator still warming up at the right edge,
 * not a price of nothing, so it is skipped rather than read.
 */
export function latest(values: (number | null)[] | undefined): number | null {
  if (!values) return null;
  for (let i = values.length - 1; i >= 0; i--) {
    const value = values[i];
    if (value !== null && value !== undefined) return value;
  }
  return null;
}

/** …and the first, for a change measured across the window on screen. */
export function earliest(values: (number | null)[] | undefined): number | null {
  for (const value of values ?? []) {
    if (value !== null && value !== undefined) return value;
  }
  return null;
}

/**
 * The day's move off the bars, for when there is no quote to read it from:
 * Streamlit's `(last - prev) / prev` over the last two closes. On an intraday
 * range the bar before the last is five minutes ago, not yesterday, so there
 * the previous close is the last bar of the previous session instead. A
 * fraction, as the quote's `pct` is; null when there is nothing to measure.
 */
export function barsDayPct(bars: Bars | null): number | null {
  if (!bars) return null;
  const close = bars.series.Close ?? [];
  let at = close.length - 1;
  while (at >= 0 && (close[at] === null || close[at] === undefined)) at--;
  if (at < 1) return null;
  const last = close[at] as number;
  const intraday = bars.interval !== "1d" && /[mh]$/.test(bars.interval);
  const today = (bars.dates[at] ?? "").slice(0, 10);
  for (let i = at - 1; i >= 0; i--) {
    const prev = close[i];
    if (prev === null || prev === undefined) continue;
    if (intraday && (bars.dates[i] ?? "").slice(0, 10) === today) continue;
    return prev ? last / prev - 1 : null;
  }
  return null;
}
