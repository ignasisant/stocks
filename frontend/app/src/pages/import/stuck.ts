/**
 * When the page stops offering the same drop zone and offers another way in.
 *
 * Accounts were seen uploading the same statement five and six times and
 * leaving with nothing booked (prod 2026-11-11): each try got its own honest
 * error and none of them said "this is not going to work, do this instead".
 */

import type { Outcome, Preview } from "./api";

/** Tries that ended with nothing to commit before the page says so. */
export const STUCK_AFTER = 3;

/**
 * Whether a reading left the reader with nothing worth committing: refused,
 * empty, or with more rows quarantined than accepted. A statement already in
 * the book is not one (its rows are importable, flagged duplicate), and
 * neither is a ledger that moved under the preview, which is asked again.
 */
export function missed(outcome: Outcome<Preview> | null): boolean {
  if (outcome === null) return false;
  if (!outcome.ok) return outcome.refusal.kind !== "changed";
  const read = outcome.value;
  if (read.kind === "positions" && (read.holdings ?? []).length > 0) return false;
  return read.importable.length === 0 || read.rejected.length > read.importable.length;
}
