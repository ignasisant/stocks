/**
 * The throw that dismisses a sheet, and the stretch past its rest position.
 *
 * A sheet that needs a full drag to close feels stuck; one that closes on any
 * twitch closes under a reader who was only scrolling. The projection is the
 * middle: a flick goes, a slow short drag springs back.
 */

import { describe, expect, it } from "vitest";

import { flung, rubberBand } from "./useSheet";

describe("flung", () => {
  it("dismisses a quick flick from a short drag", () => {
    expect(flung(40, 1.2, 400)).toBe(true);
  });

  it("springs a slow short drag back", () => {
    expect(flung(40, 0.05, 400)).toBe(false);
  });

  it("dismisses a slow drag past half the sheet", () => {
    expect(flung(220, 0, 400)).toBe(true);
  });

  it("keeps a sheet pulled back towards rest, however fast", () => {
    expect(flung(220, -2, 400)).toBe(false);
    expect(flung(-30, 3, 400)).toBe(false);
  });
});

describe("rubberBand", () => {
  it("follows less and less of the finger, and never past the sheet", () => {
    const near = rubberBand(-20, 400);
    const far = rubberBand(-400, 400);
    expect(near).toBeLessThan(0);
    expect(Math.abs(near)).toBeLessThan(20);
    expect(Math.abs(far)).toBeLessThan(400);
    expect(Math.abs(far) - Math.abs(rubberBand(-200, 400))).toBeLessThan(
      Math.abs(rubberBand(-200, 400)),
    );
  });
});
