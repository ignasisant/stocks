/** Pure helpers for the Bank page: the consent clock and the cash total. */

import type { BankConnection } from "./types";

/** PSD2 consents last at most this many days. */
const CONSENT_DAYS = 90;
/** "Renew" is offered this many days before the consent ends. */
export const RENEW_WINDOW = 14;

const DAY_MS = 86_400_000;

/** Whole days left on a consent, or null when the date will not parse.
    Never negative: an ended consent has 0 left and `expired` says the rest. */
export function daysLeft(validUntil: string, now: Date = new Date()): number | null {
  const until = Date.parse(validUntil);
  if (Number.isNaN(until)) return null;
  return Math.max(0, Math.ceil((until - now.getTime()) / DAY_MS));
}

/** Share of the consent already used, 0-100, for the meter. */
export function usedPercent(left: number): number {
  const used = CONSENT_DAYS - Math.min(CONSENT_DAYS, left);
  return Math.round((used / CONSENT_DAYS) * 100);
}

/** Whether the reader should be offered "Renew" now. */
export function renewable(connection: BankConnection, now: Date = new Date()): boolean {
  if (connection.expired) return true;
  const left = daysLeft(connection.valid_until, now);
  return left !== null && left <= RENEW_WINDOW;
}

/** Cash held at the connected banks, one total per currency (never a sum
    across currencies: the page has no rate to convert them with). Accounts
    never read have no balance and are not counted as zero. */
export function cashTotals(
  connections: BankConnection[],
): { currency: string; amount: number }[] {
  const sums = new Map<string, number>();
  for (const connection of connections) {
    for (const account of connection.accounts) {
      if (account.balance === null) continue;
      const currency = account.balance_currency || account.currency || "EUR";
      sums.set(currency, (sums.get(currency) ?? 0) + account.balance);
    }
  }
  return [...sums].map(([currency, amount]) => ({ currency, amount }));
}
