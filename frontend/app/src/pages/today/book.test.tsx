/**
 * What Today's book tiles, book chart and brief sections draw from a card.
 *
 * The book is computed: each window's own move as the figure and the index's
 * under it, a move the index could not report printed as "n/a" rather than a
 * zero, and the month drawn with the drawer's chart. A brief section draws the chart its
 * figures came with, and nothing when they came with none. A list of wire
 * rows under All shows its first few and counts the rest.
 *
 * Rendered to static markup with no catalog: a key prints as itself. The
 * chart reads computed styles off the document, which a node test does not
 * have — stubbed as `chart.test.tsx` does, so the palette falls back.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BookChart, BookKpis, IndexKpis, SectionChart } from "./Book";
import { Rows } from "./Section";
import type { DailyBook, DailySection } from "../home/types";
import type { TodayRow } from "./types";

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

describe("the book tiles", () => {
  const draw = () => renderToStaticMarkup(<BookKpis book={book} />);

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
    expect(html).toMatch(/ag-tone-up">\+0\.80%/);
    expect(html).toMatch(/ag-tone-down">-2\.00%/);
  });
});

describe("the index tiles, for a guest", () => {
  it("prints the index alone, an unknown window as n/a", () => {
    const html = renderToStaticMarkup(
      <IndexKpis index={{ name: "S&P 500", day: 0.4, week: null, month: -1.5 }} />,
    );
    expect(html).toContain("+0.40%");
    expect(html).toContain("-1.50%");
    expect(html).toContain("home.na");
    expect(html).toContain("S&amp;P 500");
  });
});

describe("the book chart", () => {
  it("draws the month with the drawer's chart", () => {
    expect(renderToStaticMarkup(<BookChart book={book} />)).toContain("ag-a2ui-chart");
  });

  it("draws no chart when there is none", () => {
    expect(renderToStaticMarkup(<BookChart book={{ ...book, chart: [] }} />)).toBe("");
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

describe("wire rows", () => {
  const row = (n: number): TodayRow => ({
    key: `n${n}`,
    kind: "news",
    line: `Headline ${n}`,
    tickers: ["MSFT"],
    source: "yahoo",
    url: "https://example.com/a",
    date: "2026-10-13",
    data: {},
  });
  const rows = [1, 2, 3, 4, 5, 6, 7].map(row);
  const more = () => {};

  it("shows the first few under All and counts the rest", () => {
    const html = renderToStaticMarkup(<Rows rows={rows} limit={4} onMore={more} />);
    expect(html).toContain("Headline 4");
    expect(html).not.toContain("Headline 5");
    expect(html).toContain("today.more_rows");
  });

  it("never hides a single row behind a button", () => {
    const html = renderToStaticMarkup(
      <Rows rows={rows.slice(0, 5)} limit={4} onMore={more} />,
    );
    expect(html).toContain("Headline 5");
    expect(html).not.toContain("today.more_rows");
  });

  it("makes the headline the link to its article", () => {
    const html = renderToStaticMarkup(<Rows rows={[row(1)]} />);
    expect(html).toMatch(
      /<a class="td-headlink" href="https:\/\/example.com\/a"[^>]*>Headline 1<\/a>/,
    );
  });
});
