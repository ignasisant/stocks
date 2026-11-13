import { describe, expect, it } from "vitest";

import { ageDays, heldPlaces, leaders, percentiles, sectorWeight, tint } from "./rank";
import type { CohortRow } from "./types";

const row = (
  ticker: string,
  score: number | null,
  metrics: Record<string, number | null> = {},
): CohortRow => ({ ticker, score, rank: null, metrics });

describe("percentiles", () => {
  const rows = [
    row("A", 0.9, { roic: 0.3, pe_ttm: 10 }),
    row("B", 0.5, { roic: 0.1, pe_ttm: 30 }),
    row("C", 0.1, { roic: 0.2, pe_ttm: null }),
  ];

  it("puts the biggest figure on top when bigger is better", () => {
    const out = percentiles(rows, "roic", false);
    expect(out.get("A")).toBe(1);
    expect(out.get("C")).toBe(0.5);
    expect(out.get("B")).toBe(0);
  });

  it("puts the smallest on top when lower is better", () => {
    const out = percentiles(rows, "pe_ttm", true);
    expect(out.get("A")).toBe(1);
    expect(out.get("B")).toBe(0);
  });

  it("gives a missing figure no standing, not the worst one", () => {
    expect(percentiles(rows, "pe_ttm", true).has("C")).toBe(false);
  });

  it("shares a place between ties", () => {
    const tied = [row("A", 1, { x: 1 }), row("B", 1, { x: 1 }), row("C", 1, { x: 0 })];
    const out = percentiles(tied, "x", false);
    expect(out.get("A")).toBe(0.75);
    expect(out.get("B")).toBe(0.75);
    expect(out.get("C")).toBe(0);
  });

  it("ranks nobody on a single figure", () => {
    expect(percentiles([row("A", 1, { x: 1 })], "x", false).size).toBe(0);
  });
});

describe("tint", () => {
  it("leaves the middle and the unknown alone", () => {
    expect(tint(undefined)).toBeUndefined();
    expect(tint(0.5)).toBeUndefined();
    expect(tint(0.52)).toBeUndefined();
  });

  it("inks the ends in the design system's up and down", () => {
    expect(tint(1)).toBe("color-mix(in srgb, var(--ag-up) 22%, transparent)");
    expect(tint(0)).toBe("color-mix(in srgb, var(--ag-down) 22%, transparent)");
  });
});

describe("heldPlaces", () => {
  const rows = [
    row("A", 0.9),
    row("B", 0.7),
    row("C", 0.5),
    row("D", 0.3),
    row("E", 0.1),
    row("F", null),
  ];

  it("ranks the reader's names by score and names who beats them", () => {
    const out = heldPlaces(
      rows,
      new Map([
        ["E", 0.04],
        ["B", 0.1],
      ]),
    );
    expect(out.map((one) => one.ticker)).toEqual(["B", "E"]);
    expect(out[0]).toMatchObject({ place: 2, of: 5, ahead: ["A"], weight: 0.1 });
    expect(out[1]).toMatchObject({ place: 5, ahead: ["A", "B", "C"], weight: 0.04 });
  });

  it("has nobody ahead of the leader", () => {
    expect(heldPlaces(rows, new Map([["A", null]]))[0]).toMatchObject({
      place: 1,
      ahead: [],
    });
  });

  it("keeps an unranked holding, placed last", () => {
    const out = heldPlaces(
      rows,
      new Map([
        ["F", 0.02],
        ["C", 0.01],
      ]),
    );
    expect(out.map((one) => one.place)).toEqual([3, null]);
  });

  it("ignores names outside the cohort", () => {
    expect(heldPlaces(rows, new Map([["ZZZ", 0.5]]))).toEqual([]);
  });
});

describe("leaders", () => {
  const rows = [
    row("A", 1, { roic: 0.3, pe_ttm: 20, x: null }),
    row("B", 1, { roic: 0.3, pe_ttm: 12, x: 1 }),
    row("C", 1, { roic: 0.1, pe_ttm: 15, x: null }),
  ];

  it("marks the best of the three, ties included", () => {
    const out = leaders(rows, ["A", "B", "C"], ["roic", "pe_ttm"], ["pe_ttm"]);
    expect([...out.get("roic")!]).toEqual(["A", "B"]);
    expect([...out.get("pe_ttm")!]).toEqual(["B"]);
  });

  it("marks nobody when only one has a figure", () => {
    expect(leaders(rows, ["A", "B", "C"], ["x"], []).has("x")).toBe(false);
  });
});

describe("ageDays", () => {
  const now = new Date("2026-11-13T09:30:00Z");

  it("counts calendar days from a date or a datetime", () => {
    expect(ageDays("2026-11-13", now)).toBe(0);
    expect(ageDays("2026-11-05T22:10:00+00:00", now)).toBe(8);
  });

  it("is null for a sector never scanned", () => {
    expect(ageDays(null, now)).toBeNull();
  });
});

describe("sectorWeight", () => {
  it("matches the sector whatever its case", () => {
    expect(sectorWeight({ Technology: 0.4 }, "technology")).toBe(0.4);
    expect(sectorWeight({ Technology: 0.4 }, "Energy")).toBeNull();
    expect(sectorWeight(null, "Energy")).toBeNull();
  });
});
