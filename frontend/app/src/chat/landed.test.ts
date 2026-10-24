/**
 * Which threads an answer landed on while the reader was elsewhere, and the
 * count the tab's title carries for them (`landed.ts`).
 */

import { describe, expect, it } from "vitest";

import { counted, landed } from "./landed";
import type { Conversation } from "./types";

function conv(id: string, messages: number, answering = false): Conversation {
  return {
    id,
    title: `Thread ${id}`,
    title_auto: true,
    created: "2026-10-24T09:00:00Z",
    updated: "2026-10-24T09:00:00Z",
    messages,
    active: false,
    answering,
  };
}

describe("an answer landing off-screen", () => {
  it("is said once, when the thread stops answering with more turns", () => {
    const watch = new Map<string, number>();
    expect(landed(watch, [conv("a", 2, true), conv("b", 4)], "b")).toEqual([]);
    expect(watch.get("a")).toBe(2);
    // Still writing: the baseline is the first count seen, not the latest.
    expect(landed(watch, [conv("a", 3, true), conv("b", 4)], "b")).toEqual([]);
    expect(watch.get("a")).toBe(2);
    expect(landed(watch, [conv("a", 4), conv("b", 4)], "b")).toEqual([
      { id: "a", title: "Thread a", ok: true },
    ]);
    expect(landed(watch, [conv("a", 4), conv("b", 4)], "b")).toEqual([]);
  });

  it("says a thread that ended with no new turns did not get its answer", () => {
    const watch = new Map<string, number>();
    landed(watch, [conv("a", 2, true)], null);
    expect(landed(watch, [conv("a", 2)], null)).toEqual([
      { id: "a", title: "Thread a", ok: false },
    ]);
  });

  it("leaves the thread on screen to its own stream", () => {
    const watch = new Map<string, number>();
    landed(watch, [conv("a", 2, true)], null);
    // The reader went back to it before it landed: nothing to announce.
    expect(landed(watch, [conv("a", 2, true)], "a")).toEqual([]);
    expect(watch.has("a")).toBe(false);
    expect(landed(watch, [conv("a", 4)], "a")).toEqual([]);
  });

  it("forgets a thread that left the list", () => {
    const watch = new Map<string, number>();
    landed(watch, [conv("a", 2, true)], null);
    expect(landed(watch, [], null)).toEqual([]);
    expect(watch.size).toBe(0);
  });

  it("never announces a thread it did not see answering", () => {
    expect(landed(new Map(), [conv("a", 6)], null)).toEqual([]);
  });
});

describe("the tab's title", () => {
  it("carries the count in front, once", () => {
    expect(counted("TopStocks", 1)).toBe("(1) TopStocks");
    expect(counted("(1) TopStocks", 3)).toBe("(3) TopStocks");
  });

  it("drops it at zero", () => {
    expect(counted("(2) TopStocks", 0)).toBe("TopStocks");
    expect(counted("TopStocks", 0)).toBe("TopStocks");
  });
});
