import { describe, expect, it } from "vitest";
import { measure, parseSpan } from "./returns";
import type { ReviewReturns } from "./types";

const data: ReviewReturns = {
  base: "EUR",
  as_of: "2026-10-16",
  names: [
    { ticker: "ESTC", returns: { "1y": 0.3, "2y": null }, sector_etf: "XLK" },
    { ticker: "SAN.MC", returns: { "1y": 0.05 }, sector_etf: null },
  ],
  benchmarks: [
    { ticker: "SPY", returns: { "1y": 0.1, "2y": 0.4 }, sector_etf: null },
    { ticker: "XLK", returns: { "1y": 0.2 }, sector_etf: null },
  ],
  missing: [],
  pending: 0,
};

describe("measure", () => {
  it("gives the name's return and its gaps to the index and its sector", () => {
    const cells = measure(data, "1y", false)("estc");
    expect(cells?.own).toBeCloseTo(0.3);
    expect(cells?.index).toBeCloseTo(0.2);
    expect(cells?.sector).toBeCloseTo(0.1);
    expect(cells?.etf).toBe("XLK");
  });

  it("has no gap where the name has no return that far back", () => {
    const cells = measure(data, "2y", false)("ESTC");
    expect(cells).toEqual({ own: null, index: null, sector: null, etf: "XLK" });
  });

  it("has no sector gap for a name with no sector ETF", () => {
    expect(measure(data, "1y", false)("SAN.MC")?.sector).toBeNull();
  });

  it("tells asking apart from not measured", () => {
    expect(measure(null, "1y", true)("ESTC")).toBeUndefined();
    expect(measure(null, "1y", false)("ESTC")).toBeNull();
    expect(measure(data, "1y", false)("NOPE")).toBeNull();
  });
});

describe("parseSpan", () => {
  it("reads a known window and falls back to a year", () => {
    expect(parseSpan("6m")).toBe("6m");
    expect(parseSpan("5y")).toBe("1y");
    expect(parseSpan(null)).toBe("1y");
  });
});
