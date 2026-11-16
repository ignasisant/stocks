import { describe, expect, it } from "vitest";
import { indexRows, largest } from "./riskLogic";
import { atBroker, spanMove } from "./Positions";
import { yieldOnCost } from "./Dividends";
import { worthSelling, type HarvestData } from "./Harvest";
import type { Position, Risk } from "./api";

describe("indexRows", () => {
  it("prices each index on the book's own money at the last common day", () => {
    const rows = indexRows({
      dates: ["a", "b"],
      invested: [1000, 2000],
      portfolio: [0.1, 0.2],
      basket: [],
      benchmarks: { SPY: [0.05, 0.1], QQQ: [0.0, 0.3] },
    } as unknown as NonNullable<Risk["curves"]>);
    expect(rows.map((r) => r.bench)).toEqual(["QQQ", "SPY"]);
    expect(rows[1]).toMatchObject({ gain: 200, versus: 200 });
    expect(rows[0]!.versus).toBeCloseTo(-200);
  });
});

describe("largest", () => {
  it("keeps the heaviest names and their correlations only", () => {
    const data = {
      weights: { A: 0.5, B: 0.3, C: 0.2 },
      names: { A: {}, B: {}, C: {} },
      correlation: { A: { A: 1, B: 0.2, C: 0.1 }, B: { A: 0.2, B: 1, C: 0 }, C: {} },
    } as unknown as Risk;
    const top = largest(data, 2);
    expect(Object.keys(top.weights)).toEqual(["A", "B"]);
    expect(Object.keys(top.correlation["A"]!)).toEqual(["A", "B"]);
    expect(top.correlation["C"]).toBeUndefined();
  });
});

describe("spanMove and atBroker", () => {
  const row = {
    value: 1200,
    day: 10,
    day_pct: 0.01,
    week_pct: 0.2,
    custody: [{ broker: "ibkr" }],
  } as unknown as Position;
  it("backs the amount out of the value", () => {
    expect(spanMove(row, "day")).toEqual({ pct: 0.01, amount: 10 });
    expect(spanMove(row, "week").amount).toBeCloseTo(200);
    expect(spanMove(row, "month")).toEqual({ pct: null, amount: null });
  });
  it("filters by custodian", () => {
    expect(atBroker([row], "ibkr")).toHaveLength(1);
    expect(atBroker([row], "revolut")).toHaveLength(0);
    expect(atBroker([row], "")).toHaveLength(1);
  });
});

describe("yieldOnCost", () => {
  it("is the forward income over the cost, null when unknown", () => {
    expect(yieldOnCost({ ticker: "A", gross_base: 50 }, { A: 1000 })).toBeCloseTo(0.05);
    expect(yieldOnCost({ ticker: "B", gross_base: 50 }, {})).toBeNull();
  });
});

describe("worthSelling", () => {
  it("orders by saving", () => {
    const c = (ticker: string, saving: number) => ({
      ticker,
      shares: 1,
      loss: -1,
      saving,
      blocked: 0,
      free: false,
    });
    const data = { candidates: [c("A", 1), c("B", 5)] } as unknown as HarvestData;
    expect(worthSelling(data).map((x) => x.ticker)).toEqual(["B", "A"]);
  });
});
