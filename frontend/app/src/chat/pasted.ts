/**
 * A statement pasted into the composer, as the file the paperclip would send.
 *
 * Three things paste as a statement: a file copied in Finder or Explorer (the
 * clipboard carries the file itself), rows copied out of a spreadsheet or a
 * CSV opened as text, and a PDF or XLSX as base64 — the Import page's paste
 * box takes the same three (`pages/import/paste`). Everything else stays text
 * for the question.
 *
 * Only a kind some parser reads is taken. A screenshot is not a statement:
 * it is a picture to ask about, and `pastedShot` is its own way in. The clip
 * and a drop on the conversation hand over files rather than a clipboard,
 * and `sorted` tells the two apart there.
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

/**
 * The picture on the clipboard, or null when the paste is anything else.
 *
 * Only a paste that is a picture and nothing but: cells copied out of Excel
 * or a paragraph out of Word arrive as text *and* a rendering of it, and the
 * words are what was meant.
 */
export function pastedShot(clip: Clipboard): File | null {
  if (clip.getData("text/plain").trim()) return null;
  return Array.from(clip.files).find((file) => file.type.startsWith("image/")) ?? null;
}

/**
 * Files picked with the clip or dropped on the conversation, told apart: the
 * pictures are for the question, the first of the rest is a statement to
 * import. Where nothing can see (`pictures` false) a picture is a file like
 * any other, and is refused as one that is not a statement.
 */
export function sorted(
  files: ArrayLike<File>,
  pictures: boolean,
): { shots: File[]; statement: File | null } {
  const all = Array.from(files);
  const shots = pictures ? all.filter((file) => file.type.startsWith("image/")) : [];
  return { shots, statement: all.find((file) => !shots.includes(file)) ?? null };
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
