import { describe, expect, it } from "vitest";

import { fits, formatMetric } from "./metrics";
import type { CohortRow, Size } from "./types";

const row = (ticker: string, size: Size | null, growth = false): CohortRow => ({
  ticker,
  score: null,
  rank: null,
  metrics: {},
  size,
  growth,
});

describe("fits", () => {
  const rows = [
    row("AAPL", "large"),
    row("SIMO", "mid", true),
    row("AXTI", "small", true),
    row("8035.T", null),
  ];
  const kept = (sizes: Size[], growthOnly = false) =>
    rows.filter((one) => fits(one, sizes, growthOnly)).map((one) => one.ticker);

  it("keeps every row, unknown size included, when no size is picked", () => {
    expect(kept([])).toEqual(["AAPL", "SIMO", "AXTI", "8035.T"]);
  });

  it("keeps only the sizes picked, and an unknown size is never small", () => {
    expect(kept(["small"])).toEqual(["AXTI"]);
    expect(kept(["mid", "small"])).toEqual(["SIMO", "AXTI"]);
  });

  it("narrows to the growth names on top of the sizes", () => {
    expect(kept([], true)).toEqual(["SIMO", "AXTI"]);
    expect(kept(["small"], true)).toEqual(["AXTI"]);
    expect(kept(["large"], true)).toEqual([]);
  });
});

describe("formatMetric money", () => {
  it("keeps a pence line's code instead of a pound sign", () => {
    expect(formatMetric("price", 473.2, "n/d", "GBp")).toBe("GBp 473.20");
    expect(formatMetric("price", 4.73, "n/d", "GBP")).toBe("£4.73");
  });
});
