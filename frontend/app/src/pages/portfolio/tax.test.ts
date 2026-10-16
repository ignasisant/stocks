import { describe, expect, it } from "vitest";

import type { TaxSale } from "./api";
import { salesByPosition, salesByTicker } from "./Tax";

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

describe("salesByPosition", () => {
  it("folds each name's sales into one row with sums and date spans", () => {
    const rows = salesByPosition([
      { ...sale("SEZL", 300), buy_date: "2025-03-28", sell_date: "2026-06-10" },
      sale("ACMR", 100),
      { ...sale("SEZL", -50), buy_date: "2025-11-13", sell_date: "2026-05-07" },
    ]);
    expect(rows).toEqual([
      {
        ticker: "SEZL",
        sales: 2,
        first_buy: "2025-03-28",
        last_buy: "2025-11-13",
        first_sell: "2026-05-07",
        last_sell: "2026-06-10",
        quantity: 2,
        cost: 200,
        proceeds: 450,
        gain: 250,
      },
      {
        ticker: "ACMR",
        sales: 1,
        first_buy: "2025-01-02",
        last_buy: "2025-01-02",
        first_sell: "2025-06-02",
        last_sell: "2025-06-02",
        quantity: 1,
        cost: 100,
        proceeds: 200,
        gain: 100,
      },
    ]);
  });
});
