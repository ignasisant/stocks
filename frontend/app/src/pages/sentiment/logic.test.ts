/**
 * The page's derived readings — the ones that are wrong silently rather than
 * loudly.
 *
 * Nothing here is a component test. A quadrant read off the wrong sign, a
 * sector called "leading" because its month was missing rather than positive,
 * and a rates block whose unit changed under us all render perfectly and mean
 * something else. That is what this covers.
 */

import { describe, expect, it } from "vitest";

import {
  BANDS,
  bandSpan,
  fromMiddle,
  indexAt,
  quadrant,
  splitTilt,
  topSectors,
} from "./logic";
import type { TrendBlock, TrendRow } from "./types";

function row(over: Partial<TrendRow> & { key: string }): TrendRow {
  return {
    name: "",
    value: 1,
    changes: {},
    spark: [],
    state: null,
    percentile: null,
    percentile_then: null,
    welcome: 1,
    stale: false,
    weight: null,
    spy_weight: null,
    core: null,
    ...over,
  };
}

function block(over: Partial<TrendBlock> & { block: string }): TrendBlock {
  return { unit: "percent", rows: [], unavailable: null, ...over };
}

const rates = (yields?: number, slope?: number) =>
  block({
    block: "rates",
    unit: "basis_points",
    rows: [
      row({
        key: "DGS10",
        changes: yields === undefined ? {} : { quarter: yields },
      }),
      row({ key: "T10Y2Y", changes: slope === undefined ? {} : { quarter: slope } }),
    ],
  });

describe("quadrant", () => {
  it("names the four regimes off the sign pair", () => {
    expect(quadrant(rates(33, 12))?.key).toBe("bear_steepening");
    expect(quadrant(rates(33, -12))?.key).toBe("bear_flattening");
    expect(quadrant(rates(-33, 12))?.key).toBe("bull_steepening");
    expect(quadrant(rates(-33, -12))?.key).toBe("bull_flattening");
  });

  it("carries the two moves through untouched, in basis points", () => {
    expect(quadrant(rates(33, -12))).toEqual({
      key: "bear_flattening",
      yields: 33,
      slope: -12,
    });
  });

  // A level with no history is no reading: the API omits a horizon the series
  // is too short to span, which is exactly where `rate_quadrant` gives up.
  it("has no reading when either series is too short for the quarter", () => {
    expect(quadrant(rates(33, undefined))).toBeNull();
    expect(quadrant(rates(undefined, 12))).toBeNull();
    expect(quadrant(null)).toBeNull();
    expect(quadrant(block({ block: "rates", unit: "basis_points" }))).toBeNull();
  });

  // The changes would still be numbers if the block started quoting percent,
  // and they would mean something else.
  it("refuses a block that is not quoting basis points", () => {
    expect(quadrant(block({ ...rates(33, 12), unit: "percent" }))).toBeNull();
  });
});

describe("topSectors", () => {
  const rotation = (rows: TrendRow[]) => block({ block: "rotation", rows });

  it("splits the three largest holdings by their excess return", () => {
    const result = topSectors(
      rotation([
        row({ key: "XLK", name: "Technology", weight: 0.4, changes: { month: 0.02 } }),
        row({
          key: "XLV",
          name: "Healthcare",
          weight: 0.3,
          changes: { month: -0.01 },
        }),
        row({ key: "XLF", name: "Financials", weight: 0.2, changes: { month: 0.005 } }),
        // Fourth by weight, and beating everything: still not in the sentence,
        // which claims to be about the largest three.
        row({ key: "XLE", name: "Energy", weight: 0.1, changes: { month: 0.09 } }),
      ]),
    );
    expect(result.leading.map((r) => r.name)).toEqual(["Technology", "Financials"]);
    expect(result.lagging.map((r) => r.name)).toEqual(["Healthcare"]);
  });

  it("names a sector in neither list when it has no month to compare", () => {
    const result = topSectors(
      rotation([row({ key: "XLK", name: "Technology", weight: 0.4 })]),
    );
    expect(result.leading).toEqual([]);
    expect(result.lagging).toEqual([]);
  });

  // The book's top three are taken first and the ones with no sector fund are
  // dropped second. Filtering to the funded sectors first would promote
  // Energy — the fourth-largest holding — into a sentence about the largest
  // three, because the book's second-largest bucket has no ETF.
  it("picks the book's top three before dropping sectors with no fund", () => {
    const result = topSectors(
      rotation([
        row({ key: "XLK", name: "Technology", weight: 0.4, changes: { month: 0.02 } }),
        row({
          key: "XLF",
          name: "Financials",
          weight: 0.15,
          changes: { month: -0.01 },
        }),
        row({ key: "XLE", name: "Energy", weight: 0.1, changes: { month: 0.09 } }),
      ]),
      { Technology: 0.4, Unknown: 0.3, Financials: 0.15, Energy: 0.1 },
    );
    expect(result.leading.map((r) => r.name)).toEqual(["Technology"]);
    expect(result.lagging.map((r) => r.name)).toEqual(["Financials"]);
  });

  // A book nobody could price sends null weights, and a null weight is not a
  // zero one: neither belongs in a sentence about "your largest sectors".
  it("says nothing without a book", () => {
    const result = topSectors(
      rotation([row({ key: "XLK", name: "Technology", changes: { month: 0.02 } })]),
    );
    expect(result.leading).toEqual([]);
    expect(result.lagging).toEqual([]);
    expect(topSectors(null).leading).toEqual([]);
  });
});

describe("meter bands", () => {
  it("cover the whole scale, once", () => {
    const spans = BANDS.map((_, i) => bandSpan(i));
    expect(spans).toEqual([20, 20, 20, 20, 20]);
    expect(spans.reduce((a, b) => a + b, 0)).toBe(100);
  });
});

describe("splitTilt", () => {
  it("orders sectors by tilt and sets the non-sector buckets aside", () => {
    const { rows, unsectored } = splitTilt({
      Technology: 0.084,
      Financial: -0.072,
      Crypto: 0.01,
      Unknown: 0.011,
      Energy: -0.032,
    });
    expect(rows.map(([name]) => name)).toEqual(["Technology", "Energy", "Financial"]);
    expect(unsectored).toBeCloseTo(0.021);
  });

  it("says nothing when the whole book has a sector", () => {
    expect(splitTilt({ Technology: 0.1 }).unsectored).toBeNull();
  });
});

describe("fromMiddle", () => {
  it("grows right above 50 and left below", () => {
    expect(fromMiddle(70)).toEqual({ side: "appetite", width: 20 });
    expect(fromMiddle(31)).toEqual({ side: "tension", width: 19 });
    expect(fromMiddle(50)).toEqual({ side: "appetite", width: 0 });
  });

  it("clamps a score outside the scale", () => {
    expect(fromMiddle(130).width).toBe(50);
    expect(fromMiddle(-5).width).toBe(50);
  });
});

describe("indexAt", () => {
  it("maps a pointer to the nearest session", () => {
    expect(indexAt(0, 100, 11)).toBe(0);
    expect(indexAt(100, 100, 11)).toBe(10);
    expect(indexAt(52, 100, 11)).toBe(5);
    expect(indexAt(500, 100, 11)).toBe(10);
    expect(indexAt(5, 0, 11)).toBe(0);
  });
});
