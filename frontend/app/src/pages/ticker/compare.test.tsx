/**
 * The comparison card: the subject leads, each index keeps the hue the risk
 * tab draws it in, and a name the server could not draw is named, not lost.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { CompareChart, lineColors } from "./Compare";
import { series, seriesOther } from "../../shell/theme";
import type { Comparison } from "./types";

// The palette reads CSS tokens off the document; with none, each falls back.
vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
vi.stubGlobal("document", { documentElement: {}, querySelector: () => null });

describe("lineColors", () => {
  const hues = series();

  it("keeps the risk tab's hue for each index, whatever the order", () => {
    const colors = lineColors(["EEM", "SPY"]);
    expect(colors.SPY).toBe(hues[0]);
    expect(colors.EEM).toBe(hues[1]);
  });

  it("hands the rest a slot no index claims, in the order they were added", () => {
    const colors = lineColors(["SPY", "MDB", "XLK"]);
    expect(colors.MDB).toBe(hues[2]);
    expect(colors.XLK).toBe(hues[4]);
    expect(new Set(Object.values(colors)).size).toBe(3);
  });

  it("leaves the others alone when one line is dropped", () => {
    const before = lineColors(["SPY", "MDB", "XLK"]);
    const after = lineColors(["SPY", "XLK"], before);
    expect(after.XLK).toBe(before.XLK);
  });

  it("folds a line past the palette into the muted hue, never a repeat", () => {
    const colors = lineColors(["A", "B", "C", "D", "E", "F"]);
    expect(new Set(Object.values(colors).slice(0, 5)).size).toBe(5);
    expect(colors.F).toBe(seriesOther());
  });
});

const data: Comparison = {
  ticker: "ESTC",
  range: "1y",
  base: "EUR",
  dates: ["2026-01-05", "2026-01-06", "2026-01-07"],
  lines: [
    { ticker: "ESTC", name: "Elastic", role: "subject", points: [0, 0.1, 0.2] },
    { ticker: "SPY", name: "", role: "index", points: [0, 0.01, 0.02] },
  ],
  offered: [],
  missing: ["ODD.XX"],
};

const render = (body: Comparison) =>
  renderToStaticMarkup(
    <CompareChart
      data={body}
      colors={lineColors(["SPY"])}
      label={(line) => line.ticker}
      formatDate={(iso) => iso}
    />,
  );

describe("CompareChart", () => {
  it("names what it could not draw", () => {
    const html = render(data);
    expect(html).toContain("ticker.compare_missing");
  });

  it("says so when the window has no history to rebase", () => {
    const html = render({ ...data, dates: ["2026-01-05"], missing: [] });
    expect(html).toContain("ticker.history_empty");
    expect(html).not.toContain("<svg");
  });
});
