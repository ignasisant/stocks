/**
 * A document either becomes the text a question takes with it or says why
 * it did not.
 *
 * Every failure ends on a locale key the composer renders, as a screenshot's
 * does. And what is sent is held to what the server takes: a paste longer
 * than one document's worth goes as its beginning, marked as cut, rather
 * than being refused once the question is already on its way.
 *
 * `fetch` stands in for `POST /chat/documents`, and a `FileReader` that
 * answers with the bytes for the browser's, which this runtime has none of.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../shell/api";
import {
  DocRefused,
  isPdf,
  MAX_DOC_CHARS,
  PASTE_FROM,
  pastedDoc,
  refused,
  textOf,
} from "./docs";

const answers = (
  status: number,
  body: object,
  headers: Record<string, string> = {},
) => {
  const fetched = vi.fn(async (_url: string, _init: RequestInit) =>
    Response.json(body, { status, headers }),
  );
  vi.stubGlobal("fetch", fetched);
  return fetched;
};

const report = (name = "results.pdf", bytes = "%PDF-1.4 words") =>
  new File([bytes], name, { type: "application/pdf" });

/** The device reads the file, or — `opens: false` — cannot. */
const device = (opens = true) =>
  vi.stubGlobal(
    "FileReader",
    class {
      result: string | null = null;
      error: Error | null = null;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      readAsDataURL(blob: Blob) {
        void blob.arrayBuffer().then((bytes) => {
          if (!opens) {
            this.error = new Error("NotReadableError");
            this.onerror?.();
            return;
          }
          const text = String.fromCharCode(...new Uint8Array(bytes));
          this.result = `data:application/pdf;base64,${btoa(text)}`;
          this.onload?.();
        });
      }
    },
  );

beforeEach(() => device());
afterEach(() => vi.unstubAllGlobals());

describe("isPdf", () => {
  it("goes by the type, or by the name where a picker gives none", () => {
    expect(isPdf(report())).toBe(true);
    expect(isPdf(new File(["x"], "Q3 Results.PDF"))).toBe(true);
    expect(isPdf(new File(["x"], "trades.csv", { type: "text/csv" }))).toBe(false);
    expect(isPdf(new File(["x"], "pdf"))).toBe(false);
  });
});

describe("refused", () => {
  it("keeps the server's own key, and how long to wait", () => {
    const wait = refused(new ApiError(429, "chat.rate_limited", undefined, 40));
    expect(wait.key).toBe("chat.rate_limited");
    expect(wait.slots).toEqual({ seconds: 40 });
    expect(refused(new ApiError(422, "chat.doc_no_text")).key).toBe("chat.doc_no_text");
  });

  it("never shows a sentence that is not a key", () => {
    expect(refused(new ApiError(422, "content must be base64")).key).toBe(
      "chat.doc_failed",
    );
    expect(refused(new TypeError("Failed to fetch")).key).toBe("chat.doc_failed");
  });
});

describe("textOf", () => {
  it("sends the file as base64 with its name and how it came in", async () => {
    const fetched = answers(200, {
      name: "results.pdf",
      text: "Revenue 4,210",
      pages: 12,
      read: 3,
      cut: true,
    });
    const found = await textOf(report(), "drop");
    expect(found).toEqual({
      name: "results.pdf",
      text: "Revenue 4,210",
      pages: 12,
      read: 3,
      cut: true,
    });
    const [url, init] = fetched.mock.calls[0]!;
    expect(url).toBe("/api/v1/chat/documents");
    expect(JSON.parse(String(init.body))).toEqual({
      filename: "results.pdf",
      content: btoa("%PDF-1.4 words"),
      via: "drop",
    });
  });

  it("says a file over the limit is too big without uploading it", async () => {
    const fetched = answers(200, {});
    const big = report();
    Object.defineProperty(big, "size", { value: 10 * 1024 * 1024 + 1 });
    await expect(textOf(big, "pick")).rejects.toMatchObject({
      key: "chat.doc_too_big",
    });
    expect(fetched).not.toHaveBeenCalled();
  });

  it("says so when the device itself cannot open the file", async () => {
    const fetched = answers(200, {});
    device(false);
    await expect(textOf(report(), "pick")).rejects.toMatchObject({
      key: "chat.unreadable",
    });
    expect(fetched).not.toHaveBeenCalled();
  });

  it("passes on why the server could not read it", async () => {
    answers(422, { detail: "chat.doc_no_text" });
    const failed = await textOf(report(), "pick").catch((failure) => failure);
    expect(failed).toBeInstanceOf(DocRefused);
    expect(failed.key).toBe("chat.doc_no_text");
  });

  it("does not pass an empty reading off as a document", async () => {
    answers(200, { name: "results.pdf", text: "  ", pages: 1, read: 1, cut: false });
    await expect(textOf(report(), "pick")).rejects.toMatchObject({
      key: "chat.doc_failed",
    });
  });
});

describe("pastedDoc", () => {
  it("is the words, tidied, under no name", () => {
    expect(pastedDoc("  First line   \r\n\r\n\r\n\r\nSecond  \n")).toEqual({
      name: "",
      text: "First line\n\nSecond",
      cut: false,
    });
  });

  it("sends the start of a paste longer than one document, and says so", () => {
    const doc = pastedDoc("word ".repeat(5000));
    expect(doc.cut).toBe(true);
    expect(doc.text.length).toBeLessThanOrEqual(MAX_DOC_CHARS);
    expect(doc.text.endsWith("\n[…]")).toBe(true);
    expect(doc.text.startsWith("word word")).toBe(true);
  });

  it("does not leave half a character at the cut", () => {
    // The emoji's first half would be the last unit kept.
    const doc = pastedDoc("a".repeat(MAX_DOC_CHARS - 5) + "😀".repeat(20));
    expect(doc.cut).toBe(true);
    // A lone half does not survive encoding; a whole text does.
    expect(() => encodeURIComponent(doc.text)).not.toThrow();
  });

  it("starts where a paste no longer leaves room for a question", () => {
    expect(PASTE_FROM).toBeGreaterThan(500);
    expect(PASTE_FROM).toBeLessThan(MAX_DOC_CHARS);
  });
});
