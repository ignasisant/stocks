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
import { chart } from "../../shell/theme";
import type { Comparison } from "./types";

// The palette reads CSS tokens off the document; with none, each falls back.
vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
vi.stubGlobal("document", { documentElement: {}, querySelector: () => null });

const palette = chart();

describe("lineColors", () => {
  it("keeps the risk tab's hue for each index, whatever the order", () => {
    const colors = lineColors(["EEM", "SPY"], palette);
    expect(colors.SPY).toBe(palette.info);
    expect(colors.EEM).toBe(palette.warnOrange);
  });

  it("hands the rest the next free hue in the order they were added", () => {
    const colors = lineColors(["SPY", "MDB", "XLK"], palette);
    expect(colors.MDB).toBe(palette.brandAccent);
    expect(colors.XLK).toBe(palette.candleUp);
    expect(new Set(Object.values(colors)).size).toBe(3);
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
      colors={lineColors(["SPY"], palette)}
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
