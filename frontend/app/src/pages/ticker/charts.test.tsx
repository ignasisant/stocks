/**
 * The non-price charts draw at the width they have, and read as a phone's
 * where the card is narrow: the axis labels move inside the plot and the
 * gutter goes. With no layout a render sees the 760 fallback.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FinancialsChart, InsiderFlow, ValuationChart } from "./Charts";
import { InsidersSection } from "./Sections";
import type { Financials, Insiders, Trade, Valuation } from "./types";

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

// One Spanish string, so a label the API sends in English shows whether it
// was looked up; every other key renders as itself, as with no catalog.
vi.mock("../../shell/i18n", async (original) => ({
  ...(await original<typeof import("../../shell/i18n")>()),
  useT: () => (key: string) =>
    ({ "ticker.verdict_very_expensive": "Muy cara" })[key] ?? key,
}));

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

describe("P/E chart verdict", () => {
  it("names the band in the reader's language, not the API's English", () => {
    dom();
    const html = renderToStaticMarkup(
      <ValuationChart
        data={{ ...valuation, current_verdict: "very expensive", current_tone: "red" }}
        fundamentalPe={20}
      />,
    );
    expect(html).toContain(">Muy cara<");
  });
});

describe("P/E chart fills", () => {
  const lossy: Valuation = {
    ...valuation,
    pe: valuation.pe.map((value, i) => (i >= 30 ? null : value)),
  };
  const draw = (trades: Trade[]) =>
    renderToStaticMarkup(
      <ValuationChart data={lossy} fundamentalPe={20} trades={trades} />,
    );

  it("marks buys and sells on the line, each with its own triangle", () => {
    dom();
    const html = draw([
      { date: "2026-02-01", action: "buy", price: 10, quantity: 1 },
      { date: "2026-03-01", action: "sell", price: 12, quantity: 1 },
    ]);
    expect(html).toContain("tk-swatch-up");
    expect(html).toContain("tk-swatch-down");
  });

  it("leaves out a fill with no multiple to sit on", () => {
    dom();
    // Past the window's last P/E: the stretch is loss-making, so nothing to mark.
    const html = draw([{ date: "2026-09-01", action: "buy", price: 10, quantity: 1 }]);
    expect(html).not.toContain("tk-swatch-up");
    expect(html).not.toContain("tk-legend");
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
