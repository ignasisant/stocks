/**
 * When the one-time "how is TopStocks for you?" prompt may ask (`RatePrompt`).
 *
 * Somebody who came back, not a first look: the prompt waits for the
 * `VISIT_DAYS`th distinct day this browser opened the signed-in app. The
 * count is per device because the server only dates sign-ins, not visits —
 * but whether it was *asked* is the account's (`rate_prompt_done`), so the
 * phone does not ask what the laptop already did. The local stamp below is the
 * fallback for a PATCH that never landed: a failed write must not turn a
 * one-time question into one on every load.
 */

/** Days of use before the question: five returns, a working week. */
export const VISIT_DAYS = 5;

const VISITS = "rateVisitDays";
const ASKED = "rateAsked";

function localDay(now: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function readDays(store: Storage): string[] {
  try {
    const parsed: unknown = JSON.parse(store.getItem(VISITS) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((d) => typeof d === "string") : [];
  } catch {
    return [];
  }
}

/** Stamps today and says how many distinct days are known, up to `VISIT_DAYS`.
 *  Storage that throws counts nothing: a prompt that cannot count never asks. */
export function recordVisit(now = new Date(), storage?: Storage): number {
  try {
    const store = storage ?? window.localStorage;
    const today = localDay(now);
    const days = readDays(store);
    if (!days.includes(today)) {
      store.setItem(VISITS, JSON.stringify([...days, today].slice(-VISIT_DAYS)));
    }
    return Math.min(VISIT_DAYS, new Set([...days, today]).size);
  } catch {
    return 0;
  }
}

/** Whether this browser already asked. Storage that throws reads as "yes". */
export function asked(storage?: Storage): boolean {
  try {
    return (storage ?? window.localStorage).getItem(ASKED) === "1";
  } catch {
    return true;
  }
}

export function markAsked(storage?: Storage): void {
  try {
    (storage ?? window.localStorage).setItem(ASKED, "1");
  } catch {
    // `asked()` already reads a throwing store as "asked".
  }
}

/** The comment box's question: what to fix after a low score, what works after a high one. */
export function followUp(stars: number): "rate_low" | "rate_high" {
  return stars <= 3 ? "rate_low" : "rate_high";
}
