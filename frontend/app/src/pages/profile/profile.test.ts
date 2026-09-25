import { describe, expect, it } from "vitest";

import { initials } from "./Profile";
import { progress } from "./TourCard";
import { parsed } from "./Watchlist";

describe("the identity card's initials", () => {
  it("come off the display name when the provider gave one", () => {
    expect(initials("jane.doe@example.com", "Ada Lovelace")).toBe("AL");
  });

  it("fall back to the address", () => {
    expect(initials("jane.doe@example.com", null)).toBe("JD");
    expect(initials("jane.doe@example.com", "  ")).toBe("JD");
  });

  it("never draw an empty avatar", () => {
    expect(initials("", null)).toBe("?");
  });
});

describe("the tour card's setup progress", () => {
  it("counts what is on, of everything", () => {
    expect(progress({ login: true, import: true, ai: false, telegram: false })).toEqual(
      [2, 4],
    );
  });

  it("draws nothing for nothing to count", () => {
    expect(progress({})).toBeNull();
  });
});

describe("a watchlist number field's edit", () => {
  it("sends what changed", () => {
    expect(parsed("12.5", 10)).toBe(12.5);
  });

  it("reads a comma decimal the way half the readers type it", () => {
    expect(parsed("12,5", null)).toBe(12.5);
  });

  it("clears with an empty box, which is 0 on the wire", () => {
    expect(parsed("", 10)).toBe(0);
  });

  it("sends nothing for no change, and nothing it cannot read", () => {
    expect(parsed("10", 10)).toBeUndefined();
    expect(parsed("", null)).toBeUndefined();
    expect(parsed("abc", 10)).toBeUndefined();
    expect(parsed("-3", 10)).toBeUndefined();
  });
});
