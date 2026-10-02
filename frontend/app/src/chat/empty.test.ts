import { describe, expect, it } from "vitest";

import { heaviest } from "./Empty";

describe("heaviest", () => {
  it("names the heaviest priced position at half its weight", () => {
    expect(
      heaviest([
        { ticker: "MSFT", shares: 3, weight: 0.12 },
        { ticker: "NVDA", shares: 5, weight: 0.31 },
        { ticker: "SAN.MC", shares: 100, weight: 0.08 },
      ]),
    ).toEqual({ top: "NVDA", n: 16 });
  });

  it("skips unpriced and closed rows, so an unlisted ISIN is never named", () => {
    expect(
      heaviest([
        { ticker: "IE00B4L5Y983", shares: 10, weight: null },
        { ticker: "TSLA", shares: 0, weight: 0.5 },
        { ticker: "ASML.AS", shares: 1, weight: 0.01 },
      ]),
    ).toEqual({ top: "ASML.AS", n: 1 });
  });

  it("falls back to a held ticker at 5% when nothing is priced", () => {
    expect(heaviest([{ ticker: "VWCE.DE", shares: 2, weight: null }])).toEqual({
      top: "VWCE.DE",
      n: 5,
    });
  });
});
