/** Money and percentages for the view, in the reader's locale. */

export function money(value: number | null, currency: string, locale: string): string {
  if (value === null || !Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      maximumFractionDigits: Math.abs(value) >= 1000 ? 0 : 2,
    }).format(value);
  } catch {
    // A code Intl does not know (a crypto base): the figure, then the code.
    return `${value.toFixed(2)} ${currency}`;
  }
}

/** A fraction as a percentage; `signed` for a move, plain for a share. */
export function percent(value: number | null, locale: string, signed = true): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
    signDisplay: signed ? "exceptZero" : "auto",
  }).format(value);
}

export function shortDay(iso: string | null, locale: string): string {
  if (!iso) return "";
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}
