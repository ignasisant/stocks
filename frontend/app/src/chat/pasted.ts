/**
 * A statement pasted into the composer, as the file the paperclip would send.
 *
 * Three things paste as a statement: a file copied in Finder or Explorer (the
 * clipboard carries the file itself), rows copied out of a spreadsheet or a
 * CSV opened as text, and a PDF or XLSX as base64 — the Import page's paste
 * box takes the same three (`pages/import/paste`). Everything else stays text
 * for the question.
 *
 * Only a kind some parser reads is taken. A screenshot pasted out of habit is
 * not a statement, and sending it would spend a model call to be told so.
 *
 * Text is held to a table, not to "has commas": a question pasted from
 * somewhere else ("Hola, tengo AAPL, MSFT, ¿qué opinas?") must still land in
 * the field. A statement is several columns wide on every line; a spreadsheet
 * copies as tabs, which prose almost never has, so two lines are enough there
 * and a comma or semicolon table needs three.
 */

import { nameOf } from "../pages/import/api";
import { pastedFile } from "../pages/import/paste";

/** The part of `DataTransfer` read here, so tests need no browser clipboard. */
export type Clipboard = {
  files: ArrayLike<File>;
  getData: (format: string) => string;
};

/** Separators past which a line is a row: four columns. */
const COLUMNS = 3;

const kindOf = (name: string) =>
  name.includes(".") ? (name.split(".").pop() ?? "").toLowerCase() : "";

export function tabular(text: string): boolean {
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  if (!/\d/.test(lines.slice(1).join(""))) return false;
  for (const [sep, least] of [
    ["\t", 2],
    [";", 3],
    [",", 3],
  ] as const) {
    if (lines.length < least) continue;
    const [head = 0, ...rest] = lines.map((line) => line.split(sep).length - 1);
    if (head < COLUMNS) continue;
    // A blank trailing cell or a quoted comma moves a line's count, so most
    // lines agreeing with the header is enough.
    const agree = 1 + rest.filter((count) => count === head).length;
    if (agree >= Math.max(least, lines.length * 0.8)) return true;
  }
  return false;
}

/** The statement on the clipboard, or null when the paste is just words. */
export function pastedStatement(
  clip: Clipboard,
  kinds: readonly string[],
): File | null {
  const copied = clip.files[0];
  if (copied) return kinds.includes(kindOf(nameOf(copied, [...kinds]))) ? copied : null;
  const text = clip.getData("text/plain").trim();
  if (!text) return null;
  const asFile = pastedFile(text, kinds);
  if ("wrong" in asFile) return null;
  // `pastedFile` calls any text a CSV; here a CSV has to look like one.
  if (asFile.filename === "pasted.csv" && !tabular(text)) return null;
  if (!kinds.includes(kindOf(asFile.filename))) return null;
  return new File([asFile.blob], asFile.filename, { type: asFile.blob.type });
}
