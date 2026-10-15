/**
 * A question a guest asked, carried across the sign-in round trip.
 *
 * The locked assistant (`Locked.tsx`) cannot answer, but the reader who
 * pressed "Ask the AI" on a page still meant the question — and losing it to
 * a Google redirect would make signing in feel like starting over. It is kept
 * in this tab's `sessionStorage`, which survives the round trip (same tab,
 * same origin), and the real composer takes it once and puts it in the field.
 *
 * Put in the field, never sent: the answer spends the account's daily
 * allowance, and that is the reader's press to make.
 */

const KEY = "chatDraft";

export function keepDraft(text: string, storage?: Storage | null): void {
  try {
    (storage ?? window.sessionStorage).setItem(KEY, text);
  } catch {
    // Private mode or storage off: the question is lost on the round trip,
    // which costs a retype and nothing else.
  }
}

/** The kept question, once: reading it clears it. */
export function takeDraft(storage?: Storage | null): string | null {
  try {
    const store = storage ?? window.sessionStorage;
    const text = store.getItem(KEY);
    if (text !== null) store.removeItem(KEY);
    return text || null;
  } catch {
    return null;
  }
}

/** Whether a question is waiting, without taking it. */
export function hasDraft(storage?: Storage | null): boolean {
  try {
    return Boolean((storage ?? window.sessionStorage).getItem(KEY));
  } catch {
    return false;
  }
}
