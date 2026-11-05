/**
 * The pieces every share is made of: a credited link, a line of text cut on
 * a word, and when the phone's own sheet goes first.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { absolute, clip, nativeFirst, sharedLink } from "./link";

const coarse = { matches: false };

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { origin: "https://topstocks.app" },
    matchMedia: () => coarse,
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  coarse.matches = false;
});

describe("a shared link", () => {
  it("is absolute on this origin and credited to a share of its kind", () => {
    expect(sharedLink("/ticker?ticker=NVDA", "ticker")).toBe(
      "https://topstocks.app/ticker?ticker=NVDA&src=share&medium=ticker",
    );
  });

  it("keeps what the path carried, encoded once", () => {
    expect(sharedLink("/ticker?ticker=%5EGSPC", "ticker")).toBe(
      "https://topstocks.app/ticker?ticker=%5EGSPC&src=share&medium=ticker",
    );
  });

  it("names no kind when it is given none", () => {
    expect(sharedLink("/?share=abc")).toBe(
      "https://topstocks.app/?share=abc&src=share",
    );
  });
});

describe("an invite link", () => {
  it("keeps its own source rather than a share's", () => {
    expect(absolute("/?src=inv-abcdefghjk")).toBe(
      "https://topstocks.app/?src=inv-abcdefghjk",
    );
  });
});

describe("the text", () => {
  it("is left alone when short and cut on a word when long", () => {
    expect(clip("  ¿Vendo   NVDA? ")).toBe("¿Vendo NVDA?");
    const cut = clip("palabra ".repeat(40));
    expect(cut.length).toBeLessThanOrEqual(100);
    expect(cut.endsWith("palabra…")).toBe(true);
  });
});

describe("the phone's own sheet", () => {
  it("goes first only on a touch screen that has one", () => {
    vi.stubGlobal("navigator", { share: () => Promise.resolve() });
    expect(nativeFirst()).toBe(false);
    coarse.matches = true;
    expect(nativeFirst()).toBe(true);
    vi.stubGlobal("navigator", {});
    expect(nativeFirst()).toBe(false);
  });
});
