/**
 * The analysts card says "too few" in words, keeps the median beside the mean,
 * and only calls a revision trend when both fiscal years agree.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AnalystsSection } from "./Analysts";
import type { Analysts, EpsRevisionRow } from "./types";

const revision = (period: string, change_30d: number | null): EpsRevisionRow => ({
  period,
  current: 8.8,
  change_7d: 0,
  change_30d,
  change_90d: 0.01,
  up_7d: 1,
  up_30d: 3,
  down_7d: 0,
  down_30d: 1,
});

const covered: Analysts = {
  ticker: "AAPL",
  currency: "USD",
  price: 100,
  analysts: 20,
  covered: true,
  min_coverage: 3,
  rating: "buy",
  rating_mean: 2.1,
  months: [
    {
      month: "2026-09",
      strong_buy: 5,
      buy: 10,
      hold: 4,
      sell: 1,
      strong_sell: 0,
      total: 20,
      mean: 2.05,
    },
  ],
  targets: {
    low: 80,
    median: 110,
    mean: 120,
    high: 160,
    upside_mean: 0.2,
    upside_median: 0.1,
    dispersion: 0.67,
  },
  revisions: [revision("0y", 0.02), revision("+1y", 0.015)],
};

const render = (data: Analysts) =>
  renderToStaticMarkup(<AnalystsSection data={data} />);

describe("AnalystsSection", () => {
  it("draws the targets with their upside and the monthly split", () => {
    const html = render(covered);
    expect(html).toContain("$110.00");
    expect(html).toContain("+10.0%");
    expect(html).toContain("$120.00");
    expect(html).toContain("+20.0%");
    expect(html).toContain("tk-ratings-strong_buy");
    expect(html).toContain("ticker.analysts_raising");
    expect(html).not.toContain("ticker.analysts_wide");
  });

  it("says too few analysts in words instead of drawing a split", () => {
    const html = render({ ...covered, analysts: 2, covered: false });
    expect(html).toContain("ticker.analysts_thin");
    expect(html).not.toContain("tk-ratings-bar");
  });

  it("says nobody covers the name when nobody does", () => {
    const html = render({
      ...covered,
      analysts: 0,
      covered: false,
      targets: null,
      months: [],
    });
    expect(html).toContain("ticker.analysts_none");
  });

  it("calls no trend when the two fiscal years disagree", () => {
    const html = render({
      ...covered,
      revisions: [revision("0y", 0.02), revision("+1y", -0.02)],
    });
    expect(html).not.toContain("ticker.analysts_raising");
    expect(html).not.toContain("ticker.analysts_cutting");
  });

  it("flags a target range wider than the mean target", () => {
    const html = render({
      ...covered,
      targets: { ...covered.targets!, dispersion: 1.2 },
    });
    expect(html).toContain("ticker.analysts_wide");
  });

  it("prints a drift too small to show as a neutral 0.0%", () => {
    const html = render({
      ...covered,
      revisions: [{ ...revision("0y", 0.02), change_7d: -0.00004 }],
    });
    expect(html).not.toContain("-0.0%");
    expect(html).toContain("+0.0%");
  });

  it("prints a pence-quoted target in pence, not pounds", () => {
    const html = render({ ...covered, currency: "GBp" });
    expect(html).toContain("110.00p");
    expect(html).not.toContain("£110");
  });
});
