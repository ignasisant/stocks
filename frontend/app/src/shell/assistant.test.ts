import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { takeDraft } from "../chat/draft";
import { drawerWidth, fillAssistant, roomBeside } from "./assistant";

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

/** A window `width` wide whose nav rail takes `nav` and whose `--chat-w` reads `chatW`. */
function screen(width: number, nav: number, chatW = ""): void {
  vi.stubGlobal("window", { innerWidth: width });
  vi.stubGlobal("document", {
    documentElement: {},
    querySelector: () => (nav ? { offsetWidth: nav } : null),
  });
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => chatW }));
}

describe("roomBeside", () => {
  it("says yes while the page keeps its minimum beside the drawer", () => {
    screen(1440, 240);
    expect(roomBeside(420)).toBe(true);
  });

  it("says no once the drawer would squeeze the page below it", () => {
    screen(1180, 240);
    expect(roomBeside(420)).toBe(false);
  });

  it("counts a drawer dragged wide as the 60% it is capped at", () => {
    screen(1440, 240);
    expect(roomBeside(2000)).toBe(false);
    screen(2400, 240);
    expect(roomBeside(2000)).toBe(true);
  });
});

describe("drawerWidth", () => {
  it("falls back to the default before anything set a width", () => {
    screen(1440, 240, "");
    expect(drawerWidth()).toBe(420);
  });

  it("reads pixels and viewport units alike, never wider than the window", () => {
    screen(1000, 0, " 520px");
    expect(drawerWidth()).toBe(520);
    screen(1000, 0, "40vw");
    expect(drawerWidth()).toBe(400);
    screen(390, 0, "520px");
    expect(drawerWidth()).toBe(390);
  });
});
