/** The phone layout follows the room `ag-main` has, not the window's width. */

import { afterEach, describe, expect, it, vi } from "vitest";

import { phoneNow } from "./ui";

const shell = (width: number) =>
  vi.stubGlobal("document", {
    querySelector: () => ({ getBoundingClientRect: () => ({ width }) }),
  });

afterEach(() => vi.unstubAllGlobals());

describe("phoneNow", () => {
  it("is false without a shell or a media query", () => {
    expect(phoneNow()).toBe(false);
  });

  it("falls back to the viewport when there is no shell", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    expect(phoneNow()).toBe(true);
  });

  it("reads the ag-main column, whatever the viewport says", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    shell(500); // the chat drawer is open on a wide window
    expect(phoneNow()).toBe(true);
    shell(900);
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    expect(phoneNow()).toBe(false);
  });
});
