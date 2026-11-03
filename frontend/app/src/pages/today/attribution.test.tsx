/**
 * What Today's "who moved the day" draws from a card's breakdown.
 *
 * Both sides with their figures in money and points, toned by sign; every
 * block, a sector by its name and a fund by its logo; the notes for a
 * repeated bar, a gap and the run against the index only when the card
 * carries them.
 *
 * Rendered to static markup with no catalog: a key prints as itself.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DayAttribution } from "./Attribution";
import type { DailyAttribution } from "../home/types";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

const data: DailyAttribution = {
  amount: 50,
  up: [{ ticker: "MSFT", amount: 100, pct: 2, pp: 0.67, weight_pct: 33.3 }],
  down: [{ ticker: "NVDA", amount: -60, pct: -1.96, pp: -0.4, weight_pct: 20 }],
  blocks: [
    {
      kind: "sector",
      label: "Technology",
      amount: 40,
      pp: 0.27,
      tickers: ["MSFT", "NVDA"],
    },
    { kind: "fund", label: "IUSN.DE", amount: 20, pp: 0.13, tickers: ["IUSN.DE"] },
    { kind: "sector", label: "Healthcare", amount: -10, pp: -0.07, tickers: ["UNH"] },
  ],
  gap: null,
  stale: [],
  explained: [],
  alpha: null,
};

const draw = (over: Partial<DailyAttribution> = {}) =>
  renderToStaticMarkup(
    <DayAttribution data={{ ...data, ...over }} currency="EUR" index="S&P 500" />,
  );

describe("who moved the day", () => {
  it("lists both sides in money, toned by sign", () => {
    const html = draw();
    expect(html).toContain("today.day_up");
    expect(html).toContain("today.day_down");
    expect(html).toMatch(/td-up">\+€100/);
    expect(html).toMatch(/td-down">-€60/);
    expect(html).toContain("MSFT");
    expect(html).toContain("NVDA");
  });

  it("names a fund block by its ticker and a sector by its name", () => {
    const html = draw();
    expect(html).toContain("today.day_blocks");
    expect(html).toContain("IUSN.DE");
    // No catalog: the sector falls back to Yahoo's spelling, not a key.
    expect(html).toContain("Technology");
    expect(html).not.toContain("sentiment.sector_technology");
  });

  it("leaves out a side with nothing on it", () => {
    const html = draw({ down: [] });
    expect(html).toContain("today.day_up");
    expect(html).not.toContain("today.day_down");
  });

  it("says the notes only when the card carries them", () => {
    const quiet = draw();
    expect(quiet).not.toContain("today.day_stale");
    expect(quiet).not.toContain("today.day_gap");
    expect(quiet).not.toContain("today.day_alpha");
    expect(quiet).not.toContain("today.day_explained");

    const html = draw({
      stale: ["UNH"],
      gap: 12,
      alpha: {
        sessions: [
          { date: "2026-10-30", book: 1, index: 0.5 },
          { date: "2026-11-02", book: -0.2, index: 0.1 },
        ],
        ahead: 1,
        excess_pp: 0.2,
      },
      explained: [
        {
          ticker: "MSFT",
          pct: -5,
          sigmas: 3.1,
          etf: "XLK",
          etf_pct: -4,
          verdict: "sector",
        },
      ],
    });
    expect(html).toContain("today.day_stale");
    expect(html).toContain("today.day_gap");
    expect(html).toContain("today.day_alpha");
    expect(html).toContain("today.day_explained");
    // Every ticker a note names is a logo and a link, the ETF included.
    expect(html).toMatch(/ag-tick[^>]*>[\s\S]*?UNH/);
    expect(html).toMatch(/ag-tick[^>]*>[\s\S]*?XLK/);
  });
});
