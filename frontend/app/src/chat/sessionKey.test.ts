/**
 * A key held for the tab is a key on every screen that counts one — and on a
 * screen already drawn, the moment it is typed: the drawer where it is typed
 * sits beside Home's start card, and no request goes out to refresh it.
 *
 * No DOM here: `window` is a bare event target with a storage on it, which is
 * all the module touches.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { dropSessionKey, holdSessionKey, withSessionKey } from "./sessionKey";

beforeEach(() => {
  const kept = new Map<string, string>();
  const tab = new EventTarget() as EventTarget & { sessionStorage: unknown };
  tab.sessionStorage = {
    getItem: (slot: string) => kept.get(slot) ?? null,
    setItem: (slot: string, value: string) => void kept.set(slot, value),
    removeItem: (slot: string) => void kept.delete(slot),
  };
  vi.stubGlobal("window", tab);
});

afterEach(() => vi.unstubAllGlobals());

describe("a key held for the tab", () => {
  it("counts as a key only where the server knows none", () => {
    expect(withSessionKey({ ai: false, login: true }, true)).toEqual({
      ai: true,
      login: true,
    });
    const stored = { ai: true };
    expect(withSessionKey(stored, false)).toBe(stored);
    expect(withSessionKey({ ai: false }, false)).toEqual({ ai: false });
  });

  it("tells the screens already drawn when it is typed and when it is dropped", () => {
    let told = 0;
    window.addEventListener("ag:session-key", () => (told += 1));
    holdSessionKey({ provider: "groq", key: "k" });
    expect(told).toBe(1);
    dropSessionKey();
    expect(told).toBe(2);
  });
});
