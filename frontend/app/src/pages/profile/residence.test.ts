import { describe, expect, it } from "vitest";
import { residenceClash } from "./residence";

describe("residence against the profile", () => {
  it("flags Spain declared while the profile says US tax", () => {
    expect(residenceClash("ES", ["us_tax", "eur"])).toEqual({
      residence: "ES",
      constraint: "us_tax",
    });
  });
  it("is quiet when they agree, or on auto", () => {
    expect(residenceClash("ES", ["spain_tax"])).toBeNull();
    expect(residenceClash(null, ["us_tax"])).toBeNull();
    expect(residenceClash("FR", ["us_tax"])).toBeNull();
  });
});
