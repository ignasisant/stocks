import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { takeDraft } from "../chat/draft";
import { fillAssistant } from "./assistant";

beforeEach(() => {
  const store = new Map<string, string>();
  vi.stubGlobal("window", {
    sessionStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("fillAssistant", () => {
  it("keeps the stem for the composer, once, and sends nothing", () => {
    fillAssistant("  I hold: 10 NVDA at 120  ");
    expect(takeDraft()).toBe("I hold: 10 NVDA at 120");
    expect(takeDraft()).toBeNull();
  });

  it("ignores an empty stem", () => {
    fillAssistant("   ");
    expect(takeDraft()).toBeNull();
  });
});
