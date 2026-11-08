import { describe, expect, it } from "vitest";
import { ticks } from "./ticks";

describe("ticks", () => {
  it("lands on round steps inside the span", () => {
    expect(ticks(11_843, 12_261, 5)).toEqual([11_900, 12_000, 12_100, 12_200]);
    expect(ticks(-0.12, 0.31, 5)).toEqual([-0.1, 0, 0.1, 0.2, 0.3]);
  });

  it("takes the 2.5 rung when 2 is too fine and 5 too coarse", () => {
    expect(ticks(0, 9, 4)).toEqual([0, 2.5, 5, 7.5]);
  });

  it("never prints float drift or a negative zero", () => {
    expect(ticks(0.1, 0.7, 6)).toEqual([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]);
    expect(Object.is(ticks(-1, 1, 2)[1], 0)).toBe(true);
  });

  it("answers a flat span with its value and a broken one with nothing", () => {
    expect(ticks(5, 5)).toEqual([5]);
    expect(ticks(Number.NaN, 1)).toEqual([]);
  });
});
