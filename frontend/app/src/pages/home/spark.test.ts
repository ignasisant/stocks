/**
 * The glance chart's windows are cut from one fetched history, not refetched.
 *
 * The cut has to be the one `/portfolio/history` would have made — counted back
 * from the series' own last day, that day's start included — or the 1w chart
 * the reader picks is a day longer or shorter than the server's 1w everywhere
 * else in the app.
 */

import { describe, expect, it } from "vitest";

import { slice } from "./Spark";
import type { History } from "./types";

function history(dates: string[]): History {
  return {
    base: "EUR",
    window: "5y",
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
