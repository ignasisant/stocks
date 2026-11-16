import { describe, expect, it } from "vitest";

import { figure, peerBars, worthAxis, worthRows } from "./worthmath";
import type { Analysts, Comparables, Dcf } from "./types";

const comps: Comparables = {
  tickers: ["S", "A", "B", "C"],
  labels: ["P/E (TTM)", "ROIC", "Market cap"],
  keys: ["pe_ttm", "roic", "market_cap"],
  lower_better: [true, false, false],
  rows: { S: ["30.0x", "40.0%", "1.20T"], A: [], B: [], C: [] },
  medals: {},
  peer_median: ["20.0x", "25.0%", ""],
  peer_range: ["", "", ""],
  outliers: {},
};

describe("figure", () => {
  it("reads the units the API bakes in", () => {
    expect(figure("14.2x")).toBe(14.2);
    expect(figure("-3.1%")).toBe(-3.1);
    expect(figure("1.20T")).toBe(1.2e12);
    expect(figure("n/a")).toBeNull();
    expect(figure("")).toBeNull();
  });
});

describe("peerBars", () => {
  it("reads each banded row against the rivals' median, the right way round", () => {
    const bars = peerBars(comps);
    expect(bars.map((b) => b.key)).toEqual(["pe_ttm", "roic"]);
    expect(bars[0]?.better).toBe(false); // dearer than the rivals
    expect(bars[1]?.better).toBe(true); // earns more than the rivals
  });

  it("leaves out a loss's multiple and an older server's rows", () => {
    const loss = { ...comps, rows: { ...comps.rows, S: ["-4.0x", "40.0%", "1T"] } };
    expect(peerBars(loss).map((b) => b.key)).toEqual(["roic"]);
    expect(peerBars({ ...comps, keys: undefined })).toEqual([]);
    expect(peerBars(null)).toEqual([]);
  });
});

describe("worthRows", () => {
  const dcf = { reason: null, value: 64, price: 100, currency: "USD" } as Dcf;
  const analysts = {
    covered: true,
    price: 100,
    currency: "USD",
    targets: { low: 80, median: 170, high: 220 },
  } as Analysts;

  it("puts each method as a distance from the price, skipping what has no figure", () => {
    const rows = worthRows(dcf, analysts, comps);
    expect(rows.map((r) => r.id)).toEqual(["dcf", "analysts", "peers"]);
    expect(rows[0]?.at).toBeCloseTo(-0.36);
    expect(rows[1]?.low).toBeCloseTo(-0.2);
    expect(rows[1]?.high).toBeCloseTo(1.2);
    expect(rows[2]?.at).toBeCloseTo(20 / 30 - 1);
    expect(worthRows(null, null, null)).toEqual([]);
    expect(worthRows({ ...dcf, reason: "negative_fcf" }, null, null)).toEqual([]);
  });

  it("keeps the price inside the axis", () => {
    const axis = worthAxis(worthRows(dcf, null, null));
    expect(axis.lo).toBeLessThan(-0.36);
    expect(axis.hi).toBeGreaterThan(0);
  });
});
