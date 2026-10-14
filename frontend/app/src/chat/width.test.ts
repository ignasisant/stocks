/**
 * The drag handle's arithmetic: inside the limits the panel's edge sits under
 * the pointer, past them it gives a little and no more, and the release always
 * lands on the limit.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { stretchAt, widthAt } from "./width";

beforeEach(() => vi.stubGlobal("window", { innerWidth: 2000 }));
afterEach(() => vi.unstubAllGlobals());

describe("dragging the chat's edge", () => {
  it("follows the pointer one to one between the limits", () => {
    expect(stretchAt(1400)).toBe(600);
    expect(widthAt(1400)).toBe(600);
  });

  it("gives past the minimum, with resistance, and releases at it", () => {
    const near = stretchAt(2000 - 300);
    const far = stretchAt(2000 - 0);
    expect(near).toBeLessThan(320);
    expect(near).toBeGreaterThan(300);
    expect(far).toBeLessThan(near);
    expect(far).toBeGreaterThan(320 - 96);
    expect(widthAt(2000)).toBe(320);
  });

  it("gives past the maximum, never by more than the give", () => {
    expect(stretchAt(2000 - 1600)).toBeGreaterThan(1500);
    expect(stretchAt(-10_000)).toBeLessThan(1500 + 96);
    expect(widthAt(-10_000)).toBe(1500);
  });
});
