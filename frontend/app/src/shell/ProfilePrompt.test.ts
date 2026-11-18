/**
 * The profile nudge's day stamp: once a day, per account on this device, and
 * a store that throws reads as "already asked".
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { markSeen, seen, seenKey } from "./ProfilePrompt";

function memoryStore(): Storage {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (i) => [...items.keys()][i] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, value),
  };
}

let store: Storage;
beforeEach(() => {
  store = memoryStore();
  vi.stubGlobal("window", { localStorage: store });
});
afterEach(() => vi.unstubAllGlobals());

describe("the profile nudge's day", () => {
  it("asks again the day after it was stamped", () => {
    markSeen("ana@example.test", "2026-11-16");
    expect(seen("ana@example.test", "2026-11-16")).toBe(true);
    expect(seen("ana@example.test", "2026-11-17")).toBe(false);
  });

  it("is one account's: the next one to sign in on this device is asked", () => {
    markSeen("ana@example.test", "2026-11-17");
    expect(seen("bo@example.test", "2026-11-17")).toBe(false);
  });

  it("keeps the address out of the browser's storage", () => {
    markSeen("ana@example.test", "2026-11-17");
    const key = store.key(0) ?? "";
    expect(key).toBe(seenKey("ana@example.test"));
    expect(key).not.toContain("ana");
    expect(key).not.toContain("example");
  });

  it("reads a store that throws as already asked", () => {
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new Error("blocked");
      },
    });
    expect(seen("ana@example.test", "2026-11-17")).toBe(true);
    expect(() => markSeen("ana@example.test")).not.toThrow();
  });
});
