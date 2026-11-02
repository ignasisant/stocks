/**
 * A holdings report turned into buys, one per line the reader dated.
 *
 * The report says what is held and at best the average paid; the ledger needs
 * a day. Each line is written as one buy of the whole quantity at that price,
 * on the day the reader picked — from the sessions whose range held the price
 * (`/import/buy-dates`) or typed. A line left undated is left out, not
 * guessed: a buy on the wrong day is a wrong return.
 */

import type { Holding, Row } from "./api";

/** What the reader said about one line, keyed by its `row`. */
export type Dating = {
  /** The price as typed: "150,25" and "150.25" alike. */
  price: string;
  /** ISO day, or empty. */
  date: string;
  /** The line the buy-dates answer priced, which is what the buy is under. */
  symbol?: string;
  currency: string;
};

/** The oldest day a buy may carry: the ledger's own floor
 *  (`validate._MIN_DATE`), which refuses anything earlier as a mangled year. */
export const MIN_DAY = "1990-01-01";

/** Past this a price is a typo (a pasted total, a stray digit), not a share. */
export const MAX_PRICE = 1e9;

/** Today as the reader's calendar has it. `toISOString` is UTC, which in
 *  Madrid after midnight is still yesterday and would refuse today's buy. */
export function today(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** A typed price as a number, or null. A comma reads as the decimal point
 *  unless a point follows it ("1,805.50"); the earlier mark is thousands. */
export function priceOf(text: string): number | null {
  let clean = text.trim().replace(/\s/g, "");
  const comma = clean.lastIndexOf(",");
  const point = clean.lastIndexOf(".");
  if (comma >= 0 && point >= 0) {
    clean =
      comma > point
        ? clean.replaceAll(".", "").replace(",", ".")
        : clean.replaceAll(",", "");
  } else if (comma >= 0) {
    clean = clean.replace(",", ".");
  }
  if (!/^\d+(\.\d+)?$/.test(clean)) return null;
  const value = Number(clean);
  return value > 0 && value <= MAX_PRICE ? value : null;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const CODE = /^[A-Z]{3}$/;

/** What is wrong with a field, as its catalog key; null when nothing is (an
 *  empty field is not wrong yet, only not done). */
export type Problem =
  | "import.hold_bad_price"
  | "import.hold_bad_date"
  | "import.hold_future"
  | "import.hold_old"
  | "import.hold_bad_currency";

export function priceProblem(text: string): Problem | null {
  return text.trim() === "" || priceOf(text) !== null ? null : "import.hold_bad_price";
}

/** A day the calendar has (no 30 February), not after `now`, not before the
 *  ledger's floor. ISO strings compare as dates. */
export function dayProblem(text: string, now: string = today()): Problem | null {
  if (text === "") return null;
  if (!DAY.test(text)) return "import.hold_bad_date";
  const [y, m, d] = text.split("-").map(Number);
  const day = new Date(Date.UTC(y!, m! - 1, d!));
  if (
    day.getUTCFullYear() !== y ||
    day.getUTCMonth() !== m! - 1 ||
    day.getUTCDate() !== d
  )
    return "import.hold_bad_date";
  if (text > now) return "import.hold_future";
  if (text < MIN_DAY) return "import.hold_old";
  return null;
}

export function currencyProblem(text: string): Problem | null {
  const code = text.trim().toUpperCase();
  return code === "" || CODE.test(code) ? null : "import.hold_bad_currency";
}

/** The line's buy once it has a valid day, price and currency; else null. */
export function boughtAs(
  holding: Holding,
  dating: Dating | undefined,
  now: string = today(),
): Row | null {
  if (!dating) return null;
  const price = priceOf(dating.price);
  const currency = dating.currency.trim().toUpperCase();
  if (
    price === null ||
    dating.date === "" ||
    dayProblem(dating.date, now) !== null ||
    !CODE.test(currency)
  )
    return null;
  return {
    date: dating.date,
    ticker: dating.symbol || holding.ticker,
    action: "buy",
    quantity: holding.quantity,
    price,
    currency,
    fee: 0,
    note: "",
    issues: [],
    duplicate: false,
  };
}

/** The opening state: the report's own cost and currency, no day yet. */
export function undated(holding: Holding): Dating {
  return {
    price: holding.cost === null ? "" : String(Math.round(holding.cost * 1e4) / 1e4),
    date: "",
    currency: holding.currency,
  };
}
