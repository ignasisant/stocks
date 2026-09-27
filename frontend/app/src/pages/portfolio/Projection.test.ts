import { describe, expect, it } from "vitest";
import { parseAmount, projectionSeries } from "./Projection";

describe("parseAmount", () => {
  it("reads both decimal conventions and thousands dots", () => {
    expect(parseAmount("150000")).toBe(150000);
    expect(parseAmount("150.000")).toBe(150000);
    expect(parseAmount("1.500,5")).toBe(1500.5);
    expect(parseAmount("1,500.5")).toBe(1500.5);
    expect(parseAmount("3900,75")).toBe(3900.75);
    expect(parseAmount("200 000 €")).toBe(200000);
  });

  it("refuses what is not an amount", () => {
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("abc")).toBeNull();
    expect(parseAmount("-5")).toBeNull();
  });
});

describe("projectionSeries", () => {
  const labels = {
    actual: "a",
    invested: "i",
    p90: "p90",
    p50: "p50",
    p10: "p10",
    contributed: "c",
  };
  const data = {
    base: "EUR",
    years: 1,
    start_value: 150,
    sleeves: [],
    correlation: null,
    crypto_weight: 0,
    real: false,
    inflation: 0.02,
    target: null,
    target_probability: null,
    monthly: 0,
    monthly_suggested: 0,
    dates: ["2026-09-27", "2026-10-27", "2026-11-27"],
    p10: [150, 140, 130],
    p25: [150, 145, 140],
    p50: [150, 152, 154],
    p75: [150, 158, 165],
    p90: [150, 165, 180],
    contributed: [150, 150, 150],
    history_dates: ["2026-07-31", "2026-08-31"],
    history_value: [100, 120],
    history_invested: [90, 100],
  };

  it("runs the past into today and the fan out of it, on one axis", () => {
    const lines = projectionSeries(data, labels);
    const byLabel = Object.fromEntries(lines.map((l) => [l.label, l.points]));
    expect(byLabel["a"]).toEqual([100, 120, 150, null, null]);
    expect(byLabel["i"]).toEqual([90, 100, null, null, null]);
    expect(byLabel["p50"]).toEqual([null, null, 150, 152, 154]);
    lines.forEach((l) => expect(l.points).toHaveLength(5));
  });

  it("notes each point as a return on the money in by then", () => {
    const pct = (f: number) => f.toFixed(2);
    const lines = projectionSeries(data, labels, pct);
    const note = (label: string, index: number, value: number) =>
      lines.find((l) => l.label === label)!.tipNote!(index, value);
    expect(note("a", 1, 120)).toBe("0.20"); // 120 on 100 put in
    expect(note("a", 2, 150)).toBeNull(); // today: no "put in" on this axis
    expect(note("p90", 4, 180)).toBe("0.20"); // 180 on 150 contributed
  });

  it("draws only the fan when there is no past", () => {
    const lines = projectionSeries(
      { ...data, history_dates: [], history_value: [], history_invested: [] },
      labels,
    );
    expect(lines.map((l) => l.label)).toEqual(["p90", "p50", "p10", "c"]);
  });
});
