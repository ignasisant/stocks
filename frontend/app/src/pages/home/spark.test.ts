/**
 * The glance chart's windows are cut from one fetched history, not refetched.
 *
 * The cut has to be the one `/portfolio/history` would have made — counted back
 * from the series' own last day, that day's start included — or the 1w chart
 * the reader picks is a day longer or shorter than the server's 1w everywhere
 * else in the app.
 */

import { describe, expect, it } from "vitest";

import { benchLine, offered, slice } from "./Spark";
import type { History } from "./types";

function history(dates: string[]): History {
  return {
    base: "EUR",
    window: "all",
    points: dates.map((date) => ({
      date,
      injected: 100,
      value: 110,
      pnl_pct: 0.1,
      twr: null,
    })),
    missing: [],
  };
}

describe("slice", () => {
  it("counts back from the last point, the boundary day included", () => {
    const days = ["2026-09-24", "2026-09-25", "2026-09-28", "2026-10-02"];
    expect(slice(history(days), "1w").map((point) => point.date)).toEqual([
      "2026-09-25",
      "2026-09-28",
      "2026-10-02",
    ]);
  });

  it("anchors on the series' end, not today", () => {
    const days = ["2025-01-01", "2025-01-20", "2025-02-01"];
    expect(slice(history(days), "1m").map((point) => point.date)).toEqual([
      "2025-01-20",
      "2025-02-01",
    ]);
  });

  it("crosses a month and a year boundary", () => {
    const days = ["2025-12-30", "2025-12-31", "2026-01-06"];
    expect(slice(history(days), "1w").map((point) => point.date)).toEqual([
      "2025-12-30",
      "2025-12-31",
      "2026-01-06",
    ]);
  });

  it("is empty for an empty history", () => {
    expect(slice(history([]), "1y")).toEqual([]);
  });
});

describe("benchLine", () => {
  it("is the server's race, sliced as it came", () => {
    expect(benchLine([{ inIndex: 120 }, { inIndex: 132 }])).toEqual([120, 132]);
  });

  it("draws nothing when a day is missing it", () => {
    expect(benchLine([{ inIndex: 120 }, { inIndex: null }])).toBeNull();
    expect(benchLine([{ inIndex: 120 }])).toBeNull();
  });
});

describe("offered", () => {
  it("keeps only the windows shorter than the book, and always the whole of it", () => {
    expect(offered(400)).toEqual(["1w", "1m", "6m", "1y", "all"]);
    expect(offered(365)).toEqual(["1w", "1m", "6m", "all"]);
    expect(offered(3)).toEqual(["all"]);
    expect(offered(4000)).toEqual(["1w", "1m", "6m", "1y", "2y", "all"]);
  });

  it("slices nothing off for the whole book", () => {
    const dates = ["2020-01-02", "2024-06-03", "2026-11-11"];
    expect(slice(history(dates), "all").map((point) => point.date)).toEqual(dates);
  });
});
