/**
 * What the card's Portfolio and brief sections draw from a card.
 *
 * Portfolio is computed: each window's own move beside the index's, a move
 * the index could not report printed as "n/a" rather than a zero, and the
 * month drawn with the drawer's chart. A brief section draws the chart its
 * figures came with, and nothing when they came with none.
 *
 * Rendered to static markup with no catalog: a key prints as itself. The
 * chart reads computed styles off the document, which a node test does not
 * have — stubbed as `chart.test.tsx` does, so the palette falls back.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BookSection, SectionChart } from "./Daily";
import type { DailyBook, DailySection } from "./types";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
  vi.stubGlobal("document", { documentElement: {} });
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
});
afterEach(() => vi.unstubAllGlobals());

const line = {
  symbol: "@BOOK",
  currency: "EUR",
  dates: ["2026-09-01", "2026-09-29"],
  values: [100, 101.2],
  label: "Your portfolio",
  index: true,
};

const book: DailyBook = {
  index: "S&P 500",
  currency: "EUR",
  rows: [
    { window: "day", pct: 0.8, amount: 120, index_pct: 0.3 },
    { window: "month", pct: -2, amount: -300, index_pct: null },
  ],
  chart: [line],
};

describe("the Portfolio section", () => {
  const draw = () => renderToStaticMarkup(<BookSection book={book} />);

  it("sets each window's move beside the index's", () => {
    const html = draw();
    expect(html).toContain("home.daily_book_day");
    expect(html).toContain("home.daily_book_month");
    expect(html).toContain("S&amp;P 500");
    expect(html).toContain("+0.80%");
    expect(html).toContain("+0.30%");
    expect(html).toContain("-2.00%");
  });

  it("prints a move the index could not report as n/a, not a zero", () => {
    const html = draw();
    expect(html).toContain("home.na");
    expect(html).not.toContain("+0.00%");
  });

  it("tones a move by its sign", () => {
    const html = draw();
    expect(html).toMatch(/hm-an-up">\+0\.80%/);
    expect(html).toMatch(/hm-an-down">-2\.00%/);
  });

  it("draws the month with the drawer's chart", () => {
    expect(draw()).toContain("ag-a2ui-chart");
  });

  it("draws no chart when there is none", () => {
    const bare = renderToStaticMarkup(<BookSection book={{ ...book, chart: [] }} />);
    expect(bare).not.toContain("ag-a2ui-chart");
  });
});

describe("a brief section's chart", () => {
  const section = (over: Partial<DailySection> = {}): DailySection => ({
    title: "NVDA",
    asks: [1],
    lines: [],
    chart: null,
    ...over,
  });

  it("draws nothing when the figures came without one", () => {
    expect(renderToStaticMarkup(<SectionChart section={section()} />)).toBe("");
    const empty = section({ chart: { window: "1m", rebased: false, series: [] } });
    expect(renderToStaticMarkup(<SectionChart section={empty} />)).toBe("");
  });

  it("draws the series it came with", () => {
    const html = renderToStaticMarkup(
      <SectionChart
        section={section({
          chart: {
            window: "1m",
            rebased: false,
            series: [{ ...line, symbol: "NVDA" }],
          },
        })}
      />,
    );
    expect(html).toContain("ag-a2ui-chart");
  });
});
