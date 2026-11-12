/**
 * A pasted screenshot either becomes words or says why it did not.
 *
 * Every way it can fail ends on a locale key the composer renders: the
 * browser could not decode it, it would not fit, the server's reader was
 * down, the account's budget was spent. None of them may reach the reader as
 * an exception's message, and none may pass as a reading — an empty one would
 * be sent beside the question as if the picture had said nothing.
 *
 * `fetch` stands in for `POST /chat/screenshots`.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../shell/api";
import { ShotFailed, type Shot } from "../shell/screenshot";
import { setShelf, type Kept, type Shelf } from "../shell/keep";
import { get, invalidate, withMemo } from "../shell/api";
import { noteShot } from "./api";
import {
  forgetPictures,
  keepPicture,
  pictureNow,
  pictureOf,
  refused,
  ShotRefused,
  wordsOf,
} from "./shots";

const shot: Shot = { base64: "/9j/4AAQ", url: "blob:shot", kb: 12 };

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

afterEach(() => vi.unstubAllGlobals());

describe("refused", () => {
  it("says a picture the browser could not shrink is too big", () => {
    expect(refused(new ShotFailed("feedback.shot_big")).key).toBe("chat.shot_too_big");
  });

  it("says a picture the browser could not open is unreadable", () => {
    expect(refused(new ShotFailed("feedback.shot_failed")).key).toBe(
      "chat.shot_unreadable",
    );
  });

  it("keeps the server's own key, and how long to wait", () => {
    const wait = refused(new ApiError(429, "chat.rate_limited", undefined, 40));
    expect(wait.key).toBe("chat.rate_limited");
    expect(wait.slots).toEqual({ seconds: 40 });
    const down = refused(new ApiError(503, "chat.shot_unavailable"));
    expect(down.key).toBe("chat.shot_unavailable");
    expect(down.slots).toEqual({});
  });

  it("never shows a sentence that is not a key", () => {
    expect(refused(new ApiError(422, "image must be base64")).key).toBe(
      "chat.shot_failed",
    );
    expect(refused(new TypeError("Failed to fetch")).key).toBe("chat.shot_failed");
  });

  it("leaves a refusal it already made as it is", () => {
    const made = new ShotRefused("chat.shot_too_big");
    expect(refused(made)).toBe(made);
  });
});

describe("wordsOf", () => {
  it("sends the JPEG and the language, and hands back what was read", async () => {
    const fetched = answers(200, { text: "AAPL | 3 | 190.50" });
    await expect(wordsOf(shot, "es")).resolves.toBe("AAPL | 3 | 190.50");
    const [url, init] = fetched.mock.calls[0]!;
    expect(url).toBe("/api/v1/chat/screenshots");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      image: "/9j/4AAQ",
      lang: "es",
      via: "paste",
    });
  });

  it("says which door the picture came in by", async () => {
    const fetched = answers(200, { text: "AAPL | 3 | 190.50" });
    await wordsOf(shot, "es", "drop");
    expect(JSON.parse(String(fetched.mock.calls[0]![1].body)).via).toBe("drop");
  });

  it("refuses a reading with nothing in it", async () => {
    answers(200, { text: "  \n" });
    await expect(wordsOf(shot, "en")).rejects.toMatchObject({
      key: "chat.shot_failed",
    });
  });

  it("refuses with the server's key, and its wait", async () => {
    answers(429, { detail: "chat.shot_day_limit" }, { "Retry-After": "3600" });
    await expect(wordsOf(shot, "en")).rejects.toMatchObject({
      key: "chat.shot_day_limit",
      slots: { seconds: 3600 },
    });
  });
});

describe("the picture of a sent question", () => {
  const jpeg = "data:image/jpeg;base64,/9j/4AAQ";
  const kept = new Map<string, Kept>();
  let meta: { owner: string; build: string } | undefined;
  const shelf: Shelf = {
    read: async (url) => kept.get(url),
    write: async (entry) => {
      kept.set(entry.url, entry);
    },
    meta: async () => meta,
    reset: async (next) => {
      kept.clear();
      meta = next;
    },
    trim: async () => undefined,
  };
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

  afterEach(() => {
    forgetPictures();
    kept.clear();
    meta = undefined;
    invalidate();
    setShelf(null);
  });

  it("is found again by what was read in it", () => {
    keepPicture("AAPL | 3 | 190.50", jpeg);
    expect(pictureNow("AAPL | 3 | 190.50")).toBe(jpeg);
    expect(pictureNow("MSFT | 1 | 410.00")).toBeUndefined();
  });

  it("is the same picture however the reading is spaced", () => {
    keepPicture("AAPL | 3\n190.50\n", jpeg);
    expect(pictureNow("AAPL | 3 190.50")).toBe(jpeg);
  });

  it("is not kept unless it is a picture", () => {
    keepPicture("AAPL", "javascript:alert(1)");
    expect(pictureNow("AAPL")).toBeUndefined();
  });

  it("holds the last dozen in memory, not every one of a long visit", () => {
    for (let i = 0; i < 14; i++) keepPicture(`reading ${i}`, jpeg);
    expect(pictureNow("reading 0")).toBeUndefined();
    expect(pictureNow("reading 1")).toBeUndefined();
    expect(pictureNow("reading 2")).toBe(jpeg);
    expect(pictureNow("reading 13")).toBe(jpeg);
  });

  it("comes back from the device's shelf on a later visit", async () => {
    setShelf(shelf);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ kind: "session", email: "a@x" })),
    );
    await withMemo(() => get("/me"));
    await flush();
    keepPicture("AAPL | 3 | 190.50", jpeg);
    await flush();
    forgetPictures();

    expect(pictureNow("AAPL | 3 | 190.50")).toBeUndefined();
    await expect(pictureOf("AAPL | 3 | 190.50")).resolves.toBe(jpeg);
    await expect(pictureOf("never sent")).resolves.toBeUndefined();
  });

  it("shows nothing for a shelf entry that is not a picture", async () => {
    setShelf(shelf);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ kind: "session", email: "a@x" })),
    );
    await withMemo(() => get("/me"));
    await flush();
    keepPicture("AAPL", jpeg);
    await flush();
    forgetPictures();
    for (const entry of kept.values()) entry.body = { not: "a picture" };
    await expect(pictureOf("AAPL")).resolves.toBeUndefined();
  });
});

describe("noteShot", () => {
  it("says what the composer did, and nothing a picture said", () => {
    const fetched = answers(204, {});
    noteShot("refused", { why: "chat.shot_too_many", sent: false });
    const [url, init] = fetched.mock.calls[0]!;
    expect(url).toBe("/api/v1/chat/screenshots/events");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      what: "refused",
      why: "chat.shot_too_many",
      sent: false,
    });
  });

  it("is nobody's problem when it does not arrive", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    expect(() => noteShot("opened")).not.toThrow();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        throw new Error("no network stack");
      }),
    );
    expect(() => noteShot("removed", { read: true })).not.toThrow();
    // The rejection above was caught, not left for the page to report.
    await Promise.resolve();
  });
});
