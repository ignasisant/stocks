/**
 * What a pasted statement is, which is not always text.
 *
 * The paste box exists for a reader whose browser will not hand over a file at
 * all — a managed device with file dialogs switched off, hardened privacy
 * settings — and that reader's statement is as often a PDF or an XLSX as a CSV.
 * Neither has a text form, so the way in for those is base64
 * (`base64 -i statement.pdf | pbcopy`), which the caption on screen already
 * tells them to use.
 *
 * Recognised by decoding it and reading the magic bytes, never by trusting a
 * label: the filename is what picks the branch inside a parser (Revolut PDF vs
 * CSV, ClickTrade xlsx vs csv), so handing a parser a format it does not read
 * would fail deep inside it instead of here, where the page can name the
 * problem. Mirrors `_pasted_file` in `web/app_pages/import_transactions.py`.
 */

/** Enough of a blob that a short CSV of pure letters cannot be mistaken for one. */
const B64_MIN = 64;

const B64 = /^[A-Za-z0-9+/=]+$/;

/** First bytes, and the format they mean. */
const MAGIC: [number[], string][] = [
  [[0x25, 0x50, 0x44, 0x46], "pdf"], // %PDF
  [[0x50, 0x4b, 0x03, 0x04], "xlsx"], // PK\x03\x04
];

export type Pasted =
  /** Ready to stage, under the name its parser will read. */
  | { filename: string; blob: Blob }
  /** A format this platform has no parser for — the extension it would need. */
  | { wrong: string };

function decoded(compact: string): Uint8Array | null {
  try {
    const binary = atob(compact);
    return Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    return null; // not base64 after all: it is text, and text is a CSV
  }
}

const starts = (bytes: Uint8Array, magic: number[]) =>
  magic.every((byte, at) => bytes[at] === byte);

/**
 * The file a paste amounts to, given what this platform can parse.
 *
 * A CSV pastes as itself. Anything that decodes to a PDF or an XLSX is named
 * for what it actually is — and refused here when this platform reads neither.
 */
export function pastedFile(text: string, types: readonly string[]): Pasted {
  const compact = text.replace(/\s+/g, "");
  if (compact.length >= B64_MIN && B64.test(compact)) {
    const bytes = decoded(compact);
    for (const [magic, kind] of MAGIC) {
      if (bytes && starts(bytes, magic)) {
        if (!types.includes(kind)) return { wrong: kind };
        return {
          filename: `pasted.${kind}`,
          blob: new Blob([bytes as BlobPart], { type: "application/octet-stream" }),
        };
      }
    }
  }
  return {
    // Same name the Streamlit page gives it, and the extension matters: the
    // parsers read it to decide how to read the bytes.
    filename: "pasted.csv",
    blob: new Blob([text], { type: "text/csv" }),
  };
}
