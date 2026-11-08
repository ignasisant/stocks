import { describe, expect, it } from "vitest";
import { fitHeight } from "./fit";

describe("fitHeight", () => {
  it("takes a squarer shape as the plot narrows, and the desktop's past 480", () => {
    // A 350px phone: four fifths of the width, not the desktop's 300 and not
    // the half-height strip a scaled viewBox gave.
    expect(fitHeight(350, 300)).toBe(280);
    // Never under `min`, never over the desktop height.
    expect(fitHeight(240, 300)).toBe(240);
    expect(fitHeight(720, 300)).toBe(300);
    expect(fitHeight(720, 240)).toBe(240);
    expect(fitHeight(260, 400, 320)).toBe(320);
  });
});
