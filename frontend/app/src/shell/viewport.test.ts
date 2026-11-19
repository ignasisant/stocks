import { describe, expect, it } from "vitest";
import { shortBy, STUCK_PX } from "./viewport";

const full = { inner: 852, vv: 852, top: 0, client: 852, fixed: 852 };

describe("shortBy", () => {
  it("is nothing for a window at its tallest, all of it on screen", () => {
    expect(shortBy(full, 852)).toBe(0);
  });

  it("reads a window left short of its tallest by a keyboard", () => {
    expect(shortBy({ inner: 516, vv: 516, top: 0, client: 516, fixed: 516 }, 852)).toBe(
      336,
    );
  });

  it("reads the fixed box short while the window says it is whole", () => {
    expect(shortBy({ ...full, fixed: 540 }, 852)).toBe(312);
  });

  it("reads a visual viewport still short or still panned", () => {
    expect(shortBy({ ...full, vv: 828 }, 852)).toBe(24);
    expect(shortBy({ ...full, vv: 800, top: 52 }, 852)).toBe(52);
  });

  it("leaves toolbar-sized differences alone", () => {
    expect(shortBy({ ...full, inner: 840, fixed: 840 }, 852)).toBeLessThanOrEqual(
      STUCK_PX,
    );
  });
});
