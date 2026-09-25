/**
 * Turning API numbers into cells, with one rule running through all of it: a
 * value that could not be computed comes back as `null`, and the caller prints
 * `home.na`. Nothing here ever substitutes a zero for a missing figure — that
 * is the whole reason the API sends null in the first place.
 *
 * Money and percentages go through `Intl`, keyed on the account's language, so
 * a Spanish reader gets `1.234,5 %` without this file owning a second table of
 * separators.
 */

export type Translate = (
  key: string,
  slots?: Record<string, string | number>,
) => string;

/** `:material/bolt:` icon tokens and `**bold**` markers, as Streamlit stores them. */
const MARKUP = /:material\/[a-z0-9_]+:|\*\*/g;

/**
 * A catalog string with its Streamlit markup taken off.
 *
 * Several headings are stored as `":material/event: **Earnings**"` because the
 * Python side renders them through `st.markdown`. Re-keying them would fork the
 * catalog in two, so the markers come off here instead — the icon font the rail
 * uses is not loaded for page content, and a literal `**` on screen is worse
 * than no emphasis at all.
 */
export function plain(label: string): string {
  return label.replace(MARKUP, "").trim();
}

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function money(
  value: number | null | undefined,
  currency: string,
  lang: string,
  opts?: { digits?: number; signed?: boolean },
): string | null {
  if (!finite(value)) return null;
  const digits = opts?.digits ?? 0;
  const options: Intl.NumberFormatOptions = {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: opts?.signed ? "always" : "auto",
  };
  try {
    return new Intl.NumberFormat(lang, options).format(value);
  } catch {
    // A ledger row can carry a currency Intl does not know (a broker's own
    // code). The figure is still worth printing — the code just trails it.
    return `${decimal(value, lang, digits) ?? ""} ${currency}`.trim();
  }
}

export function percent(
  value: number | null | undefined,
  lang: string,
  opts?: { digits?: number; signed?: boolean },
): string | null {
  if (!finite(value)) return null;
  const digits = opts?.digits ?? 2;
  return new Intl.NumberFormat(lang, {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: opts?.signed ? "always" : "auto",
  }).format(value);
}

export function decimal(
  value: number | null | undefined,
  lang: string,
  digits = 2,
  opts?: { signed?: boolean },
): string | null {
  if (!finite(value)) return null;
  return new Intl.NumberFormat(lang, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: opts?.signed ? "always" : "auto",
  }).format(value);
}

/**
 * An ISO `YYYY-MM-DD` as a local calendar date.
 *
 * Built field by field rather than handed to `new Date(iso)`, which reads a
 * bare date as UTC and slides it a day west of Greenwich — the API's dates are
 * calendar days, not instants.
 */
function parseDay(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return null;
  const [year, month, day] = [match[1], match[2], match[3]].map(Number);
  if (year === undefined || month === undefined || day === undefined) return null;
  const date = new Date(year, month - 1, day);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The local calendar day as `YYYY-MM-DD` — the key the API's dates use. */
export function dayKey(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/**
 * "2 Sep" — day plus the month name from the catalog.
 *
 * The month comes from `home.mon_*` rather than `Intl`, which is what the
 * Streamlit card does: the two front ends print the same twelve words.
 */
export function monthDay(iso: string | null | undefined, t: Translate): string | null {
  const date = parseDay(iso);
  if (!date) return null;
  return `${date.getDate()} ${t(`home.mon_${date.getMonth() + 1}`)}`;
}

export function shortDate(iso: string, lang: string): string {
  const date = parseDay(iso);
  if (!date) return iso;
  return new Intl.DateTimeFormat(lang, { day: "2-digit", month: "short" }).format(date);
}

/** Monday of the week `date` falls in, as a new date. */
export function mondayOf(date: Date): Date {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  // getDay() is Sunday-first; the grid is Monday-first.
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  return monday;
}

export function addDays(date: Date, days: number): Date {
  const moved = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  moved.setDate(moved.getDate() + days);
  return moved;
}
