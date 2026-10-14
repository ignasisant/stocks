import { describe, expect, it } from "vitest";
import { keyStep } from "./useKeyWalk";

describe("keyStep", () => {
  it("steps one point, ten with shift, and stops at the edges", () => {
    expect(keyStep("ArrowLeft", false, 5, 20)).toBe(4);
    expect(keyStep("ArrowRight", true, 5, 20)).toBe(15);
    expect(keyStep("ArrowRight", true, 15, 20)).toBe(20);
    expect(keyStep("ArrowLeft", true, 3, 20)).toBe(0);
  });

  it("jumps to the ends and puts the readout away on Escape", () => {
    expect(keyStep("Home", false, 7, 20)).toBe(0);
    expect(keyStep("End", false, 7, 20)).toBe(20);
    expect(keyStep("Escape", false, 7, 20)).toBe("clear");
  });

  it("leaves every other key to the page", () => {
    expect(keyStep("Tab", false, 7, 20)).toBeNull();
    expect(keyStep("ArrowUp", false, 7, 20)).toBeNull();
  });
});
