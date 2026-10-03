import { describe, expect, it } from "vitest";

import type { TaxSale } from "./api";
import { salesByTicker } from "./Tax";

const sale = (ticker: string, gain: number): TaxSale => ({
  ticker,
  buy_date: "2025-01-02",
  sell_date: "2025-06-02",
  quantity: 1,
  cost: 100,
  proceeds: 100 + gain,
  gain,
  matched: "fifo",
  term: null,
});

describe("salesByTicker", () => {
  it("adds each name's sales up, the largest result either way first", () => {
    const names = salesByTicker([
      sale("AAPL", 300),
      sale("TSLA", -900),
      sale("AAPL", 200),
      sale("MSFT", 50),
    ]);
    expect(names).toEqual([
      { ticker: "TSLA", count: 1, gain: -900 },
      { ticker: "AAPL", count: 2, gain: 500 },
      { ticker: "MSFT", count: 1, gain: 50 },
    ]);
  });
});
