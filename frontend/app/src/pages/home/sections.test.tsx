/**
 * What the card's Portfolio and Your routines sections draw from a card.
 *
 * Portfolio is computed: each window's own move beside the index's, a move
 * the index could not report printed as "n/a" rather than a zero, and the
 * month drawn with the drawer's chart. A routine still being fetched says it
 * is being answered — never an empty slot — and one that is answered says it.
 *
 * Rendered to static markup with no catalog: a key prints as itself. The
 * chart reads computed styles off the document, which a node test does not
 * have — stubbed as `chart.test.tsx` does, so the palette falls back.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BookSection, Routines } from "./Daily";
import type { DailyBook, DailyRoutine } from "./types";

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

describe("the routines", () => {
  const asked = (over: Partial<DailyRoutine> = {}): DailyRoutine => ({
    id: "r1",
    text: "how is NVDA doing",
    answer: "",
    chart: null,
    ...over,
  });

  it("says a routine is being answered while the card is written", () => {
    const html = renderToStaticMarkup(<Routines routines={[asked()]} pending />);
    expect(html).toContain("how is NVDA doing");
    expect(html).toContain("home.daily_routine_pending");
    expect(html).toContain('role="status"');
  });

  it("prints the answer and its chart once there is one", () => {
    const html = renderToStaticMarkup(
      <Routines
        routines={[
          asked({
            answer: "NVDA at 182.50 USD",
            chart: {
              window: "1m",
              rebased: false,
              series: [{ ...line, symbol: "NVDA" }],
            },
          }),
        ]}
        pending={false}
      />,
    );
    expect(html).toContain("NVDA at 182.50 USD");
    expect(html).not.toContain("home.daily_routine_pending");
    expect(html).toContain("ag-a2ui-chart");
  });
});
