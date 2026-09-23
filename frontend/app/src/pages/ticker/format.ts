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

/** The same, rounded the way a money column reads: one decimal on a suffix. */
export function amount(value: Maybe, currency: string | null): string {
  if (!known(value)) return DASH;
  const size = Math.abs(value);
  const [scaled, unit] =
    size >= 1e12
      ? [value / 1e12, "T"]
      : size >= 1e9
        ? [value / 1e9, "B"]
        : size >= 1e6
          ? [value / 1e6, "M"]
          : [value, ""];
  return `${scaled.toFixed(unit ? 1 : 0)}${unit} ${currency ?? ""}`.trim();
}

/**
 * Growth measured against the magnitude of the base. Null when there is no
 * usable one — a growth rate out of zero is not a large number, it is none.
 */
export function yoy(cur: Maybe, prev: Maybe): number | null {
  if (!known(cur) || !known(prev) || prev === 0) return null;
  return ((cur - prev) / Math.abs(prev)) * 100;
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
