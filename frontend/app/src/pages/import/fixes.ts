/**
 * The reader's word on a ticker, laid over the preview.
 *
 * A statement the model read carries the names the model gave, and one of
 * them can be another company (`Preview.doubted`, or a reader who simply sees
 * it). The reader confirms the ticker or picks the line it really was, the
 * server checks that line against the fills (`POST /import/ticker`), and the
 * answer lives here: the preview is not asked again, because the same bytes
 * would be read to the same name. A commit sends the rows back, so the rows it
 * sends are these.
 *
 * The preview itself is never changed: the fixes are a list beside it, and
 * taking one back is dropping it from the list.
 */

import type { Preview, Row } from "./api";

/** `symbol` is the line the code's rows become; the code itself when the
 *  reader said the ticker was right as read. */
export type Fix = { code: string; currency: string; symbol: string };

const DOUBT = "validate.ticker_doubt";
// A code nobody recognised that the reader has now named is recognised.
const UNKNOWN = "validate.unknown_ticker";

/** Whether the row's ticker is one the prices do not back. */
export const inDoubt = (row: Row): boolean =>
  row.issues.some((issue) => issue.key === DOUBT);

const without = (row: Row, keys: string[]): Row["issues"] =>
  row.issues.filter((issue) => !keys.includes(issue.key));

function fixed(row: Row, fix: Fix): Row {
  if (row.ticker !== fix.code || row.currency !== fix.currency) return row;
  if (fix.symbol === fix.code) return { ...row, issues: without(row, [DOUBT]) };
  return {
    ...row,
    ticker: fix.symbol,
    issues: without(row, [DOUBT, UNKNOWN]),
    // Measured against the other company's quote.
    gain: null,
  };
}

/** The preview as the reader corrected it: what is shown and what is sent. */
export function corrected(preview: Preview, fixes: Fix[]): Preview {
  if (fixes.length === 0) return preview;
  const importable = fixes.reduce(
    (rows, fix) => rows.map((row) => fixed(row, fix)),
    preview.importable,
  );
  const held = new Set(importable.map((row) => row.ticker));
  const doubted = new Set(importable.filter(inDoubt).map((row) => row.ticker));
  return {
    ...preview,
    importable,
    unlisted: preview.unlisted?.filter((code) => held.has(code)),
    doubted: preview.doubted?.filter((code) => doubted.has(code)),
  };
}

/**
 * `fixes` with one more answer. A second answer about the same rows replaces
 * the first rather than chaining on it: AMT to MU and then MU to MTE.DE is AMT
 * to MTE.DE, and one that leads back to the code is no fix at all.
 */
export function answered(fixes: Fix[], fix: Fix): Fix[] {
  const prior = fixes.find(
    (old) =>
      old.currency === fix.currency &&
      (old.symbol === fix.code || old.code === fix.code),
  );
  const rest = fixes.filter((old) => old !== prior);
  const code = prior?.code ?? fix.code;
  const whole = { code, currency: fix.currency, symbol: fix.symbol };
  // Naming the code again undoes a change; said of an untouched code, it is
  // the reader confirming it.
  return prior && prior.symbol !== prior.code && fix.symbol === code
    ? rest
    : [...rest, whole];
}

/** The fixes that changed a ticker, which the page lists with their undo. */
export const changes = (fixes: Fix[]): Fix[] =>
  fixes.filter((fix) => fix.symbol !== fix.code);
