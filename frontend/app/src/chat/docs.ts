/**
 * A document set beside a question: a PDF, or words pasted in one piece.
 *
 * The second thing a reader hands the chat that is not a sentence (`shots.ts`
 * is the first): a company's results, a broker's note, a fund's fact sheet,
 * an article copied whole. It becomes text before the question goes — a PDF
 * on the server, by a program and not a model (`POST /chat/documents`); a
 * paste already is — and that text travels with the question (`runInput`'s
 * `documents`), on the thread from then on.
 *
 * Only the start of a long one is sent, and the composer says so before the
 * question goes: a turn's budget is the free chain's, and a hundred pages do
 * not fit in it.
 *
 * A PDF is also what a broker's statement comes as, and the same clip takes
 * both. Which one a file is, is the reader's to say: the composer asks.
 */

import { ApiError } from "../shell/api";
import { asBase64, readDocument } from "./api";
import type { Way } from "./shots";
import type { Doc } from "./types";

/** Per question — the server's `document.MAX_DOCS`. */
export const MAX_DOCS = 2;
/** Per document — the server's `document.MAX_CHARS`. */
export const MAX_DOC_CHARS = 12_000;
/** The server's `document.MAX_BYTES`, so a file over it is told before the upload. */
const MAX_BYTES = 10 * 1024 * 1024;
/**
 * Where pasted words stop being a question and become a document. Half of
 * what a message may hold: past it a paste leaves no room to ask anything.
 */
export const PASTE_FROM = 2000;

const CUT = "\n[…]";

/** A refusal with a locale key on it — never a sentence. */
export class DocRefused extends Error {
  constructor(
    readonly key: string,
    readonly slots: Record<string, number> = {},
  ) {
    super(key);
  }
}

/** What went wrong, as the key that says so and how to get past it. */
export function refused(failure: unknown): DocRefused {
  if (failure instanceof DocRefused) return failure;
  if (failure instanceof ApiError && failure.detail.startsWith("chat.")) {
    return new DocRefused(
      failure.detail,
      failure.retryAfter === undefined ? {} : { seconds: failure.retryAfter },
    );
  }
  return new DocRefused("chat.doc_failed");
}

/** By its type, or its name where a phone's picker gives no type. */
export const isPdf = (file: File): boolean =>
  file.type === "application/pdf" || /\.pdf$/i.test(file.name);

/** The PDF as the text the question takes with it. */
export async function textOf(
  file: File,
  via: Way,
): Promise<Doc & { pages: number; read: number }> {
  if (file.size > MAX_BYTES) throw new DocRefused("chat.doc_too_big");
  let content: string;
  try {
    content = await asBase64(file);
  } catch {
    // A file the device itself cannot open: one still in Drive, one shared
    // out of a chat app. Nothing was sent.
    throw new DocRefused("chat.unreadable");
  }
  try {
    const found = await readDocument(file.name, content, via);
    if (!found.text.trim()) throw new DocRefused("chat.doc_failed");
    return found;
  } catch (failure) {
    throw refused(failure);
  }
}

/**
 * Pasted words as a document, held to one document's length the way the
 * server holds a PDF's (`document.clip`): trailing spaces and runs of blank
 * lines gone, then the start of it.
 */
export function pastedDoc(words: string): Doc {
  const text = words
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  if (text.length <= MAX_DOC_CHARS) return { name: "", text, cut: false };
  const start = text
    .slice(0, MAX_DOC_CHARS - CUT.length)
    // Half of an emoji left at the cut is a character the server refuses.
    .replace(/[\uD800-\uDBFF]$/, "")
    .trimEnd();
  return { name: "", text: start + CUT, cut: true };
}
