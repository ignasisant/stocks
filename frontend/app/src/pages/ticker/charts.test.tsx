/**
 * The non-price charts draw at the width they have, and read as a phone's
 * where the card is narrow: the axis labels move inside the plot and the
 * gutter goes. With no layout a render sees the 760 fallback.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FinancialsChart, InsiderFlow, ValuationChart } from "./Charts";
import { InsidersSection } from "./Sections";
import type { Financials, Insiders, Valuation } from "./types";

// The palette reads CSS tokens off the document; with none, each is "".
const dom = (width?: number) => {
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
  vi.stubGlobal("document", {
    documentElement: {},
    querySelector: () =>
      width === undefined ? null : { getBoundingClientRect: () => ({ width }) },
  });
};

afterEach(() => vi.unstubAllGlobals());

const financials: Financials = {
  ticker: "X",
  currency: "USD",
  annual: ["2021", "2022", "2023", "2024"].map((year, i) => ({
    year,
    revenue: 100 + i * 10,
    net_income: 10 + i,
    eps: 1 + i / 10,
  })),
  quarterly_eps: ["Q1", "Q2", "Q3", "Q4"].map((period, i) => ({
    period,
    eps: 0.5 + i / 10,
  })),
  projection: [
    {
      period: "2025E",
      revenue: 150,
      revenue_low: 140,
      revenue_high: 160,
      eps: 1.6,
      eps_low: 1.5,
      eps_high: 1.7,
      revenue_extrapolated: false,
      eps_extrapolated: false,
    },
  ],
  estimate_currency: "USD",
};

const valuation: Valuation = {
  ticker: "X",
  source: "edgar",
  current: 20,
  current_verdict: null,
  current_tone: null,
  dates: Array.from(
    { length: 40 },
    (_, i) => `2026-${String((i % 9) + 1).padStart(2, "0")}-01`,
  ).sort(),
  pe: Array.from({ length: 40 }, (_, i) => 15 + (i % 7)),
  windows: [
    {
      window: "5y",
      days: 3650,
      mean: 18,
      median: 18,
      low: 15,
      high: 21,
      percentile: 50,
      premium: 0.1,
    },
  ],
};

const insiders: Insiders = {
  ticker: "X",
  source: "sec",
  summary: null,
  sec_filer: true,
  trades: ["2026-01", "2026-02", "2026-03"].map((month, i) => ({
    date: `${month}-10`,
    insider: "A",
    role: "CEO",
    code: "P",
    label: "Purchase",
    shares: 10,
    price: 10,
    value: i % 2 ? -1000 : 2000,
    is_open_market: true,
    currency: "USD",
  })),
};

const render = () => [
  renderToStaticMarkup(<FinancialsChart data={financials} />),
  renderToStaticMarkup(<FinancialsChart data={{ ...financials, annual: [] }} />),
  renderToStaticMarkup(<ValuationChart data={valuation} fundamentalPe={20} />),
  renderToStaticMarkup(<InsiderFlow insiders={insiders} />),
];

describe("results, P/E and insider charts", () => {
  it("draw at the fallback width with the gutter labels", () => {
    dom();
    for (const html of render()) {
      expect(html).toContain('viewBox="0 0 760 ');
      expect(html).not.toContain("tk-grid-in");
    }
  });

  it("put the axis inside the plot on a phone", () => {
    dom(380);
    for (const html of render()) expect(html).toContain("tk-grid-in");
  });
});

describe("insider card", () => {
  it("keeps the trade table behind its button until asked", () => {
    dom();
    const html = renderToStaticMarkup(<InsidersSection insiders={insiders} />);
    expect(html).toContain("tk-show-more");
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("tk-table");
    expect(html).not.toContain("tk-stack-card");
  });
});
